"""Migrations 017 and 018: intermediate state, closure and grants (RF-003, RF-005).

Every test builds a throwaway database at init + 001-016, seeds a deterministic
catalog with two organizations and applies the real migration files with the
administrator role. The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` (creating databases and applying DDL require a role the
application role does not have).

The assertions cover the intermediate state (the plaintext column is still
present but unreadable and unwritable for ``bracket_app``, the ciphertext is
write-only, the derived age is readable and the historical age follows the
oldest roster registration instant) and the closure performed by 018: pending
rows block the migration, dependencies are checked before the drop, the
ciphertext becomes mandatory and the plaintext column disappears.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg
import pytest

from birth_date_migration_helpers import (
    MATCH_A,
    ORG_A,
    PLAYER_OLDEST_ROSTER,
    PLAYER_OTHER_ORGANIZATION,
    PLAYER_TIE_BREAK,
    PLAYER_WITHOUT_ROSTER,
    WITHOUT_ROSTER_SESSION_TIMEZONE,
    apply_migration,
    seed_birth_date_scenario,
    throwaway_database,
)

PLAYERS_TABLE = "public.players"
PUBLIC_VIEW = "public.v_public_tournament_players"
LINEUPS_VIEW = "public.v_public_match_lineups"

NEW_COLUMNS = ("birth_date_encrypted", "age_at_reference", "age_reference_year")

EXPECTED_PUBLIC_VIEW_COLUMNS = [
    ("tournament_id", "uuid"),
    ("player_id", "uuid"),
    ("first_name", "character varying(100)"),
    ("last_name", "character varying(100)"),
    ("dorsal_number", "integer"),
    ("team_id", "uuid"),
    ("public_age", "integer"),
    ("photo_url", "text"),
]


@asynccontextmanager
async def _as_application_role(
    connection: asyncpg.Connection, *, organization_id: str, user_id: str
):
    """Run statements as ``bracket_app`` inside a transaction scoped to a tenant."""

    async with connection.transaction():
        await connection.execute("SET LOCAL ROLE bracket_app")
        await connection.execute(
            "SELECT set_config('app.current_organization_id', $1, true)",
            organization_id,
        )
        await connection.execute(
            "SELECT set_config('app.current_user_id', $1, true)", user_id
        )
        yield


async def _column_definition(connection: asyncpg.Connection, column: str):
    return await connection.fetchrow(
        """
        SELECT data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'players'
          AND column_name = $1
        """,
        column,
    )


async def _column_privilege(
    connection: asyncpg.Connection, column: str, privilege: str
) -> bool:
    return await connection.fetchval(
        "SELECT has_column_privilege('bracket_app', $1, $2, $3)",
        PLAYERS_TABLE,
        column,
        privilege,
    )


async def _public_column_privileges(
    connection: asyncpg.Connection, column: str
) -> set[str]:
    """Return the column privileges granted to PUBLIC (grantee oid 0)."""

    rows = await connection.fetch(
        """
        SELECT acl.privilege_type
        FROM pg_attribute a
        CROSS JOIN LATERAL aclexplode(a.attacl) AS acl
        WHERE a.attrelid = 'public.players'::regclass
          AND a.attname = $1
          AND acl.grantee = 0
        """,
        column,
    )
    return {row["privilege_type"] for row in rows}


async def _age_rows(connection: asyncpg.Connection) -> dict[str, tuple[int, int]]:
    rows = await connection.fetch(
        "SELECT id::text, age_at_reference, age_reference_year FROM public.players"
    )
    return {
        row["id"]: (row["age_at_reference"], row["age_reference_year"])
        for row in rows
    }


T004_KEY = "t004-test-key"


async def _encrypt_pending_birth_dates(
    connection: asyncpg.Connection, key: str = T004_KEY
) -> None:
    """Simulate the completed backfill with the administrator role."""

    await connection.execute(
        """
        UPDATE public.players
        SET birth_date_encrypted = pgp_sym_encrypt(birth_date::text, $1)
        WHERE birth_date_encrypted IS NULL
        """,
        key,
    )


async def _table_counts(connection: asyncpg.Connection) -> dict[str, int]:
    """Return the row counts that migration 018 must preserve."""

    tables = (
        "players",
        "rosters",
        "match_rosters",
        "match_events",
        "player_suspensions",
    )
    return {
        table: await connection.fetchval(f"SELECT count(*) FROM public.{table}")
        for table in tables
    }


async def _plaintext_birth_dates(connection: asyncpg.Connection) -> dict[str, str]:
    rows = await connection.fetch(
        "SELECT id::text, birth_date::text FROM public.players ORDER BY id"
    )
    return {row["id"]: row["birth_date"] for row in rows}


async def _decrypted_birth_dates(
    connection: asyncpg.Connection, key: str = T004_KEY
) -> dict[str, str]:
    rows = await connection.fetch(
        """
        SELECT id::text,
               pgp_sym_decrypt(birth_date_encrypted, $1)::date::text AS birth_date
        FROM public.players
        ORDER BY id
        """,
        key,
    )
    return {row["id"]: row["birth_date"] for row in rows}


async def _public_view_columns(connection: asyncpg.Connection):
    rows = await connection.fetch(
        """
        SELECT a.attname AS name,
               format_type(a.atttypid, a.atttypmod) AS type
        FROM pg_attribute a
        WHERE a.attrelid = $1::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        PUBLIC_VIEW,
    )
    return [(row["name"], row["type"]) for row in rows]


@pytest.mark.asyncio
async def test_migration_017_adds_the_ciphertext_and_materializes_the_historical_age(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        scenario = await seed_birth_date_scenario(connection)

        # A session timezone that is not UTC must not change the reference year
        # of a player without rosters.
        await connection.execute(f"SET TIME ZONE '{WITHOUT_ROSTER_SESSION_TIMEZONE}'")
        await apply_migration(connection, 17)

        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["data_type"] == "bytea"
        assert ciphertext["is_nullable"] == "YES"

        age_at_reference = await _column_definition(connection, "age_at_reference")
        assert age_at_reference["data_type"] == "smallint"
        assert age_at_reference["is_nullable"] == "NO"

        reference_year = await _column_definition(connection, "age_reference_year")
        assert reference_year["data_type"] == "smallint"
        assert reference_year["is_nullable"] == "NO"

        plaintext = await _column_definition(connection, "birth_date")
        assert plaintext is not None, "La fecha en claro se conserva hasta la 018"
        assert plaintext["is_nullable"] == "YES"

        ages = await _age_rows(connection)
        assert ages == {
            player_id: (
                scenario.expected_age_at_reference[player_id],
                scenario.expected_reference_year[player_id],
            )
            for player_id in scenario.expected_age_at_reference
        }

        # The oldest roster wins even when its tournament is older than the
        # newer roster, and ties break on the roster identifier.
        assert ages[PLAYER_OLDEST_ROSTER] == (24, 2024)
        assert ages[PLAYER_TIE_BREAK] == (34, 2024)
        assert ages[PLAYER_WITHOUT_ROSTER] == (27, 2028)
        assert ages[PLAYER_OTHER_ORGANIZATION] == (18, 2028)

        # Identifiers and tenant ownership are preserved.
        assert await connection.fetchval("SELECT count(*) FROM public.players") == 4
        assert await connection.fetchval(
            "SELECT count(*) FROM public.players WHERE organization_id = $1",
            ORG_A,
        ) == 3
        assert (
            await connection.fetchval(
                "SELECT organization_id::text FROM public.players WHERE id = $1",
                PLAYER_WITHOUT_ROSTER,
            )
            == ORG_A
        )
        assert (
            await connection.fetchval(
                """
                SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
                FROM public.players
                WHERE id = $1
                """,
                PLAYER_WITHOUT_ROSTER,
            )
            == "2028-01-01 02:00:00"
        )


@pytest.mark.asyncio
async def test_migration_017_handles_a_leap_day_and_the_cipher_round_trip(
    database_admin_url,
):
    """RF-001/RF-003: 29 February keeps its day and computes the right age."""

    async with throwaway_database(database_admin_url) as connection:
        scenario = await seed_birth_date_scenario(connection)
        leap_player_id = await connection.fetchval(
            """
            INSERT INTO public.players (
                organization_id, first_name, last_name, document_type,
                national_id_encrypted, national_id_hmac, issuing_country,
                birth_date, created_at
            ) VALUES (
                $1, 'Leap', 'Day', 'DNI', decode('0909', 'hex'),
                repeat('9', 64), 'ARG', DATE '2000-02-29',
                '2025-06-01 00:00:00+00'
            )
            RETURNING id::text
            """,
            scenario.organization_a,
        )

        await apply_migration(connection, 17)

        row = await connection.fetchrow(
            """
            SELECT age_at_reference, age_reference_year,
                   pgp_sym_decrypt(
                       pgp_sym_encrypt(birth_date::text, $1), $1
                   )::date::text AS round_trip
            FROM public.players
            WHERE id = $2
            """,
            T004_KEY,
            leap_player_id,
        )
        # No roster: the reference year comes from created_at in UTC.
        assert (row["age_at_reference"], row["age_reference_year"]) == (25, 2025)
        assert row["round_trip"] == "2000-02-29"


@pytest.mark.asyncio
async def test_migration_017_turns_the_plaintext_into_an_unreadable_unwritable_column(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        scenario = await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)

        # Column privileges on players: exact plan matrix.
        assert await _column_privilege(connection, "birth_date", "SELECT") is False
        assert await _column_privilege(connection, "birth_date", "INSERT") is False
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "SELECT")
            is False
        )
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "INSERT")
            is True
        )
        for column in ("age_at_reference", "age_reference_year"):
            assert await _column_privilege(connection, column, "SELECT") is True
            assert await _column_privilege(connection, column, "INSERT") is True
        assert (
            await _column_privilege(connection, "national_id_encrypted", "SELECT")
            is False
        )
        assert (
            await _column_privilege(connection, "national_id_encrypted", "INSERT")
            is True
        )
        table = await connection.fetchrow(
            """
            SELECT has_table_privilege('bracket_app', $1, 'UPDATE') AS update_allowed,
                   has_table_privilege('bracket_app', $1, 'DELETE') AS delete_allowed,
                   has_table_privilege('bracket_app', $1, 'SELECT') AS select_allowed
            """,
            PLAYERS_TABLE,
        )
        assert table["update_allowed"] is False
        assert table["delete_allowed"] is False
        assert table["select_allowed"] is False

        # PUBLIC keeps no plaintext grant either.
        assert await _public_column_privileges(connection, "birth_date") == set()

        # The application role really cannot read or write the plaintext.
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            async with _as_application_role(
                connection,
                organization_id=scenario.organization_a,
                user_id=scenario.user_a,
            ):
                await connection.fetchval("SELECT birth_date FROM public.players LIMIT 1")

        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            async with _as_application_role(
                connection,
                organization_id=scenario.organization_a,
                user_id=scenario.user_a,
            ):
                await connection.fetchval(
                    "SELECT birth_date_encrypted FROM public.players LIMIT 1"
                )

        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            async with _as_application_role(
                connection,
                organization_id=scenario.organization_a,
                user_id=scenario.user_a,
            ):
                await connection.execute(
                    """
                    INSERT INTO public.players (
                        organization_id, first_name, last_name, document_type,
                        national_id_encrypted, national_id_hmac, issuing_country,
                        birth_date, age_at_reference, age_reference_year
                    ) VALUES (
                        $1, 'Denied', 'Plaintext', 'DNI', decode('00', 'hex'),
                        repeat('d', 64), 'ARG', CAST('1999-01-01' AS DATE), 27, 2026
                    )
                    """,
                    scenario.organization_a,
                )

        # The new write-only path works with the application role and no plaintext.
        async with _as_application_role(
            connection,
            organization_id=scenario.organization_a,
            user_id=scenario.user_a,
        ):
            new_player_id = await connection.fetchval(
                """
                INSERT INTO public.players (
                    organization_id, first_name, last_name, document_type,
                    national_id_encrypted, national_id_hmac, issuing_country,
                    birth_date_encrypted, age_at_reference, age_reference_year
                ) VALUES (
                    $1, 'New', 'Player', 'DNI', decode('00', 'hex'),
                    repeat('e', 64), 'ARG', decode('0102', 'hex'), 26, 2026
                )
                RETURNING id
                """,
                scenario.organization_a,
            )
            inserted = await connection.fetchrow(
                """
                SELECT age_at_reference, age_reference_year
                FROM public.players
                WHERE id = $1
                """,
                new_player_id,
            )
        assert (inserted["age_at_reference"], inserted["age_reference_year"]) == (26, 2026)
        assert (
            await connection.fetchval(
                "SELECT birth_date FROM public.players WHERE id = $1", new_player_id
            )
            is None
        )
        assert (
            await connection.fetchval(
                "SELECT birth_date_encrypted FROM public.players WHERE id = $1",
                new_player_id,
            )
            == b"\x01\x02"
        )


@pytest.mark.asyncio
async def test_migration_017_recreates_the_public_projection_with_the_same_contract(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)

        columns = await connection.fetch(
            """
            SELECT a.attname AS name,
                   format_type(a.atttypid, a.atttypmod) AS type
            FROM pg_attribute a
            WHERE a.attrelid = $1::regclass
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            PUBLIC_VIEW,
        )
        assert [(row["name"], row["type"]) for row in columns] == (
            EXPECTED_PUBLIC_VIEW_COLUMNS
        )

        # The age is the historical age adjusted by the tournament year.
        rows = await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        )
        assert len(rows) == 1
        assert rows[0]["player_id"] == PLAYER_OLDEST_ROSTER
        assert rows[0]["public_age"] == 26

        # The projection never exposes the plaintext or the ciphertext.
        view_columns = {row["name"] for row in columns}
        assert view_columns.isdisjoint(
            {"birth_date", "birth_date_encrypted", "national_id_encrypted"}
        )

        # Owner exempt from RLS, no security_invoker, application keeps SELECT.
        owner = await connection.fetchrow(
            """
            SELECT r.rolsuper OR r.rolbypassrls AS owner_exempt,
                   c.reloptions
            FROM pg_class c
            JOIN pg_roles r ON r.oid = c.relowner
            WHERE c.oid = $1::regclass
            """,
            PUBLIC_VIEW,
        )
        assert owner["owner_exempt"] is True
        reloptions = owner["reloptions"] or []
        assert "security_barrier=true" in reloptions
        assert "security_invoker=true" not in reloptions
        assert await connection.fetchval(
            "SELECT has_table_privilege('bracket_app', $1, 'SELECT')", PUBLIC_VIEW
        ) is True

        # The classic lineups projection still resolves and returns the player.
        lineups = await connection.fetch(
            f"SELECT match_id::text, player_id::text, first_name FROM {LINEUPS_VIEW}"
        )
        assert len(lineups) == 1
        assert lineups[0]["match_id"] == MATCH_A
        assert lineups[0]["player_id"] == PLAYER_OLDEST_ROSTER
        assert lineups[0]["first_name"] == "Oldest"
        assert await connection.fetchval(
            "SELECT has_table_privilege('bracket_app', $1, 'SELECT')", LINEUPS_VIEW
        ) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup_sql", "insert_sql"),
    [
        (
            "",
            """
            INSERT INTO public.players (
                id, organization_id, first_name, last_name, document_type,
                national_id_encrypted, national_id_hmac, issuing_country,
                birth_date, created_at
            ) VALUES (
                'd0000000-0000-4000-8000-000000000001', $1, 'Future', 'Date', 'DNI',
                decode('0505', 'hex'), repeat('5', 64), 'ARG',
                CAST('2999-01-01' AS DATE), '2025-01-01 00:00:00+00'
            )
            """,
        ),
        (
            "",
            """
            INSERT INTO public.players (
                id, organization_id, first_name, last_name, document_type,
                national_id_encrypted, national_id_hmac, issuing_country,
                birth_date, created_at
            ) VALUES (
                'd0000000-0000-4000-8000-000000000002', $1, 'After', 'Creation', 'DNI',
                decode('0606', 'hex'), repeat('6', 64), 'ARG',
                CAST('2021-06-01' AS DATE), '2020-01-01 00:00:00+00'
            )
            """,
        ),
        (
            "",
            """
            INSERT INTO public.players (
                id, organization_id, first_name, last_name, document_type,
                national_id_encrypted, national_id_hmac, issuing_country,
                birth_date, created_at
            ) VALUES (
                'd0000000-0000-4000-8000-000000000003', $1, 'No', 'Roster Future', 'DNI',
                decode('0707', 'hex'), repeat('7', 64), 'ARG',
                CAST('2999-01-01' AS DATE), '2025-01-01 00:00:00+00'
            )
            """,
        ),
        (
            "ALTER TABLE public.players ALTER COLUMN birth_date DROP NOT NULL;",
            """
            INSERT INTO public.players (
                id, organization_id, first_name, last_name, document_type,
                national_id_encrypted, national_id_hmac, issuing_country,
                birth_date, created_at
            ) VALUES (
                'd0000000-0000-4000-8000-000000000004', $1, 'Null', 'Plaintext', 'DNI',
                decode('0808', 'hex'), repeat('8', 64), 'ARG',
                NULL, '2025-01-01 00:00:00+00'
            )
            """,
        ),
    ],
    ids=["future", "after_created_at", "without_roster_future", "null_plaintext"],
)
async def test_migration_017_blocks_impossible_dates_without_exposing_them(
    database_admin_url, setup_sql, insert_sql
):
    async with throwaway_database(database_admin_url) as connection:
        scenario = await seed_birth_date_scenario(connection)
        if setup_sql:
            await connection.execute(setup_sql)
        await connection.execute(insert_sql, scenario.organization_a)

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 17)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 017" in message
        assert "1 jugador" in message
        # The report identifies the row by its internal id and never exposes
        # the date or any personal value.
        assert "d0000000-0000-4000-8000-00000000000" in message
        for forbidden in (
            "2999-01-01",
            "2021-06-01",
            "Future",
            "After",
            "Null",
            "Roster",
            "Plaintext",
        ):
            assert forbidden not in message

        # No partial changes: the new columns are rolled back with 017.
        assert await connection.fetchval(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'players'
              AND column_name = ANY($1::text[])
            """,
            list(NEW_COLUMNS),
        ) == 0
        assert await connection.fetchval(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'players'
              AND column_name = 'birth_date'
            """
        ) == 1
        # The failing rows were seeded before 017 and survive untouched.
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM public.players WHERE id::text LIKE 'd0000000-%'"
            )
            == 1
        )


@pytest.mark.asyncio
async def test_migration_017_is_idempotent_in_the_intermediate_state(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)

        ages_before = await _age_rows(connection)
        view_before = await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        )
        columns_before = await connection.fetchval(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'players'
              AND column_name = ANY($1::text[])
            """,
            list(NEW_COLUMNS),
        )

        await apply_migration(connection, 17)

        assert await connection.fetchval("SELECT count(*) FROM public.players") == 4
        assert await _age_rows(connection) == ages_before
        assert ages_before[PLAYER_OLDEST_ROSTER] == (24, 2024)
        assert ages_before[PLAYER_TIE_BREAK] == (34, 2024)
        assert await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        ) == view_before
        assert (
            await connection.fetchval(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'players'
                  AND column_name = ANY($1::text[])
                """,
                list(NEW_COLUMNS),
            )
            == columns_before
            == 3
        )
        assert await _column_privilege(connection, "birth_date", "SELECT") is False
        assert await _column_privilege(connection, "birth_date", "INSERT") is False
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "INSERT")
            is True
        )
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "SELECT")
            is False
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM public.players WHERE age_at_reference IS NULL"
            )
            == 0
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM public.players WHERE age_reference_year IS NULL"
            )
            == 0
        )


@pytest.mark.asyncio
async def test_clean_database_applies_init_and_migrations_through_017(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await apply_migration(connection, 17)

        assert await connection.fetchval("SELECT count(*) FROM public.players") == 0
        definitions = {
            row["column_name"]: (row["data_type"], row["is_nullable"])
            for row in await connection.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'players'
                  AND column_name = ANY($1::text[])
                """,
                ["birth_date", *NEW_COLUMNS],
            )
        }
        assert definitions["birth_date"] == ("date", "YES")
        assert definitions["birth_date_encrypted"] == ("bytea", "YES")
        assert definitions["age_at_reference"] == ("smallint", "NO")
        assert definitions["age_reference_year"] == ("smallint", "NO")

        assert await connection.fetchval(
            f"SELECT count(*) FROM {PUBLIC_VIEW}"
        ) == 0
        columns = await connection.fetch(
            """
            SELECT a.attname AS name,
                   format_type(a.atttypid, a.atttypmod) AS type
            FROM pg_attribute a
            WHERE a.attrelid = $1::regclass
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            PUBLIC_VIEW,
        )
        assert [(row["name"], row["type"]) for row in columns] == (
            EXPECTED_PUBLIC_VIEW_COLUMNS
        )
        assert await connection.fetchval(
            "SELECT has_table_privilege('bracket_app', $1, 'SELECT')", PUBLIC_VIEW
        ) is True
        assert await _column_privilege(connection, "birth_date", "SELECT") is False
        assert await _column_privilege(connection, "birth_date", "INSERT") is False
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "SELECT")
            is False
        )
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "INSERT")
            is True
        )


# ---------------------------------------------------------------------------
# Migration 018 — closed failure, mandatory ciphertext and plaintext removal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_018_fails_closed_while_the_ciphertext_is_pending(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)
        # Only one row is already encrypted: the other three block the closure.
        await connection.execute(
            """
            UPDATE public.players
            SET birth_date_encrypted = pgp_sym_encrypt(birth_date::text, $1)
            WHERE id = $2
            """,
            T004_KEY,
            PLAYER_OLDEST_ROSTER,
        )
        encrypted_before = await _decrypted_birth_dates(connection)

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 18)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 018" in message
        assert "3 jugador" in message
        # The report never exposes a date or a personal value.
        for forbidden in ("2000-05-15", "1990-12-31", "2001-07-04", "2010-02-28"):
            assert forbidden not in message
        assert "Oldest" not in message and "Roster" not in message

        # No partial changes: the plaintext and the nullable ciphertext survive.
        assert await _column_definition(connection, "birth_date") is not None
        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["is_nullable"] == "YES"
        assert await _decrypted_birth_dates(connection) == encrypted_before
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM public.players WHERE birth_date_encrypted IS NULL"
            )
            == 3
        )
        # The migration did not grant nor revoke anything before failing.
        assert await _column_privilege(connection, "birth_date", "SELECT") is False
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "SELECT")
            is False
        )
        assert (
            await connection.fetchval(
                f"SELECT count(*) FROM {PUBLIC_VIEW}"
            )
            == 1
        )


@pytest.mark.asyncio
async def test_migration_018_closes_the_schema_after_a_complete_backfill(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)

        counts_before = await _table_counts(connection)
        plaintext_before = await _plaintext_birth_dates(connection)
        view_before = await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        )
        assert len(plaintext_before) == 4

        await _encrypt_pending_birth_dates(connection)
        await apply_migration(connection, 18)

        # The column is gone and the ciphertext is mandatory.
        assert await _column_definition(connection, "birth_date") is None
        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["data_type"] == "bytea"
        assert ciphertext["is_nullable"] == "NO"

        # Counts, identifiers and references survive. Every ciphertext still
        # decrypts to the original plaintext value.
        assert await _table_counts(connection) == counts_before
        assert await _decrypted_birth_dates(connection) == plaintext_before
        assert (
            await connection.fetchval(
                """
                SELECT count(*)
                FROM public.match_rosters mr
                JOIN public.rosters r
                  ON r.id = mr.roster_id
                 AND r.organization_id = mr.organization_id
                JOIN public.players p
                  ON p.id = mr.player_id
                 AND p.organization_id = mr.organization_id
                """
            )
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT organization_id::text FROM public.players WHERE id = $1",
                PLAYER_WITHOUT_ROSTER,
            )
            == ORG_A
        )

        # The public projection keeps its contract and its value.
        assert await _public_view_columns(connection) == EXPECTED_PUBLIC_VIEW_COLUMNS
        view_after = await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        )
        assert view_after == view_before
        assert view_after[0]["public_age"] == 26
        assert await connection.fetchval(
            "SELECT has_table_privilege('bracket_app', $1, 'SELECT')", PUBLIC_VIEW
        ) is True

        # The lineups projection still resolves without the plaintext column.
        lineups = await connection.fetch(
            f"SELECT match_id::text, player_id::text, first_name FROM {LINEUPS_VIEW}"
        )
        assert len(lineups) == 1
        assert lineups[0]["match_id"] == MATCH_A
        assert lineups[0]["player_id"] == PLAYER_OLDEST_ROSTER
        assert await connection.fetchval(
            "SELECT has_table_privilege('bracket_app', $1, 'SELECT')", LINEUPS_VIEW
        ) is True


@pytest.mark.asyncio
async def test_clean_database_applies_init_and_migrations_through_018(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await apply_migration(connection, 17)
        await apply_migration(connection, 18)

        assert await connection.fetchval("SELECT count(*) FROM public.players") == 0
        assert await _column_definition(connection, "birth_date") is None
        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["is_nullable"] == "NO"
        assert await _public_view_columns(connection) == EXPECTED_PUBLIC_VIEW_COLUMNS
        assert await connection.fetchval(f"SELECT count(*) FROM {PUBLIC_VIEW}") == 0
        assert await connection.fetchval(f"SELECT count(*) FROM {LINEUPS_VIEW}") == 0


@pytest.mark.asyncio
async def test_migration_018_blocks_a_view_that_still_depends_on_the_plaintext(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)
        await _encrypt_pending_birth_dates(connection)
        await connection.execute(
            """
            CREATE VIEW public.v_depends_on_birth_date AS
            SELECT id, birth_date FROM public.players
            """
        )

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 18)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 018" in message
        assert "v_depends_on_birth_date" in message
        assert "players.birth_date" in message

        # Nothing was dropped: both the column and the dependent view remain.
        assert await _column_definition(connection, "birth_date") is not None
        assert await connection.fetchval(
            "SELECT count(*) FROM pg_views WHERE schemaname = 'public' AND viewname = $1",
            "v_depends_on_birth_date",
        ) == 1
        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_migration_018_blocks_an_index_that_still_depends_on_the_plaintext(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)
        await _encrypt_pending_birth_dates(connection)
        await connection.execute(
            "CREATE INDEX t004_birth_date_idx ON public.players (birth_date)"
        )

        with pytest.raises(asyncpg.PostgresError) as error:
            await apply_migration(connection, 18)
        await connection.execute("ROLLBACK")

        message = str(error.value)
        assert "MIGRACION 018" in message
        assert "t004_birth_date_idx" in message
        assert "índice" in message
        assert "players.birth_date" in message

        # Nothing was dropped: the column and its index survive.
        assert await _column_definition(connection, "birth_date") is not None
        assert await connection.fetchval(
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = 't004_birth_date_idx'"
        ) == 1
        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_migration_018_leaves_the_final_application_grants(
    database_admin_url,
):
    async with throwaway_database(database_admin_url) as connection:
        scenario = await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)
        await _encrypt_pending_birth_dates(connection)
        await apply_migration(connection, 18)

        # Final column matrix from the plan: exact read and write sets.
        select_columns = {
            "id",
            "organization_id",
            "first_name",
            "last_name",
            "document_type",
            "national_id_hmac",
            "issuing_country",
            "age_at_reference",
            "age_reference_year",
            "created_at",
        }
        insert_columns = {
            "organization_id",
            "first_name",
            "last_name",
            "document_type",
            "national_id_encrypted",
            "national_id_hmac",
            "issuing_country",
            "birth_date_encrypted",
            "age_at_reference",
            "age_reference_year",
        }
        for column in select_columns:
            assert await _column_privilege(connection, column, "SELECT") is True
        for column in insert_columns:
            assert await _column_privilege(connection, column, "INSERT") is True
        for column in ("national_id_encrypted", "birth_date_encrypted"):
            assert await _column_privilege(connection, column, "SELECT") is False
        assert await _column_privilege(connection, "birth_date_encrypted", "INSERT") is True
        assert await _column_privilege(connection, "photo_url", "SELECT") is False
        assert await _column_privilege(connection, "photo_url", "INSERT") is False

        table = await connection.fetchrow(
            """
            SELECT has_table_privilege('bracket_app', $1, 'UPDATE') AS update_allowed,
                   has_table_privilege('bracket_app', $1, 'DELETE') AS delete_allowed,
                   has_table_privilege('bracket_app', $1, 'SELECT') AS select_allowed
            """,
            PLAYERS_TABLE,
        )
        assert table["update_allowed"] is False
        assert table["delete_allowed"] is False
        assert table["select_allowed"] is False
        assert await _public_column_privileges(
            connection, "birth_date_encrypted"
        ) == set()

        # RLS stays enabled and forced.
        rls = await connection.fetchrow(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'public.players'::regclass
            """
        )
        assert rls["relrowsecurity"] is True
        assert rls["relforcerowsecurity"] is True

        # The application role can insert the ciphertext and the age...
        async with _as_application_role(
            connection,
            organization_id=scenario.organization_a,
            user_id=scenario.user_a,
        ):
            new_player_id = await connection.fetchval(
                """
                INSERT INTO public.players (
                    organization_id, first_name, last_name, document_type,
                    national_id_encrypted, national_id_hmac, issuing_country,
                    birth_date_encrypted, age_at_reference, age_reference_year
                ) VALUES (
                    $1, 'After', 'Closure', 'DNI', decode('0a0a', 'hex'),
                    repeat('a', 64), 'ARG', pgp_sym_encrypt('1999-02-28', $2),
                    27, 2026
                )
                RETURNING id
                """,
                scenario.organization_a,
                T004_KEY,
            )
            inserted = await connection.fetchrow(
                """
                SELECT age_at_reference, age_reference_year
                FROM public.players
                WHERE id = $1
                """,
                new_player_id,
            )
        assert (inserted["age_at_reference"], inserted["age_reference_year"]) == (
            27,
            2026,
        )

        # ...but can never read the ciphertext, not even with SELECT *.
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            async with _as_application_role(
                connection,
                organization_id=scenario.organization_a,
                user_id=scenario.user_a,
            ):
                await connection.fetchval(
                    "SELECT birth_date_encrypted FROM public.players LIMIT 1"
                )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            async with _as_application_role(
                connection,
                organization_id=scenario.organization_a,
                user_id=scenario.user_a,
            ):
                await connection.fetchval("SELECT * FROM public.players LIMIT 1")

        # The plaintext column does not exist for anyone.
        assert await _column_definition(connection, "birth_date") is None


@pytest.mark.asyncio
async def test_migration_018_is_idempotent_on_a_direct_rerun(database_admin_url):
    async with throwaway_database(database_admin_url) as connection:
        await seed_birth_date_scenario(connection)
        await apply_migration(connection, 17)
        await _encrypt_pending_birth_dates(connection)
        await apply_migration(connection, 18)

        counts_before = await _table_counts(connection)
        view_before = await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        )
        plaintext_after = await _decrypted_birth_dates(connection)

        # Re-executing the file directly must not fail on existing objects.
        await apply_migration(connection, 18)

        assert await _table_counts(connection) == counts_before
        assert await _decrypted_birth_dates(connection) == plaintext_after
        assert await connection.fetch(
            f"SELECT tournament_id::text, player_id::text, public_age FROM {PUBLIC_VIEW}"
        ) == view_before
        assert await _column_definition(connection, "birth_date") is None
        ciphertext = await _column_definition(connection, "birth_date_encrypted")
        assert ciphertext["is_nullable"] == "NO"
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "INSERT")
            is True
        )
        assert (
            await _column_privilege(connection, "birth_date_encrypted", "SELECT")
            is False
        )
