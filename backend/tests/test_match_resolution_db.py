"""Opt-in PostgreSQL coverage for the resolution of segments (P5, H3-T02/T03).

Requires ``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL`` (the database must
also have the application role). Each case builds a throwaway database at
the latest migrations, because the close service owns the transaction it writes in: a
rejected close must roll back only its own work and the assertions must be able
to read the committed state from an independent session.

The effective configuration of the stage decides whether the requested
resolution is enabled. A disabled one raises the unified ``409
RESOLUTION_NOT_ENABLED`` before any write, and a confirmed act is never
revalidated (RF-035). No rule, default or schema changes here: the stage pair,
the 180-minute cap and the 30-added-minute cap keep their current behaviour
(RF-036).

H3-T03 adds the same optional resolution to creating a segment and to
interrupting one: without the field the stage maximum is kept (P1), with the
field the maximum of that resolution applies, and a resolution the stage does
not enable is the same unified 409, written nothing.
"""

from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.matches.errors import (
    RESOLUTION_NOT_ENABLED,
    RESOLUTION_NOT_ENABLED_DETAIL,
    ResolutionNotEnabled,
)
from app.modules.matches.router import create_match_segment, interrupt_match_segment
from app.modules.matches.schemas import (
    CloseMatchReportDTO,
    CreateMatchSegmentRequest,
    InterruptMatchSegmentRequest,
    MatchEventPayload,
)
from app.modules.matches.service import CloseMatchReportService
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


def rules_config(
    *,
    regular: int = 90,
    extra: int = 120,
    extra_time_enabled: bool = False,
    penalties_enabled: bool = False,
) -> dict:
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "regular_time_minutes": regular,
        "extra_time_minutes": extra,
        "extra_time_enabled": extra_time_enabled,
        "penalties_enabled": penalties_enabled,
    }
    return config


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


@dataclass(frozen=True)
class ClosableMatch:
    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    match_id: UUID
    segment_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    home_player_id: UUID


@asynccontextmanager
async def committed_application(database_admin_url):
    """Throwaway database at 023 plus a dedicated role that inherits the app role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc012_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1)
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


async def _create_tournament(
    session, tenant: TenantContext, *, config: dict
) -> tuple[UUID, UUID, UUID]:
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
                "name": f"H3T02 {uuid4().hex[:8]}",
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


async def _register_team(
    session, tenant: TenantContext, tournament_id: UUID, version_id: UUID, stage_id: UUID
) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"H3T02 {uuid4().hex[:8]}",
                "short_code": f"H{uuid4().hex[:5].upper()}",
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


async def _create_closable_match(
    session,
    tenant: TenantContext,
    *,
    config: dict,
    segment_minute_end: int | None = 90,
) -> ClosableMatch:
    """Build a published match with one active segment and one starter per team."""

    await set_tenant_context(session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, config=config
    )
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
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
    segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES
                    (:organization_id, :match_id, 1, 0, :minute_end, 'active')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "minute_end": segment_minute_end,
            },
        )
    ).scalar_one()

    home_player_id: UUID | None = None
    for team_id, dorsal_number in ((home_team_id, 9), (away_team_id, 10)):
        player_id = await insert_player(
            session,
            tenant.organization_id,
            first_name=f"H3T02{dorsal_number}",
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
                        (:organization_id, :tournament_id, :team_id, :player_id,
                         :dorsal_number, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
                    (:organization_id, :match_id, :roster_id, :player_id, :team_id,
                     'starter', TRUE)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "roster_id": str(roster_id),
                "player_id": str(player_id),
                "team_id": str(team_id),
            },
        )
        if team_id == home_team_id:
            home_player_id = player_id

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
    assert home_player_id is not None
    return ClosableMatch(
        tenant=tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        match_id=match_id,
        segment_id=segment_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_player_id=home_player_id,
    )


async def seeded_match(
    engine,
    *,
    config: dict,
    segment_minute_end: int | None = 90,
) -> tuple[AuthContext, ClosableMatch]:
    """Create and commit one published match visible to independent sessions."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="H3T02 committed")
        match = await _create_closable_match(
            session,
            tenant,
            config=config,
            segment_minute_end=segment_minute_end,
        )
        await session.commit()
    return context_for(tenant), match


def extra_time_report(match: ClosableMatch, *, minute: int = 95) -> CloseMatchReportDTO:
    """Report that needs extra time: the goal is scored past the regular time."""

    return CloseMatchReportDTO(
        resolution_type="extra_time",
        home_score_regular=0,
        away_score_regular=0,
        home_score=1,
        away_score=0,
        winner_team_id=match.home_team_id,
        events=[
            MatchEventPayload(
                client_event_id="h3t02-extra-time-goal",
                event_type="goal",
                team_id=match.home_team_id,
                player_id=match.home_player_id,
                minute=minute,
                segment_id=match.segment_id,
            )
        ],
    )


def penalties_report(match: ClosableMatch) -> CloseMatchReportDTO:
    return CloseMatchReportDTO(
        resolution_type="penalties",
        home_score_regular=0,
        away_score_regular=0,
        home_score=0,
        away_score=0,
        home_penalties=4,
        away_penalties=3,
        winner_team_id=match.home_team_id,
    )


async def close(engine, context: AuthContext, match_id: UUID, dto: CloseMatchReportDTO):
    """Run the close in its own session, exactly as a request does."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await CloseMatchReportService(session).execute(
            context, match_id, dto
        )


async def read_state(engine, match: ClosableMatch) -> dict[str, object]:
    """Read the committed state from an independent session."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT status, resolution_type, result_confirmed, winner_team_id
                    FROM matches
                    WHERE id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).mappings().one()
        events = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM match_events
                    WHERE match_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        segment_status = (
            await session.execute(
                text("SELECT status FROM match_segments WHERE id = :segment_id"),
                {"segment_id": str(match.segment_id)},
            )
        ).scalar_one()
        rules = (
            await session.execute(
                text("SELECT rules_config FROM tournament_versions WHERE id = :version_id"),
                {"version_id": str(match.version_id)},
            )
        ).scalar_one()
    return {
        **dict(row),
        "events": events,
        "segment_status": segment_status,
        "rules_config": rules,
    }


async def _assert_nothing_was_written(engine, match: ClosableMatch, expected_rules: dict) -> None:
    state = await read_state(engine, match)
    assert state["status"] == "scheduled"
    assert state["resolution_type"] is None
    assert state["result_confirmed"] is False
    assert state["winner_team_id"] is None
    assert state["events"] == 0
    assert state["segment_status"] == "active"
    # The published version keeps its effective configuration untouched.
    assert state["rules_config"] == expected_rules


def _assert_unified_conflict(error: pytest.ExceptionInfo) -> None:
    assert error.value.status_code == 409
    assert error.value.code == RESOLUTION_NOT_ENABLED
    assert error.value.detail == RESOLUTION_NOT_ENABLED_DETAIL


@pytest.mark.asyncio
async def test_closing_with_extra_time_disabled_returns_the_unified_409(
    database_admin_url,
):
    config = rules_config(extra_time_enabled=False)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)

        with pytest.raises(ResolutionNotEnabled) as error:
            await close(engine, context, match.match_id, extra_time_report(match))

        _assert_unified_conflict(error)
        await _assert_nothing_was_written(engine, match, config)


@pytest.mark.asyncio
async def test_closing_with_penalties_disabled_returns_the_unified_409(
    database_admin_url,
):
    config = rules_config(extra_time_enabled=True, penalties_enabled=False)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)

        with pytest.raises(ResolutionNotEnabled) as error:
            await close(engine, context, match.match_id, penalties_report(match))

        _assert_unified_conflict(error)
        await _assert_nothing_was_written(engine, match, config)


@pytest.mark.asyncio
async def test_closing_with_extra_time_enabled_still_succeeds(database_admin_url):
    config = rules_config(extra_time_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=config, segment_minute_end=None
        )

        outcome = await close(
            engine, context, match.match_id, extra_time_report(match)
        )

        assert outcome["status"] == "success"
        state = await read_state(engine, match)
        assert state["status"] == "finished"
        assert state["resolution_type"] == "extra_time"
        assert state["winner_team_id"] == match.home_team_id


@pytest.mark.asyncio
async def test_a_confirmed_act_is_not_revalidated_by_the_new_rule(database_admin_url):
    config = rules_config(extra_time_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=config, segment_minute_end=None
        )
        await close(engine, context, match.match_id, extra_time_report(match))
        confirmed = await read_state(engine, match)

        # Closing again is rejected by the existing state rule, not by the new
        # one: a confirmed act is not revalidated (RF-035).
        with pytest.raises(ValueError) as error:
            await close(engine, context, match.match_id, penalties_report(match))

        assert not isinstance(error.value, ResolutionNotEnabled)
        assert "no admite cierre normal" in str(error.value)
        assert await read_state(engine, match) == confirmed


# ---------------------------------------------------------------------------
# Segment creation and interruption with the optional resolution (H3-T03)
# ---------------------------------------------------------------------------


async def call_create_segment(engine, context: AuthContext, match_id: UUID, payload):
    """Run the route in its own session, exactly as a request does."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await create_match_segment(match_id, payload, context, session)


async def call_interrupt(
    engine, context: AuthContext, match_id: UUID, segment_id: UUID, payload
):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await interrupt_match_segment(
            match_id, segment_id, payload, context, session
        )


async def read_segment_state(engine, match: ClosableMatch) -> dict[str, object]:
    """Segments, interruptions and audit entries of the match, committed view."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        segments = (
            await session.execute(
                text("""
                    SELECT segment_number, minute_start, minute_end, status
                    FROM match_segments
                    WHERE match_id = :match_id
                    ORDER BY segment_number
                """),
                {"match_id": str(match.match_id)},
            )
        ).mappings().all()
        interruptions = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM match_segment_interruptions
                    WHERE match_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        audits = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM administrative_audit_logs
                    WHERE entity_type = 'matches' AND entity_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
    return {
        "segments": [dict(row) for row in segments],
        "interruptions": interruptions,
        "audits": audits,
    }


@pytest.mark.asyncio
async def test_creating_a_segment_with_a_disabled_resolution_is_the_unified_409(
    database_admin_url,
):
    config = rules_config(extra_time_enabled=False)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        before = await read_segment_state(engine, match)

        with pytest.raises(ResolutionNotEnabled) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(
                    segment_number=2, minute_start=95, resolution_type="extra_time"
                ),
            )

        _assert_unified_conflict(error)
        # The check comes before the range one and before any write.
        assert await read_segment_state(engine, match) == before
        assert before["segments"] == [
            {"segment_number": 1, "minute_start": 0, "minute_end": 90, "status": "active"}
        ]
        assert before["interruptions"] == 0
        assert before["audits"] == 0


@pytest.mark.asyncio
async def test_creating_a_segment_with_regular_resolution_uses_the_regular_maximum(
    database_admin_url,
):
    config = rules_config(extra_time_enabled=True)  # 90/120

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        before = await read_segment_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(
                    segment_number=2, minute_start=95, resolution_type="regular"
                ),
            )

        assert error.value.status_code == 422
        assert "máximo de 90" in error.value.detail
        assert await read_segment_state(engine, match) == before


@pytest.mark.asyncio
async def test_creating_a_segment_without_resolution_keeps_the_stage_maximum(
    database_admin_url,
):
    config = rules_config(extra_time_enabled=True)  # 90/120, stage maximum 120

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)

        created = await call_create_segment(
            engine,
            context,
            match.match_id,
            CreateMatchSegmentRequest(segment_number=2, minute_start=95),
        )

        assert created["segment_number"] == 2
        assert created["minute_start"] == 95
        state = await read_segment_state(engine, match)
        assert state["segments"] == [
            {"segment_number": 1, "minute_start": 0, "minute_end": 95, "status": "completed"},
            {"segment_number": 2, "minute_start": 95, "minute_end": None, "status": "active"},
        ]


@pytest.mark.asyncio
async def test_interrupting_with_a_disabled_resolution_is_the_unified_409(
    database_admin_url,
):
    config = rules_config(extra_time_enabled=False)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        before = await read_segment_state(engine, match)

        with pytest.raises(ResolutionNotEnabled) as error:
            await call_interrupt(
                engine,
                context,
                match.match_id,
                match.segment_id,
                InterruptMatchSegmentRequest(
                    reason="weather", minute=50, resolution_type="extra_time"
                ),
            )

        _assert_unified_conflict(error)
        # No interruption, no segment update and no audit entry.
        assert await read_segment_state(engine, match) == before
        assert before["segments"][0]["status"] == "active"
        assert before["interruptions"] == 0
        assert before["audits"] == 0


@pytest.mark.asyncio
async def test_interrupting_without_resolution_keeps_the_stage_maximum(
    database_admin_url,
):
    config = rules_config(regular=40, extra=100, extra_time_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        before = await read_segment_state(engine, match)

        # With the regular resolution the same minute is out of range.
        with pytest.raises(HTTPException) as error:
            await call_interrupt(
                engine,
                context,
                match.match_id,
                match.segment_id,
                InterruptMatchSegmentRequest(
                    reason="weather", minute=95, resolution_type="regular"
                ),
            )

        assert error.value.status_code == 422
        assert "máximo de 40" in error.value.detail
        assert await read_segment_state(engine, match) == before

        # Without the field the stage maximum (100) still applies (P1).
        response = await call_interrupt(
            engine,
            context,
            match.match_id,
            match.segment_id,
            InterruptMatchSegmentRequest(reason="weather", minute=95),
        )

        assert response["minute"] == 95
        state = await read_segment_state(engine, match)
        assert state["segments"] == [
            {"segment_number": 1, "minute_start": 0, "minute_end": 95, "status": "interrupted"}
        ]
        assert state["interruptions"] == 1
        assert state["audits"] == 1
