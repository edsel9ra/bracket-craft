"""Publication effects share the preview transaction and preserve original reports."""

from copy import deepcopy
import json
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.standings.service import StandingsService
from test_migration_031 import MATCH, ORG, PLAYER_AWAY, SEGMENT_FIRST, STAGE, TEAM_AWAY, TEAM_HOME, TOURNAMENT
import test_rectification_flow as flow_module
from test_rectification_flow import add_approver, create, database_snapshot, decide, proposal
from test_rectification_flow import flow as flow


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
