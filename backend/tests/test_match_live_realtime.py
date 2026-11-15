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


# ---------------------------------------------------------------------------
# B3 T50: el aviso público nuevo solo se emite tras revalidar visibilidad actual
# ---------------------------------------------------------------------------

LIVE_PUBLIC = "MATCH_LIVE_PUBLIC_UPDATED"
FOREIGN = "32000000-0000-4000-8000-"


def public_envelope(event_type=LIVE_PUBLIC, **payload):
    return {
        "event_id": str(uuid4()),
        "organization_id": ORG,
        "event_type": event_type,
        "payload": {"match_id": MATCH, "tournament_id": TOURNAMENT, **payload},
    }


class RecordingDelivery:
    def __init__(self):
        self.envelopes = []

    async def deliver(self, envelope):
        self.envelopes.append(envelope)


def dispatch_harness(fixture, monkeypatch):
    from app import main

    calls = []

    async def emit(name, payload, **kwargs):
        calls.append((name, payload, kwargs))

    delivery = RecordingDelivery()
    monkeypatch.setattr(
        main, "SessionFactory", lambda: AsyncSession(fixture.engine)
    )
    monkeypatch.setattr(main.sio, "emit", emit)
    monkeypatch.setattr(main, "private_delivery", delivery)
    return main, calls, delivery


async def emit_envelope(main, data):
    await main.emit_domain_event(main.parse_envelope({"event": json.dumps(data)}))


async def start_clock(f):
    """Materializa ``match_live_state``: el partido entra en la proyección."""
    await f.call(
        "execute", command("start_clock", segment_id=SEGMENT_FIRST)
    )


async def test_public_dispatch_emits_after_current_visibility_revalidation(
    live_service_db, monkeypatch
):
    await start_clock(live_service_db)
    main, calls, delivery = dispatch_harness(live_service_db, monkeypatch)
    data = public_envelope()
    await emit_envelope(main, data)
    assert calls == [
        (
            LIVE_PUBLIC,
            {
                "event_id": data["event_id"],
                "match_id": MATCH,
                "tournament_id": TOURNAMENT,
            },
            {"room": f"tournament:{TOURNAMENT}"},
        )
    ]
    assert len(delivery.envelopes) == 1


async def test_public_dispatch_tournament_hidden_after_enqueue_does_not_emit(
    live_service_db, monkeypatch
):
    await start_clock(live_service_db)
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await live_service_db.admin.execute(
        "UPDATE tournaments SET status='draft' WHERE id=$1", TOURNAMENT
    )
    await emit_envelope(main, public_envelope())
    assert calls == []


@pytest.mark.parametrize(
    "statement",
    [
        # Organización inactiva tras encolar: ya no es proyección autorizada.
        "UPDATE organizations SET is_active=FALSE WHERE id='" + ORG + "'",
        # Versión archivada tras encolar: sale de la selección publicada.
        "UPDATE tournament_versions SET status='archived' WHERE tournament_id='"
        + TOURNAMENT + "'",
    ],
    ids=["organization_inactive", "version_archived"],
)
async def test_public_dispatch_match_out_of_projection_does_not_emit(
    live_service_db, monkeypatch, statement
):
    await start_clock(live_service_db)
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await live_service_db.admin.execute(statement)
    await emit_envelope(main, public_envelope())
    assert calls == []


@pytest.mark.parametrize(
    "organization_id,match_id,tournament_id",
    [
        (FOREIGN + "000000000001", MATCH, TOURNAMENT),
        (ORG, FOREIGN + "000000000050", TOURNAMENT),
        (ORG, MATCH, FOREIGN + "000000000010"),
        (FOREIGN + "000000000001", FOREIGN + "000000000050", FOREIGN + "000000000010"),
    ],
    ids=["foreign_org", "foreign_match", "foreign_tournament", "all_foreign"],
)
async def test_public_dispatch_foreign_references_do_not_emit(
    live_service_db, monkeypatch, organization_id, match_id, tournament_id
):
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    data = public_envelope(match_id=match_id, tournament_id=tournament_id)
    data["organization_id"] = organization_id
    await emit_envelope(main, data)
    assert calls == []


@pytest.mark.parametrize(
    "event_type,extra",
    [
        # Nombre privado compartiendo identificadores: nunca sale al room público.
        ("MATCH_LIVE_UPDATED", {}),
        ("MATCH_LIVE_UPDATED", {"scope": "organization"}),
        # El nombre público no acepta ámbito organizativo ni claves extra.
        (LIVE_PUBLIC, {"scope": "organization"}),
        (LIVE_PUBLIC, {"home_score": 3}),
        (LIVE_PUBLIC, {"match_id": None}),
        (LIVE_PUBLIC, {"match_id": "no-uuid"}),
        (LIVE_PUBLIC, {"tournament_id": "no-uuid"}),
    ],
    ids=[
        "private_name",
        "private_name_scoped",
        "public_scoped",
        "extra_key",
        "null_match",
        "bad_match",
        "bad_tournament",
    ],
)
async def test_public_dispatch_rejects_private_or_malformed_wires(
    live_service_db, monkeypatch, event_type, extra
):
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await emit_envelope(main, public_envelope(event_type=event_type, **extra))
    assert calls == []


async def test_public_dispatch_query_failure_does_not_emit(
    live_service_db, monkeypatch
):
    from app import main

    calls = []

    async def emit(name, payload, **kwargs):
        calls.append((name, payload, kwargs))

    def broken_factory():
        raise RuntimeError("consulta de visibilidad caída")

    monkeypatch.setattr(main, "SessionFactory", broken_factory)
    monkeypatch.setattr(main.sio, "emit", emit)
    monkeypatch.setattr(main, "private_delivery", RecordingDelivery())
    with pytest.raises(RuntimeError):
        await emit_envelope(main, public_envelope())
    assert calls == []


async def test_public_dispatch_preserves_previous_public_events(
    live_service_db, monkeypatch
):
    main, calls, _ = dispatch_harness(live_service_db, monkeypatch)
    await live_service_db.admin.execute(
        "UPDATE tournaments SET status='draft' WHERE id=$1", TOURNAMENT
    )
    for name in ("MATCH_UPDATED", "MATCH_CLOSED", "STANDINGS_UPDATED"):
        await emit_envelope(main, public_envelope(event_type=name))
    assert [c[0] for c in calls] == ["MATCH_UPDATED", "MATCH_CLOSED", "STANDINGS_UPDATED"]
    assert all(c[2] == {"room": f"tournament:{TOURNAMENT}"} for c in calls)


async def test_public_dispatch_draft_never_broadcasts_to_organization_room(
    live_service_db, monkeypatch
):
    await start_clock(live_service_db)
    main, calls, delivery = dispatch_harness(live_service_db, monkeypatch)
    await emit_envelope(main, public_envelope())
    await emit_envelope(
        main, public_envelope(event_type="MATCH_LIVE_UPDATED", scope="organization")
    )
    rooms = [c[2].get("room", "") for c in calls]
    assert all(not room.startswith("organization:") for room in rooms)
    # Solo el aviso privado llega a la entrega organizativa autorizada; el
    # público pasa por el filtro pero el catálogo lo descarta.
    assert len(delivery.envelopes) == 2
