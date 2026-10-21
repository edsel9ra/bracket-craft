"""Migration 022: structural minute bounds on match events (RF-010).

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the additive change is validated both on an
already migrated volume (021 -> 022) and on the clean-volume chain
(init + 001..022). The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` because creating databases and applying DDL require a
role the application role does not have.

Assertions cover the two validated ``CHECK`` constraints, the accepted
boundaries (180 and 30), the rejected values (181 and 31), the aborting
pre-check that names both out-of-range counts without trimming rows, and the
equality between the clean and the migrated chains.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "22000000-0000-4000-8000-000000000001"
USER = "22000000-0000-4000-8000-000000000002"
MEMBER = "22000000-0000-4000-8000-000000000003"
TOURNAMENT = "22000000-0000-4000-8000-000000000010"
VERSION = "22000000-0000-4000-8000-000000000011"
STAGE = "22000000-0000-4000-8000-000000000012"
TEAM = "22000000-0000-4000-8000-000000000013"
TOURNAMENT_TEAM = "22000000-0000-4000-8000-000000000014"
STAGE_TEAM = "22000000-0000-4000-8000-000000000015"
MATCH = "22000000-0000-4000-8000-000000000016"
SEGMENT = "22000000-0000-4000-8000-000000000017"
PLAYER = "22000000-0000-4000-8000-000000000020"
ROSTER = "22000000-0000-4000-8000-000000000030"
MATCH_ROSTER = "22000000-0000-4000-8000-000000000040"

MINUTE_CHECK = "chk_match_event_minute_range"
ADDED_MINUTE_CHECK = "chk_match_event_added_minute_range"

# The segment accepts any minute up to 180 (``minute_end`` NULL), so the
# trigger 009 never masks the structural CHECK under test.
SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug)
VALUES ('{ORG}', 'Migration 022 Org', 'migration-022-org');

INSERT INTO public.users (id, email, password_hash, full_name)
VALUES ('{USER}', 'migration-022@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country,
    birth_date_encrypted, age_at_reference, age_reference_year
) VALUES (
    '{PLAYER}', '{ORG}', 'Minute', 'Player', 'DNI',
    decode('01', 'hex'), repeat('a', 64), 'ARG', decode('10', 'hex'), 25, 2026
);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 022 Cup', '2026', DATE '2026-01-01',
    'draft', '{{}}'::jsonb
);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    '{VERSION}', '{ORG}', '{TOURNAMENT}', 1, '{{}}'::jsonb, '{{}}'::jsonb,
    'draft', '{MEMBER}'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES ('{STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Group', 'round_robin', 1);

INSERT INTO public.teams (id, organization_id, name, short_code)
VALUES ('{TEAM}', '{ORG}', 'Migration 022 Team', 'M22');

INSERT INTO public.tournament_teams (
    id, organization_id, tournament_id, team_id, status
) VALUES ('{TOURNAMENT_TEAM}', '{ORG}', '{TOURNAMENT}', '{TEAM}', 'registered');

INSERT INTO public.stage_teams (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, team_id
) VALUES ('{STAGE_TEAM}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL, '{TEAM}');

INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, status, match_date, created_at
) VALUES (
    '{MATCH}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL, '{TEAM}',
    NULL, 'scheduled', '2026-01-05 12:00:00+00', '2026-01-05 00:00:00+00'
);

INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end,
    status, created_at
) VALUES (
    '{SEGMENT}', '{ORG}', '{MATCH}', 1, 0, NULL, 'active',
    '2026-01-05 00:00:00+00'
);

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    is_active, photo_consent, registered_at, valid_from, valid_to, eligible_from
) VALUES (
    '{ROSTER}', '{ORG}', '{TOURNAMENT}', '{TEAM}', '{PLAYER}', 9,
    TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
    '2026-01-01 00:00:00+00'
);

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    '{MATCH_ROSTER}', '{ORG}', '{MATCH}', '{ROSTER}', '{PLAYER}',
    '{TEAM}', '{TOURNAMENT}', NULL, 'starter', TRUE
);
"""


async def insert_event(
    connection: asyncpg.Connection,
    *,
    client_event_id: str,
    minute: int = 10,
    added_minute: int = 0,
) -> None:
    await connection.execute(
        """
        INSERT INTO public.match_events (
            organization_id, match_id, segment_id, team_id, player_id,
            event_type, minute, added_minute, client_event_id
        ) VALUES ($1, $2, $3, $4, $5, 'goal', $6, $7, $8)
        """,
        ORG,
        MATCH,
        SEGMENT,
        TEAM,
        PLAYER,
        minute,
        added_minute,
        client_event_id,
    )


async def constraint_definitions(
    connection: asyncpg.Connection,
) -> list[tuple[str, bool, str]]:
    rows = await connection.fetch(
        """
        SELECT con.conname, con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = 'public.match_events'::regclass
        ORDER BY con.conname
        """
    )
    return [
        (row["conname"], row["convalidated"], row["definition"]) for row in rows
    ]


async def minute_constraints(
    connection: asyncpg.Connection,
) -> dict[str, tuple[bool, str]]:
    rows = await constraint_definitions(connection)
    return {
        name: (validated, definition)
        for name, validated, definition in rows
        if name in {MINUTE_CHECK, ADDED_MINUTE_CHECK}
    }


async def column_definitions(
    connection: asyncpg.Connection,
) -> list[tuple[str, str, bool]]:
    rows = await connection.fetch(
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull
        FROM pg_attribute a
        WHERE a.attrelid = 'public.match_events'::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attname
        """
    )
    return [(row["attname"], row["data_type"], row["attnotnull"]) for row in rows]


async def table_snapshot(connection: asyncpg.Connection) -> dict[str, object]:
    return {
        "columns": await column_definitions(connection),
        "constraints": await constraint_definitions(connection),
    }


# ---------------------------------------------------------------------------
# Accepted and rejected boundaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_022_accepts_180_and_30_and_rejects_181_and_31(database_admin_url):
    async with throwaway_database(database_admin_url, last=21) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 22)

        await insert_event(
            connection, client_event_id="boundary-180", minute=180, added_minute=0
        )
        await insert_event(
            connection, client_event_id="boundary-30", minute=0, added_minute=30
        )
        await insert_event(
            connection, client_event_id="both-boundaries", minute=180, added_minute=30
        )

        stored = await connection.fetch(
            """
            SELECT client_event_id, minute, added_minute
            FROM public.match_events
            ORDER BY client_event_id
            """
        )
        assert [
            (row["client_event_id"], row["minute"], row["added_minute"])
            for row in stored
        ] == [
            ("both-boundaries", 180, 30),
            ("boundary-180", 180, 0),
            ("boundary-30", 0, 30),
        ]

        with pytest.raises(asyncpg.exceptions.CheckViolationError) as error:
            await insert_event(
                connection, client_event_id="minute-181", minute=181, added_minute=0
            )
        assert MINUTE_CHECK in str(error.value)
        assert "minute" in str(error.value)

        with pytest.raises(asyncpg.exceptions.CheckViolationError) as error:
            await insert_event(
                connection, client_event_id="added-31", minute=90, added_minute=31
            )
        assert ADDED_MINUTE_CHECK in str(error.value)
        assert "added_minute" in str(error.value)

        # Nothing beyond the accepted boundaries was written.
        assert await connection.fetchval(
            "SELECT count(*) FROM public.match_events WHERE client_event_id IN "
            "('minute-181', 'added-31')"
        ) == 0


# ---------------------------------------------------------------------------
# Shape: validated constraints with the documented bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_022_adds_validated_minute_and_added_minute_checks(database_admin_url):
    async with throwaway_database(database_admin_url, last=21) as connection:
        await apply_migration(connection, 22)

        constraints = await minute_constraints(connection)
        assert set(constraints) == {MINUTE_CHECK, ADDED_MINUTE_CHECK}

        minute_validated, minute_definition = constraints[MINUTE_CHECK]
        added_validated, added_definition = constraints[ADDED_MINUTE_CHECK]

        # The pre-check already guarantees there are no violating rows, so the
        # constraints are added validated (not NOT VALID).
        assert minute_validated is True
        assert added_validated is True
        assert "minute" in minute_definition
        assert "180" in minute_definition
        assert "added_minute" in added_definition
        assert "30" in added_definition


# ---------------------------------------------------------------------------
# Pre-check: abort with explicit counts and no data trimming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_022_precheck_aborts_naming_both_counts_without_trimming(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=21) as connection:
        await connection.execute(SEED_SQL)
        await insert_event(
            connection, client_event_id="out-minute-1", minute=181, added_minute=0
        )
        await insert_event(
            connection, client_event_id="out-minute-2", minute=200, added_minute=0
        )
        await insert_event(
            connection, client_event_id="out-added", minute=90, added_minute=31
        )

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 22)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 022" in message
        assert "minute fuera de 0..180=2" in message
        assert "added_minute fuera de 0..30=1" in message

        # The rows are preserved byte for byte: no trimming and no rewriting.
        rows = await connection.fetch(
            """
            SELECT client_event_id, minute, added_minute
            FROM public.match_events
            ORDER BY client_event_id
            """
        )
        assert [
            (row["client_event_id"], row["minute"], row["added_minute"])
            for row in rows
        ] == [
            ("out-added", 90, 31),
            ("out-minute-1", 181, 0),
            ("out-minute-2", 200, 0),
        ]

        # The constraints were not created: the pre-check aborts before the
        # ALTER TABLE runs.
        assert await minute_constraints(connection) == {}

        # The same 181 value is rejected by the structural CHECK once the data
        # is corrected and the migration runs again.
        await connection.execute(
            """
            UPDATE public.match_events
            SET minute = 90, added_minute = 0
            WHERE client_event_id IN ('out-minute-1', 'out-minute-2')
            """
        )
        await connection.execute(
            "UPDATE public.match_events SET added_minute = 0 WHERE client_event_id = 'out-added'"
        )
        await apply_migration(connection, 22)

        assert set(await minute_constraints(connection)) == {
            MINUTE_CHECK,
            ADDED_MINUTE_CHECK,
        }
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                connection, client_event_id="still-181", minute=181, added_minute=0
            )


# ---------------------------------------------------------------------------
# Clean chain versus migrated chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_022_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=21) as connection:
        await apply_migration(connection, 22)
        migrated = await table_snapshot(connection)

    async with throwaway_database(database_admin_url, last=22) as clean:
        clean_snapshot = await table_snapshot(clean)
        assert clean_snapshot == migrated

        # The clean chain really applied 022: boundaries hold there too.
        await clean.execute(SEED_SQL)
        await insert_event(
            clean, client_event_id="clean-180", minute=180, added_minute=30
        )
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                clean, client_event_id="clean-181", minute=181, added_minute=0
            )
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                clean, client_event_id="clean-31", minute=90, added_minute=31
            )

        constraints = await minute_constraints(clean)
        assert set(constraints) == {MINUTE_CHECK, ADDED_MINUTE_CHECK}
        assert all(validated for validated, _definition in constraints.values())
