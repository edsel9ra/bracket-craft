"""B2 invalidations and real SQL/HTTP parity; no production live routers."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.realtime_policy import (
    classify_organization_event,
    build_private_invalidation,
    resolve_event_references,
)
from app.core.realtime_authorization import RealtimeAuthorizer
from app.core.realtime_policy import Principal, SocketRecipient, Decision
from app.modules.matches.live_service import LiveMatchService
from test_match_live_db import (
    live_service_db as live_service_db,
    command,
    goal,
    MATCH,
    ORG,
    USER,
    MEMBER,
)
from test_migration_031 import TOURNAMENT
from test_migration_056 import SEGMENT_FIRST


def envelope(**payload):
    return dict(
        event_id=str(uuid4()),
        organization_id=ORG,
        event_type="MATCH_LIVE_UPDATED",
        payload=dict(
            scope="organization", match_id=MATCH, tournament_id=TOURNAMENT, **payload
        ),
    )


def test_catalog_live_organization_without_version_and_minimal_wire():
    event = classify_organization_event(envelope())
    assert event is not None and event.rule.permission == "VIEW_MATCH_LIVE_DRAFT"
    assert not event.rule.version_read and event.rule.requires_official
    payload = build_private_invalidation(
        event.event_id, resolve_event_references(event.rule, event.envelope["payload"])
    )
    assert set(payload) == {"event_id", "match_id", "tournament_id"}


@pytest.mark.parametrize(
    "extra",
    [
        {"version_id": str(uuid4())},
        {"events": []},
        {"revision": 1},
        {"actor": str(uuid4())},
    ],
)
def test_catalog_rejects_unrelated_or_private_details(extra):
    assert classify_organization_event(envelope(**extra)) is None


@pytest.mark.parametrize(
    "event_type",
    [
        "MATCH_LIVE_PUBLIC_UPDATED",
        "SANCTION_CASE_NOTICE_INTERNAL",
        "SANCTION_CASE_NOTICE_EMAIL",
    ],
)
def test_catalog_never_routes_public_or_f9_as_live_private(event_type):
    data = envelope()
    data["event_type"] = event_type
    assert classify_organization_event(data) is None


async def live_outbox(f):
    return await f.admin.fetch(
        "SELECT id,event_type,payload FROM outbox_events WHERE event_type LIKE 'MATCH_LIVE_%' ORDER BY created_at,id"
    )


async def test_outbox_accepted_retry_rejection_card_and_goal(live_service_db):
    f = live_service_db
    start = command("start_clock", segment_id=SEGMENT_FIRST)
    await f.call("execute", start)
    rows = await live_outbox(f)
    assert {r["event_type"] for r in rows} == {
        "MATCH_LIVE_UPDATED",
        "MATCH_LIVE_PUBLIC_UPDATED",
    }
    first = rows
    await f.call("execute", start)
    assert await live_outbox(f) == first
    card = goal()
    card["event_type"] = "yellow_card"
    await f.call("execute", command("add_event", 1, event=card))
    rows = await live_outbox(f)
    assert (
        len(rows) == 3
        and sum(r["event_type"] == "MATCH_LIVE_PUBLIC_UPDATED" for r in rows) == 1
    )
    await f.call("execute", command("add_event", 2, event=goal()))
    rows = await live_outbox(f)
    assert len(rows) == 5
    for row in rows:
        payload = json.loads(row["payload"])
        assert set(payload) == (
            {"scope", "match_id", "tournament_id"}
            if row["event_type"] == "MATCH_LIVE_UPDATED"
            else {"match_id", "tournament_id"}
        )
    with pytest.raises(Exception):
        await f.call("execute", command("pause_clock", 0))
    assert await live_outbox(f) == rows


async def test_outbox_rollback_on_notice_failure(live_service_db, monkeypatch):
    import app.modules.matches.live_notices as notices

    f = live_service_db
    original = notices.enqueue_outbox

    async def fail_public(db, org, event, payload, **kwargs):
        if event == "MATCH_LIVE_PUBLIC_UPDATED":
            raise RuntimeError("public notice failure")
        return await original(db, org, event, payload, **kwargs)

    monkeypatch.setattr(notices, "enqueue_outbox", fail_public)
    with pytest.raises(RuntimeError):
        await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    assert await live_outbox(f) == []
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 0


@pytest.mark.parametrize("live_service_db", [{"extra_match": True}], indirect=True)
@pytest.mark.parametrize(
    "case",
    [
        "view",
        "operate",
        "both",
        "none",
        "assigned",
        "unassigned",
        "wrong_assignment",
        "multirole",
        "revoked",
        "inactive_member",
        "inactive_user",
        "inactive_org",
        "platform",
        "other_tenant",
    ],
)
async def test_http_sql_parity(live_service_db, case):
    f = live_service_db
    permissions = (
        ["VIEW_MATCH_LIVE_DRAFT"]
        if case not in {"operate", "none", "platform"}
        else (["OPERATE_MATCH_LIVE"] if case == "operate" else [])
    )
    if case == "both":
        permissions.append("OPERATE_MATCH_LIVE")
    await f.permissions(permissions)
    if case in {"assigned", "unassigned", "wrong_assignment"}:
        await f.admin.execute(
            "UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='referee') WHERE organization_id=$1",
            ORG,
        )
        if case != "unassigned":
            target = (
                MATCH if case == "assigned" else "31000000-0000-4000-8000-000000000053"
            )
            await f.admin.execute(
                "INSERT INTO match_officials(organization_id,match_id,organization_user_id,official_role) VALUES ($1,$2,$3,'main_referee')",
                ORG,
                target,
                MEMBER,
            )
    if case == "multirole":
        await f.admin.execute(
            "INSERT INTO roles(organization_id,role_definition_id,name,permissions) SELECT $1,id,'Empty observer','[]' FROM role_definitions WHERE code='observer'",
            ORG,
        )
        await f.admin.execute(
            "INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) SELECT $1,$2,id FROM roles WHERE name='Empty observer'",
            ORG,
            MEMBER,
        )
    if case == "revoked":
        await f.admin.execute(
            "UPDATE user_sessions SET revoked_at=now() WHERE id=$1", f.session_id
        )
    if case == "inactive_member":
        await f.admin.execute(
            "UPDATE organization_users SET is_active=FALSE WHERE id=$1", MEMBER
        )
    if case == "inactive_user":
        await f.admin.execute("UPDATE users SET is_active=FALSE WHERE id=$1", USER)
    if case == "inactive_org":
        await f.admin.execute(
            "UPDATE organizations SET is_active=FALSE WHERE id=$1", ORG
        )
    if case == "platform":
        await f.admin.execute(
            "INSERT INTO platform_admins(user_id,role_code) VALUES ($1,'platform_admin')",
            USER,
        )
    data = envelope()
    if case == "other_tenant":
        data["payload"]["match_id"] = MATCH.replace("31000000", "32000000")
    event = classify_organization_event(data)
    assert event is not None
    now = datetime.now(timezone.utc)
    principal = Principal(
        UUID(ORG),
        UUID(USER),
        f.session_id,
        (SocketRecipient("socket", "generation", now + timedelta(minutes=10)),),
    )
    authorizer = RealtimeAuthorizer(lambda: AsyncSession(f.engine), lambda: now)
    decision = (await authorizer.evaluate_batch(event, [principal]))[0].decision
    app = FastAPI()

    @app.get("/live")
    async def read():
        async with AsyncSession(f.engine) as db:
            return await LiveMatchService(db).snapshot(
                f.context, UUID(data["payload"]["match_id"]), f.session_id
            )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/live")
    expected = case in {"view", "both", "assigned", "multirole"}
    assert (response.status_code == 200) is expected
    assert decision == (Decision.ALLOW if expected else Decision.DENY)
