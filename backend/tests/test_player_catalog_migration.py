"""Migration 015 tests against a real PostgreSQL instance (RF-004 / RF-018).

The test builds a throwaway database in state 014, seeds a player that is shared
by two organizations, applies the real migration file with an administrator role
and checks that references were split without losing history. It also applies
the full migration chain to a clean database.

The suite is opt-in. It needs ``RUN_DATABASE_TESTS=1`` and a second URL with an
administrator role (``DATABASE_ADMIN_URL``) because ``bracket_app`` cannot create
databases or apply DDL.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_DIR = REPO_ROOT / "infra" / "postgres" / "init"
MIGRATIONS_DIR = REPO_ROOT / "infra" / "postgres" / "migrations"
MIGRATION_015 = MIGRATIONS_DIR / "015_player_catalog_tenant_isolation.sql"

ORG_A = "a0000000-0000-4000-8000-000000000001"
ORG_B = "b0000000-0000-4000-8000-000000000001"
SHARED_PLAYER = "c0000000-0000-4000-8000-000000000001"
ORPHAN_PLAYER = "c0000000-0000-4000-8000-000000000002"

REFERENCE_TABLES = (
    "rosters",
    "match_rosters",
    "match_lineup_snapshots",
    "match_events",
    "player_suspensions",
)

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG_A}', 'Organization A', 't002-org-a'),
    ('{ORG_B}', 'Organization B', 't002-org-b');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('a0000000-0000-4000-8000-000000000002', 't002-a@example.test', 'hash', 'Owner A'),
    ('b0000000-0000-4000-8000-000000000002', 't002-b@example.test', 'hash', 'Owner B');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active) VALUES
    ('a0000000-0000-4000-8000-000000000003', '{ORG_A}',
     'a0000000-0000-4000-8000-000000000002', TRUE),
    ('b0000000-0000-4000-8000-000000000003', '{ORG_B}',
     'b0000000-0000-4000-8000-000000000002', TRUE);

INSERT INTO public.players (
    id, first_name, last_name, document_type, national_id_encrypted,
    national_id_hmac, issuing_country, birth_date, photo_url, created_at
) VALUES
    ('{SHARED_PLAYER}', 'Shared', 'Player', 'DNI', decode('010203', 'hex'),
     repeat('a', 64), 'ARG', '2000-01-02', 'private/original.jpg',
     '2026-01-01 00:00:00+00'),
    ('{ORPHAN_PLAYER}', 'Orphan', 'Player', 'DNI', decode('040506', 'hex'),
     repeat('b', 64), 'ARG', '2000-01-03', NULL, '2026-01-01 00:00:00+00');

-- Organization A
INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    'a0000000-0000-4000-8000-000000000010', '{ORG_A}', 'Tournament A', '2026',
    '2026-01-01', 'draft', '{{}}'
);
INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    'a0000000-0000-4000-8000-000000000011', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010', 1, '{{}}', '{{}}', 'draft',
    'a0000000-0000-4000-8000-000000000003'
);
INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES (
    'a0000000-0000-4000-8000-000000000012', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010',
    'a0000000-0000-4000-8000-000000000011', 'Group', 'round_robin', 1
);
INSERT INTO public.teams (id, organization_id, name, short_code) VALUES (
    'a0000000-0000-4000-8000-000000000013', '{ORG_A}', 'Team A', 'TA'
);
INSERT INTO public.tournament_teams (
    id, organization_id, tournament_id, team_id, status
) VALUES (
    'a0000000-0000-4000-8000-000000000014', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010',
    'a0000000-0000-4000-8000-000000000013', 'registered'
);
INSERT INTO public.stage_teams (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, team_id
) VALUES (
    'a0000000-0000-4000-8000-000000000015', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010',
    'a0000000-0000-4000-8000-000000000011',
    'a0000000-0000-4000-8000-000000000012', NULL,
    'a0000000-0000-4000-8000-000000000013'
);
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, status, match_date, created_at
) VALUES (
    'a0000000-0000-4000-8000-000000000016', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010',
    'a0000000-0000-4000-8000-000000000011',
    'a0000000-0000-4000-8000-000000000012', NULL,
    'a0000000-0000-4000-8000-000000000013', NULL, 'scheduled',
    '2026-01-05 12:00:00+00', '2026-01-05 00:00:00+00'
);
INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end,
    status, created_at
) VALUES (
    'a0000000-0000-4000-8000-000000000017', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000016', 1, 0, 90, 'active',
    '2026-01-05 00:00:00+00'
);
INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    is_active, photo_consent, registered_at, valid_from, valid_to, eligible_from
) VALUES (
    'a0000000-0000-4000-8000-000000000018', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010',
    'a0000000-0000-4000-8000-000000000013', '{SHARED_PLAYER}', 1, TRUE, FALSE,
    '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
    '2026-01-01 00:00:00+00'
);
INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    'a0000000-0000-4000-8000-000000000019', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000016',
    'a0000000-0000-4000-8000-000000000018', '{SHARED_PLAYER}',
    'a0000000-0000-4000-8000-000000000013',
    'a0000000-0000-4000-8000-000000000010', NULL, 'starter', TRUE
);
INSERT INTO public.match_lineup_snapshots (
    id, organization_id, match_id, segment_id, team_id, player_id, is_starter
) VALUES (
    'a0000000-0000-4000-8000-00000000001a', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000016',
    'a0000000-0000-4000-8000-000000000017',
    'a0000000-0000-4000-8000-000000000013', '{SHARED_PLAYER}', TRUE
);
INSERT INTO public.match_events (
    id, organization_id, match_id, segment_id, team_id, beneficiary_team_id,
    player_id, event_type, minute, added_minute, client_event_id, created_at
) VALUES (
    'a0000000-0000-4000-8000-00000000001b', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000016',
    'a0000000-0000-4000-8000-000000000017',
    'a0000000-0000-4000-8000-000000000013', NULL, '{SHARED_PLAYER}',
    'yellow_card', 10, 0, 'event-a', '2026-01-05 00:00:00+00'
);
INSERT INTO public.player_suspensions (
    id, organization_id, source_tournament_id, player_id, origin_match_id,
    source_event_id, source_type, dedupe_key, scope_type, matches_suspended,
    status, reason, created_at
) VALUES (
    'a0000000-0000-4000-8000-00000000001c', '{ORG_A}',
    'a0000000-0000-4000-8000-000000000010', '{SHARED_PLAYER}',
    'a0000000-0000-4000-8000-000000000016',
    'a0000000-0000-4000-8000-00000000001b', 'match_event', 'dedupe-a',
    'tournament', 1, 'active', 'Test suspension', '2026-01-05 00:00:00+00'
);

-- Organization B: same player, later reference so A keeps the original id.
INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    'b0000000-0000-4000-8000-000000000010', '{ORG_B}', 'Tournament B', '2026',
    '2026-01-01', 'draft', '{{}}'
);
INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    'b0000000-0000-4000-8000-000000000011', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010', 1, '{{}}', '{{}}', 'draft',
    'b0000000-0000-4000-8000-000000000003'
);
INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES (
    'b0000000-0000-4000-8000-000000000012', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010',
    'b0000000-0000-4000-8000-000000000011', 'Group', 'round_robin', 1
);
INSERT INTO public.teams (id, organization_id, name, short_code) VALUES (
    'b0000000-0000-4000-8000-000000000013', '{ORG_B}', 'Team B', 'TB'
);
INSERT INTO public.tournament_teams (
    id, organization_id, tournament_id, team_id, status
) VALUES (
    'b0000000-0000-4000-8000-000000000014', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010',
    'b0000000-0000-4000-8000-000000000013', 'registered'
);
INSERT INTO public.stage_teams (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, team_id
) VALUES (
    'b0000000-0000-4000-8000-000000000015', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010',
    'b0000000-0000-4000-8000-000000000011',
    'b0000000-0000-4000-8000-000000000012', NULL,
    'b0000000-0000-4000-8000-000000000013'
);
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, status, match_date, created_at
) VALUES (
    'b0000000-0000-4000-8000-000000000016', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010',
    'b0000000-0000-4000-8000-000000000011',
    'b0000000-0000-4000-8000-000000000012', NULL,
    'b0000000-0000-4000-8000-000000000013', NULL, 'scheduled',
    '2026-01-06 12:00:00+00', '2026-01-06 00:00:00+00'
);
INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end,
    status, created_at
) VALUES (
    'b0000000-0000-4000-8000-000000000017', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000016', 1, 0, 90, 'active',
    '2026-01-06 00:00:00+00'
);
INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    is_active, photo_consent, registered_at, valid_from, valid_to, eligible_from
) VALUES (
    'b0000000-0000-4000-8000-000000000018', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010',
    'b0000000-0000-4000-8000-000000000013', '{SHARED_PLAYER}', 9, TRUE, TRUE,
    '2026-01-02 00:00:00+00', '2026-01-02 00:00:00+00', NULL,
    '2026-01-02 00:00:00+00'
);
INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    'b0000000-0000-4000-8000-000000000019', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000016',
    'b0000000-0000-4000-8000-000000000018', '{SHARED_PLAYER}',
    'b0000000-0000-4000-8000-000000000013',
    'b0000000-0000-4000-8000-000000000010', NULL, 'starter', TRUE
);
INSERT INTO public.match_lineup_snapshots (
    id, organization_id, match_id, segment_id, team_id, player_id, is_starter
) VALUES (
    'b0000000-0000-4000-8000-00000000001a', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000016',
    'b0000000-0000-4000-8000-000000000017',
    'b0000000-0000-4000-8000-000000000013', '{SHARED_PLAYER}', TRUE
);
INSERT INTO public.match_events (
    id, organization_id, match_id, segment_id, team_id, beneficiary_team_id,
    player_id, event_type, minute, added_minute, client_event_id, created_at
) VALUES (
    'b0000000-0000-4000-8000-00000000001b', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000016',
    'b0000000-0000-4000-8000-000000000017',
    'b0000000-0000-4000-8000-000000000013', NULL, '{SHARED_PLAYER}',
    'yellow_card', 20, 0, 'event-b', '2026-01-06 00:00:00+00'
);
INSERT INTO public.player_suspensions (
    id, organization_id, source_tournament_id, player_id, origin_match_id,
    source_event_id, source_type, dedupe_key, scope_type, matches_suspended,
    status, reason, created_at
) VALUES (
    'b0000000-0000-4000-8000-00000000001c', '{ORG_B}',
    'b0000000-0000-4000-8000-000000000010', '{SHARED_PLAYER}',
    'b0000000-0000-4000-8000-000000000016',
    'b0000000-0000-4000-8000-00000000001b', 'match_event', 'dedupe-b',
    'tournament', 1, 'active', 'Test suspension', '2026-01-06 00:00:00+00'
);
"""


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
    database = f"bc_t002_{uuid4().hex[:12]}"
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


async def _execute_file(connection: asyncpg.Connection, path: Path) -> None:
    await connection.execute(path.read_text(encoding="utf-8"))


async def _apply_init(connection: asyncpg.Connection) -> None:
    for filename in ("01_schema.sql", "02_public_projections.sql", "03_hardening.sql"):
        await _execute_file(connection, INIT_DIR / filename)


async def _apply_migrations(
    connection: asyncpg.Connection, *, first: int, last: int
) -> None:
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        if first <= version <= last:
            await _execute_file(connection, path)


async def _reference_counts(connection: asyncpg.Connection) -> dict[str, int]:
    return {
        table: (
            await connection.fetchval(f"SELECT count(*) FROM public.{table}")
        )
        for table in REFERENCE_TABLES
    }


async def _player_ids_by_organization(
    connection: asyncpg.Connection,
) -> dict[str, str]:
    rows = await connection.fetch(
        "SELECT id, organization_id FROM public.players ORDER BY organization_id"
    )
    return {str(row["organization_id"]): str(row["id"]) for row in rows}


async def _assert_references_are_coherent(
    connection: asyncpg.Connection, player_ids: dict[str, str]
) -> None:
    for table in REFERENCE_TABLES:
        cross_tenant = await connection.fetchval(
            f"""
            SELECT count(*)
            FROM public.{table} referenced
            JOIN public.players player ON player.id = referenced.player_id
            WHERE referenced.organization_id <> player.organization_id
            """
        )
        assert cross_tenant == 0, f"{table} mezcla jugadores de otra organización"

        orphaned = await connection.fetchval(
            f"""
            SELECT count(*)
            FROM public.{table} referenced
            LEFT JOIN public.players player ON player.id = referenced.player_id
            WHERE player.id IS NULL
            """
        )
        assert orphaned == 0, f"{table} conserva referencias huérfanas"

        for organization_id, player_id in player_ids.items():
            mismatched = await connection.fetchval(
                f"""
                SELECT count(*)
                FROM public.{table}
                WHERE organization_id = $1
                  AND player_id <> $2
                """,
                organization_id,
                player_id,
            )
            assert mismatched == 0, f"{table} no apunta al jugador de su organización"

    roster_mismatch = await connection.fetchval(
        """
        SELECT count(*)
        FROM public.match_rosters mr
        JOIN public.rosters r ON r.id = mr.roster_id
        WHERE mr.player_id <> r.player_id
           OR mr.organization_id <> r.organization_id
        """
    )
    assert roster_mismatch == 0, "match_rosters no coincide con su roster"

    suspension_mismatch = await connection.fetchval(
        """
        SELECT count(*)
        FROM public.player_suspensions ps
        JOIN public.match_events me ON me.id = ps.source_event_id
        WHERE ps.source_type = 'match_event'
          AND (
              ps.player_id <> me.player_id
              OR ps.origin_match_id <> me.match_id
              OR ps.organization_id <> me.organization_id
          )
        """
    )
    assert suspension_mismatch == 0, "La suspensión no coincide con su evento de origen"


@pytest.mark.asyncio
async def test_migration_015_splits_shared_player_and_preserves_history(
    database_admin_url,
):
    database = await _create_database(database_admin_url)
    connection = await _connect(database_admin_url, database)
    try:
        await _apply_init(connection)
        await _apply_migrations(connection, first=1, last=14)
        await connection.execute(SEED_SQL)

        counts_before = await _reference_counts(connection)
        assert counts_before == {
            "rosters": 2,
            "match_rosters": 2,
            "match_lineup_snapshots": 2,
            "match_events": 2,
            "player_suspensions": 2,
        }

        await _execute_file(connection, MIGRATION_015)

        players = await connection.fetch(
            """
            SELECT id, organization_id, first_name, last_name, national_id_hmac,
                   national_id_encrypted, photo_url, birth_date
            FROM public.players
            ORDER BY organization_id
            """
        )
        assert len(players) == 2
        assert {str(row["organization_id"]) for row in players} == {ORG_A, ORG_B}
        player_ids = await _player_ids_by_organization(connection)
        assert player_ids[ORG_A] == SHARED_PLAYER
        assert player_ids[ORG_B] != SHARED_PLAYER

        copies = {str(row["organization_id"]): row for row in players}
        assert copies[ORG_A]["first_name"] == copies[ORG_B]["first_name"] == "Shared"
        assert copies[ORG_A]["last_name"] == copies[ORG_B]["last_name"] == "Player"
        assert copies[ORG_A]["national_id_hmac"] == copies[ORG_B]["national_id_hmac"]
        assert (
            copies[ORG_A]["national_id_encrypted"]
            == copies[ORG_B]["national_id_encrypted"]
            == b"\x01\x02\x03"
        )
        assert copies[ORG_A]["photo_url"] == copies[ORG_B]["photo_url"] == "private/original.jpg"
        assert copies[ORG_A]["birth_date"] == copies[ORG_B]["birth_date"]

        assert await connection.fetchval("SELECT count(*) FROM players WHERE organization_id IS NULL") == 0
        assert await connection.fetchval(
            "SELECT count(*) FROM players WHERE id = $1", ORPHAN_PLAYER
        ) == 0

        counts_after = await _reference_counts(connection)
        assert counts_after == counts_before

        await _assert_references_are_coherent(connection, player_ids)

        # Re-running the migration is idempotent: no new players, same references.
        await _execute_file(connection, MIGRATION_015)
        assert await _player_ids_by_organization(connection) == player_ids
        assert await _reference_counts(connection) == counts_before
        assert await connection.fetchval(
            "SELECT count(*) FROM players WHERE organization_id IS NULL"
        ) == 0
    finally:
        await connection.close()
        await _drop_database(database_admin_url, database)


@pytest.mark.asyncio
async def test_clean_database_applies_init_and_migrations_through_015(
    database_admin_url,
):
    database = await _create_database(database_admin_url)
    connection = await _connect(database_admin_url, database)
    try:
        await _apply_init(connection)
        await _apply_migrations(connection, first=1, last=15)

        assert await connection.fetchval(
            """
            SELECT is_nullable = 'NO'
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'players'
              AND column_name = 'organization_id'
            """
        ) is True
        assert await connection.fetchval(
            """
            SELECT relrowsecurity AND relforcerowsecurity
            FROM pg_class
            WHERE oid = 'public.players'::regclass
            """
        ) is True
        assert await connection.fetchval("SELECT count(*) FROM public.players") == 0
        assert await connection.fetchval(
            "SELECT to_regclass('public.v_public_tournament_players') IS NOT NULL"
        ) is True
        assert await connection.fetchval(
            "SELECT to_regclass('public.v_public_match_lineups_unpublished') IS NOT NULL"
        ) is True
        assert await connection.fetchval(
            """
            SELECT has_table_privilege(
                'bracket_app', 'public.v_public_tournament_players', 'SELECT'
            )
            """
        ) is True
        assert await connection.fetchval(
            """
            SELECT has_table_privilege(
                'bracket_app', 'public.v_public_match_lineups', 'SELECT'
            )
            """
        ) is True
        assert await connection.fetchval(
            """
            SELECT NOT has_table_privilege(
                'bracket_app', 'public.v_public_match_lineups_unpublished', 'SELECT'
            )
            """
        ) is True
    finally:
        await connection.close()
        await _drop_database(database_admin_url, database)
