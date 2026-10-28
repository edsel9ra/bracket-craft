"""Migración 029: ``organization_id`` en la proyección pública de torneos (spec 022, D2).

Opt-in: ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL`` para crear bases
desechables (``migration_helpers.throwaway_database``).

La columna es **interna**: la lee el backend para fijar el contexto RLS cuando
sirve una lectura pública y **no** aparece en ningún modelo de respuesta. La
lista cerrada de campos públicos vive en ``test_public_field_allowlist.py``; aquí
solo se fija que ``organization_id`` no sea un campo de esos modelos, sin repetir
la lista. Se cubre la cadena limpia (init + 001…029) y el salto 028 → 029, la
forma y los privilegios de la vista y que la migración no cambia las filas que
publicaba la 028.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "29000000-0000-4000-8000-000000000001"
USER = "29000000-0000-4000-8000-000000000002"
MEMBER = "29000000-0000-4000-8000-000000000003"

TOURNAMENT = "29000000-0000-4000-8000-000000000010"
VERSION = "29000000-0000-4000-8000-000000000011"
DRAFT_TOURNAMENT = "29000000-0000-4000-8000-000000000012"
DRAFT_VERSION = "29000000-0000-4000-8000-000000000013"

VIEW = "v_public_tournaments"

#: Forma previa a la 029 (migración 002) y forma final, con la columna nueva
#: **al final**: `CREATE OR REPLACE VIEW` solo puede añadir columnas al final.
BASE_COLUMNS = ["id", "name", "season", "start_date", "status"]
EXPECTED_COLUMNS = [*BASE_COLUMNS, "organization_id"]

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 029 Org', 'migration-029-org');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-029@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES
    ('{TOURNAMENT}', '{ORG}', 'Migration 029 Cup', '2026', DATE '2026-01-01',
     'draft', '{{}}'::jsonb),
    ('{DRAFT_TOURNAMENT}', '{ORG}', 'Migration 029 Draft', '2026', DATE '2026-01-01',
     'draft', '{{}}'::jsonb);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES
    ('{VERSION}', '{ORG}', '{TOURNAMENT}', 1, '{{}}'::jsonb, '{{}}'::jsonb,
     'draft', '{MEMBER}'),
    ('{DRAFT_VERSION}', '{ORG}', '{DRAFT_TOURNAMENT}', 1, '{{}}'::jsonb,
     '{{}}'::jsonb, 'draft', '{MEMBER}');

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
        f"public.{VIEW} debe conservar security_barrier"
    )
    assert contract["rolsuper"] or contract["rolbypassrls"], (
        f"el propietario de {VIEW} debe estar exento de RLS"
    )
    assert contract["app_select"] is True, (
        f"bracket_app debe conservar SELECT sobre public.{VIEW}"
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


async def published_ids(connection: asyncpg.Connection) -> list[str]:
    rows = await connection.fetch(
        f"SELECT id FROM public.{VIEW} ORDER BY id"
    )
    return [str(row["id"]) for row in rows]


@pytest.mark.asyncio
async def test_029_organization_id_absent_before_migration(database_admin_url):
    async with throwaway_database(database_admin_url, last=28) as connection:
        columns = await view_columns(connection, VIEW)
        assert columns == BASE_COLUMNS, (
            f"antes de la 029 public.{VIEW} debe tener la forma de la 002; tiene {columns}"
        )


@pytest.mark.asyncio
async def test_029_clean_chain_appends_column_and_keeps_contract(database_admin_url):
    async with throwaway_database(database_admin_url, last=29) as connection:
        columns = await view_columns(connection, VIEW)
        assert columns == EXPECTED_COLUMNS, (
            f"columnas inesperadas en public.{VIEW}: {columns}"
        )
        assert columns[-1] == "organization_id", (
            "organization_id debe ser la última columna: el salto de la 002 a la "
            "029 usa CREATE OR REPLACE y solo puede añadir columnas al final"
        )
        await assert_contract(connection)


@pytest.mark.asyncio
async def test_029_jump_from_028_appends_column_and_keeps_grants(database_admin_url):
    async with throwaway_database(database_admin_url, last=28) as connection:
        assert "organization_id" not in await view_columns(connection, VIEW)

        await apply_migration(connection, 29)

        columns = await view_columns(connection, VIEW)
        assert "organization_id" in columns, (
            "la 029 debe añadir organization_id al aplicarse sobre el esquema 028"
        )
        assert columns == EXPECTED_COLUMNS
        await assert_contract(connection)


@pytest.mark.asyncio
async def test_029_published_rows_unchanged_and_organization_exposed(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=28) as connection:
        await connection.execute(SEED_SQL)
        before = await published_ids(connection)
        assert before == [TOURNAMENT], (
            "la vista previa a la 029 debe publicar solo el torneo publicado"
        )

        await apply_migration(connection, 29)

        after = await published_ids(connection)
        assert after == before, (
            "la 029 no puede cambiar las filas que publica la vista: "
            f"antes {before}, después {after}"
        )
        assert DRAFT_TOURNAMENT not in after, (
            "un torneo en borrador no debe aparecer en la proyección pública"
        )

        organization = await connection.fetchval(
            f"SELECT organization_id FROM public.{VIEW} WHERE id = $1::uuid",
            TOURNAMENT,
        )
        assert str(organization) == ORG, (
            "organization_id debe ser la organización del torneo publicado"
        )


@pytest.mark.asyncio
async def test_029_inactive_organization_hides_published_tournament(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=29) as connection:
        await connection.execute(SEED_SQL)
        assert await published_ids(connection) == [TOURNAMENT]

        await connection.execute(
            "UPDATE public.organizations SET is_active = FALSE WHERE id = $1::uuid",
            ORG,
        )

        assert await published_ids(connection) == [], (
            "una organización inactiva no debe publicar torneos tras la 029"
        )


@pytest.mark.asyncio
async def test_029_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=28) as connection:
        await apply_migration(connection, 29)
        migrated_columns = await view_columns(connection, VIEW)

    async with throwaway_database(database_admin_url, last=29) as connection:
        clean_columns = await view_columns(connection, VIEW)

    assert migrated_columns == clean_columns
    assert clean_columns == EXPECTED_COLUMNS


def test_029_organization_id_no_es_campo_de_los_modelos_publicos():
    """La lista cerrada vive en ``test_public_field_allowlist.py``.

    Esta comprobación es estática (sin base) y solo fija el punto que la 029
    documenta: la columna es interna y ningún modelo de respuesta la declara.
    """

    from app.modules.tournaments import schemas

    public_models = [
        name
        for name in dir(schemas)
        if name.startswith("Public") and name.endswith("Response")
    ]
    assert public_models, "deben existir modelos públicos de respuesta"

    leaked = sorted(
        name
        for name in public_models
        if "organization_id" in getattr(schemas, name).model_fields
    )
    assert leaked == [], (
        "organization_id es una columna interna y no puede declararse en los "
        f"modelos públicos: {leaked}"
    )
