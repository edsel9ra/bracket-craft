"""B1 review receipts do not confirm or freeze the report."""

import pytest
from fastapi import HTTPException

from app.modules.matches.live_schemas import LiveReviewRequest, LiveResultDTO
from test_match_live_db import live_service_db as live_service_db, command
from test_migration_056 import SEGMENT_FIRST
from test_match_live_db import goal
from app.modules.matches.live_policy import review_fingerprint


def request(revision=0, home=0):
    return LiveReviewRequest(
        expected_content_revision=revision,
        result=LiveResultDTO(
            resolution_type="regular", home_score_regular=home, away_score_regular=0
        ),
    )


async def test_create_review_empty_complete_receipt(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    result = await f.call("create_review", request())
    assert result["report"].events == [] and result["content_revision"] == 0
    receipt = await f.admin.fetchrow(
        "SELECT * FROM match_live_reviews WHERE id=$1", result["live_review_id"]
    )
    assert (
        receipt["actor_user_id"] == f.context.user_id
        and receipt["session_id"] == f.session_id
    )
    assert await f.admin.fetchval("SELECT frozen_at FROM match_live_state") is None
    assert not await f.admin.fetchval("SELECT result_confirmed FROM matches LIMIT 1")
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0


@pytest.mark.parametrize(
    "permissions",
    [["VIEW_MATCH_LIVE_DRAFT"], ["CLOSE_MATCH_REPORT"], ["OPERATE_MATCH_LIVE"]],
)
async def test_create_review_needs_view_and_close(live_service_db, permissions):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    await f.permissions(permissions)
    with pytest.raises(HTTPException) as error:
        await f.call("create_review", request())
    assert error.value.status_code == 403
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 0


async def test_create_review_invalid_result_or_stale_content(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    for body in (request(home=3), request(revision=1)):
        with pytest.raises(HTTPException):
            await f.call("create_review", body)
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 0


async def test_create_review_complete_events_fingerprint_and_no_clock_invalidation(
    live_service_db,
):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    result = await f.call("create_review", request(1, home=1))
    receipt = await f.admin.fetchrow(
        "SELECT * FROM match_live_reviews WHERE id=$1", result["live_review_id"]
    )
    assert len(result["report"].events) == 1
    assert receipt["fingerprint"] == review_fingerprint(
        tuple(result["report"].events), request(1, home=1).result, 1
    )
    assert result["fingerprint"] == receipt["fingerprint"]
    await f.call("execute", command("start_clock", 1, segment_id=SEGMENT_FIRST))
    second = await f.call("create_review", request(1, home=1))
    assert second["report"] == result["report"]
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 2
