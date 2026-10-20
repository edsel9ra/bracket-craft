"""Opt-in PostgreSQL checks for the signing transaction boundary (RF-002, RF-010).

T003 covers the photo-signing boundary with a real session: after the read or
write transaction closes, ``session.in_transaction()`` is false and the backend
is ``idle`` (not ``idle in transaction``) while the fake signer runs. T007
amplifies this module with the ``SHOW`` checks for the statement and
idle-in-transaction timeouts.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.storage import SignedUrls
from app.modules.tournaments.photos import sign_photo_rows
from db_helpers import application_database_url, database_tests_enabled

pytestmark = pytest.mark.skipif(
    not database_tests_enabled(),
    reason="RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas",
)


class RecordingStorage:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.transaction_states: list[bool] = []

    async def signed_urls(self, keys, expires_seconds=None):
        self.transaction_states.append(self.session.in_transaction())
        return SignedUrls(urls={key: f"https://signed.example/{key}" for key in keys})


async def test_photo_signing_happens_after_the_read_transaction_is_idle():
    engine = create_async_engine(application_database_url(), pool_pre_ping=True)
    observer = create_async_engine(application_database_url(), pool_pre_ping=True)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        async with session.begin():
            backend_pid = (
                await session.execute(text("SELECT pg_backend_pid()"))
            ).scalar_one()
            row = dict(
                (
                    await session.execute(
                        text(
                            "SELECT CAST(:key AS TEXT) AS photo_object_key,"
                            " TRUE AS photo_consent"
                        ),
                        {"key": "private/organizations/org/rosters/roster/photo.jpg"},
                    )
                )
                .mappings()
                .one()
            )
        assert session.in_transaction() is False

        storage = RecordingStorage(session)
        await sign_photo_rows(
            [row], key_field="photo_object_key", policy="error", storage=storage
        )

        assert storage.transaction_states == [False]
        async with observer.connect() as look:
            state = (
                await look.execute(
                    text("SELECT state FROM pg_stat_activity WHERE pid = :pid"),
                    {"pid": backend_pid},
                )
            ).scalar_one()
        assert state == "idle"
    finally:
        await session.close()
        await engine.dispose()
        await observer.dispose()


async def test_application_engine_applies_the_server_timeouts():
    from app.core.database import engine as application_engine

    async with application_engine.connect() as connection:
        statement_timeout = (
            await connection.execute(text("SHOW statement_timeout"))
        ).scalar_one()
        idle_timeout = (
            await connection.execute(
                text("SHOW idle_in_transaction_session_timeout")
            )
        ).scalar_one()

    assert statement_timeout == "15s"
    assert idle_timeout == "30s"
