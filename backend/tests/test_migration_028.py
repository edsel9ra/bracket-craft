from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "28000000-0000-4000-8000-000000000001"
USER = "28000000-0000-4000-8000-000000000002"
MEMBER = "28000000-0000-4000-8000-000000000003"

TOURNAMENT = "28000000-0000-4000-8000-000000000010"
VERSION = "28000000-0000-4000-8000-000000000011"
STAGE = "28000000-0000-4000-8000-000000000012"
TEAM_HOME = "28000000-0000-4000-8000-000000000013"
TEAM_AWAY = "28000000-0000-4000-8000-000000000014"
PLAYER_HOME = "28000000-0000-4000-8000-000000000020"
PLAYER_AWAY = "28000000-0000-4000-8000-000000000021"
ROSTER_AWAY = "28000000-0000-4000-8000-000000000030"
MATCH = "28000000-0000-4000-8000-000000000050"
SEGMENT = "28000000-0000-4000-8000-000000000051"
SEGMENT_NUMBER = 7

PUBLISHED_VIEW = "v_public_match_lineups"
RAW_VIEW = "v_public_match_lineups_unpublished"

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 028 Org', 'migration-028-org');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-028@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country,
    birth_date_encrypted, age_at_reference, age_reference_year
) VALUES
    ('{PLAYER_HOME}', '{ORG}', 'Home', 'Player', 'DNI',
     decode('01', 'hex'), repeat('a', 64), 'ARG', decode('10', 'hex'), 25, 2026),
    ('{PLAYER_AWAY}', '{ORG}', 'Away', 'Player', 'DNI',
     decode('02', 'hex'), repeat('b', 64), 'ARG', decode('11', 'hex'), 24, 2026);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 028 Cup', '2026', DATE '2026-01-01',
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
) VALUES (
    '{STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Group', 'round_robin', 1
);

INSERT INTO public.teams (id, organization_id, name, short_code) VALUES
    ('{TEAM_HOME}', '{ORG}', 'Home Team', 'H28'),
    ('{TEAM_AWAY}', '{ORG}', 'Away Team', 'A28');

INSERT INTO public.tournament_teams (organization_id, tournament_id, team_id, status)
VALUES
    ('{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', 'registered'),
    ('{ORG}', '{TOURNAMENT}', '{TEAM_AWAY}', 'registered');

INSERT INTO public.stage_teams (
    organization_id, tournament_id, tournament_version_id, stage_id, team_id
) VALUES
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', '{TEAM_HOME}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', '{TEAM_AWAY}');

INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    home_team_id, away_team_id, status, matchday
) VALUES (
    '{MATCH}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}',
    '{TEAM_HOME}', '{TEAM_AWAY}', 'scheduled', 1
);

INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end, status
) VALUES (
    '{SEGMENT}', '{ORG}', '{MATCH}', {SEGMENT_NUMBER}, 0, 45, 'active'
);

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    photo_consent, valid_from, eligible_from
) VALUES (
    '{ROSTER_AWAY}', '{ORG}', '{TOURNAMENT}', '{TEAM_AWAY}', '{PLAYER_AWAY}', 5,
    FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    '{ROSTER_AWAY}', '{ORG}', '{MATCH}', '{ROSTER_AWAY}', '{PLAYER_AWAY}',
    '{TEAM_AWAY}', '{TOURNAMENT}', NULL, 'starter', TRUE
);

INSERT INTO public.match_lineup_snapshots (
    organization_id, match_id, segment_id, team_id, player_id, is_starter, position_slot
) VALUES (
    '{ORG}', '{MATCH}', '{SEGMENT}', '{TEAM_HOME}', '{PLAYER_HOME}', TRUE, 'P1'
);

INSERT INTO public.match_team_lineups (
    organization_id, match_id, segment_id, team_id, formation_code,
    is_public, published_at
) VALUES (
    '{ORG}', '{MATCH}', '{SEGMENT}', '{TEAM_HOME}', '4-3-3', TRUE, CURRENT_TIMESTAMP
);

UPDATE public.tournament_versions
SET status = 'published'
WHERE id = '{VERSION}';

UPDATE public.tournaments
SET status = 'published',
    published_version_id = '{VERSION}'
WHERE id = '{TOURNAMENT}';
"""


async def view_columns(connection: asyncpg.Connection, view_name: str) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT a.attname
        FROM pg_attribute a
        WHERE a.attrelid = ('public.' || $1)::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        view_name,
    )
    return [row["attname"] for row in rows]


async def view_contract(connection: asyncpg.Connection, view_name: str) -> dict:
    row = await connection.fetchrow(
        """
        SELECT pg_get_userbyid(c.relowner) AS owner_name,
               r.rolsuper,
               r.rolbypassrls,
               COALESCE(array_to_string(c.reloptions, ','), '') AS options,
               has_table_privilege('bracket_app', c.oid, 'SELECT') AS app_select,
               EXISTS (
                   SELECT 1
                   FROM aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) acl
                   WHERE acl.grantee = 0
                     AND acl.privilege_type = 'SELECT'
               ) AS public_select
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_roles r ON r.oid = c.relowner
        WHERE n.nspname = 'public'
          AND c.relname = $1
        """,
        view_name,
    )
    assert row is not None, f"falta la vista public.{view_name}"
    return dict(row)


async def grants_unchanged(connection: asyncpg.Connection) -> None:
    assert await connection.fetchval(
        "SELECT has_table_privilege('bracket_app', 'public.v_public_match_lineups', 'SELECT')"
    ) is True
    contract = await view_contract(connection, PUBLISHED_VIEW)
    assert contract["public_select"] is False, "PUBLIC no debe leer la vista publicada"
    assert await connection.fetchval(
        "SELECT NOT has_table_privilege('bracket_app', 'public.v_public_match_lineups_unpublished', 'SELECT')"
    ) is True


PUBLISHED_VIEW = "v_public_match_lineups"
RAW_VIEW = "v_public_match_lineups_unpublished"


@pytest.mark.asyncio
async def test_028_segment_number_absent_before_migration(database_admin_url):
    async with throwaway_database(database_admin_url, last=27) as connection:
        assert "segment_number" not in await view_columns(connection, PUBLISHED_VIEW)
        assert "segment_number" not in await view_columns(connection, RAW_VIEW)


@pytest.mark.asyncio
async def test_028_clean_chain_adds_column_and_keeps_grants(database_admin_url):
    async with throwaway_database(database_admin_url, last=28) as connection:
        for view in (PUBLISHED_VIEW, RAW_VIEW):
            assert "segment_number" in await view_columns(connection, view), (
                f"falta segment_number en {view}"
            )

        for view in (PUBLISHED_VIEW, RAW_VIEW):
            contract = await view_contract(connection, view)
            assert "security_barrier=true" in contract["options"]
            assert contract["rolsuper"] or contract["rolbypassrls"], (
                f"el propietario de {view} debe estar exento de RLS"
            )

        await grants_unchanged(connection)


@pytest.mark.asyncio
async def test_028_jump_from_027_adds_column_and_keeps_grants(database_admin_url):
    async with throwaway_database(database_admin_url, last=27) as connection:
        assert "segment_number" not in await view_columns(connection, PUBLISHED_VIEW)

        await apply_migration(connection, 28)

        for view in (PUBLISHED_VIEW, RAW_VIEW):
            assert "segment_number" in await view_columns(connection, view), (
                f"falta segment_number en {view} tras la 028"
            )

        await grants_unchanged(connection)


@pytest.mark.asyncio
async def test_028_segment_number_null_in_planilla_and_value_in_formation(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=28) as connection:
        await connection.execute(SEED_SQL)

        rows = await connection.fetch(
            """
            SELECT team_id, formation_code, segment_number
            FROM public.v_public_match_lineups
            WHERE match_id = $1::uuid
            """,
            MATCH,
        )
        assert rows, "la vista pública debe devolver filas para el partido"

        tactical = [r for r in rows if r["formation_code"] is not None]
        classic = [r for r in rows if r["formation_code"] is None]

        assert tactical, "debe haber una formación táctica publicada"
        assert classic, "debe haber una planilla clásica"

        assert all(r["segment_number"] == SEGMENT_NUMBER for r in tactical), (
            "la formación debe llevar el número de segmento"
        )
        assert all(r["segment_number"] is None for r in classic), (
            "la planilla clásica debe tener segment_number nulo"
        )


@pytest.mark.asyncio
async def test_028_jump_chain_data_level(database_admin_url):
    async with throwaway_database(database_admin_url, last=27) as connection:
        await apply_migration(connection, 28)
        await connection.execute(SEED_SQL)

        rows = await connection.fetch(
            """
            SELECT team_id, formation_code, segment_number
            FROM public.v_public_match_lineups
            WHERE match_id = $1::uuid
            """,
            MATCH,
        )
        tactical = [r for r in rows if r["formation_code"] is not None]
        classic = [r for r in rows if r["formation_code"] is None]

        assert tactical and all(r["segment_number"] == SEGMENT_NUMBER for r in tactical)
        assert classic and all(r["segment_number"] is None for r in classic)


@pytest.mark.asyncio
async def test_028_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=27) as connection:
        await apply_migration(connection, 28)
        migrated_columns = await view_columns(connection, PUBLISHED_VIEW)

    async with throwaway_database(database_admin_url, last=28) as connection:
        clean_columns = await view_columns(connection, PUBLISHED_VIEW)

    assert migrated_columns == clean_columns
    assert "segment_number" in clean_columns
