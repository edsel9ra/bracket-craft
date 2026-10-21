"""Migration 023: persisted stage legs (RF-009).

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the additive change is validated both on an
already migrated volume (022 -> 023) and on the clean-volume chain
(init + 001..023). The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` because creating databases and applying DDL require a
role the application role does not have.

Assertions cover the column shape (``SMALLINT NOT NULL DEFAULT 1``), the
``chk_stages_schedule_legs`` CHECK (0 and 3 rejected, 1 and 2 accepted), the
absence of a data backfill (a stage that existed before 023 stays at one leg),
the version clone copying two legs, the league draw persisting the received
legs, and the equality between the clean and the migrated chains.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.tournaments.router import (
    _create_draft_version_record,
    _draw_non_swiss_schedule,
)
from app.modules.tournaments.schemas import GenerateSingleEliminationRequest
from migration_helpers import apply_migration, throwaway_database

ORG = "23000000-0000-4000-8000-000000000001"
USER = "23000000-0000-4000-8000-000000000002"
MEMBER = "23000000-0000-4000-8000-000000000003"
ROLE = "23000000-0000-4000-8000-000000000004"
TOURNAMENT = "23000000-0000-4000-8000-000000000010"
VERSION = "23000000-0000-4000-8000-000000000011"
STAGE = "23000000-0000-4000-8000-000000000012"
EXTRA_STAGE = "23000000-0000-4000-8000-000000000013"
TEAM_HOME = "23000000-0000-4000-8000-000000000021"
TEAM_AWAY = "23000000-0000-4000-8000-000000000022"
TOURNAMENT_TEAM_HOME = "23000000-0000-4000-8000-000000000031"
TOURNAMENT_TEAM_AWAY = "23000000-0000-4000-8000-000000000032"

CHECK_NAME = "chk_stages_schedule_legs"
START_DATE = datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc)

# The source stage is inserted without ``schedule_legs``: migration 023 does not
# exist yet, and the point is that the column arrives with its default.
SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug)
VALUES ('{ORG}', 'Migration 023 Org', 'migration-023-org');

INSERT INTO public.users (id, email, password_hash, full_name)
VALUES ('{USER}', 'migration-023@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.roles (id, organization_id, role_definition_id, name, permissions)
SELECT '{ROLE}', '{ORG}', rd.id, 'Owner', '["MANAGE_TOURNAMENTS"]'::jsonb
FROM public.role_definitions rd
WHERE rd.code = 'owner';

INSERT INTO public.organization_user_roles (
    organization_id, organization_user_id, role_id
) VALUES ('{ORG}', '{MEMBER}', '{ROLE}');

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 023 Cup', '2026', DATE '2026-01-01',
    'draft', '{{}}'::jsonb
);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    '{VERSION}', '{ORG}', '{TOURNAMENT}', 1, '{json.dumps(DEFAULT_RULES_CONFIG)}'::jsonb,
    '{{}}'::jsonb, 'draft', '{MEMBER}'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES
    ('{STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'League', 'round_robin', 1),
    ('{EXTRA_STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Cup', 'swiss', 2);

INSERT INTO public.teams (id, organization_id, name, short_code)
VALUES
    ('{TEAM_HOME}', '{ORG}', 'Home 023', 'H23'),
    ('{TEAM_AWAY}', '{ORG}', 'Away 023', 'A23');

INSERT INTO public.tournament_teams (
    id, organization_id, tournament_id, team_id, status
) VALUES
    ('{TOURNAMENT_TEAM_HOME}', '{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', 'registered'),
    ('{TOURNAMENT_TEAM_AWAY}', '{ORG}', '{TOURNAMENT}', '{TEAM_AWAY}', 'registered');

INSERT INTO public.stage_teams (
    organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id
) VALUES
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL, '{TEAM_HOME}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL, '{TEAM_AWAY}');
"""


async def column_definition(
    connection: asyncpg.Connection,
) -> tuple[str, bool, str | None]:
    row = await connection.fetchrow(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid) AS default_expr
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.stages'::regclass
          AND a.attname = 'schedule_legs'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    )
    assert row is not None, "falta la columna stages.schedule_legs"
    return row["data_type"], row["attnotnull"], row["default_expr"]


async def constraint_definition(
    connection: asyncpg.Connection,
) -> tuple[bool, str]:
    row = await connection.fetchrow(
        """
        SELECT con.convalidated, pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = 'public.stages'::regclass
          AND con.conname = $1
        """,
        CHECK_NAME,
    )
    assert row is not None, f"falta la restricción {CHECK_NAME}"
    return row["convalidated"], row["definition"]


async def stage_legs(connection: asyncpg.Connection, stage_id: str) -> int:
    return await connection.fetchval(
        "SELECT schedule_legs FROM public.stages WHERE id = $1", stage_id
    )


async def stages_snapshot(connection: asyncpg.Connection) -> dict[str, object]:
    columns = await connection.fetch(
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid) AS default_expr
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.stages'::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attname
        """
    )
    constraints = await connection.fetch(
        """
        SELECT con.conname, con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = 'public.stages'::regclass
        ORDER BY con.conname
        """
    )
    return {
        "columns": [
            (row["attname"], row["data_type"], row["attnotnull"], row["default_expr"])
            for row in columns
        ],
        "constraints": [
            (row["conname"], row["convalidated"], row["definition"])
            for row in constraints
        ],
    }


# ---------------------------------------------------------------------------
# Shape: column, default and CHECK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_023_adds_default_one_and_check_without_backfill(database_admin_url):
    async with throwaway_database(database_admin_url, last=22) as connection:
        await connection.execute(SEED_SQL)
        assert await connection.fetchval(
            """
            SELECT count(*) FROM pg_attribute
            WHERE attrelid = 'public.stages'::regclass
              AND attname = 'schedule_legs'
              AND attnum > 0
              AND NOT attisdropped
            """
        ) == 0

        await apply_migration(connection, 23)

        # Existing stages were not rewritten: the default left them at one leg.
        assert await stage_legs(connection, STAGE) == 1
        assert await stage_legs(connection, EXTRA_STAGE) == 1

        data_type, not_null, default_expr = await column_definition(connection)
        assert data_type == "smallint"
        assert not_null is True
        assert default_expr is not None
        assert default_expr.strip() == "1"

        validated, definition = await constraint_definition(connection)
        assert validated is True
        assert "schedule_legs" in definition
        assert "1" in definition
        assert "2" in definition

        # Only 1 and 2 are accepted.
        await connection.execute(
            "UPDATE public.stages SET schedule_legs = 2 WHERE id = $1", STAGE
        )
        assert await stage_legs(connection, STAGE) == 2
        await connection.execute(
            "UPDATE public.stages SET schedule_legs = 1 WHERE id = $1", STAGE
        )

        for rejected in (0, 3):
            with pytest.raises(asyncpg.exceptions.CheckViolationError) as error:
                await connection.execute(
                    "UPDATE public.stages SET schedule_legs = $2 WHERE id = $1",
                    STAGE,
                    rejected,
                )
            assert CHECK_NAME in str(error.value)
            assert await stage_legs(connection, STAGE) == 1


# ---------------------------------------------------------------------------
# Persistence: clone and league draw
# ---------------------------------------------------------------------------


def async_database_url(admin_url: str, database: str) -> str:
    url = make_url(admin_url)
    if "asyncpg" not in url.drivername:
        url = url.set(drivername="postgresql+asyncpg")
    return url.set(database=database).render_as_string(hide_password=False)


def auth_context() -> AuthContext:
    return AuthContext(
        user_id=UUID(USER),
        organization_id=UUID(ORG),
        organization_user_id=UUID(MEMBER),
    )


@pytest.mark.asyncio
async def test_023_clone_copies_two_legs(database_admin_url):
    async with throwaway_database(database_admin_url, last=22) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 23)
        # A historical two-leg league stage (draft) is the clone source.
        await connection.execute(
            "UPDATE public.stages SET schedule_legs = 2 WHERE id = $1", STAGE
        )
        await connection.execute(
            "UPDATE public.tournament_versions SET status = 'published' WHERE id = $1",
            VERSION,
        )
        await connection.execute(
            """
            UPDATE public.tournaments
            SET status = 'published', published_version_id = $1
            WHERE id = $2
            """,
            VERSION,
            TOURNAMENT,
        )
        database = await connection.fetchval("SELECT current_database()")

        engine = create_async_engine(
            async_database_url(database_admin_url, database)
        )
        try:
            async with engine.connect() as connection_orm:
                session = AsyncSession(bind=connection_orm, expire_on_commit=False)
                async with session.begin():
                    cloned = await _create_draft_version_record(
                        session, auth_context(), UUID(TOURNAMENT), None
                    )
        finally:
            await engine.dispose()

        cloned_stage_legs = await connection.fetch(
            """
            SELECT id, stage_type, schedule_legs
            FROM public.stages
            WHERE tournament_version_id = $1
            ORDER BY stage_order, id
            """,
            UUID(str(cloned["id"])),
        )
        assert [
            (row["stage_type"], row["schedule_legs"]) for row in cloned_stage_legs
        ] == [("round_robin", 2), ("swiss", 1)]


@pytest.mark.asyncio
async def test_023_league_draw_persists_two_legs(database_admin_url):
    async with throwaway_database(database_admin_url, last=23) as connection:
        await connection.execute(SEED_SQL)
        database = await connection.fetchval("SELECT current_database()")

        payload = GenerateSingleEliminationRequest(
            version_id=UUID(VERSION),
            stage_id=UUID(STAGE),
            start_date=START_DATE,
            round_interval_days=7,
            match_interval_hours=2,
            seed=17,
            legs=2,
        )
        team_rows = [
            {"team_id": UUID(TEAM_HOME), "group_id": None},
            {"team_id": UUID(TEAM_AWAY), "group_id": None},
        ]

        engine = create_async_engine(async_database_url(database_admin_url, database))
        try:
            async with engine.connect() as connection_orm:
                session = AsyncSession(bind=connection_orm, expire_on_commit=False)
                async with session.begin():
                    response = await _draw_non_swiss_schedule(
                        session,
                        auth_context(),
                        UUID(TOURNAMENT),
                        payload,
                        "round_robin",
                        team_rows,
                        [row["team_id"] for row in team_rows],
                    )
        finally:
            await engine.dispose()

        assert response.match_count == 2
        assert await stage_legs(connection, STAGE) == 2
        # The non-league stage keeps the default and is left untouched.
        assert await stage_legs(connection, EXTRA_STAGE) == 1
        assert await connection.fetchval(
            "SELECT count(*) FROM public.matches WHERE stage_id = $1", UUID(STAGE)
        ) == 2


# ---------------------------------------------------------------------------
# Clean chain versus migrated chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_023_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=22) as connection:
        await apply_migration(connection, 23)
        migrated = await stages_snapshot(connection)

    async with throwaway_database(database_admin_url, last=23) as clean:
        assert await stages_snapshot(clean) == migrated

        # The clean chain really carries the CHECK too.
        await clean.execute(SEED_SQL)
        for rejected in (0, 3):
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await clean.execute(
                    "UPDATE public.stages SET schedule_legs = $2 WHERE id = $1",
                    STAGE,
                    rejected,
                )
