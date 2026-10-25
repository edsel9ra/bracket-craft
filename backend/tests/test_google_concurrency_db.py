"""Concurrencia del inicio de sesión con Google (RF-13, RF-22, RNF-11).

Pruebas opt-in que construyen una base desechable con ``init`` + 001…024 y un
rol dedicado que hereda ``bracket_app`` (patrón de ``test_concurrency_006.py``):
el rol compartido nunca se modifica y los datos se borran al terminar.

La carrera es determinista, sin ``sleep``: dos tareas reales y dos conexiones.
La primera se detiene justo después de insertar la cuenta y la identidad, pero
**antes de confirmar**, mediante un doble de ``create_user_session``; la segunda
solo arranca entonces, de modo que su lectura inicial no ve nada y su ``INSERT``
choca con la unicidad cuando la primera confirma. Así se ejerce el segundo pase
de ``resolve_login``:

* misma identidad → una cuenta, una identidad y una sesión por intento;
* mismo correo con otro sujeto → una cuenta y el segundo recibe
  ``ACCOUNT_EXISTS_GOOGLE_ONLY``;
* dos conflictos seguidos → ``GOOGLE_IDENTITY_INVALID`` sin bucle.
"""

from __future__ import annotations

import asyncio
import secrets
import sys
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.identity.account_rules import LoginOutcome
from app.modules.identity.google_accounts import (
    LoginRejected,
    LoginResult,
    resolve_login,
)
from app.modules.identity.google_claims import GoogleIdentity
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)

RACE_TIMEOUT_SECONDS = 30


@pytest.fixture
async def google_engine(database_admin_url):
    """Throwaway database at init + 001…024 with a dedicated application role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc009_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1, last=24)
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')

        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        yield engine, admin
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.close()
        await drop_database(database_admin_url, database)
        cleaner = await connect(database_admin_url)
        try:
            await cleaner.execute(f'DROP ROLE IF EXISTS "{role_name}"')
        finally:
            await cleaner.close()


def identity(*, subject: str, email: str, name: str | None = None) -> GoogleIdentity:
    return GoogleIdentity(
        subject=subject, email=email, email_verified=True, name=name
    )


async def _race(engine, monkeypatch, first_identity, second_identity):
    """Run both logins with a deterministic overlap; return their outcomes.

    The first attempt is paused after inserting the account and its identity
    (inside ``create_user_session``, before the commit). The second starts only
    then, so its initial read misses the uncommitted rows and its insert waits
    for the first commit: it is the one that must take the second pass.
    """

    from app.modules.identity import google_accounts

    inserted = asyncio.Event()
    second_selected = asyncio.Event()
    tasks: dict[str, asyncio.Task] = {}

    original_decide = google_accounts.decide_existing_account
    original_create_session = google_accounts.create_user_session

    def decide_spy(**kwargs):
        outcome = original_decide(**kwargs)
        if asyncio.current_task() is tasks.get("second"):
            # The second transaction has already read (and decided) without
            # seeing the first: let the first commit and collide.
            second_selected.set()
        return outcome

    async def create_session_spy(db, user_id):
        if asyncio.current_task() is tasks.get("first"):
            inserted.set()
            await second_selected.wait()
        return await original_create_session(db, user_id)

    monkeypatch.setattr(google_accounts, "decide_existing_account", decide_spy)
    monkeypatch.setattr(google_accounts, "create_user_session", create_session_spy)

    async def run_first():
        tasks["first"] = asyncio.current_task()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                return await resolve_login(session, first_identity)
        except Exception as exc:  # captured for the assertions
            return exc

    async def run_second():
        tasks["second"] = asyncio.current_task()
        await inserted.wait()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                return await resolve_login(session, second_identity)
        except Exception as exc:  # captured for the assertions
            return exc

    return await asyncio.gather(run_first(), run_second())


# ---------------------------------------------------------------------------
# Misma identidad simultánea: una cuenta y una identidad
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_identity_concurrently_creates_one_account_and_one_identity(
    google_engine, monkeypatch
):
    engine, admin = google_engine
    subject = f"google-subject-{uuid4().hex}"
    email = f"race.{uuid4().hex}@example.test"
    person = identity(subject=subject, email=email, name="  Persona Concurrente  ")

    first, second = await asyncio.wait_for(
        _race(engine, monkeypatch, person, person), timeout=RACE_TIMEOUT_SECONDS
    )

    assert isinstance(first, LoginResult), first
    assert isinstance(second, LoginResult), second
    # One account wins the race; the other lands on the very same account,
    # either through the second pass or through the winning identity.
    assert first.user_id == second.user_id
    assert first.outcome is LoginOutcome.CREATE
    assert second.outcome is LoginOutcome.LINKED
    assert first.organization_id is None
    assert second.organization_id is None

    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.users WHERE LOWER(email) = LOWER($1)", email
        )
        == 1
    )
    assert (
        await admin.fetchval(
            """
            SELECT count(*) FROM public.auth_identities
            WHERE provider = 'google' AND provider_subject = $1
            """,
            subject,
        )
        == 1
    )
    assert (
        await admin.fetchval(
            """
            SELECT count(*) FROM public.auth_identities
            WHERE user_id = $1 AND provider = 'google'
            """,
            first.user_id,
        )
        == 1
    )
    # Both valid attempts have their own session for the same account.
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.user_sessions WHERE user_id = $1",
            first.user_id,
        )
        == 2
    )
    assert (
        await admin.fetchval(
            "SELECT full_name FROM public.users WHERE id = $1", first.user_id
        )
        == "Persona Concurrente"
    )


# ---------------------------------------------------------------------------
# Mismo correo con distinto sujeto: una cuenta y el segundo rechazado
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_email_with_another_subject_keeps_one_account_and_rejects(
    google_engine, monkeypatch
):
    engine, admin = google_engine
    email = f"race.{uuid4().hex}@example.test"
    first_subject = f"google-subject-{uuid4().hex}"
    second_subject = f"google-subject-{uuid4().hex}"

    first, second = await asyncio.wait_for(
        _race(
            engine,
            monkeypatch,
            identity(subject=first_subject, email=email, name="Primera"),
            identity(subject=second_subject, email=email.upper(), name="Segunda"),
        ),
        timeout=RACE_TIMEOUT_SECONDS,
    )

    assert isinstance(first, LoginResult), first
    assert first.outcome is LoginOutcome.CREATE
    assert isinstance(second, LoginRejected), second
    assert second.code == LoginOutcome.GOOGLE_ONLY_ACCOUNT.value

    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.users WHERE LOWER(email) = LOWER($1)", email
        )
        == 1
    )
    assert (
        await admin.fetchval(
            """
            SELECT count(*) FROM public.auth_identities
            WHERE provider = 'google' AND provider_subject = $1
            """,
            first_subject,
        )
        == 1
    )
    assert (
        await admin.fetchval(
            """
            SELECT count(*) FROM public.auth_identities
            WHERE provider = 'google' AND provider_subject = $1
            """,
            second_subject,
        )
        == 0
    )
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM public.user_sessions WHERE user_id = $1",
            first.user_id,
        )
        == 1
    )


# ---------------------------------------------------------------------------
# Un segundo conflicto falla cerrado: nunca bucle ni 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_conflict_fails_closed_after_exactly_two_attempts(
    monkeypatch,
):
    from app.modules.identity import google_accounts

    calls = 0

    async def conflicting_attempt(db, identity_value, email):
        nonlocal calls
        calls += 1
        raise IntegrityError(
            "INSERT INTO public.users", {}, Exception("duplicate key value")
        )

    monkeypatch.setattr(google_accounts, "_resolve_login_once", conflicting_attempt)

    with pytest.raises(LoginRejected) as error:
        await resolve_login(
            None,
            identity(
                subject=f"google-subject-{uuid4().hex}",
                email=f"race.{uuid4().hex}@example.test",
            ),
        )

    assert error.value.outcome is LoginOutcome.INCONSISTENT
    assert error.value.code == LoginOutcome.INCONSISTENT.value
    assert calls == 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
