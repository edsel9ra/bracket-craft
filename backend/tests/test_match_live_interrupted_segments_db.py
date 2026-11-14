"""Interrupted segments retain provisional facts until explicit repair."""

from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.matches.router import create_match_segment, interrupt_match_segment
from app.modules.matches.schemas import (
    CreateMatchSegmentRequest,
    InterruptMatchSegmentRequest,
)
from test_match_live_close_db import close_live, request
from test_match_live_db import command, goal, live_service_db as live_service_db
from test_migration_056 import MATCH, SEGMENT_FIRST


async def interrupt_and_reopen(f):
    async with AsyncSession(f.engine) as db:
        await interrupt_match_segment(
            UUID(MATCH),
            UUID(SEGMENT_FIRST),
            InterruptMatchSegmentRequest(reason="weather", minute=5),
            f.context,
            db,
        )
    async with AsyncSession(f.engine) as db:
        return await create_match_segment(
            UUID(MATCH),
            CreateMatchSegmentRequest(segment_number=3, minute_start=90),
            f.context,
            db,
        )


async def test_review_rejects_interrupted_facts_that_cannot_close(live_service_db):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    candidate = request(1, home=1)
    receipt = await f.call("create_review", candidate)
    await interrupt_and_reopen(f)
    with pytest.raises(ValueError, match="segmento interrumpido"):
        await close_live(f, receipt["live_review_id"], result=candidate.result)
    with pytest.raises(HTTPException) as error:
        await f.call("create_review", candidate)
    assert error.value.status_code == 422
    snapshot = await f.call("snapshot")
    assert snapshot.content_revision == 1 and snapshot.home_score == 1
    assert len(snapshot.events) == 1
    assert snapshot.events[0].client_event_id == event["client_event_id"]
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_reviews") == 1
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0
    assert await f.admin.fetchval("SELECT frozen_at FROM match_live_state") is None


@pytest.mark.parametrize("repair", ["remove_event", "correct_event"])
async def test_explicit_repair_of_interrupted_facts_allows_review_and_close(
    live_service_db, repair
):
    f = live_service_db
    events = [goal(), goal()]
    for revision, event in enumerate(events):
        await f.call("execute", command("add_event", revision, event=event))
    segment = await interrupt_and_reopen(f)
    for event in events:
        snapshot = await f.call("snapshot")
        body = {"event_id": event["client_event_id"]}
        if repair == "correct_event":
            body["event"] = {**event, "segment_id": segment["id"], "minute": 90}
        await f.call("execute", command(repair, snapshot.revision, **body))
    candidate = request(4, home=2 if repair == "correct_event" else 0)
    receipt = await f.call("create_review", candidate)
    await close_live(f, receipt["live_review_id"], result=candidate.result)
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_events") == 2
    confirmed = await f.admin.fetch(
        "SELECT client_event_id,segment_id FROM match_events"
    )
    if repair == "correct_event":
        assert {row["client_event_id"] for row in confirmed} == {
            event["client_event_id"] for event in events
        }
        assert all(str(row["segment_id"]) == str(segment["id"]) for row in confirmed)
    else:
        assert confirmed == []


async def test_interrupted_segment_without_facts_does_not_block_empty_close(
    live_service_db,
):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    await interrupt_and_reopen(f)
    receipt = await f.call("create_review", request())
    await close_live(f, receipt["live_review_id"])
    assert await f.admin.fetchval(
        "SELECT result_confirmed FROM matches WHERE id=$1", MATCH
    )
