"""Backfill command ``scripts.encrypt_birth_dates`` (RF-004).

Every database test builds a throwaway PostgreSQL database at init + 001-016
with the shared scenario of the 017 tests, replaces the placeholder documents
with real ciphertext/HMAC pairs and applies the real 017 migration. The command
then runs with the administrator URL against that same throwaway database.

The suite is opt-in (``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL``); the
three ``main()`` tests are pure unit tests and run without a database.
"""

from __future__ import annotations

import asyncio
import logging
import types
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from sqlalchemy import text

from birth_date_migration_helpers import (
    ORG_A,
    PLAYER_OLDEST_ROSTER,
    PLAYER_TIE_BREAK,
    PLAYER_WITHOUT_ROSTER,
    apply_migration,
    migration_environment,
    seed_birth_date_scenario,
    throwaway_database,
)
from scripts import encrypt_birth_dates

LOGGER_NAME = "scripts.encrypt_birth_dates"

TEST_KEY = "test-player-data-key-with-at-least-32-characters"
WRONG_KEY = "wrong-player-data-key-with-at-least-32-characters"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _set_valid_documents(connection, key: str = TEST_KEY) -> None:
    """Replace the scenario placeholders with ciphertext/HMAC for ``key``."""

    await connection.execute(
        """
        UPDATE public.players
        SET national_id_encrypted = pgp_sym_encrypt('BC-BACKFILL-' || id::text, $1),
            national_id_hmac = encode(
                hmac('BC-BACKFILL-' || id::text, $1, 'sha256'), 'hex'
            )
        """,
        key,
    )


async def _pending(connection) -> int:
    return await connection.fetchval(
        "SELECT count(*) FROM public.players WHERE birth_date_encrypted IS NULL"
    )


async def _mismatched_ciphertexts(connection, key: str = TEST_KEY) -> int:
    return await connection.fetchval(
        """
        SELECT count(*)
        FROM public.players
        WHERE birth_date IS NOT NULL
          AND pgp_sym_decrypt(birth_date_encrypted, $1)::date <> birth_date
        """,
        key,
    )


@asynccontextmanager
async def _prepared(admin_url: str, *, seed: bool = True):
    """Yield a connection in the 017 state and the admin URL of that database."""

    async with throwaway_database(admin_url) as connection:
        if seed:
            await seed_birth_date_scenario(connection)
            await _set_valid_documents(connection)
        await apply_migration(connection, 17)
        database = await connection.fetchval("SELECT current_database()")
        url = migration_environment(admin_url, database)["DATABASE_ADMIN_URL"]
        yield connection, url


async def _insert_legacy_player(
    connection,
    key: str = TEST_KEY,
    *,
    index: int = 1,
    birth_date: str | None = "2000-01-01",
    created_at: str = "2025-01-01 00:00:00+00",
) -> str:
    """Insert one pending player with its own encrypted document."""

    return await connection.fetchval(
        """
        INSERT INTO public.players (
            organization_id, first_name, last_name, document_type,
            national_id_encrypted, national_id_hmac, issuing_country,
            birth_date, created_at, age_at_reference, age_reference_year
        ) VALUES (
            $1, 'Legacy', 'Player', 'DNI',
            pgp_sym_encrypt('BC-EXTRA-' || $2::text, $3),
            encode(hmac('BC-EXTRA-' || $2::text, $3, 'sha256'), 'hex'),
            'ARG', CAST($4::text AS DATE), CAST($5::text AS timestamptz), 25, 2025
        )
        RETURNING id::text
        """,
        ORG_A,
        str(index),
        key,
        birth_date,
        created_at,
    )


async def _insert_legacy_players(connection, count: int, key: str = TEST_KEY) -> None:
    """Insert ``count`` pending players in one statement for the batch test."""

    await connection.execute(
        """
        INSERT INTO public.players (
            organization_id, first_name, last_name, document_type,
            national_id_encrypted, national_id_hmac, issuing_country,
            birth_date, created_at, age_at_reference, age_reference_year
        )
        SELECT
            $1, 'Bulk', 'Player ' || i, 'DNI',
            pgp_sym_encrypt('BC-BULK-' || i, $2),
            encode(hmac('BC-BULK-' || i, $2, 'sha256'), 'hex'),
            'ARG', DATE '2000-01-01', TIMESTAMPTZ '2025-01-01 00:00:00+00',
            25, 2025
        FROM generate_series(1, $3) AS i
        """,
        ORG_A,
        key,
        count,
    )


# ---------------------------------------------------------------------------
# Key verification and full backfill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_key_encrypts_every_pending_row_and_verifies_the_round_trip(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url) as (connection, url):
        assert await _pending(connection) == 4

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 0
        assert await _pending(connection) == 0
        assert await _mismatched_ciphertexts(connection) == 0
        # The original plaintext is preserved byte-for-byte after decryption.
        assert await connection.fetchval(
            """
            SELECT pgp_sym_decrypt(birth_date_encrypted, $1)::date
            FROM public.players
            WHERE id = $2
            """,
            TEST_KEY,
            UUID(PLAYER_OLDEST_ROSTER),
        ) == await connection.fetchval(
            "SELECT birth_date FROM public.players WHERE id = $1",
            UUID(PLAYER_OLDEST_ROSTER),
        )
        assert "4 fila(s) cifrada(s)" in caplog.text


@pytest.mark.asyncio
async def test_leap_day_round_trip_preserves_the_exact_date_and_age(
    database_admin_url, caplog
):
    """RF-001/RF-011: 29 February survives encryption and keeps its age."""

    async with _prepared(database_admin_url) as (connection, url):
        player_id = await _insert_legacy_player(
            connection,
            index=2000,
            birth_date="2000-02-29",
            created_at="2025-06-01 00:00:00+00",
        )

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await encrypt_birth_dates.run(url, TEST_KEY) == 0

        row = await connection.fetchrow(
            """
            SELECT pgp_sym_decrypt(birth_date_encrypted, $1)::date::text AS birth_date,
                   age_at_reference, age_reference_year
            FROM public.players
            WHERE id = $2
            """,
            TEST_KEY,
            UUID(player_id),
        )
        assert row["birth_date"] == "2000-02-29"
        assert (row["age_at_reference"], row["age_reference_year"]) == (25, 2025)
        # The day and month never reach the logs.
        assert "2000-02-29" not in caplog.text


@pytest.mark.asyncio
async def test_wrong_key_aborts_before_writing_anything(database_admin_url, caplog):
    async with _prepared(database_admin_url) as (connection, url):
        before = await _pending(connection)

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, WRONG_KEY)

        assert exit_code == 1
        assert await _pending(connection) == before
        assert "PLAYER_DATA_KEY" in caplog.text
        # The failing decrypt is a database error: no value or key leaks.
        assert WRONG_KEY not in caplog.text
        assert "2000-05-15" not in caplog.text
        assert "Oldest" not in caplog.text


@pytest.mark.asyncio
async def test_tampered_hmac_aborts_before_writing_anything(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url) as (connection, url):
        await connection.execute(
            """
            UPDATE public.players
            SET national_id_hmac = encode(
                hmac('tampered-' || id::text, 'not-the-key', 'sha256'), 'hex'
            )
            """
        )
        before = await _pending(connection)

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 1
        assert await _pending(connection) == before
        assert "hmac" in caplog.text.lower()


@pytest.mark.asyncio
async def test_rows_without_encrypted_document_abort_without_confirmation(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url) as (connection, url):
        await connection.execute(
            "ALTER TABLE public.players ALTER COLUMN national_id_encrypted DROP NOT NULL"
        )
        await connection.execute(
            "UPDATE public.players SET national_id_encrypted = NULL"
        )

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await encrypt_birth_dates.run(url, TEST_KEY) == 1
        assert "PLAYER_DATA_KEY" in caplog.text
        assert "documento cifrado" in caplog.text
        # There is no confirmation bypass: the pending rows stay untouched.
        assert "CONFIRM_UNVERIFIED_KEY" not in caplog.text
        assert await _pending(connection) == 4


# ---------------------------------------------------------------------------
# No-op branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_player_table_is_a_noop_without_confirmation(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url, seed=False) as (connection, url):
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 0
        assert await connection.fetchval("SELECT count(*) FROM public.players") == 0
        assert "vacía" in caplog.text


@pytest.mark.asyncio
async def test_after_the_final_schema_the_command_exits_successfully(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url, seed=False) as (connection, url):
        # Simulate the post-018 schema: no plaintext column and a mandatory
        # ciphertext column (empty table, so NOT NULL is satisfiable).
        await connection.execute(
            "ALTER TABLE public.players ALTER COLUMN birth_date_encrypted SET NOT NULL"
        )
        await connection.execute("ALTER TABLE public.players DROP COLUMN birth_date")

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 0
        assert "final" in caplog.text.lower()
        assert await connection.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'players' "
            "AND column_name = 'birth_date'"
        ) == 0


@pytest.mark.asyncio
async def test_missing_017_is_reported_as_an_error(database_admin_url, caplog):
    async with throwaway_database(database_admin_url) as connection:
        database = await connection.fetchval("SELECT current_database()")
        url = migration_environment(database_admin_url, database)["DATABASE_ADMIN_URL"]

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 1
        assert "017" in caplog.text


# ---------------------------------------------------------------------------
# Batches, resumption and idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_more_than_500_rows_are_encrypted_in_several_batches(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url) as (connection, url):
        await _insert_legacy_players(connection, 600)

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 0
        assert await connection.fetchval("SELECT count(*) FROM public.players") == 604
        assert await _pending(connection) == 0
        assert await _mismatched_ciphertexts(connection) == 0
        assert "Lote 1" in caplog.text
        assert "Lote 2" in caplog.text
        assert "604 fila(s) cifrada(s)" in caplog.text


@pytest.mark.asyncio
async def test_second_run_does_not_reencrypt_anything(database_admin_url, caplog):
    async with _prepared(database_admin_url) as (connection, url):
        assert await encrypt_birth_dates.run(url, TEST_KEY) == 0
        ciphertexts = {
            row["id"]: row["birth_date_encrypted"]
            for row in await connection.fetch(
                "SELECT id, birth_date_encrypted FROM public.players"
            )
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 0
        assert {
            row["id"]: row["birth_date_encrypted"]
            for row in await connection.fetch(
                "SELECT id, birth_date_encrypted FROM public.players"
            )
        } == ciphertexts
        assert "0 fila(s) cifrada(s)" in caplog.text
        assert "Lote" not in caplog.text


@pytest.mark.asyncio
async def test_resumption_only_processes_pending_rows(database_admin_url, caplog):
    async with _prepared(database_admin_url) as (connection, url):
        await connection.execute(
            """
            UPDATE public.players
            SET birth_date_encrypted = pgp_sym_encrypt(birth_date::text, $1)
            WHERE id = ANY($2::uuid[])
            """,
            TEST_KEY,
            [UUID(PLAYER_OLDEST_ROSTER), UUID(PLAYER_TIE_BREAK)],
        )
        preserved = await connection.fetchval(
            "SELECT birth_date_encrypted FROM public.players WHERE id = $1",
            UUID(PLAYER_OLDEST_ROSTER),
        )
        assert await _pending(connection) == 2

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 0
        assert await _pending(connection) == 0
        assert await _mismatched_ciphertexts(connection) == 0
        assert (
            await connection.fetchval(
                "SELECT birth_date_encrypted FROM public.players WHERE id = $1",
                UUID(PLAYER_OLDEST_ROSTER),
            )
            == preserved
        )
        assert "2 fila(s) cifrada(s)" in caplog.text


@pytest.mark.asyncio
async def test_a_failure_mid_run_keeps_previous_batches_and_can_resume(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url) as (connection, url):
        # Fail the second row (ids are ordered deterministically) so the first
        # one-row batch must already be committed when the command aborts.
        await connection.execute(
            """
            CREATE FUNCTION public.t003_fail_second_player() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.id = 'c0000000-0000-4000-8000-000000000002'::uuid THEN
                    RAISE EXCEPTION 'forced failure for the resumption test';
                END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER t003_fail_second
                BEFORE UPDATE ON public.players
                FOR EACH ROW EXECUTE FUNCTION public.t003_fail_second_player();
            """
        )

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await encrypt_birth_dates.run(url, TEST_KEY, batch_size=1) == 1

        assert (
            await connection.fetchval(
                "SELECT birth_date_encrypted IS NOT NULL FROM public.players "
                "WHERE id = $1",
                UUID(PLAYER_OLDEST_ROSTER),
            )
            is True
        )
        assert (
            await connection.fetchval(
                "SELECT birth_date_encrypted IS NULL FROM public.players "
                "WHERE id = $1",
                UUID(PLAYER_TIE_BREAK),
            )
            is True
        )
        assert await _pending(connection) == 3
        # The database error is logged without its statement, params or values.
        assert "forced failure" not in caplog.text
        assert "2000-05-15" not in caplog.text

        # Removing the failure lets the same command resume from the pending rows.
        await connection.execute(
            "DROP TRIGGER t003_fail_second ON public.players; "
            "DROP FUNCTION public.t003_fail_second_player();"
        )
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await encrypt_birth_dates.run(url, TEST_KEY, batch_size=1) == 0

        assert await _pending(connection) == 0
        assert await _mismatched_ciphertexts(connection) == 0
        assert "3 fila(s) cifrada(s)" in caplog.text


# ---------------------------------------------------------------------------
# Data errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_row_without_plaintext_fails_and_reports_the_row(
    database_admin_url, caplog
):
    async with _prepared(database_admin_url) as (connection, url):
        player_id = await _insert_legacy_player(
            connection, index=9001, birth_date=None
        )
        before = await _pending(connection)

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 1
        assert await _pending(connection) == before
        assert "fecha" in caplog.text.lower()
        assert player_id in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("birth_date", "created_at"),
    [
        ("2999-01-01", "2025-01-01 00:00:00+00"),
        ("2021-06-01", "2020-01-01 00:00:00+00"),
    ],
    ids=["future", "after_created_at"],
)
async def test_impossible_dates_block_the_backfill_before_writing(
    database_admin_url, caplog, birth_date, created_at
):
    async with _prepared(database_admin_url) as (connection, url):
        # The row has no roster: the rule also covers players without rosters.
        player_id = await _insert_legacy_player(
            connection,
            index=9002,
            birth_date=birth_date,
            created_at=created_at,
        )
        before = await _pending(connection)

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 1
        assert await _pending(connection) == before
        assert player_id in caplog.text
        assert birth_date not in caplog.text


@pytest.mark.asyncio
async def test_a_batch_that_does_not_reduce_pending_rows_fails_instead_of_looping(
    database_admin_url, caplog, monkeypatch
):
    async with _prepared(database_admin_url) as (connection, url):
        before = await _pending(connection)
        monkeypatch.setattr(
            encrypt_birth_dates,
            "ENCRYPT_BATCH_SQL",
            text(
                "UPDATE public.players "
                "SET birth_date_encrypted = birth_date_encrypted "
                "WHERE FALSE"
            ),
        )

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            exit_code = await encrypt_birth_dates.run(url, TEST_KEY)

        assert exit_code == 1
        assert await _pending(connection) == before
        assert "reducir" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Logs never contain PII or the key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logs_only_contain_counts_batches_and_duration(database_admin_url, caplog):
    async with _prepared(database_admin_url) as (connection, url):
        ciphertext = await connection.fetchval(
            "SELECT national_id_encrypted FROM public.players WHERE id = $1",
            UUID(PLAYER_OLDEST_ROSTER),
        )
        birth_ciphertext = await connection.fetchval(
            "SELECT pgp_sym_encrypt(birth_date::text, $1) "
            "FROM public.players WHERE id = $2",
            TEST_KEY,
            UUID(PLAYER_OLDEST_ROSTER),
        )

        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await encrypt_birth_dates.run(url, TEST_KEY) == 0

        logged = caplog.text
        assert TEST_KEY not in logged
        assert ciphertext.hex() not in logged
        assert birth_ciphertext.hex() not in logged
        for forbidden in (
            "2000-05-15",
            "Oldest",
            "Roster",
            "No",
            "Tie",
            "BC-BACKFILL",
            "BC-EXTRA",
            ORG_A,
            PLAYER_WITHOUT_ROSTER,
        ):
            assert forbidden not in logged


# ---------------------------------------------------------------------------
# Entry point (no database needed)
# ---------------------------------------------------------------------------


def test_run_does_not_echo_an_invalid_admin_url(caplog):
    """RNF-005: a bad DSN must not leak the URL or its credentials in the log."""

    admin_url = "postgresql+asyncpg://admin:sensitive-password@[invalid/db"

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        exit_code = asyncio.run(encrypt_birth_dates.run(admin_url, TEST_KEY))

    assert exit_code in (1, 2)
    assert "sensitive-password" not in caplog.text
    assert admin_url not in caplog.text
    assert "Traceback" not in caplog.text


def test_main_requires_database_admin_url(monkeypatch, caplog):
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)
    monkeypatch.setattr(
        encrypt_birth_dates,
        "get_settings",
        lambda: types.SimpleNamespace(player_data_key=TEST_KEY),
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        assert encrypt_birth_dates.main() == 2

    assert "DATABASE_ADMIN_URL" in caplog.text


def test_main_fails_closed_when_the_configuration_guard_rejects_the_key(
    monkeypatch, caplog
):
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql+asyncpg://admin@127.0.0.1/db")

    def failing_settings():
        raise ValueError("PLAYER_DATA_KEY debe cambiarse antes de ejecutar")

    monkeypatch.setattr(encrypt_birth_dates, "get_settings", failing_settings)

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        assert encrypt_birth_dates.main() == 2

    assert "PLAYER_DATA_KEY" in caplog.text


def test_main_passes_the_admin_url_and_configured_key_to_run(monkeypatch):
    admin_url = "postgresql+asyncpg://admin@127.0.0.1:5432/throwaway"
    monkeypatch.setenv("DATABASE_ADMIN_URL", admin_url)
    monkeypatch.setattr(
        encrypt_birth_dates,
        "get_settings",
        lambda: types.SimpleNamespace(player_data_key=TEST_KEY),
    )
    captured: dict[str, str] = {}

    def fake_run(url: str, player_data_key: str):
        captured["url"] = url
        captured["key"] = player_data_key

        async def result() -> int:
            return 0

        return result()

    monkeypatch.setattr(encrypt_birth_dates, "run", fake_run)

    assert encrypt_birth_dates.main() == 0
    assert captured == {"url": admin_url, "key": TEST_KEY}
