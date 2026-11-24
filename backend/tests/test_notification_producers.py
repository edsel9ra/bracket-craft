"""Productores de avisos (spec 046, T3: RF-001–RF-004).

Opt-in con ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL``: cada caso usa una
base desechable con todas las migraciones y llama a las rutas reales, que
abren y confirman su propia transacción.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.tournaments.routes.matches import (
    create_match,
    draw_stage_schedule,
    generate_single_elimination_matches,
)
from app.modules.tournaments.schemas import (
    CreateMatchRequest,
    GenerateSingleEliminationRequest,
)
from migration_helpers import connect, throwaway_database
from test_match_assists_db import (
    close,
    committed_application,
    goal_and_red_report,
    report_of,
    seeded_match,
)
from test_tournament_scheduling import (
    PAIRING_SEED_SQL,
    STAGE_CUP,
    STAGE_ONE_LEG,
    STAGE_SWISS,
    START_DATE,
    TEAM_ONE,
    TEAM_TWO,
    TOURNAMENT,
    USER,
    VERSION,
    async_database_url,
    pairing_context,
)

NOTICE_SQL = """
SELECT n.notification_type, n.tournament_id, n.match_id, n.suspension_id, n.match_count,
       array_agg(r.user_id::text || ':' || r.channel ORDER BY r.user_id, r.channel) AS recipients
FROM notifications n JOIN notification_recipients r ON r.notification_id = n.id
GROUP BY n.id ORDER BY n.created_at, n.notification_type, n.suspension_id
"""


@pytest.fixture
async def schedule(database_admin_url):
    async with throwaway_database(database_admin_url, last=999) as admin:
        await admin.execute(PAIRING_SEED_SQL)
        database = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(async_database_url(database_admin_url, database))
        try:
            yield admin, engine
        finally:
            await engine.dispose()


def schedule_request(stage_id, **extra):
    return GenerateSingleEliminationRequest(
        version_id=UUID(VERSION),
        stage_id=UUID(stage_id),
        start_date=START_DATE,
        seed=7,
        legs=1,
        **extra,
    )


async def call(engine, route, payload):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            return await route(UUID(TOURNAMENT), payload, pairing_context(), session)
        except HTTPException as exc:
            return exc


async def notices(admin):
    return [dict(row) for row in await admin.fetch(NOTICE_SQL)]


async def stage_count(admin, stage_id):
    return await admin.fetchval(
        "SELECT count(*) FROM matches WHERE stage_id=$1", UUID(stage_id)
    )


def scheduled(count):
    return {
        "notification_type": "match_scheduled",
        "tournament_id": UUID(TOURNAMENT),
        "match_id": None,
        "suspension_id": None,
        "match_count": count,
        "recipients": [f"{USER}:inbox"],
    }


async def test_league_draw_records_one_notice_with_the_match_count(schedule):
    admin, engine = schedule
    response = await call(engine, draw_stage_schedule, schedule_request(STAGE_ONE_LEG))
    assert response.match_count == await stage_count(admin, STAGE_ONE_LEG) > 1
    assert await notices(admin) == [scheduled(response.match_count)]
    events = await admin.fetch(
        "SELECT event_type FROM outbox_events WHERE event_type LIKE 'NOTIFICATION_%'"
    )
    assert [row["event_type"] for row in events] == ["NOTIFICATION_INBOX"]


async def test_bracket_generation_and_draw_record_one_notice_each(schedule):
    admin, engine = schedule
    first = await call(
        engine, generate_single_elimination_matches, schedule_request(STAGE_CUP)
    )
    second = await call(
        engine, draw_stage_schedule, schedule_request(STAGE_CUP, replace_existing=True)
    )
    assert await notices(admin) == [
        scheduled(first.match_count),
        scheduled(second.match_count),
    ]


async def test_swiss_round_records_one_notice(schedule):
    admin, engine = schedule
    response = await call(
        engine, draw_stage_schedule, schedule_request(STAGE_SWISS, swiss_rounds=1)
    )
    assert not isinstance(response, HTTPException), response.detail
    assert await notices(admin) == [scheduled(response.match_count)]


async def test_manual_match_records_a_notice_for_one_match(schedule):
    admin, engine = schedule
    payload = CreateMatchRequest(
        version_id=UUID(VERSION),
        stage_id=UUID(STAGE_ONE_LEG),
        home_team_id=UUID(TEAM_ONE),
        away_team_id=UUID(TEAM_TWO),
        match_date=START_DATE,
    )
    response = await call(engine, create_match, payload)
    assert not isinstance(response, HTTPException), response.detail
    assert await notices(admin) == [scheduled(1)]


async def test_a_rejected_draw_records_no_notice(schedule):
    admin, engine = schedule
    await call(engine, draw_stage_schedule, schedule_request(STAGE_ONE_LEG))
    error = await call(engine, draw_stage_schedule, schedule_request(STAGE_ONE_LEG))
    assert isinstance(error, HTTPException) and error.status_code == 409
    assert len(await notices(admin)) == 1


async def close_notices(database_admin_url, engine):
    admin = await connect(database_admin_url, engine.url.database)
    try:
        return await notices(admin), await admin.fetch(
            "SELECT id FROM player_suspensions ORDER BY created_at, id"
        )
    finally:
        await admin.close()


async def test_regular_close_records_result_and_one_notice_per_suspension(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        await close(engine, context, match.match_id, goal_and_red_report(match))
        rows, suspensions = await close_notices(database_admin_url, engine)
    assert suspensions
    member = f"{context.user_id}:inbox"
    assert [
        (r["notification_type"], r["match_id"], r["match_count"], r["recipients"])
        for r in rows
    ] == [("result_confirmed", match.match_id, None, [member])] + [
        ("sanction_generated", match.match_id, None, [member])
    ] * len(suspensions)
    assert {r["suspension_id"] for r in rows[1:]} == {s["id"] for s in suspensions}
    assert all(r["tournament_id"] == match.tournament_id for r in rows)


async def test_close_without_suspensions_records_only_the_result(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        await close(engine, context, match.match_id, report_of(home_score_regular=0))
        rows, suspensions = await close_notices(database_admin_url, engine)
    assert suspensions == []
    assert [r["notification_type"] for r in rows] == ["result_confirmed"]


async def test_walkover_records_its_own_notice(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        dto = CloseMatchReportDTO(
            resolution_type="walkover",
            winner_team_id=match.home_team_id,
            reason="no_show",
        )
        await close(engine, context, match.match_id, dto)
        rows, _ = await close_notices(database_admin_url, engine)
    assert [(r["notification_type"], r["match_id"]) for r in rows] == [
        ("walkover_declared", match.match_id)
    ]


async def test_a_rejected_close_records_no_notice(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        await close(engine, context, match.match_id, report_of(home_score_regular=0))
        with pytest.raises(HTTPException):
            await close(
                engine, context, match.match_id, report_of(home_score_regular=0)
            )
        rows, _ = await close_notices(database_admin_url, engine)
    assert [r["notification_type"] for r in rows] == ["result_confirmed"]
