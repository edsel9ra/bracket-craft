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

Spec 016 extends the same file twice: T7 covers **what a walkover leaves
written** (result, standings, bracket, counters and outbox) and T8 covers its
**three 409 codes** —`detail` string, additive `code` and nothing written—, the
immutable confirmed act, the concurrency pairs and the `limits.walkover_score`
block the operation publishes.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.matches.errors import (
    RESOLUTION_NOT_ENABLED,
    RESOLUTION_NOT_ENABLED_DETAIL,
    WALKOVER_CONFIG_INCONSISTENT,
    WALKOVER_SCORE_MISMATCH,
    WALKOVER_STATE_NOT_ALLOWED,
    ResolutionNotEnabled,
)
from app.modules.matches.router import (
    close_match,
    create_match_segment,
    get_match_operation,
    interrupt_match_segment,
)
from app.modules.matches.schemas import (
    CloseMatchReportDTO,
    CreateMatchSegmentRequest,
    InterruptMatchSegmentRequest,
    MatchEventPayload,
)
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import compute_match_outcome
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
from tests.event_ids import event_id


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
                client_event_id=event_id("h3t02-extra-time-goal"),
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


# ---------------------------------------------------------------------------
# Coherencia numérica del marcador (spec 017, T2: 422 → 409)
# ---------------------------------------------------------------------------
#
# Las cuatro condiciones numéricas de la matriz de marcadores dejan de vivir en
# el DTO (422) y pasan al dominio (409, paso 13; RF-007). El motor puro
# `compute_match_outcome` ya las rechaza con `ValueError`, y el router lo
# publica como **409** con `detail` cadena y sin `code` (RF-010). Nada se
# escribe: el cierre entero está en una transacción.
#
# Las condiciones de **presencia** no se mueven: siguen siendo 422 del esquema
# y se comprueban aquí sin base.


async def close_through_the_route(
    engine, context: AuthContext, match_id: UUID, dto: CloseMatchReportDTO
):
    """Run the close route in its own session, exactly as a request does."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await close_match(match_id, dto, context, session)


def _assert_score_coherence_conflict(
    error: pytest.ExceptionInfo, *, fragment: str
) -> None:
    """409 de dominio: `detail` cadena, ningún `code` (RF-010) y mensaje del motor."""

    assert error.value.status_code == 409
    detail = error.value.detail
    assert isinstance(detail, str) and detail
    assert getattr(error.value, "code", None) is None
    assert fragment in detail, detail


def _goal(team_id: UUID, player_id: UUID, minute: int, segment_id: UUID, label: str):
    return MatchEventPayload(
        client_event_id=event_id(label),
        event_type="goal",
        team_id=team_id,
        player_id=player_id,
        minute=minute,
        segment_id=segment_id,
    )


@pytest.mark.asyncio
async def test_a_final_score_lower_than_the_regular_one_is_the_score_step_409(
    database_admin_url,
):
    # Antes: 422 del DTO («El marcador final no puede ser menor al
    # reglamentario»). Ahora: **409** de dominio, sin escribir.
    #
    # Ojo con el paso que lo informa: por la ruta, un final menor que el
    # reglamentario en `extra_time` no llega al paso 13, porque el paso 11
    # (`_validate_event_score_consistency`) ya exige `final = reglamentario +
    # goles posteriores` y el final informado no cuadra con los eventos. El
    # mensaje del motor («El marcador final no puede ser menor al
    # reglamentario») es una rama **defensiva** que la ruta no alcanza; se
    # ejercita directamente en
    # `test_the_engine_keeps_the_final_below_regular_branch_as_defence_in_depth`.
    config = rules_config(extra_time_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=config, segment_minute_end=None
        )
        report = CloseMatchReportDTO(
            resolution_type="extra_time",
            home_score_regular=2,
            away_score_regular=0,
            home_score=1,
            away_score=0,
            winner_team_id=match.home_team_id,
            events=[
                _goal(match.home_team_id, match.home_player_id, 20, match.segment_id, "t2-lower-1"),
                _goal(match.home_team_id, match.home_player_id, 40, match.segment_id, "t2-lower-2"),
            ],
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, report)

        # Paso 11, no paso 13: el marcador final no coincide con los eventos.
        _assert_score_coherence_conflict(
            error, fragment="marcador final no coincide con los eventos"
        )
        await _assert_nothing_was_written(engine, match, config)


@pytest.mark.asyncio
async def test_a_regular_resolution_whose_final_score_differs_is_a_domain_409(
    database_admin_url,
):
    # Antes: 422 del DTO («Una resolución regular debe coincidir…»). Ahora: 409.
    config = rules_config()  # 90/120, sin prórroga ni penales

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        report = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=1,
            away_score_regular=0,
            home_score=2,
            away_score=0,
            winner_team_id=match.home_team_id,
            events=[
                _goal(match.home_team_id, match.home_player_id, 30, match.segment_id, "t2-regular-final"),
            ],
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, report)

        _assert_score_coherence_conflict(error, fragment="marcador de prórroga")
        await _assert_nothing_was_written(engine, match, config)


@pytest.mark.asyncio
async def test_penalties_without_a_draw_after_extra_time_are_a_domain_409(
    database_admin_url,
):
    # Antes: 422 del DTO («El partido debe estar empatado después de la
    # prórroga»). Ahora: 409 del motor, sin escribir.
    config = rules_config(extra_time_enabled=True, penalties_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=config, segment_minute_end=None
        )
        report = CloseMatchReportDTO(
            resolution_type="penalties",
            home_score_regular=0,
            away_score_regular=0,
            home_score=1,
            away_score=0,
            home_penalties=4,
            away_penalties=3,
            winner_team_id=match.home_team_id,
            events=[
                _goal(match.home_team_id, match.home_player_id, 95, match.segment_id, "t2-penalties-no-draw"),
            ],
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, report)

        _assert_score_coherence_conflict(error, fragment="empate después de la prórroga")
        await _assert_nothing_was_written(engine, match, config)


@pytest.mark.asyncio
async def test_a_level_penalty_shootout_is_a_domain_409(database_admin_url):
    # Antes: 422 del DTO («La tanda de penales debe tener un ganador»).
    config = rules_config(extra_time_enabled=True, penalties_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=config, segment_minute_end=None
        )
        report = CloseMatchReportDTO(
            resolution_type="penalties",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
            home_penalties=4,
            away_penalties=4,
            winner_team_id=match.home_team_id,
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, report)

        _assert_score_coherence_conflict(error, fragment="tanda de penales")
        await _assert_nothing_was_written(engine, match, config)


@pytest.mark.asyncio
async def test_a_regular_report_with_the_same_final_score_still_closes(
    database_admin_url,
):
    # El caso aceptado de la matriz: `regular` con final igual al reglamentario.
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        report = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=1,
            away_score_regular=0,
            home_score=1,
            away_score=0,
            winner_team_id=match.home_team_id,
            events=[
                _goal(match.home_team_id, match.home_player_id, 30, match.segment_id, "t2-regular-ok"),
            ],
        )

        outcome = await close_through_the_route(engine, context, match.match_id, report)

        assert outcome["status"] == "success"
        state = await read_state(engine, match)
        assert state["status"] == "finished"
        assert state["resolution_type"] == "regular"
        assert state["winner_team_id"] == match.home_team_id
        assert state["events"] == 1


@pytest.mark.asyncio
async def test_penalties_with_a_draw_and_a_winner_still_closes(database_admin_url):
    # El caso aceptado de la matriz: empate tras la prórroga y tanda con ganador.
    config = rules_config(extra_time_enabled=True, penalties_enabled=True)

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=config, segment_minute_end=None
        )

        outcome = await close_through_the_route(
            engine, context, match.match_id, penalties_report(match)
        )

        assert outcome["status"] == "success"
        state = await read_state(engine, match)
        assert state["status"] == "finished"
        assert state["resolution_type"] == "penalties"
        assert state["winner_team_id"] == match.home_team_id


# Las condiciones de presencia del DTO no cambian: siguen siendo 422.


def test_the_structural_presence_rules_are_still_422():
    with pytest.raises(ValidationError):
        # final sin reglamentario (campo obligatorio del esquema)
        CloseMatchReportDTO(
            resolution_type="regular", home_score=1, away_score=0
        )
    with pytest.raises(ValidationError):
        # `penalties` sin los dos marcadores de penales
        CloseMatchReportDTO(
            resolution_type="penalties",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
            winner_team_id=uuid4(),
        )
    with pytest.raises(ValidationError):
        # `penalties` sin el marcador final
        CloseMatchReportDTO(
            resolution_type="penalties",
            home_score_regular=0,
            away_score_regular=0,
            home_penalties=4,
            away_penalties=3,
            winner_team_id=uuid4(),
        )
    with pytest.raises(ValidationError):
        # ganador ausente en una resolución que lo exige
        CloseMatchReportDTO(
            resolution_type="extra_time",
            home_score_regular=0,
            away_score_regular=0,
            home_score=1,
            away_score=0,
        )
    with pytest.raises(ValidationError):
        # un marcador negativo es estructura (`ge=0`)
        CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=-1,
            away_score_regular=0,
        )
    with pytest.raises(ValidationError):
        # la razón no aplica a `regular`
        CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            reason="no aplica",
        )
    with pytest.raises(ValidationError):
        # walkover no admite eventos individuales (el motivo de catálogo se
        # informa para que el 422 sea el de los eventos y no el del motivo)
        CloseMatchReportDTO(
            resolution_type="walkover",
            home_score_regular=3,
            away_score_regular=0,
            winner_team_id=uuid4(),
            reason="no_show",
            events=[
                MatchEventPayload(
                    client_event_id=event_id("t2-walkover-event"),
                    event_type="goal",
                    team_id=uuid4(),
                    player_id=uuid4(),
                    minute=10,
                    segment_id=uuid4(),
                )
            ],
        )


# ---------------------------------------------------------------------------
# La rama defensiva del motor (spec 017, corrección de la validación)
# ---------------------------------------------------------------------------


def test_the_engine_keeps_the_final_below_regular_branch_as_defence_in_depth():
    """La rama «final menor que el reglamentario» del motor es defensiva.

    Por la ruta de cierre no se alcanza: el paso 11
    (`_validate_event_score_consistency`) exige que el final informado sea el
    reglamentario más los goles posteriores, así que un final menor nunca llega
    al paso 13 (`compute_match_outcome`). La rama sigue existiendo como defensa
    del motor puro y se ejercita aquí directamente.
    """

    config = rules_config(extra_time_enabled=True)

    with pytest.raises(ValueError, match="no puede ser menor al reglamentario"):
        compute_match_outcome(
            config,
            [],  # sin goles: el motor no compara con los eventos
            "extra_time",
            UUID(int=1),
            UUID(int=2),
            2,
            0,
            1,
            0,
            None,
            None,
            UUID(int=1),
        )


# ---------------------------------------------------------------------------
# Validación de los segmentos por la ruta (RF-013, RF-014)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_non_consecutive_segment_number_is_a_422(database_admin_url):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        before = await read_segment_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(segment_number=3, minute_start=45),
            )

        assert error.value.status_code == 422
        assert "debe ser consecutivo" in error.value.detail
        assert await read_segment_state(engine, match) == before


@pytest.mark.asyncio
async def test_a_segment_starting_before_the_previous_end_is_a_422(database_admin_url):
    # El segmento 1 del escenario está cerrado en el minuto 90 (minute_end), así
    # que el nuevo no puede empezar antes de ese final.
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config)
        before = await read_segment_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(segment_number=2, minute_start=80),
            )

        assert error.value.status_code == 422
        assert "antes del segmento anterior" in error.value.detail
        assert await read_segment_state(engine, match) == before


@pytest.mark.asyncio
async def test_a_segment_starting_before_the_active_one_is_a_422(database_admin_url):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        # El segmento 2 queda activo desde el minuto 45.
        await call_create_segment(
            engine,
            context,
            match.match_id,
            CreateMatchSegmentRequest(segment_number=2, minute_start=45),
        )
        before = await read_segment_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(segment_number=3, minute_start=30),
            )

        assert error.value.status_code == 422
        assert "antes del segmento activo" in error.value.detail
        assert await read_segment_state(engine, match) == before


@pytest.mark.asyncio
async def test_interrupting_a_segment_that_is_not_active_is_a_409(database_admin_url):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        # Al crear el segmento 2, el 1 pasa a `completed`.
        await call_create_segment(
            engine,
            context,
            match.match_id,
            CreateMatchSegmentRequest(segment_number=2, minute_start=45),
        )
        before = await read_segment_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_interrupt(
                engine,
                context,
                match.match_id,
                match.segment_id,
                InterruptMatchSegmentRequest(reason="weather", minute=60),
            )

        assert error.value.status_code == 409
        assert "Solo se puede interrumpir el segmento activo" in error.value.detail
        assert await read_segment_state(engine, match) == before


@pytest.mark.asyncio
async def test_interrupting_before_the_segment_start_is_a_422(database_admin_url):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        created = await call_create_segment(
            engine,
            context,
            match.match_id,
            CreateMatchSegmentRequest(segment_number=2, minute_start=45),
        )
        before = await read_segment_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_interrupt(
                engine,
                context,
                match.match_id,
                created["id"],
                InterruptMatchSegmentRequest(reason="weather", minute=30),
            )

        assert error.value.status_code == 422
        assert "antes del inicio del segmento" in error.value.detail
        assert await read_segment_state(engine, match) == before


# ---------------------------------------------------------------------------
# Abrir, cerrar e interrumpir segmentos no cambia el estado del partido (RF-016)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_match_status_does_not_change_when_a_segment_is_interrupted(
    database_admin_url,
):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        before = await read_state(engine, match)
        assert before["status"] == "scheduled"

        response = await call_interrupt(
            engine,
            context,
            match.match_id,
            match.segment_id,
            InterruptMatchSegmentRequest(reason="weather", minute=37),
        )

        assert response["minute"] == 37
        after = await read_state(engine, match)
        # Ninguna transición a `live` ni a `suspended`: solo cambian el segmento,
        # su interrupción y la auditoría.
        assert after["status"] == "scheduled"
        assert after["result_confirmed"] is False
        assert after["resolution_type"] is None
        assert after["winner_team_id"] is None
        assert after["segment_status"] == "interrupted"
        assert after["events"] == 0
        interruptions = await read_segment_state(engine, match)
        assert interruptions["interruptions"] == 1
        assert interruptions["audits"] == 1


# ---------------------------------------------------------------------------
# Concurrencia: el cierre frente a una interrupción y frente a un segmento nuevo
# (RF-018)
# ---------------------------------------------------------------------------


async def _read_race_state(engine, match: ClosableMatch) -> dict[str, object]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        status = (
            await session.execute(
                text("SELECT status FROM matches WHERE id = :match_id"),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
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
                    SELECT count(*) FROM match_segment_interruptions
                    WHERE match_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
    return {
        "status": status,
        "segments": [dict(row) for row in segments],
        "interruptions": interruptions,
        "active": sum(1 for row in segments if row["status"] == "active"),
    }


async def _attempt(engine, action) -> object:
    """Run one operation in its own session; return its 409 instead of raising."""

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await action(session)
    except HTTPException as error:
        return error


@pytest.mark.asyncio
async def test_a_close_concurrent_with_an_interruption_never_leaves_a_partial_state(
    database_admin_url,
):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        dto = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
        )

        close_result, interrupt_result = await asyncio.gather(
            _attempt(
                engine,
                lambda session: close_match(match.match_id, dto, context, session),
            ),
            _attempt(
                engine,
                lambda session: interrupt_match_segment(
                    match.match_id,
                    match.segment_id,
                    InterruptMatchSegmentRequest(reason="weather", minute=37),
                    context,
                    session,
                ),
            ),
        )

        state = await _read_race_state(engine, match)
        # Invariante: nunca dos segmentos activos ni un cierre parcial.
        assert state["active"] <= 1, state["segments"]

        if isinstance(close_result, dict):
            # El cierre llegó antes: la interrupción encuentra el partido
            # terminado (o el segmento ya completado) y cede con su 409.
            assert isinstance(interrupt_result, HTTPException), interrupt_result
            assert interrupt_result.status_code == 409
            assert any(
                fragment in interrupt_result.detail
                for fragment in (
                    "no admite interrupciones",
                    "Solo se puede interrumpir el segmento activo",
                )
            ), interrupt_result.detail
            assert state["status"] == "finished"
            assert state["interruptions"] == 0
        else:
            # La interrupción llegó antes: el cierre ya no tiene segmento activo.
            assert isinstance(close_result, HTTPException), close_result
            assert close_result.status_code == 409
            assert "necesita un segmento activo" in close_result.detail
            assert state["status"] == "scheduled"
            assert state["interruptions"] == 1
            assert state["segments"][-1]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_a_close_concurrent_with_a_new_segment_keeps_one_active_segment(
    database_admin_url,
):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        dto = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
        )

        close_result, create_result = await asyncio.gather(
            _attempt(
                engine,
                lambda session: close_match(match.match_id, dto, context, session),
            ),
            _attempt(
                engine,
                lambda session: create_match_segment(
                    match.match_id,
                    CreateMatchSegmentRequest(segment_number=2, minute_start=45),
                    context,
                    session,
                ),
            ),
        )

        state = await _read_race_state(engine, match)
        assert state["active"] <= 1, state["segments"]

        if isinstance(create_result, dict):
            # El segmento llegó antes: el cierre ve el segmento nuevo activo y
            # termina sobre él; el partido no queda a medias.
            assert isinstance(close_result, dict), close_result
            assert state["status"] == "finished"
            assert state["segments"][-1]["status"] == "completed"
            assert state["segments"][-1]["segment_number"] == 2
        else:
            # El cierre llegó antes: la creación cede con su código, sin crear
            # ningún segmento.
            assert isinstance(create_result, HTTPException), create_result
            assert create_result.status_code == 409
            assert "no admite nuevos segmentos" in create_result.detail
            assert state["status"] == "finished"
            assert len(state["segments"]) == 1


# Las dos órdenes posibles de cada pareja, sin depender del planificador: con la
# primera operación ya confirmada, la segunda ve el estado resultante y cede con
# su código (RF-018). Los dos casos de `asyncio.gather` de arriba cubren el
# intercalado real; estos fijan la respuesta de cada perdedor.


@pytest.mark.asyncio
async def test_an_interruption_after_the_close_yields_with_its_409(database_admin_url):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        dto = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
        )
        await close_through_the_route(engine, context, match.match_id, dto)

        with pytest.raises(HTTPException) as error:
            await call_interrupt(
                engine,
                context,
                match.match_id,
                match.segment_id,
                InterruptMatchSegmentRequest(reason="weather", minute=37),
            )

        assert error.value.status_code == 409
        assert "no admite interrupciones" in error.value.detail
        state = await _read_race_state(engine, match)
        assert state["status"] == "finished"
        assert state["interruptions"] == 0
        assert state["active"] == 0


@pytest.mark.asyncio
async def test_a_close_after_the_interruption_yields_with_its_409(database_admin_url):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        await call_interrupt(
            engine,
            context,
            match.match_id,
            match.segment_id,
            InterruptMatchSegmentRequest(reason="weather", minute=37),
        )
        dto = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, dto)

        assert error.value.status_code == 409
        assert "necesita un segmento activo" in error.value.detail
        state = await _read_race_state(engine, match)
        assert state["status"] == "scheduled"
        assert state["interruptions"] == 1
        assert state["active"] == 0


@pytest.mark.asyncio
async def test_a_segment_created_after_the_close_yields_with_its_409(
    database_admin_url,
):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        dto = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
        )
        await close_through_the_route(engine, context, match.match_id, dto)

        with pytest.raises(HTTPException) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(segment_number=2, minute_start=45),
            )

        assert error.value.status_code == 409
        assert "no admite nuevos segmentos" in error.value.detail
        state = await _read_race_state(engine, match)
        assert state["status"] == "finished"
        assert len(state["segments"]) == 1


@pytest.mark.asyncio
async def test_a_close_after_a_new_segment_finishes_on_the_new_one(
    database_admin_url,
):
    config = rules_config()

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine, config=config, segment_minute_end=None)
        created = await call_create_segment(
            engine,
            context,
            match.match_id,
            CreateMatchSegmentRequest(segment_number=2, minute_start=45),
        )
        dto = CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
        )

        response = await close_through_the_route(engine, context, match.match_id, dto)

        assert response["status"] == "success"
        state = await _read_race_state(engine, match)
        assert state["status"] == "finished"
        assert state["active"] == 0
        assert state["segments"] == [
            {
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": 45,
                "status": "completed",
            },
            {
                "segment_number": 2,
                "minute_start": created["minute_start"],
                "minute_end": created["minute_start"],
                "status": "completed",
            },
        ]


# ---------------------------------------------------------------------------
# Efecto publicado del walkover (spec 016, T7)
# ---------------------------------------------------------------------------
#
# El walkover no tiene acta: lo que se verifica aquí es lo que **queda escrito**
# y lo que ven las demás superficies —resultado, clasificación, avance,
# sanciones, contadores y outbox—, no la precedencia de los códigos (T6) ni la
# exención de segmento y plantilla como tales (T5).
#
# Decisión DU-6: el partido cuenta como **jugado**, con el marcador configurado
# y **sus goles en la diferencia**. La tabla de un W.O. 5-2 deja +3 en el
# ganador y -3 en el perdedor; no es un 0-0 ni un resultado sin goles.

WALKOVER_OUTBOX_TYPES = ("MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED")


@dataclass(frozen=True)
class WalkoverEffect:
    """Escenario del walkover: solo existe lo que pide cada caso."""

    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    match_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    target_match_id: UUID | None = None
    reset_match_id: UUID | None = None
    completed_segment_id: UUID | None = None
    interrupted_segment_id: UUID | None = None
    active_segment_id: UUID | None = None
    suspended_player_id: UUID | None = None


async def _create_walkover_match(
    session,
    tenant: TenantContext,
    *,
    config: dict | None = None,
    stage_pair: tuple[int, int] | None = None,
    bracket_code: str | None = None,
    with_advancement_target: bool = False,
    with_bracket_reset: bool = False,
    with_completed_segment: bool = False,
    with_interrupted_segment: bool = False,
    with_active_segment: bool = False,
    with_suspension: bool = False,
    status: str = "scheduled",
) -> WalkoverEffect:
    """Partido publicado que un walkover puede cerrar sin datos de acta.

    Por defecto **no** hay segmentos, ni plantilla de partido, ni sanciones: el
    escenario vacío es justamente «sin segmento y sin plantilla» (RF-003).
    ``status`` permite arrancar en un estado inadmisible (`finished`, `cancelled`,
    `administrative_resolution` o `suspended`) para probar el 409 del paso 3
    (T8); los dos estados terminales exigen el resultado completo.
    """

    effective_config = deepcopy(config) if config is not None else deepcopy(
        DEFAULT_RULES_CONFIG
    )
    await set_tenant_context(session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, config=effective_config
    )
    if stage_pair is not None:
        # El override por fase necesita el id real de la fase: se escribe sobre
        # la versión **antes** de publicarla (es configuración, no una escritura
        # del cierre).
        effective_config.setdefault("stage_overrides", {})[str(stage_id)] = {
            "walkover_score": {"winner": stage_pair[0], "loser": stage_pair[1]}
        }
        await session.execute(
            text("""
                UPDATE tournament_versions
                SET rules_config = CAST(:config AS jsonb)
                WHERE id = :version_id
            """),
            {
                "config": json.dumps(effective_config),
                "version_id": str(version_id),
            },
        )
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )

    async def insert_match(
        *,
        matchday: int,
        status: str,
        with_teams: bool,
        code: str | None = None,
    ) -> UUID:
        return (
            await session.execute(
                text("""
                    INSERT INTO matches
                        (organization_id, tournament_id, tournament_version_id,
                         stage_id, home_team_id, away_team_id, status, matchday,
                         bracket_code)
                    VALUES
                        (:organization_id, :tournament_id, :version_id, :stage_id,
                         :home_team_id, :away_team_id, :status, :matchday,
                         :bracket_code)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                    "stage_id": str(stage_id),
                    "home_team_id": str(home_team_id) if with_teams else None,
                    "away_team_id": str(away_team_id) if with_teams else None,
                    "status": status,
                    "matchday": matchday,
                    "bracket_code": code,
                },
            )
        ).scalar_one()

    target_match_id = (
        await insert_match(matchday=2, status="scheduled", with_teams=False)
        if with_advancement_target
        else None
    )
    reset_match_id = (
        await insert_match(
            matchday=3, status="cancelled", with_teams=False, code="GF2"
        )
        if with_bracket_reset
        else None
    )
    match_id = await insert_match(
        matchday=1, status="scheduled", with_teams=True, code=bracket_code
    )
    if status in {"finished", "administrative_resolution"}:
        # `chk_terminal_result` exige el resultado completo en la misma
        # sentencia, así que el estado terminal se materializa con un `UPDATE`
        # antes de publicar la versión (el escenario es de configuración, no una
        # escritura del cierre).
        await session.execute(
            text("""
                UPDATE matches
                SET status = :status,
                    home_score_regular = 1, away_score_regular = 0,
                    home_score = 1, away_score = 0,
                    winner_team_id = :winner_team_id,
                    resolution_type = 'regular', result_confirmed = TRUE
                WHERE id = :match_id
            """),
            {
                "status": status,
                "winner_team_id": str(home_team_id),
                "match_id": str(match_id),
            },
        )
    elif status != "scheduled":
        # `cancelled` y `suspended` no exigen marcador: se escriben tal cual.
        await session.execute(
            text("UPDATE matches SET status = :status WHERE id = :match_id"),
            {"status": status, "match_id": str(match_id)},
        )
    if target_match_id is not None:
        await session.execute(
            text("""
                INSERT INTO advancement_links
                    (organization_id, source_match_id, target_match_id, outcome,
                     target_side)
                VALUES
                    (:organization_id, :source_match_id, :target_match_id,
                     'winner', 'home')
            """),
            {
                "organization_id": str(tenant.organization_id),
                "source_match_id": str(match_id),
                "target_match_id": str(target_match_id),
            },
        )

    completed_segment_id: UUID | None = None
    interrupted_segment_id: UUID | None = None
    active_segment_id: UUID | None = None
    next_segment_number = 1
    next_minute_start = 0
    if with_completed_segment:
        completed_segment_id = (
            await session.execute(
                text("""
                    INSERT INTO match_segments
                        (organization_id, match_id, segment_number, minute_start,
                         minute_end, status)
                    VALUES
                        (:organization_id, :match_id, :segment_number, 0, 45,
                         'completed')
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "match_id": str(match_id),
                    "segment_number": next_segment_number,
                },
            )
        ).scalar_one()
        await session.execute(
            text("""
                INSERT INTO match_segment_team_state
                    (organization_id, match_id, segment_id, team_id,
                     substitutions_remaining, substitution_windows_remaining)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, 2, 1)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(completed_segment_id),
                "team_id": str(home_team_id),
            },
        )
        next_segment_number += 1
        next_minute_start = 45
    if with_interrupted_segment:
        interrupted_segment_id = (
            await session.execute(
                text("""
                    INSERT INTO match_segments
                        (organization_id, match_id, segment_number, minute_start,
                         minute_end, status)
                    VALUES
                        (:organization_id, :match_id, :segment_number,
                         :minute_start, :minute_end, 'interrupted')
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "match_id": str(match_id),
                    "segment_number": next_segment_number,
                    "minute_start": next_minute_start,
                    "minute_end": next_minute_start + 30,
                },
            )
        ).scalar_one()
        await session.execute(
            text("""
                INSERT INTO match_segment_interruptions
                    (organization_id, match_id, segment_id, reason, minute,
                     created_by_member_id)
                VALUES
                    (:organization_id, :match_id, :segment_id, 'weather', :minute,
                     :member_id)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(interrupted_segment_id),
                "minute": next_minute_start + 30,
                "member_id": str(tenant.member_id),
            },
        )
        next_segment_number += 1
        next_minute_start += 30
    if with_active_segment:
        active_segment_id = (
            await session.execute(
                text("""
                    INSERT INTO match_segments
                        (organization_id, match_id, segment_number, minute_start,
                         status)
                    VALUES
                        (:organization_id, :match_id, :segment_number,
                         :minute_start, 'active')
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "match_id": str(match_id),
                    "segment_number": next_segment_number,
                    "minute_start": next_minute_start,
                },
            )
        ).scalar_one()

    suspended_player_id: UUID | None = None
    if with_suspension:
        # El jugador está en la plantilla del **torneo** y su suspensión sigue
        # activa: un cierre normal la serviría (cumpliría sanción), el walkover
        # no (RF-009).
        suspended_player_id = await insert_player(
            session,
            tenant.organization_id,
            first_name="W016T7",
            last_name="Suspended",
            reference_year=2026,
        )
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id,
                     dorsal_number, photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, 9,
                     FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(home_team_id),
                "player_id": str(suspended_player_id),
            },
        )
        await session.execute(
            text("""
                INSERT INTO player_suspensions
                    (organization_id, source_tournament_id, player_id,
                     source_type, dedupe_key, scope_type, matches_suspended,
                     reason)
                VALUES
                    (:organization_id, :tournament_id, :player_id,
                     'administrative_resolution', :dedupe_key, 'organization',
                     1, 'walkover_effect_test')
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "player_id": str(suspended_player_id),
                "dedupe_key": f"w016t7:{uuid4().hex}",
            },
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
    return WalkoverEffect(
        tenant=tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        match_id=match_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        target_match_id=target_match_id,
        reset_match_id=reset_match_id,
        completed_segment_id=completed_segment_id,
        interrupted_segment_id=interrupted_segment_id,
        active_segment_id=active_segment_id,
        suspended_player_id=suspended_player_id,
    )


async def seed_walkover(
    engine, **kwargs
) -> tuple[AuthContext, WalkoverEffect]:
    """Crea y confirma el escenario, visible para sesiones independientes."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="W016 T7")
        match = await _create_walkover_match(session, tenant, **kwargs)
        await session.commit()
    return context_for(tenant), match


def walkover_pair(
    match: WalkoverEffect | ClosableMatch,
    *,
    winner: UUID | None = None,
    reason: str = "no_show",
) -> CloseMatchReportDTO:
    """Declaración mínima del contrato nuevo: sin ninguno de los seis marcadores."""

    return CloseMatchReportDTO(
        resolution_type="walkover",
        winner_team_id=winner or match.home_team_id,
        reason=reason,
    )


async def _read_walkover_state(engine, match: WalkoverEffect | ClosableMatch) -> dict[str, object]:
    """Estado publicado del escenario, desde una sesión independiente.

    Acepta también el escenario del cierre normal (:class:`ClosableMatch`) para
    las parejas de concurrencia de T8: el snapshot es el mismo —partido,
    segmentos, proyección, clasificación, sanciones, auditoría y outbox— y los
    dos campos de llave quedan en ``None`` cuando el escenario no los tiene.
    """

    target_match_id = getattr(match, "target_match_id", None)
    reset_match_id = getattr(match, "reset_match_id", None)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT status, resolution_type, resolution_reason,
                           result_confirmed, winner_team_id,
                           home_score_regular, away_score_regular,
                           home_score, away_score, home_penalties, away_penalties
                    FROM matches
                    WHERE id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).mappings().one()
        events = (
            await session.execute(
                text("SELECT count(*) FROM match_events WHERE match_id = :match_id"),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        segments = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT id, segment_number, minute_start, minute_end, status
                        FROM match_segments
                        WHERE match_id = :match_id
                        ORDER BY segment_number
                    """),
                    {"match_id": str(match.match_id)},
                )
            ).mappings().all()
        ]
        projection = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT segment_id, team_id, substitutions_remaining,
                               substitution_windows_remaining
                        FROM match_segment_team_state
                        WHERE match_id = :match_id
                        ORDER BY segment_id, team_id
                    """),
                    {"match_id": str(match.match_id)},
                )
            ).mappings().all()
        ]
        standings = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT team_id, played, won, drawn, lost, goals_for,
                               goals_against, goal_difference, points,
                               fair_play_points
                        FROM standings
                        WHERE stage_id = :stage_id
                        ORDER BY team_id
                    """),
                    {"stage_id": str(match.stage_id)},
                )
            ).mappings().all()
        ]
        outbox = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT event_type, payload
                        FROM outbox_events
                        WHERE organization_id = :organization_id
                        ORDER BY created_at, event_type
                    """),
                    {"organization_id": str(match.tenant.organization_id)},
                )
            ).mappings().all()
        ]
        audits = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM administrative_audit_logs
                    WHERE entity_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
        serves = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM player_suspension_serves
                    WHERE match_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
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
        suspensions = [
            dict(item)
            for item in (
                await session.execute(
                    text("""
                        SELECT player_id, matches_suspended, status
                        FROM player_suspensions
                        WHERE organization_id = :organization_id
                        ORDER BY player_id
                    """),
                    {"organization_id": str(match.tenant.organization_id)},
                )
            ).mappings().all()
        ]
        target = None
        if target_match_id is not None:
            target = dict(
                (
                    await session.execute(
                        text("""
                            SELECT home_team_id, away_team_id, status
                            FROM matches
                            WHERE id = :match_id
                        """),
                        {"match_id": str(target_match_id)},
                    )
                ).mappings().one()
            )
        reset = None
        if reset_match_id is not None:
            reset = dict(
                (
                    await session.execute(
                        text("""
                            SELECT home_team_id, away_team_id, status
                            FROM matches
                            WHERE id = :match_id
                        """),
                        {"match_id": str(reset_match_id)},
                    )
                ).mappings().one()
            )
    return {
        **dict(row),
        "events": events,
        "segments": segments,
        "projection": projection,
        "standings": {item["team_id"]: item for item in standings},
        "outbox": outbox,
        "audits": audits,
        "serves": serves,
        "interruptions": interruptions,
        "suspensions": suspensions,
        "target": target,
        "reset": reset,
    }


def _outbox_types(state: dict[str, object]) -> list[str]:
    return [item["event_type"] for item in state["outbox"]]


@pytest.mark.asyncio
async def test_a_walkover_without_segment_or_roster_publishes_the_default_effect(
    database_admin_url,
):
    """Casos 1 y 2 con el efecto: 3-0, tabla, avance, cero eventos y outbox."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(engine, with_advancement_target=True)
        before = await _read_walkover_state(engine, match)
        # Sin segmentos y sin ningún jugador inscrito: nada que validar.
        assert before["segments"] == []
        assert before["projection"] == []
        assert before["suspensions"] == []

        response = await close(engine, context, match.match_id, walkover_pair(match))

        assert response == {
            "status": "success",
            "match_id": str(match.match_id),
            "home_score": 3,
            "away_score": 0,
            "winner_team_id": str(match.home_team_id),
        }
        state = await _read_walkover_state(engine, match)
        # RF-008: terminado y confirmado, con el marcador derivado en las dos
        # columnas (reglamentario y final) y sin penales.
        assert state["status"] == "finished"
        assert state["result_confirmed"] is True
        assert state["resolution_type"] == "walkover"
        assert state["resolution_reason"] == "no_show"
        assert state["winner_team_id"] == match.home_team_id
        assert (
            state["home_score_regular"],
            state["away_score_regular"],
            state["home_score"],
            state["away_score"],
        ) == (3, 0, 3, 0)
        assert (state["home_penalties"], state["away_penalties"]) == (None, None)
        # RF-004 y RF-008: no hay eventos, no se crea ningún segmento y la
        # proyección por equipo sigue vacía (no se escribe).
        assert state["events"] == 0
        assert state["segments"] == []
        assert state["projection"] == []

        # DU-6: cuenta como **jugado**, con sus puntos y **sus goles** en la
        # diferencia (no es un resultado sin goles ni un partido excluido).
        home = state["standings"][match.home_team_id]
        away = state["standings"][match.away_team_id]
        assert (home["played"], home["won"], home["drawn"], home["lost"]) == (1, 1, 0, 0)
        assert (home["goals_for"], home["goals_against"], home["goal_difference"]) == (
            3,
            0,
            3,
        )
        assert home["points"] == 3
        assert (away["played"], away["won"], away["drawn"], away["lost"]) == (1, 0, 0, 1)
        assert (away["goals_for"], away["goals_against"], away["goal_difference"]) == (
            0,
            3,
            -3,
        )
        assert away["points"] == 0
        # Sin tarjetas no hay fair play: el walkover no genera disciplina.
        assert home["fair_play_points"] == 0
        assert away["fair_play_points"] == 0

        # RF-008: el ganador avanza de llave.
        assert state["target"] == {
            "home_team_id": match.home_team_id,
            "away_team_id": None,
            "status": "scheduled",
        }
        # RNF-010: la acción de cierre existente, con el motivo.
        assert state["audits"] == 1
        # RNF-011: los mismos tres eventos que un cierre normal, sin duplicados.
        assert sorted(_outbox_types(state)) == sorted(WALKOVER_OUTBOX_TYPES)
        assert len(_outbox_types(state)) == len(set(_outbox_types(state)))
        for item in state["outbox"]:
            assert item["payload"] == {
                "match_id": str(match.match_id),
                "tournament_id": str(match.tournament_id),
            }


@pytest.mark.parametrize("stage_pair", [(3, 1), (5, 2)])
@pytest.mark.asyncio
async def test_the_stage_override_scores_the_win_and_counts_in_the_goal_difference(
    database_admin_url, stage_pair
):
    """Caso 8, caso 19 y DU-6: la fase manda y los goles del W.O. cuentan.

    Se cubren la pareja 3-1 del caso límite 19 y una 5-2 más abierta (el valor
    no tiene tope: RF-011 solo exige `winner > loser`).
    """

    winner, loser = stage_pair

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(engine, stage_pair=stage_pair)

        await close(engine, context, match.match_id, walkover_pair(match))

        state = await _read_walkover_state(engine, match)
        assert (
            state["home_score_regular"],
            state["away_score_regular"],
            state["home_score"],
            state["away_score"],
        ) == (winner, loser, winner, loser)
        home = state["standings"][match.home_team_id]
        away = state["standings"][match.away_team_id]
        # **Dato clave de DU-6:** la diferencia sale de los goles del walkover
        # (no de un marcador convencional ni de cero).
        assert (home["goals_for"], home["goals_against"]) == (winner, loser)
        assert home["goal_difference"] == winner - loser
        assert (away["goals_for"], away["goals_against"]) == (loser, winner)
        assert away["goal_difference"] == -(winner - loser)
        assert (home["points"], away["points"]) == (3, 0)


@pytest.mark.asyncio
async def test_the_derived_pair_is_oriented_to_the_declared_winner(
    database_admin_url,
):
    """El ganador declarado recibe la victoria y la pareja se orienta a su lado."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(engine, stage_pair=(5, 2))

        await close(
            engine,
            context,
            match.match_id,
            walkover_pair(match, winner=match.away_team_id),
        )

        state = await _read_walkover_state(engine, match)
        assert (
            state["home_score_regular"],
            state["away_score_regular"],
            state["home_score"],
            state["away_score"],
        ) == (2, 5, 2, 5)
        assert state["winner_team_id"] == match.away_team_id
        home = state["standings"][match.home_team_id]
        away = state["standings"][match.away_team_id]
        assert (home["won"], home["lost"], home["points"]) == (0, 1, 0)
        assert (away["won"], away["lost"], away["points"]) == (1, 0, 3)
        assert (home["goals_for"], home["goals_against"], home["goal_difference"]) == (
            2,
            5,
            -3,
        )
        assert (away["goals_for"], away["goals_against"], away["goal_difference"]) == (
            5,
            2,
            3,
        )


@pytest.mark.asyncio
async def test_a_walkover_advances_the_bracket_winner(database_admin_url):
    """RF-008: el ganador del W.O. ocupa el destino de la llave."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine,
            bracket_code="SF1",
            with_advancement_target=True,
            with_bracket_reset=True,
        )

        await close(engine, context, match.match_id, walkover_pair(match))

        state = await _read_walkover_state(engine, match)
        assert state["status"] == "finished"
        assert state["target"] == {
            "home_team_id": match.home_team_id,
            "away_team_id": None,
            "status": "scheduled",
        }
        # La repetición de doble eliminación no se toca si no gana el finalista
        # del cuadro de perdedores.
        assert state["reset"] == {
            "home_team_id": None,
            "away_team_id": None,
            "status": "cancelled",
        }


@pytest.mark.asyncio
async def test_a_walkover_of_the_grand_final_activates_the_reset(database_admin_url):
    """Caso 13: GF1 con el finalista del cuadro de perdedores ganando."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine, bracket_code="GF1", with_bracket_reset=True
        )

        await close(
            engine,
            context,
            match.match_id,
            walkover_pair(match, winner=match.away_team_id),
        )

        state = await _read_walkover_state(engine, match)
        assert state["status"] == "finished"
        assert state["winner_team_id"] == match.away_team_id
        # La misma regla que un cierre normal: GF2 se reactiva con los dos
        # equipos de la final.
        assert state["reset"] == {
            "home_team_id": match.home_team_id,
            "away_team_id": match.away_team_id,
            "status": "scheduled",
        }
        # El cuarto evento es el `MATCH_UPDATED` que el reset ya emitía antes de
        # esta spec (no se añade ningún tipo nuevo: RNF-011).
        types = _outbox_types(state)
        assert types.count("MATCH_CLOSED") == 1
        assert types.count("MATCH_UPDATED") == 2
        assert types.count("STANDINGS_UPDATED") == 1
        assert set(types) == set(WALKOVER_OUTBOX_TYPES)


@pytest.mark.asyncio
async def test_a_walkover_neither_serves_nor_creates_suspensions(database_admin_url):
    """RF-009: no se cumple la sanción pendiente ni se crea ninguna nueva."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(engine, with_suspension=True)
        assert match.suspended_player_id is not None

        await close(engine, context, match.match_id, walkover_pair(match))

        state = await _read_walkover_state(engine, match)
        assert state["status"] == "finished"
        # Un partido no disputado no cumple sanción: ninguna fila de servicio.
        assert state["serves"] == 0
        # Y no se crea ninguna: sigue habiendo **una** suspensión, activa.
        assert state["suspensions"] == [
            {
                "player_id": match.suspended_player_id,
                "matches_suspended": 1,
                "status": "active",
            }
        ]


@pytest.mark.asyncio
async def test_a_walkover_closes_the_active_segment_at_its_start_without_projection(
    database_admin_url,
):
    """Casos 3 y 4: el activo se cierra en su inicio y la proyección no se toca."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine, with_completed_segment=True, with_active_segment=True
        )
        before = await _read_walkover_state(engine, match)
        assert before["projection"] == [
            {
                "segment_id": match.completed_segment_id,
                "team_id": match.home_team_id,
                "substitutions_remaining": 2,
                "substitution_windows_remaining": 1,
            }
        ]

        await close(engine, context, match.match_id, walkover_pair(match))

        state = await _read_walkover_state(engine, match)
        segments = {row["segment_number"]: row for row in state["segments"]}
        # El completado no cambia de estado ni de minutos.
        assert segments[1] == {
            "id": match.completed_segment_id,
            "segment_number": 1,
            "minute_start": 0,
            "minute_end": 45,
            "status": "completed",
        }
        # El activo queda completo en su propio minuto de inicio.
        assert segments[2] == {
            "id": match.active_segment_id,
            "segment_number": 2,
            "minute_start": 45,
            "minute_end": 45,
            "status": "completed",
        }
        # `match_segment_team_state` no se reescribe ni se crea para el cierre.
        assert state["projection"] == before["projection"]
        # Sin eventos y sin activo al terminar.
        assert state["events"] == 0
        assert all(row["status"] != "active" for row in state["segments"])


@pytest.mark.asyncio
async def test_a_walkover_leaves_an_interrupted_segment_untouched(database_admin_url):
    """Caso 4: un interrumpido no cambia y el activo se cierra en su inicio."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine, with_interrupted_segment=True, with_active_segment=True
        )
        before = await _read_walkover_state(engine, match)
        assert before["interruptions"] == 1

        await close(engine, context, match.match_id, walkover_pair(match))

        state = await _read_walkover_state(engine, match)
        segments = {row["segment_number"]: row for row in state["segments"]}
        # El interrumpido conserva estado, minutos y su fila de interrupción.
        assert segments[1] == {
            "id": match.interrupted_segment_id,
            "segment_number": 1,
            "minute_start": 0,
            "minute_end": 30,
            "status": "interrupted",
        }
        assert state["interruptions"] == before["interruptions"]
        assert segments[2] == {
            "id": match.active_segment_id,
            "segment_number": 2,
            "minute_start": 30,
            "minute_end": 30,
            "status": "completed",
        }


@pytest.mark.asyncio
async def test_a_walkover_does_not_affect_another_organization(database_admin_url):
    """RNF-001: el W.O. de una organización no toca la tabla de otra."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(engine, with_advancement_target=True)
        # Segunda organización con su propio torneo y partido, en la misma base.
        other_context, other = await seed_walkover(engine, with_advancement_target=True)
        other_before = await _read_walkover_state(engine, other)
        assert other.tenant.organization_id != match.tenant.organization_id

        await close(engine, context, match.match_id, walkover_pair(match))

        # La otra organización queda exactamente igual: partido sin cerrar, sin
        # clasificación, sin auditoría y sin eventos de outbox.
        assert await _read_walkover_state(engine, other) == other_before
        other_state = await _read_walkover_state(engine, other)
        assert other_state["status"] == "scheduled"
        assert other_state["standings"] == {}
        assert other_state["outbox"] == []
        assert other_state["audits"] == 0
        assert other_state["target"] == {
            "home_team_id": None,
            "away_team_id": None,
            "status": "scheduled",
        }
        # Y el W.O. sí escribió en la suya.
        assert (await _read_walkover_state(engine, match))["status"] == "finished"
        assert other_context.organization_id != context.organization_id


# ---------------------------------------------------------------------------
# Códigos, acta confirmada y concurrencia del walkover (spec 016, T8)
# ---------------------------------------------------------------------------
#
# T7 dejó verificado **qué queda escrito** en un W.O. válido. Aquí se cubren
# las tres salidas de error que no escriben nada (RF-001, RF-005, RF-008), la
# inmutabilidad del acta confirmada (RF-010), las parejas de concurrencia con
# las otras dos escrituras del partido (casos 15-17) y el bloque `limits` que la
# operación publica (RF-005).
#
# Los tres 409 se piden por la **ruta real** (`close_match`, el handler HTTP) y
# no por el servicio, así que el contrato completo se comprueba como lo ve un
# cliente: `detail` cadena, `code` aditivo exacto y **cero escrituras**. «Cero
# escrituras» es un snapshot completo del escenario (partido, segmentos,
# proyección por equipo, clasificación, sanciones, auditoría, outbox y destino
# de la llave), no una lista de campos elegidos.
#
# Las parejas de concurrencia se prueban **dos veces**: con `asyncio.gather`
# (intercalado real) y con las dos órdenes fijas, porque un `gather` puede pasar
# con una guarda rota según el planificador (lección de la 017).

#: Las ocho claves que `limits` publicaba antes de la 016 (RNF-003 a).
WALKOVER_LIMIT_KEYS = frozenset(
    {
        "regular_time_minutes",
        "extra_time_minutes",
        "max_minute",
        "added_minute_max",
        "max_minute_regular",
        "max_minute_extra",
        "extra_time_enabled",
        "penalties_enabled",
    }
)

#: Valores de esas ocho claves con la configuración del escenario (90/120 sin
#: prórroga ni penales). El walkover no las cambia: solo añade su pareja.
WALKOVER_LIMIT_VALUES = {
    "regular_time_minutes": 90,
    "extra_time_minutes": 120,
    "max_minute": 90,
    "added_minute_max": 30,
    "max_minute_regular": 90,
    "max_minute_extra": None,
    "extra_time_enabled": False,
    "penalties_enabled": False,
}


def _assert_walkover_conflict(error: pytest.ExceptionInfo, code: str) -> None:
    """409 de dominio del walkover: `detail` cadena y `code` aditivo exacto."""

    assert error.value.status_code == 409
    assert error.value.code == code
    detail = error.value.detail
    assert isinstance(detail, str) and detail, detail


def regular_report() -> CloseMatchReportDTO:
    """Acta reglamentaria mínima que el escenario del cierre normal acepta."""

    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=0,
        away_score_regular=0,
        home_score=0,
        away_score=0,
    )


def _active_segments(state: dict[str, object]) -> int:
    return sum(1 for row in state["segments"] if row["status"] == "active")


async def call_operation(engine, context: AuthContext, match_id: UUID):
    """Operación del partido en su propia sesión, exactamente como una petición."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await get_match_operation(match_id, context, session)


@pytest.mark.asyncio
async def test_the_walkover_state_code_refuses_the_four_inadmissible_states(
    database_admin_url,
):
    """RF-001: `suspended` y los tres terminales, por la ruta y sin escribir.

    Los estados admisibles son los que hoy admiten cierre; esta spec no añade
    ninguna transición. El mensaje nombra el estado leído del servidor y el
    cliente usa `code`.
    """

    async with committed_application(database_admin_url) as engine:
        for status in (
            "finished",
            "cancelled",
            "administrative_resolution",
            "suspended",
        ):
            context, match = await seed_walkover(
                engine, status=status, with_advancement_target=True
            )
            before = await _read_walkover_state(engine, match)
            assert before["status"] == status

            with pytest.raises(HTTPException) as error:
                await close_through_the_route(
                    engine, context, match.match_id, walkover_pair(match)
                )

            _assert_walkover_conflict(error, WALKOVER_STATE_NOT_ALLOWED)
            assert status in error.value.detail
            assert await _read_walkover_state(engine, match) == before


@pytest.mark.asyncio
async def test_an_informed_pair_that_differs_is_the_score_mismatch(
    database_admin_url,
):
    """Caso 7 y RF-005: el marcador informado distinto, sin escribir."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine, with_advancement_target=True
        )  # pareja publicada 3-0
        before = await _read_walkover_state(engine, match)
        # El escenario también tiene destino de llave: el snapshot de «cero
        # escrituras» incluye que el ganador no haya avanzado.
        assert before["target"] == {
            "home_team_id": None,
            "away_team_id": None,
            "status": "scheduled",
        }
        # La pareja reglamentaria es opcional en el walkover (D-9), así que para
        # informar un marcador distinto basta con declararla: el DTO lo acepta y
        # el defecto es de dominio.
        dto = CloseMatchReportDTO(
            resolution_type="walkover",
            winner_team_id=match.home_team_id,
            reason="no_show",
            home_score_regular=1,
            away_score_regular=0,
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, dto)

        _assert_walkover_conflict(error, WALKOVER_SCORE_MISMATCH)
        # El mensaje nombra la pareja **configurada**, nunca la enviada
        # (RNF-002: el texto del cliente no viaja al error).
        assert "3-0" in error.value.detail
        assert "1-0" not in error.value.detail
        assert await _read_walkover_state(engine, match) == before


@pytest.mark.asyncio
async def test_a_published_incoherent_pair_is_the_config_code_before_the_mismatch(
    database_admin_url,
):
    """Caso 18 y D-4: la pareja publicada 0-3 gana al desajuste informado.

    La petición informa además un marcador que no coincide, de modo que la
    guarda de coherencia (D-4) demuestra que va **antes** del desajuste y que el
    cliente recibe su `code` con la salida documentada.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine, stage_pair=(0, 3), with_advancement_target=True
        )
        before = await _read_walkover_state(engine, match)
        dto = CloseMatchReportDTO(
            resolution_type="walkover",
            winner_team_id=match.home_team_id,
            reason="no_show",
            home_score_regular=1,
            away_score_regular=0,
        )

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(engine, context, match.match_id, dto)

        _assert_walkover_conflict(error, WALKOVER_CONFIG_INCONSISTENT)
        assert "0-3" in error.value.detail
        assert "administrativa" in error.value.detail
        assert await _read_walkover_state(engine, match) == before


@pytest.mark.asyncio
async def test_a_confirmed_act_does_not_revalidate_the_walkover_pair(
    database_admin_url,
):
    """RF-010 y D-5: un acta confirmada responde por estado, no por la pareja.

    La versión publicada lleva 0-3 —posible solo antes de D-3— y aun así el
    cierre informa el código del **estado**: el paso 3 descarta el acta antes de
    llegar a la guarda del 13′, así que la configuración publicada no se
    revalida ni se reescribe.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(
            engine, status="finished", stage_pair=(0, 3), with_advancement_target=True
        )
        before = await _read_walkover_state(engine, match)
        assert before["status"] == "finished"
        assert before["result_confirmed"] is True

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(
                engine, context, match.match_id, walkover_pair(match)
            )

        _assert_walkover_conflict(error, WALKOVER_STATE_NOT_ALLOWED)
        assert await _read_walkover_state(engine, match) == before


@pytest.mark.asyncio
async def test_the_second_walkover_on_the_confirmed_act_writes_nothing(
    database_admin_url,
):
    """RF-010 y caso 12/15: ni motivo, ni ganador, ni reversión."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seed_walkover(engine)
        await close_through_the_route(
            engine, context, match.match_id, walkover_pair(match)
        )
        confirmed = await _read_walkover_state(engine, match)
        assert confirmed["resolution_reason"] == "no_show"

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(
                engine,
                context,
                match.match_id,
                walkover_pair(match, winner=match.away_team_id, reason="withdrawal"),
            )

        _assert_walkover_conflict(error, WALKOVER_STATE_NOT_ALLOWED)
        assert "finished" in error.value.detail
        assert await _read_walkover_state(engine, match) == confirmed


@pytest.mark.asyncio
async def test_the_operation_publishes_the_effective_walkover_pair(
    database_admin_url,
):
    """RF-005 y RNF-003 a: default y override efectivos, ocho claves intactas."""

    async with committed_application(database_admin_url) as engine:
        context, default_match = await seed_walkover(engine)
        override_context, override_match = await seed_walkover(
            engine, stage_pair=(3, 1)
        )

        default_limits = (
            await call_operation(engine, context, default_match.match_id)
        )["limits"]
        override_limits = (
            await call_operation(engine, override_context, override_match.match_id)
        )["limits"]

        for limits, pair in (
            (default_limits, {"winner": 3, "loser": 0}),
            (override_limits, {"winner": 3, "loser": 1}),
        ):
            assert set(limits) == WALKOVER_LIMIT_KEYS | {"walkover_score"}
            assert limits["walkover_score"] == pair
            # Las ocho claves existentes conservan su valor y su forma.
            assert {
                key: value for key, value in limits.items() if key != "walkover_score"
            } == WALKOVER_LIMIT_VALUES


# --- Concurrencia con el intercalado real -----------------------------------
#
# Las tres parejas usan el escenario del cierre normal (segmento activo y un
# titular por equipo), que es el único con el que **las dos** operaciones pueden
# ganar: así el perdedor cede por su guarda y no por un defecto del escenario.


@pytest.mark.parametrize("first", ["walkover", "close"])
@pytest.mark.asyncio
async def test_a_walkover_concurrent_with_another_close_leaves_one_result(
    database_admin_url, first
):
    """Caso 15: dos cierres simultáneos, un solo resultado y un solo perdedor.

    Se lanza primero una y luego la otra para ejercitar los **dos** desenlaces
    reales del `gather`: quien gana el bloqueo del partido decide el resultado y
    el otro revierte entero.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )

        attempts = {
            "walkover": lambda session: close_match(
                match.match_id, walkover_pair(match), context, session
            ),
            "close": lambda session: close_match(
                match.match_id, regular_report(), context, session
            ),
        }
        other = "close" if first == "walkover" else "walkover"
        first_result, second_result = await asyncio.gather(
            _attempt(engine, attempts[first]),
            _attempt(engine, attempts[other]),
        )
        walkover_result = first_result if first == "walkover" else second_result
        close_result = second_result if first == "walkover" else first_result

        state = await _read_walkover_state(engine, match)
        # Invariante: un solo cierre escribió (una auditoría y los tres eventos
        # de outbox); el otro revirtió entero.
        assert state["status"] == "finished"
        assert state["result_confirmed"] is True
        assert state["audits"] == 1
        assert sorted(item["event_type"] for item in state["outbox"]) == sorted(
            WALKOVER_OUTBOX_TYPES
        )
        assert state["events"] == 0

        if isinstance(walkover_result, dict):
            # El W.O. llegó antes: el cierre normal encuentra el acta terminada.
            assert isinstance(close_result, HTTPException), close_result
            assert close_result.status_code == 409
            assert "no admite cierre normal" in close_result.detail
            assert walkover_result["home_score"] == 3
            assert state["resolution_type"] == "walkover"
            assert (state["home_score"], state["away_score"]) == (3, 0)
        else:
            # El cierre normal llegó antes: el W.O. cede con su código.
            assert isinstance(close_result, dict), close_result
            assert isinstance(walkover_result, HTTPException), walkover_result
            assert walkover_result.status_code == 409
            assert walkover_result.code == WALKOVER_STATE_NOT_ALLOWED
            assert state["resolution_type"] == "regular"
            assert (state["home_score"], state["away_score"]) == (0, 0)

        # La clasificación se calculó una sola vez: un partido jugado por equipo.
        assert sorted(
            (row["team_id"], row["played"]) for row in state["standings"].values()
        ) == sorted(
            (team_id, 1) for team_id in (match.home_team_id, match.away_team_id)
        )


@pytest.mark.parametrize("first", ["walkover", "interrupt"])
@pytest.mark.asyncio
async def test_a_walkover_concurrent_with_an_interruption_leaves_no_active_segment(
    database_admin_url, first
):
    """Caso 17: el W.O. cierra en las dos órdenes y no deja activo.

    Si la interrupción gana, el W.O. **también** cierra (no necesita segmento
    activo) y el interrumpido queda intacto; si gana el W.O., la interrupción
    encuentra el acta terminada y cede con su 409.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )

        attempts = {
            "walkover": lambda session: close_match(
                match.match_id, walkover_pair(match), context, session
            ),
            "interrupt": lambda session: interrupt_match_segment(
                match.match_id,
                match.segment_id,
                InterruptMatchSegmentRequest(reason="weather", minute=37),
                context,
                session,
            ),
        }
        other = "interrupt" if first == "walkover" else "walkover"
        first_result, second_result = await asyncio.gather(
            _attempt(engine, attempts[first]),
            _attempt(engine, attempts[other]),
        )
        walkover_result = first_result if first == "walkover" else second_result
        interrupt_result = second_result if first == "walkover" else first_result

        state = await _read_walkover_state(engine, match)
        segments = {row["segment_number"]: row for row in state["segments"]}
        # El W.O. no necesita segmento activo: llega o no, el partido termina.
        assert state["status"] == "finished"
        assert isinstance(walkover_result, dict), walkover_result
        assert _active_segments(state) == 0

        if isinstance(interrupt_result, dict):
            # La interrupción llegó antes: el W.O. no toca el interrumpido.
            assert state["interruptions"] == 1
            assert segments[1] == {
                "id": match.segment_id,
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": 37,
                "status": "interrupted",
            }
        else:
            # El W.O. llegó antes: la interrupción encuentra el acta terminada.
            assert interrupt_result.status_code == 409
            assert "no admite interrupciones" in interrupt_result.detail
            assert state["interruptions"] == 0
            assert segments[1] == {
                "id": match.segment_id,
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": 0,
                "status": "completed",
            }


@pytest.mark.asyncio
async def test_a_walkover_concurrent_with_a_new_segment_leaves_no_orphan_segment(
    database_admin_url,
):
    """Caso 16: si el segmento se creó antes, el W.O. lo cierra en su inicio.

    Y si el W.O. llegó antes, la creación cede con su código y no deja ningún
    segmento huérfano: el invariante es el mismo en las dos órdenes.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )

        walkover_result, create_result = await asyncio.gather(
            _attempt(
                engine,
                lambda session: close_match(
                    match.match_id, walkover_pair(match), context, session
                ),
            ),
            _attempt(
                engine,
                lambda session: create_match_segment(
                    match.match_id,
                    CreateMatchSegmentRequest(segment_number=2, minute_start=45),
                    context,
                    session,
                ),
            ),
        )

        state = await _read_walkover_state(engine, match)
        segments = {row["segment_number"]: row for row in state["segments"]}
        assert state["status"] == "finished"
        assert isinstance(walkover_result, dict), walkover_result
        assert _active_segments(state) == 0

        if isinstance(create_result, dict):
            # El segmento llegó antes: el W.O. cierra el nuevo en su inicio.
            assert len(state["segments"]) == 2
            assert segments[1] == {
                "id": match.segment_id,
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": 45,
                "status": "completed",
            }
            assert segments[2]["segment_number"] == 2
            assert segments[2]["minute_start"] == 45
            assert segments[2]["minute_end"] == 45
            assert segments[2]["status"] == "completed"
        else:
            # El W.O. llegó antes: no queda ningún segmento huérfano.
            assert create_result.status_code == 409
            assert "no admite nuevos segmentos" in create_result.detail
            assert state["segments"] == [
                {
                    "id": match.segment_id,
                    "segment_number": 1,
                    "minute_start": 0,
                    "minute_end": 0,
                    "status": "completed",
                }
            ]


# --- Las dos órdenes de cada pareja, sin depender del planificador ----------
#
# Con la primera operación ya confirmada, la segunda ve el estado resultante y
# cede con su código (o, en el W.O., cierra igual porque no necesita segmento).


@pytest.mark.asyncio
async def test_the_regular_close_after_the_walkover_yields_with_its_409(
    database_admin_url,
):
    """RF-010: un acta confirmada no admite el cierre normal."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )
        await close_through_the_route(
            engine, context, match.match_id, walkover_pair(match)
        )
        confirmed = await _read_walkover_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(
                engine, context, match.match_id, regular_report()
            )

        assert error.value.status_code == 409
        assert "no admite cierre normal" in error.value.detail
        # El cierre normal conserva su 409 sin `code` (spec 017).
        assert getattr(error.value, "code", None) is None
        assert await _read_walkover_state(engine, match) == confirmed


@pytest.mark.asyncio
async def test_the_walkover_after_the_regular_close_yields_with_its_code(
    database_admin_url,
):
    """RF-001: un W.O. sobre un acta ya cerrada responde por su `code`."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )
        await close_through_the_route(
            engine, context, match.match_id, regular_report()
        )
        closed = await _read_walkover_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await close_through_the_route(
                engine, context, match.match_id, walkover_pair(match)
            )

        _assert_walkover_conflict(error, WALKOVER_STATE_NOT_ALLOWED)
        assert closed["resolution_type"] == "regular"
        assert await _read_walkover_state(engine, match) == closed


@pytest.mark.asyncio
async def test_the_interruption_after_the_walkover_yields_with_its_409(
    database_admin_url,
):
    """Caso 17: la interrupción posterior encuentra el partido terminado."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )
        await close_through_the_route(
            engine, context, match.match_id, walkover_pair(match)
        )
        confirmed = await _read_walkover_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_interrupt(
                engine,
                context,
                match.match_id,
                match.segment_id,
                InterruptMatchSegmentRequest(reason="weather", minute=37),
            )

        assert error.value.status_code == 409
        assert "no admite interrupciones" in error.value.detail
        assert await _read_walkover_state(engine, match) == confirmed
        # El segmento se cerró en su minuto de inicio y no hay interrupción.
        assert confirmed["interruptions"] == 0
        assert confirmed["segments"] == [
            {
                "id": match.segment_id,
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": 0,
                "status": "completed",
            }
        ]


@pytest.mark.asyncio
async def test_the_walkover_after_the_interruption_leaves_it_untouched(
    database_admin_url,
):
    """Caso 17: la interrupción anterior deja el segmento y el W.O. no lo toca."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )
        await call_interrupt(
            engine,
            context,
            match.match_id,
            match.segment_id,
            InterruptMatchSegmentRequest(reason="weather", minute=37),
        )
        interrupted = await _read_walkover_state(engine, match)
        assert interrupted["segments"] == [
            {
                "id": match.segment_id,
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": 37,
                "status": "interrupted",
            }
        ]

        response = await close_through_the_route(
            engine, context, match.match_id, walkover_pair(match)
        )

        assert response["status"] == "success"
        state = await _read_walkover_state(engine, match)
        assert state["status"] == "finished"
        assert state["resolution_type"] == "walkover"
        # Sin segmento activo no se crea ni se reabre ninguno y la interrupción
        # sigue siendo exactamente la misma.
        assert state["segments"] == interrupted["segments"]
        assert state["interruptions"] == interrupted["interruptions"] == 1


@pytest.mark.asyncio
async def test_the_segment_created_after_the_walkover_yields_with_its_409(
    database_admin_url,
):
    """Caso 16: la creación posterior cede y no deja segmento huérfano."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )
        await close_through_the_route(
            engine, context, match.match_id, walkover_pair(match)
        )
        confirmed = await _read_walkover_state(engine, match)

        with pytest.raises(HTTPException) as error:
            await call_create_segment(
                engine,
                context,
                match.match_id,
                CreateMatchSegmentRequest(segment_number=2, minute_start=45),
            )

        assert error.value.status_code == 409
        assert "no admite nuevos segmentos" in error.value.detail
        assert await _read_walkover_state(engine, match) == confirmed
        assert len(confirmed["segments"]) == 1


@pytest.mark.asyncio
async def test_the_walkover_after_a_new_segment_closes_it_at_its_start(
    database_admin_url,
):
    """Caso 16: si el segmento se creó antes, el W.O. lo cierra en su inicio."""

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(
            engine, config=rules_config(), segment_minute_end=None
        )
        created = await call_create_segment(
            engine,
            context,
            match.match_id,
            CreateMatchSegmentRequest(segment_number=2, minute_start=45),
        )

        response = await close_through_the_route(
            engine, context, match.match_id, walkover_pair(match)
        )

        assert response["status"] == "success"
        state = await _read_walkover_state(engine, match)
        assert state["status"] == "finished"
        assert state["segments"] == [
            {
                "id": match.segment_id,
                "segment_number": 1,
                "minute_start": 0,
                "minute_end": created["minute_start"],
                "status": "completed",
            },
            {
                "id": state["segments"][1]["id"],
                "segment_number": 2,
                "minute_start": created["minute_start"],
                "minute_end": created["minute_start"],
                "status": "completed",
            },
        ]

