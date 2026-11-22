"""Consulta de la auditoría organizacional contra PostgreSQL (spec 041, T3; opt-in ``RUN_DATABASE_TESTS=1``)."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from db_helpers import application_database_url
from migration_helpers import throwaway_database
from test_request_schema_strictness import walk_routes
from test_migration_031 import MATCH, MEMBER, ORG, SEED_SQL, TEAM_HOME, USER

OTHER = {name: value.replace("31000000", "32000000") for name, value in
         {"ORG": ORG, "USER": USER, "MEMBER": MEMBER, "MATCH": MATCH}.items()}
VIEWER_USER = "31000000-0000-4000-8000-0000000000a1"
VIEWER = "31000000-0000-4000-8000-0000000000a2"
OUTSIDER_USER = "31000000-0000-4000-8000-0000000000a3"
URL = "/api/v1/organization-audit"
ITEM_KEYS = {"id", "performed_at", "action", "cataloged", "entity_type", "entity_id",
             "entity_available", "actor", "details"}


@dataclass
class Audit:
    client: AsyncClient
    admin: object
    context: AuthContext
    statements: list


async def grant(admin, organization, member, code):
    role = await admin.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,$2,system_permissions FROM role_definitions WHERE code=$3 RETURNING id""",
        organization, f"Rol {code} {member[-4:]}", code)
    await admin.execute("""INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id)
        VALUES ($1,$2,$3)""", organization, member, role)


async def entry(admin, action, *, at, organization=ORG, entity_type="matches", entity=MATCH,
                payload="{}", member=MEMBER, user=None):
    return str(await admin.fetchval("""INSERT INTO administrative_audit_logs
        (organization_id,entity_type,entity_id,action,payload,performed_by_member_id,performed_by_user_id,performed_at)
        VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8::text::timestamptz) RETURNING id""",
        organization, entity_type, entity, action, payload, member, user, at))


@pytest.fixture
async def audit(database_admin_url):
    async with throwaway_database(database_admin_url, last=64) as admin:
        await admin.execute(SEED_SQL)
        await admin.execute(SEED_SQL.replace("31000000", "32000000").replace("migration-031", "audit-ajena"))
        await admin.execute("""INSERT INTO users (id,email,password_hash,full_name) VALUES
            ($1,'viewer-041@example.test','hash','Vera Visor'),($2,'outsider-041@example.test','hash','Ajeno')""",
            VIEWER_USER, OUTSIDER_USER)
        await admin.execute("INSERT INTO organization_users (id,organization_id,user_id,is_active) VALUES ($1,$2,$3,TRUE)",
                            VIEWER, ORG, VIEWER_USER)
        await grant(admin, ORG, MEMBER, "owner")
        await grant(admin, ORG, VIEWER, "viewer")
        await grant(admin, OTHER["ORG"], OTHER["MEMBER"], "owner")
        name = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(make_url(application_database_url()).set(database=name))
        statements: list[str] = []
        event.listen(engine.sync_engine, "before_cursor_execute",
                     lambda *args: statements.append(args[2]))
        state = Audit(None, admin, AuthContext(UUID(USER), UUID(ORG), UUID(MEMBER)), statements)

        async def database():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

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
            await engine.dispose()


async def test_list_orders_projects_and_isolates(audit):
    old = await entry(audit.admin, "CHANGE_MEMBER_ROLE", at="2026-11-01T10:00:00Z", entity_type="organization_users",
                      entity=VIEWER, payload='{"role_code":"viewer","email":"x@example.test"}')
    same_time = sorted([await entry(audit.admin, "SET_MEMBER_ACTIVE", at="2026-11-02T10:00:00Z",
                                    entity_type="organization_users", entity=VIEWER, payload='{"is_active":false}')
                        for _ in range(2)], reverse=True)
    unknown = await entry(audit.admin, "FUTURE_ACTION", at="2026-11-03T10:00:00Z", payload='{"secret":"x"}')
    await entry(audit.admin, "CHANGE_MEMBER_ROLE", at="2026-11-04T10:00:00Z", organization=OTHER["ORG"],
                entity_type="organization_users", entity=OTHER["MEMBER"], member=OTHER["MEMBER"])
    response = await audit.client.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert (body["total"], body["limit"], body["offset"]) == (4, 50, 0)
    assert [item["id"] for item in body["items"]] == [unknown, *same_time, old]
    assert all(set(item) == ITEM_KEYS for item in body["items"])
    first, last = body["items"][0], body["items"][-1]
    assert (first["cataloged"], first["details"], first["entity_available"]) == (False, None, True)
    assert last["details"] == [{"key": "role_code", "value": "viewer"}]
    assert last["actor"] == {"kind": "member", "member_id": MEMBER, "name": "Migration Owner"}
    assert (last["entity_type"], last["entity_id"], last["entity_available"]) == ("organization_users", VIEWER, False)
    assert "example.test" not in response.text and "secret" not in response.text
    audit.context = AuthContext(UUID(OTHER["USER"]), UUID(OTHER["ORG"]), UUID(OTHER["MEMBER"]))
    foreign = (await audit.client.get(URL)).json()
    assert foreign["total"] == 1 and foreign["items"][0]["entity_id"] == OTHER["MEMBER"]


async def test_pagination_and_bounded_queries(audit):
    for day in range(1, 4):
        await entry(audit.admin, "MATCH_LIVE_COMMAND", at=f"2026-11-0{day}T10:00:00Z", payload='{"type":"goal"}')
    page = (await audit.client.get(f"{URL}?limit=2")).json()
    following = (await audit.client.get(f"{URL}?limit=2&offset=2")).json()
    assert (page["total"], len(page["items"]), len(following["items"])) == (3, 2, 1)
    assert following["items"][0]["performed_at"].startswith("2026-11-01")
    beyond = (await audit.client.get(f"{URL}?offset=10")).json()
    assert beyond == {"items": [], "total": 3, "limit": 50, "offset": 10}
    audit.statements.clear()
    await audit.client.get(URL)
    few = len(audit.statements)
    for day in range(10, 28):
        await entry(audit.admin, "ASSIGN_MATCH_OFFICIAL", at=f"2026-10-{day}T10:00:00Z",
                    payload=f'{{"organization_user_id":"{VIEWER}","official_role":"referee"}}')
    audit.statements.clear()
    body = (await audit.client.get(URL)).json()
    assert len(audit.statements) == few
    assert body["items"][-1]["details"] == [{"key": "member", "value": "Vera Visor"},
                                            {"key": "official_role", "value": "referee"}]


async def test_filters_combine_actions_actor_and_inclusive_dates(audit):
    first = await entry(audit.admin, "SAVE_MATCH_LINEUP", at="2026-11-01T00:00:00Z")
    second = await entry(audit.admin, "PUBLISH_MATCH_LINEUP", at="2026-11-02T12:00:00Z", member=VIEWER)
    third = await entry(audit.admin, "UNPUBLISH_MATCH_LINEUP", at="2026-11-03T23:59:59Z")

    async def ids(query):
        response = await audit.client.get(f"{URL}?{query}")
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    assert await ids("action=SAVE_MATCH_LINEUP&action=UNPUBLISH_MATCH_LINEUP") == [third, first]
    assert await ids(f"actor_member_id={VIEWER}") == [second]
    assert await ids("from=2026-11-01T00:00:00Z&to=2026-11-03T23:59:59Z") == [third, second, first]
    assert await ids("from=2026-11-02T00:00:00%2B00:00") == [third, second]
    assert await ids(f"action=PUBLISH_MATCH_LINEUP&actor_member_id={MEMBER}") == []
    assert await ids(f"actor_member_id={OTHER['MEMBER']}") == []
    assert await ids(f"actor_member_id={uuid4()}") == []


@pytest.mark.parametrize("query", [
    "action=UNKNOWN_ACTION", "action=", "from=2026-11-01T00:00:00", "from=ayer", "to=2026-13-01T00:00:00Z",
    "from=2026-11-02T00:00:00Z&to=2026-11-01T00:00:00Z", "limit=0", "limit=101", "offset=-1",
    "actor_member_id=bad", "extra=1",
])
async def test_invalid_filters_are_rejected(audit, query):
    audit.statements.clear()
    response = await audit.client.get(f"{URL}?{query}")
    assert response.status_code == 422, response.text
    assert not any("administrative_audit_logs" in sql for sql in audit.statements)


@pytest.mark.parametrize("path", ["", "/actors"])
async def test_permission_required_with_identical_403(audit, path):
    await entry(audit.admin, "CLOSE_MATCH_REPORT", at="2026-11-01T10:00:00Z")
    audit.context = AuthContext(UUID(VIEWER_USER), UUID(ORG), UUID(VIEWER))
    denied = await audit.client.get(f"{URL}{path}")
    audit.context = AuthContext(UUID(OUTSIDER_USER), UUID(ORG), UUID(f"{VIEWER[:-2]}ff"))
    stranger = await audit.client.get(f"{URL}{path}")
    assert denied.status_code == stranger.status_code == 403
    assert denied.json() == stranger.json()
    assert "CLOSE_MATCH_REPORT" not in denied.text


async def test_actor_resolution_by_member_user_or_platform(audit):
    by_user = await entry(audit.admin, "GRANT_SANCTION_AUTHORIZATION", at="2026-11-02T10:00:00Z",
                          entity_type="sanction_cases", entity=str(uuid4()), member=None, user=USER,
                          payload='{"authorization_id":"a","platform_admin_user_id":"p"}')
    platform = await entry(audit.admin, "DECIDE_SANCTION_CASE", at="2026-11-01T10:00:00Z",
                           entity_type="sanction_cases", entity=str(uuid4()), member=None, user=OUTSIDER_USER,
                           payload='{"decision":"annul"}')
    member_decision = await entry(audit.admin, "DECIDE_SANCTION_CASE", at="2026-10-31T10:00:00Z",
                                  entity_type="sanction_cases", entity=str(uuid4()), member=None, user=USER,
                                  payload='{"decision_id":"d","decision":"confirm"}')
    platform_decisions = [
        await entry(audit.admin, "DECIDE_SANCTION_CASE", at="2026-10-30T10:00:00Z", entity_type="sanction_cases",
                    entity=str(uuid4()), member=None, user=USER,
                    payload='{"decision_id":"d","authorization_id":"a","decision":"annul"}'),
        await entry(audit.admin, "DECIDE_MATCH_REPORT_RECTIFICATION", at="2026-10-29T10:00:00Z",
                    member=None, user=USER, payload='{"decision":"approve"}'),
    ]
    items = {item["id"]: item for item in (await audit.client.get(URL)).json()["items"]}
    assert items[member_decision]["actor"]["member_id"] == MEMBER
    assert all(items[entry_id]["actor"] == {"kind": "platform", "member_id": None, "name": None}
               for entry_id in platform_decisions)
    assert "Migration Owner" not in str([items[entry_id] for entry_id in platform_decisions])
    assert items[by_user]["actor"] == {"kind": "member", "member_id": MEMBER, "name": "Migration Owner"}
    assert items[by_user]["details"] == [] and items[by_user]["entity_available"] is False
    assert items[platform]["actor"] == {"kind": "platform", "member_id": None, "name": None}
    assert items[platform]["details"] == [{"key": "decision", "value": "annul"}]
    filtered = (await audit.client.get(f"{URL}?actor_member_id={MEMBER}")).json()
    assert [item["id"] for item in filtered["items"]] == [by_user, member_decision]


async def test_entity_availability(audit):
    match = await entry(audit.admin, "CLOSE_MATCH_REPORT", at="2026-11-04T10:00:00Z")
    gone = await entry(audit.admin, "CLOSE_MATCH_REPORT", at="2026-11-03T10:00:00Z", entity=str(uuid4()))
    foreign = await entry(audit.admin, "CLOSE_MATCH_REPORT", at="2026-11-02T10:00:00Z", entity=OTHER["MATCH"])
    team = await entry(audit.admin, "SET_TEAM_CREST", at="2026-11-01T10:00:00Z", entity_type="teams", entity=TEAM_HOME)
    items = {item["id"]: item["entity_available"] for item in (await audit.client.get(URL)).json()["items"]}
    assert items == {match: True, gone: False, foreign: False, team: False}


async def test_reading_does_not_write_and_routes_are_read_only(audit):
    await entry(audit.admin, "CLOSE_MATCH_REPORT", at="2026-11-01T10:00:00Z")
    before = await audit.admin.fetchval("SELECT count(*) FROM administrative_audit_logs")
    assert (await audit.client.get(URL)).status_code == 200
    assert (await audit.client.get(f"{URL}/actors")).status_code == 200
    assert await audit.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == before
    methods = {method for path, route in walk_routes(api.routes) if path.startswith(URL) for method in route.methods}
    assert methods == {"GET"}
    assert all(sql.lstrip().upper().startswith(("SELECT", "WITH", "BEGIN", "COMMIT", "ROLLBACK"))
               or "set_config" in sql for sql in audit.statements)


async def test_actors_lists_organization_members_only(audit):
    response = await audit.client.get(f"{URL}/actors")
    assert response.status_code == 200, response.text
    assert response.json() == [{"member_id": MEMBER, "name": "Migration Owner"},
                               {"member_id": VIEWER, "name": "Vera Visor"}]
    assert "example.test" not in response.text
