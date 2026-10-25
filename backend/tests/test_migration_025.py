"""Migration 025: team crests column and public team projection (RF-38, RF-47/49).

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the additive change is validated both on an
already migrated volume (up to 024 -> 025) and on the clean-volume chain
(init + 001..025). The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` because creating databases and applying DDL require a
role the application role does not have.

Assertions cover the shape of ``teams.crest_object_key`` (nullable ``TEXT``
with no default), the table grants that the new column inherits (no
column-level grant is added), the tenant RLS policy (another organization never
sees the row, even when asking for the new column), the grants and
``security_barrier`` of ``public.v_public_tournament_teams``, its visibility
rule (draft, unpublished and inactive-organization tournaments stay out) and
the equality between the clean and the migrated chains.

The public view is read as ``bracket_app`` without any RLS context: that is the
anonymous path, and it can only work because the view owner is exempt from RLS
and ``PUBLIC`` has no privilege on the view.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG_VISIBLE = "25000000-0000-4000-8000-000000000001"
ORG_OTHER = "25000000-0000-4000-8000-000000000002"
ORG_INACTIVE = "25000000-0000-4000-8000-000000000003"

USER_VISIBLE = "25000000-0000-4000-8000-000000000011"
USER_OTHER = "25000000-0000-4000-8000-000000000012"
USER_INACTIVE = "25000000-0000-4000-8000-000000000013"

MEMBER_VISIBLE = "25000000-0000-4000-8000-000000000021"
MEMBER_OTHER = "25000000-0000-4000-8000-000000000022"
MEMBER_INACTIVE = "25000000-0000-4000-8000-000000000023"

TOURNAMENT_VISIBLE = "25000000-0000-4000-8000-000000000031"
TOURNAMENT_DRAFT = "25000000-0000-4000-8000-000000000032"
TOURNAMENT_NO_VERSION = "25000000-0000-4000-8000-000000000033"
TOURNAMENT_ARCHIVED = "25000000-0000-4000-8000-000000000034"
TOURNAMENT_OTHER = "25000000-0000-4000-8000-000000000035"
TOURNAMENT_INACTIVE = "25000000-0000-4000-8000-000000000036"

VERSION_VISIBLE = "25000000-0000-4000-8000-000000000041"
VERSION_DRAFT = "25000000-0000-4000-8000-000000000042"
VERSION_NO_VERSION = "25000000-0000-4000-8000-000000000043"
VERSION_ARCHIVED = "25000000-0000-4000-8000-000000000044"
VERSION_OTHER = "25000000-0000-4000-8000-000000000045"
VERSION_INACTIVE = "25000000-0000-4000-8000-000000000046"

TEAM_VISIBLE = "25000000-0000-4000-8000-000000000051"
TEAM_VISIBLE_NO_CREST = "25000000-0000-4000-8000-000000000052"
TEAM_DRAFT = "25000000-0000-4000-8000-000000000053"
TEAM_NO_VERSION = "25000000-0000-4000-8000-000000000054"
TEAM_ARCHIVED = "25000000-0000-4000-8000-000000000055"
TEAM_OTHER = "25000000-0000-4000-8000-000000000056"
TEAM_INACTIVE = "25000000-0000-4000-8000-000000000057"

CREST_VISIBLE = (
    f"private/organizations/{ORG_VISIBLE}/teams/{TEAM_VISIBLE}"
    "/crest/0f0e0d0c-0000-4000-8000-000000000001.webp"
)
CREST_OTHER = (
    f"private/organizations/{ORG_OTHER}/teams/{TEAM_OTHER}"
    "/crest/0f0e0d0c-0000-4000-8000-000000000002.jpg"
)

VIEW_COLUMNS = ["tournament_id", "team_id", "name", "short_code", "crest_object_key"]

# Seeds that exist before 025: no ``crest_object_key`` yet. The crest keys are
# written afterwards by ``CREST_SQL`` so the migrated chain proves the column
# arrives empty and is filled by the application, never by a backfill.
SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG_VISIBLE}', 'Migration 025 Visible', 'migration-025-visible'),
    ('{ORG_OTHER}', 'Migration 025 Other', 'migration-025-other'),
    ('{ORG_INACTIVE}', 'Migration 025 Inactive', 'migration-025-inactive');

UPDATE public.organizations
SET is_active = FALSE
WHERE id = '{ORG_INACTIVE}';

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER_VISIBLE}', 'migration-025-visible@example.test', 'hash', 'Visible Owner'),
    ('{USER_OTHER}', 'migration-025-other@example.test', 'hash', 'Other Owner'),
    ('{USER_INACTIVE}', 'migration-025-inactive@example.test', 'hash', 'Inactive Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active) VALUES
    ('{MEMBER_VISIBLE}', '{ORG_VISIBLE}', '{USER_VISIBLE}', TRUE),
    ('{MEMBER_OTHER}', '{ORG_OTHER}', '{USER_OTHER}', TRUE),
    ('{MEMBER_INACTIVE}', '{ORG_INACTIVE}', '{USER_INACTIVE}', TRUE);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES
    ('{TOURNAMENT_VISIBLE}', '{ORG_VISIBLE}', 'Visible Cup', '2026',
     DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{TOURNAMENT_DRAFT}', '{ORG_VISIBLE}', 'Draft Cup', '2026',
     DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{TOURNAMENT_NO_VERSION}', '{ORG_VISIBLE}', 'No Version Cup', '2026',
     DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{TOURNAMENT_ARCHIVED}', '{ORG_VISIBLE}', 'Archived Cup', '2026',
     DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{TOURNAMENT_OTHER}', '{ORG_OTHER}', 'Other Cup', '2026',
     DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{TOURNAMENT_INACTIVE}', '{ORG_INACTIVE}', 'Inactive Cup', '2026',
     DATE '2026-01-01', 'draft', '{{}}'::jsonb);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES
    ('{VERSION_VISIBLE}', '{ORG_VISIBLE}', '{TOURNAMENT_VISIBLE}', 1,
     '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER_VISIBLE}'),
    ('{VERSION_DRAFT}', '{ORG_VISIBLE}', '{TOURNAMENT_DRAFT}', 1,
     '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER_VISIBLE}'),
    ('{VERSION_NO_VERSION}', '{ORG_VISIBLE}', '{TOURNAMENT_NO_VERSION}', 1,
     '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER_VISIBLE}'),
    ('{VERSION_ARCHIVED}', '{ORG_VISIBLE}', '{TOURNAMENT_ARCHIVED}', 1,
     '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER_VISIBLE}'),
    ('{VERSION_OTHER}', '{ORG_OTHER}', '{TOURNAMENT_OTHER}', 1,
     '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER_OTHER}'),
    ('{VERSION_INACTIVE}', '{ORG_INACTIVE}', '{TOURNAMENT_INACTIVE}', 1,
     '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER_INACTIVE}');

INSERT INTO public.teams (id, organization_id, name, short_code, logo_url) VALUES
    ('{TEAM_VISIBLE}', '{ORG_VISIBLE}', 'Visible Team', 'V25',
     'https://crest.example.test/visible.png'),
    ('{TEAM_VISIBLE_NO_CREST}', '{ORG_VISIBLE}', 'Plain Team', 'P25', NULL),
    ('{TEAM_DRAFT}', '{ORG_VISIBLE}', 'Draft Team', 'D25', NULL),
    ('{TEAM_NO_VERSION}', '{ORG_VISIBLE}', 'No Version Team', 'N25', NULL),
    ('{TEAM_ARCHIVED}', '{ORG_VISIBLE}', 'Archived Team', 'A25', NULL),
    ('{TEAM_OTHER}', '{ORG_OTHER}', 'Other Team', 'O25', NULL),
    ('{TEAM_INACTIVE}', '{ORG_INACTIVE}', 'Inactive Team', 'I25', NULL);

INSERT INTO public.tournament_teams (
    organization_id, tournament_id, team_id, status
) VALUES
    ('{ORG_VISIBLE}', '{TOURNAMENT_VISIBLE}', '{TEAM_VISIBLE}', 'registered'),
    ('{ORG_VISIBLE}', '{TOURNAMENT_VISIBLE}', '{TEAM_VISIBLE_NO_CREST}', 'registered'),
    ('{ORG_VISIBLE}', '{TOURNAMENT_DRAFT}', '{TEAM_DRAFT}', 'registered'),
    ('{ORG_VISIBLE}', '{TOURNAMENT_NO_VERSION}', '{TEAM_NO_VERSION}', 'registered'),
    ('{ORG_VISIBLE}', '{TOURNAMENT_ARCHIVED}', '{TEAM_ARCHIVED}', 'registered'),
    ('{ORG_OTHER}', '{TOURNAMENT_OTHER}', '{TEAM_OTHER}', 'registered'),
    ('{ORG_INACTIVE}', '{TOURNAMENT_INACTIVE}', '{TEAM_INACTIVE}', 'registered');

-- Publication order used by the application: the version first, the tournament
-- afterwards. ``TOURNAMENT_DRAFT`` keeps its version in draft. The database
-- forbids a public tournament without a published version, so the «no published
-- version» case is a tournament whose referenced version is archived afterwards
-- (the version-status join of the view is what excludes it).
UPDATE public.tournament_versions
SET status = 'published', published_at = CURRENT_TIMESTAMP
WHERE id IN (
    '{VERSION_VISIBLE}', '{VERSION_ARCHIVED}', '{VERSION_OTHER}',
    '{VERSION_INACTIVE}', '{VERSION_NO_VERSION}'
);

UPDATE public.tournaments
SET status = 'published', published_version_id = '{VERSION_VISIBLE}'
WHERE id = '{TOURNAMENT_VISIBLE}';

UPDATE public.tournaments
SET status = 'archived', published_version_id = '{VERSION_ARCHIVED}'
WHERE id = '{TOURNAMENT_ARCHIVED}';

UPDATE public.tournaments
SET status = 'published', published_version_id = '{VERSION_OTHER}'
WHERE id = '{TOURNAMENT_OTHER}';

UPDATE public.tournaments
SET status = 'published', published_version_id = '{VERSION_INACTIVE}'
WHERE id = '{TOURNAMENT_INACTIVE}';

UPDATE public.tournaments
SET status = 'published', published_version_id = '{VERSION_NO_VERSION}'
WHERE id = '{TOURNAMENT_NO_VERSION}';

-- The version is archived after the tournament already points at it: there is no
-- longer a published version, so the public projection must not expose the team.
UPDATE public.tournament_versions
SET status = 'archived'
WHERE id = '{VERSION_NO_VERSION}';
"""

CREST_SQL = f"""
UPDATE public.teams SET crest_object_key = '{CREST_VISIBLE}'
WHERE id IN (
    '{TEAM_VISIBLE}', '{TEAM_DRAFT}', '{TEAM_NO_VERSION}', '{TEAM_ARCHIVED}'
);

UPDATE public.teams SET crest_object_key = '{CREST_OTHER}'
WHERE id IN ('{TEAM_OTHER}', '{TEAM_INACTIVE}');
"""


async def column_shape(connection: asyncpg.Connection) -> dict[str, object] | None:
    return await connection.fetchrow(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid) AS default_expr
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.teams'::regclass
          AND a.attname = 'crest_object_key'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    )


async def view_contract(connection: asyncpg.Connection) -> dict[str, object]:
    row = await connection.fetchrow(
        """
        SELECT pg_get_userbyid(c.relowner) AS owner_name,
               r.rolsuper,
               r.rolbypassrls,
               COALESCE(array_to_string(c.reloptions, ','), '') AS options,
               pg_get_viewdef(c.oid, true) AS definition,
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
          AND c.relname = 'v_public_tournament_teams'
        """
    )
    assert row is not None, "falta la vista public.v_public_tournament_teams"
    return dict(row)


async def view_columns(connection: asyncpg.Connection) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT a.attname
        FROM pg_attribute a
        WHERE a.attrelid = 'public.v_public_tournament_teams'::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """
    )
    return [row["attname"] for row in rows]


async def teams_snapshot(connection: asyncpg.Connection) -> dict[str, object]:
    columns = await connection.fetch(
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid) AS default_expr
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.teams'::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attname
        """
    )
    constraints = await connection.fetch(
        """
        SELECT con.conname,
               con.contype,
               con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = 'public.teams'::regclass
        ORDER BY con.conname
        """
    )
    contract = await view_contract(connection)
    return {
        "columns": [
            (row["attname"], row["data_type"], row["attnotnull"], row["default_expr"])
            for row in columns
        ],
        "constraints": [
            (row["conname"], row["contype"], row["convalidated"], row["definition"])
            for row in constraints
        ],
        "view": {
            "owner": contract["owner_name"],
            "rls_exempt": bool(contract["rolsuper"] or contract["rolbypassrls"]),
            "options": contract["options"],
            "definition": " ".join(str(contract["definition"]).split()),
            "columns": await view_columns(connection),
            "app_select": contract["app_select"],
            "public_select": contract["public_select"],
        },
    }


async def as_application_role(connection: asyncpg.Connection) -> None:
    """Switch the admin connection to ``bracket_app`` for the block."""

    await connection.execute("SET ROLE bracket_app")


async def reset_role(connection: asyncpg.Connection) -> None:
    await connection.execute(
        """
        SELECT set_config('app.current_organization_id', '', false),
               set_config('app.current_user_id', '', false)
        """
    )
    await connection.execute("RESET ROLE")


async def set_tenant(connection: asyncpg.Connection, org: str, user: str) -> None:
    await connection.execute(
        """
        SELECT set_config('app.current_organization_id', $1, false),
               set_config('app.current_user_id', $2, false)
        """,
        org,
        user,
    )


# ---------------------------------------------------------------------------
# Shape: nullable TEXT column and the public projection with its grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_025_adds_nullable_text_column_and_public_view(database_admin_url):
    async with throwaway_database(database_admin_url, last=24) as connection:
        assert await column_shape(connection) is None, (
            "teams.crest_object_key no debe existir antes de la 025"
        )
        assert (
            await connection.fetchval(
                "SELECT to_regclass('public.v_public_tournament_teams') IS NULL"
            )
            is True
        )

        await apply_migration(connection, 25)

        shape = await column_shape(connection)
        assert shape is not None, "falta la columna teams.crest_object_key"
        assert shape["data_type"] == "text"
        assert shape["attnotnull"] is False
        assert shape["default_expr"] is None

        # The projection exposes only the agreed columns: no ``logo_url``.
        assert await view_columns(connection) == VIEW_COLUMNS
        assert "logo_url" not in await view_columns(connection)

        contract = await view_contract(connection)
        assert contract["owner_name"] != "bracket_app"
        assert contract["rolsuper"] or contract["rolbypassrls"], (
            "el propietario de la vista debe estar exento de RLS"
        )
        options = contract["options"]
        assert "security_barrier=true" in options
        assert "security_invoker" not in options
        assert contract["app_select"] is True
        assert contract["public_select"] is False, "PUBLIC no debe leer la vista"


# ---------------------------------------------------------------------------
# Privileges: the new column inherits the table grants of ``teams``
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_025_crest_column_inherits_the_teams_grants(database_admin_url):
    async with throwaway_database(database_admin_url, last=24) as connection:
        await apply_migration(connection, 25)

        for privilege in ("SELECT", "INSERT", "UPDATE"):
            granted = await connection.fetchval(
                """
                SELECT has_column_privilege(
                    'bracket_app', 'public.teams', 'crest_object_key', $1
                )
                """,
                privilege,
            )
            assert granted is True, f"bracket_app debe poder {privilege} la columna"

        # DELETE has no column-level form in PostgreSQL: it stays the table grant
        # the new column is written and removed with.
        assert await connection.fetchval(
            "SELECT has_table_privilege('bracket_app', 'public.teams', 'DELETE')"
        ) is True

        # No column-level grant was added: the table GRANT already covers it.
        column_privileges = await connection.fetch(
            """
            SELECT a.attname, a.attacl::text AS column_acl
            FROM pg_attribute a
            WHERE a.attrelid = 'public.teams'::regclass
              AND a.attnum > 0
              AND NOT a.attisdropped
              AND a.attacl IS NOT NULL
            """
        )
        assert column_privileges == [], "la 025 no debe añadir privilegios por columna"


# ---------------------------------------------------------------------------
# RLS: another organization never sees the team, even the new column
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_025_rls_hides_another_organization_team(database_admin_url):
    async with throwaway_database(database_admin_url, last=24) as connection:
        await apply_migration(connection, 25)
        await connection.execute(SEED_SQL)
        await connection.execute(CREST_SQL)

        await as_application_role(connection)
        try:
            # Tenant A sees its own teams with the crest key and never the other
            # organization's one, although every row exists in the table.
            await set_tenant(connection, ORG_VISIBLE, USER_VISIBLE)
            own_rows = await connection.fetch(
                "SELECT id, crest_object_key FROM public.teams ORDER BY id"
            )
            own_ids = {str(row["id"]) for row in own_rows}
            assert TEAM_VISIBLE in own_ids
            assert TEAM_DRAFT in own_ids
            assert TEAM_OTHER not in own_ids
            assert TEAM_INACTIVE not in own_ids
            crests = {
                str(row["id"]): row["crest_object_key"]
                for row in own_rows
                if row["crest_object_key"] is not None
            }
            assert crests[TEAM_VISIBLE] == CREST_VISIBLE

            # The application role can write the new column inside its tenant:
            # the table GRANT covers the column and RLS keeps the fence.
            await connection.execute(
                "UPDATE public.teams SET crest_object_key = $1 WHERE id = $2",
                "private/organizations/renamed/crest.webp",
                TEAM_VISIBLE,
            )
            assert await connection.fetchval(
                "SELECT crest_object_key FROM public.teams WHERE id = $1",
                TEAM_VISIBLE,
            ) == "private/organizations/renamed/crest.webp"

            # A team of another organization is out of reach: the UPDATE touches
            # no row and the row stays invisible.
            updated = await connection.execute(
                "UPDATE public.teams SET crest_object_key = 'leak' WHERE id = $1",
                TEAM_OTHER,
            )
            assert updated == "UPDATE 0"
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM public.teams WHERE id = $1", TEAM_OTHER
                )
                == 0
            )

            # Tenant B only sees its own row.
            await set_tenant(connection, ORG_OTHER, USER_OTHER)
            other_ids = {
                str(row["id"])
                for row in await connection.fetch("SELECT id FROM public.teams")
            }
            assert other_ids == {TEAM_OTHER}
            assert (
                await connection.fetchval(
                    "SELECT crest_object_key FROM public.teams WHERE id = $1",
                    TEAM_OTHER,
                )
                == CREST_OTHER
            )

            # No tenant context: no row at all, the new column included.
            await set_tenant(connection, "", "")
            assert await connection.fetchval("SELECT count(*) FROM public.teams") == 0
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM public.teams "
                    "WHERE crest_object_key IS NOT NULL"
                )
                == 0
            )
        finally:
            await reset_role(connection)


# ---------------------------------------------------------------------------
# Visibility: the public projection follows the public tournament condition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_025_public_view_only_returns_publicly_visible_tournaments(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=24) as connection:
        await apply_migration(connection, 25)
        await connection.execute(SEED_SQL)
        await connection.execute(CREST_SQL)

        # Anonymous read: no RLS context, application role, only the view GRANT.
        await as_application_role(connection)
        try:
            rows = await connection.fetch(
                """
                SELECT tournament_id, team_id, name, short_code, crest_object_key
                FROM public.v_public_tournament_teams
                ORDER BY team_id
                """
            )
        finally:
            await reset_role(connection)

        projected = {
            (str(row["tournament_id"]), str(row["team_id"])): row for row in rows
        }
        assert set(projected) == {
            (TOURNAMENT_VISIBLE, TEAM_VISIBLE),
            (TOURNAMENT_VISIBLE, TEAM_VISIBLE_NO_CREST),
            (TOURNAMENT_OTHER, TEAM_OTHER),
        }

        # Draft, published tournament without a published version, archived and
        # inactive organization stay out even though their crest key exists.
        visible_tournaments = {tournament for tournament, _team in projected}
        for excluded in (
            TOURNAMENT_DRAFT,
            TOURNAMENT_NO_VERSION,
            TOURNAMENT_ARCHIVED,
            TOURNAMENT_INACTIVE,
        ):
            assert excluded not in visible_tournaments, (
                f"el torneo {excluded} no es visible públicamente"
            )

        visible = projected[(TOURNAMENT_VISIBLE, TEAM_VISIBLE)]
        assert visible["crest_object_key"] == CREST_VISIBLE
        assert visible["name"] == "Visible Team"
        assert visible["short_code"] == "V25"

        # A team without a crest is still projected: absence is NULL, not a
        # missing row, and ``logo_url`` is never part of the projection.
        no_crest = projected[(TOURNAMENT_VISIBLE, TEAM_VISIBLE_NO_CREST)]
        assert no_crest["crest_object_key"] is None
        assert set(no_crest.keys()) == {
            "tournament_id",
            "team_id",
            "name",
            "short_code",
            "crest_object_key",
        }


# ---------------------------------------------------------------------------
# Clean chain versus migrated chain, and no backfill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_025_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=24) as connection:
        # Rows created before the column: the migration leaves them at NULL, so
        # there is no backfill and no rewrite.
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 25)
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM public.teams WHERE crest_object_key IS NOT NULL"
            )
            == 0
        )
        migrated = await teams_snapshot(connection)

    async with throwaway_database(database_admin_url, last=25) as clean:
        assert await teams_snapshot(clean) == migrated

        # The clean chain really applied 025: the column exists and the view is
        # readable by the application role without a tenant context.
        await clean.execute(SEED_SQL)
        await clean.execute(CREST_SQL)
        await as_application_role(clean)
        try:
            count = await clean.fetchval(
                "SELECT count(*) FROM public.v_public_tournament_teams"
            )
        finally:
            await reset_role(clean)
        assert count == 3
