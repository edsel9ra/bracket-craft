import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.database import set_rls_context
from app.core.permissions import require_permission
from app.core.tenancy import AuthContext
from app.modules.invitations.router import _token_hash


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
