"""Publication effects share the preview transaction and preserve original reports."""

from copy import deepcopy
import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.standings.service import StandingsService
from test_migration_031 import MATCH, ORG, PLAYER_AWAY, SEGMENT_FIRST, STAGE, TEAM_AWAY, TEAM_HOME, TOURNAMENT
import test_rectification_flow as flow_module
from test_rectification_flow import add_approver, create, database_snapshot, decide, proposal
from test_rectification_flow import flow as flow

TARGET = "31000000-0000-4000-8000-000000000070"
LATER = "31000000-0000-4000-8000-000000000071"


def reversed_report():
    body = proposal(home_score_regular=0, away_score_regular=1, home_score=0, away_score=1, winner_team_id=TEAM_AWAY)
    body["proposed_report"]["events"][0].update(team_id=TEAM_AWAY, player_id=PLAYER_AWAY)
    return body


async def fail_d4(state, condition):
    if condition == "segments":
        await state.admin.execute("""INSERT INTO match_segments (organization_id,match_id,segment_number,minute_start)
            VALUES ($1,$2,1,0)""", ORG, TARGET)
    elif condition == "confirmed":
        await state.admin.execute("""UPDATE matches SET status='finished',result_confirmed=TRUE,
            resolution_type='regular',home_score=0,away_score=0,home_score_regular=0,away_score_regular=0 WHERE id=$1""", TARGET)
    elif condition == "status":
        await state.admin.execute("UPDATE matches SET status='live' WHERE id=$1", TARGET)
    elif condition == "later_phase":
        assert await state.admin.fetchval("SELECT count(*) FROM stage_teams WHERE stage_id=$1", LATER) == 1


async def slot_effect(state, version, new_team):
    link = await state.admin.fetchrow("SELECT * FROM advancement_links WHERE source_match_id=$1", MATCH)
    prior = await state.admin.fetchrow("SELECT * FROM match_slot_assignments WHERE match_id=$1 ORDER BY assigned_at DESC,id DESC LIMIT 1", TARGET)
    return {"effect_type": "advancement", "entity_type": "match", "entity_id": TARGET,
        "payload": {"original_match_id": MATCH, "version_id": str(version["id"]), "source_match_id": MATCH,
            "target_match_id": TARGET, "side": "home", "advancement_link_id": str(link["id"]),
            "before_assignment_id": str(prior["id"]), "before_team_id": str(prior["team_id"]),
            "after_team_id": new_team}}


@pytest.mark.parametrize("flow", [{"advancement": {"outcome": outcome, "side": side}}
    for outcome in ["winner", "loser"] for side in ["home", "away"]], indirect=True)
async def test_d4_winner_and_loser_preview_publication_and_next_version(flow):
    requester = flow.context
    foreign = await flow.admin.fetch("SELECT * FROM matches WHERE organization_id<>$1 ORDER BY id", ORG)
    original = dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", MATCH))
    old = dict(await flow.admin.fetchrow("SELECT * FROM match_slot_assignments WHERE match_id=$1", TARGET))
    column = f"{old['side']}_team_id"
    expected = TEAM_AWAY if old["team_id"] == UUID(TEAM_HOME) else TEAM_HOME
    request = await pending(flow, reversed_report())
    approver = flow.context
    before = await database_snapshot(flow.admin)
    preview = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert preview.status_code == 200, preview.text
    advancement = [e for e in preview.json()["effects"] if e["effect_type"] == "advancement"]
    assert len(advancement) == 1 and advancement[0]["payload"]["after_team_id"] == expected
    assert await database_snapshot(flow.admin) == before
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert str((await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", TARGET))[column]) == expected
    assert dict(await flow.admin.fetchrow("SELECT * FROM match_slot_assignments WHERE id=$1", old["id"])) == old
    assigned = await flow.admin.fetchrow("SELECT * FROM match_slot_assignments WHERE match_id=$1 AND origin='rectification'", TARGET)
    assert str(assigned["match_report_version_id"]) == response.json()["resulting_version_id"]
    assert assigned["advancement_link_id"] == old["advancement_link_id"]
    assert assigned["team_id"] == UUID(expected)
    assert dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", MATCH)) == original
    flow.context = requester
    created = await create(flow, proposal())
    assert created.status_code == 201, created.text
    request = created.json()["id"]
    flow.context = approver
    response = await decide(flow, request, expected_base_version=2)
    assert response.status_code == 200, response.text
    assert (await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", TARGET))[column] == old["team_id"]
    assert await flow.admin.fetchval("SELECT count(*) FROM match_slot_assignments WHERE match_id=$1", TARGET) == 3
    assert await flow.admin.fetch("SELECT * FROM matches WHERE organization_id<>$1 ORDER BY id", ORG) == foreign


@pytest.mark.parametrize("flow", [{"advancement": {"both_sides": True}}], indirect=True)
async def test_d4_both_sides_are_swapped_atomically(flow):
    request = await pending(flow, reversed_report())
    before = await database_snapshot(flow.admin)
    preview = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert preview.status_code == 200, preview.text
    assert len([e for e in preview.json()["effects"] if e["effect_type"] == "advancement"]) == 2
    assert await database_snapshot(flow.admin) == before
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    target = await flow.admin.fetchrow("SELECT home_team_id,away_team_id FROM matches WHERE id=$1", TARGET)
    assert tuple(target) == (UUID(TEAM_AWAY), UUID(TEAM_HOME))
    assert await flow.admin.fetchval("SELECT count(*) FROM match_slot_assignments WHERE match_id=$1", TARGET) == 4


@pytest.mark.parametrize("flow", [{"advancement": {"both_sides": True, "manual_side": "away"}}], indirect=True)
async def test_d4_unsafe_partial_swap_is_an_impact_not_a_failed_publication(flow, monkeypatch):
    from app.modules.rectifications import effects
    observed = []
    async def hook(db, context, version, candidates, now):
        observed.extend(candidates)
        return []
    monkeypatch.setattr(effects, "apply_competitive_impacts", hook)
    before = dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", TARGET))
    assignments = await flow.admin.fetch("SELECT * FROM match_slot_assignments WHERE match_id=$1 ORDER BY id", TARGET)
    request = await pending(flow, reversed_report())
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert {candidate.reason for candidate in observed} == {"manual", "opponent_conflict"}
    assert dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", TARGET)) == before
    assert await flow.admin.fetch("SELECT * FROM match_slot_assignments WHERE match_id=$1 ORDER BY id", TARGET) == assignments


@pytest.mark.parametrize("flow", [{"advancement": {}}], indirect=True)
@pytest.mark.parametrize("operation", ["preview", "decision"])
async def test_d4_failure_after_substitution_rolls_back_all_tables(flow, monkeypatch, operation):
    from app.modules.rectifications import effects
    substitute = effects.substitute_slots
    async def fail(db, context, changes):
        await substitute(db, context, changes)
        assert (await db.execute(text("SELECT home_team_id FROM matches WHERE id=:id"), {"id": UUID(TARGET)})).scalar_one() == UUID(TEAM_AWAY)
        raise ValueError("advancement rollback")
    monkeypatch.setattr(effects, "substitute_slots", fail)
    request = await pending(flow, reversed_report())
    before = await database_snapshot(flow.admin)
    response = await flow.client.get(f"/api/v1/rectifications/{request}/preview") if operation == "preview" else await decide(flow, request)
    assert response.status_code == 409 and response.json()["detail"] == "advancement rollback"
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("flow", [{"advancement": {}}], indirect=True)
async def test_d4_cannot_reuse_a_committed_publication_context(flow):
    request = await pending(flow, reversed_report())
    version_id = await flow.admin.fetchval("""INSERT INTO match_report_versions
        (organization_id,match_id,version_number,supersedes_version_number,resolution_type,
         home_score_regular,away_score_regular,home_score,away_score,winner_team_id,request_id,published_by_user_id)
        VALUES ($1,$2,2,1,'regular',0,1,0,1,$3,$4,$5) RETURNING id""",
        ORG,MATCH,TEAM_AWAY,request,flow.context.user_id)
    effect = await slot_effect(flow, {"id": version_id}, TEAM_AWAY)
    await flow.admin.execute("""INSERT INTO match_report_rectification_effects
        (organization_id,version_id,effect_type,entity_type,entity_id,payload)
        VALUES ($1,$2,'advancement','match',$3,$4::jsonb)""", ORG,version_id,TARGET,json.dumps(effect["payload"]))
    async with flow.engine.connect() as connection:
        await connection.execute(text("SET ROLE bracket_app"))
        await connection.commit()
        async with AsyncSession(bind=connection) as db, db.begin():
            await set_rls_context(db, flow.context.organization_id, flow.context.user_id)
            await db.execute(text("SELECT set_config('app.rectification_version_id',:id,true)"), {"id": str(version_id)})
            with pytest.raises(DBAPIError, match="La estructura de un partido publicado o archivado es inmutable"):
                async with db.begin_nested():
                    await db.execute(text("UPDATE matches SET home_team_id=:team WHERE id=:target"), {"team": UUID(TEAM_AWAY), "target": UUID(TARGET)})


@pytest.mark.parametrize("flow", [{"advancement": {"later_phase": True, "no_link": True}}], indirect=True)
async def test_d4_phase_order_changes_deliver_impact_without_an_advancement_link(flow, monkeypatch):
    from app.modules.rectifications import effects
    observed = []
    async def hook(db, context, version, candidates, now):
        observed.extend(candidates)
        return []
    monkeypatch.setattr(effects, "apply_competitive_impacts", hook)
    await recalculate(flow)
    request = await pending(flow, reversed_report())
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert len(observed) == 1 and observed[0].stage_id == UUID(LATER)
    assert observed[0].reason == "later_phase" and observed[0].match_id is None


@pytest.mark.parametrize("flow", [{"advancement": {"reset": True}}], indirect=True)
async def test_d4_grand_final_reset_is_an_impact_not_an_implicit_activation(flow, monkeypatch):
    from app.modules.rectifications import effects
    observed = []
    async def hook(db, context, version, candidates, now):
        observed.extend(candidates)
        return []
    monkeypatch.setattr(effects, "apply_competitive_impacts", hook)
    request = await pending(flow, reversed_report())
    before = dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", TARGET))
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert len(observed) == 1 and observed[0].reason == "bracket_reset" and observed[0].match_id == UUID(TARGET)
    assert dict(await flow.admin.fetchrow("SELECT * FROM matches WHERE id=$1", TARGET)) == before


@pytest.mark.parametrize("condition", ["segments", "confirmed", "status", "later_phase"])
@pytest.mark.parametrize("flow", [{"advancement": {}}], indirect=True)
async def test_d4_failed_condition_delivers_typed_impact_without_substitution(flow, monkeypatch, condition):
    from app.modules.rectifications import effects
    from app.modules.rectifications.advancement import AdvancementImpactCandidate
    await fail_d4(flow, condition)
    before = [dict(r) for r in await flow.admin.fetch("SELECT * FROM match_slot_assignments ORDER BY id")]
    observed = []
    async def hook(db, context, version, candidates, now):
        assert db.in_transaction()
        observed.extend(candidates)
        return []
    monkeypatch.setattr(effects, "apply_competitive_impacts", hook)
    request = await pending(flow, reversed_report())
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert len(observed) == 1 and isinstance(observed[0], AdvancementImpactCandidate)
    assert str(observed[0].match_id) == TARGET and observed[0].reason == condition
    assert await flow.admin.fetchval("SELECT home_team_id FROM matches WHERE id=$1", TARGET) == UUID(TEAM_HOME)
    assert [dict(r) for r in await flow.admin.fetch("SELECT * FROM match_slot_assignments ORDER BY id")] == before
    assert await flow.admin.fetchval("SELECT count(*) FROM competitive_impact_procedures") == 0


@pytest.mark.parametrize("flow", [{"advancement": {"origin": "manual"}}, {"advancement": {"wrong_origin": True}}], indirect=True)
async def test_d4_immutable_provenance_failures_are_impact_candidates(flow, monkeypatch):
    from app.modules.rectifications import effects
    from app.modules.rectifications.advancement import AdvancementImpactCandidate
    observed = []
    async def hook(db, context, version, candidates, now):
        observed.extend(candidates)
        return []
    monkeypatch.setattr(effects, "apply_competitive_impacts", hook)
    old = await flow.admin.fetchval("SELECT home_team_id FROM matches WHERE id=$1", TARGET)
    request = await pending(flow, reversed_report())
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert len(observed) == 1 and isinstance(observed[0], AdvancementImpactCandidate)
    assert await flow.admin.fetchval("SELECT home_team_id FROM matches WHERE id=$1", TARGET) == old


@pytest.mark.parametrize("condition", ["segments", "confirmed", "status", "later_phase", "no_context", "invalid_context",
    "wrong_team", "no_effect", "wrong_trace", "starting_during_update", "confirming_during_update"])
@pytest.mark.parametrize("flow", [{"advancement": {}}], indirect=True)
async def test_d4_trigger_rejects_each_invalid_condition(flow, monkeypatch, condition):
    from app.modules.rectifications import effects
    await fail_d4(flow, condition)
    async def forbidden(db, context, version, now):
        effect = await slot_effect(flow, version, TEAM_AWAY)
        if condition == "wrong_trace":
            effect["payload"]["side"] = "away"
        if condition != "no_effect":
            await effects.record_effect(db, context, version["id"], effect, now)
        with pytest.raises(DBAPIError, match="La estructura de un partido publicado o archivado es inmutable"):
            async with db.begin_nested():
                if condition == "no_context":
                    await db.execute(text("SELECT set_config('app.rectification_version_id','',true)"))
                elif condition == "invalid_context":
                    await db.execute(text("SELECT set_config('app.rectification_version_id','invalid',true)"))
                statement = "UPDATE matches SET home_team_id=:team WHERE id=:id"
                if condition == "starting_during_update":
                    statement = "UPDATE matches SET home_team_id=:team,status='live' WHERE id=:id"
                elif condition == "confirming_during_update":
                    statement = """UPDATE matches SET home_team_id=:team,status='finished',result_confirmed=TRUE,
                        resolution_type='regular',home_score=0,away_score=0,home_score_regular=0,away_score_regular=0 WHERE id=:id"""
                await db.execute(text(statement), {"id": UUID(TARGET),
                    "team": UUID("31000000-0000-4000-8000-000000000072") if condition == "wrong_team" else UUID(TEAM_AWAY)})
        return []
    monkeypatch.setattr(effects, "apply_effects", forbidden)
    monkeypatch.setattr("app.modules.rectifications.service.apply_effects", forbidden)
    request = await pending(flow, reversed_report())
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert await flow.admin.fetchval("SELECT home_team_id FROM matches WHERE id=$1", TARGET) == UUID(TEAM_HOME)


@pytest.mark.parametrize("flow", [{"advancement": {"origin": "manual"}}, {"advancement": {"wrong_origin": True}}], indirect=True)
async def test_d4_trigger_rejects_manual_or_inconsistent_provenance(flow, monkeypatch):
    from app.modules.rectifications import effects
    old = await flow.admin.fetchval("SELECT home_team_id FROM matches WHERE id=$1", TARGET)
    team = TEAM_AWAY if old == UUID(TEAM_HOME) else TEAM_HOME
    async def forbidden(db, context, version, now):
        await effects.record_effect(db, context, version["id"], await slot_effect(flow, version, team), now)
        with pytest.raises(DBAPIError, match="La estructura de un partido publicado o archivado es inmutable"):
            async with db.begin_nested():
                await db.execute(text("UPDATE matches SET home_team_id=:team WHERE id=:id"),
                    {"id": UUID(TARGET), "team": UUID(team)})
        return []
    monkeypatch.setattr("app.modules.rectifications.service.apply_effects", forbidden)
    request = await pending(flow, reversed_report() if team == TEAM_AWAY else proposal())
    assert (await decide(flow, request)).status_code == 200


@pytest.fixture
def draw_enabled():
    return True


@pytest.fixture(autouse=True)
def ranking_config(monkeypatch, draw_enabled):
    config = deepcopy(flow_module.DEFAULT_RULES_CONFIG)
    if draw_enabled:
        config["ranking_pipeline"].append({"step": 6, "criterion": "random_draw", "params": {}})
    monkeypatch.setattr(flow_module, "DEFAULT_RULES_CONFIG", config)


async def recalculate(state):
    async with state.engine.connect() as connection:
        await connection.execute(text("SET ROLE bracket_app"))
        await connection.commit()
        async with AsyncSession(bind=connection) as db, db.begin():
            await set_rls_context(db, state.context.organization_id, state.context.user_id)
            await StandingsService(db).recalculate(state.context, UUID(TOURNAMENT), UUID(STAGE))


async def standings(state):
    rows = await state.admin.fetch("""
        SELECT team_id, played, points, goals_for, goals_against, goal_difference, rank
        FROM standings WHERE organization_id = $1 ORDER BY team_id
    """, ORG)
    return {str(row["team_id"]): dict(row) for row in rows}


async def pending(state, body=None):
    response = await create(state, body)
    assert response.status_code == 201, response.text
    state.context = await add_approver(state)
    return response.json()["id"]


async def test_preview_and_publication_recalculate_and_record_invalidated_draw(flow):
    await recalculate(flow)
    await flow.admin.execute("""
        INSERT INTO standings (organization_id, tournament_id, stage_id, team_id, points, rank)
        SELECT organization_id, tournament_id, stage_id, team_id, 42, 42
        FROM stage_teams WHERE organization_id <> $1
    """, ORG)
    foreign = await flow.admin.fetch("SELECT * FROM standings WHERE organization_id <> $1 ORDER BY team_id", ORG)
    original = await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH)
    request = await pending(flow)
    before = await database_snapshot(flow.admin)
    preview = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert preview.status_code == 200, preview.text
    effects = preview.json()["effects"]
    assert [effect["effect_type"] for effect in effects] == ["standings", "tiebreak_draw_invalidated"]
    assert effects[0]["entity_type"] == "stage" and effects[0]["entity_id"] == STAGE
    assert effects[1]["payload"] == {"group_id": None,
        "before_team_ids": [TEAM_HOME, TEAM_AWAY], "after_team_groups": []}
    assert await database_snapshot(flow.admin) == before
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    table = await standings(flow)
    assert (table[TEAM_HOME]["points"], table[TEAM_HOME]["goals_for"], table[TEAM_HOME]["rank"]) == (3, 1, 1)
    assert (table[TEAM_AWAY]["points"], table[TEAM_AWAY]["goals_against"], table[TEAM_AWAY]["rank"]) == (0, 1, 2)
    recorded = await flow.admin.fetch("""
        SELECT effect_type, entity_type, entity_id::text, payload
        FROM match_report_rectification_effects WHERE version_id = $1 ORDER BY effect_type
    """, response.json()["resulting_version_id"])
    assert [{**dict(row), "payload": json.loads(row["payload"])} for row in recorded] == effects
    assert await flow.admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH) == original
    assert await flow.admin.fetchval("SELECT count(*) FROM match_events") == 0
    assert await flow.admin.fetch("SELECT * FROM standings WHERE organization_id <> $1 ORDER BY team_id", ORG) == foreign
    after = await database_snapshot(flow.admin)
    for name in before.keys() - {"standings", "match_report_versions", "match_report_version_events",
            "match_report_rectification_effects", "match_report_rectification_requests",
            "match_report_rectification_decisions", "administrative_audit_logs"}:
        assert after[name] == before[name], name


async def test_unchanged_draw_members_are_not_invalidated(flow):
    await recalculate(flow)
    ranks = {team: row["rank"] for team, row in (await standings(flow)).items()}
    body = proposal(away_score_regular=1, away_score=1, winner_team_id=None)
    body["proposed_report"]["events"].append({**body["proposed_report"]["events"][0],
        "client_event_id": "aaaaaaaa-0000-4000-8000-000000000001", "team_id": TEAM_AWAY,
        "player_id": PLAYER_AWAY, "segment_id": SEGMENT_FIRST, "minute": 20})
    request = await pending(flow, body)
    preview = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert preview.status_code == 200, preview.text
    assert [effect["effect_type"] for effect in preview.json()["effects"]] == ["standings"]
    assert (await decide(flow, request)).status_code == 200
    assert {row["points"] for row in (await standings(flow)).values()} == {1}
    assert {team: row["rank"] for team, row in (await standings(flow)).items()} == ranks
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_effects") == 1


async def test_fair_play_changes_from_current_events_invalidate_the_old_draw(flow):
    await recalculate(flow)
    body = proposal(home_score_regular=0, home_score=0, winner_team_id=None)
    body["proposed_report"]["events"][0]["event_type"] = "yellow_card"
    request = await pending(flow, body)
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert await flow.admin.fetchval("SELECT fair_play_points FROM standings WHERE team_id = $1", TEAM_HOME) == -1
    assert (await standings(flow))[TEAM_AWAY]["rank"] == 1
    assert await flow.admin.fetchval("""
        SELECT count(*) FROM match_report_rectification_effects WHERE effect_type = 'tiebreak_draw_invalidated'
    """) == 1


async def test_nonranking_event_change_keeps_draw_and_standings_values(flow):
    await recalculate(flow)
    before = await standings(flow)
    body = proposal(home_score_regular=0, home_score=0, winner_team_id=None)
    body["proposed_report"]["events"][0]["event_type"] = "foul"
    request = await pending(flow, body)
    response = await decide(flow, request)
    assert response.status_code == 200, response.text
    assert await standings(flow) == before
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_effects") == 1


async def test_version_three_recalculates_from_latest_report_not_original(flow):
    await recalculate(flow)
    requester = flow.context
    first = await pending(flow)
    assert (await decide(flow, first)).status_code == 200
    approver = flow.context
    flow.context = requester
    body = proposal(home_score_regular=0, home_score=0, away_score_regular=1,
        away_score=1, winner_team_id=TEAM_AWAY)
    body["proposed_report"]["events"][0].update(team_id=TEAM_AWAY, player_id=PLAYER_AWAY)
    second = await create(flow, body)
    assert second.status_code == 201 and second.json()["base_version_number"] == 2, second.text
    flow.context = approver
    response = await decide(flow, second.json()["id"], expected_base_version=2)
    assert response.status_code == 200, response.text
    table = await standings(flow)
    assert (table[TEAM_HOME]["points"], table[TEAM_HOME]["goals_for"], table[TEAM_HOME]["goals_against"]) == (0, 0, 1)
    assert (table[TEAM_AWAY]["points"], table[TEAM_AWAY]["rank"]) == (3, 1)
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_rectification_effects") == 3
    original = await flow.admin.fetchrow("SELECT home_score, away_score FROM matches WHERE id = $1", MATCH)
    assert tuple(original.values()) == (0, 0)


@pytest.mark.parametrize("persisted,draw_enabled", [(False, True), (True, False)])
async def test_no_resolved_draw_without_persisted_standings_or_draw_criterion(flow, persisted, draw_enabled):
    if persisted:
        await recalculate(flow)
    request = await pending(flow)
    response = await flow.client.get(f"/api/v1/rectifications/{request}/preview")
    assert response.status_code == 200, response.text
    assert [effect["effect_type"] for effect in response.json()["effects"]] == ["standings"]


@pytest.mark.parametrize("operation", ["preview", "decision"])
async def test_failure_after_effect_insert_rolls_back_every_table(flow, monkeypatch, operation):
    from app.modules.rectifications import effects

    await recalculate(flow)
    request = await pending(flow)
    before = await database_snapshot(flow.admin)
    record = effects.record_effect

    async def fail(*args, **kwargs):
        await record(*args, **kwargs)
        db = args[0]
        assert (await db.execute(text("SELECT count(*) FROM match_report_rectification_effects"))).scalar_one() == 1
        raise ValueError("effect insert rollback")

    monkeypatch.setattr(effects, "record_effect", fail)
    response = (await flow.client.get(f"/api/v1/rectifications/{request}/preview")
        if operation == "preview" else await decide(flow, request))
    assert response.status_code == 409 and response.json()["detail"] == "effect insert rollback"
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("after,expected", [([], [[]]),
    ([["a", "b"]], []), ([["a", "c"], ["b", "d"]], [[["a", "c"], ["b", "d"]]])])
def test_invalidated_groups_preserve_members_before_and_after(after, expected):
    from app.modules.rectifications.effects import invalidated_draws

    before = [{"group_id": None, "team_ids": ["a", "b"]}]
    current = [{"group_id": None, "team_ids": group} for group in after]
    assert [item["after_team_groups"] for item in invalidated_draws(before, current)] == expected


def test_empty_draw_groups_have_no_invalidations():
    from app.modules.rectifications.effects import invalidated_draws

    assert invalidated_draws([], []) == []


def test_each_removed_group_is_recorded_without_unrelated_new_groups():
    from app.modules.rectifications.effects import invalidated_draws

    before = [{"group_id": "group", "team_ids": group} for group in [["a", "b"], ["c", "d"], ["e", "f"]]]
    after = [{"group_id": "group", "team_ids": group} for group in [["b", "a"], ["g", "h"]]]
    assert invalidated_draws(before, after) == [
        {"group_id": "group", "before_team_ids": members, "after_team_groups": []}
        for members in [["c", "d"], ["e", "f"]]]
