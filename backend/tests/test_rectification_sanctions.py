"""RF-018/DA-8/D5: immutable provenance, consumed serves and deferred impacts."""

from copy import deepcopy
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.matches.service import CloseMatchReportService
from app.modules.rectifications.sanctions import capture_discipline
from app.modules.rules_engine.engine import evaluate_suspensions
import test_rectification_flow as flow_module
from test_migration_031 import MATCH, ORG, PLAYER_AWAY, PLAYER_HOME_FIRST, SEGMENT_FIRST, TEAM_AWAY, TEAM_HOME
from test_rectification_flow import UNCONFIRMED, add_approver, create, database_snapshot, decide, proposal
from test_rectification_flow import flow as flow


@pytest.mark.parametrize("flow", [{"schema": 39}, {"schema": 43}], indirect=True)
async def test_recalculation_without_resolutions_matches_039_baseline(flow, monkeypatch):
    if not await flow.admin.fetchval("SELECT to_regclass('public.sanction_resolutions') IS NOT NULL"):
        async def no_cases_before_040(db, version_id):
            return None
        monkeypatch.setattr("app.modules.rectifications.effects.close_for_rectification", no_cases_before_040)
        async def original_blocking(self, context, tournament_id, player_ids, **kwargs):
            result = await self.db.execute(text("""SELECT 1 FROM player_suspensions ps
                WHERE ps.organization_id=:org AND ps.status='active' AND ps.player_id=ANY(CAST(:players AS uuid[]))
                AND (ps.scope_type='organization' OR ps.source_tournament_id=:tournament)
                AND ps.origin_match_id IS DISTINCT FROM :origin
                AND (CAST(:cutoff AS timestamptz) IS NULL OR ps.created_at<=:cutoff)
                AND (SELECT count(*) FROM player_suspension_serves s WHERE s.suspension_id=ps.id AND NOT s.is_voided)<ps.matches_suspended"""),
                {"org": context.organization_id, "players": player_ids, "tournament": tournament_id,
                 "origin": kwargs.get("exclude_origin_match_id"), "cutoff": kwargs.get("created_before")})
            return result.first() is not None
        monkeypatch.setattr(CloseMatchReportService, "_has_suspended_players", original_blocking)
    requester = flow.context
    body = card_report()
    request = await submit(flow, body)
    assert (await decide(flow, request)).status_code == 200
    original = dict(await flow.admin.fetchrow("SELECT * FROM player_suspensions"))
    assert original["status"] == "active" and original["source_type"] == "match_event"
    duration = original["matches_suspended"]
    await flow.admin.execute("INSERT INTO player_suspension_serves(organization_id,suspension_id,match_id) VALUES ($1,$2,$3)", ORG, original["id"], UNCONFIRMED)
    serves = [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspension_serves")]
    approver = flow.context
    for number, report in [(2, body), (3, proposal())]:
        report = deepcopy(report)
        if number == 2:
            report["proposed_report"]["events"][0]["minute"] = 12
        flow.context = requester
        response = await create(flow, report)
        assert response.status_code == 201, response.text
        flow.context = approver
        response = await decide(flow, response.json()["id"], expected_base_version=number)
        assert response.status_code == 200, response.text
        rows = [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspensions")]
        assert len(rows) == 1 and rows[0]["id"] == original["id"]
        assert rows[0]["matches_suspended"] == duration
        assert rows[0]["status"] == ("active" if number == 2 else "cancelled")
        assert [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspension_serves")] == serves


def card_report():
    body = proposal()
    body["proposed_report"]["events"].append({
        "client_event_id": str(uuid4()), "segment_id": SEGMENT_FIRST,
        "team_id": TEAM_HOME, "player_id": PLAYER_HOME_FIRST,
        "event_type": "red_card", "minute": 20,
    })
    return body


async def submit(flow, body):
    response = await create(flow, body)
    assert response.status_code == 201, response.text
    flow.context = await add_approver(flow)
    return response.json()["id"]


async def serve(flow):
    match = dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", UNCONFIRMED))
    await flow.admin.execute("DELETE FROM match_rosters WHERE match_id = $1 AND player_id = $2", UNCONFIRMED, PLAYER_HOME_FIRST)
    async with flow.engine.connect() as conn:
        await conn.execute(text("SET ROLE bracket_app"))
        await conn.commit()
        async with AsyncSession(bind=conn) as session, session.begin():
            await set_rls_context(session, flow.context.organization_id, flow.context.user_id)
            await CloseMatchReportService(session)._serve_suspensions(flow.context, match)


async def test_new_version_card_preview_rollback_and_published_provenance(flow):
    request = await submit(flow, card_report())
    before = await database_snapshot(flow.admin)
    preview = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert preview.status_code == 200, preview.text
    assert "sanction_created" in [effect["effect_type"] for effect in preview.json()["effects"]]
    assert await database_snapshot(flow.admin) == before
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    row = await flow.admin.fetchrow("SELECT * FROM player_suspensions WHERE organization_id = $1", ORG)
    assert row["status"] == "active" and row["source_event_id"] is None
    assert await flow.admin.fetchval("SELECT event_type FROM match_report_version_events WHERE id = $1", row["source_version_event_id"]) == "red_card"
    assert await flow.admin.fetchval("SELECT count(*) FROM match_events WHERE match_id = $1", MATCH) == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspensions WHERE organization_id <> $1", ORG) == 0


@pytest.mark.parametrize("original_status", ["active", "served"])
async def test_same_logical_card_retained_then_annulled_with_serves_and_restored_as_new(flow, original_status):
    requester = flow.context
    body = card_report()
    request = await submit(flow, body)
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
    await flow.admin.execute("UPDATE player_suspensions SET status=$1", original_status)
    original = dict(await flow.admin.fetchrow("SELECT * FROM player_suspensions"))
    await flow.admin.execute("INSERT INTO player_suspension_serves (organization_id, suspension_id, match_id) VALUES ($1,$2,$3)", ORG, original["id"], UNCONFIRMED)
    serves_before = [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspension_serves")]
    unchanged = deepcopy(body)
    unchanged["proposed_report"]["events"][0]["minute"] = 11
    for number, report in [(2, unchanged), (3, proposal()), (4, body)]:
        flow.context = requester
        response = await create(flow, report)
        assert response.status_code == 201, response.text
        flow.context = approver
        response = await decide(flow, response.json()["id"], expected_base_version=number)
        assert response.status_code == 200, response.text
        if number == 2:
            assert dict(await flow.admin.fetchrow("SELECT * FROM player_suspensions")) == original
    rows = [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspensions ORDER BY created_at")]
    assert len(rows) == 2 and rows[0] == {**original, "status": "cancelled"}
    assert rows[1]["status"] == "active" and rows[1]["id"] != original["id"]
    assert [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspension_serves")] == serves_before
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspension_annulments WHERE suspension_id = $1", original["id"]) == 1


@pytest.mark.parametrize("already_started", [False, True])
async def test_new_sanction_served_only_if_match_had_not_started(flow, already_started):
    if already_started:
        await flow.admin.execute("""INSERT INTO match_segments (organization_id, match_id, segment_number, minute_start, created_at)
            VALUES ($1,$2,1,0,now() - interval '1 hour')""", ORG, UNCONFIRMED)
    request = await submit(flow, card_report())
    assert (await decide(flow, request)).status_code == 200
    if not already_started:
        await flow.admin.execute("""INSERT INTO match_segments (organization_id, match_id, segment_number, minute_start, created_at)
            VALUES ($1,$2,1,0,now() + interval '1 hour')""", ORG, UNCONFIRMED)
    await serve(flow)
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspension_serves") == (0 if already_started else 1)


async def test_failure_after_sanction_effect_rolls_back_all_tables(flow, monkeypatch):
    from app.modules.rectifications import effects

    request = await submit(flow, card_report())
    before = await database_snapshot(flow.admin)
    record = effects.record_effect
    async def fail(db, context, version_id, effect, now):
        await record(db, context, version_id, effect, now)
        if effect["effect_type"] == "sanction_created":
            raise RuntimeError("after sanction effect")
    monkeypatch.setattr(effects, "record_effect", fail)
    with pytest.raises(RuntimeError, match="after sanction effect"):
        await decide(flow, request)
    assert await database_snapshot(flow.admin) == before


def test_reconciliation_keeps_logical_identity_and_replaces_cancelled_sanctions():
    from app.modules.rectifications.sanctions import reconcile_sanctions

    desired = {"logical_event_id": "card", "player_id": UUID(PLAYER_HOME_FIRST), "reason": "direct_red_card"}
    old = {**desired, "id": uuid4(), "status": "served", "source_event_id": uuid4()}
    assert reconcile_sanctions([old], [{**desired, "source_event_id": uuid4()}]) == ([], [])
    assert reconcile_sanctions([{**old, "status": "cancelled"}], [desired]) == ([desired], [])
    assert reconcile_sanctions([old], []) == ([], [old])
    assert reconcile_sanctions([], []) == ([], [])


def test_later_accumulation_is_typed_candidate_not_a_sanction_mutation():
    from app.modules.rectifications.sanctions import AccumulationImpactCandidate, accumulation_impacts

    old = [{"player_id": UUID(PLAYER_HOME_FIRST), "logical_event_id": "later-yellow", "reason": "yellow_card_accumulation"}]
    candidates = accumulation_impacts(UUID(UNCONFIRMED), old, [], 1)
    assert candidates == [AccumulationImpactCandidate(UUID(UNCONFIRMED), UUID(PLAYER_HOME_FIRST), ("later-yellow",), (), 1)]
    assert accumulation_impacts(UUID(UNCONFIRMED), old, old, 1) == []
    assert accumulation_impacts(UUID(UNCONFIRMED), [], [], 1) == []


@pytest.mark.parametrize("flow,removing", [((str(uuid4()), str(uuid4())), True), ((), False)], indirect=["flow"])
async def test_later_confirmed_accumulation_delivered_to_transactional_hook_without_mutation(flow, removing, monkeypatch):
    from app.modules.rectifications import effects
    from app.modules.rectifications.sanctions import AccumulationImpactCandidate

    segment = await flow.admin.fetchval("""INSERT INTO match_segments
        (organization_id, match_id, segment_number, minute_start) VALUES ($1,$2,1,0) RETURNING id""", ORG, UNCONFIRMED)
    logical_id = str(uuid4())
    event = await flow.admin.fetchval("""INSERT INTO match_events
        (organization_id, match_id, segment_id, team_id, player_id, event_type, minute, client_event_id)
        VALUES ($1,$2,$3,$4,$5,'yellow_card',20,$6) RETURNING id""",
        ORG, UNCONFIRMED, segment, TEAM_HOME, PLAYER_HOME_FIRST, logical_id)
    await flow.admin.execute("""UPDATE matches SET status='finished', result_confirmed=TRUE,
        resolution_type='regular', home_score_regular=0, away_score_regular=0,
        home_score=0, away_score=0 WHERE id=$1""", UNCONFIRMED)
    if removing:
        await flow.admin.execute("""INSERT INTO player_suspensions
            (organization_id, source_tournament_id, player_id, origin_match_id, source_event_id,
             source_type, dedupe_key, scope_type, matches_suspended, reason)
            SELECT organization_id,tournament_id,$2,id,$3,'match_event','later-accumulation',
                'organization',1,'yellow_card_accumulation' FROM matches WHERE id=$1""", UNCONFIRMED, PLAYER_HOME_FIRST, event)
    before = [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspensions")]
    observed = []
    async def hook(db, context, version, candidates, now):
        assert db.in_transaction()
        observed.extend(candidates)
        return []
    monkeypatch.setattr(effects, "apply_competitive_impacts", hook)
    body = proposal()
    if not removing:
        body["proposed_report"]["events"].extend({
            "client_event_id": str(uuid4()), "segment_id": SEGMENT_FIRST,
            "team_id": TEAM_HOME, "player_id": PLAYER_HOME_FIRST,
            "event_type": "yellow_card", "minute": minute,
        } for minute in [20, 21])
    request = await submit(flow, body)
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert observed == [AccumulationImpactCandidate(UUID(UNCONFIRMED), UUID(PLAYER_HOME_FIRST),
        (logical_id,) if removing else (), () if removing else (logical_id,), 1)]
    assert [dict(row) for row in await flow.admin.fetch("SELECT * FROM player_suspensions")] == before
    assert await flow.admin.fetchval("SELECT count(*) FROM competitive_impact_procedures") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_effects WHERE effect_type='impact_opened'") == 0


@pytest.mark.parametrize("offset,status", [(-1, 409), (0, 409), (1, 201)])
async def test_administrative_sanction_eligibility_at_original_confirmation(flow, offset, status):
    await flow.admin.execute("""INSERT INTO player_suspensions
        (organization_id, source_tournament_id, player_id, source_type, dedupe_key,
         scope_type, matches_suspended, reason, created_at)
        SELECT organization_id, tournament_id, $2, 'administrative_resolution', 'administrative',
               'organization', 1, 'Administrative', original_report_confirmed_at + $3 * interval '1 second'
        FROM matches WHERE id=$1""", MATCH, PLAYER_HOME_FIRST, offset)
    response = await create(flow)
    assert response.status_code == status, response.text
    if status == 201:
        flow.context = await add_approver(flow)
        request = response.json()["id"]
        assert (await flow.client.get(f"/api/v1/rectifications/{request}/preview")).status_code == 200
        assert (await decide(flow, request)).status_code == 200


@pytest.mark.parametrize("flow", [{"legacy_confirmation": True}], indirect=True)
async def test_unknown_original_confirmation_keeps_conservative_suspension_check(flow):
    assert await flow.admin.fetchval("SELECT original_report_confirmed_at FROM matches WHERE id=$1", MATCH) is None
    await flow.admin.execute("""INSERT INTO player_suspensions
        (organization_id, source_tournament_id, player_id, source_type, dedupe_key,
         scope_type, matches_suspended, reason)
        SELECT organization_id, tournament_id, $2, 'administrative_resolution', 'unknown-time',
               'organization', 1, 'Administrative' FROM matches WHERE id=$1""", MATCH, PLAYER_HOME_FIRST)
    response = await create(flow)
    assert response.status_code == 409 and response.json()["detail"] == "La planilla contiene un jugador suspendido"


@pytest.fixture
def single_yellow_config(monkeypatch):
    config = deepcopy(flow_module.DEFAULT_RULES_CONFIG)
    config["discipline"]["yellow_card_limit"] = 1
    monkeypatch.setattr(flow_module, "DEFAULT_RULES_CONFIG", config)


@pytest.mark.usefixtures("single_yellow_config")
@pytest.mark.parametrize("kind,expected", [("yellow", ["yellow_card_accumulation"]),
    ("double", ["double_yellow_red"]), ("direct", ["direct_red_card", "yellow_card_accumulation"])])
async def test_current_cards_use_configured_accumulation_and_double_yellow_absorption(flow, kind, expected):
    body = proposal()
    for minute in ([18, 19] if kind == "double" else [18]):
        body["proposed_report"]["events"].append({
            "client_event_id": str(uuid4()), "segment_id": SEGMENT_FIRST, "team_id": TEAM_HOME,
            "player_id": PLAYER_HOME_FIRST, "event_type": "yellow_card", "minute": minute})
    if kind != "yellow":
        body["proposed_report"]["events"].append({
            "client_event_id": str(uuid4()), "segment_id": SEGMENT_FIRST, "team_id": TEAM_HOME,
            "player_id": PLAYER_HOME_FIRST, "event_type": "red_card", "minute": 20,
            "metadata": {"red_card_type": "double_yellow_red" if kind == "double" else "direct_red"}})
    request = await submit(flow, body)
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert [row["reason"] for row in await flow.admin.fetch("SELECT reason FROM player_suspensions ORDER BY reason")] == expected
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_effects WHERE effect_type='sanction_created'") == len(expected)


@pytest.fixture
def two_yellow_config(monkeypatch):
    config = deepcopy(flow_module.DEFAULT_RULES_CONFIG)
    config["discipline"]["yellow_card_limit"] = 2
    monkeypatch.setattr(flow_module, "DEFAULT_RULES_CONFIG", config)


@pytest.mark.usefixtures("two_yellow_config")
@pytest.mark.parametrize("minutes", [(15, 15), (30, 10)])
async def test_rectification_accumulation_follows_original_close_report_order(flow, minutes):
    body = proposal()
    cards = [{"client_event_id": identity, "segment_id": SEGMENT_FIRST,
        "team_id": TEAM_HOME, "player_id": PLAYER_HOME_FIRST,
        "event_type": "yellow_card", "minute": minute}
        for identity, minute in zip(["ffffffff-ffff-4fff-8fff-ffffffffffff",
            "00000000-0000-4000-8000-000000000001"], minutes, strict=True)]
    body["proposed_report"]["events"].extend(cards)
    derived = evaluate_suspensions(flow_module.DEFAULT_RULES_CONFIG,
        [{**event, "id": event["client_event_id"]} for event in cards], [])
    expected = str(derived[0]["source_event_id"])
    assert expected == cards[1]["client_event_id"]
    request = await submit(flow, body)
    before = await database_snapshot(flow.admin)
    preview = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert preview.status_code == 200, preview.text
    created = [effect for effect in preview.json()["effects"] if effect["effect_type"] == "sanction_created"]
    assert [effect["payload"]["logical_event_id"] for effect in created] == [expected]
    assert await database_snapshot(flow.admin) == before
    assert (await decide(flow, request)).status_code == 200
    assert await flow.admin.fetchval("""SELECT e.client_event_id FROM player_suspensions s
        JOIN match_report_version_events e ON e.id=s.source_version_event_id""") == expected


@pytest.mark.usefixtures("two_yellow_config")
async def test_reordering_cards_rederives_the_threshold_in_version_three(flow):
    requester = flow.context
    body = proposal()
    cards = [{"client_event_id": identity, "segment_id": SEGMENT_FIRST,
        "team_id": TEAM_HOME, "player_id": PLAYER_HOME_FIRST,
        "event_type": "yellow_card", "minute": 15} for identity in [
            "00000000-0000-4000-8000-000000000001", "ffffffff-ffff-4fff-8fff-ffffffffffff"]]
    body["proposed_report"]["events"].extend(cards)
    request = await submit(flow, body)
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
    flow.context = requester
    body["proposed_report"]["events"][1:] = reversed(cards)
    response = await create(flow, body)
    assert response.status_code == 201, response.text
    flow.context = approver
    response = await decide(flow, response.json()["id"], expected_base_version=2)
    assert response.status_code == 200, response.text
    rows = await flow.admin.fetch("""SELECT e.client_event_id, s.status FROM player_suspensions s
        JOIN match_report_version_events e ON e.id=s.source_version_event_id ORDER BY s.created_at""")
    assert [(row["client_event_id"], row["status"]) for row in rows] == [
        (cards[1]["client_event_id"], "cancelled"), (cards[0]["client_event_id"], "active")]
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspension_annulments") == 1


@pytest.mark.parametrize("flow", [{"events": [
    {"client_event_id": "ffffffff-ffff-4fff-8fff-ffffffffffff", "minute": 15},
    {"client_event_id": "00000000-0000-4000-8000-000000000001", "minute": 15},
]}], indirect=True)
async def test_original_discipline_snapshot_uses_closing_audit_order(flow):
    cards = await flow.admin.fetch("SELECT id, client_event_id FROM match_events WHERE match_id=$1 ORDER BY created_at", MATCH)
    await flow.admin.execute("""INSERT INTO administrative_audit_logs
        (organization_id,entity_type,entity_id,action,payload,performed_by_member_id)
        VALUES ($1,'matches',$2,'CLOSE_MATCH_REPORT',$3::jsonb,$4)""", ORG, MATCH,
        json.dumps({"event_ids": [str(row["id"]) for row in cards]}), flow.context.organization_user_id)
    async with flow.engine.connect() as conn:
        await conn.execute(text("SET ROLE bracket_app"))
        await conn.commit()
        async with AsyncSession(bind=conn) as session, session.begin():
            await set_rls_context(session, flow.context.organization_id, flow.context.user_id)
            snapshot = await capture_discipline(session, flow.context,
                dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", MATCH)))
    assert [row["client_event_id"] for row in snapshot["events"]] == [row["client_event_id"] for row in cards]


@pytest.mark.usefixtures("two_yellow_config")
@pytest.mark.parametrize("flow", [{"events": [
    {"client_event_id": "ffffffff-ffff-4fff-8fff-ffffffffffff", "minute": 15},
    {"client_event_id": "00000000-0000-4000-8000-000000000001", "minute": 15},
]}], indirect=True)
async def test_other_players_cards_do_not_rederive_unchanged_original_sanctions(flow):
    original_cards = await flow.admin.fetch("SELECT id, client_event_id FROM match_events WHERE match_id=$1 ORDER BY created_at", MATCH)
    sanction_id = await flow.admin.fetchval("""INSERT INTO player_suspensions
        (organization_id,source_tournament_id,player_id,origin_match_id,source_event_id,source_type,
         dedupe_key,scope_type,matches_suspended,reason)
        SELECT organization_id,tournament_id,$2,id,$3,'match_event','original-accumulation',
            'organization',1,'yellow_card_accumulation' FROM matches WHERE id=$1 RETURNING id""",
        MATCH, PLAYER_HOME_FIRST, original_cards[1]["id"])
    before = dict(await flow.admin.fetchrow("SELECT * FROM player_suspensions WHERE id=$1", sanction_id))
    body = proposal()
    body["proposed_report"]["events"].extend({"client_event_id": row["client_event_id"],
        "segment_id": SEGMENT_FIRST, "team_id": TEAM_HOME, "player_id": PLAYER_HOME_FIRST,
        "event_type": "yellow_card", "minute": 15} for row in original_cards)
    body["proposed_report"]["events"].append({"client_event_id": str(uuid4()),
        "segment_id": SEGMENT_FIRST, "team_id": TEAM_AWAY, "player_id": PLAYER_AWAY,
        "event_type": "red_card", "minute": 20})
    request = await submit(flow, body)
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert dict(await flow.admin.fetchrow("SELECT * FROM player_suspensions WHERE id=$1", sanction_id)) == before
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspension_annulments") == 0
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspensions") == 2
