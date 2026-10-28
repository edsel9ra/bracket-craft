"""Migración 030: vistas públicas de eventos, segmentos y plantillas (spec 022).

Opt-in: ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL`` para crear bases
desechables (``migration_helpers.throwaway_database``).

Comprueba la cadena limpia (init + 001…030) y el salto 029 → 030, la forma
cerrada y los privilegios de las tres vistas —``security_barrier``,
``GRANT SELECT`` solo a ``bracket_app`` y ``REVOKE`` de ``PUBLIC``— y el filtro
de visibilidad: un torneo publicado aparece y uno en borrador o de una
organización inactiva no. ``v_public_tournament_rosters`` es una proyección
interna de las rutas de estadísticas: solo la lee la ruta pública, nunca otra
superficie de la API (spec 022, RF-035).
"""

from __future__ import annotations

import re
from pathlib import Path

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "30000000-0000-4000-8000-000000000001"
USER = "30000000-0000-4000-8000-000000000002"
MEMBER = "30000000-0000-4000-8000-000000000003"

PLAYER_HOME = "30000000-0000-4000-8000-000000000020"
PLAYER_AWAY = "30000000-0000-4000-8000-000000000021"

TEAM_HOME = "30000000-0000-4000-8000-000000000030"
TEAM_AWAY = "30000000-0000-4000-8000-000000000031"

TOURNAMENT = "30000000-0000-4000-8000-000000000040"
VERSION = "30000000-0000-4000-8000-000000000041"
STAGE = "30000000-0000-4000-8000-000000000042"
MATCH = "30000000-0000-4000-8000-000000000043"
SEGMENT = "30000000-0000-4000-8000-000000000044"
EVENT = "30000000-0000-4000-8000-000000000045"
ROSTER_HOME = "30000000-0000-4000-8000-000000000046"
ROSTER_AWAY = "30000000-0000-4000-8000-000000000047"

DRAFT_TOURNAMENT = "30000000-0000-4000-8000-000000000050"
DRAFT_VERSION = "30000000-0000-4000-8000-000000000051"
DRAFT_STAGE = "30000000-0000-4000-8000-000000000052"
DRAFT_MATCH = "30000000-0000-4000-8000-000000000053"
DRAFT_SEGMENT = "30000000-0000-4000-8000-000000000054"
DRAFT_EVENT = "30000000-0000-4000-8000-000000000055"
DRAFT_ROSTER = "30000000-0000-4000-8000-000000000056"

HOME_PHOTO_KEY = "photos/migration-030-home.jpg"
AWAY_PHOTO_KEY = "photos/migration-030-away.jpg"

EVENTS_VIEW = "v_public_match_events"
SEGMENTS_VIEW = "v_public_match_segments"
ROSTERS_VIEW = "v_public_tournament_rosters"
VIEWS = (EVENTS_VIEW, SEGMENTS_VIEW, ROSTERS_VIEW)

#: Forma cerrada de las tres proyecciones: sin `organization_id`, sin
#: documentos, sin fechas de nacimiento y sin claves de almacenamiento
#: (`photo_url` hereda solo la clave cuando hay consentimiento).
EXPECTED_COLUMNS = {
    EVENTS_VIEW: [
        "id",
        "match_id",
        "tournament_id",
        "team_id",
        "player_id",
        "event_type",
        "minute",
        "added_minute",
        "player_out_id",
        "player_in_id",
        "beneficiary_team_id",
        "metadata",
        "is_voided",
    ],
    SEGMENTS_VIEW: [
        "id",
        "match_id",
        "tournament_id",
        "segment_number",
        "minute_start",
        "minute_end",
        "status",
    ],
    ROSTERS_VIEW: [
        "tournament_id",
        "team_id",
        "player_id",
        "first_name",
        "last_name",
        "dorsal_number",
        "is_active",
        "photo_consent",
        "photo_url",
        "team_name",
    ],
}

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 030 Org', 'migration-030-org');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-030@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country,
    birth_date_encrypted, age_at_reference, age_reference_year
) VALUES
    ('{PLAYER_HOME}', '{ORG}', 'Home', 'Striker', 'DNI',
     decode('01', 'hex'), repeat('a', 64), 'ARG', decode('10', 'hex'), 25, 2026),
    ('{PLAYER_AWAY}', '{ORG}', 'Away', 'Defender', 'DNI',
     decode('02', 'hex'), repeat('b', 64), 'ARG', decode('11', 'hex'), 24, 2026);

INSERT INTO public.teams (id, organization_id, name, short_code) VALUES
    ('{TEAM_HOME}', '{ORG}', 'Home Team', 'H30'),
    ('{TEAM_AWAY}', '{ORG}', 'Away Team', 'A30');

-- Torneo visible: se publica al final del seed.
INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 030 Cup', '2026', DATE '2026-01-01',
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
    '{SEGMENT}', '{ORG}', '{MATCH}', 1, 0, 45, 'completed'
);

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    photo_consent, photo_object_key, valid_from, eligible_from
) VALUES
    ('{ROSTER_HOME}', '{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', '{PLAYER_HOME}', 9,
     TRUE, '{HOME_PHOTO_KEY}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('{ROSTER_AWAY}', '{ORG}', '{TOURNAMENT}', '{TEAM_AWAY}', '{PLAYER_AWAY}', 4,
     FALSE, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    '{ROSTER_HOME}', '{ORG}', '{MATCH}', '{ROSTER_HOME}', '{PLAYER_HOME}',
    '{TEAM_HOME}', '{TOURNAMENT}', NULL, 'starter', TRUE
);

INSERT INTO public.match_events (
    id, organization_id, match_id, segment_id, team_id, player_id,
    event_type, minute, client_event_id
) VALUES (
    '{EVENT}', '{ORG}', '{MATCH}', '{SEGMENT}', '{TEAM_HOME}', '{PLAYER_HOME}',
    'goal', 10, 'migration-030-visible-goal'
);

-- Torneo oculto: se queda en borrador con su propia estructura y sus propios
-- eventos, segmentos y plantillas.
INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{DRAFT_TOURNAMENT}', '{ORG}', 'Migration 030 Draft', '2026', DATE '2026-01-01',
    'draft', '{{}}'::jsonb
);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    '{DRAFT_VERSION}', '{ORG}', '{DRAFT_TOURNAMENT}', 1, '{{}}'::jsonb,
    '{{}}'::jsonb, 'draft', '{MEMBER}'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES (
    '{DRAFT_STAGE}', '{ORG}', '{DRAFT_TOURNAMENT}', '{DRAFT_VERSION}', 'Group',
    'round_robin', 1
);

INSERT INTO public.tournament_teams (organization_id, tournament_id, team_id, status)
VALUES
    ('{ORG}', '{DRAFT_TOURNAMENT}', '{TEAM_HOME}', 'registered'),
    ('{ORG}', '{DRAFT_TOURNAMENT}', '{TEAM_AWAY}', 'registered');

INSERT INTO public.stage_teams (
    organization_id, tournament_id, tournament_version_id, stage_id, team_id
) VALUES
    ('{ORG}', '{DRAFT_TOURNAMENT}', '{DRAFT_VERSION}', '{DRAFT_STAGE}', '{TEAM_HOME}'),
    ('{ORG}', '{DRAFT_TOURNAMENT}', '{DRAFT_VERSION}', '{DRAFT_STAGE}', '{TEAM_AWAY}');

INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    home_team_id, away_team_id, status, matchday
) VALUES (
    '{DRAFT_MATCH}', '{ORG}', '{DRAFT_TOURNAMENT}', '{DRAFT_VERSION}', '{DRAFT_STAGE}',
    '{TEAM_HOME}', '{TEAM_AWAY}', 'scheduled', 1
);

INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end, status
) VALUES (
    '{DRAFT_SEGMENT}', '{ORG}', '{DRAFT_MATCH}', 1, 0, 45, 'completed'
);

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    photo_consent, valid_from, eligible_from
) VALUES (
    '{DRAFT_ROSTER}', '{ORG}', '{DRAFT_TOURNAMENT}', '{TEAM_HOME}', '{PLAYER_HOME}',
    9, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    '{DRAFT_ROSTER}', '{ORG}', '{DRAFT_MATCH}', '{DRAFT_ROSTER}', '{PLAYER_HOME}',
    '{TEAM_HOME}', '{DRAFT_TOURNAMENT}', NULL, 'starter', TRUE
);

INSERT INTO public.match_events (
    id, organization_id, match_id, segment_id, team_id, player_id,
    event_type, minute, client_event_id
) VALUES (
    '{DRAFT_EVENT}', '{ORG}', '{DRAFT_MATCH}', '{DRAFT_SEGMENT}', '{TEAM_HOME}',
    '{PLAYER_HOME}', 'goal', 10, 'migration-030-draft-goal'
);

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
    for view in VIEWS:
        contract = await view_contract(connection, view)

        assert "security_barrier=true" in contract["options"], (
            f"public.{view} debe declararse security_barrier"
        )
        assert contract["rolsuper"] or contract["rolbypassrls"], (
            f"el propietario de {view} debe estar exento de RLS"
        )
        assert contract["app_select"] is True, (
            f"bracket_app debe poder leer public.{view}"
        )
        assert contract["public_select"] is False, (
            f"PUBLIC no debe leer public.{view}"
        )

        grantees = await select_grantees(connection, view)
        unexpected = [
            grantee
            for grantee in grantees
            if grantee not in (contract["owner_name"], "bracket_app")
        ]
        assert "bracket_app" in grantees, (
            f"bracket_app debe tener SELECT sobre public.{view}"
        )
        assert unexpected == [], (
            f"SELECT sobre public.{view} solo puede quedar en el propietario y en "
            f"bracket_app; también lo tienen: {unexpected}"
        )


async def assert_shapes(connection: asyncpg.Connection) -> None:
    for view, expected in EXPECTED_COLUMNS.items():
        assert await view_exists(connection, view) is True, (
            f"falta la vista public.{view}"
        )
        columns = await view_columns(connection, view)
        assert columns == expected, (
            f"columnas inesperadas en public.{view}: {columns}"
        )
    await assert_contract(connection)


@pytest.mark.asyncio
async def test_030_views_absent_before_migration(database_admin_url):
    async with throwaway_database(database_admin_url, last=29) as connection:
        for view in VIEWS:
            assert await view_exists(connection, view) is False, (
                f"public.{view} no puede existir antes de la 030"
            )


@pytest.mark.asyncio
async def test_030_clean_chain_creates_three_closed_views(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        await assert_shapes(connection)


@pytest.mark.asyncio
async def test_030_jump_from_029_creates_three_closed_views(database_admin_url):
    async with throwaway_database(database_admin_url, last=29) as connection:
        for view in VIEWS:
            assert await view_exists(connection, view) is False

        await apply_migration(connection, 30)

        await assert_shapes(connection)


@pytest.mark.asyncio
async def test_030_visibilidad_solo_del_torneo_publicado(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        await connection.execute(SEED_SQL)

        events = await connection.fetch(
            f"SELECT id, tournament_id FROM public.{EVENTS_VIEW} ORDER BY id"
        )
        assert [str(row["id"]) for row in events] == [EVENT], (
            "la vista de eventos debe devolver solo los del torneo publicado"
        )
        assert str(events[0]["tournament_id"]) == TOURNAMENT

        segments = await connection.fetch(
            f"SELECT id FROM public.{SEGMENTS_VIEW} ORDER BY id"
        )
        assert [str(row["id"]) for row in segments] == [SEGMENT], (
            "la vista de segmentos debe devolver solo los del torneo publicado"
        )

        rosters = await connection.fetch(
            f"""
            SELECT player_id, team_id, tournament_id
            FROM public.{ROSTERS_VIEW}
            ORDER BY player_id
            """
        )
        assert {str(row["tournament_id"]) for row in rosters} == {TOURNAMENT}, (
            "la vista de plantillas solo puede publicar el torneo publicado"
        )
        assert {str(row["player_id"]) for row in rosters} == {
            PLAYER_HOME,
            PLAYER_AWAY,
        }, "debe devolver las dos plantillas del torneo publicado"


@pytest.mark.asyncio
async def test_030_foto_solo_con_consentimiento(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        await connection.execute(SEED_SQL)

        rows = await connection.fetch(
            f"""
            SELECT player_id, photo_consent, photo_url
            FROM public.{ROSTERS_VIEW}
            WHERE tournament_id = $1::uuid
            """,
            TOURNAMENT,
        )
        by_player = {str(row["player_id"]): row for row in rows}

        assert by_player[PLAYER_HOME]["photo_consent"] is True
        assert by_player[PLAYER_HOME]["photo_url"] == HOME_PHOTO_KEY, (
            "con consentimiento, photo_url resuelve la clave del objeto"
        )
        assert by_player[PLAYER_AWAY]["photo_consent"] is False
        assert by_player[PLAYER_AWAY]["photo_url"] is None, (
            "sin consentimiento, la vista no puede exponer la clave del objeto"
        )


@pytest.mark.asyncio
async def test_030_organizacion_inactiva_oculta_las_tres_vistas(database_admin_url):
    async with throwaway_database(database_admin_url, last=30) as connection:
        await connection.execute(SEED_SQL)
        assert await connection.fetchval(
            f"SELECT count(*) FROM public.{EVENTS_VIEW}"
        ) == 1

        await connection.execute(
            "UPDATE public.organizations SET is_active = FALSE WHERE id = $1::uuid",
            ORG,
        )

        for view in VIEWS:
            count = await connection.fetchval(f"SELECT count(*) FROM public.{view}")
            assert count == 0, (
                f"una organización inactiva no debe publicar filas en {view}"
            )


@pytest.mark.asyncio
async def test_030_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=29) as connection:
        await apply_migration(connection, 30)
        migrated = {
            view: await view_columns(connection, view) for view in VIEWS
        }

    async with throwaway_database(database_admin_url, last=30) as connection:
        clean = {view: await view_columns(connection, view) for view in VIEWS}

    assert migrated == clean
    for view, expected in EXPECTED_COLUMNS.items():
        assert clean[view] == expected


def test_030_plantillas_es_interna_y_solo_la_lee_la_ruta_publica():
    """La plantilla es una proyección **interna** de las rutas de estadísticas.

    La spec 022 y ``AGENTS.md`` documentan que ``v_public_tournament_rosters`` la
    leen las dos rutas de estadísticas para calcular las cifras, así que la
    comprobación estática posible es que **ninguna otra superficie** de la API la
    consulta: su única referencia en ``backend/app`` está en el router de torneos
    y dentro de una ruta pública, nunca en el Workspace ni en la administración.
    """

    app_modules = Path(__file__).resolve().parents[1] / "app"
    references = [
        path
        for path in sorted(app_modules.rglob("*.py"))
        if ROSTERS_VIEW in path.read_text(encoding="utf-8")
    ]

    assert references, (
        f"debe existir la lectura de {ROSTERS_VIEW} en las rutas de estadísticas"
    )

    router = app_modules / "modules" / "tournaments" / "router.py"
    assert references == [router], (
        f"{ROSTERS_VIEW} es interna de las rutas públicas: solo puede referenciarse "
        f"en {router.relative_to(app_modules)}; también aparece en "
        f"{[str(path.relative_to(app_modules)) for path in references if path != router]}"
    )

    lines = router.read_text(encoding="utf-8").splitlines()
    route_pattern = re.compile(
        r"@router\.(?:get|post|put|patch|delete)\(\s*\"([^\"]+)\""
    )
    for index, line in enumerate(lines):
        if ROSTERS_VIEW not in line:
            continue
        route = None
        for previous in reversed(lines[:index]):
            match = route_pattern.search(previous)
            if match:
                route = match.group(1)
                break
        assert route is not None, (
            f"la referencia a {ROSTERS_VIEW} debe vivir dentro de una ruta"
        )
        assert route.startswith("/public/"), (
            f"{ROSTERS_VIEW} solo puede leerse desde una ruta pública; "
            f"la referencia está bajo {route}"
        )
