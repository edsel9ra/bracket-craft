"""Spec 033 T7: requests and immutable history through HTTP, with real RLS/RBAC."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db, set_rls_context
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.matches.service import load_report_payload_snapshot
from app.modules.rectifications.service import RectificationService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from migration_helpers import throwaway_database
from test_migration_031 import (
    MATCH, MEMBER, ORG, PLAYER_HOME_FIRST, SEED_SQL, SEGMENT_FIRST,
    TEAM_HOME, TOURNAMENT, USER, VERSION,
)

UNCONFIRMED = "31000000-0000-4000-8000-000000000053"


def proposal(**changes):
    report = {
        "resolution_type": "regular", "home_score_regular": 1, "away_score_regular": 0,
        "home_score": 1, "away_score": 0, "winner_team_id": TEAM_HOME,
        "events": [{
            "client_event_id": str(uuid4()), "segment_id": SEGMENT_FIRST,
            "team_id": TEAM_HOME, "player_id": PLAYER_HOME_FIRST,
            "event_type": "goal", "minute": 10,
        }],
    }
    report.update(changes)
    return {"proposed_report": report, "reason": " Corregir el acta ", "evidence": " Vídeo https://example.test "}


@pytest.fixture
async def flow(database_admin_url):
    async with throwaway_database(database_admin_url, last=35) as admin:
        seed = SEED_SQL.replace("1, '{}'::jsonb, '{}'::jsonb,", f"1, '{json.dumps(DEFAULT_RULES_CONFIG)}'::jsonb, '{{}}'::jsonb,")
        seed = seed.replace("UPDATE public.tournament_versions", f"""
            INSERT INTO matches (id, organization_id, tournament_id, tournament_version_id,
                stage_id, home_team_id, away_team_id, status)
            SELECT '{UNCONFIRMED}', organization_id, tournament_id, tournament_version_id,
                stage_id, home_team_id, away_team_id, 'scheduled' FROM matches WHERE id = '{MATCH}';
            UPDATE public.tournament_versions
        """)
        await admin.execute(seed)
        await admin.execute(seed.replace("31000000", "32000000").replace("migration-031", "rectification-other"))
        await admin.execute("""
            INSERT INTO roles (organization_id, role_definition_id, name, permissions)
            SELECT $1, id, name, system_permissions FROM role_definitions WHERE code = 'owner';
        """, ORG)
        await admin.execute("""
            INSERT INTO organization_user_roles (organization_id, organization_user_id, role_id)
            SELECT $1, $2, id FROM roles WHERE organization_id = $1
        """, ORG, MEMBER)
        await admin.execute("""
            INSERT INTO rosters (organization_id, tournament_id, team_id, player_id,
                dorsal_number, valid_from, eligible_from)
            SELECT s.organization_id, m.tournament_id, s.team_id, s.player_id,
                   row_number() OVER (ORDER BY s.player_id), '2026-01-01', '2026-01-01'
            FROM match_lineup_snapshots s JOIN matches m ON m.id = s.match_id
            WHERE s.organization_id = $1;
            INSERT INTO match_rosters (organization_id, match_id, roster_id, player_id,
                team_id, tournament_id, role)
            SELECT r.organization_id, m.id, r.id, r.player_id, r.team_id, r.tournament_id, 'starter'
            FROM rosters r JOIN matches m ON m.tournament_id = r.tournament_id
            WHERE r.organization_id = $1;
        """.replace("$1", f"'{ORG}'"))
        await admin.execute("""
            UPDATE matches SET status = 'finished', result_confirmed = TRUE,
                resolution_type = 'regular', home_score_regular = 0, away_score_regular = 0,
                home_score = 0, away_score = 0 WHERE id IN ($1, $2)
        """, MATCH, MATCH.replace("31000000", "32000000"))
        database = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(make_url(database_admin_url).set(database=database))
        state = SimpleNamespace(admin=admin, engine=engine,
            context=AuthContext(UUID(USER), UUID(ORG), UUID(MEMBER)))

        async def db():
            async with engine.connect() as connection:
                await connection.execute(text("SET ROLE bracket_app"))
                await connection.commit()
                async with AsyncSession(bind=connection) as session:
                    yield session

        async def auth():
            return state.context

        previous = api.dependency_overrides.copy()
        api.dependency_overrides[get_db] = db
        api.dependency_overrides[get_auth_context] = auth
        try:
            async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test",
                                   headers={"Origin": "http://localhost:3000"}) as client:
                state.client = client
                yield state
        finally:
            api.dependency_overrides.clear()
            api.dependency_overrides.update(previous)
            await engine.dispose()


async def create(flow, payload=None):
    return await flow.client.post(f"/api/v1/matches/{MATCH}/rectifications", json=payload or proposal())


async def assert_empty(flow):
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_requests") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 0


async def test_valid_request_audit_history_and_withdrawal(flow, monkeypatch):
    from app.modules.rectifications import service

    calls = []
    record = service.record_match_audit

    async def audit(*args, **kwargs):
        calls.append(kwargs)
        await record(*args, **kwargs)

    monkeypatch.setattr(service, "record_match_audit", audit)
    original = await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH)
    response = await create(flow)
    assert response.status_code == 201, response.text
    request = response.json()
    assert (request["status"], request["base_version_number"], request["requested_by_user_id"]) == ("pending", 1, USER)
    assert (request["reason"], request["evidence"]) == ("Corregir el acta", "Vídeo https://example.test")
    assert len(calls) == 1 and calls[0]["match_id"] == UUID(MATCH)
    assert await flow.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 1
    assert (await flow.client.get(f"/api/v1/matches/{MATCH}/rectifications")).json() == [request]
    detail = (await flow.client.get(f"/api/v1/rectifications/{request['id']}")).json()
    assert {key: value for key, value in detail.items() if key != "diff"} == request
    assert set(detail) == set(request) | {"diff"}
    versions = (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions")).json()
    assert [v["version_number"] for v in versions] == [1]
    assert versions[0]["report"]["home_score"] == 0 and versions[0]["report"]["events"] == []
    assert (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/1")).json() == versions[0]
    withdrawn = await flow.client.post(f"/api/v1/rectifications/{request['id']}/withdraw")
    assert withdrawn.status_code == 200 and withdrawn.json()["withdrawn_at"]
    assert withdrawn.json()["status"] == "withdrawn"
    again = await flow.client.post(f"/api/v1/rectifications/{request['id']}/withdraw")
    assert again.status_code == 409 and again.json()["code"] == "RECTIFICATION_NOT_PENDING"
    assert await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH) == original
    assert await flow.admin.fetchval("SELECT count(*) FROM match_events") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_versions") == 0


@pytest.mark.parametrize("state,code", [("unconfirmed", "MATCH_NOT_CONFIRMED"), ("archived", "TOURNAMENT_ARCHIVED")])
async def test_state_rejections_leave_no_record(flow, state, code):
    if state == "unconfirmed":
        match = UNCONFIRMED
    else:
        match = MATCH
        await flow.admin.execute("UPDATE tournament_versions SET status = 'archived' WHERE id = $1", VERSION)
    response = await flow.client.post(f"/api/v1/matches/{match}/rectifications", json=proposal())
    assert response.status_code == 409 and response.json()["code"] == code
    assert isinstance(response.json()["detail"], str)
    await assert_empty(flow)


@pytest.mark.parametrize("kind", ["resolution", "double-yellow", "score"])
async def test_invalid_proposal_reuses_closing_validation_and_does_not_write(flow, kind):
    payload = proposal()
    code = None
    if kind == "resolution":
        payload = proposal(resolution_type="extra_time")
        code = "RESOLUTION_NOT_ENABLED"
    elif kind == "double-yellow":
        payload = proposal(home_score_regular=0, home_score=0, winner_team_id=None)
        payload["proposed_report"]["events"][0].update(event_type="red_card", metadata={"red_card_type": "double_yellow_red"})
        code = "DOUBLE_YELLOW_INCONSISTENT"
    else:
        payload["proposed_report"]["events"] = []
    response = await create(flow, payload)
    assert response.status_code == 409, response.text
    if code:
        assert response.json()["code"] == code
    await assert_empty(flow)


async def test_no_changes_uses_effective_scores_and_event_defaults(flow):
    response = await create(flow, proposal(home_score_regular=0, away_score_regular=0,
        home_score=None, away_score=None, winner_team_id=None, events=[]))
    assert response.status_code == 409 and response.json()["code"] == "RECTIFICATION_NO_CHANGES"
    await assert_empty(flow)


async def test_pending_unique_index_and_match_lock(flow, monkeypatch):
    from app.modules.rectifications.service import RectificationService

    insert = RectificationService._insert_request

    async def collide(self, *args, **kwargs):
        with pytest.raises(asyncpg.LockNotAvailableError):
            await flow.admin.fetchrow("SELECT id FROM matches WHERE id = $1 FOR UPDATE NOWAIT", MATCH)
        await insert(self, *args, **kwargs)
        return await insert(self, *args, **kwargs)

    monkeypatch.setattr(RectificationService, "_insert_request", collide)
    response = await create(flow)
    assert response.status_code == 409 and response.json()["code"] == "RECTIFICATION_ALREADY_OPEN"
    await assert_empty(flow)


async def test_concurrent_requests_allow_only_one_pending(flow):
    responses = await asyncio.gather(create(flow), create(flow))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "RECTIFICATION_ALREADY_OPEN"
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_requests") == 1
    assert await flow.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 1


@pytest.mark.parametrize("resolution", ["walkover", "administrative"])
async def test_administrative_resolution_requires_additional_permission(flow, resolution):
    await flow.admin.execute("UPDATE roles SET permissions = '[\"REQUEST_MATCH_REPORT_RECTIFICATION\"]' WHERE organization_id = $1", ORG)
    payload = proposal(resolution_type=resolution, reason="no_show" if resolution == "walkover" else "Resolución",
        home_score_regular=3, home_score=3, events=[])
    response = await create(flow, payload)
    assert response.status_code == 403, response.text
    await assert_empty(flow)
    await flow.admin.execute("UPDATE roles SET permissions = permissions || '[\"RESOLVE_MATCH_ADMINISTRATIVELY\"]' WHERE organization_id = $1", ORG)
    response = await create(flow, payload)
    assert response.status_code == 201, response.text


async def test_reads_are_membership_only_but_create_requires_permission_and_withdraw_requires_requester(flow):
    request = (await create(flow)).json()
    user, member = uuid4(), uuid4()
    await flow.admin.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES ($1, 'reader@example.test', 'hash', 'Reader')", user)
    await flow.admin.execute("INSERT INTO organization_users (id, organization_id, user_id, is_active) VALUES ($1, $2, $3, TRUE)", member, ORG, user)
    flow.context = AuthContext(user, UUID(ORG), member)
    for path in (f"/matches/{MATCH}/rectifications", f"/rectifications/{request['id']}",
                 f"/matches/{MATCH}/report-versions", f"/matches/{MATCH}/report-versions/1"):
        assert (await flow.client.get("/api/v1" + path)).status_code == 200
    denied = await flow.client.post(f"/api/v1/rectifications/{request['id']}/withdraw")
    assert denied.status_code == 403
    assert (await create(flow)).status_code == 403
    assert await flow.admin.fetchval("SELECT status FROM match_report_rectification_requests WHERE id = $1", request["id"]) == "pending"


async def test_versions_use_published_base_and_preserve_original(flow):
    request = (await create(flow)).json()
    version = await flow.admin.fetchval("""
        INSERT INTO match_report_versions (organization_id, match_id, version_number,
            supersedes_version_number, resolution_type, home_score_regular, away_score_regular,
            home_score, away_score, winner_team_id, request_id, published_by_user_id)
        VALUES ($1, $2, 2, 1, 'regular', 1, 0, 1, 0, $3, $4, $5) RETURNING id
    """, ORG, MATCH, TEAM_HOME, request["id"], USER)
    event = request["proposed_report"]["events"][0]
    await flow.admin.execute("""
        INSERT INTO match_report_version_events (organization_id, version_id, match_id, segment_id,
            team_id, player_id, event_type, minute, client_event_id)
        VALUES ($1, $2, $3, $4, $5, $6, 'goal', 10, $7)
    """, ORG, version, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST, event["client_event_id"])
    await flow.admin.execute("UPDATE match_report_rectification_requests SET status = 'published', resulting_version_id = $2 WHERE id = $1", request["id"], version)
    versions = (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions")).json()
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["report"]["home_score"] == 0
    assert versions[1]["report"]["home_score"] == 1 and len(versions[1]["report"]["events"]) == 1
    assert versions[1]["reason"] == request["reason"] and versions[1]["evidence"] == request["evidence"]
    assert (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/2")).json() == versions[1]
    identical = await create(flow, {**proposal(), "proposed_report": deepcopy(request["proposed_report"])})
    assert identical.status_code == 409 and identical.json()["code"] == "RECTIFICATION_NO_CHANGES"
    changed = deepcopy(request["proposed_report"])
    changed["events"][0]["minute"] = 11
    response = await create(flow, {**proposal(), "proposed_report": changed})
    assert response.status_code == 201 and response.json()["base_version_number"] == 2


async def test_archiving_does_not_prevent_withdrawing_pending_request(flow):
    request = (await create(flow)).json()
    await flow.admin.execute("UPDATE tournament_versions SET status = 'archived' WHERE id = $1", VERSION)
    response = await flow.client.post(f"/api/v1/rectifications/{request['id']}/withdraw")
    assert response.status_code == 200 and response.json()["status"] == "withdrawn"


async def test_original_history_keeps_voided_events_and_no_changes_normalizes_event_defaults(flow):
    segment, goal, card = uuid4(), str(uuid4()), str(uuid4())
    await flow.admin.execute("""
        INSERT INTO match_segments (id, organization_id, match_id, segment_number,
            minute_start, minute_end, status) VALUES ($1, $2, $3, 1, 0, 90, 'completed')
    """, segment, ORG, UNCONFIRMED)
    await flow.admin.execute("""
        INSERT INTO match_events (organization_id, match_id, segment_id, team_id,
            player_id, event_type, minute, client_event_id)
        VALUES ($1, $2, $3, $4, $5, 'goal', 10, $6)
    """, ORG, UNCONFIRMED, segment, TEAM_HOME, PLAYER_HOME_FIRST, goal)
    await flow.admin.execute("""
        INSERT INTO match_events (organization_id, match_id, segment_id, team_id,
            player_id, event_type, minute, client_event_id, is_voided,
            voided_at, voided_by_member_id, void_reason)
        VALUES ($1, $2, $3, $4, $5, 'yellow_card', 11, $6, TRUE, CURRENT_TIMESTAMP, $7, 'Error')
    """, ORG, UNCONFIRMED, segment, TEAM_HOME, PLAYER_HOME_FIRST, card, MEMBER)
    await flow.admin.execute("""
        UPDATE matches SET status = 'finished', result_confirmed = TRUE, resolution_type = 'regular',
            home_score_regular = 1, away_score_regular = 0, home_score = 1, away_score = 0,
            winner_team_id = home_team_id WHERE id = $1
    """, UNCONFIRMED)
    await flow.admin.execute("""
        INSERT INTO administrative_audit_logs (organization_id, entity_type, entity_id,
            action, payload, performed_by_member_id)
        VALUES ($1, 'matches', $2, 'CLOSE_MATCH_REPORT', '{}', $3)
    """, ORG, UNCONFIRMED, MEMBER)
    history = await flow.client.get(f"/api/v1/matches/{UNCONFIRMED}/report-versions/1")
    assert history.status_code == 200, history.text
    assert [event["is_voided"] for event in history.json()["report"]["events"]] == [False, True]
    assert history.json()["published_by_user_id"] == USER and history.json()["published_at"]
    body = proposal()
    body["proposed_report"]["events"][0].update(segment_id=str(segment), client_event_id=goal.upper(), metadata={})
    response = await flow.client.post(f"/api/v1/matches/{UNCONFIRMED}/rectifications", json=body)
    assert response.status_code == 409 and response.json()["code"] == "RECTIFICATION_NO_CHANGES"
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_requests") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 1


@pytest.mark.parametrize("field,value", [("reason", "  "), ("evidence", "  "), ("evidence", None), ("attachment", "file")])
async def test_strict_nonempty_text_schema(flow, field, value):
    body = proposal()
    body[field] = value
    response = await create(flow, body)
    assert response.status_code == 422
    await assert_empty(flow)


@pytest.mark.parametrize("level", ["report", "event", "missing-evidence", "missing-reason"])
async def test_nested_schema_and_required_fields(flow, level):
    body = proposal()
    if level == "report":
        body["proposed_report"]["unexpected"] = True
    elif level == "event":
        body["proposed_report"]["events"][0]["unexpected"] = True
    else:
        del body[level.removeprefix("missing-")]
    assert (await create(flow, body)).status_code == 422
    await assert_empty(flow)


async def test_foreign_and_missing_resources_are_indistinguishable_404(flow):
    foreign_match = MATCH.replace("31000000", "32000000")
    foreign = await flow.admin.fetchval("""
        INSERT INTO match_report_rectification_requests (organization_id, match_id,
            base_version_number, proposed_report, reason, requested_by_user_id, requested_by_member_id)
        VALUES ($1, $2, 1, '{}', 'private', $3, $4) RETURNING id
    """, ORG.replace("31000000", "32000000"), foreign_match,
        USER.replace("31000000", "32000000"), MEMBER.replace("31000000", "32000000"))
    for method, template, alien in [
        ("GET", "/matches/{id}/rectifications", foreign_match),
        ("POST", "/matches/{id}/rectifications", foreign_match),
        ("GET", "/matches/{id}/report-versions", foreign_match),
        ("GET", "/matches/{id}/report-versions/1", foreign_match),
        ("GET", "/rectifications/{id}", foreign),
        ("POST", "/rectifications/{id}/withdraw", foreign),
    ]:
        kwargs = {"json": proposal()} if template.endswith("/rectifications") and method == "POST" else {}
        hidden = await flow.client.request(method, "/api/v1" + template.format(id=alien), **kwargs)
        missing = await flow.client.request(method, "/api/v1" + template.format(id=uuid4()), **kwargs)
        assert hidden.status_code == missing.status_code == 404, hidden.text
        assert hidden.json() == missing.json()
    assert (await flow.client.get(f"/api/v1/matches/{MATCH}/rectifications")).json() == []
    assert (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/99")).status_code == 404


async def test_anonymous_routes_require_authentication():
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        for path in (f"/matches/{MATCH}/rectifications", f"/rectifications/{uuid4()}",
                     f"/matches/{MATCH}/report-versions", f"/matches/{MATCH}/report-versions/1"):
            assert (await client.get("/api/v1" + path)).status_code == 401


async def database_snapshot(admin):
    tables = await admin.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
    return {row["tablename"]: await admin.fetchval(
        'SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM public."'
        + row["tablename"].replace('"', '""') + '" t') for row in tables}


async def test_preview_and_detail_diff_leave_every_table_unchanged(flow):
    request = (await create(flow)).json()
    before = await database_snapshot(flow.admin)
    detail = await flow.client.get(f"/api/v1/rectifications/{request['id']}")
    assert detail.status_code == 200
    assert any(field["field"] == "home_score" for field in detail.json()["diff"]["fields"])
    assert len(detail.json()["diff"]["events"]["added"]) == 1
    response = await flow.client.get(f"/api/v1/rectifications/{request['id']}/preview")
    assert response.status_code == 200, response.text
    assert response.json()["version"]["version_number"] == 2
    assert response.json()["version"]["report"]["home_score"] == 1
    assert len(response.json()["version"]["report"]["events"]) == 1
    assert response.json()["effects"] == []
    assert await database_snapshot(flow.admin) == before


async def test_preview_errors_roll_back_inserted_version_and_events(flow, monkeypatch):
    from app.modules.rectifications import service

    request = (await create(flow)).json()
    before = await database_snapshot(flow.admin)

    async def fail(db, context, version, now):
        assert (await db.execute(text("SELECT count(*) FROM match_report_versions"))).scalar_one() == 1
        assert (await db.execute(text("SELECT count(*) FROM match_report_version_events"))).scalar_one() == 1
        raise ValueError("Efectos no disponibles")

    monkeypatch.setattr(service, "apply_effects", fail)
    response = await flow.client.get(f"/api/v1/rectifications/{request['id']}/preview")
    assert response.status_code == 409
    assert await database_snapshot(flow.admin) == before


async def test_preview_permission_and_404_isolation(flow):
    request = (await create(flow)).json()
    await flow.admin.execute("UPDATE roles SET permissions = '[]' WHERE organization_id = $1", ORG)
    response = await flow.client.get(f"/api/v1/rectifications/{request['id']}/preview")
    assert response.status_code == 403
    flow.context = AuthContext(UUID(USER.replace("31000000", "32000000")),
        UUID(ORG.replace("31000000", "32000000")), UUID(MEMBER.replace("31000000", "32000000")))
    hidden = await flow.client.get(f"/api/v1/rectifications/{request['id']}/preview")
    missing = await flow.client.get(f"/api/v1/rectifications/{uuid4()}/preview")
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()


async def add_approver(flow, permissions=None):
    user, member = uuid4(), uuid4()
    await flow.admin.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES ($1, $2, 'hash', 'Approver')", user, f"{user}@example.test")
    await flow.admin.execute("INSERT INTO organization_users (id, organization_id, user_id, is_active) VALUES ($1, $2, $3, TRUE)", member, ORG, user)
    role = await flow.admin.fetchval("""
        INSERT INTO roles (organization_id, role_definition_id, name, permissions)
        SELECT $1, id, name, system_permissions FROM role_definitions WHERE code = 'administrator' RETURNING id
    """, ORG)
    if permissions is not None:
        await flow.admin.execute("UPDATE roles SET permissions = $2::jsonb WHERE id = $1", role, json.dumps(permissions))
    await flow.admin.execute("INSERT INTO organization_user_roles (organization_id, organization_user_id, role_id) VALUES ($1, $2, $3)", ORG, member, role)
    return AuthContext(user, UUID(ORG), member)


async def decide(flow, request_id, **changes):
    body = {"decision": "approve", "reason": " Revisado con el vídeo ", "expected_base_version": 1, **changes}
    return await flow.client.post(f"/api/v1/rectifications/{request_id}/decision", json=body)


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_self_decision_is_rejected_by_service_before_permission(flow, monkeypatch, decision):
    from app.modules.rectifications.service import RectificationService

    request = (await create(flow)).json()
    await flow.admin.execute("UPDATE roles SET permissions = '[]' WHERE organization_id = $1", ORG)
    before = await database_snapshot(flow.admin)
    calls = []

    async def forbidden(*args):
        calls.append(True)
        raise PermissionError("Sin permiso")

    monkeypatch.setattr(RectificationService, "_approval_permission", forbidden)
    response = await decide(flow, request["id"], decision=decision)
    assert response.status_code == 403 and response.json()["code"] == "RECTIFICATION_SELF_APPROVAL"
    assert calls == []
    assert await database_snapshot(flow.admin) == before


async def test_self_decision_trigger_42501_is_mapped_to_same_403(flow, monkeypatch):
    from app.modules.rectifications.service import RectificationService

    request = (await create(flow)).json()
    before = await database_snapshot(flow.admin)
    monkeypatch.setattr(RectificationService, "_require_distinct_actor", staticmethod(lambda request, context: None))
    response = await decide(flow, request["id"])
    assert response.status_code == 403 and response.json()["code"] == "RECTIFICATION_SELF_APPROVAL"
    assert await database_snapshot(flow.admin) == before


async def test_decision_without_permission_does_not_write(flow):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow, permissions=[])
    before = await database_snapshot(flow.admin)
    response = await decide(flow, request["id"])
    assert response.status_code == 403
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("change", [{"reason": "  "}, {"reason": None}, {"expected_base_version": 0},
    {"decision": "other"}, {"unexpected": True}])
async def test_decision_schema_is_strict(flow, change):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    before = await database_snapshot(flow.admin)
    response = await decide(flow, request["id"], **change)
    assert response.status_code == 422
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("resolution", ["walkover", "administrative"])
async def test_decision_requires_resolution_permission_too(flow, resolution):
    request = (await create(flow, proposal(resolution_type=resolution,
        reason="no_show" if resolution == "walkover" else "Resolución", home_score_regular=3, home_score=3, events=[]))).json()
    flow.context = await add_approver(flow, permissions=["APPROVE_MATCH_REPORT_RECTIFICATION"])
    response = await decide(flow, request["id"])
    assert response.status_code == 403
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_decisions") == 0
    await flow.admin.execute("UPDATE roles SET permissions = permissions || '[\"RESOLVE_MATCH_ADMINISTRATIVELY\"]' WHERE organization_id = $1", ORG)
    response = await decide(flow, request["id"])
    assert response.status_code == 200 and response.json()["status"] == "published"


async def test_expected_base_stale_rolls_back_decision(flow):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    before = await database_snapshot(flow.admin)
    response = await decide(flow, request["id"], expected_base_version=2)
    assert response.status_code == 409 and response.json()["code"] == "RECTIFICATION_STALE"
    assert await database_snapshot(flow.admin) == before


async def test_pending_base_stale_against_published_version(flow):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    assert (await decide(flow, request["id"])).status_code == 200
    stale = await flow.admin.fetchval("""
        INSERT INTO match_report_rectification_requests (organization_id, match_id, base_version_number,
            proposed_report, reason, evidence, requested_by_user_id, requested_by_member_id)
        VALUES ($1, $2, 1, $3::jsonb, 'Old reference', 'Evidence', $4, $5) RETURNING id
    """, ORG, MATCH, json.dumps(request["proposed_report"]), USER, MEMBER)
    before = await database_snapshot(flow.admin)
    response = await decide(flow, str(stale))
    assert response.status_code == 409 and response.json()["code"] == "RECTIFICATION_STALE"
    assert await database_snapshot(flow.admin) == before


async def test_archived_approval_fails_but_rejection_records_decision_and_audit(flow):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    await flow.admin.execute("UPDATE tournament_versions SET status = 'archived' WHERE id = $1", VERSION)
    before = await database_snapshot(flow.admin)
    response = await decide(flow, request["id"])
    assert response.status_code == 409 and response.json()["code"] == "TOURNAMENT_ARCHIVED"
    assert await database_snapshot(flow.admin) == before
    rejected = await decide(flow, request["id"], decision="reject", expected_base_version=99)
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    row = await flow.admin.fetchrow("SELECT * FROM match_report_rectification_decisions")
    assert row["decision"] == "reject" and row["reason"] == "Revisado con el vídeo"
    assert row["decided_by_user_id"] == flow.context.user_id and row["decided_as"] == "member" and row["decided_at"]
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_versions") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 2
    repeated = await decide(flow, request["id"])
    assert repeated.status_code == 409 and repeated.json()["code"] == "RECTIFICATION_NOT_PENDING"


async def test_concurrent_approvals_publish_once(flow):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    responses = await asyncio.gather(decide(flow, request["id"]), decide(flow, request["id"]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "RECTIFICATION_NOT_PENDING"
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_versions") == 1
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_decisions") == 1
    assert await flow.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 2


async def test_publication_and_preview_share_hook_and_versions_2_3_preserve_original(flow, monkeypatch):
    from app.modules.rectifications import service

    original = await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH)
    first = (await create(flow)).json()
    requester = flow.context
    approver = await add_approver(flow)
    flow.context = approver
    calls = []

    async def effects(db, context, version, now):
        assert (await db.execute(text("SELECT current_setting('app.rectification_version_id')"))).scalar_one() == str(version["id"])
        calls.append(version["version_number"])
        return []

    monkeypatch.setattr(service, "apply_effects", effects)
    preview = await flow.client.get(f"/api/v1/rectifications/{first['id']}/preview")
    assert preview.status_code == 200 and calls == [2]
    response = await decide(flow, first["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published" and response.json()["resulting_version_id"]
    published = (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/2")).json()
    assert published["report"]["home_score"] == preview.json()["version"]["report"]["home_score"] == 1
    assert published["published_by_user_id"] == str(approver.user_id)
    detail = (await flow.client.get(f"/api/v1/rectifications/{first['id']}")).json()
    assert detail["diff"] == {"fields": [], "events": {"added": [], "removed": [], "changed": []}}
    first_version = deepcopy(published)
    flow.context = requester
    body = proposal()
    body["proposed_report"] = deepcopy(first["proposed_report"])
    body["proposed_report"].update(home_score_regular=2, home_score=2)
    body["proposed_report"]["events"].append({**body["proposed_report"]["events"][0], "client_event_id": str(uuid4()), "minute": 20})
    second = (await create(flow, body)).json()
    assert second["base_version_number"] == 2
    flow.context = approver
    assert (await decide(flow, second["id"], expected_base_version=2)).status_code == 200
    assert calls == [2, 2, 3]
    assert (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/2")).json() == first_version
    operation = await flow.client.get(f"/api/v1/matches/{MATCH}/operation")
    assert operation.status_code == 200, operation.text
    assert operation.json()["match"]["home_score"] == 2 and len(operation.json()["events"]) == 2
    versions = (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions")).json()
    assert [version["version_number"] for version in versions] == [1, 2, 3]
    public = await flow.client.get(f"/api/v1/tournaments/public/{TOURNAMENT}/matches")
    assert public.status_code == 200, public.text
    public_match = next(match for match in public.json() if match["id"] == MATCH)
    assert public_match["home_score"] == 2 and public_match["rectified_at"]
    assert await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH) == original
    assert await flow.admin.fetchval("SELECT count(*) FROM match_events") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM outbox_events") == 0


@pytest.mark.parametrize("failure", ["validation", "effects", "audit"])
async def test_failed_publication_rolls_back_every_table(flow, monkeypatch, failure):
    from app.modules.rectifications import service
    from app.modules.matches.errors import ResolutionNotEnabled

    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    before = await database_snapshot(flow.admin)
    if failure == "validation":
        def invalid(*args):
            raise ResolutionNotEnabled()
        monkeypatch.setattr(service, "validate_report_payload", invalid)
    elif failure == "effects":
        async def unavailable(*args):
            raise ValueError("Efectos no disponibles")
        monkeypatch.setattr(service, "apply_effects", unavailable)
    else:
        async def unavailable(*args, **kwargs):
            raise ValueError("Auditoría no disponible")
        monkeypatch.setattr(service, "record_match_audit", unavailable)
    response = await decide(flow, request["id"])
    assert response.status_code == 409
    if failure == "validation":
        assert response.json()["code"] == "RESOLUTION_NOT_ENABLED"
    assert await database_snapshot(flow.admin) == before


async def test_decision_foreign_and_missing_requests_have_identical_404(flow):
    request = (await create(flow)).json()
    flow.context = AuthContext(UUID(USER.replace("31000000", "32000000")),
        UUID(ORG.replace("31000000", "32000000")), UUID(MEMBER.replace("31000000", "32000000")))
    before = await database_snapshot(flow.admin)
    hidden = await decide(flow, request["id"])
    missing = await decide(flow, str(uuid4()))
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert await database_snapshot(flow.admin) == before


async def test_not_pending_precedes_self_approval(flow):
    request = (await create(flow)).json()
    assert (await flow.client.post(f"/api/v1/rectifications/{request['id']}/withdraw")).status_code == 200
    before = await database_snapshot(flow.admin)
    response = await decide(flow, request["id"])
    assert response.status_code == 409 and response.json()["code"] == "RECTIFICATION_NOT_PENDING"
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("origin", [MATCH, UNCONFIRMED])
async def test_rectification_ignores_only_suspensions_originating_in_its_match(flow, origin):
    await flow.admin.execute("""
        INSERT INTO player_suspensions (organization_id, source_tournament_id, player_id,
            origin_match_id, reason, matches_suspended, scope_type, source_type, dedupe_key)
        VALUES ($1, $2, $3, $4, 'red_card', 1, 'tournament', 'administrative_resolution', 'self-match-regression')
    """, ORG, TOURNAMENT, PLAYER_HOME_FIRST, origin)
    async with flow.engine.connect() as connection:
        await connection.execute(text("SET ROLE bracket_app"))
        await connection.commit()
        async with AsyncSession(bind=connection) as db, db.begin():
            await set_rls_context(db, flow.context.organization_id, flow.context.user_id)
            match = await RectificationService(db)._match(flow.context, UUID(MATCH))
            snapshot = await load_report_payload_snapshot(db, flow.context, match,
                CloseMatchReportDTO.model_validate(proposal()["proposed_report"]))
            assert snapshot.has_suspended_players is True
    before = await database_snapshot(flow.admin)
    response = await create(flow)
    if origin != MATCH:
        assert response.status_code == 409 and "suspendido" in response.json()["detail"]
        assert await database_snapshot(flow.admin) == before
        return
    assert response.status_code == 201, response.text
    request = response.json()
    flow.context = await add_approver(flow)
    assert (await flow.client.get(f"/api/v1/rectifications/{request['id']}/preview")).status_code == 200
    assert (await decide(flow, request["id"])).status_code == 200
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspensions") == 1
    assert await flow.admin.fetchval("SELECT status FROM player_suspensions") == "active"
