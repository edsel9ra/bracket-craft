"""Opt-in PostgreSQL coverage for spec 042 (F11): concurrent draws.

Requires ``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL``. Reuses the spec 006
harness (throwaway database, dedicated role without ``BYPASSRLS``, real route
functions). A barrier holds the ``stages`` row with ``FOR UPDATE`` until every
request is waiting on that lock, so the requests overlap without ``sleep``.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tournaments.routes.matches import (
    draw_stage_schedule,
    generate_single_elimination_matches,
)
from app.modules.tournaments.scheduling import build_round_robin_schedule
from app.modules.tournaments.schemas import GenerateSingleEliminationRequest
from migration_helpers import connect
import test_concurrency_006
from test_concurrency_006 import Harness, _seed_other_tenant

harness = test_concurrency_006.harness

START = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
BARRIER_TIMEOUT_SECONDS = 15


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _add_teams(h: Harness, count: int) -> list[UUID]:
    team_ids = []
    for _ in range(count):
        team_id = uuid4()
        await h.admin.execute(
            "INSERT INTO public.teams (id, organization_id, name, short_code) VALUES ($1, $2, $3, $4)",
            team_id,
            h.organization_id,
            f"Concurrency 042 {team_id.hex[:8]}",
            team_id.hex[:4].upper(),
        )
        await h.admin.execute(
            """
            INSERT INTO public.tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES ($1, $2, $3, 'registered')
            """,
            h.organization_id,
            h.tournament_id,
            team_id,
        )
        team_ids.append(team_id)
    return team_ids


async def _prepare_stage(h: Harness, stage_type: str, team_count: int) -> list[UUID]:
    await h.admin.execute(
        "UPDATE public.stages SET stage_type = $2 WHERE id = $1", h.stage_id, stage_type
    )
    team_ids = list(h.teams) + await _add_teams(h, max(0, team_count - len(h.teams)))
    team_ids = team_ids[:team_count]
    await h.add_stage_teams(team_ids)
    return sorted(team_ids)


def _payload(h: Harness, **fields) -> GenerateSingleEliminationRequest:
    fields.setdefault("seed", 1)
    fields.setdefault("legs", 1)
    return GenerateSingleEliminationRequest(
        version_id=h.version_id, stage_id=h.stage_id, start_date=START, **fields
    )


async def _call(h: Harness, route, payload, *, tournament_id: UUID | None = None):
    async with AsyncSession(h.engine, expire_on_commit=False) as session:
        try:
            response = await route(tournament_id or h.tournament_id, payload, h.context, session)
        except HTTPException as exc:
            return exc.status_code, exc.detail
        return 201, response


async def _draw(h: Harness, **fields):
    return await _call(h, draw_stage_schedule, _payload(h, **fields))


async def _lock_waiters(h: Harness) -> int:
    return await h.admin.fetchval(
        """
        SELECT count(*) FROM pg_stat_activity
        WHERE datname = current_database() AND wait_event_type = 'Lock'
        """
    )


@asynccontextmanager
async def _stage_barrier(h: Harness, database_admin_url: str):
    """Hold the stage row; whatever the holder writes is committed on release."""
    database = await h.admin.fetchval("SELECT current_database()")
    holder = await connect(database_admin_url, database)
    transaction = holder.transaction()
    await transaction.start()
    try:
        await holder.execute("SELECT 1 FROM public.stages WHERE id = $1 FOR UPDATE", h.stage_id)
        yield holder
    except BaseException:
        await transaction.rollback()
        raise
    else:
        await transaction.commit()
    finally:
        await holder.close()


async def _together(h: Harness, database_admin_url: str, *requests, while_held=None):
    """Run every request at once: all of them must be waiting on the stage lock."""
    async with _stage_barrier(h, database_admin_url) as holder:
        tasks = [asyncio.create_task(request) for request in requests]
        deadline = time.monotonic() + BARRIER_TIMEOUT_SECONDS
        while await _lock_waiters(h) < len(tasks):
            assert not any(task.done() for task in tasks), "a request did not wait for the stage lock"
            assert time.monotonic() < deadline, "the requests never met at the stage lock"
            await asyncio.sleep(0.01)
        if while_held is not None:
            await while_held(holder)
    return await asyncio.gather(*tasks)


async def _stage_matches(h: Harness) -> list[asyncpg.Record]:
    return await h.admin.fetch(
        """
        SELECT bracket_code, home_team_id, away_team_id, group_id
        FROM public.matches WHERE organization_id = $1 AND stage_id = $2
        ORDER BY bracket_code
        """,
        h.organization_id,
        h.stage_id,
    )


async def _assert_single_calendar(h: Harness, results) -> None:
    statuses = sorted(status for status, _ in results)
    assert statuses == [201, 409], results
    winner = next(body for status, body in results if status == 201)
    rows = await _stage_matches(h)
    codes = [row["bracket_code"] for row in rows]
    assert len(set(codes)) == len(codes)
    if winner.stage_type == "swiss":
        # Later Swiss rounds are stored as empty placeholders.
        rows = [row for row in rows if row["bracket_code"].startswith("SW1-")]
    assert len(rows) == winner.match_count


# ---------------------------------------------------------------------------
# two cold draws: one calendar, one 409 (RF-001, RF-002)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage_type", "team_count", "extra"),
    [
        ("round_robin", 4, {}),
        ("custom_group", 4, {"group_count": 2}),
        ("single_elimination", 4, {}),
        ("double_elimination", 4, {}),
        ("swiss", 4, {"swiss_rounds": 3}),
    ],
)
async def test_two_cold_draws_produce_one_calendar(harness, database_admin_url, stage_type, team_count, extra):
    await _prepare_stage(harness, stage_type, team_count)

    results = await _together(
        harness,
        database_admin_url,
        _draw(harness, seed=1, **extra),
        _draw(harness, seed=2, **extra),
    )

    await _assert_single_calendar(harness, results)


@pytest.mark.asyncio
async def test_two_cold_single_elimination_generations_produce_one_bracket(harness, database_admin_url):
    await _prepare_stage(harness, "single_elimination", 4)

    results = await _together(
        harness,
        database_admin_url,
        _call(harness, generate_single_elimination_matches, _payload(harness, seed=1)),
        _call(harness, generate_single_elimination_matches, _payload(harness, seed=2)),
    )

    await _assert_single_calendar(harness, results)


# ---------------------------------------------------------------------------
# later Swiss round (RF-004)
# ---------------------------------------------------------------------------


FINISH_MATCHES = """
    UPDATE public.matches
    SET status = 'finished', result_confirmed = TRUE, resolution_type = 'regular',
        home_score_regular = 1, away_score_regular = 0, home_score = 1, away_score = 0,
        winner_team_id = home_team_id
    WHERE organization_id = $1 AND stage_id = $2 AND bracket_code LIKE $3
"""


@pytest.mark.asyncio
async def test_two_requests_for_the_same_later_swiss_round_apply_once(harness, database_admin_url):
    await _prepare_stage(harness, "swiss", 4)
    status, _ = await _draw(harness, swiss_rounds=3)
    assert status == 201
    assert await harness.publish() == 200
    await harness.admin.execute(FINISH_MATCHES, harness.organization_id, harness.stage_id, "SW1-%")
    before = await _stage_matches(harness)
    round_one = [row for row in before if row["bracket_code"].startswith("SW1-")]

    results = await _together(
        harness,
        database_admin_url,
        _draw(harness, swiss_rounds=3, swiss_round=2, seed=1),
        _draw(harness, swiss_rounds=3, swiss_round=2, seed=2),
    )

    assert sorted(status for status, _ in results) == [201, 409], results
    rows = await _stage_matches(harness)
    codes = [row["bracket_code"] for row in rows]
    assert len(set(codes)) == len(codes) == len(before)
    round_two = [row for row in rows if row["bracket_code"].startswith("SW2-")]
    assert len(round_two) == 2
    assert all(row["home_team_id"] and row["away_team_id"] for row in round_two)
    previous = {frozenset((r["home_team_id"], r["away_team_id"])) for r in round_one}
    assert not previous & {frozenset((r["home_team_id"], r["away_team_id"])) for r in round_two}


# ---------------------------------------------------------------------------
# draw against manual creation (RF-005)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draw_and_manual_match_are_serialized(harness, database_admin_url):
    team_ids = await _prepare_stage(harness, "round_robin", 4)

    draw_result, manual_status = await _together(
        harness,
        database_admin_url,
        _draw(harness),
        harness.create_match(team_ids[0], team_ids[1]),
    )

    assert sorted([draw_result[0], manual_status]) == [201, 409], (draw_result, manual_status)
    rows = await _stage_matches(harness)
    if draw_result[0] == 201:
        assert len(rows) == draw_result[1].match_count
    else:
        assert len(rows) == 1
        assert rows[0]["bracket_code"] is None


@pytest.mark.asyncio
async def test_manual_match_after_a_draw_counts_generated_matches(harness):
    team_ids = await _prepare_stage(harness, "round_robin", 4)
    assert (await _draw(harness))[0] == 201

    assert await harness.create_match(team_ids[0], team_ids[1]) == 409


@pytest.mark.asyncio
async def test_draw_after_a_manual_match_without_replacement_is_409(harness):
    team_ids = await _prepare_stage(harness, "round_robin", 4)
    assert await harness.create_match(team_ids[0], team_ids[1]) == 201

    status, detail = await _draw(harness)

    assert status == 409
    assert "ya tiene partidos" in detail
    assert len(await _stage_matches(harness)) == 1


# ---------------------------------------------------------------------------
# two replacements: applied one after the other, the last one stays (RF-003)
# ---------------------------------------------------------------------------


def _expected_round_robin(team_ids: list[UUID], seed: int) -> set[tuple]:
    schedule = build_round_robin_schedule(
        team_ids, seed=seed, start_date=START, round_interval_days=7, match_interval_hours=2, legs=1
    )
    return {(m.code, m.home_team_id, m.away_team_id) for m in schedule.matches}


@pytest.mark.asyncio
async def test_two_replacements_apply_in_sequence_and_the_last_one_stays(harness, database_admin_url):
    team_ids = await _prepare_stage(harness, "round_robin", 4)
    assert (await _draw(harness, seed=1))[0] == 201

    results = await _together(
        harness,
        database_admin_url,
        _draw(harness, seed=2, replace_existing=True),
        _draw(harness, seed=3, replace_existing=True),
    )

    assert [status for status, _ in results] == [201, 201], results
    final = {(r["bracket_code"], r["home_team_id"], r["away_team_id"]) for r in await _stage_matches(harness)}
    candidates = [_expected_round_robin(team_ids, seed) for seed in (2, 3)]
    assert candidates[0] != candidates[1]
    assert final in candidates
    assert len(final) == len(candidates[0])


@pytest.mark.asyncio
async def test_two_swiss_round_one_replacements_never_mix_matches(harness, database_admin_url):
    # Swiss computes the pairings outside the stage lock and revalidates them
    # under it, so the second replacement sees a changed stage and gets 409.
    await _prepare_stage(harness, "swiss", 4)
    status, first = await _draw(harness, swiss_rounds=3, seed=1)
    assert status == 201
    before = len(await _stage_matches(harness))

    results = await _together(
        harness,
        database_admin_url,
        _draw(harness, swiss_rounds=3, seed=2, replace_existing=True),
        _draw(harness, swiss_rounds=3, seed=3, replace_existing=True),
    )

    assert sorted(status for status, _ in results) == [201, 409], results
    rows = await _stage_matches(harness)
    codes = [row["bracket_code"] for row in rows]
    assert len(set(codes)) == len(codes) == before
    round_one = [row for row in rows if row["bracket_code"].startswith("SW1-")]
    assert len(round_one) == first.match_count
    teams = [team for row in round_one for team in (row["home_team_id"], row["away_team_id"])]
    assert len(set(teams)) == len(teams) == 4


@pytest.mark.asyncio
async def test_replacement_waiting_behind_a_closed_report_is_409(harness, database_admin_url):
    await _prepare_stage(harness, "round_robin", 4)
    assert (await _draw(harness, seed=1))[0] == 201
    before = await _stage_matches(harness)

    async def close_report(holder):
        await holder.execute(FINISH_MATCHES, harness.organization_id, harness.stage_id, "RR1-1")

    [(status, _)] = await _together(
        harness,
        database_admin_url,
        _draw(harness, seed=2, replace_existing=True),
        while_held=close_report,
    )

    assert status == 409
    assert await _stage_matches(harness) == before


# ---------------------------------------------------------------------------
# tenant isolation (RF-010)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draw_on_another_organization_stage_is_404_and_writes_nothing(harness):
    other = await _seed_other_tenant(harness.admin)
    payload = GenerateSingleEliminationRequest(
        version_id=other["version_id"], stage_id=other["stage_id"], start_date=START, seed=1, legs=1
    )

    status, _ = await _call(harness, draw_stage_schedule, payload, tournament_id=other["tournament_id"])

    assert status == 404
    assert await harness.admin.fetchval(
        "SELECT count(*) FROM public.matches WHERE stage_id = $1", other["stage_id"]
    ) == 0


# ---------------------------------------------------------------------------
# database guarantee without the application lock (RF-007)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_direct_inserts_of_the_same_code_keep_one_row(harness, database_admin_url):
    database = await harness.admin.fetchval("SELECT current_database()")
    first = await connect(database_admin_url, database)
    second = await connect(database_admin_url, database)
    insert = """
        INSERT INTO public.matches (organization_id, tournament_id, tournament_version_id, stage_id, bracket_code, status)
        VALUES ($1, $2, $3, $4, 'RR1-1', 'scheduled')
    """
    args = (harness.organization_id, harness.tournament_id, harness.version_id, harness.stage_id)
    try:
        transaction = first.transaction()
        await transaction.start()
        await first.execute(insert, *args)
        pending = asyncio.create_task(second.execute(insert, *args))
        while await _lock_waiters(harness) < 1:
            assert not pending.done()
            await asyncio.sleep(0.01)
        await transaction.commit()
        with pytest.raises(asyncpg.UniqueViolationError):
            await pending
    finally:
        await first.close()
        await second.close()
    assert len(await _stage_matches(harness)) == 1
