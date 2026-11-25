"""Bandeja y preferencias de avisos contra PostgreSQL (spec 046, T5; opt-in ``RUN_DATABASE_TESTS=1``)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.workers import outbox
from db_helpers import create_tenant_owner
from migration_helpers import connect
from test_match_assists_db import close, committed_application, goal_and_red_report, seeded_match
from test_organization_audit_routes import grant
from test_outbox_worker import FakeRedis
from test_request_schema_strictness import walk_routes

URL = "/api/v1/notifications"
PREFERENCES = "/api/v1/notification-preferences"
ITEM_KEYS = {
    "id", "type", "created_at", "read_at", "tournament_id", "tournament_name", "match_id",
    "home_team_name", "away_team_name", "match_count", "sanction",
}
TYPES = ("match_scheduled", "result_confirmed", "walkover_declared", "sanction_generated")
DEFAULTS = [{"type": kind, "channel": channel, "enabled": channel == "inbox"}
            for kind in TYPES for channel in ("inbox", "email")]


@dataclass
class Inbox:
    client: AsyncClient
    admin: object
    owner: AuthContext
    colleague: AuthContext
    stranger: AuthContext
    owner_elsewhere: AuthContext
    match: object
    context: AuthContext | None = None


async def add_member(admin, organization, user, code):
    member = await admin.fetchval(
        "INSERT INTO organization_users (organization_id,user_id,is_active) VALUES ($1,$2,TRUE) RETURNING id",
        organization, user)
    await grant(admin, str(organization), str(member), code)
    return AuthContext(user, organization, member)


@pytest.fixture
async def inbox(database_admin_url, monkeypatch):
    async with committed_application(database_admin_url) as engine:
        owner, match = await seeded_match(engine)
        admin = await connect(database_admin_url, engine.url.database)
        try:
            colleague_user = await admin.fetchval("""INSERT INTO users (email,password_hash,full_name)
                VALUES ('colega-046@example.test','hash','Cora Colega') RETURNING id""")
            colleague = await add_member(admin, owner.organization_id, colleague_user, "operator")
            # La colega no quiere el resultado en la bandeja: solo recibe las sanciones.
            await admin.execute("""INSERT INTO notification_preferences
                (organization_id,user_id,notification_type,channel,enabled)
                VALUES ($1,$2,'result_confirmed','inbox',FALSE)""", owner.organization_id, colleague_user)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                tenant = await create_tenant_owner(session, full_name="Otra organización 046")
                await session.commit()
            stranger = AuthContext(tenant.user_id, tenant.organization_id, tenant.member_id)
            owner_elsewhere = await add_member(admin, tenant.organization_id, owner.user_id, "operator")
            await close(engine, owner, match.match_id, goal_and_red_report(match))

            @asynccontextmanager
            async def factory():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    yield session

            monkeypatch.setattr(outbox, "SessionFactory", factory)
            await outbox.process_once(FakeRedis())

            async def database():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    yield session

            state = Inbox(None, admin, owner, colleague, stranger, owner_elsewhere, match)
            state.context = owner

            async def auth_context():
                return state.context

            api.dependency_overrides[get_db] = database
            api.dependency_overrides[get_auth_context] = auth_context
            try:
                async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
                    state.client = client
                    yield state
            finally:
                api.dependency_overrides.clear()
        finally:
            await admin.close()


async def notice_ids(admin, kind):
    return [str(row["id"]) for row in await admin.fetch(
        "SELECT id FROM notifications WHERE notification_type = $1 ORDER BY id", kind)]


async def test_routes_are_registered():
    methods = {(path, method) for path, route in walk_routes(api.routes)
               if path.startswith((URL, PREFERENCES)) for method in route.methods}
    assert methods == {
        (URL, "GET"), (f"{URL}/{{notification_id}}/read", "POST"), (f"{URL}/read-all", "POST"),
        (PREFERENCES, "GET"), (PREFERENCES, "PUT"),
    }


async def test_the_inbox_lists_own_delivered_notices_newest_first(inbox):
    result = (await notice_ids(inbox.admin, "result_confirmed"))[0]
    sanctions = await notice_ids(inbox.admin, "sanction_generated")
    assert sanctions
    await inbox.admin.execute(
        "UPDATE notifications SET created_at = created_at - interval '1 hour' WHERE id = $1", result)
    response = await inbox.client.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "unread_count", "total", "limit", "offset"}
    assert (body["total"], body["unread_count"], body["limit"], body["offset"]) == (
        1 + len(sanctions), 1 + len(sanctions), 50, 0)
    assert [item["id"] for item in body["items"]] == [*sorted(sanctions, reverse=True), result]
    assert all(set(item) == ITEM_KEYS for item in body["items"])
    assert all(item["read_at"] is None for item in body["items"])
    last = body["items"][-1]
    assert (last["type"], last["match_id"], last["tournament_id"], last["sanction"]) == (
        "result_confirmed", str(inbox.match.match_id), str(inbox.match.tournament_id), None)
    assert last["tournament_name"] and last["home_team_name"] and last["away_team_name"]
    assert "example.test" not in response.text


async def test_the_sanction_names_the_player_only_in_the_inbox(inbox):
    player = await inbox.admin.fetchrow(
        "SELECT first_name, last_name FROM players WHERE id = $1", inbox.match.away_scorer_id)
    team = await inbox.admin.fetchval("SELECT name FROM teams WHERE id = $1", inbox.match.away_team_id)
    suspended = await inbox.admin.fetchval("SELECT matches_suspended FROM player_suspensions LIMIT 1")
    items = (await inbox.client.get(URL)).json()["items"]
    sanction = next(item for item in items if item["type"] == "sanction_generated")
    assert sanction["sanction"] == {
        "player_name": f"{player['first_name']} {player['last_name']}",
        "team_name": team,
        "matches_suspended": suspended,
    }
    stored = await inbox.admin.fetchrow("SELECT * FROM notifications WHERE id = $1", sanction["id"])
    assert player["last_name"] not in str(dict(stored))


async def test_the_sanction_detail_requires_view_sanction_cases(inbox):
    inbox.context = inbox.colleague
    response = await inbox.client.get(URL)
    sanctions = [item for item in response.json()["items"] if item["type"] == "sanction_generated"]
    assert sanctions and all(item["sanction"] is None for item in sanctions)
    assert all(item["match_id"] == str(inbox.match.match_id) for item in sanctions)
    player = await inbox.admin.fetchval("SELECT last_name FROM players WHERE id = $1", inbox.match.away_scorer_id)
    assert player not in response.text
    await grant(inbox.admin, str(inbox.colleague.organization_id), str(inbox.colleague.organization_user_id), "administrator")
    granted = (await inbox.client.get(URL)).json()["items"]
    assert all(item["sanction"] for item in granted if item["type"] == "sanction_generated")


async def test_pagination_and_bounds(inbox):
    full = (await inbox.client.get(URL)).json()
    page = (await inbox.client.get(URL, params={"limit": 1, "offset": 1})).json()
    assert [item["id"] for item in page["items"]] == [full["items"][1]["id"]]
    assert (page["total"], page["unread_count"]) == (full["total"], full["unread_count"])
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"unknown": 1}):
        assert (await inbox.client.get(URL, params=params)).status_code == 422


async def test_marking_as_read_is_own_idempotent_and_hides_foreign_ones(inbox):
    result = (await notice_ids(inbox.admin, "result_confirmed"))[0]
    before = (await inbox.client.get(URL)).json()["unread_count"]
    for _ in range(2):
        assert (await inbox.client.post(f"{URL}/{result}/read")).status_code == 204
    after = (await inbox.client.get(URL)).json()
    assert after["unread_count"] == before - 1
    assert next(i for i in after["items"] if i["id"] == result)["read_at"] is not None
    inbox.context = inbox.colleague
    colleague = (await inbox.client.get(URL)).json()
    assert result not in [item["id"] for item in colleague["items"]]
    assert colleague["unread_count"] == colleague["total"] > 0
    missing = await inbox.client.post(f"{URL}/{uuid4()}/read")
    foreign = await inbox.client.post(f"{URL}/{result}/read")
    assert (missing.status_code, foreign.status_code) == (404, 404)
    assert missing.json() == foreign.json()
    assert (await inbox.client.post(f"{URL}/not-a-uuid/read")).status_code == 422


async def test_read_all_only_touches_the_own_inbox(inbox):
    assert (await inbox.client.post(f"{URL}/read-all")).status_code == 204
    assert (await inbox.client.get(URL)).json()["unread_count"] == 0
    inbox.context = inbox.colleague
    colleague = (await inbox.client.get(URL)).json()
    assert colleague["unread_count"] == colleague["total"] > 0


async def test_other_organizations_see_and_mark_nothing(inbox):
    result = (await notice_ids(inbox.admin, "result_confirmed"))[0]
    for context in (inbox.stranger, inbox.owner_elsewhere):
        inbox.context = context
        body = (await inbox.client.get(URL)).json()
        assert (body["items"], body["total"], body["unread_count"]) == ([], 0, 0)
        assert (await inbox.client.post(f"{URL}/{result}/read")).status_code == 404
        assert (await inbox.client.post(f"{URL}/read-all")).status_code == 204
    inbox.context = inbox.owner
    assert (await inbox.client.get(URL)).json()["unread_count"] > 0


async def test_an_archived_tournament_keeps_its_notices(inbox):
    await inbox.admin.execute("UPDATE tournaments SET status = 'archived' WHERE id = $1",
                              inbox.match.tournament_id)
    assert (await inbox.client.get(URL)).json()["total"] > 0


async def test_preferences_default_and_save_exactly_every_pair(inbox):
    response = await inbox.client.get(PREFERENCES)
    assert response.status_code == 200
    assert response.json() == {"items": DEFAULTS}
    wanted = [{**item, "enabled": not item["enabled"]} if item["type"] == "sanction_generated" else item
              for item in DEFAULTS]
    saved = await inbox.client.put(PREFERENCES, json={"items": list(reversed(wanted))})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"items": wanted}
    assert (await inbox.client.get(PREFERENCES)).json() == {"items": wanted}
    rows = await inbox.admin.fetch(
        "SELECT user_id, organization_id FROM notification_preferences WHERE user_id = $1", inbox.owner.user_id)
    assert {(row["user_id"], row["organization_id"]) for row in rows} == {
        (inbox.owner.user_id, inbox.owner.organization_id)}


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown_type", "unknown_channel", "extra", "strict"])
async def test_incomplete_or_malformed_preferences_are_rejected_without_writing(inbox, change):
    items = [dict(item) for item in DEFAULTS]
    body: dict = {"items": items}
    if change == "missing":
        items.pop()
    elif change == "duplicate":
        items[-1] = dict(items[0])
    elif change == "unknown_type":
        items[0]["type"] = "webhook_sent"
    elif change == "unknown_channel":
        items[0]["channel"] = "webhook"
    elif change == "extra":
        body["user_id"] = str(inbox.colleague.user_id)
    else:
        items[0]["enabled"] = "yes"
    assert (await inbox.client.put(PREFERENCES, json=body)).status_code == 422
    assert await inbox.admin.fetchval(
        "SELECT count(*) FROM notification_preferences WHERE user_id = $1", inbox.owner.user_id) == 0


async def test_preferences_are_per_member_and_per_organization(inbox):
    enabled = [{**item, "enabled": True} for item in DEFAULTS]
    assert (await inbox.client.put(PREFERENCES, json={"items": enabled})).status_code == 200
    inbox.context = inbox.owner_elsewhere
    assert (await inbox.client.get(PREFERENCES)).json() == {"items": DEFAULTS}
    inbox.context = inbox.colleague
    colleague = (await inbox.client.get(PREFERENCES)).json()["items"]
    assert {"type": "result_confirmed", "channel": "inbox", "enabled": False} in colleague
    assert {"type": "match_scheduled", "channel": "email", "enabled": False} in colleague
