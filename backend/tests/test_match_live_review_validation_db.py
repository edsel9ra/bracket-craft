"""Review receipts use the same validation as report closure."""

import pytest
from fastapi import HTTPException

from app.modules.matches.live_schemas import LiveReviewRequest, LiveResultDTO
from test_match_live_db import live_service_db as live_service_db, command, goal
from test_migration_056 import ORG, SEGMENT_FIRST, TEAM_HOME


async def initialize(f):
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    await f.call("execute", command("pause_clock", 1))


async def test_walkover_review_needs_close_not_administrative(live_service_db):
    f = live_service_db
    await initialize(f)
    await f.admin.execute(
        "UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='operator') WHERE organization_id=$1",
        ORG,
    )
    await f.permissions(["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT"])
    result = await f.call(
        "create_review",
        LiveReviewRequest(
            expected_content_revision=0,
            result=LiveResultDTO(
                resolution_type="walkover", winner_team_id=TEAM_HOME, reason="no_show"
            ),
        ),
    )
    assert result["report"].resolution_type == "walkover"
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 1


async def test_administrative_review_still_requires_administrative_permission(
    live_service_db,
):
    f = live_service_db
    await initialize(f)
    await f.permissions(["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT"])
    with pytest.raises(HTTPException) as error:
        await f.call(
            "create_review",
            LiveReviewRequest(
                expected_content_revision=0,
                result=LiveResultDTO(
                    resolution_type="administrative",
                    home_score_regular=0,
                    away_score_regular=0,
                    home_score=3,
                    away_score=0,
                    winner_team_id=TEAM_HOME,
                    reason="Decision",
                ),
            ),
        )
    assert error.value.status_code == 403
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 0


@pytest.mark.parametrize(
    "live_service_db", [{"stage_override": {"extra_time_enabled": True}}], indirect=True
)
async def test_review_uses_effective_stage_resolution(live_service_db):
    f = live_service_db
    await initialize(f)
    event = goal()
    await f.call("execute", command("add_event", 2, event={**event, "minute": 91}))
    result = await f.call(
        "create_review",
        LiveReviewRequest(
            expected_content_revision=1,
            result=LiveResultDTO(
                resolution_type="extra_time",
                home_score_regular=0,
                away_score_regular=0,
                home_score=1,
                away_score=0,
                winner_team_id=TEAM_HOME,
            ),
        ),
    )
    assert result["report"].resolution_type == "extra_time"
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 1
