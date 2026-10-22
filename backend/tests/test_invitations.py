import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from inspect import getsource
from urllib.parse import unquote
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db, set_rls_context
from app.core.permissions import require_permission
from app.core.security import decode_access_token, get_optional_current_user_id
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.invitations import router as invitations_router
from app.modules.invitations.errors import (
    INVITATION_ALREADY_ACCEPTED,
    INVITATION_OTHER_PENDING,
    INVITATION_REVOKED_RESEND,
)
from app.modules.invitations.lifecycle import effective_invitation_status
from app.modules.invitations.router import (
    _invitation_payload,
    _token_hash,
    list_invitations,
    resend_invitation,
)
from assertion_messages import describe_response
from db_helpers import TenantContext, create_test_organization


@dataclass(frozen=True)
class InvitationTestContext:
    db: AsyncSession
    organization_id: UUID
    owner_user_id: UUID
    owner_member_id: UUID


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


@pytest.fixture
async def invitation_context():
    if os.getenv("RUN_DATABASE_TESTS") != "1":
        pytest.skip("RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas")

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        async with db.begin():
            owner = await db.execute(
                text("SELECT id FROM users WHERE LOWER(email) = 'demo.owner@bracketcraft.dev'")
            )
            owner_user_id = owner.scalar_one_or_none()
            if owner_user_id is None:
                pytest.skip("La base de integración no contiene el usuario demo.owner")

            await set_rls_context(db, None, owner_user_id)
            organization = await db.execute(text("SELECT * FROM list_user_organizations() LIMIT 1"))
            organization_row = organization.mappings().one_or_none()
            if organization_row is None:
                pytest.skip("El usuario demo.owner no tiene una organización de pruebas")

            yield InvitationTestContext(
                db=db,
                organization_id=organization_row["id"],
                owner_user_id=owner_user_id,
                owner_member_id=organization_row["organization_user_id"],
            )
    await engine.dispose()


async def _insert_invitation(
    context: InvitationTestContext,
    email: str,
    role_code: str,
    token: str,
    expires_at: datetime,
) -> None:
    db = context.db
    await set_rls_context(db, context.organization_id, context.owner_user_id)
    await db.execute(
        text("""
            INSERT INTO organization_invitations
                (organization_id, email, role_code, token_hash, token_encrypted,
                 expires_at, invited_by_member_id)
            VALUES
                (:organization_id, :email, :role_code, :token_hash,
                 pgp_sym_encrypt(:token, 'integration-test-key'), :expires_at,
                 :member_id)
        """),
        {
            "organization_id": str(context.organization_id),
            "email": email,
            "role_code": role_code,
            "token_hash": _token_hash(token),
            "token": token,
            "expires_at": expires_at,
            "member_id": str(context.owner_member_id),
        },
    )


async def _preview(context: InvitationTestContext, token: str) -> dict:
    result = await context.db.execute(
        text("SELECT * FROM get_organization_invitation_by_token(:token_hash)"),
        {"token_hash": _token_hash(token)},
    )
    return dict(result.mappings().one())


async def _accept(context: InvitationTestContext, token: str, user_id: UUID | None = None) -> dict:
    await set_rls_context(context.db, None, user_id)
    result = await context.db.execute(
        text("""
            SELECT *
            FROM accept_organization_invitation(
                :token_hash,
                :password_hash,
                :full_name
            )
        """),
        {
            "token_hash": _token_hash(token),
            "password_hash": "integration-password-hash",
            "full_name": "Integration Invitee",
        },
    )
    return dict(result.mappings().one())


class _AcceptanceResult:
    def __init__(self, mapping: dict | None = None):
        self._mapping = mapping

    def mappings(self):
        return self

    def one_or_none(self):
        return self._mapping

    def one(self):
        return self._mapping

    def all(self):
        return [] if self._mapping is None else [self._mapping]


class _AcceptanceTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _AcceptanceDatabase:
    """Minimal database double for the real acceptance endpoint over ASGI."""

    def __init__(self, accepted: dict, *, requires_login: bool = False):
        self.accepted = accepted
        self.requires_login = requires_login

    def begin(self):
        return _AcceptanceTransaction()

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "get_organization_invitation_by_token" in sql:
            return _AcceptanceResult(
                {
                    "status": "pending",
                    "requires_login": self.requires_login,
                }
            )
        if "accept_organization_invitation" in sql:
            return _AcceptanceResult(self.accepted)
        return _AcceptanceResult()


def _auth_cookies(response) -> list[str]:
    name = get_settings().auth_cookie_name
    return [
        cookie
        for cookie in response.headers.get_list("set-cookie")
        if cookie.startswith(f"{name}=")
    ]


@asynccontextmanager
async def _acceptance_api(database, *, current_user_id: UUID | None = None):
    async def database_dependency():
        yield database

    api.dependency_overrides[get_db] = database_dependency
    if current_user_id is not None:
        async def current_user():
            return current_user_id

        api.dependency_overrides[get_optional_current_user_id] = current_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_optional_current_user_id, None)


@pytest.mark.asyncio
async def test_acceptance_response_has_no_tokens_and_sets_the_session_cookie():
    user_id = uuid4()
    database = _AcceptanceDatabase(
        {
            "user_id": user_id,
            "organization_id": uuid4(),
            "organization_user_id": uuid4(),
            "role_code": "operator",
            "created_user": True,
        }
    )

    async with _acceptance_api(database) as client:
        response = await client.post(
            "/api/v1/invitations/acceptance-token/accept",
            json={"password": "Secret1234!", "full_name": "Nuevo Invitado"},
        )

    assert response.status_code == 200, describe_response(
        "acceptance returns the session contract", response
    )
    body = response.json()
    assert "access_token" not in body
    assert "token_type" not in body
    assert set(body) == {
        "user_id",
        "organization_id",
        "organization_user_id",
        "role_code",
        "created_user",
    }

    cookies = _auth_cookies(response)
    assert len(cookies) == 1
    assert "HttpOnly" in cookies[0]

    parsed = SimpleCookie()
    parsed.load(cookies[0])
    token = parsed[get_settings().auth_cookie_name].value
    assert token
    assert decode_access_token(token) == user_id


@pytest.mark.asyncio
async def test_acceptance_with_an_existing_session_returns_no_credentials():
    existing_user_id = uuid4()
    database = _AcceptanceDatabase(
        {
            "user_id": existing_user_id,
            "organization_id": uuid4(),
            "organization_user_id": uuid4(),
            "role_code": "viewer",
            "created_user": False,
        },
        requires_login=True,
    )

    async with _acceptance_api(database, current_user_id=existing_user_id) as client:
        response = await client.post(
            "/api/v1/invitations/existing-session-token/accept",
            json={},
        )

    assert response.status_code == 200, describe_response(
        "acceptance with an existing session returns no credentials", response
    )
    assert "access_token" not in response.text
    assert "token_type" not in response.text
    assert _auth_cookies(response) == []


@pytest.mark.asyncio
async def test_invitation_expiration_and_single_use(invitation_context: InvitationTestContext):
    token = f"single-use-{uuid4().hex}"
    invitee_email = f"invitee-{uuid4().hex}@example.com"
    await _insert_invitation(
        invitation_context,
        invitee_email,
        "operator",
        token,
        datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert (await _preview(invitation_context, token))["status"] == "pending"
    accepted = await _accept(invitation_context, token)
    assert accepted["created_user"] is True

    existing_account_token = f"existing-account-{uuid4().hex}"
    await _insert_invitation(
        invitation_context,
        invitee_email,
        "viewer",
        existing_account_token,
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert (await _preview(invitation_context, existing_account_token))["requires_login"] is True
    with pytest.raises(DBAPIError) as failure:
        async with invitation_context.db.begin_nested():
            await _accept(invitation_context, existing_account_token)
    assert _sqlstate(failure.value) == "42501"

    with pytest.raises(DBAPIError) as failure:
        async with invitation_context.db.begin_nested():
            await _accept(invitation_context, token)
    assert _sqlstate(failure.value) == "P0001"

    expired_token = f"expired-{uuid4().hex}"
    await _insert_invitation(
        invitation_context,
        f"expired-{uuid4().hex}@example.com",
        "viewer",
        expired_token,
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    assert (await _preview(invitation_context, expired_token))["status"] == "expired"
    with pytest.raises(DBAPIError) as failure:
        async with invitation_context.db.begin_nested():
            await _accept(invitation_context, expired_token)
    assert _sqlstate(failure.value) == "P0001"


@pytest.mark.asyncio
async def test_invitation_roles_cannot_escalate_and_operation_scope_is_enforced(
    invitation_context: InvitationTestContext,
):
    owner_context = invitation_context
    owner_role_token = f"owner-role-{uuid4().hex}"
    with pytest.raises(DBAPIError) as failure:
        async with invitation_context.db.begin_nested():
            await _insert_invitation(
                owner_context,
                f"owner-role-{uuid4().hex}@example.com",
                "owner",
                owner_role_token,
                datetime.now(timezone.utc) + timedelta(hours=1),
            )
    assert _sqlstate(failure.value) == "23514"

    accepted_members: dict[str, dict] = {}
    for role_code in ("operator", "referee", "viewer"):
        token = f"role-{role_code}-{uuid4().hex}"
        await _insert_invitation(
            owner_context,
            f"{role_code}-{uuid4().hex}@example.com",
            role_code,
            token,
            datetime.now(timezone.utc) + timedelta(hours=1),
        )
        accepted_members[role_code] = await _accept(owner_context, token)

    match_id = uuid4()
    operator = accepted_members["operator"]
    operator_context = AuthContext(
        user_id=operator["user_id"],
        organization_id=invitation_context.organization_id,
        organization_user_id=operator["organization_user_id"],
    )
    await set_rls_context(invitation_context.db, invitation_context.organization_id, operator_context.user_id)
    await require_permission(
        invitation_context.db,
        operator_context,
        "CLOSE_MATCH_REPORT",
        match_id=match_id,
    )

    referee = accepted_members["referee"]
    referee_context = AuthContext(
        user_id=referee["user_id"],
        organization_id=invitation_context.organization_id,
        organization_user_id=referee["organization_user_id"],
    )
    await set_rls_context(invitation_context.db, invitation_context.organization_id, referee_context.user_id)
    with pytest.raises(PermissionError):
        await require_permission(
            invitation_context.db,
            referee_context,
            "CLOSE_MATCH_REPORT",
            match_id=match_id,
        )

    viewer = accepted_members["viewer"]
    viewer_context = AuthContext(
        user_id=viewer["user_id"],
        organization_id=invitation_context.organization_id,
        organization_user_id=viewer["organization_user_id"],
    )
    await set_rls_context(invitation_context.db, invitation_context.organization_id, viewer_context.user_id)
    with pytest.raises(PermissionError):
        await require_permission(invitation_context.db, viewer_context, "CLOSE_MATCH_REPORT")


# --- R22 / RF-005: estado efectivo de la invitación vencida -----------------


NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def test_effective_status_marks_a_past_pending_invitation_as_expired():
    assert (
        effective_invitation_status("pending", NOW - timedelta(seconds=1), NOW)
        == "expired"
    )


def test_effective_status_keeps_a_live_pending_invitation_pending():
    assert (
        effective_invitation_status("pending", NOW + timedelta(seconds=1), NOW)
        == "pending"
    )


def test_effective_status_expires_at_the_expiration_instant():
    assert effective_invitation_status("pending", NOW, NOW) == "expired"


@pytest.mark.parametrize("stored_status", ["accepted", "expired", "revoked"])
def test_effective_status_returns_other_states_unchanged(stored_status):
    assert (
        effective_invitation_status(
            stored_status, NOW - timedelta(days=30), NOW
        )
        == stored_status
    )
    assert (
        effective_invitation_status(
            stored_status, NOW + timedelta(days=30), NOW
        )
        == stored_status
    )


def test_effective_status_depends_only_on_the_received_now():
    expires_at = NOW + timedelta(hours=1)

    assert effective_invitation_status("pending", expires_at, NOW) == "pending"
    assert (
        effective_invitation_status(
            "pending", expires_at, expires_at + timedelta(seconds=1)
        )
        == "expired"
    )


def test_invitation_listing_does_not_write():
    source = getsource(list_invitations).upper()

    assert "UPDATE ORGANIZATION_INVITATIONS" not in source
    assert "SET STATUS" not in source
    assert "NOW=NOW" in source
    assert "EFFECTIVE_INVITATION_STATUS" in getsource(_invitation_payload).upper()


def test_resending_a_revoked_invitation_checks_the_conflict_before_writing():
    """RF-003: el 409 se decide antes de materializar y de reescribir la fila."""

    source = getsource(resend_invitation).upper()

    assert "RESEND_CONFLICT" in source
    assert source.index("RESEND_CONFLICT") < source.index("_MATERIALIZE_EXPIRED_PENDING")
    assert source.index("_MATERIALIZE_EXPIRED_PENDING") < source.index(
        "UPDATE ORGANIZATION_INVITATIONS"
    )


async def _insert_tenant_invitation(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    email: str,
    token: str,
    expires_at: datetime,
    role_code: str = "operator",
) -> dict:
    await set_rls_context(session, tenant.organization_id, tenant.user_id)
    result = await session.execute(
        text("""
            INSERT INTO organization_invitations
                (organization_id, email, role_code, token_hash, token_encrypted,
                 expires_at, invited_by_member_id)
            VALUES
                (:organization_id, :email, :role_code, :token_hash,
                 pgp_sym_encrypt(:token, 'integration-test-key'), :expires_at,
                 :member_id)
            RETURNING id, status, expires_at, updated_at, revoked_at
        """),
        {
            "organization_id": str(tenant.organization_id),
            "email": email,
            "role_code": role_code,
            "token_hash": _token_hash(token),
            "token": token,
            "expires_at": expires_at,
            "member_id": str(tenant.member_id),
        },
    )
    return dict(result.mappings().one())


async def _stored_invitations(
    session: AsyncSession,
    tenant: TenantContext,
    email: str,
) -> list[dict]:
    await set_rls_context(session, tenant.organization_id, tenant.user_id)
    result = await session.execute(
        text("""
            SELECT id, status, expires_at, updated_at, revoked_at
            FROM organization_invitations
            WHERE organization_id = :organization_id
              AND email = :email
            ORDER BY created_at
        """),
        {"organization_id": str(tenant.organization_id), "email": email},
    )
    return [dict(row) for row in result.mappings().all()]


@asynccontextmanager
async def _invitation_api(
    session: AsyncSession,
    tenant: TenantContext,
    monkeypatch,
    *,
    member_id: UUID | None = None,
    user_id: UUID | None = None,
    raise_app_exceptions: bool = True,
):
    """Run the real invitation endpoints on the rolled-back test transaction.

    ``raise_app_exceptions=False`` convierte una excepción no controlada del
    endpoint en la respuesta HTTP 500 que vería un cliente real.
    """

    class _RequestSession:
        def begin(self):
            return session.begin_nested()

        def __getattr__(self, name):
            return getattr(session, name)

    async def database():
        yield _RequestSession()

    async def current_context():
        return AuthContext(
            user_id=user_id or tenant.user_id,
            organization_id=tenant.organization_id,
            organization_user_id=member_id or tenant.member_id,
        )

    async def skip_email(*args, **kwargs):
        return None

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = current_context
    monkeypatch.setattr(invitations_router, "send_invitation_email", skip_email)
    try:
        async with AsyncClient(
            transport=ASGITransport(
                app=api, raise_app_exceptions=raise_app_exceptions
            ),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_auth_context, None)


@pytest.mark.asyncio
async def test_listing_invitations_reports_the_effective_status_without_writing(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Listing")
    email = f"expired-listing-{uuid4().hex}@example.com"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"listing-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    assert invitation["status"] == "pending"

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        first = await client.get("/api/v1/organizations/invitations")
        second = await client.get("/api/v1/organizations/invitations")

    assert first.status_code == 200, describe_response("listing invitations (first read)", first)
    assert second.status_code == 200, describe_response("listing invitations (second read)", second)
    assert first.json() == second.json()
    assert [row["status"] for row in first.json()] == ["expired"]

    stored = await _stored_invitations(db_session, tenant, email)
    assert [row["status"] for row in stored] == ["pending"]
    assert stored[0]["updated_at"] == invitation["updated_at"]


@pytest.mark.asyncio
async def test_creating_over_an_expired_invitation_returns_201_and_leaves_one_pending(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Create")
    email = f"expired-create-{uuid4().hex}@example.com"
    await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"create-old-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            "/api/v1/organizations/invitations",
            json={"email": email, "role_code": "operator"},
        )

    assert response.status_code == 201, describe_response(
        "create over an expired invitation returns 201", response
    )
    assert response.json()["status"] == "pending"

    stored = await _stored_invitations(db_session, tenant, email)
    assert sorted(row["status"] for row in stored) == ["expired", "pending"]
    pending = [row for row in stored if row["status"] == "pending"]
    assert len(pending) == 1
    assert str(pending[0]["id"]) == response.json()["id"]


@pytest.mark.asyncio
async def test_creating_over_a_live_pending_invitation_returns_409(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Conflict")
    email = f"live-create-{uuid4().hex}@example.com"
    await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"create-live-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            "/api/v1/organizations/invitations",
            json={"email": email, "role_code": "operator"},
        )

    assert response.status_code == 409, describe_response(
        "create over a live pending invitation returns 409", response
    )
    assert response.json()["code"] == INVITATION_OTHER_PENDING
    stored = await _stored_invitations(db_session, tenant, email)
    assert [row["status"] for row in stored] == ["pending"]


@pytest.mark.asyncio
async def test_revoking_an_expired_invitation_returns_409_without_rewriting(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Revoke")
    email = f"expired-revoke-{uuid4().hex}@example.com"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"revoke-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.delete(
            f"/api/v1/organizations/invitations/{invitation['id']}"
        )

    assert response.status_code == 409, describe_response(
        "revoke an expired invitation returns 409", response
    )
    stored = await _stored_invitations(db_session, tenant, email)
    assert stored[0]["status"] == "pending"
    assert stored[0]["revoked_at"] is None
    assert stored[0]["updated_at"] == invitation["updated_at"]


@pytest.mark.asyncio
async def test_accepting_an_expired_invitation_returns_410(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Accept")
    email = f"expired-accept-{uuid4().hex}@example.com"
    token = f"accept-expired-{uuid4().hex}"
    await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=token,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/invitations/{token}/accept",
            json={},
        )

    assert response.status_code == 410, describe_response(
        "accept an expired invitation returns 410", response
    )
    stored = await _stored_invitations(db_session, tenant, email)
    assert [row["status"] for row in stored] == ["pending"]


@pytest.mark.asyncio
async def test_resending_reuses_an_expired_invitation_without_creating_a_new_one(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Resend")
    email = f"expired-resend-{uuid4().hex}@example.com"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"resend-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    before = await _stored_invitation_details(db_session, tenant, email)

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation['id']}/resend"
        )

    assert response.status_code == 200, describe_response(
        "resend an expired invitation returns 200", response
    )
    assert response.json()["status"] == "pending"
    assert "code" not in response.json()
    stored = await _stored_invitations(db_session, tenant, email)
    assert len(stored) == 1
    assert stored[0]["status"] == "pending"
    assert stored[0]["expires_at"] > invitation["expires_at"]
    after = await _stored_invitation_details(db_session, tenant, email)
    assert after[0]["token_hash"] != before[0]["token_hash"]


@pytest.mark.asyncio
async def test_resending_an_expired_invitation_with_another_live_pending_returns_409(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Resend Conflict")
    email = f"resend-conflict-{uuid4().hex}@example.com"
    expired = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"resend-conflict-old-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        created = await client.post(
            "/api/v1/organizations/invitations",
            json={"email": email, "role_code": "operator"},
        )
    assert created.status_code == 201, describe_response(
        "create before the resend conflict returns 201", created
    )

    before = await _stored_invitations(db_session, tenant, email)

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{expired['id']}/resend"
        )

    assert response.status_code == 409, describe_response(
        "resend with another live pending returns 409", response
    )
    assert response.json()["code"] == INVITATION_OTHER_PENDING
    assert "pendiente" in response.json()["detail"].lower()
    after = await _stored_invitations(db_session, tenant, email)
    assert after == before


@pytest.mark.asyncio
async def test_resending_a_revoked_invitation_returns_409_without_writing_or_sending(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    """RF-003 (C-1): una revocada ya no se resucita por reenvío."""

    tenant = await tenant_factory("Invitation Resend Revoked")
    email = f"resend-revoked-{uuid4().hex}@example.com"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"resend-revoked-old-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, invitation["id"])

    # CURRENT_TIMESTAMP es el inicio de la transacción de la prueba: se retrasa
    # updated_at para que cualquier reescritura sea observable dentro de la misma.
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await set_rls_context(db_session, tenant.organization_id, tenant.user_id)
    await db_session.execute(
        text("""
            UPDATE organization_invitations
            SET updated_at = :past
            WHERE id = :invitation_id
        """),
        {"past": past, "invitation_id": str(invitation["id"])},
    )
    before = await _stored_invitation_details(db_session, tenant, email)
    assert before[0]["status"] == "revoked"
    assert before[0]["revoked_at"] is not None

    sent: list[tuple] = []

    async def recording_email(*args, **kwargs):
        sent.append(args)

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        monkeypatch.setattr(invitations_router, "send_invitation_email", recording_email)
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation['id']}/resend"
        )

    assert response.status_code == 409, describe_response(
        "resend a revoked invitation returns 409", response
    )
    body = response.json()
    assert body["code"] == INVITATION_REVOKED_RESEND
    assert isinstance(body["detail"], str)
    assert body["detail"]
    assert "invite_url" not in body
    assert "token" not in json.dumps(body)
    assert sent == []

    after = await _stored_invitation_details(db_session, tenant, email)
    assert after == before
    assert after[0]["status"] == "revoked"
    assert after[0]["revoked_at"] is not None
    assert await _invitation_audit_entries(db_session, tenant) == []


@pytest.mark.asyncio
async def test_resending_an_accepted_invitation_returns_409_with_its_code(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Resend Accepted")
    email = f"resend-accepted-{uuid4().hex}@example.com"
    token = f"resend-accepted-{uuid4().hex}"
    await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        accepted = await client.post(
            f"/api/v1/invitations/{token}/accept",
            json={"password": "Secret1234!", "full_name": "Invitado Reenvío"},
        )
    assert accepted.status_code == 200, describe_response(
        "accept before the resend accepted returns 200", accepted
    )

    before = await _stored_invitation_details(db_session, tenant, email)
    assert [row["status"] for row in before] == ["accepted"]

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{before[0]['id']}/resend"
        )

    assert response.status_code == 409, describe_response(
        "resend an accepted invitation returns 409", response
    )
    assert response.json()["code"] == INVITATION_ALREADY_ACCEPTED
    after = await _stored_invitation_details(db_session, tenant, email)
    assert after == before


@pytest.mark.asyncio
async def test_resending_a_revoked_invitation_with_another_live_pending_returns_409(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    """C-1 se evalúa antes que la otra pendiente: el motivo es el de la revocada."""

    tenant = await tenant_factory("Invitation Resend Revoked Conflict")
    email = f"resend-revoked-conflict-{uuid4().hex}@example.com"
    revoked = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"resend-revoked-old-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        revoked_response = await client.delete(
            f"/api/v1/organizations/invitations/{revoked['id']}"
        )
        assert revoked_response.status_code == 204, describe_response(
            "revoke before the reopen conflict returns 204", revoked_response
        )
        created = await client.post(
            "/api/v1/organizations/invitations",
            json={"email": email, "role_code": "operator"},
        )
    assert created.status_code == 201, describe_response(
        "create before the reopen conflict returns 201", created
    )

    before = await _stored_invitations(db_session, tenant, email)

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{revoked['id']}/resend"
        )

    assert response.status_code == 409, describe_response(
        "resend a revoked invitation with another live pending returns 409", response
    )
    assert response.json()["code"] == INVITATION_REVOKED_RESEND
    after = await _stored_invitations(db_session, tenant, email)
    assert after == before


# --- R32a / RF-015 y R32b / RF-016: contrato y precedencia --------------------


@pytest.mark.asyncio
async def test_accepting_an_invitation_sets_only_the_session_cookie(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Acceptance Contract")
    email = f"accept-contract-{uuid4().hex}@example.com"
    token = f"accept-contract-{uuid4().hex}"
    await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/invitations/{token}/accept",
            json={"password": "Secret1234!", "full_name": "Contrato Invitado"},
        )

    assert response.status_code == 200, describe_response(
        "acceptance sets only the session cookie returns 200", response
    )
    body = response.json()
    assert "access_token" not in body
    assert "token_type" not in body
    assert body["created_user"] is True
    cookies = _auth_cookies(response)
    assert len(cookies) == 1
    assert "HttpOnly" in cookies[0]

    stored = await _stored_invitations(db_session, tenant, email)
    assert [row["status"] for row in stored] == ["accepted"]


async def _create_organization_member(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    full_name: str = "Precedence Member",
) -> tuple[UUID, UUID, str]:
    email = f"member-{uuid4().hex}@example.com"
    await set_rls_context(session, tenant.organization_id, tenant.user_id)
    user_id = (
        await session.execute(
            text("""
                INSERT INTO users (email, password_hash, full_name)
                VALUES (:email, 'integration-test-hash', :full_name)
                RETURNING id
            """),
            {"email": email, "full_name": full_name},
        )
    ).scalar_one()
    member_id = (
        await session.execute(
            text("""
                INSERT INTO organization_users (organization_id, user_id)
                VALUES (:organization_id, :user_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "user_id": str(user_id),
            },
        )
    ).scalar_one()
    return user_id, member_id, email


async def _grant_role(
    session: AsyncSession,
    tenant: TenantContext,
    member_id: UUID,
    role_code: str,
) -> None:
    await set_rls_context(session, tenant.organization_id, tenant.user_id)
    await session.execute(
        text("""
            INSERT INTO roles (organization_id, role_definition_id, name, permissions)
            SELECT :organization_id, rd.id, rd.name, rd.system_permissions
            FROM role_definitions rd
            WHERE rd.code = :role_code
            ON CONFLICT (organization_id, name) DO UPDATE
                SET role_definition_id = EXCLUDED.role_definition_id,
                    permissions = EXCLUDED.permissions
        """),
        {
            "organization_id": str(tenant.organization_id),
            "role_code": role_code,
        },
    )
    await session.execute(
        text("""
            INSERT INTO organization_user_roles
                (organization_id, organization_user_id, role_id)
            SELECT :organization_id, :member_id, r.id
            FROM roles r
            JOIN role_definitions rd ON rd.id = r.role_definition_id
            WHERE r.organization_id = :organization_id
              AND rd.code = :role_code
            ON CONFLICT DO NOTHING
        """),
        {
            "organization_id": str(tenant.organization_id),
            "member_id": str(member_id),
            "role_code": role_code,
        },
    )


@pytest.mark.asyncio
async def test_role_precedence_is_consistent_in_listing_access_and_role_change(
    db_session: AsyncSession, monkeypatch
):
    owner_email = f"precedence-owner-{uuid4().hex}@example.com"
    owner_user_id = (
        await db_session.execute(
            text("""
                INSERT INTO users (email, password_hash, full_name)
                VALUES (:email, 'integration-test-hash', 'Precedence Owner')
                RETURNING id
            """),
            {"email": owner_email},
        )
    ).scalar_one()
    organization_id = await create_test_organization(
        db_session, owner_user_id, name=f"Role Precedence {uuid4().hex[:8]}"
    )
    await set_rls_context(db_session, organization_id, owner_user_id)
    owner_member_id = (
        await db_session.execute(
            text("""
                SELECT id
                FROM organization_users
                WHERE organization_id = :organization_id AND user_id = :user_id
            """),
            {
                "organization_id": str(organization_id),
                "user_id": str(owner_user_id),
            },
        )
    ).scalar_one()
    tenant = TenantContext(
        organization_id=organization_id,
        user_id=owner_user_id,
        member_id=owner_member_id,
    )
    await _grant_role(db_session, tenant, tenant.member_id, "administrator")

    operator_user_id, operator_member_id, operator_email = (
        await _create_organization_member(db_session, tenant, full_name="Operator Referee")
    )
    await _grant_role(db_session, tenant, operator_member_id, "referee")
    await _grant_role(db_session, tenant, operator_member_id, "operator")

    viewer_user_id, viewer_member_id, viewer_email = await _create_organization_member(
        db_session, tenant, full_name="No Role"
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        listing = await client.get("/api/v1/organizations/members")
        status = await client.patch(
            f"/api/v1/organizations/members/{operator_member_id}/status",
            json={"is_active": True},
        )
        owner_reassignment = await client.patch(
            f"/api/v1/organizations/members/{tenant.member_id}/role",
            json={"role_code": "viewer"},
        )

    assert listing.status_code == 200, describe_response("list members returns 200", listing)
    roles = {row["email"]: row["role_code"] for row in listing.json()}
    assert roles[owner_email] == "owner"
    assert roles[operator_email] == "operator"
    assert roles[viewer_email] == "viewer"

    assert status.status_code == 200, describe_response("update member status returns 200", status)
    assert status.json()["role_code"] == "operator"
    assert owner_reassignment.status_code == 409, describe_response(
        "reassign the owner role returns 409", owner_reassignment
    )

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        owner_access = await client.get("/api/v1/organizations/current/access")
    async with _invitation_api(
        db_session,
        tenant,
        monkeypatch,
        member_id=operator_member_id,
        user_id=operator_user_id,
    ) as client:
        operator_access = await client.get("/api/v1/organizations/current/access")
    async with _invitation_api(
        db_session,
        tenant,
        monkeypatch,
        member_id=viewer_member_id,
        user_id=viewer_user_id,
    ) as client:
        viewer_access = await client.get("/api/v1/organizations/current/access")

    assert owner_access.status_code == 200, describe_response(
        "owner access returns 200", owner_access
    )
    assert owner_access.json()["role_code"] == "owner"
    assert operator_access.status_code == 200, describe_response(
        "operator access returns 200", operator_access
    )
    assert operator_access.json()["role_code"] == "operator"
    assert viewer_access.status_code == 200, describe_response(
        "viewer access returns 200", viewer_access
    )
    assert viewer_access.json()["role_code"] == "viewer"
    assert viewer_access.json()["permissions"] == []

    operator_context = AuthContext(
        user_id=operator_user_id,
        organization_id=tenant.organization_id,
        organization_user_id=operator_member_id,
    )
    await set_rls_context(db_session, tenant.organization_id, operator_user_id)
    # Autorización aditiva por permisos: el rol mostrado no la sustituye.
    await require_permission(
        db_session, operator_context, "CLOSE_MATCH_REPORT", match_id=uuid4()
    )


# --- 009 / RF-001, RF-002 y RF-004: reapertura de una invitación revocada -----


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _token_from_invite_url(invite_url: str | None) -> str:
    assert invite_url, "la respuesta debe incluir el enlace nuevo"
    return unquote(invite_url.rsplit("/", 1)[-1])


async def _stored_invitation_details(
    session: AsyncSession,
    tenant: TenantContext,
    email: str,
) -> list[dict]:
    await set_rls_context(session, tenant.organization_id, tenant.user_id)
    result = await session.execute(
        text("""
            SELECT id, status, expires_at, updated_at, revoked_at, token_hash
            FROM organization_invitations
            WHERE organization_id = :organization_id
              AND email = :email
            ORDER BY created_at, id
        """),
        {"organization_id": str(tenant.organization_id), "email": email},
    )
    return [dict(row) for row in result.mappings().all()]


async def _invitation_audit_entries(
    session: AsyncSession,
    tenant: TenantContext,
) -> list[dict]:
    await set_rls_context(session, tenant.organization_id, tenant.user_id)
    result = await session.execute(
        text("""
            SELECT entity_type, entity_id, action, payload, performed_by_member_id
            FROM administrative_audit_logs
            WHERE organization_id = :organization_id
            ORDER BY performed_at, id
        """),
        {"organization_id": str(tenant.organization_id)},
    )
    entries = [dict(row) for row in result.mappings().all()]
    for entry in entries:
        if isinstance(entry["payload"], str):
            entry["payload"] = json.loads(entry["payload"])
    return entries


async def _revoke_through_api(
    session: AsyncSession,
    tenant: TenantContext,
    monkeypatch,
    invitation_id: UUID,
) -> None:
    async with _invitation_api(session, tenant, monkeypatch) as client:
        response = await client.delete(
            f"/api/v1/organizations/invitations/{invitation_id}"
        )
    assert response.status_code == 204, describe_response(
        "revoke through the api returns 204", response
    )


@pytest.mark.asyncio
async def test_reopening_a_revoked_invitation_reuses_the_row_and_rotates_the_link(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Reopen")
    email = f"reopen-{uuid4().hex}@example.com"
    old_token = f"reopen-old-{uuid4().hex}"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=old_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, invitation["id"])

    # CURRENT_TIMESTAMP es el inicio de la transacción de la prueba: se retrasa
    # updated_at para que la reescritura sea observable dentro de la misma.
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await set_rls_context(db_session, tenant.organization_id, tenant.user_id)
    await db_session.execute(
        text("""
            UPDATE organization_invitations
            SET updated_at = :past
            WHERE id = :invitation_id
        """),
        {"past": past, "invitation_id": str(invitation["id"])},
    )
    before = await _stored_invitation_details(db_session, tenant, email)
    assert len(before) == 1
    assert before[0]["status"] == "revoked"
    assert before[0]["revoked_at"] is not None
    old_token_hash = before[0]["token_hash"]

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation['id']}/reopen"
        )
        old_preview = await client.get(f"/api/v1/invitations/{old_token}")
        new_token = _token_from_invite_url(response.json().get("invite_url"))
        new_preview = await client.get(f"/api/v1/invitations/{new_token}")

    assert response.status_code == 200, describe_response(
        "reopen a revoked invitation returns 200", response
    )
    body = response.json()
    assert body["id"] == str(invitation["id"])
    assert body["email"] == email
    assert body["role_code"] == "operator"
    assert body["status"] == "pending"
    assert body["revoked_at"] is None
    assert new_token != old_token
    assert _as_datetime(body["expires_at"]) > before[0]["expires_at"]
    assert _as_datetime(body["updated_at"]) > past

    assert old_preview.status_code == 404, describe_response(
        "old link preview returns 404", old_preview
    )
    assert new_preview.status_code == 200, describe_response(
        "new link preview returns 200", new_preview
    )
    assert new_preview.json()["invitation_id"] == str(invitation["id"])
    assert new_preview.json()["status"] == "pending"

    after = await _stored_invitation_details(db_session, tenant, email)
    assert len(after) == 1
    assert after[0]["id"] == invitation["id"]
    assert after[0]["status"] == "pending"
    assert after[0]["revoked_at"] is None
    assert after[0]["token_hash"] != old_token_hash
    assert after[0]["expires_at"] > before[0]["expires_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_state", ["pending", "expired", "accepted"])
async def test_reopening_an_invitation_that_is_not_revoked_returns_409_without_writing(
    db_session: AsyncSession, tenant_factory, monkeypatch, stored_state
):
    tenant = await tenant_factory(f"Invitation Reopen {stored_state}")
    email = f"reopen-not-revoked-{uuid4().hex}@example.com"
    token = f"reopen-not-revoked-{uuid4().hex}"
    expires_at = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
        if stored_state == "expired"
        else datetime.now(timezone.utc) + timedelta(hours=1)
    )
    invitation = await _insert_tenant_invitation(
        db_session, tenant, email=email, token=token, expires_at=expires_at
    )
    if stored_state == "accepted":
        async with _invitation_api(db_session, tenant, monkeypatch) as client:
            accepted = await client.post(
                f"/api/v1/invitations/{token}/accept",
                json={"password": "Secret1234!", "full_name": "Reopen Accepted"},
            )
        assert accepted.status_code == 200, describe_response(
            "accept before reopen not revoked returns 200", accepted
        )

    before = await _stored_invitation_details(db_session, tenant, email)

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation['id']}/reopen"
        )

    assert response.status_code == 409, describe_response(
        "reopen a not revoked invitation returns 409", response
    )
    body = response.json()
    assert body["code"] == "INVITATION_NOT_REVOKED"
    assert isinstance(body["detail"], str) and body["detail"]
    assert "invite_url" not in body

    after = await _stored_invitation_details(db_session, tenant, email)
    assert after == before
    # La aceptación conserva su entrada; un 409 no añade ninguna de reapertura.
    entries = await _invitation_audit_entries(db_session, tenant)
    assert [entry for entry in entries if entry["action"] == "REOPEN_INVITATION"] == []


@pytest.mark.asyncio
async def test_reopening_with_another_live_pending_invitation_returns_409_without_writing(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Reopen Conflict")
    email = f"reopen-other-pending-{uuid4().hex}@example.com"
    revoked = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-other-pending-old-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, revoked["id"])
    live = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-other-pending-live-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    before = await _stored_invitation_details(db_session, tenant, email)
    assert sorted(row["status"] for row in before) == ["pending", "revoked"]

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{revoked['id']}/reopen"
        )

    assert response.status_code == 409, describe_response(
        "reopen with another live pending returns 409", response
    )
    assert response.json()["code"] == "INVITATION_OTHER_PENDING"

    after = await _stored_invitation_details(db_session, tenant, email)
    assert after == before
    assert {row["id"]: row["status"] for row in after}[live["id"]] == "pending"
    assert await _invitation_audit_entries(db_session, tenant) == []


@pytest.mark.asyncio
async def test_reopening_materializes_another_expired_pending_in_the_same_transaction(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Reopen Materialization")
    email = f"reopen-materialize-{uuid4().hex}@example.com"
    revoked = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-materialize-old-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, revoked["id"])
    stale = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-materialize-stale-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    before = await _stored_invitation_details(db_session, tenant, email)
    assert {row["id"]: row["status"] for row in before} == {
        revoked["id"]: "revoked",
        stale["id"]: "pending",
    }

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{revoked['id']}/reopen"
        )

    assert response.status_code == 200, describe_response(
        "reopen materializing an expired pending returns 200", response
    )
    assert response.json()["id"] == str(revoked["id"])
    assert response.json()["status"] == "pending"

    after = await _stored_invitation_details(db_session, tenant, email)
    statuses = {row["id"]: row["status"] for row in after}
    assert statuses == {revoked["id"]: "pending", stale["id"]: "expired"}
    assert list(statuses.values()).count("pending") == 1

    entries = await _invitation_audit_entries(db_session, tenant)
    assert len(entries) == 1
    assert str(entries[0]["entity_id"]) == str(revoked["id"])


@pytest.mark.asyncio
async def test_reopen_failure_after_materializing_rolls_back_both_writes(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    """RF-001: un fallo tras materializar y reabrir revierte las dos escrituras.

    El doble de ``record_invitation_audit`` se ejecuta dentro de la transacción
    de la petición, después de ``_materialize_expired_pending`` y del ``UPDATE``
    que reabre la revocada, y antes del cierre: lee ambas filas y el recuento de
    auditoría, y después lanza. El caso límite 5 exige una respuesta HTTP 500,
    no una excepción propagada (``raise_app_exceptions=False``).
    """

    tenant = await tenant_factory("Invitation Reopen Atomicity")
    email = f"reopen-atomic-{uuid4().hex}@example.com"
    revoked_token = f"reopen-atomic-old-{uuid4().hex}"
    revoked = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=revoked_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, revoked["id"])
    stale = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-atomic-stale-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )

    before = {
        row["id"]: row
        for row in await _stored_invitation_details(db_session, tenant, email)
    }
    assert set(before) == {revoked["id"], stale["id"]}
    assert before[revoked["id"]]["status"] == "revoked"
    assert before[stale["id"]]["status"] == "pending"
    revoked_token_hash = before[revoked["id"]]["token_hash"]

    observed: dict[str, object] = {}

    async def failing_audit(
        db,
        *,
        organization_id,
        member_id,
        invitation_id,
        action,
        payload,
    ):
        # Dentro de la transacción de la petición: las dos escrituras ya
        # ocurrieron, pero todavía no hay commit.
        materialized = await db.execute(
            text("SELECT status FROM organization_invitations WHERE id = :id"),
            {"id": str(stale["id"])},
        )
        observed["materialized_status"] = materialized.scalar_one()
        reopened = await db.execute(
            text("""
                SELECT status, token_hash
                FROM organization_invitations
                WHERE id = :id
            """),
            {"id": str(revoked["id"])},
        )
        reopened_row = reopened.mappings().one()
        observed["reopened_status"] = reopened_row["status"]
        observed["reopened_token_hash"] = reopened_row["token_hash"]
        audit_rows = await db.execute(
            text("""
                SELECT count(*) AS total
                FROM administrative_audit_logs
                WHERE entity_id = :entity_id
            """),
            {"entity_id": str(invitation_id)},
        )
        observed["audit_rows"] = audit_rows.scalar_one()
        observed["action"] = action
        raise RuntimeError("fallo inducido: después de materializar y antes del commit")

    monkeypatch.setattr(invitations_router, "record_invitation_audit", failing_audit)

    sent: list[dict] = []

    async def recording_email(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})

    async with _invitation_api(
        db_session, tenant, monkeypatch, raise_app_exceptions=False
    ) as client:
        # Después del que instala `_invitation_api`: el envío se registra, no se omite.
        monkeypatch.setattr(invitations_router, "send_invitation_email", recording_email)
        response = await client.post(
            f"/api/v1/organizations/invitations/{revoked['id']}/reopen"
        )

    assert response.status_code == 500, describe_response(
        "reopen with an induced failure after materializing returns 500", response
    )
    # El cuerpo es exactamente el 500 saneado de Starlette: no lleva invite_url
    # (ni nada más) y el token revocado no aparece.
    assert response.text == "Internal Server Error"
    assert revoked_token not in response.text

    # El fallo ocurrió en el punto declarado: las dos escrituras eran visibles.
    assert observed, "el doble de auditoría debe ejecutarse dentro de la petición"
    assert observed["action"] == "REOPEN_INVITATION"
    assert observed["materialized_status"] == "expired"
    assert observed["reopened_status"] == "pending"
    assert observed["reopened_token_hash"] != revoked_token_hash
    assert observed["audit_rows"] == 0

    after = {
        row["id"]: row
        for row in await _stored_invitation_details(db_session, tenant, email)
    }
    assert after == before
    assert await _invitation_audit_entries(db_session, tenant) == []
    assert sent == []


@pytest.mark.asyncio
async def test_reopening_without_member_management_permission_returns_403_without_writing(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Reopen Forbidden")
    email = f"reopen-forbidden-{uuid4().hex}@example.com"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-forbidden-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, invitation["id"])
    viewer_user_id, viewer_member_id, _ = await _create_organization_member(
        db_session, tenant, full_name="Reopen Viewer"
    )

    before = await _stored_invitation_details(db_session, tenant, email)

    async with _invitation_api(
        db_session,
        tenant,
        monkeypatch,
        member_id=viewer_member_id,
        user_id=viewer_user_id,
    ) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation['id']}/reopen"
        )

    assert response.status_code == 403, describe_response(
        "reopen without member management permission returns 403", response
    )
    assert "invite_url" not in response.text

    after = await _stored_invitation_details(db_session, tenant, email)
    assert after == before
    assert await _invitation_audit_entries(db_session, tenant) == []


@pytest.mark.asyncio
async def test_reopening_an_invitation_from_another_organization_returns_404(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant_a = await tenant_factory("Invitation Reopen Foreign A")
    tenant_b = await tenant_factory("Invitation Reopen Foreign B")
    email = f"reopen-foreign-{uuid4().hex}@example.com"
    invitation_b = await _insert_tenant_invitation(
        db_session,
        tenant_b,
        email=email,
        token=f"reopen-foreign-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant_b, monkeypatch, invitation_b["id"])

    before = await _stored_invitation_details(db_session, tenant_b, email)

    async with _invitation_api(db_session, tenant_a, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation_b['id']}/reopen"
        )

    assert response.status_code == 404, describe_response(
        "reopen a foreign invitation returns 404", response
    )

    after = await _stored_invitation_details(db_session, tenant_b, email)
    assert after == before
    assert await _invitation_audit_entries(db_session, tenant_b) == []


@pytest.mark.asyncio
async def test_reopening_records_exactly_one_audit_entry_and_conflicts_record_none(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Reopen Audit")
    reopened_email = f"reopen-audit-{uuid4().hex}@example.com"
    reopened = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=reopened_email,
        token=f"reopen-audit-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, reopened["id"])

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        success = await client.post(
            f"/api/v1/organizations/invitations/{reopened['id']}/reopen"
        )
    assert success.status_code == 200, describe_response(
        "reopen audit success returns 200", success
    )

    live_token = f"reopen-audit-live-{uuid4().hex}"
    live_email = f"reopen-audit-live-{uuid4().hex}@example.com"
    live = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=live_email,
        token=live_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        conflict = await client.post(
            f"/api/v1/organizations/invitations/{live['id']}/reopen"
        )
    assert conflict.status_code == 409, describe_response(
        "reopen live audit conflict returns 409", conflict
    )
    assert conflict.json()["code"] == "INVITATION_NOT_REVOKED"

    entries = await _invitation_audit_entries(db_session, tenant)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entity_type"] == "organization_invitations"
    assert entry["action"] == "REOPEN_INVITATION"
    assert str(entry["entity_id"]) == str(reopened["id"])
    assert str(entry["performed_by_member_id"]) == str(tenant.member_id)
    assert entry["payload"] == {"previous_status": "revoked", "role_code": "operator"}
    serialized_payload = json.dumps(entry["payload"])
    assert reopened_email not in serialized_payload
    assert live_email not in serialized_payload
    assert "token" not in serialized_payload


@pytest.mark.asyncio
async def test_reopening_with_a_failing_email_returns_502_and_keeps_the_row_pending(
    db_session: AsyncSession, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Invitation Reopen Mail Failure")
    email = f"reopen-mail-failure-{uuid4().hex}@example.com"
    invitation = await _insert_tenant_invitation(
        db_session,
        tenant,
        email=email,
        token=f"reopen-mail-failure-{uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await _revoke_through_api(db_session, tenant, monkeypatch, invitation["id"])
    before = await _stored_invitation_details(db_session, tenant, email)

    async def failing_email(*args, **kwargs):
        raise OSError("el servidor SMTP no está disponible")

    async with _invitation_api(db_session, tenant, monkeypatch) as client:
        monkeypatch.setattr(invitations_router, "send_invitation_email", failing_email)
        response = await client.post(
            f"/api/v1/organizations/invitations/{invitation['id']}/reopen"
        )

    assert response.status_code == 502, describe_response(
        "reopen with a failing email returns 502", response
    )

    after = await _stored_invitation_details(db_session, tenant, email)
    assert len(after) == 1
    assert after[0]["status"] == "pending"
    assert after[0]["revoked_at"] is None
    assert after[0]["token_hash"] != before[0]["token_hash"]
