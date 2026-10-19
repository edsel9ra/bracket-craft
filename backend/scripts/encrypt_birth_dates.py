"""Encrypt historical player birth dates in place (spec 002, RF-004).

Run between migration 017 and migration 018 as a one-off service::

    DATABASE_ADMIN_URL=postgresql+asyncpg://... \\
    PLAYER_DATA_KEY=... \\
    python -m scripts.encrypt_birth_dates

Flow:

1. Detect the schema. Without the plaintext column the final schema (018) is
   already in place and the command exits successfully doing nothing.
2. An empty player table is a no-op: there is nothing to verify or encrypt.
3. Verify ``PLAYER_DATA_KEY`` before writing: decrypt a sample encrypted
   document and compare its HMAC with the stored one. A wrong key, a tampered
   HMAC or a non-empty table without any encrypted document aborts without
   writing.
4. Reject impossible historical dates (null, future or after the player's
   creation instant in UTC) before writing anything.
5. Encrypt pending rows in deterministic batches of 500, one commit per batch,
   so a failure leaves the previous batches encrypted and the run resumable.
6. Verify that no row stays pending and that every row with plaintext decrypts
   exactly to its original value.

Logs only contain counts, batch numbers, durations and internal identifiers on
data errors: never names, documents, dates, ciphertext or the key. Database
errors are logged as the exception class and SQLSTATE only.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import get_settings

LOGGER = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500

SCHEMA_COLUMNS_SQL = text(
    """
    SELECT column_name, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'players'
      AND column_name IN ('birth_date', 'birth_date_encrypted')
    """
)

COUNT_PLAYERS_SQL = text("SELECT count(*) FROM public.players")

COUNT_DOCUMENTS_SQL = text(
    "SELECT count(*) FROM public.players WHERE national_id_encrypted IS NOT NULL"
)

SAMPLE_DOCUMENT_SQL = text(
    """
    SELECT pgp_sym_decrypt(national_id_encrypted, :player_data_key)::text
           AS national_id,
           national_id_hmac
    FROM public.players
    WHERE national_id_encrypted IS NOT NULL
    ORDER BY id
    LIMIT 1
    """
)

COUNT_PENDING_SQL = text(
    "SELECT count(*) FROM public.players WHERE birth_date_encrypted IS NULL"
)

IMPOSSIBLE_DATES_FILTER = """
    birth_date_encrypted IS NULL
    AND (
        birth_date IS NULL
        OR birth_date > CURRENT_DATE
        OR birth_date > ((created_at AT TIME ZONE 'UTC')::date)
    )
"""

COUNT_IMPOSSIBLE_DATES_SQL = text(
    f"SELECT count(*) FROM public.players WHERE {IMPOSSIBLE_DATES_FILTER}"
)

IMPOSSIBLE_DATE_IDS_SQL = text(
    f"""
    SELECT id::text
    FROM public.players
    WHERE {IMPOSSIBLE_DATES_FILTER}
    ORDER BY id
    LIMIT 20
    """
)

# One batch: the subquery picks the same deterministic set the loop would read
# (oldest ids first, at most ``batch_size``) and the update commits atomically.
ENCRYPT_BATCH_SQL = text(
    """
    UPDATE public.players
    SET birth_date_encrypted = pgp_sym_encrypt(birth_date::text, :player_data_key)
    WHERE id IN (
        SELECT id
        FROM public.players
        WHERE birth_date_encrypted IS NULL
        ORDER BY id
        LIMIT :batch_size
    )
      AND birth_date_encrypted IS NULL
    """
)

VERIFY_SQL = text(
    """
    SELECT
        count(*) FILTER (WHERE birth_date_encrypted IS NULL) AS pending,
        count(*) FILTER (
            WHERE birth_date IS NOT NULL
              AND pgp_sym_decrypt(birth_date_encrypted, :player_data_key)::date
                  <> birth_date
        ) AS mismatch
    FROM public.players
    """
)


def _sqlstate(exc: BaseException) -> str | None:
    """Return the database SQLSTATE without exposing the statement or params."""

    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


async def _columns(connection: AsyncConnection) -> dict[str, str]:
    rows = (await connection.execute(SCHEMA_COLUMNS_SQL)).mappings().all()
    return {row["column_name"]: row["is_nullable"] for row in rows}


async def _verify_key(connection: AsyncConnection, player_data_key: str) -> bool:
    """Verify the key against an encrypted document and its HMAC.

    Returns ``False`` (after logging a clear message) when the key cannot
    decrypt the sample, when the stored HMAC does not match, or when a non-empty
    table has no encrypted document to verify. The caller must abort without
    writing: there is no confirmation bypass.
    """

    document_count = (await connection.execute(COUNT_DOCUMENTS_SQL)).scalar_one()
    await connection.rollback()

    if document_count == 0:
        LOGGER.error(
            "No hay ninguna fila con documento cifrado para verificar "
            "PLAYER_DATA_KEY. El documento es obligatorio en cada jugador; "
            "revise los datos. No se escribió nada."
        )
        return False

    try:
        sample = (
            await connection.execute(
                SAMPLE_DOCUMENT_SQL, {"player_data_key": player_data_key}
            )
        ).mappings().one()
    except SQLAlchemyError as exc:
        await connection.rollback()
        LOGGER.error(
            "No se pudo descifrar el documento de prueba (%s%s): PLAYER_DATA_KEY "
            "es incorrecta o los datos están corruptos. No se escribió nada.",
            type(exc).__name__,
            f", SQLSTATE {_sqlstate(exc)}" if _sqlstate(exc) else "",
        )
        return False
    finally:
        # The read above may have opened an implicit transaction.
        await connection.rollback()

    computed = hmac.new(
        player_data_key.encode("utf-8"),
        sample["national_id"].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(computed, sample["national_id_hmac"]):
        LOGGER.error(
            "El HMAC del documento de prueba no coincide con PLAYER_DATA_KEY. "
            "No se escribió nada."
        )
        return False

    return True


async def _check_impossible_dates(connection: AsyncConnection) -> bool:
    """Return ``True`` when every pending row has a valid plaintext date."""

    bad_count = (await connection.execute(COUNT_IMPOSSIBLE_DATES_SQL)).scalar_one()
    if not bad_count:
        await connection.rollback()
        return True

    bad_ids = [
        row[0]
        for row in (await connection.execute(IMPOSSIBLE_DATE_IDS_SQL)).all()
    ]
    await connection.rollback()
    LOGGER.error(
        "Backfill abortado: %s jugador(es) con fecha de nacimiento nula, futura "
        "o posterior a su creación. Identificadores internos: %s. Corrija los "
        "datos y reintente.",
        bad_count,
        ", ".join(bad_ids),
    )
    return False


async def run(
    admin_url: str,
    player_data_key: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Encrypt the pending birth dates and return a process exit code."""

    if batch_size < 1:
        LOGGER.error("El tamaño de lote debe ser positivo.")
        return 2

    started = time.monotonic()
    engine = None
    try:
        # Build the engine inside its own guard: a malformed URL or a missing
        # async driver must not raise a traceback that echoes the credentials.
        try:
            engine = create_async_engine(admin_url)
        except Exception as exc:  # noqa: BLE001 - never expose the URL or DSN
            LOGGER.error(
                "No se pudo preparar la conexión administrativa (%s). "
                "No se registran credenciales ni valores.",
                type(exc).__name__,
            )
            return 2

        async with engine.connect() as connection:
            columns = await _columns(connection)
            await connection.rollback()

            if "birth_date" not in columns:
                if "birth_date_encrypted" not in columns:
                    LOGGER.error(
                        "El esquema no está preparado: falta birth_date_encrypted. "
                        "Aplique la migración 017."
                    )
                    return 1
                if columns["birth_date_encrypted"] == "YES":
                    LOGGER.error(
                        "Esquema inconsistente: birth_date no existe y "
                        "birth_date_encrypted es nullable. Aplique las migraciones "
                        "017 y 018 en orden."
                    )
                    return 1
                LOGGER.info(
                    "Esquema final detectado (018 aplicada): la fecha en claro ya "
                    "no existe. Nada que hacer."
                )
                return 0

            if "birth_date_encrypted" not in columns:
                LOGGER.error(
                    "El esquema no está preparado: falta birth_date_encrypted. "
                    "Aplique la migración 017."
                )
                return 1

            total = (await connection.execute(COUNT_PLAYERS_SQL)).scalar_one()
            await connection.rollback()
            if total == 0:
                LOGGER.info(
                    "La tabla de jugadores está vacía: nada que verificar ni cifrar."
                )
                return 0

            if not await _verify_key(connection, player_data_key):
                return 1

            if not await _check_impossible_dates(connection):
                return 1

            pending = (await connection.execute(COUNT_PENDING_SQL)).scalar_one()
            await connection.rollback()

        processed = 0
        batches = 0
        while True:
            async with engine.begin() as batch_connection:
                updated = (
                    await batch_connection.execute(
                        ENCRYPT_BATCH_SQL,
                        {
                            "player_data_key": player_data_key,
                            "batch_size": batch_size,
                        },
                    )
                ).rowcount or 0
                remaining = (
                    await batch_connection.execute(COUNT_PENDING_SQL)
                ).scalar_one()

            if updated == 0:
                if remaining:
                    LOGGER.error(
                        "El backfill no pudo reducir los pendientes (%s restante(s)) "
                        "y se detiene para evitar un bucle.",
                        remaining,
                    )
                    return 1
                break

            if remaining >= pending:
                LOGGER.error(
                    "El lote %s no redujo los pendientes (%s restante(s)) y se "
                    "detiene para evitar un bucle.",
                    batches + 1,
                    remaining,
                )
                return 1

            processed += updated
            batches += 1
            pending = remaining
            LOGGER.info(
                "Lote %s: %s fila(s) cifrada(s); %s pendiente(s).",
                batches,
                updated,
                remaining,
            )

        async with engine.connect() as connection:
            pending_rows, mismatch = (
                await connection.execute(
                    VERIFY_SQL, {"player_data_key": player_data_key}
                )
            ).one()
            await connection.rollback()

        elapsed = time.monotonic() - started
        if pending_rows or mismatch:
            LOGGER.error(
                "Verificación final fallida: %s pendiente(s) y %s fila(s) que no "
                "descifran a su valor original. La fecha en claro no debe eliminarse.",
                pending_rows,
                mismatch,
            )
            return 1

        LOGGER.info(
            "Backfill completado: %s fila(s) cifrada(s), %s pendiente(s), %s "
            "lote(s) en %.2f s.",
            processed,
            pending_rows,
            batches,
            elapsed,
        )
        return 0

    except SQLAlchemyError as exc:
        elapsed = time.monotonic() - started
        LOGGER.error(
            "Backfill abortado por un error de base de datos (%s%s) tras %.2f s. "
            "No se registran valores.",
            type(exc).__name__,
            f", SQLSTATE {_sqlstate(exc)}" if _sqlstate(exc) else "",
            elapsed,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - never expose the URL or DSN
        LOGGER.error(
            "Backfill abortado por un error inesperado (%s). No se registran "
            "credenciales ni valores.",
            type(exc).__name__,
        )
        return 1
    finally:
        if engine is not None:
            await engine.dispose()


def main() -> int:
    """Read the environment and run the backfill.

    ``DATABASE_ADMIN_URL`` is mandatory. ``PLAYER_DATA_KEY`` is read through the
    application settings so the production guard rejects development defaults.
    """

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        player_data_key = get_settings().player_data_key
    except Exception as exc:  # noqa: BLE001 - the settings guard must fail closed
        LOGGER.error(
            "Configuración inválida: no se pudo cargar PLAYER_DATA_KEY (%s).",
            type(exc).__name__,
        )
        return 2

    admin_url = os.environ.get("DATABASE_ADMIN_URL", "").strip()
    if not admin_url:
        LOGGER.error(
            "DATABASE_ADMIN_URL es obligatorio para ejecutar el backfill con la "
            "conexión administrativa."
        )
        return 2

    try:
        return asyncio.run(run(admin_url, player_data_key))
    except Exception as exc:  # noqa: BLE001 - never expose the URL or DSN
        LOGGER.error(
            "Backfill abortado antes de completar (%s). No se registran "
            "credenciales ni valores.",
            type(exc).__name__,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
