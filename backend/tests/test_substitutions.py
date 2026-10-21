"""Opt-in PostgreSQL coverage for closing reports with substitutions (T005).

Requires ``RUN_DATABASE_TESTS=1`` and a database at schema 021. The bulk of the
suite runs inside the ``db_session`` fixture (application role, rolled back);
the concurrency case builds its own throwaway database from the real ``init``
scripts and migrations 1..21, with a dedicated role that inherits
``bracket_app``, so the shared role is never altered.

Covered: persistence of ``player_out_id``/``player_in_id``, the per-segment
projection with its accumulated balance, re-entry, limits, the
``client_event_id`` idempotency, rejection before writing, ``GET /operation``
without writes and two simultaneous closes.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.matches.router import get_match_operation
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import NO_LINEUP_NOTICE, CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from db_helpers import (
    TenantContext,
    create_tenant_owner,
    insert_player,
    set_tenant_context,
)
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)

MATCH_DATE = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


def rules_config(**substitutions: object) -> dict:
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "regular_time_minutes": 90,
        "extra_time_minutes": 120,
    }
    config["substitutions"] = {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
        **substitutions,
    }
    return config


def substitution(
    out_id: UUID,
    in_id: UUID,
    *,
    team_id: UUID,
    segment_id: UUID,
    minute: int,
    client_event_id: str,
) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=client_event_id,
        event_type="substitution",
        team_id=team_id,
        player_id=out_id,
        player_out_id=out_id,
        player_in_id=in_id,
        minute=minute,
        segment_id=segment_id,
    )


def goal(
    player_id: UUID,
    *,
    team_id: UUID,
    segment_id: UUID,
    minute: int,
    client_event_id: str,
) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=client_event_id,
        event_type="goal",
        team_id=team_id,
        player_id=player_id,
        minute=minute,
        segment_id=segment_id,
    )


def report(events: list[MatchEventPayload], *, home: int = 0, away: int = 0) -> CloseMatchReportDTO:
    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=home,
        away_score_regular=away,
        home_score=home,
        away_score=away,
        events=events,
    )


def minutes_config(
    *,
    regular: int,
    extra: int,
    extra_time_enabled: bool = True,
    **substitutions: object,
) -> dict:
    config = rules_config(**substitutions)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "regular_time_minutes": regular,
        "extra_time_minutes": extra,
        "extra_time_enabled": extra_time_enabled,
    }
    return config


@dataclass(frozen=True)
class ClosableMatch:
    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    match_id: UUID
    segment_1: UUID
    segment_2: UUID
    home_team_id: UUID
    away_team_id: UUID
    home_starters: tuple[UUID, ...]
    home_substitutes: tuple[UUID, ...]


async def _create_tournament(session, tenant: TenantContext, *, config: dict) -> tuple[UUID, UUID, UUID]:
    payload = json.dumps(config)
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', '2026-01-01', 'draft',
                     CAST(:config AS jsonb))
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T005 {uuid4().hex[:8]}",
                "config": payload,
            },
        )
    ).scalar_one()
    version_id = (
        await session.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config,
                     phase_config, status, created_by_member_id)
                VALUES
                    (:organization_id, :tournament_id, 1, CAST(:config AS jsonb),
                     '{}'::jsonb, 'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
                "config": payload,
            },
        )
    ).scalar_one()
    stage_id = (
        await session.execute(
            text("""
                INSERT INTO stages
                    (organization_id, tournament_id, tournament_version_id, name,
                     stage_type, stage_order)
                VALUES
                    (:organization_id, :tournament_id, :version_id, 'Group stage',
                     'round_robin', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
            },
        )
    ).scalar_one()
    return tournament_id, version_id, stage_id


async def _register_team(session, tenant: TenantContext, tournament_id: UUID, version_id: UUID, stage_id: UUID, *, label: str) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T005 {label} {uuid4().hex[:6]}",
                "short_code": f"T{uuid4().hex[:5].upper()}",
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    await session.execute(
        text("""
            INSERT INTO stage_teams
                (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
            VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :team_id)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _add_lineup_player(
    session,
    tenant: TenantContext,
    *,
    tournament_id: UUID,
    match_id: UUID,
    team_id: UUID,
    role: str,
    dorsal_number: int,
) -> UUID:
    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name=f"T005{dorsal_number}",
        last_name=team_id.hex[:4],
        reference_year=2026,
    )
    roster_id = (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, :dorsal_number,
                     FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": dorsal_number,
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO match_rosters
                (organization_id, match_id, roster_id, player_id, team_id, role, is_valid)
            VALUES
                (:organization_id, :match_id, :roster_id, :player_id, :team_id, :role, TRUE)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "roster_id": str(roster_id),
            "player_id": str(player_id),
            "team_id": str(team_id),
            "role": role,
        },
    )
    return player_id


async def create_closable_match(
    session,
    tenant: TenantContext,
    *,
    config: dict | None = None,
    with_lineup: bool = True,
) -> ClosableMatch:
    """Create a published match with two segments and an initial XI per team."""

    await set_tenant_context(session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, config=config or rules_config()
    )
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id, label="home"
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id, label="away"
    )
    match_id = (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'scheduled', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()
    segment_1 = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 45, 'completed')
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "match_id": str(match_id)},
        )
    ).scalar_one()
    segment_2 = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, status)
                VALUES (:organization_id, :match_id, 2, 45, 'active')
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "match_id": str(match_id)},
        )
    ).scalar_one()

    home_starters: list[UUID] = []
    home_substitutes: list[UUID] = []
    if with_lineup:
        for index in range(1, 12):
            home_starters.append(
                await _add_lineup_player(
                    session,
                    tenant,
                    tournament_id=tournament_id,
                    match_id=match_id,
                    team_id=home_team_id,
                    role="starter",
                    dorsal_number=index,
                )
            )
        for index in range(12, 15):
            home_substitutes.append(
                await _add_lineup_player(
                    session,
                    tenant,
                    tournament_id=tournament_id,
                    match_id=match_id,
                    team_id=home_team_id,
                    role="substitute",
                    dorsal_number=index,
                )
            )
        for index in range(1, 12):
            await _add_lineup_player(
                session,
                tenant,
                tournament_id=tournament_id,
                match_id=match_id,
                team_id=away_team_id,
                role="starter",
                dorsal_number=index,
            )
        for index in range(12, 15):
            await _add_lineup_player(
                session,
                tenant,
                tournament_id=tournament_id,
                match_id=match_id,
                team_id=away_team_id,
                role="substitute",
                dorsal_number=index,
            )

    await session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
        """),
        {"version_id": str(version_id)},
    )
    await session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :tournament_id
        """),
        {"tournament_id": str(tournament_id), "version_id": str(version_id)},
    )
    return ClosableMatch(
        tenant=tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        match_id=match_id,
        segment_1=segment_1,
        segment_2=segment_2,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_starters=tuple(home_starters),
        home_substitutes=tuple(home_substitutes),
    )


async def _count(session, sql: str, **params) -> int:
    return (await session.execute(text(sql), params)).scalar_one()


async def _state_rows(session, match_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            text("""
                SELECT ms.segment_number, st.team_id, st.substitutions_remaining,
                       st.substitution_windows_remaining
                FROM match_segment_team_state st
                JOIN match_segments ms
                  ON ms.id = st.segment_id AND ms.match_id = st.match_id
                WHERE st.match_id = :match_id
                ORDER BY ms.segment_number, st.team_id
            """),
            {"match_id": str(match_id)},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _insert_event(
    session,
    tenant: TenantContext,
    match: ClosableMatch,
    *,
    client_event_id: str,
    out_id: UUID,
    in_id: UUID,
    minute: int,
    segment_id: UUID,
) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO match_events
                    (organization_id, match_id, segment_id, team_id, player_id,
                     player_out_id, player_in_id, event_type, minute, added_minute,
                     client_event_id)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                     :player_out_id, :player_in_id, 'substitution', :minute, 0,
                     :client_event_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match.match_id),
                "segment_id": str(segment_id),
                "team_id": str(match.home_team_id),
                "player_id": str(out_id),
                "player_out_id": str(out_id),
                "player_in_id": str(in_id),
                "minute": minute,
                "client_event_id": client_event_id,
            },
        )
    ).scalar_one()


@asynccontextmanager
async def committed_application(database_admin_url):
    """Throwaway database at 021 plus a dedicated role that inherits the app role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc005_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1, last=21)
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')
        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.close()
        await drop_database(database_admin_url, database)
        cleaner = await connect(database_admin_url)
        try:
            await cleaner.execute(f'DROP ROLE IF EXISTS "{role_name}"')
        finally:
            await cleaner.close()


async def seeded_match(
    engine,
    *,
    config: dict | None = None,
    with_lineup: bool = True,
) -> tuple[AuthContext, ClosableMatch]:
    """Create and commit one published match visible to independent sessions."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="T005 committed")
        match = await create_closable_match(
            session, tenant, config=config, with_lineup=with_lineup
        )
        await session.commit()
    return context_for(tenant), match


async def _read_counts(engine, match: ClosableMatch) -> dict[str, object]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        events = await _count(
            session,
            "SELECT count(*) FROM match_events WHERE match_id = :match_id",
            match_id=str(match.match_id),
        )
        states = await _count(
            session,
            "SELECT count(*) FROM match_segment_team_state WHERE match_id = :match_id",
            match_id=str(match.match_id),
        )
        result = (
            await session.execute(
                text("SELECT status, result_confirmed FROM matches WHERE id = :match_id"),
                {"match_id": str(match.match_id)},
            )
        ).mappings().one()
    return {
        "events": events,
        "states": states,
        "status": result["status"],
        "result_confirmed": result["result_confirmed"],
    }


# ---------------------------------------------------------------------------
# Persistence and projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_persists_the_pair_and_rewrites_every_segment_balance(
    db_session, tenant_factory
):
    tenant = await tenant_factory("T005 persistence")
    match = await create_closable_match(db_session, tenant)
    await db_session.commit()

    starter_1, starter_2, starter_3 = match.home_starters[:3]
    substitute_1, substitute_2, substitute_3 = match.home_substitutes
    dto = report(
        [
            substitution(
                starter_1,
                substitute_1,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                client_event_id="t005-persist-1",
            ),
            substitution(
                starter_2,
                substitute_2,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=30,
                client_event_id="t005-persist-2",
            ),
            substitution(
                starter_3,
                substitute_3,
                team_id=match.home_team_id,
                segment_id=match.segment_2,
                minute=60,
                client_event_id="t005-persist-3",
            ),
        ]
    )

    outcome = await CloseMatchReportService(db_session).execute(
        context_for(tenant), match.match_id, dto
    )

    assert outcome["status"] == "success"
    pairs = (
        await db_session.execute(
            text("""
                SELECT client_event_id, player_id, player_out_id, player_in_id
                FROM match_events
                WHERE match_id = :match_id
                ORDER BY client_event_id
            """),
            {"match_id": str(match.match_id)},
        )
    ).mappings().all()
    assert [(row["client_event_id"], row["player_out_id"], row["player_in_id"]) for row in pairs] == [
        ("t005-persist-1", starter_1, substitute_1),
        ("t005-persist-2", starter_2, substitute_2),
        ("t005-persist-3", starter_3, substitute_3),
    ]
    assert all(row["player_id"] == row["player_out_id"] for row in pairs)

    rows = await _state_rows(db_session, match.match_id)
    assert {(row["segment_number"], row["team_id"]) for row in rows} == {
        (1, match.home_team_id),
        (1, match.away_team_id),
        (2, match.home_team_id),
        (2, match.away_team_id),
    }
    balances = {
        (row["segment_number"], row["team_id"]): (
            row["substitutions_remaining"],
            row["substitution_windows_remaining"],
        )
        for row in rows
    }
    assert balances == {
        (1, match.home_team_id): (3, 1),
        (1, match.away_team_id): (5, 3),
        (2, match.home_team_id): (2, 0),
        (2, match.away_team_id): (5, 3),
    }


@pytest.mark.asyncio
async def test_a_goal_in_minute_50_is_extra_time_in_a_40_100_match(db_session, tenant_factory):
    tenant = await tenant_factory("T008 40/100")
    match = await create_closable_match(
        db_session,
        tenant,
        config=minutes_config(regular=40, extra=100),
    )
    await db_session.commit()

    dto = CloseMatchReportDTO(
        resolution_type="extra_time",
        home_score_regular=0,
        away_score_regular=0,
        home_score=1,
        away_score=0,
        winner_team_id=match.home_team_id,
        events=[
            goal(
                match.home_starters[0],
                team_id=match.home_team_id,
                segment_id=match.segment_2,
                minute=50,
                client_event_id="t008-40-100-goal",
            )
        ],
    )

    outcome = await CloseMatchReportService(db_session).execute(
        context_for(tenant), match.match_id, dto
    )

    assert outcome["home_score"] == 1
    assert outcome["away_score"] == 0
    closed = (
        await db_session.execute(
            text("""
                SELECT status, resolution_type, home_score_regular, away_score_regular,
                       home_score, away_score
                FROM matches
                WHERE id = :match_id
            """),
            {"match_id": str(match.match_id)},
        )
    ).mappings().one()
    assert closed["status"] == "finished"
    assert closed["resolution_type"] == "extra_time"
    # The goal in minute 50 belongs to extra time, so the regular score is 0-0.
    assert (closed["home_score_regular"], closed["away_score_regular"]) == (0, 0)
    assert (closed["home_score"], closed["away_score"]) == (1, 0)


@pytest.mark.asyncio
async def test_close_rejects_a_goal_after_the_player_left_without_writing(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        out_id, substitute_id = match.home_starters[0], match.home_substitutes[0]

        dto = report(
            [
                substitution(
                    out_id,
                    substitute_id,
                    team_id=match.home_team_id,
                    segment_id=match.segment_2,
                    minute=60,
                    client_event_id="t005-interval-1",
                ),
                goal(
                    out_id,
                    team_id=match.home_team_id,
                    segment_id=match.segment_2,
                    minute=65,
                    client_event_id="t005-interval-2",
                ),
            ],
            home=1,
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError, match="intervalos"):
                await CloseMatchReportService(session).execute(
                    context, match.match_id, dto
                )

        counts = await _read_counts(engine, match)
        assert counts["events"] == 0
        assert counts["states"] == 0
        assert counts["status"] == "scheduled"
        assert counts["result_confirmed"] is False


@pytest.mark.asyncio
async def test_reentry_is_rejected_when_it_is_not_configured(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        out_id, substitute_id = match.home_starters[0], match.home_substitutes[0]

        dto = report(
            [
                substitution(
                    out_id,
                    substitute_id,
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    client_event_id="t005-reentry-1",
                ),
                substitution(
                    substitute_id,
                    out_id,
                    team_id=match.home_team_id,
                    segment_id=match.segment_2,
                    minute=60,
                    client_event_id="t005-reentry-2",
                ),
            ]
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError, match="reentrada"):
                await CloseMatchReportService(session).execute(
                    context, match.match_id, dto
                )

        counts = await _read_counts(engine, match)
        assert counts["events"] == 0
        assert counts["status"] == "scheduled"


@pytest.mark.asyncio
async def test_reentry_is_persisted_when_the_configuration_allows_it(db_session, tenant_factory):
    tenant = await tenant_factory("T005 reentry")
    match = await create_closable_match(
        db_session, tenant, config=rules_config(allow_reentry=True)
    )
    await db_session.commit()
    out_id, substitute_id = match.home_starters[0], match.home_substitutes[0]

    dto = report(
        [
            substitution(
                out_id,
                substitute_id,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                client_event_id="t005-reentry-ok-1",
            ),
            substitution(
                substitute_id,
                out_id,
                team_id=match.home_team_id,
                segment_id=match.segment_2,
                minute=60,
                client_event_id="t005-reentry-ok-2",
            ),
        ]
    )

    await CloseMatchReportService(db_session).execute(
        context_for(tenant), match.match_id, dto
    )

    assert await _count(
        db_session,
        "SELECT count(*) FROM match_events WHERE match_id = :match_id",
        match_id=str(match.match_id),
    ) == 2
    rows = await _state_rows(db_session, match.match_id)
    home_rows = [row for row in rows if row["team_id"] == match.home_team_id]
    assert [(row["substitutions_remaining"], row["substitution_windows_remaining"]) for row in home_rows] == [
        (4, 2),
        (3, 1),
    ]


@pytest.mark.asyncio
async def test_max_per_team_zero_rejects_the_report_without_writing(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(max_per_team=0)
        )

        dto = report(
            [
                substitution(
                    match.home_starters[0],
                    match.home_substitutes[0],
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    client_event_id="t005-zero-1",
                )
            ]
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError, match="saldo 0"):
                await CloseMatchReportService(session).execute(
                    context, match.match_id, dto
                )

        counts = await _read_counts(engine, match)
        assert counts["events"] == 0
        assert counts["states"] == 0
        assert counts["status"] == "scheduled"


# ---------------------------------------------------------------------------
# client_event_id idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_identical_event_is_reused_and_not_counted_twice(db_session, tenant_factory):
    tenant = await tenant_factory("T005 retry")
    match = await create_closable_match(db_session, tenant)
    out_id, substitute_id = match.home_starters[0], match.home_substitutes[0]
    existing_id = await _insert_event(
        db_session,
        tenant,
        match,
        client_event_id="t005-retry-1",
        out_id=out_id,
        in_id=substitute_id,
        minute=20,
        segment_id=match.segment_1,
    )
    await db_session.commit()

    dto = report(
        [
            substitution(
                out_id,
                substitute_id,
                team_id=match.home_team_id,
                segment_id=match.segment_1,
                minute=20,
                client_event_id="t005-retry-1",
            )
        ]
    )
    await CloseMatchReportService(db_session).execute(
        context_for(tenant), match.match_id, dto
    )

    event = (
        await db_session.execute(
            text("""
                SELECT id, player_out_id, player_in_id
                FROM match_events
                WHERE match_id = :match_id AND client_event_id = 't005-retry-1'
            """),
            {"match_id": str(match.match_id)},
        )
    ).mappings().one()
    assert event["id"] == existing_id
    assert event["player_out_id"] == out_id
    assert event["player_in_id"] == substitute_id
    rows = await _state_rows(db_session, match.match_id)
    home_rows = [row for row in rows if row["team_id"] == match.home_team_id]
    assert [(row["substitutions_remaining"], row["substitution_windows_remaining"]) for row in home_rows] == [
        (4, 2),
        (4, 2),
    ]


@pytest.mark.asyncio
async def test_a_conflicting_retry_is_rejected_without_partial_writes(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await set_tenant_context(session, match.tenant)
            await _insert_event(
                session,
                match.tenant,
                match,
                client_event_id="t005-retry-conflict",
                out_id=match.home_starters[0],
                in_id=match.home_substitutes[0],
                minute=20,
                segment_id=match.segment_1,
            )
            await session.commit()

        dto = report(
            [
                substitution(
                    match.home_starters[1],
                    match.home_substitutes[1],
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    client_event_id="t005-retry-conflict",
                )
            ]
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError, match="inmutable"):
                await CloseMatchReportService(session).execute(
                    context, match.match_id, dto
                )

        counts = await _read_counts(engine, match)
        assert counts["events"] == 1
        assert counts["states"] == 0
        assert counts["status"] == "scheduled"
        assert counts["result_confirmed"] is False


# ---------------------------------------------------------------------------
# GET /operation never writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operation_exposes_the_state_without_writing(db_session, tenant_factory):
    tenant = await tenant_factory("T005 operation")
    match = await create_closable_match(db_session, tenant)
    out_id, substitute_id = match.home_starters[0], match.home_substitutes[0]
    await _insert_event(
        db_session,
        tenant,
        match,
        client_event_id="t005-operation-1",
        out_id=out_id,
        in_id=substitute_id,
        minute=20,
        segment_id=match.segment_1,
    )
    await db_session.commit()

    response = await get_match_operation(
        match.match_id, context_for(tenant), db_session
    )

    substitutions = response["substitutions"]
    assert substitutions["max_per_team"] == 5
    assert substitutions["max_windows"] == 3
    teams = {row["team_id"]: row for row in substitutions["teams"]}
    home = teams[match.home_team_id]
    assert out_id not in home["on_field"]
    assert substitute_id in home["on_field"]
    assert out_id in home["bench"]
    assert substitute_id not in home["bench"]
    assert (home["substitutions_used"], home["substitutions_remaining"]) == (1, 4)
    assert (home["windows_used"], home["windows_remaining"]) == (1, 2)
    assert await _count(
        db_session,
        "SELECT count(*) FROM match_segment_team_state WHERE match_id = :match_id",
        match_id=str(match.match_id),
    ) == 0


@pytest.mark.asyncio
async def test_operation_without_lineup_reports_the_notice(db_session, tenant_factory):
    tenant = await tenant_factory("T005 no lineup")
    match = await create_closable_match(db_session, tenant, with_lineup=False)
    await db_session.commit()

    response = await get_match_operation(
        match.match_id, context_for(tenant), db_session
    )

    substitutions = response["substitutions"]
    teams = {row["team_id"]: row for row in substitutions["teams"]}
    for team_id in (match.home_team_id, match.away_team_id):
        assert teams[team_id]["on_field"] == []
        assert teams[team_id]["bench"] == []
        assert teams[team_id]["can_register"] is False
        assert teams[team_id]["reason"] == NO_LINEUP_NOTICE
    assert await _count(
        db_session,
        "SELECT count(*) FROM match_segment_team_state WHERE match_id = :match_id",
        match_id=str(match.match_id),
    ) == 0


# ---------------------------------------------------------------------------
# Two simultaneous closes (throwaway database, dedicated application role)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_simultaneous_closes_serialise_on_the_match(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        dto = report(
            [
                substitution(
                    match.home_starters[0],
                    match.home_substitutes[0],
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=20,
                    client_event_id="t005-concurrent-1",
                ),
                substitution(
                    match.home_starters[1],
                    match.home_substitutes[1],
                    team_id=match.home_team_id,
                    segment_id=match.segment_1,
                    minute=30,
                    client_event_id="t005-concurrent-2",
                ),
            ]
        )

        async def attempt():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                try:
                    return await CloseMatchReportService(session).execute(
                        context, match.match_id, dto
                    )
                except ValueError as error:
                    return error

        first, second = await asyncio.gather(attempt(), attempt())
        successes = [result for result in (first, second) if isinstance(result, dict)]
        failures = [result for result in (first, second) if isinstance(result, ValueError)]

        assert len(successes) == 1
        assert len(failures) == 1
        assert "no admite cierre normal" in str(failures[0])

        counts = await _read_counts(engine, match)
        assert counts["events"] == 2
        assert counts["states"] == 4
        assert counts["status"] == "finished"
