"""Migración 031: proyección interna con todas las formaciones publicadas.

Spec 022, RF-015 y RF-026 (casos límite 14 y 16b). Prueba opt-in: necesita
``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL`` para crear bases desechables.
Comprueba la forma y los privilegios de ``public.v_public_match_formations``,
que devuelve **todas** las formaciones publicadas de un partido y no solo la
última como ``v_public_match_lineups``, y que una formación sin publicar no
aparece. Cubre la cadena limpia y el salto 030 → 031.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "31000000-0000-4000-8000-000000000001"
USER = "31000000-0000-4000-8000-000000000002"
MEMBER = "31000000-0000-4000-8000-000000000003"

TOURNAMENT = "31000000-0000-4000-8000-000000000010"
VERSION = "31000000-0000-4000-8000-000000000011"
STAGE = "31000000-0000-4000-8000-000000000012"
TEAM_HOME = "31000000-0000-4000-8000-000000000013"
TEAM_AWAY = "31000000-0000-4000-8000-000000000014"

PLAYER_HOME_FIRST = "31000000-0000-4000-8000-000000000020"
PLAYER_HOME_SECOND = "31000000-0000-4000-8000-000000000021"
PLAYER_AWAY = "31000000-0000-4000-8000-000000000022"

MATCH = "31000000-0000-4000-8000-000000000050"
SEGMENT_FIRST = "31000000-0000-4000-8000-000000000051"
SEGMENT_SECOND = "31000000-0000-4000-8000-000000000052"
FIRST_SEGMENT_NUMBER = 1
SECOND_SEGMENT_NUMBER = 2

VIEW = "v_public_match_formations"

#: Forma cerrada de la proyección: sin nombres, documentos, fotos ni
#: `organization_id`. `is_public` se conserva siempre verdadero para que la
#: regla pura pueda comprobarlo por su cuenta (plan D8).
EXPECTED_COLUMNS = [
    "match_id",
    "tournament_id",
    "segment_id",
    "segment_number",
    "team_id",
    "player_id",
    "position_slot",
    "is_starter",
    "is_public",
    "formation_code",
]

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 031 Org', 'migration-031-org');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-031@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country,
    birth_date_encrypted, age_at_reference, age_reference_year
) VALUES
    ('{PLAYER_HOME_FIRST}', '{ORG}', 'First', 'Keeper', 'DNI',
     decode('01', 'hex'), repeat('a', 64), 'ARG', decode('10', 'hex'), 25, 2026),
    ('{PLAYER_HOME_SECOND}', '{ORG}', 'Second', 'Keeper', 'DNI',
     decode('02', 'hex'), repeat('b', 64), 'ARG', decode('11', 'hex'), 24, 2026),
    ('{PLAYER_AWAY}', '{ORG}', 'Away', 'Keeper', 'DNI',
     decode('03', 'hex'), repeat('c', 64), 'ARG', decode('12', 'hex'), 23, 2026);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 031 Cup', '2026', DATE '2026-01-01',
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
    ('{TEAM_HOME}', '{ORG}', 'Home Team', 'H31'),
    ('{TEAM_AWAY}', '{ORG}', 'Away Team', 'A31');

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
) VALUES
    ('{SEGMENT_FIRST}', '{ORG}', '{MATCH}', {FIRST_SEGMENT_NUMBER}, 0, 45, 'completed'),
    ('{SEGMENT_SECOND}', '{ORG}', '{MATCH}', {SECOND_SEGMENT_NUMBER}, 45, 90, 'completed');

INSERT INTO public.match_lineup_snapshots (
    organization_id, match_id, segment_id, team_id, player_id, is_starter, position_slot
) VALUES
    ('{ORG}', '{MATCH}', '{SEGMENT_FIRST}', '{TEAM_HOME}', '{PLAYER_HOME_FIRST}', TRUE, 'GK'),
    ('{ORG}', '{MATCH}', '{SEGMENT_SECOND}', '{TEAM_HOME}', '{PLAYER_HOME_SECOND}', TRUE, 'GK'),
    ('{ORG}', '{MATCH}', '{SEGMENT_FIRST}', '{TEAM_AWAY}', '{PLAYER_AWAY}', TRUE, 'GK');

INSERT INTO public.match_team_lineups (
    organization_id, match_id, segment_id, team_id, formation_code,
    is_public, published_at
) VALUES
    ('{ORG}', '{MATCH}', '{SEGMENT_FIRST}', '{TEAM_HOME}', '4-3-3', TRUE, CURRENT_TIMESTAMP),
    ('{ORG}', '{MATCH}', '{SEGMENT_SECOND}', '{TEAM_HOME}', '4-4-2', TRUE, CURRENT_TIMESTAMP),
    ('{ORG}', '{MATCH}', '{SEGMENT_FIRST}', '{TEAM_AWAY}', '4-4-2', FALSE, NULL);

UPDATE public.tournament_versions
SET status = 'published'
WHERE id = '{VERSION}';

UPDATE public.tournaments
SET status = 'published',
    published_version_id = '{VERSION}'
WHERE id = '{TOURNAMENT}';
"""


async def view_exists(connection: asyncpg.Connection, view_name: str) -> bool:
    return await connection.fetchval(
        "SELECT to_regclass('public.' || $1) IS NOT NULL",
        view_name,
    )


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


async def select_grantees(connection: asyncpg.Connection, view_name: str) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT CASE
                   WHEN acl.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_get_userbyid(acl.grantee)
               END AS grantee
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace,
             aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) acl
        WHERE n.nspname = 'public'
          AND c.relname = $1
          AND acl.privilege_type = 'SELECT'
        ORDER BY grantee
        """,
        view_name,
    )
    return [row["grantee"] for row in rows]


async def assert_contract(connection: asyncpg.Connection) -> None:
    contract = await view_contract(connection, VIEW)

    assert "security_barrier=true" in contract["options"], (
        f"public.{VIEW} debe declararse security_barrier"
    )
    assert contract["rolsuper"] or contract["rolbypassrls"], (
        f"el propietario de {VIEW} debe estar exento de RLS"
    )
    assert contract["app_select"] is True, (
        f"bracket_app debe poder leer public.{VIEW}"
    )
    assert contract["public_select"] is False, (
        f"PUBLIC no debe leer public.{VIEW}"
    )

    grantees = await select_grantees(connection, VIEW)
    unexpected = [
        grantee
        for grantee in grantees
        if grantee not in (contract["owner_name"], "bracket_app")
    ]
    assert "bracket_app" in grantees, (
        f"bracket_app debe tener SELECT sobre public.{VIEW}"
    )
    assert unexpected == [], (
        f"SELECT sobre public.{VIEW} solo puede quedar en el propietario y en "
        f"bracket_app; también lo tienen: {unexpected}"
    )


@pytest.mark.asyncio
async def test_031_view_absent_before_migration(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        assert await view_exists(connection, VIEW) is False, (
            f"public.{VIEW} no puede existir antes de la 031"
        )


@pytest.mark.asyncio
async def test_031_clean_chain_creates_view_with_closed_shape(database_admin_url):
    async with throwaway_database(database_admin_url, last=31) as connection:
        assert await view_exists(connection, VIEW) is True, (
            f"falta la vista public.{VIEW} tras la cadena limpia"
        )
        columns = await view_columns(connection, VIEW)
        assert columns == EXPECTED_COLUMNS, (
            f"columnas inesperadas en public.{VIEW}: {columns}"
        )
        await assert_contract(connection)


@pytest.mark.asyncio
async def test_031_jump_from_030_creates_view(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        assert await view_exists(connection, VIEW) is False

        await apply_migration(connection, 31)

        assert await view_exists(connection, VIEW) is True, (
            "la 031 debe crear la vista al aplicarse sobre el esquema 030"
        )
        assert await view_columns(connection, VIEW) == EXPECTED_COLUMNS
        await assert_contract(connection)


@pytest.mark.asyncio
async def test_031_two_published_segments_return_two_formations(database_admin_url):
    async with throwaway_database(database_admin_url, last=31) as connection:
        await connection.execute(SEED_SQL)

        rows = await connection.fetch(
            """
            SELECT match_id, tournament_id, segment_id, segment_number, team_id,
                   player_id, position_slot, is_starter, is_public, formation_code
            FROM public.v_public_match_formations
            WHERE match_id = $1::uuid
              AND team_id = $2::uuid
            ORDER BY segment_number
            """,
            MATCH,
            TEAM_HOME,
        )

        assert len(rows) == 2, (
            "las dos formaciones publicadas del mismo equipo y partido deben "
            f"devolver dos filas; la vista devolvió {len(rows)}"
        )
        assert [row["segment_number"] for row in rows] == [
            FIRST_SEGMENT_NUMBER,
            SECOND_SEGMENT_NUMBER,
        ], "cada formación debe llevar su propio segment_number"
        assert {str(row["player_id"]) for row in rows} == {
            PLAYER_HOME_FIRST,
            PLAYER_HOME_SECOND,
        }, "cada formación debe devolver su propio jugador"
        assert all(row["position_slot"] == "GK" for row in rows)
        assert all(row["is_starter"] is True for row in rows)
        assert all(row["is_public"] is True for row in rows)
        assert all(str(row["tournament_id"]) == TOURNAMENT for row in rows)
        assert all(str(row["match_id"]) == MATCH for row in rows)

        # La proyección pública de la spec 021 sigue devolviendo solo la última
        # formación del equipo: es el defecto que la 031 resuelve para el cálculo.
        public_rows = await connection.fetchval(
            """
            SELECT count(DISTINCT (segment_id, team_id))
            FROM public.v_public_match_lineups
            WHERE match_id = $1::uuid
              AND team_id = $2::uuid
              AND formation_code IS NOT NULL
            """,
            MATCH,
            TEAM_HOME,
        )
        assert public_rows == 1, (
            "v_public_match_lineups debe seguir publicando una sola formación "
            f"por equipo; devolvió {public_rows}"
        )

        # Organización inactiva: la proyección no publica nada.
        await connection.execute(
            "UPDATE public.organizations SET is_active = FALSE WHERE id = $1::uuid",
            ORG,
        )
        assert await connection.fetchval(
            "SELECT count(*) FROM public.v_public_match_formations WHERE match_id = $1::uuid",
            MATCH,
        ) == 0, "una organización inactiva no debe publicar formaciones"


@pytest.mark.asyncio
async def test_031_unpublished_formation_is_excluded(database_admin_url):
    async with throwaway_database(database_admin_url, last=31) as connection:
        await connection.execute(SEED_SQL)

        stored = await connection.fetchval(
            """
            SELECT count(*)
            FROM public.match_team_lineups
            WHERE match_id = $1::uuid
              AND team_id = $2::uuid
              AND is_public = FALSE
            """,
            MATCH,
            TEAM_AWAY,
        )
        assert stored == 1, "la formación sin publicar debe existir en la tabla"

        exposed = await connection.fetchval(
            """
            SELECT count(*)
            FROM public.v_public_match_formations
            WHERE match_id = $1::uuid
              AND team_id = $2::uuid
            """,
            MATCH,
            TEAM_AWAY,
        )
        assert exposed == 0, "una formación con is_public falso no debe aparecer"


@pytest.mark.asyncio
async def test_031_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        await apply_migration(connection, 31)
        migrated_columns = await view_columns(connection, VIEW)

    async with throwaway_database(database_admin_url, last=31) as connection:
        clean_columns = await view_columns(connection, VIEW)

    assert migrated_columns == clean_columns
    assert clean_columns == EXPECTED_COLUMNS
