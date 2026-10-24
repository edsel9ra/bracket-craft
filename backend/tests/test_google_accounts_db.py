"""Resolución del inicio de sesión con Google en base real (RF-10, RF-12, RF-26, RF-27).

Pruebas opt-in (``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL``): usan el rol
de aplicación y una transacción externa que se revierte al terminar, igual que
el resto de la suite con base. ``resolve_login`` abre su propia transacción, así
que la prueba le entrega un envoltorio que convierte ``begin()`` en un
``SAVEPOINT`` dentro de la transacción revertida: se ejecuta el código real sin
dejar filas.

Se comprueban el alta (nombre recortado, derivado del correo o neutro), la
reutilización de la cuenta vinculada aunque el proveedor cambie las mayúsculas
del correo, la organización inicial del orden estable, la sesión emitida y que
el camino de Google no escribe membresías ni roles. Ninguna prueba inventa
resultados: sin base, se omiten.
"""

from __future__ import annotations

import secrets
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import set_rls_context
from app.core.security import create_user_session, decode_access_token_claims
from app.modules.identity.account_rules import LinkOutcome, LoginOutcome
from app.modules.identity.google_accounts import (
    LinkRejected,
    LoginRejected,
    SessionAccountInvalid,
    _classify_link_conflict,
    link_identity,
    resolve_login,
)
from app.modules.identity.google_claims import (
    DEFAULT_DISPLAY_NAME,
    GoogleIdentity,
)
from db_helpers import create_test_organization, create_test_user
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)


class SavepointSession:
    """Delegates to the test session, turning ``begin()`` into a savepoint."""

    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


def identity(**overrides) -> GoogleIdentity:
    values = {
        "subject": f"google-subject-{uuid4().hex}",
        "email": f"google-{uuid4().hex}@example.test",
        "email_verified": True,
        "name": "Persona de Google",
    }
    values.update(overrides)
    return GoogleIdentity(**values)


async def insert_user(
    session, *, email: str, full_name: str, password_hash: str | None = None
) -> UUID:
    result = await session.execute(
        text("""
            INSERT INTO public.users (email, password_hash, full_name)
            VALUES (:email, :password_hash, :full_name)
            RETURNING id
        """),
        {"email": email, "password_hash": password_hash, "full_name": full_name},
    )
    return result.scalar_one()


async def insert_identity(session, *, user_id: UUID, subject: str) -> None:
    await session.execute(
        text("""
            INSERT INTO public.auth_identities (user_id, provider, provider_subject)
            VALUES (:user_id, 'google', :subject)
        """),
        {"user_id": user_id, "subject": subject},
    )


async def stored_user(session, *, email: str) -> dict | None:
    result = await session.execute(
        text("""
            SELECT id, email, password_hash, full_name, is_active
            FROM public.users
            WHERE LOWER(email) = LOWER(:email)
        """),
        {"email": email},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def count_rows(session, sql: str, **params) -> int:
    return (await session.execute(text(sql), params)).scalar_one()


async def membership_counts(
    session, *, user_id: UUID, organization_ids: list[UUID]
) -> dict[str, int]:
    """Count membership and role rows visible for the user in each organization."""

    counts: dict[str, int] = {}
    for organization_id in organization_ids:
        await set_rls_context(session, organization_id, user_id)
        counts[str(organization_id)] = await count_rows(
            session,
            """
            SELECT count(*)
            FROM public.organization_users
            WHERE user_id = :user_id
            """,
            user_id=user_id,
        )
        counts[str(organization_id) + ":roles"] = await count_rows(
            session,
            """
            SELECT count(*)
            FROM public.organization_user_roles
            WHERE organization_user_id IN (
                SELECT id FROM public.organization_users WHERE user_id = :user_id
            )
            """,
            user_id=user_id,
        )
    await set_rls_context(session, None, user_id)
    return counts


# ---------------------------------------------------------------------------
# Alta de una cuenta nueva (RF-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_login_creates_the_account_with_the_trimmed_name(db_session):
    session = SavepointSession(db_session)
    person = identity(
        email=f"  Ana.{uuid4().hex}@Example.Test  ",
        name="  Ana Pérez  ",
    )
    expected_email = person.email.strip().lower()

    result = await resolve_login(session, person)

    assert result.outcome is LoginOutcome.CREATE
    assert result.user_id is not None
    assert result.organization_id is None
    assert result.session_token

    user = await stored_user(db_session, email=expected_email)
    assert user is not None
    assert user["email"] == expected_email
    assert user["full_name"] == "Ana Pérez"
    assert user["password_hash"] is None
    assert user["is_active"] is True

    assert (
        await count_rows(
            db_session,
            """
            SELECT count(*)
            FROM public.auth_identities
            WHERE user_id = :user_id
              AND provider = 'google'
              AND provider_subject = :subject
            """,
            user_id=result.user_id,
            subject=person.subject,
        )
        == 1
    )

    # The token is the existing session token and there is exactly one session.
    claims = decode_access_token_claims(result.session_token)
    assert claims["sub"] == str(result.user_id)
    session_rows = await db_session.execute(
        text("SELECT id FROM public.user_sessions WHERE user_id = :user_id"),
        {"user_id": result.user_id},
    )
    assert [str(row["id"]) for row in session_rows.mappings().all()] == [claims["jti"]]

    # The Google path never writes memberships or roles (RF-26).
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.organization_users WHERE user_id = :user_id",
            user_id=result.user_id,
        )
        == 0
    )
    assert (
        await count_rows(
            db_session,
            """
            SELECT count(*)
            FROM public.organization_user_roles
            WHERE organization_user_id IN (
                SELECT id FROM public.organization_users WHERE user_id = :user_id
            )
            """,
            user_id=result.user_id,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_resolve_login_uses_the_email_local_part_for_a_blank_name(db_session):
    session = SavepointSession(db_session)
    local_part = f"ana.{uuid4().hex}"
    person = identity(email=f"{local_part}@example.test", name="   ")

    result = await resolve_login(session, person)

    user = await stored_user(db_session, email=person.email)
    assert user is not None
    assert result.user_id == user["id"]
    assert user["full_name"] == local_part[:100]


@pytest.mark.asyncio
async def test_resolve_login_uses_the_neutral_name_when_the_email_has_no_local_part(
    db_session,
):
    session = SavepointSession(db_session)
    person = identity(email=f"@{uuid4().hex}.example.test", name=None)

    await resolve_login(session, person)

    user = await stored_user(db_session, email=person.email)
    assert user is not None
    assert user["full_name"] == DEFAULT_DISPLAY_NAME


# ---------------------------------------------------------------------------
# Reutilización de la cuenta ya vinculada (RF-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_login_reuses_the_linked_account_regardless_of_email_case(
    db_session,
):
    session = SavepointSession(db_session)
    person = identity(email=f"reuse.{uuid4().hex}@example.test", name="Reuse Person")

    first = await resolve_login(session, person)
    first_user = await stored_user(db_session, email=person.email)
    assert first_user is not None

    # The provider may return the same subject with a different email casing;
    # the identity wins and the stored email is never rewritten.
    second = await resolve_login(
        session,
        identity(
            subject=person.subject,
            email=person.email.upper(),
            name="Nombre nuevo",
        ),
    )

    assert second.outcome is LoginOutcome.LINKED
    assert second.user_id == first.user_id
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.users WHERE LOWER(email) = LOWER(:email)",
            email=person.email,
        )
        == 1
    )
    assert (
        await count_rows(
            db_session,
            """
            SELECT count(*)
            FROM public.auth_identities
            WHERE provider = 'google' AND provider_subject = :subject
            """,
            subject=person.subject,
        )
        == 1
    )
    stored = await stored_user(db_session, email=person.email)
    assert stored is not None
    assert stored["email"] == person.email
    assert stored["full_name"] == "Reuse Person"
    assert second.session_token != first.session_token


# ---------------------------------------------------------------------------
# Decisiones por correo: no se crea ni se vincula nada (RF-15, RF-16, RF-17)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_login_compares_the_email_without_case(db_session):
    email = f"Case.{uuid4().hex}@Example.Test"
    existing_id = await insert_user(
        db_session, email=email, full_name="Google Only", password_hash=None
    )
    session = SavepointSession(db_session)

    with pytest.raises(LoginRejected) as error:
        await resolve_login(
            session, identity(email=email.lower(), name="Otra persona")
        )

    assert error.value.code == LoginOutcome.GOOGLE_ONLY_ACCOUNT.value
    assert error.value.outcome is LoginOutcome.GOOGLE_ONLY_ACCOUNT
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.users WHERE LOWER(email) = LOWER(:email)",
            email=email,
        )
        == 1
    )
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.user_sessions WHERE user_id = :user_id",
            user_id=existing_id,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_resolve_login_rejects_a_local_password_account_without_writing(
    db_session,
):
    email = f"password.{uuid4().hex}@example.test"
    existing_id = await insert_user(
        db_session, email=email, full_name="Password Person", password_hash="hash"
    )
    session = SavepointSession(db_session)

    with pytest.raises(LoginRejected) as error:
        await resolve_login(session, identity(email=email.upper()))

    assert error.value.code == LoginOutcome.PASSWORD_ACCOUNT.value
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.users WHERE LOWER(email) = LOWER(:email)",
            email=email,
        )
        == 1
    )
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.auth_identities WHERE user_id = :user_id",
            user_id=existing_id,
        )
        == 0
    )
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.user_sessions WHERE user_id = :user_id",
            user_id=existing_id,
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Organización inicial del orden estable y sesión (RF-10, RF-27)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_login_returns_the_first_organization_in_stable_order(
    db_session,
):
    user_id = await create_test_user(db_session, full_name="Member Person")
    subject = f"google-subject-{uuid4().hex}"
    await insert_identity(db_session, user_id=user_id, subject=subject)
    zulu = await create_test_organization(db_session, user_id, name="Zulu Google")
    alfa = await create_test_organization(db_session, user_id, name="Alfa Google")

    before = await membership_counts(
        db_session, user_id=user_id, organization_ids=[zulu, alfa]
    )

    session = SavepointSession(db_session)
    result = await resolve_login(
        session,
        identity(
            subject=subject,
            email=f"member.{uuid4().hex}@example.test",
            name="Member Person",
        ),
    )

    assert result.outcome is LoginOutcome.LINKED
    assert result.user_id == user_id
    assert result.organization_id == alfa

    after = await membership_counts(
        db_session, user_id=user_id, organization_ids=[zulu, alfa]
    )
    assert after == before
    assert sum(value for key, value in before.items() if not key.endswith(":roles")) == 2
    assert all(
        value == 1 for key, value in before.items() if key.endswith(":roles")
    )

    claims = decode_access_token_claims(result.session_token)
    assert claims["sub"] == str(user_id)
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.user_sessions WHERE id = :session_id",
            session_id=claims["jti"],
        )
        == 1
    )


@pytest.mark.asyncio
async def test_resolve_login_keeps_the_provider_name_when_reusing_the_account(
    db_session,
):
    user_id = await create_test_user(db_session, full_name="Already Linked")
    subject = f"google-subject-{uuid4().hex}"
    await insert_identity(db_session, user_id=user_id, subject=subject)

    result = await resolve_login(
        SavepointSession(db_session),
        identity(subject=subject, name="Proveedor distinto"),
    )

    assert result.user_id == user_id
    email = (
        await db_session.execute(
            text("SELECT email FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )
    ).scalar_one()
    stored = await stored_user(db_session, email=email)
    assert stored is not None
    assert stored["full_name"] == "Already Linked"


# ---------------------------------------------------------------------------
# Atomicidad: un fallo posterior no deja cuenta ni identidad (RF-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_login_rolls_back_the_account_when_the_session_fails(
    db_session, monkeypatch
):
    from app.modules.identity import google_accounts

    async def failing_session(*args, **kwargs):
        raise RuntimeError("session creation failed")

    monkeypatch.setattr(google_accounts, "create_user_session", failing_session)
    person = identity(email=f"rollback.{uuid4().hex}@example.test", name="Rollback")

    with pytest.raises(RuntimeError):
        await resolve_login(SavepointSession(db_session), person)

    assert await stored_user(db_session, email=person.email) is None
    assert (
        await count_rows(
            db_session,
            """
            SELECT count(*)
            FROM public.auth_identities
            WHERE provider = 'google' AND provider_subject = :subject
            """,
            subject=person.subject,
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Cuenta desactivada (RF-11/RF-16): no se reactiva ni se emite sesión
# ---------------------------------------------------------------------------


@pytest.fixture
async def disabled_google_account(database_admin_url):
    """Create a committed, disabled Google account outside the rolled-back tx."""

    suffix = uuid4().hex
    email = f"disabled.{suffix}@example.test"
    subject = f"disabled-subject-{suffix}"

    connection = await connect(database_admin_url)
    try:
        user_id = await connection.fetchval(
            """
            INSERT INTO public.users (email, password_hash, full_name, is_active)
            VALUES ($1, NULL, 'Disabled Person', FALSE)
            RETURNING id
            """,
            email,
        )
        await connection.execute(
            """
            INSERT INTO public.auth_identities (user_id, provider, provider_subject)
            VALUES ($1, 'google', $2)
            """,
            user_id,
            subject,
        )
    finally:
        await connection.close()

    yield user_id, email, subject

    connection = await connect(database_admin_url)
    try:
        await connection.execute(
            "DELETE FROM public.user_sessions WHERE user_id = $1", user_id
        )
        await connection.execute(
            "DELETE FROM public.auth_identities WHERE user_id = $1", user_id
        )
        await connection.execute("DELETE FROM public.users WHERE id = $1", user_id)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_resolve_login_rejects_a_disabled_linked_account(
    db_session, disabled_google_account
):
    user_id, email, subject = disabled_google_account
    session = SavepointSession(db_session)

    with pytest.raises(LoginRejected) as error:
        await resolve_login(
            session, identity(subject=subject, email=email, name="Disabled Person")
        )

    assert error.value.code == LoginOutcome.DISABLED.value
    assert error.value.outcome is LoginOutcome.DISABLED

    stored = await stored_user(db_session, email=email)
    assert stored is not None
    # The account is not reactivated and the identity is untouched.
    assert stored["is_active"] is False
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.auth_identities WHERE user_id = :user_id",
            user_id=user_id,
        )
        == 1
    )
    assert (
        await count_rows(
            db_session,
            "SELECT count(*) FROM public.user_sessions WHERE user_id = :user_id",
            user_id=user_id,
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Vinculación desde una sesión iniciada (RF-14, RF-18…RF-21)
# ---------------------------------------------------------------------------


async def account_email(session, user_id: UUID) -> str:
    return (
        await session.execute(
            text("SELECT email FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )
    ).scalar_one()


async def identity_snapshot(session, user_id: UUID) -> list[str]:
    # ``bracket_app`` only has column privileges on (user_id, provider,
    # provider_subject): never select ``id`` here.
    rows = await session.execute(
        text("""
            SELECT provider_subject
            FROM public.auth_identities
            WHERE user_id = :user_id AND provider = 'google'
            ORDER BY provider_subject
        """),
        {"user_id": user_id},
    )
    return [row["provider_subject"] for row in rows.mappings().all()]


async def session_snapshot(session, user_id: UUID) -> list[tuple[str, object]]:
    rows = await session.execute(
        text("""
            SELECT id, revoked_at
            FROM public.user_sessions
            WHERE user_id = :user_id
            ORDER BY id
        """),
        {"user_id": user_id},
    )
    return [(str(row["id"]), row["revoked_at"]) for row in rows.mappings().all()]


async def memberships_for(
    session, user_id: UUID, organization_ids: list[UUID]
) -> dict[str, int]:
    return await membership_counts(
        session, user_id=user_id, organization_ids=organization_ids
    )


@pytest.mark.asyncio
async def test_link_identity_links_a_new_identity_without_side_effects(db_session):
    user_id = await create_test_user(db_session, full_name="Linking Person")
    email = await account_email(db_session, user_id)
    alfa = await create_test_organization(db_session, user_id, name="Alfa Link")
    zulu = await create_test_organization(db_session, user_id, name="Zulu Link")
    await create_user_session(db_session, user_id)

    before_memberships = await memberships_for(db_session, user_id, [alfa, zulu])
    before_sessions = await session_snapshot(db_session, user_id)
    before_email = await account_email(db_session, user_id)

    subject = f"google-subject-{uuid4().hex}"
    result = await link_identity(
        SavepointSession(db_session),
        user_id=user_id,
        identity=identity(subject=subject, email=email.upper(), name="Proveedor"),
    )

    assert result is LinkOutcome.LINK
    identities = await identity_snapshot(db_session, user_id)
    assert identities == [subject]

    # No UPDATE of users, no DELETE, no session changes, no membership changes.
    assert await account_email(db_session, user_id) == before_email
    stored = await stored_user(db_session, email=email)
    assert stored is not None
    assert stored["full_name"] == "Linking Person"
    assert await session_snapshot(db_session, user_id) == before_sessions
    after_memberships = await memberships_for(db_session, user_id, [alfa, zulu])
    assert after_memberships == before_memberships
    assert sum(v for k, v in after_memberships.items() if not k.endswith(":roles")) == 2
    assert all(v == 1 for k, v in after_memberships.items() if k.endswith(":roles"))


@pytest.mark.asyncio
async def test_link_identity_is_idempotent_for_the_same_subject(db_session):
    user_id = await create_test_user(db_session, full_name="Idempotent Person")
    email = await account_email(db_session, user_id)
    subject = f"google-subject-{uuid4().hex}"

    first = await link_identity(
        SavepointSession(db_session),
        user_id=user_id,
        identity=identity(subject=subject, email=email),
    )
    snapshot = await identity_snapshot(db_session, user_id)
    sessions = await session_snapshot(db_session, user_id)

    second = await link_identity(
        SavepointSession(db_session),
        user_id=user_id,
        identity=identity(subject=subject, email=email),
    )

    assert first is LinkOutcome.LINK
    assert second is LinkOutcome.IDEMPOTENT
    assert await identity_snapshot(db_session, user_id) == snapshot
    assert await session_snapshot(db_session, user_id) == sessions


@pytest.mark.asyncio
async def test_link_identity_does_not_rewrite_the_stored_email_when_the_provider_changes_it(
    db_session,
):
    user_id = await create_test_user(db_session, full_name="Stable Email")
    email = await account_email(db_session, user_id)
    subject = f"google-subject-{uuid4().hex}"

    await link_identity(
        SavepointSession(db_session),
        user_id=user_id,
        identity=identity(subject=subject, email=email),
    )
    before = await identity_snapshot(db_session, user_id)

    # Same subject, a different verified email from the provider: the identity
    # wins, nothing is written and users.email is untouched (RF-20).
    outcome = await link_identity(
        SavepointSession(db_session),
        user_id=user_id,
        identity=identity(
            subject=subject, email=f"changed.{uuid4().hex}@example.test"
        ),
    )

    assert outcome is LinkOutcome.IDEMPOTENT
    assert await identity_snapshot(db_session, user_id) == before
    assert await account_email(db_session, user_id) == email


@pytest.mark.asyncio
async def test_link_identity_rejects_an_account_that_already_has_another_identity(
    db_session,
):
    user_id = await create_test_user(db_session, full_name="Already Linked")
    email = await account_email(db_session, user_id)
    existing_subject = f"google-subject-{uuid4().hex}"
    await insert_identity(db_session, user_id=user_id, subject=existing_subject)
    sessions = await session_snapshot(db_session, user_id)

    with pytest.raises(LinkRejected) as error:
        await link_identity(
            SavepointSession(db_session),
            user_id=user_id,
            identity=identity(
                subject=f"google-subject-{uuid4().hex}", email=email
            ),
        )

    assert error.value.code == LinkOutcome.GOOGLE_ALREADY_LINKED.value
    assert await identity_snapshot(db_session, user_id) == [existing_subject]
    assert await session_snapshot(db_session, user_id) == sessions


@pytest.mark.asyncio
async def test_link_identity_rejects_an_identity_owned_by_another_account(db_session):
    owner_id = await create_test_user(db_session, full_name="Owner Person")
    owner_org = await create_test_organization(db_session, owner_id, name="Owner Org")
    user_id = await create_test_user(db_session, full_name="Linking Person")
    user_org = await create_test_organization(db_session, user_id, name="Linking Org")
    subject = f"google-subject-{uuid4().hex}"
    await insert_identity(db_session, user_id=owner_id, subject=subject)

    before = {
        "owner": await memberships_for(db_session, owner_id, [owner_org]),
        "user": await memberships_for(db_session, user_id, [user_org]),
    }
    owner_identities = await identity_snapshot(db_session, owner_id)

    with pytest.raises(LinkRejected) as error:
        await link_identity(
            SavepointSession(db_session),
            user_id=user_id,
            identity=identity(
                subject=subject, email=f"owner.{uuid4().hex}@example.test"
            ),
        )

    assert error.value.code == LinkOutcome.LINK_IDENTITY_TAKEN.value
    assert await identity_snapshot(db_session, owner_id) == owner_identities
    assert await identity_snapshot(db_session, user_id) == []
    assert {
        "owner": await memberships_for(db_session, owner_id, [owner_org]),
        "user": await memberships_for(db_session, user_id, [user_org]),
    } == before


@pytest.mark.asyncio
async def test_link_identity_rejects_a_different_provider_email(db_session):
    user_id = await create_test_user(db_session, full_name="Mismatch Person")
    email = await account_email(db_session, user_id)
    subject = f"google-subject-{uuid4().hex}"

    with pytest.raises(LinkRejected) as error:
        await link_identity(
            SavepointSession(db_session),
            user_id=user_id,
            identity=identity(
                subject=subject, email=f"other.{uuid4().hex}@example.test"
            ),
        )

    assert error.value.code == LinkOutcome.LINK_EMAIL_MISMATCH.value
    assert await identity_snapshot(db_session, user_id) == []
    assert await account_email(db_session, user_id) == email


@pytest.mark.asyncio
async def test_link_identity_rejects_a_missing_session_account(db_session):
    with pytest.raises(SessionAccountInvalid):
        await link_identity(
            SavepointSession(db_session),
            user_id=uuid4(),
            identity=identity(),
        )


@pytest.mark.asyncio
async def test_link_identity_rejects_an_inactive_session_account(
    db_session, disabled_google_account
):
    user_id, _email, _subject = disabled_google_account
    before = await identity_snapshot(db_session, user_id)

    with pytest.raises(SessionAccountInvalid):
        await link_identity(
            SavepointSession(db_session),
            user_id=user_id,
            identity=identity(),
        )

    assert await identity_snapshot(db_session, user_id) == before


# ---------------------------------------------------------------------------
# La 024 es la última garantía: un choque no produce 500
# ---------------------------------------------------------------------------


@pytest.fixture
async def fresh_database(database_admin_url):
    """Throwaway schema at init + 001…024, needed to hit the 024 constraint."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc010_{secrets.token_hex(8)}"
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


@pytest.mark.asyncio
async def test_link_identity_translates_an_account_uniqueness_conflict(
    fresh_database, monkeypatch
):
    from app.modules.identity import google_accounts

    engine, admin = fresh_database
    suffix = uuid4().hex
    email = f"race.{suffix}@example.test"
    existing_subject = f"google-subject-{suffix}"
    user_id = await admin.fetchval(
        """
        INSERT INTO public.users (email, password_hash, full_name)
        VALUES ($1, 'hash', 'Race Account')
        RETURNING id
        """,
        email,
    )
    await admin.execute(
        """
        INSERT INTO public.auth_identities (user_id, provider, provider_subject)
        VALUES ($1, 'google', $2)
        """,
        user_id,
        existing_subject,
    )

    # Simulate the decision read missing a concurrent insert: the INSERT hits
    # uq_auth_identity_user_provider and the conflict is classified.
    monkeypatch.setattr(google_accounts, "decide_link", lambda **kwargs: LinkOutcome.LINK)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        with pytest.raises(LinkRejected) as error:
            await link_identity(
                session,
                user_id=user_id,
                identity=identity(
                    subject=f"google-subject-{uuid4().hex}", email=email
                ),
            )

    assert error.value.code == LinkOutcome.GOOGLE_ALREADY_LINKED.value
    identities = await admin.fetch(
        """
        SELECT provider_subject FROM public.auth_identities
        WHERE user_id = $1 AND provider = 'google'
        """,
        user_id,
    )
    assert [row["provider_subject"] for row in identities] == [existing_subject]


@pytest.mark.asyncio
async def test_link_identity_translates_a_subject_uniqueness_conflict(
    fresh_database, monkeypatch
):
    from app.modules.identity import google_accounts

    engine, admin = fresh_database
    suffix = uuid4().hex
    subject = f"google-subject-{suffix}"
    owner_id = await admin.fetchval(
        """
        INSERT INTO public.users (email, password_hash, full_name)
        VALUES ($1, 'hash', 'Owner Person')
        RETURNING id
        """,
        f"owner.{suffix}@example.test",
    )
    user_id = await admin.fetchval(
        """
        INSERT INTO public.users (email, password_hash, full_name)
        VALUES ($1, 'hash', 'Race Account')
        RETURNING id
        """,
        f"race.{suffix}@example.test",
    )
    await admin.execute(
        """
        INSERT INTO public.auth_identities (user_id, provider, provider_subject)
        VALUES ($1, 'google', $2)
        """,
        owner_id,
        subject,
    )

    monkeypatch.setattr(google_accounts, "decide_link", lambda **kwargs: LinkOutcome.LINK)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        with pytest.raises(LinkRejected) as error:
            await link_identity(
                session,
                user_id=user_id,
                identity=identity(
                    subject=subject, email=f"race.{uuid4().hex}@example.test"
                ),
            )

    assert error.value.code == LinkOutcome.LINK_IDENTITY_TAKEN.value
    owned = await admin.fetch(
        """
        SELECT provider_subject FROM public.auth_identities
        WHERE user_id = $1 AND provider = 'google'
        """,
        owner_id,
    )
    assert [row["provider_subject"] for row in owned] == [subject]
    assert [
        row["provider_subject"]
        for row in await admin.fetch(
            """
            SELECT provider_subject FROM public.auth_identities
            WHERE user_id = $1 AND provider = 'google'
            """,
            user_id,
        )
    ] == []


@pytest.mark.asyncio
async def test_link_conflict_without_a_known_owner_fails_closed(db_session):
    user_id = await create_test_user(db_session, full_name="Closed Person")

    with pytest.raises(LinkRejected) as error:
        await _classify_link_conflict(
            SavepointSession(db_session),
            user_id=user_id,
            subject=f"google-subject-{uuid4().hex}",
        )

    assert error.value.code == "GOOGLE_IDENTITY_INVALID"
