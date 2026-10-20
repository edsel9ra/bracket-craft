"""Migration 019: retirement of tournament roles and stage selectors.

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so both the clean-volume chain (init + 001..019) and
an already migrated volume (018 -> 019) are covered. The suite is opt-in: it
needs ``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL`` because creating
databases and applying DDL require a role the application role does not have.

Assertions cover the three pre-checks (rows in both tables and retired
``source_type`` values), the catalog discovery of the CHECK constraint, the
narrowed CHECK, the ``ZZ409`` SQLSTATE of the recreated trigger function, the
RLS posture left by ``init`` and the preservation of ``phase_slots``.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import (
    STAGE_TARGET,
    TOURNAMENT,
    VERSION,
    apply_migration,
    insert_phase_slot,
    insert_stage_edge,
    insert_tournament_user_role,
    seed_retired_structures,
    source_type_check_names,
    throwaway_database,
)

RETIRED_TABLES = ("tournament_user_roles", "stage_edges")
PUBLISHED_MESSAGE = "La versión publicada o archivada no puede modificarse"
INSERT_MESSAGE = "No se pueden insertar estructuras en una versión publicada"


async def _table_exists(connection: asyncpg.Connection, table: str) -> bool:
    return await connection.fetchval(
        "SELECT to_regclass($1) IS NOT NULL", f"public.{table}"
    )


async def _function_definition(connection: asyncpg.Connection) -> str:
    return await connection.fetchval(
        """
        SELECT pg_get_functiondef(
            'public.prevent_published_structure_mutation()'::regprocedure
        )
        """
    )


async def _source_type_constraint(
    connection: asyncpg.Connection,
) -> tuple[str, str]:
    row = await connection.fetchrow(
        """
        SELECT con.conname, pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = 'public.phase_slots'::regclass
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ~ '\\msource_type\\M'
        """
    )
    assert row is not None, "phase_slots.source_type debe tener un CHECK"
    return row["conname"], row["definition"]


async def _assert_retired_tables_survive_abort(
    connection: asyncpg.Connection,
) -> None:
    for table in RETIRED_TABLES:
        assert await _table_exists(connection, table) is True
    assert "ZZ409" not in await _function_definition(connection)


# ---------------------------------------------------------------------------
# Clean volume and already migrated volume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_volume_applies_init_and_migrations_through_019(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=19) as connection:
        for table in RETIRED_TABLES:
            assert await _table_exists(connection, table) is False

        # The narrowed CHECK accepts only the two real provenance values.
        name, definition = await _source_type_constraint(connection)
        assert name
        assert "direct_team" in definition
        assert "match_result" in definition
        assert "stage_rank" not in definition
        assert "manual" not in definition

        # phase_slots and the match slot columns remain as stored provenance.
        slot_columns = {
            row["column_name"]
            for row in await connection.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'phase_slots'
                """
            )
        }
        assert {
            "id",
            "organization_id",
            "tournament_id",
            "tournament_version_id",
            "stage_id",
            "slot_code",
            "source_type",
            "source_reference",
        } <= slot_columns
        match_columns = {
            row["column_name"]
            for row in await connection.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'matches'
                """
            )
        }
        assert {"home_slot_id", "away_slot_id"} <= match_columns

        # RLS stays enabled and forced on the preserved table.
        rls = await connection.fetchrow(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'public.phase_slots'::regclass
            """
        )
        assert rls["relrowsecurity"] is True
        assert rls["relforcerowsecurity"] is True

        # The immutability function uses the stable, user-class SQLSTATE.
        definition_sql = await _function_definition(connection)
        assert definition_sql.count("ZZ409") == 2
        assert PUBLISHED_MESSAGE in definition_sql
        assert INSERT_MESSAGE in definition_sql


@pytest.mark.asyncio
async def test_migrated_volume_at_018_upgrades_to_019_preserving_slots(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=18) as connection:
        # State after 018: both retired tables still exist with RLS forced.
        for table in RETIRED_TABLES:
            assert await _table_exists(connection, table) is True
            rls = await connection.fetchrow(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = $1::regclass
                """,
                f"public.{table}",
            )
            assert rls["relrowsecurity"] is True
            assert rls["relforcerowsecurity"] is True

        await seed_retired_structures(connection)
        await insert_phase_slot(connection, source_type="direct_team", slot_code="P1")

        await apply_migration(connection, 19)

        for table in RETIRED_TABLES:
            assert await _table_exists(connection, table) is False
            assert await connection.fetchval(
                "SELECT count(*) FROM pg_class WHERE relname = $1", table
            ) == 0

        # Kind='c' CHECK is narrowed and functional; data is preserved.
        _, definition = await _source_type_constraint(connection)
        assert "stage_rank" not in definition
        assert "manual" not in definition
        preserved = await connection.fetchrow(
            """
            SELECT source_type, source_reference
            FROM public.phase_slots
            WHERE tournament_id = $1
            """,
            TOURNAMENT,
        )
        assert preserved["source_type"] == "direct_team"
        assert preserved["source_reference"] == "{}"

        assert "ZZ409" in await _function_definition(connection)


# ---------------------------------------------------------------------------
# init: RLS enabled but no policies or grants for the retired tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_keeps_rls_without_policies_or_grants(database_admin_url):
    async with throwaway_database(database_admin_url, last=0) as connection:
        for table in RETIRED_TABLES:
            assert await _table_exists(connection, table) is True

            rls = await connection.fetchrow(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = $1::regclass
                """,
                f"public.{table}",
            )
            assert rls["relrowsecurity"] is True
            assert rls["relforcerowsecurity"] is True

            assert await connection.fetchval(
                """
                SELECT count(*)
                FROM pg_policy pol
                WHERE pol.polrelid = $1::regclass
                """,
                f"public.{table}",
            ) == 0

            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert await connection.fetchval(
                    "SELECT has_table_privilege('bracket_app', $1, $2)",
                    f"public.{table}",
                    privilege,
                ) is False

        # init no longer creates the stage_edges trigger.
        assert await connection.fetchval(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_protect_stage_edges'"
        ) == 0


# ---------------------------------------------------------------------------
# Pre-checks: rows in the retired tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_019_aborts_with_rows_in_tournament_user_roles(database_admin_url):
    async with throwaway_database(database_admin_url, last=18) as connection:
        await seed_retired_structures(connection)
        await insert_tournament_user_role(connection)

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 19)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 019" in message
        assert "tournament_user_roles" in message
        assert "1 fila" in message
        await _assert_retired_tables_survive_abort(connection)


@pytest.mark.asyncio
async def test_019_aborts_with_rows_in_stage_edges(database_admin_url):
    async with throwaway_database(database_admin_url, last=18) as connection:
        await seed_retired_structures(connection)
        await insert_stage_edge(connection)

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 19)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 019" in message
        assert "stage_edges" in message
        assert "1 fila" in message
        await _assert_retired_tables_survive_abort(connection)


# ---------------------------------------------------------------------------
# Pre-checks: retired source_type values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("retired_value", ["stage_rank", "manual"])
async def test_019_aborts_with_retired_source_type_values(
    database_admin_url, retired_value
):
    async with throwaway_database(database_admin_url, last=18) as connection:
        await seed_retired_structures(connection)
        await insert_phase_slot(
            connection, source_type=retired_value, slot_code="R1"
        )

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 19)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 019" in message
        assert "phase_slots.source_type" in message
        assert f"{retired_value}=1" in message
        await _assert_retired_tables_survive_abort(connection)

        # The row was not rewritten or deleted.
        assert await connection.fetchval(
            "SELECT count(*) FROM public.phase_slots WHERE source_type = $1",
            retired_value,
        ) == 1


# ---------------------------------------------------------------------------
# Pre-checks: CHECK constraint discovery by catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_019_aborts_without_a_matching_source_type_check(database_admin_url):
    async with throwaway_database(database_admin_url, last=18) as connection:
        names = await source_type_check_names(connection)
        assert len(names) == 1
        await connection.execute(
            f'ALTER TABLE public.phase_slots DROP CONSTRAINT "{names[0]}"'
        )

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 19)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 019" in message
        assert "phase_slots.source_type" in message
        assert "exactamente una constraint CHECK" in message
        await _assert_retired_tables_survive_abort(connection)
        assert await source_type_check_names(connection) == []


@pytest.mark.asyncio
async def test_019_aborts_with_duplicate_source_type_checks(database_admin_url):
    async with throwaway_database(database_admin_url, last=18) as connection:
        await connection.execute(
            """
            ALTER TABLE public.phase_slots
            ADD CONSTRAINT phase_slots_source_type_check_dup
            CHECK (source_type IN ('direct_team', 'stage_rank', 'match_result', 'manual'))
            """
        )
        assert len(await source_type_check_names(connection)) == 2

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 19)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 019" in message
        assert "phase_slots.source_type" in message
        assert "se encontraron 2" in message
        await _assert_retired_tables_survive_abort(connection)
        assert len(await source_type_check_names(connection)) == 2


# ---------------------------------------------------------------------------
# Final state: narrowed CHECK and ZZ409 trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_019_narrows_the_source_type_check_at_runtime(database_admin_url):
    async with throwaway_database(database_admin_url, last=18) as connection:
        await seed_retired_structures(connection)
        await apply_migration(connection, 19)

        # Retired values are rejected by the database.
        for index, retired_value in enumerate(("stage_rank", "manual"), start=1):
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await insert_phase_slot(
                    connection, source_type=retired_value, slot_code=f"X{index}"
                )

        # Both real provenance values are accepted.
        for index, allowed_value in enumerate(("direct_team", "match_result"), start=1):
            await insert_phase_slot(
                connection, source_type=allowed_value, slot_code=f"O{index}"
            )

        assert await connection.fetchval(
            "SELECT count(*) FROM public.phase_slots"
        ) == 2


@pytest.mark.asyncio
async def test_019_trigger_raises_the_zz409_sqlstate(database_admin_url):
    async with throwaway_database(database_admin_url, last=18) as connection:
        await seed_retired_structures(connection)
        await apply_migration(connection, 19)

        await connection.execute(
            "UPDATE public.tournament_versions SET status = 'published' WHERE id = $1",
            VERSION,
        )

        with pytest.raises(asyncpg.exceptions.PostgresError) as error:
            await insert_phase_slot(connection, source_type="direct_team")

        assert error.value.sqlstate == "ZZ409"
        assert INSERT_MESSAGE in str(error.value)
        assert await connection.fetchval(
            "SELECT count(*) FROM public.phase_slots WHERE stage_id = $1",
            STAGE_TARGET,
        ) == 0
