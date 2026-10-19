"""Immutability of confirmed match results in the database (R03: RF-010 to RF-013).

A confirmed result (``result_confirmed = TRUE``) must not be editable nor
deletable through any path, including direct SQL. These tests run as
``bracket_app`` (no superuser, no ``BYPASSRLS``), build their own organization,
tournament, version, stage, teams and matches, and never depend on demo data or
on execution order: the ``db_session`` fixture rolls the whole tenant back.

The legitimate flows are covered too, because the trigger must not block them:
closing a report from ``result_confirmed = FALSE``, the administrative
resolution, the bracket advancement, the double-elimination reset and the
development seed.

Finally, the migration itself is verified on a throwaway database applied with
the administrator role: 016 works on a clean database, on one already migrated
through 015, and can be re-run without failing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import set_rls_context
from app.core.tenancy import AuthContext
from app.modules.advancement.service import AdvancementService
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from db_helpers import (
    TenantContext,
    application_database_url,
    insert_player,
    set_tenant_context,
)
from scripts import seed_demo

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_DIR = REPO_ROOT / "infra" / "postgres" / "init"
MIGRATIONS_DIR = REPO_ROOT / "infra" / "postgres" / "migrations"
MIGRATION_016 = MIGRATIONS_DIR / "016_confirmed_match_result_immutability.sql"

TRIGGER_NAME = "trg_protect_confirmed_match_result"
FUNCTION_NAME = "prevent_confirmed_match_result_mutation"

REGULAR = "regular"
PENALTIES = "penalties"
ADMINISTRATIVE = "administrative"

# Result payloads used to build a confirmed match without going through the
# service: the same statement is allowed while ``result_confirmed = FALSE``.
CONFIRMED_RESULTS: dict[str, dict[str, object]] = {
    REGULAR: {
        "home_score_regular": 2,
        "away_score_regular": 1,
        "home_score": 2,
        "away_score": 1,
        "home_penalties": None,
        "away_penalties": None,
        "status": "finished",
        "resolution_type": "regular",
        "resolution_reason": None,
        "winner": "home",
    },
    PENALTIES: {
        "home_score_regular": 1,
        "away_score_regular": 1,
        "home_score": 1,
        "away_score": 1,
        "home_penalties": 4,
        "away_penalties": 3,
        "status": "finished",
        "resolution_type": "penalties",
        "resolution_reason": None,
        "winner": "home",
    },
    ADMINISTRATIVE: {
        "home_score_regular": 3,
        "away_score_regular": 0,
        "home_score": 3,
        "away_score": 0,
        "home_penalties": None,
        "away_penalties": None,
        "status": "administrative_resolution",
        "resolution_type": "administrative",
        "resolution_reason": "Resolución administrativa original",
        "winner": "home",
    },
}


def _context(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


@dataclass(frozen=True)
class MatchStructure:
    """Minimal tournament structure with one match ready to be confirmed."""

    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    match_id: UUID


@dataclass(frozen=True)
class ClosableMatch:
    """Structure with teams, planilla, active segment and a published version."""

    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    match_id: UUID
    segment_id: UUID
    home_player_id: UUID
    away_player_id: UUID


async def _create_tournament(
    session,
    tenant: TenantContext,
    *,
    label: str,
) -> tuple[UUID, UUID, UUID]:
    """Create a draft tournament with its version, one stage and a valid config."""

    config = json.dumps(DEFAULT_RULES_CONFIG)
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
                "name": f"R03 {label} {uuid4().hex[:8]}",
                "config": config,
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
                "config": config,
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


async def _publish_version(session, tournament_id: UUID, version_id: UUID) -> None:
    """Publish the version and the tournament, in the order the application does."""

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


async def _register_team(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    *,
    label: str,
) -> UUID:
    """Register a team, enroll it in the tournament and assign it to the stage."""

    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"Team {label} {uuid4().hex[:6]}",
                "short_code": f"{label[:2].upper()}{uuid4().hex[:5].upper()}",
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


async def _insert_match(
    session,
    tenant: TenantContext,
    *,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    home_team_id: UUID | None,
    away_team_id: UUID | None,
    status: str = "scheduled",
    bracket_code: str | None = None,
    matchday: int = 1,
) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday, bracket_code)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, :status, :matchday, :bracket_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id) if home_team_id else None,
                "away_team_id": str(away_team_id) if away_team_id else None,
                "status": status,
                "matchday": matchday,
                "bracket_code": bracket_code,
            },
        )
    ).scalar_one()


async def _insert_segment(session, tenant: TenantContext, match_id: UUID) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 90, 'active')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()


async def _insert_roster(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    team_id: UUID,
    *,
    dorsal_number: int,
) -> tuple[UUID, UUID]:
    """Create a tenant-owned player plus its active roster, returning both ids."""

    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name=f"R03{dorsal_number}",
        last_name=f"Team{team_id.hex[:4]}",
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
    return player_id, roster_id


async def _insert_match_roster(
    session,
    tenant: TenantContext,
    *,
    match_id: UUID,
    roster_id: UUID,
    player_id: UUID,
    team_id: UUID,
) -> None:
    await session.execute(
        text("""
            INSERT INTO match_rosters
                (organization_id, match_id, roster_id, player_id, team_id, role, is_valid)
            VALUES
                (:organization_id, :match_id, :roster_id, :player_id, :team_id, 'starter', TRUE)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "roster_id": str(roster_id),
            "player_id": str(player_id),
            "team_id": str(team_id),
        },
    )


async def _create_match_structure(
    session,
    tenant: TenantContext,
    *,
    label: str,
    published: bool = False,
) -> MatchStructure:
    """Create a tournament with two teams and one scheduled match."""

    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, label=label
    )
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id, label="home"
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id, label="away"
    )
    match_id = await _insert_match(
        session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )
    if published:
        await _publish_version(session, tournament_id, version_id)
    return MatchStructure(
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        match_id=match_id,
    )


async def _confirm_match(
    session,
    structure: MatchStructure,
    kind: str = REGULAR,
) -> None:
    """Write a full result and confirm it, starting from ``result_confirmed = FALSE``."""

    values = CONFIRMED_RESULTS[kind]
    winner_team_id = (
        structure.home_team_id if values["winner"] == "home" else structure.away_team_id
    )
    result_values = {key: value for key, value in values.items() if key != "winner"}
    result = await session.execute(
        text("""
            UPDATE matches
            SET home_score_regular = CAST(:home_score_regular AS INT),
                away_score_regular = CAST(:away_score_regular AS INT),
                home_score = CAST(:home_score AS INT),
                away_score = CAST(:away_score AS INT),
                home_penalties = CAST(:home_penalties AS INT),
                away_penalties = CAST(:away_penalties AS INT),
                winner_team_id = CAST(:winner_team_id AS UUID),
                status = CAST(:status AS VARCHAR),
                resolution_type = CAST(:resolution_type AS VARCHAR),
                resolution_reason = CAST(:resolution_reason AS VARCHAR),
                result_confirmed = TRUE,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :match_id
        """),
        {
            **result_values,
            "winner_team_id": str(winner_team_id),
            "match_id": str(structure.match_id),
        },
    )
    assert result.rowcount == 1


async def _create_confirmed_match(
    session,
    tenant: TenantContext,
    *,
    label: str,
    kind: str = REGULAR,
) -> MatchStructure:
    structure = await _create_match_structure(session, tenant, label=label)
    await _confirm_match(session, structure, kind)
    return structure


async def _match_row(session, match_id: UUID) -> dict[str, object]:
    row = (
        await session.execute(
            text("""
                SELECT home_score_regular, away_score_regular, home_score, away_score,
                       home_penalties, away_penalties, winner_team_id, status,
                       resolution_type, resolution_reason, result_confirmed
                FROM matches
                WHERE id = :match_id
            """),
            {"match_id": str(match_id)},
        )
    ).mappings().one()
    return dict(row)


async def _expect_blocked_update(
    session,
    match_id: UUID,
    set_clause: str,
    params: dict[str, object],
) -> str:
    """Run a direct UPDATE that must be rejected and return the error message."""

    with pytest.raises(DBAPIError) as error:
        async with session.begin_nested():
            await session.execute(
                text(
                    f"UPDATE matches SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :match_id"
                ),
                {**params, "match_id": str(match_id)},
            )
    return f"{error.value.orig} {error.value}"


# ---------------------------------------------------------------------------
# RF-010 — a confirmed result cannot be updated
# ---------------------------------------------------------------------------

PROTECTED_FIELD_CASES = (
    pytest.param(REGULAR, "home_score_regular", "CAST(:value AS INT)", 1, id="home_score_regular"),
    pytest.param(REGULAR, "away_score_regular", "CAST(:value AS INT)", 0, id="away_score_regular"),
    pytest.param(REGULAR, "home_score", "CAST(:value AS INT)", 3, id="home_score"),
    pytest.param(REGULAR, "away_score", "CAST(:value AS INT)", 2, id="away_score"),
    pytest.param(PENALTIES, "home_penalties", "CAST(:value AS INT)", 5, id="home_penalties"),
    pytest.param(PENALTIES, "away_penalties", "CAST(:value AS INT)", 2, id="away_penalties"),
    pytest.param(REGULAR, "winner_team_id", "CAST(:value AS UUID)", None, id="winner_team_id"),
    pytest.param(REGULAR, "status", "CAST(:value AS VARCHAR)", "live", id="status"),
    pytest.param(
        REGULAR, "resolution_type", "CAST(:value AS VARCHAR)", "walkover", id="resolution_type"
    ),
    pytest.param(
        ADMINISTRATIVE,
        "resolution_reason",
        "CAST(:value AS VARCHAR)",
        "Motivo modificado",
        id="resolution_reason",
    ),
    pytest.param(
        REGULAR, "result_confirmed", "CAST(:value AS BOOLEAN)", False, id="result_confirmed"
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "column", "cast", "value"), PROTECTED_FIELD_CASES)
async def test_direct_update_of_each_protected_field_is_rejected(
    db_session, tenant_factory, kind, column, cast, value
):
    tenant = await tenant_factory(f"Protected {column}")
    await set_tenant_context(db_session, tenant)
    structure = await _create_confirmed_match(db_session, tenant, label=column, kind=kind)
    before = await _match_row(db_session, structure.match_id)

    message = await _expect_blocked_update(
        db_session,
        structure.match_id,
        f"{column} = {cast}",
        {"value": value},
    )

    assert "resultado confirmado" in message
    assert "inmutable" in message

    # The blocked statement left no partial change behind.
    assert await _match_row(db_session, structure.match_id) == before


@pytest.mark.asyncio
async def test_rolling_back_result_confirmed_to_false_is_rejected(db_session, tenant_factory):
    tenant = await tenant_factory("Reopen attempt")
    await set_tenant_context(db_session, tenant)
    structure = await _create_confirmed_match(db_session, tenant, label="reopen")

    message = await _expect_blocked_update(
        db_session,
        structure.match_id,
        "result_confirmed = CAST(:value AS BOOLEAN)",
        {"value": False},
    )

    assert "resultado confirmado" in message
    assert (await _match_row(db_session, structure.match_id))["result_confirmed"] is True


@pytest.mark.asyncio
async def test_update_with_the_same_values_is_allowed(db_session, tenant_factory):
    tenant = await tenant_factory("Idempotent retry")
    await set_tenant_context(db_session, tenant)
    structure = await _create_confirmed_match(db_session, tenant, label="same-values")
    values = CONFIRMED_RESULTS[REGULAR]
    before = await _match_row(db_session, structure.match_id)

    result = await db_session.execute(
        text("""
            UPDATE matches
            SET home_score_regular = CAST(:home_score_regular AS INT),
                away_score_regular = CAST(:away_score_regular AS INT),
                home_score = CAST(:home_score AS INT),
                away_score = CAST(:away_score AS INT),
                home_penalties = CAST(:home_penalties AS INT),
                away_penalties = CAST(:away_penalties AS INT),
                winner_team_id = CAST(:winner_team_id AS UUID),
                status = CAST(:status AS VARCHAR),
                resolution_type = CAST(:resolution_type AS VARCHAR),
                resolution_reason = CAST(:resolution_reason AS VARCHAR),
                result_confirmed = TRUE,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :match_id
        """),
        {
            **{key: value for key, value in values.items() if key != "winner"},
            "winner_team_id": str(structure.home_team_id),
            "match_id": str(structure.match_id),
        },
    )

    assert result.rowcount == 1
    assert await _match_row(db_session, structure.match_id) == before


@pytest.mark.asyncio
async def test_update_of_non_result_fields_is_allowed(db_session, tenant_factory):
    tenant = await tenant_factory("Non result fields")
    await set_tenant_context(db_session, tenant)
    structure = await _create_confirmed_match(db_session, tenant, label="updated-at")
    before = await _match_row(db_session, structure.match_id)

    result = await db_session.execute(
        text("""
            UPDATE matches
            SET match_date = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :match_id
        """),
        {"match_id": str(structure.match_id)},
    )

    assert result.rowcount == 1
    assert await _match_row(db_session, structure.match_id) == before


@pytest.mark.asyncio
async def test_protection_applies_to_the_application_role(db_session):
    """RF-010: the trigger is enforced for ``bracket_app``, not only for admins."""

    role = (
        await db_session.execute(
            text("""
                SELECT current_user AS role_name, rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = current_user
            """)
        )
    ).mappings().one()

    assert role["role_name"] == "bracket_app"
    assert role["rolsuper"] is False
    assert role["rolbypassrls"] is False


@pytest.mark.asyncio
async def test_bulk_update_touching_a_confirmed_match_aborts_the_statement(
    db_session, tenant_factory
):
    """Spec R03 case 9: a statement that also matches a confirmed match fails whole."""

    tenant = await tenant_factory("Bulk update")
    await set_tenant_context(db_session, tenant)
    confirmed = await _create_match_structure(db_session, tenant, label="bulk")
    pending_id = await _insert_match(
        db_session,
        tenant,
        tournament_id=confirmed.tournament_id,
        version_id=confirmed.version_id,
        stage_id=confirmed.stage_id,
        home_team_id=confirmed.home_team_id,
        away_team_id=confirmed.away_team_id,
        matchday=2,
    )
    await _confirm_match(db_session, confirmed)

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("""
                    UPDATE matches
                    SET status = 'live'
                    WHERE organization_id = :organization_id
                      AND stage_id = :stage_id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "stage_id": str(confirmed.stage_id),
                },
            )

    assert "resultado confirmado" in f"{error.value.orig} {error.value}"

    statuses = dict(
        (
            await db_session.execute(
                text("""
                    SELECT id, status
                    FROM matches
                    WHERE id IN (:confirmed_id, :pending_id)
                """),
                {
                    "confirmed_id": str(confirmed.match_id),
                    "pending_id": str(pending_id),
                },
            )
        ).all()
    )
    assert statuses[confirmed.match_id] == "finished"
    assert statuses[pending_id] == "scheduled"


# ---------------------------------------------------------------------------
# RF-011 — a confirmed result cannot be deleted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_of_a_confirmed_match_is_rejected(db_session, tenant_factory):
    tenant = await tenant_factory("Delete confirmed")
    await set_tenant_context(db_session, tenant)
    structure = await _create_confirmed_match(db_session, tenant, label="delete")

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM matches WHERE id = :match_id"),
                {"match_id": str(structure.match_id)},
            )

    message = f"{error.value.orig} {error.value}"
    assert "resultado confirmado" in message
    assert "borrar" in message
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM matches WHERE id = :match_id"),
            {"match_id": str(structure.match_id)},
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_deleting_a_non_confirmed_match_keeps_the_previous_rules(db_session, tenant_factory):
    tenant = await tenant_factory("Delete pending")
    await set_tenant_context(db_session, tenant)

    # A draft version without a confirmed result can still be cleaned up.
    pending = await _create_match_structure(db_session, tenant, label="draft-delete")
    deleted = await db_session.execute(
        text("DELETE FROM matches WHERE id = :match_id"),
        {"match_id": str(pending.match_id)},
    )
    assert deleted.rowcount == 1

    # A published version keeps its own structural protection.
    published = await _create_match_structure(
        db_session, tenant, label="published-delete", published=True
    )
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM matches WHERE id = :match_id"),
                {"match_id": str(published.match_id)},
            )
    message = f"{error.value.orig} {error.value}"
    assert "versión publicada o archivada es inmutable" in message
    assert "resultado confirmado" not in message


# ---------------------------------------------------------------------------
# RF-012 — legitimate flows keep working
# ---------------------------------------------------------------------------


async def _create_closable_match(
    session,
    tenant: TenantContext,
    *,
    label: str,
) -> ClosableMatch:
    """Build a published match with planilla, active segment and both teams."""

    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, label=label
    )
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id, label="home"
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id, label="away"
    )
    match_id = await _insert_match(
        session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )
    segment_id = await _insert_segment(session, tenant, match_id)
    home_player_id, home_roster_id = await _insert_roster(
        session, tenant, tournament_id, home_team_id, dorsal_number=9
    )
    away_player_id, away_roster_id = await _insert_roster(
        session, tenant, tournament_id, away_team_id, dorsal_number=10
    )
    await _insert_match_roster(
        session,
        tenant,
        match_id=match_id,
        roster_id=home_roster_id,
        player_id=home_player_id,
        team_id=home_team_id,
    )
    await _insert_match_roster(
        session,
        tenant,
        match_id=match_id,
        roster_id=away_roster_id,
        player_id=away_player_id,
        team_id=away_team_id,
    )
    await _publish_version(session, tournament_id, version_id)

    return ClosableMatch(
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        match_id=match_id,
        segment_id=segment_id,
        home_player_id=home_player_id,
        away_player_id=away_player_id,
    )


async def _hand_over_transaction(session) -> None:
    """Release the fixture savepoint so the service can open its own transaction.

    ``CloseMatchReportService`` owns the transaction it writes in
    (``async with self.db.begin()``), exactly as it does during a request. The
    ``db_session`` fixture joins the outer connection transaction with a
    SAVEPOINT, so committing here releases only that savepoint and the fixture
    still rolls the whole tenant back when the test ends.
    """

    await session.commit()


@pytest.mark.asyncio
async def test_normal_close_confirms_the_result_and_then_freezes_it(db_session, tenant_factory):
    tenant = await tenant_factory("Close report")
    await set_tenant_context(db_session, tenant)
    match = await _create_closable_match(db_session, tenant, label="close")
    await _hand_over_transaction(db_session)

    dto = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=2,
        away_score_regular=1,
        home_score=2,
        away_score=1,
        winner_team_id=match.home_team_id,
        events=[
            MatchEventPayload(
                client_event_id="r03-close-1",
                event_type="goal",
                team_id=match.home_team_id,
                player_id=match.home_player_id,
                minute=11,
                segment_id=match.segment_id,
            ),
            MatchEventPayload(
                client_event_id="r03-close-2",
                event_type="goal",
                team_id=match.home_team_id,
                player_id=match.home_player_id,
                minute=22,
                segment_id=match.segment_id,
            ),
            MatchEventPayload(
                client_event_id="r03-close-3",
                event_type="goal",
                team_id=match.away_team_id,
                player_id=match.away_player_id,
                minute=33,
                segment_id=match.segment_id,
            ),
        ],
    )

    outcome = await CloseMatchReportService(db_session).execute(
        _context(tenant), match.match_id, dto
    )

    assert outcome["status"] == "success"
    assert outcome["home_score"] == 2
    assert outcome["away_score"] == 1

    row = await _match_row(db_session, match.match_id)
    assert row["status"] == "finished"
    assert row["resolution_type"] == "regular"
    assert row["result_confirmed"] is True
    assert (row["home_score"], row["away_score"]) == (2, 1)
    assert row["winner_team_id"] == match.home_team_id

    segment_status = (
        await db_session.execute(
            text("SELECT status FROM match_segments WHERE id = :segment_id"),
            {"segment_id": str(match.segment_id)},
        )
    ).scalar_one()
    assert segment_status == "completed"

    # Once confirmed, the same result is frozen.
    message = await _expect_blocked_update(
        db_session,
        match.match_id,
        "home_score = CAST(:value AS INT)",
        {"value": 4},
    )
    assert "resultado confirmado" in message
    assert (await _match_row(db_session, match.match_id))["home_score"] == 2


@pytest.mark.asyncio
async def test_administrative_resolution_confirms_the_result_and_then_freezes_it(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Administrative resolution")
    await set_tenant_context(db_session, tenant)
    match = await _create_closable_match(db_session, tenant, label="administrative")
    await _hand_over_transaction(db_session)

    dto = CloseMatchReportDTO(
        resolution_type="administrative",
        home_score_regular=3,
        away_score_regular=0,
        home_score=3,
        away_score=0,
        winner_team_id=match.home_team_id,
        reason="Resolución administrativa de prueba",
    )

    outcome = await CloseMatchReportService(db_session).execute(
        _context(tenant), match.match_id, dto
    )

    assert outcome["status"] == "success"
    row = await _match_row(db_session, match.match_id)
    assert row["status"] == "administrative_resolution"
    assert row["resolution_type"] == "administrative"
    assert row["resolution_reason"] == "Resolución administrativa de prueba"
    assert row["result_confirmed"] is True

    message = await _expect_blocked_update(
        db_session,
        match.match_id,
        "resolution_reason = CAST(:value AS VARCHAR)",
        {"value": "Otro motivo"},
    )
    assert "resultado confirmado" in message

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM matches WHERE id = :match_id"),
                {"match_id": str(match.match_id)},
            )
    assert "borrar" in f"{error.value.orig} {error.value}"


@pytest.mark.asyncio
async def test_advancement_assigns_teams_to_unconfirmed_matches(db_session, tenant_factory):
    tenant = await tenant_factory("Advancement")
    await set_tenant_context(db_session, tenant)

    source = await _create_match_structure(db_session, tenant, label="advance-source")
    target_id = await _insert_match(
        db_session,
        tenant,
        tournament_id=source.tournament_id,
        version_id=source.version_id,
        stage_id=source.stage_id,
        home_team_id=None,
        away_team_id=None,
        matchday=2,
    )
    await db_session.execute(
        text("""
            INSERT INTO advancement_links
                (organization_id, source_match_id, target_match_id, target_side, outcome)
            VALUES
                (:organization_id, :source_match_id, :target_match_id, 'home', 'winner')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "source_match_id": str(source.match_id),
            "target_match_id": str(target_id),
        },
    )

    await AdvancementService(db_session).advance_from_match(
        _context(tenant),
        source.match_id,
        {"home_team_id": source.home_team_id, "away_team_id": source.away_team_id},
        SimpleNamespace(winner_team_id=source.home_team_id),
    )

    target = (
        await db_session.execute(
            text("""
                SELECT home_team_id, away_team_id, status, result_confirmed
                FROM matches
                WHERE id = :match_id
            """),
            {"match_id": str(target_id)},
        )
    ).mappings().one()
    assert target["home_team_id"] == source.home_team_id
    assert target["away_team_id"] is None
    assert target["status"] == "scheduled"
    assert target["result_confirmed"] is False


@pytest.mark.asyncio
async def test_bracket_reset_reactivates_the_cancelled_match(db_session, tenant_factory):
    tenant = await tenant_factory("Bracket reset")
    await set_tenant_context(db_session, tenant)

    tournament_id, version_id, stage_id = await _create_tournament(
        db_session, tenant, label="double-elimination"
    )
    home_team_id = await _register_team(
        db_session, tenant, tournament_id, version_id, stage_id, label="winners"
    )
    away_team_id = await _register_team(
        db_session, tenant, tournament_id, version_id, stage_id, label="losers"
    )
    gf1_id = await _insert_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        bracket_code="GF1",
    )
    gf2_id = await _insert_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=None,
        away_team_id=None,
        status="cancelled",
        bracket_code="GF2",
    )
    await _publish_version(db_session, tournament_id, version_id)

    await AdvancementService(db_session).activate_double_elimination_reset(
        _context(tenant),
        {
            "tournament_id": tournament_id,
            "tournament_version_id": version_id,
            "stage_id": stage_id,
            "bracket_code": "GF1",
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
        },
        SimpleNamespace(winner_team_id=away_team_id),
    )

    reset = (
        await db_session.execute(
            text("""
                SELECT home_team_id, away_team_id, status, result_confirmed
                FROM matches
                WHERE id = :match_id
            """),
            {"match_id": str(gf2_id)},
        )
    ).mappings().one()
    assert reset["status"] == "scheduled"
    assert reset["home_team_id"] == home_team_id
    assert reset["away_team_id"] == away_team_id
    assert reset["result_confirmed"] is False

    assert gf1_id != gf2_id


def _application_url_for(database: str) -> str:
    """Return the application role URL pointing at a throwaway database."""

    return make_url(application_database_url()).set(database=database).render_as_string(
        hide_password=False
    )


async def _count_demo_rows(
    connection: asyncpg.Connection,
) -> tuple[int, int, int, int]:
    """Count the demo user, organization, players and tournaments."""

    user = await connection.fetchval(
        "SELECT count(*) FROM public.users WHERE LOWER(email) = LOWER($1)",
        seed_demo.DEMO_USER_EMAIL,
    )
    organization = await connection.fetchval(
        "SELECT count(*) FROM public.organizations WHERE slug = $1",
        seed_demo.DEMO_ORGANIZATION_SLUG,
    )
    players = await connection.fetchval(
        """
        SELECT count(*)
        FROM public.players p
        JOIN public.organizations o ON o.id = p.organization_id
        WHERE o.slug = $1
        """,
        seed_demo.DEMO_ORGANIZATION_SLUG,
    )
    tournaments = await connection.fetchval(
        """
        SELECT count(*)
        FROM public.tournaments t
        JOIN public.organizations o ON o.id = t.organization_id
        WHERE o.slug = $1
        """,
        seed_demo.DEMO_ORGANIZATION_SLUG,
    )
    return user, organization, players, tournaments


@pytest.mark.asyncio
async def test_seed_demo_still_closes_and_confirms_matches(
    database_admin_url, monkeypatch
):
    """The development seed keeps closing reports with the trigger installed.

    ``seed_demo`` opens its own sessions and commits, so it runs against a
    throwaway database: executing it on the shared test database would leave
    demo rows behind and make later runs depend on them (RF-018 / RNF-008).
    """

    main_connection = await _connect(database_admin_url)
    try:
        demo_rows_before = await _count_demo_rows(main_connection)
    finally:
        await main_connection.close()

    database = await _create_database(database_admin_url)
    seed_engine = None
    try:
        admin_connection = await _connect(database_admin_url, database)
        try:
            await _apply_init(admin_connection)
            await _apply_migrations(admin_connection, first=1, last=18)
        finally:
            await admin_connection.close()

        seed_engine = create_async_engine(
            _application_url_for(database), pool_pre_ping=True
        )
        monkeypatch.setattr(
            seed_demo,
            "SessionFactory",
            async_sessionmaker(
                seed_engine, class_=AsyncSession, expire_on_commit=False
            ),
        )
        seeded = await seed_demo.seed_demo()

        assert seeded["players"] == seed_demo.DEMO_PLAYER_COUNT * len(
            seed_demo.TEAM_SPECS
        )
        organization_id = UUID(seeded["organization_id"])
        tournament_id = UUID(seeded["tournament_id"])

        seed_connection = await _connect(database_admin_url, database)
        try:
            confirmed = await seed_connection.fetch(
                """
                SELECT id, status, result_confirmed, home_score, away_score
                FROM public.matches
                WHERE organization_id = $1
                  AND tournament_id = $2
                  AND result_confirmed = TRUE
                """,
                organization_id,
                tournament_id,
            )
            assert len(confirmed) == 4
            assert {row["status"] for row in confirmed} == {"finished"}
            assert all(
                row["home_score"] is not None and row["away_score"] is not None
                for row in confirmed
            )

            # The seed encrypts the birth date and materializes the age with the
            # tournament start year; the plaintext column no longer exists.
            settings = get_settings()
            players = await seed_connection.fetch(
                """
                SELECT p.first_name,
                       p.last_name,
                       p.age_at_reference,
                       p.age_reference_year,
                       pgp_sym_decrypt(p.birth_date_encrypted, $3)::date::text
                           AS birth_date,
                       EXTRACT(YEAR FROM t.start_date)::int AS tournament_year
                FROM public.players p
                JOIN public.organizations o ON o.id = p.organization_id
                JOIN public.tournaments t
                  ON t.id = $2
                 AND t.organization_id = p.organization_id
                WHERE o.slug = $1
                """,
                seed_demo.DEMO_ORGANIZATION_SLUG,
                tournament_id,
                settings.player_data_key,
            )
            specs = {
                (player.first_name, player.last_name): player.birth_date
                for player in seed_demo.PLAYER_SPECS
            }
            assert len(players) == seed_demo.DEMO_PLAYER_COUNT * len(
                seed_demo.TEAM_SPECS
            )
            for row in players:
                expected_birth_date = specs[(row["first_name"], row["last_name"])]
                assert row["birth_date"] == expected_birth_date.isoformat()
                assert row["age_reference_year"] == row["tournament_year"]
                assert row["age_at_reference"] == (
                    row["tournament_year"] - expected_birth_date.year
                )
            assert (
                await seed_connection.fetchval(
                    """
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'players'
                      AND column_name = 'birth_date'
                    """
                )
                == 0
            )

            # The trigger also protects the results the seed just confirmed.
            with pytest.raises(asyncpg.PostgresError) as error:
                await seed_connection.execute(
                    "UPDATE public.matches SET away_score = 99 WHERE id = $1",
                    confirmed[0]["id"],
                )
            assert "resultado confirmado" in str(error.value)
        finally:
            await seed_connection.close()
    finally:
        if seed_engine is not None:
            await seed_engine.dispose()
        await _drop_database(database_admin_url, database)

    main_connection = await _connect(database_admin_url)
    try:
        assert await _count_demo_rows(main_connection) == demo_rows_before, (
            "seed_demo escribió datos demo en la base compartida"
        )
    finally:
        await main_connection.close()


# ---------------------------------------------------------------------------
# RF-013 — migration 016: clean database, migrated database and idempotency
# ---------------------------------------------------------------------------


def _connection_kwargs(url: str, database: str | None = None) -> dict[str, object]:
    parsed = make_url(url)
    return {
        "host": parsed.host or "127.0.0.1",
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "database": database or parsed.database,
    }


async def _connect(url: str, database: str | None = None) -> asyncpg.Connection:
    return await asyncpg.connect(**_connection_kwargs(url, database))


async def _create_database(admin_url: str) -> str:
    database = f"bc_t005_{uuid4().hex[:12]}"
    connection = await _connect(admin_url)
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()
    return database


async def _drop_database(admin_url: str, database: str) -> None:
    connection = await _connect(admin_url)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await connection.close()


async def _apply_init(connection: asyncpg.Connection) -> None:
    for filename in ("01_schema.sql", "02_public_projections.sql", "03_hardening.sql"):
        await connection.execute((INIT_DIR / filename).read_text(encoding="utf-8"))


async def _apply_migrations(connection: asyncpg.Connection, *, first: int, last: int) -> None:
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        if first <= version <= last:
            await connection.execute(path.read_text(encoding="utf-8"))


async def _apply_016(connection: asyncpg.Connection) -> None:
    await connection.execute(MIGRATION_016.read_text(encoding="utf-8"))


async def _trigger_definition(connection: asyncpg.Connection) -> str | None:
    return await connection.fetchval(
        """
        SELECT pg_get_triggerdef(t.oid)
        FROM pg_trigger t
        WHERE t.tgname = 'trg_protect_confirmed_match_result'
          AND t.tgrelid = 'public.matches'::regclass
          AND NOT t.tgisinternal
        """
    )


async def _function_source(connection: asyncpg.Connection) -> str | None:
    return await connection.fetchval(
        """
        SELECT prosrc
        FROM pg_proc
        WHERE proname = 'prevent_confirmed_match_result_mutation'
          AND pronamespace = 'public'::regnamespace
        """
    )


async def _count_triggers(connection: asyncpg.Connection) -> int:
    return await connection.fetchval(
        """
        SELECT count(*)
        FROM pg_trigger t
        WHERE t.tgname = 'trg_protect_confirmed_match_result'
          AND t.tgrelid = 'public.matches'::regclass
          AND NOT t.tgisinternal
        """
    )


MIGRATION_016_SEED_SQL = """
INSERT INTO public.organizations (id, name, slug)
VALUES ('d0000000-0000-4000-8000-000000000001', 'R03 Organization', 'r03-organization');

INSERT INTO public.users (id, email, password_hash, full_name)
VALUES (
    'd0000000-0000-4000-8000-000000000002', 'r03@example.test', 'hash', 'R03 Owner'
);

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES (
    'd0000000-0000-4000-8000-000000000003',
    'd0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000002',
    TRUE
);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    'd0000000-0000-4000-8000-000000000004',
    'd0000000-0000-4000-8000-000000000001',
    'R03 Cup', '2026', '2026-01-01', 'draft', '{}'::jsonb
);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config, phase_config,
    status, created_by_member_id
) VALUES (
    'd0000000-0000-4000-8000-000000000005',
    'd0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000004',
    1,
    '{"schema_version": "3.2.0"}'::jsonb,
    '{}'::jsonb,
    'draft',
    'd0000000-0000-4000-8000-000000000003'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order
) VALUES (
    'd0000000-0000-4000-8000-000000000006',
    'd0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000004',
    'd0000000-0000-4000-8000-000000000005',
    'Group stage', 'round_robin', 1
);

INSERT INTO public.teams (id, organization_id, name, short_code) VALUES
    ('d0000000-0000-4000-8000-000000000007',
     'd0000000-0000-4000-8000-000000000001', 'R03 Home', 'R03H'),
    ('d0000000-0000-4000-8000-000000000008',
     'd0000000-0000-4000-8000-000000000001', 'R03 Away', 'R03A');

INSERT INTO public.tournament_teams (id, organization_id, tournament_id, team_id, status) VALUES
    ('d0000000-0000-4000-8000-000000000009',
     'd0000000-0000-4000-8000-000000000001',
     'd0000000-0000-4000-8000-000000000004',
     'd0000000-0000-4000-8000-000000000007', 'registered'),
    ('d0000000-0000-4000-8000-00000000000a',
     'd0000000-0000-4000-8000-000000000001',
     'd0000000-0000-4000-8000-000000000004',
     'd0000000-0000-4000-8000-000000000008', 'registered');

INSERT INTO public.stage_teams (
    id, organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id
) VALUES
    ('d0000000-0000-4000-8000-00000000000b',
     'd0000000-0000-4000-8000-000000000001',
     'd0000000-0000-4000-8000-000000000004',
     'd0000000-0000-4000-8000-000000000005',
     'd0000000-0000-4000-8000-000000000006', NULL,
     'd0000000-0000-4000-8000-000000000007'),
    ('d0000000-0000-4000-8000-00000000000c',
     'd0000000-0000-4000-8000-000000000001',
     'd0000000-0000-4000-8000-000000000004',
     'd0000000-0000-4000-8000-000000000005',
     'd0000000-0000-4000-8000-000000000006', NULL,
     'd0000000-0000-4000-8000-000000000008');

INSERT INTO public.platform_admins (user_id, role_code, is_active)
VALUES ('d0000000-0000-4000-8000-000000000002', 'platform_admin', TRUE);

INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id, group_id,
    home_team_id, away_team_id, home_score_regular, away_score_regular, home_score,
    away_score, winner_team_id, status, resolution_type, result_confirmed
) VALUES (
    'd0000000-0000-4000-8000-00000000000d',
    'd0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000004',
    'd0000000-0000-4000-8000-000000000005',
    'd0000000-0000-4000-8000-000000000006', NULL,
    'd0000000-0000-4000-8000-000000000007',
    'd0000000-0000-4000-8000-000000000008',
    2, 1, 2, 1,
    'd0000000-0000-4000-8000-000000000007',
    'finished', 'regular', TRUE
), (
    'd0000000-0000-4000-8000-00000000000e',
    'd0000000-0000-4000-8000-000000000001',
    'd0000000-0000-4000-8000-000000000004',
    'd0000000-0000-4000-8000-000000000005',
    'd0000000-0000-4000-8000-000000000006', NULL,
    'd0000000-0000-4000-8000-000000000007',
    'd0000000-0000-4000-8000-000000000008',
    NULL, NULL, NULL, NULL, NULL,
    'scheduled', NULL, FALSE
);

SELECT set_config('app.current_organization_id',
                  'd0000000-0000-4000-8000-000000000001', FALSE);
SELECT set_config('app.current_user_id',
                  'd0000000-0000-4000-8000-000000000002', FALSE);
"""

CONFIRMED_MATCH_ID = "d0000000-0000-4000-8000-00000000000d"
PENDING_MATCH_ID = "d0000000-0000-4000-8000-00000000000e"


@pytest.mark.asyncio
async def test_clean_database_applies_init_and_migrations_through_016(database_admin_url):
    database = await _create_database(database_admin_url)
    connection = await _connect(database_admin_url, database)
    try:
        await _apply_init(connection)
        await _apply_migrations(connection, first=1, last=16)

        assert MIGRATION_016.exists(), "La migración 016 debe existir en el repositorio"
        assert MIGRATION_016.name.startswith("016_")
        assert int(MIGRATION_016.name[:3]) > 15

        definition = await _trigger_definition(connection)
        assert definition is not None
        assert definition.startswith(
            "CREATE TRIGGER trg_protect_confirmed_match_result BEFORE "
        )
        assert "DELETE" in definition
        assert "UPDATE" in definition
        assert "INSERT" not in definition
        assert "ON public.matches FOR EACH ROW" in definition
        assert "EXECUTE FUNCTION prevent_confirmed_match_result_mutation()" in definition

        source = await _function_source(connection)
        assert source is not None
        assert "IS DISTINCT FROM" in source
        assert source.count("OLD.result_confirmed") >= 1
        assert "platform_admin" not in source
        assert await _count_triggers(connection) == 1

        # Re-running the migration is idempotent: no duplicate objects and no error.
        await _apply_016(connection)
        await _apply_016(connection)
        assert await _count_triggers(connection) == 1
        assert (await _trigger_definition(connection)) == definition
        assert (await _function_source(connection)) == source
    finally:
        await connection.close()
        await _drop_database(database_admin_url, database)


@pytest.mark.asyncio
async def test_migration_016_applies_on_a_database_migrated_through_015(database_admin_url):
    database = await _create_database(database_admin_url)
    connection = await _connect(database_admin_url, database)
    try:
        await _apply_init(connection)
        await _apply_migrations(connection, first=1, last=15)

        # Before 016 the protection does not exist yet.
        assert await _trigger_definition(connection) is None
        assert await _function_source(connection) is None

        await connection.execute(MIGRATION_016_SEED_SQL)
        await connection.execute(
            f"UPDATE public.matches SET home_score = 3 WHERE id = '{CONFIRMED_MATCH_ID}'"
        )
        assert await connection.fetchval(
            f"SELECT home_score FROM public.matches WHERE id = '{CONFIRMED_MATCH_ID}'"
        ) == 3
        await connection.execute(
            f"UPDATE public.matches SET home_score = 2 WHERE id = '{CONFIRMED_MATCH_ID}'"
        )

        await _apply_016(connection)

        assert await _count_triggers(connection) == 1
        assert await _function_source(connection) is not None

        # A confirmed result cannot be updated nor deleted, not even for a
        # platform administrator (the trigger has no exception for it).
        with pytest.raises(asyncpg.PostgresError) as update_error:
            await connection.execute(
                f"UPDATE public.matches SET status = 'live' WHERE id = '{CONFIRMED_MATCH_ID}'"
            )
        assert "resultado confirmado" in str(update_error.value)
        assert "inmutable" in str(update_error.value)

        with pytest.raises(asyncpg.PostgresError) as delete_error:
            await connection.execute(
                f"DELETE FROM public.matches WHERE id = '{CONFIRMED_MATCH_ID}'"
            )
        assert "resultado confirmado" in str(delete_error.value)

        assert await connection.fetchval(
            f"SELECT count(*) FROM public.matches WHERE id = '{CONFIRMED_MATCH_ID}'"
        ) == 1
        assert await connection.fetchval(
            f"SELECT status FROM public.matches WHERE id = '{CONFIRMED_MATCH_ID}'"
        ) == "finished"

        # Non-result updates and unconfirmed matches stay fully operational.
        await connection.execute(
            f"UPDATE public.matches SET updated_at = CURRENT_TIMESTAMP "
            f"WHERE id = '{CONFIRMED_MATCH_ID}'"
        )
        await connection.execute(
            f"UPDATE public.matches SET home_score = 1 WHERE id = '{PENDING_MATCH_ID}'"
        )
        assert await connection.fetchval(
            f"SELECT home_score FROM public.matches WHERE id = '{PENDING_MATCH_ID}'"
        ) == 1

        # Re-running 016 does not fail on the existing objects.
        await _apply_016(connection)
        assert await _count_triggers(connection) == 1
    finally:
        await connection.close()
        await _drop_database(database_admin_url, database)
