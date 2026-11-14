"""Automatic segment pauses must not confer ordinary live-operation grants."""

import asyncpg
import pytest

from migration_helpers import apply_migrations, apply_migration, throwaway_database
from test_migration_056 import app, seed, state, ORG, MATCH, SEGMENT_FIRST


@pytest.fixture
async def segment_db(database_admin_url):
    async with throwaway_database(database_admin_url, last=56) as db:
        await seed(db)
        async with app(db):
            await state(db)
            await db.execute(
                "UPDATE match_segments SET status='active',minute_end=NULL WHERE id=$1",
                SEGMENT_FIRST,
            )
            await db.execute(
                "UPDATE match_live_state SET segment_id=$1,clock_state='running',clock_anchor_at=now()-interval '5 seconds'",
                SEGMENT_FIRST,
            )
        await db.execute(
            "UPDATE roles SET permissions='[\"CLOSE_MATCH_REPORT\"]' WHERE organization_id=$1",
            ORG,
        )
        await apply_migrations(db, first=57)
        yield db


@pytest.mark.parametrize("status", ["interrupted", "completed"])
async def test_segment_pause_close_without_view_or_operate(segment_db, status):
    db = segment_db
    async with app(db):
        assert await db.fetchval(
            "SELECT match_live_has_permission($1,$2,'CLOSE_MATCH_REPORT')", ORG, MATCH
        )
        assert not await db.fetchval(
            "SELECT match_live_has_permission($1,$2,'OPERATE_MATCH_LIVE')", ORG, MATCH
        )
        assert not await db.fetchval(
            "SELECT match_live_has_permission($1,$2,'VIEW_MATCH_LIVE_DRAFT')",
            ORG,
            MATCH,
        )
        await db.execute(
            "UPDATE match_segments SET status=$1,minute_end=5 WHERE id=$2",
            status,
            SEGMENT_FIRST,
        )
        row = await db.fetchrow("SELECT * FROM match_live_state")
        assert row["clock_state"] == "paused"
        assert row["clock_elapsed_us"] >= 5_000_000
        assert row["clock_anchor_at"] is None
        assert row["revision"] == 1 and row["content_revision"] == 0
        assert row["frozen_at"] is None


@pytest.mark.parametrize(
    "assignment",
    [
        "clock_state='paused',clock_anchor_at=NULL",
        "home_score=1",
        "revision=revision+1",
        "frozen_at=now(),clock_state='paused',clock_anchor_at=NULL",
    ],
)
async def test_segment_close_does_not_grant_live_operations(segment_db, assignment):
    with pytest.raises(asyncpg.PostgresError):
        async with app(segment_db):
            await segment_db.execute(f"UPDATE match_live_state SET {assignment}")


async def test_segment_close_requires_permission_and_tenant(segment_db):
    db = segment_db
    async with app(db, org=ORG.replace("31000000", "32000000")):
        assert (
            await db.execute(
                "UPDATE match_segments SET status='interrupted',minute_end=5 WHERE id=$1",
                SEGMENT_FIRST,
            )
            == "UPDATE 0"
        )
    await db.execute("UPDATE roles SET permissions='[]' WHERE organization_id=$1", ORG)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(db):
            await db.execute(
                "UPDATE match_segments SET status='interrupted',minute_end=5 WHERE id=$1",
                SEGMENT_FIRST,
            )


async def test_segment_pause_migration_idempotent(segment_db):
    db = segment_db
    before = await db.fetch("SELECT to_jsonb(s) FROM match_live_state s")
    await apply_migration(db, 57)
    await apply_migration(db, 57)
    assert await db.fetch("SELECT to_jsonb(s) FROM match_live_state s") == before
    rows = await db.fetch(
        "SELECT prosecdef FROM pg_proc WHERE proname IN ('validate_match_live_write','validate_match_live_segment','pause_match_live_segment')"
    )
    assert len(rows) == 3 and not any(row["prosecdef"] for row in rows)


async def test_segment_pause_migration_clean(database_admin_url):
    async with throwaway_database(database_admin_url, last=57) as db:
        assert (
            await db.fetchval(
                "SELECT count(*) FROM pg_trigger WHERE tgname='trg_pause_match_live_segment'"
            )
            == 1
        )
