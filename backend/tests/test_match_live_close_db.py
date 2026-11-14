"""B1 review receipts do not confirm or freeze the report."""

import pytest
from fastapi import HTTPException

from app.modules.matches.live_schemas import LiveReviewRequest, LiveResultDTO
from test_match_live_db import live_service_db as live_service_db, command
from test_migration_056 import SEGMENT_FIRST
from test_match_live_db import goal
from app.modules.matches.live_policy import review_fingerprint
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.matches.service import CloseMatchReportService
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from test_match_live_db import MATCH
import asyncio
from dataclasses import replace
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.modules.advancement.service import AdvancementService
import app.modules.matches.service as closing
import app.modules.matches.live_service as operating
from app.modules.rectifications.service import RectificationService
from app.modules.rectifications.schemas import (
    CreateRectificationRequest,
    RectificationDecisionRequest,
)
from test_rectification_flow import add_approver


async def close_live(f, receipt, *, result=None, session_id=None, context=None):
    values = (result or request().result).model_dump(exclude={"events"})
    dto = CloseMatchReportDTO(**values, live_review_id=receipt)
    async with AsyncSession(f.engine) as db:
        return await CloseMatchReportService(db).execute(
            context or f.context,
            UUID(MATCH),
            dto,
            session_id=session_id or f.session_id,
        )


@pytest.mark.parametrize("with_goal", [False, True])
async def test_consolidation_canonical_report_from_server(live_service_db, with_goal):
    f = live_service_db
    if with_goal:
        await f.call("execute", command("add_event", event=goal()))
    else:
        await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    candidate = request(int(with_goal), home=int(with_goal))
    reviewed = await f.call("create_review", candidate)
    await f.permissions(["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT"])
    result = await close_live(f, reviewed["live_review_id"], result=candidate.result)
    assert result["home_score"] == int(with_goal)
    row = await f.admin.fetchrow(
        "SELECT status,result_confirmed FROM matches WHERE id=$1", MATCH
    )
    assert row["status"] == "finished" and row["result_confirmed"]
    frozen = await f.admin.fetchrow(
        "SELECT frozen_at,clock_state FROM match_live_state WHERE match_id=$1", MATCH
    )
    assert frozen["frozen_at"] is not None and frozen["clock_state"] != "running"
    assert await f.admin.fetchval(
        "SELECT count(*) FROM match_events WHERE match_id=$1", MATCH
    ) == int(with_goal)
    if with_goal:
        assert await f.admin.fetchval(
            "SELECT client_event_id FROM match_events WHERE match_id=$1", MATCH
        ) == str(reviewed["report"].events[0].client_event_id)


@pytest.mark.parametrize(
    "change", ["event", "result", "session", "unknown", "view", "close", "revoked"]
)
async def test_validate_review_rejects_stale_or_unauthorized(live_service_db, change):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    candidate = request(1, home=1)
    review = await f.call("create_review", candidate)
    receipt = review["live_review_id"]
    session_id = f.session_id
    if change == "event":
        await f.call(
            "execute",
            command(
                "correct_event",
                1,
                event_id=event["client_event_id"],
                event={**event, "minute": 6},
            ),
        )
    elif change == "result":
        candidate = request(1)
    elif change == "session":
        session_id = uuid4()
        await f.admin.execute(
            "INSERT INTO user_sessions(id,user_id,expires_at) VALUES ($1,$2,'2099-01-01')",
            session_id,
            f.context.user_id,
        )
    elif change == "unknown":
        receipt = uuid4()
    elif change in {"view", "close"}:
        await f.permissions(
            ["CLOSE_MATCH_REPORT"] if change == "view" else ["VIEW_MATCH_LIVE_DRAFT"]
        )
    else:
        await f.admin.execute(
            "UPDATE user_sessions SET revoked_at=now() WHERE id=$1", f.session_id
        )
    with pytest.raises((HTTPException, PermissionError)):
        await close_live(f, receipt, result=candidate.result, session_id=session_id)
    assert not await f.admin.fetchval(
        "SELECT result_confirmed FROM matches WHERE id=$1", MATCH
    )
    assert await f.admin.fetchval("SELECT frozen_at FROM match_live_state") is None
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0


async def test_validate_review_clock_correction_does_not_invalidate(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    review = await f.call("create_review", request())
    await f.call(
        "execute",
        command("correct_clock", 1, segment_id=SEGMENT_FIRST, elapsed_us=20000000),
    )
    await close_live(f, review["live_review_id"])


async def test_canonical_report_excludes_removed_events(live_service_db):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    await f.call(
        "execute", command("remove_event", 1, event_id=event["client_event_id"])
    )
    review = await f.call("create_review", request(2))
    await close_live(f, review["live_review_id"])
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0
    assert (
        await f.admin.fetchval(
            "SELECT count(*) FROM match_live_events WHERE removed_at IS NOT NULL"
        )
        == 1
    )


@pytest.mark.parametrize("point", ["sanctions", "advancement", "outbox"])
async def test_consolidation_rollback_restores_draft(
    live_service_db, monkeypatch, point
):
    f = live_service_db
    await f.call("execute", command("add_event", event=goal()))
    candidate = request(1, home=1)
    review = await f.call("create_review", candidate)

    async def fail(*args, **kwargs):
        raise RuntimeError("late close failure")

    def fail_sync(*args, **kwargs):
        raise RuntimeError("late close failure")

    if point == "sanctions":
        monkeypatch.setattr(closing, "evaluate_suspensions", fail_sync)
    elif point == "advancement":
        monkeypatch.setattr(AdvancementService, "advance_from_match", fail)
    else:
        monkeypatch.setattr(closing, "enqueue_outbox", fail)
    before = await f.admin.fetchval("SELECT count(*) FROM outbox_events")
    with pytest.raises(RuntimeError, match="late close failure"):
        await close_live(f, review["live_review_id"], result=candidate.result)
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0
    assert await f.admin.fetchval("SELECT frozen_at FROM match_live_state") is None
    assert await f.admin.fetchval("SELECT count(*) FROM outbox_events") == before
    assert not await f.admin.fetchval(
        "SELECT result_confirmed FROM matches WHERE id=$1", MATCH
    )


async def test_consolidation_concurrency_double_close(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    review = await f.call("create_review", request())
    results = await asyncio.gather(
        *(close_live(f, review["live_review_id"]) for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(isinstance(item, Exception) for item in results) == 1


async def test_classic_consolidation_regression_without_live_state(live_service_db):
    f = live_service_db
    async with AsyncSession(f.engine) as db:
        result = await CloseMatchReportService(db).execute(
            f.context,
            UUID(MATCH),
            CloseMatchReportDTO(
                resolution_type="regular", home_score_regular=0, away_score_regular=0
            ),
        )
    assert result["status"] == "success"
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0


@pytest.mark.parametrize("first", ["close", "edit"])
async def test_consolidation_concurrency_close_vs_edit(
    live_service_db, monkeypatch, first
):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    review = await f.call("create_review", request())
    ready, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    owner, method = (
        (CloseMatchReportService, "_persist_events")
        if first == "close"
        else (operating.LiveMatchService, "_record_command")
    )
    original = getattr(owner, method)

    async def hold(*args, **kwargs):
        ready.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(owner, method, hold)
    waiter_module = operating if first == "close" else closing
    original_lock = waiter_module.lock_discipline

    async def signal_lock(*args, **kwargs):
        attempted.set()
        return await original_lock(*args, **kwargs)

    monkeypatch.setattr(waiter_module, "lock_discipline", signal_lock)

    async def edit():
        return await f.call("execute", command("add_event", 1, event=goal()))

    leading = asyncio.create_task(
        close_live(f, review["live_review_id"]) if first == "close" else edit()
    )
    try:
        await asyncio.wait_for(ready.wait(), 10)
        trailing = asyncio.create_task(
            edit() if first == "close" else close_live(f, review["live_review_id"])
        )
        await asyncio.wait_for(attempted.wait(), 10)
    finally:
        release.set()
    results = await asyncio.wait_for(
        asyncio.gather(leading, trailing, return_exceptions=True), 20
    )
    assert not isinstance(results[0], Exception) and isinstance(
        results[1], HTTPException
    )
    assert results[1].status_code == 409
    assert await f.admin.fetchval(
        "SELECT result_confirmed FROM matches WHERE id=$1", MATCH
    ) is (first == "close")


async def test_concurrency_confirmed_live_report_requires_033(live_service_db):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    candidate = request(1, home=1)
    review = await f.call("create_review", candidate)
    await close_live(f, review["live_review_id"], result=candidate.result)
    original_events = await f.admin.fetch("SELECT * FROM match_events ORDER BY id")
    original_live = await f.admin.fetch("SELECT * FROM match_live_state")
    with pytest.raises(HTTPException):
        await f.call("execute", command("add_event", 1, event=goal()))
    async with AsyncSession(f.engine) as db:
        with pytest.raises(DBAPIError):
            async with db.begin():
                await closing.set_rls_context(
                    db, f.context.organization_id, f.context.user_id
                )
                await db.execute(
                    text("UPDATE match_events SET minute=0 WHERE match_id=:match"),
                    {"match": UUID(MATCH)},
                )
    proposed = review["report"].model_dump(mode="json")
    proposed["events"][0]["minute"] = 0
    async with AsyncSession(f.engine) as db:
        change = await RectificationService(db).create(
            f.context,
            UUID(MATCH),
            CreateRectificationRequest(
                proposed_report=proposed, reason="Fix minute", evidence="Video"
            ),
        )
    approver = await add_approver(f)
    async with AsyncSession(f.engine) as db:
        decision = await RectificationService(db).decide(
            approver,
            change["id"],
            RectificationDecisionRequest(
                decision="approve", reason="Verified", expected_base_version=1
            ),
        )
    assert decision["status"] == "published"
    assert (
        await f.admin.fetch("SELECT * FROM match_events ORDER BY id") == original_events
    )
    assert await f.admin.fetch("SELECT * FROM match_live_state") == original_live
    assert (
        await f.admin.fetchval(
            "SELECT max(version_number) FROM match_report_versions WHERE match_id=$1",
            MATCH,
        )
        == 2
    )


@pytest.mark.parametrize("foreign", [False, True])
async def test_validate_review_another_actor_or_tenant(live_service_db, foreign):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    review = await f.call("create_review", request())
    actor = await add_approver(f)
    session_id = uuid4()
    await f.admin.execute(
        "INSERT INTO user_sessions(id,user_id,expires_at) VALUES($1,$2,'2099-01-01')",
        session_id,
        actor.user_id,
    )
    if foreign:
        actor = replace(
            actor,
            organization_id=UUID(
                str(actor.organization_id).replace("31000000", "32000000")
            ),
        )
    with pytest.raises(LookupError if foreign else HTTPException):
        await close_live(
            f, review["live_review_id"], session_id=session_id, context=actor
        )
    assert await f.admin.fetchval("SELECT frozen_at FROM match_live_state") is None


async def test_consolidation_effects_once_with_discipline(live_service_db):
    f = live_service_db
    card = goal()
    card.update(event_type="red_card", metadata={"red_card_type": "direct_red"})
    await f.call("execute", command("add_event", event=card))
    review = await f.call("create_review", request(1))
    await close_live(f, review["live_review_id"])
    assert (
        await f.admin.fetchval(
            "SELECT count(*) FROM player_suspensions WHERE origin_match_id=$1", MATCH
        )
        == 1
    )
    effects = await f.admin.fetch("SELECT to_jsonb(s) FROM standings s ORDER BY id")
    notices = await f.admin.fetch("SELECT id FROM outbox_events ORDER BY id")
    with pytest.raises(ValueError):
        await close_live(f, review["live_review_id"])
    assert (
        await f.admin.fetch("SELECT to_jsonb(s) FROM standings s ORDER BY id")
        == effects
    )
    assert await f.admin.fetch("SELECT id FROM outbox_events ORDER BY id") == notices
    assert (
        await f.admin.fetchval(
            "SELECT count(*) FROM player_suspensions WHERE origin_match_id=$1", MATCH
        )
        == 1
    )


async def test_validate_review_required_for_classic_attempt(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    async with AsyncSession(f.engine) as db:
        with pytest.raises(HTTPException) as error:
            await CloseMatchReportService(db).execute(
                f.context,
                UUID(MATCH),
                CloseMatchReportDTO(
                    resolution_type="regular",
                    home_score_regular=0,
                    away_score_regular=0,
                ),
            )
    assert (
        error.value.status_code == 409 and error.value.detail == "LIVE_REVIEW_REQUIRED"
    )


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
