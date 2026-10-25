"""Migration 024: one Google identity per account (RF-13, RF-22, RNF-11).

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the additive change is validated both on an
already migrated volume (023 -> 024) and on the clean-volume chain
(init + 001..024). The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` because creating databases and applying DDL require a
role the application role does not have.

Assertions cover the ``UNIQUE (user_id, provider)`` constraint (type, columns
and validation state), its enforcement on new rows, the aborting pre-check that
names the count of duplicated accounts without deleting or rewriting rows, the
absence of grants and RLS changes, and the equality between the clean and the
migrated chains.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

USER_A = "24000000-0000-4000-8000-000000000001"
USER_B = "24000000-0000-4000-8000-000000000002"
IDENTITY_A1 = "24000000-0000-4000-8000-000000000011"
IDENTITY_A2 = "24000000-0000-4000-8000-000000000012"
IDENTITY_B1 = "24000000-0000-4000-8000-000000000013"
IDENTITY_B2 = "24000000-0000-4000-8000-000000000014"
IDENTITY_C = "24000000-0000-4000-8000-000000000015"
IDENTITY_D = "24000000-0000-4000-8000-000000000016"

CONSTRAINT = "uq_auth_identity_user_provider"
EXISTING_CONSTRAINT = "uq_auth_provider_subject"

SEED_USERS_SQL = f"""
INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER_A}', 'migration-024-a@example.test', 'hash', 'Migration 024 A'),
    ('{USER_B}', 'migration-024-b@example.test', NULL, 'Migration 024 B');
"""

# Two accounts, each with two Google identities: the invariant is already
# violated twice (RNF-11, case 4).
SEED_DUPLICATES_SQL = (
    SEED_USERS_SQL
    + f"""
INSERT INTO public.auth_identities (id, user_id, provider, provider_subject) VALUES
    ('{IDENTITY_A1}', '{USER_A}', 'google', 'google-subject-a-1'),
    ('{IDENTITY_A2}', '{USER_A}', 'google', 'google-subject-a-2'),
    ('{IDENTITY_B1}', '{USER_B}', 'google', 'google-subject-b-1'),
    ('{IDENTITY_B2}', '{USER_B}', 'google', 'google-subject-b-2');
"""
)


async def constraint_catalog(
    connection: asyncpg.Connection,
) -> list[tuple[str, str, bool, str, list[str]]]:
    """Return the constraint catalog of ``auth_identities`` in a stable order."""

    rows = await connection.fetch(
        """
        SELECT con.conname,
               con.contype,
               con.convalidated,
               pg_get_constraintdef(con.oid) AS definition,
               ARRAY(
                   SELECT a.attname
                   FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                   JOIN pg_attribute a
                     ON a.attrelid = con.conrelid
                    AND a.attnum = k.attnum
                   ORDER BY k.ord
               ) AS columns
        FROM pg_constraint con
        WHERE con.conrelid = 'public.auth_identities'::regclass
        ORDER BY con.conname
        """
    )
    return [
        (
            row["conname"],
            row["contype"],
            row["convalidated"],
            row["definition"],
            list(row["columns"]),
        )
        for row in rows
    ]


async def table_snapshot(connection: asyncpg.Connection) -> dict[str, object]:
    """Columns, constraints, RLS flags and grants of ``auth_identities``."""

    columns = await connection.fetch(
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull
        FROM pg_attribute a
        WHERE a.attrelid = 'public.auth_identities'::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attname
        """
    )
    table_flags = await connection.fetchrow(
        """
        SELECT c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c
        WHERE c.oid = 'public.auth_identities'::regclass
        """
    )
    grants = await connection.fetch(
        """
        SELECT grantee, privilege_type, column_name
        FROM information_schema.column_privileges
        WHERE table_schema = 'public'
          AND table_name = 'auth_identities'
        ORDER BY grantee, column_name, privilege_type
        """
    )
    return {
        "columns": [
            (row["attname"], row["data_type"], row["attnotnull"]) for row in columns
        ],
        "constraints": await constraint_catalog(connection),
        "rls": (table_flags["relrowsecurity"], table_flags["relforcerowsecurity"]),
        "grants": [
            (row["grantee"], row["column_name"], row["privilege_type"])
            for row in grants
        ],
    }


async def identity_rows(connection: asyncpg.Connection) -> list[tuple[str, str, str]]:
    rows = await connection.fetch(
        """
        SELECT id::text, user_id::text, provider_subject
        FROM public.auth_identities
        ORDER BY id
        """
    )
    return [(row["id"], row["user_id"], row["provider_subject"]) for row in rows]


# ---------------------------------------------------------------------------
# Shape: the unique constraint exists in the clean chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_024_clean_chain_has_unique_user_provider_constraint(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=24) as connection:
        constraints = {
            name: (contype, validated, definition, columns)
            for name, contype, validated, definition, columns in await constraint_catalog(
                connection
            )
        }

        assert CONSTRAINT in constraints
        contype, validated, definition, columns = constraints[CONSTRAINT]
        # asyncpg decodes "char" columns as bytes.
        assert contype == b"u"
        assert validated is True
        assert columns == ["user_id", "provider"]
        assert "UNIQUE" in definition

        # The constraint that guarantees "one identity belongs to exactly one
        # account" is still there, untouched.
        assert EXISTING_CONSTRAINT in constraints
        assert constraints[EXISTING_CONSTRAINT][3] == [
            "provider",
            "provider_subject",
        ]


# ---------------------------------------------------------------------------
# Migrated chain (023 -> 024) equals the clean chain, with no grants or RLS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_024_migrated_chain_matches_clean_chain_without_grants_or_rls(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=23) as connection:
        before = await table_snapshot(connection)
        assert CONSTRAINT not in {row[0] for row in before["constraints"]}

        await apply_migration(connection, 24)

        migrated = await table_snapshot(connection)

        assert CONSTRAINT in {row[0] for row in migrated["constraints"]}
        # Additive only: columns, RLS flags and privileges are unchanged.
        assert migrated["columns"] == before["columns"]
        assert migrated["rls"] == before["rls"]
        assert migrated["rls"] == (False, False)
        assert migrated["grants"] == before["grants"]

    async with throwaway_database(database_admin_url, last=24) as clean:
        clean_snapshot = await table_snapshot(clean)
        assert clean_snapshot == migrated


# ---------------------------------------------------------------------------
# Enforcement: at most one identity per (user, provider)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_024_rejects_second_identity_for_same_account_and_provider(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=23) as connection:
        await connection.execute(SEED_USERS_SQL)
        await apply_migration(connection, 24)

        await connection.execute(
            """
            INSERT INTO public.auth_identities (id, user_id, provider, provider_subject)
            VALUES ($1, $2, 'google', 'google-subject-a-1')
            """,
            IDENTITY_A1,
            USER_A,
        )

        # A second Google identity for the same account is rejected by the
        # constraint, not by an application-level check.
        with pytest.raises(asyncpg.exceptions.UniqueViolationError) as error:
            await connection.execute(
                """
                INSERT INTO public.auth_identities (id, user_id, provider, provider_subject)
                VALUES ($1, $2, 'google', 'google-subject-a-2')
                """,
                IDENTITY_A2,
                USER_A,
            )
        assert CONSTRAINT in str(error.value)

        # Another provider is a different identity and is accepted.
        await connection.execute(
            """
            INSERT INTO public.auth_identities (id, user_id, provider, provider_subject)
            VALUES ($1, $2, 'github', 'github-subject-a')
            """,
            IDENTITY_C,
            USER_A,
        )

        # The same provider for a different account is accepted: the existing
        # (provider, provider_subject) uniqueness is what makes subjects unique.
        await connection.execute(
            """
            INSERT INTO public.auth_identities (id, user_id, provider, provider_subject)
            VALUES ($1, $2, 'google', 'google-subject-b-1')
            """,
            IDENTITY_B1,
            USER_B,
        )

        assert await identity_rows(connection) == [
            (IDENTITY_A1, USER_A, "google-subject-a-1"),
            (IDENTITY_B1, USER_B, "google-subject-b-1"),
            (IDENTITY_C, USER_A, "github-subject-a"),
        ]


# ---------------------------------------------------------------------------
# Pre-check: abort with the count and no row deletion or rewriting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_024_precheck_aborts_with_count_and_preserves_rows(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=23) as connection:
        await connection.execute(SEED_DUPLICATES_SQL)
        before = await identity_rows(connection)
        assert len(before) == 4

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 24)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 024" in message
        # The count is of duplicated accounts, not of duplicated rows.
        assert "cuentas con mas de una identidad del mismo proveedor=2" in message

        # Nothing is deleted, merged or rewritten.
        assert await identity_rows(connection) == before

        # The pre-check aborts before the ALTER TABLE runs: no constraint.
        assert CONSTRAINT not in {row[0] for row in await constraint_catalog(connection)}

        # Once the data is reviewed by hand, the migration applies cleanly.
        await connection.execute(
            """
            DELETE FROM public.auth_identities
            WHERE id IN ($1, $2)
            """,
            IDENTITY_A2,
            IDENTITY_B2,
        )
        await apply_migration(connection, 24)

        assert CONSTRAINT in {row[0] for row in await constraint_catalog(connection)}
        assert await identity_rows(connection) == [
            row for row in before if row[0] in {IDENTITY_A1, IDENTITY_B1}
        ]
