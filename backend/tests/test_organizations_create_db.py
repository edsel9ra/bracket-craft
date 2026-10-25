"""Organización opcional con PostgreSQL real (RF-24, RF-25, RF-26).

Pruebas opt-in (``RUN_DATABASE_TESTS=1``) que ejercitan el endpoint real
``POST /organizations`` y ``resolve_login`` sobre el rol de aplicación. Cada
prueba usa la transacción externa revertida de ``db_session``: el envoltorio
convierte ``begin()`` en un ``SAVEPOINT``, así que se ejecuta el código de
producción completo y no queda ningún dato al terminar.

Cubren: el alta con dueño (membresía activa y rol ``owner``), el slug ocupado
(409 con código, sesión y cuenta intactas, sin organización nueva), la guarda de
una cuenta que ya tiene organización (409 sin código) y que el login con Google
no crea organizaciones.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import get_db, set_rls_context
from app.core.security import create_user_session, get_current_user_id
from app.main import api
from app.modules.identity.google_accounts import resolve_login
from app.modules.identity.google_claims import GoogleIdentity
from db_helpers import create_test_organization, create_test_user


class SavepointSession:
    """Delegates to the test session, turning ``begin()`` into a savepoint."""

    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture
async def client():
    api.dependency_overrides.clear()
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as value:
        yield value
    api.dependency_overrides.clear()


def use_session(database, user_id: UUID) -> None:
    async def fake_database():
        yield SavepointSession(database)

    async def fake_user():
        return user_id

    api.dependency_overrides[get_db] = fake_database
    api.dependency_overrides[get_current_user_id] = fake_user


async def user_organizations(session, user_id: UUID) -> list[dict]:
    await set_rls_context(session, None, user_id)
    rows = await session.execute(
        text("""
            SELECT id, name, slug, organization_user_id
            FROM list_user_organizations()
        """)
    )
    return [dict(row) for row in rows.mappings().all()]


async def owner_membership(
    session, *, organization_id: UUID, user_id: UUID
) -> list[dict]:
    await set_rls_context(session, organization_id, user_id)
    row = await session.execute(
        text("""
            SELECT ou.is_active, ou.id AS organization_user_id, rd.code AS role_code
            FROM organization_users ou
            JOIN organization_user_roles our
              ON our.organization_user_id = ou.id
             AND our.organization_id = ou.organization_id
            JOIN roles r
              ON r.id = our.role_id
             AND r.organization_id = ou.organization_id
            JOIN role_definitions rd ON rd.id = r.role_definition_id
            WHERE ou.user_id = :user_id
            ORDER BY rd.code
        """),
        {"user_id": user_id},
    )
    return [dict(row) for row in row.mappings().all()]


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


# ---------------------------------------------------------------------------
# Alta con dueño
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_organization_creates_an_active_owner_membership(
    db_session, client
):
    user_id = await create_test_user(db_session)
    use_session(db_session, user_id)
    suffix = uuid4().hex[:12]

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Liga Base Real", "slug": f"liga-{suffix}"},
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "Liga Base Real"
    assert created["slug"] == f"liga-{suffix}"

    organizations = await user_organizations(db_session, user_id)
    assert len(organizations) == 1
    stored = organizations[0]
    assert str(stored["id"]) == created["id"]
    assert stored["name"] == created["name"]
    assert stored["slug"] == created["slug"]
    assert str(stored["organization_user_id"]) == created["organization_user_id"]

    membership = await owner_membership(
        db_session, organization_id=UUID(created["id"]), user_id=user_id
    )
    assert membership == [
        {
            "is_active": True,
            "organization_user_id": UUID(created["organization_user_id"]),
            "role_code": "owner",
        }
    ]


# ---------------------------------------------------------------------------
# Slug ocupado: 409 codificado, sin organización nueva y con la sesión intacta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taken_slug_returns_409_and_keeps_the_account_and_session(db_session, client):
    owner_id = await create_test_user(db_session)
    await create_test_organization(db_session, owner_id, name="Dueña Existente")
    owner_organizations = await user_organizations(db_session, owner_id)
    taken_slug = owner_organizations[0]["slug"]

    user_id = await create_test_user(db_session)
    await create_user_session(db_session, user_id)
    sessions_before = await session_snapshot(db_session, user_id)
    use_session(db_session, user_id)

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Liga Duplicada", "slug": taken_slug},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ORGANIZATION_SLUG_TAKEN"
    assert isinstance(response.json()["detail"], str)
    # No new organization, no membership and the account remains usable.
    assert await user_organizations(db_session, user_id) == []
    assert await user_organizations(db_session, owner_id) == owner_organizations
    assert len(sessions_before) == 1
    assert await session_snapshot(db_session, user_id) == sessions_before
    still_there = await db_session.execute(
        text("SELECT is_active FROM public.users WHERE id = :user_id"),
        {"user_id": user_id},
    )
    assert still_there.scalar_one() is True


# ---------------------------------------------------------------------------
# Guarda de organización previa: 409 sin código y sin cambios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_with_an_organization_gets_409_without_code_and_no_changes(
    db_session, client
):
    user_id = await create_test_user(db_session)
    await create_test_organization(db_session, user_id, name="Organización Previa")
    await create_user_session(db_session, user_id)
    organizations_before = await user_organizations(db_session, user_id)
    sessions_before = await session_snapshot(db_session, user_id)
    use_session(db_session, user_id)

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Otra Organización", "slug": f"otra-{uuid4().hex[:12]}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]
    assert "code" not in response.json()
    assert await user_organizations(db_session, user_id) == organizations_before
    assert await session_snapshot(db_session, user_id) == sessions_before


# ---------------------------------------------------------------------------
# El login con Google no crea organizaciones (RF-26)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_login_does_not_create_an_organization(db_session):
    person = GoogleIdentity(
        subject=f"google-subject-{uuid4().hex}",
        email=f"orgless.{uuid4().hex}@example.test",
        email_verified=True,
        name="Sin Organización",
    )

    result = await resolve_login(SavepointSession(db_session), person)

    assert result.organization_id is None
    assert await user_organizations(db_session, result.user_id) == []
