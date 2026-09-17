import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db, set_rls_context
from app.core.email import send_invitation_email
from app.core.permissions import require_permission
from app.core.security import (
    create_user_session,
    get_optional_current_user_id,
    hash_password,
)
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.invitations.schemas import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    CreateInvitationRequest,
    InvitationPreviewResponse,
    InvitationResponse,
    MemberResponse,
    OrganizationAccessResponse,
    UpdateMemberActiveRequest,
    UpdateMemberRoleRequest,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["invitations", "members"])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _invite_url(token: str) -> str:
    return f"{get_settings().frontend_base_url.rstrip('/')}/invitations/{quote(token, safe='')}"


def _db_error_code(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


async def _require_member_management(db: AsyncSession, context: AuthContext) -> None:
    try:
        await require_permission(db, context, "MANAGE_MEMBERS")
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


async def _load_invitation_for_email(
    db: AsyncSession,
    context: AuthContext,
    invitation_id: UUID,
) -> dict:
    result = await db.execute(
        text("""
            SELECT i.id, i.organization_id, i.email, i.role_code, i.status,
                   i.expires_at, i.invited_by_member_id, i.accepted_by_user_id,
                   i.accepted_at, i.revoked_at, i.created_at, i.updated_at
            FROM organization_invitations i
            WHERE i.id = :invitation_id
              AND i.organization_id = :organization_id
            FOR UPDATE
        """),
        {"invitation_id": str(invitation_id), "organization_id": str(context.organization_id)},
    )
    invitation = result.mappings().one_or_none()
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitación no encontrada")
    return dict(invitation)


def _invitation_payload(row: dict, invite_url: str | None = None) -> dict:
    payload = {
        key: row[key]
        for key in (
            "id",
            "organization_id",
            "email",
            "role_code",
            "expires_at",
            "status",
            "invited_by_member_id",
            "accepted_by_user_id",
            "accepted_at",
            "revoked_at",
            "created_at",
            "updated_at",
        )
    }
    payload["invite_url"] = invite_url
    return payload


@router.post("/organizations/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: CreateInvitationRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    settings = get_settings()
    email = str(payload.email).lower()
    raw_token = secrets.token_urlsafe(32)
    token_hash = _token_hash(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.invitation_expire_hours)

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        organization_result = await db.execute(text("SELECT name FROM get_current_organization()"))
        organization_name = organization_result.scalar_one_or_none()
        if organization_name is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")
        try:
            result = await db.execute(
                text("""
                    INSERT INTO organization_invitations
                        (organization_id, email, role_code, token_hash, token_encrypted,
                         expires_at, invited_by_member_id)
                    VALUES
                        (:organization_id, LOWER(:email), :role_code, :token_hash,
                         pgp_sym_encrypt(:token, :encryption_key), :expires_at, :member_id)
                    RETURNING id, organization_id, email, role_code, expires_at, status,
                              invited_by_member_id, accepted_by_user_id, accepted_at,
                              revoked_at, created_at, updated_at
                """),
                {
                    "organization_id": str(context.organization_id),
                    "email": email,
                    "role_code": payload.role_code,
                    "token_hash": token_hash,
                    "token": raw_token,
                    "encryption_key": settings.invitation_token_key,
                    "expires_at": expires_at,
                    "member_id": str(context.organization_user_id),
                },
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una invitación pendiente para ese email",
            ) from exc
        invitation = dict(result.mappings().one())

    invite_url = _invite_url(raw_token)
    try:
        await send_invitation_email(email, organization_name, payload.role_code, invite_url, expires_at)
    except (OSError, smtplib.SMTPException) as exc:
        logger.exception("No se pudo enviar la invitación %s", invitation["id"])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo enviar el correo de invitación") from exc
    return _invitation_payload(invitation, invite_url)


@router.get("/organizations/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[InvitationResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        await db.execute(
            text("""
                UPDATE organization_invitations
                SET status = 'expired', updated_at = CURRENT_TIMESTAMP
                WHERE organization_id = :organization_id
                  AND status = 'pending'
                  AND expires_at <= CURRENT_TIMESTAMP
            """),
            {"organization_id": str(context.organization_id)},
        )
        result = await db.execute(
            text("""
                SELECT id, organization_id, email, role_code, expires_at, status,
                       invited_by_member_id, accepted_by_user_id, accepted_at,
                       revoked_at, created_at, updated_at
                FROM organization_invitations
                WHERE organization_id = :organization_id
                ORDER BY created_at DESC, id DESC
            """),
            {"organization_id": str(context.organization_id)},
        )
        return [_invitation_payload(dict(row)) for row in result.mappings().all()]


@router.post("/organizations/invitations/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation(
    invitation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.invitation_expire_hours)
    token_hash = _token_hash(raw_token)

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        invitation = await _load_invitation_for_email(db, context, invitation_id)
        if invitation["status"] == "accepted":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Una invitación aceptada no se puede reenviar")
        result = await db.execute(
            text("""
                UPDATE organization_invitations
                SET token_hash = :token_hash,
                    token_encrypted = pgp_sym_encrypt(:token, :encryption_key),
                    expires_at = :expires_at,
                    status = 'pending',
                    revoked_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :invitation_id
                RETURNING id, organization_id, email, role_code, expires_at, status,
                          invited_by_member_id, accepted_by_user_id, accepted_at,
                          revoked_at, created_at, updated_at
            """),
            {
                "invitation_id": str(invitation_id),
                "token_hash": token_hash,
                "token": raw_token,
                "encryption_key": settings.invitation_token_key,
                "expires_at": expires_at,
            },
        )
        updated = dict(result.mappings().one())
        organization_result = await db.execute(text("SELECT name FROM get_current_organization()"))
        organization_name = organization_result.scalar_one_or_none()
        if organization_name is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organización no encontrada")

    invite_url = _invite_url(raw_token)
    try:
        await send_invitation_email(
            updated["email"],
            organization_name,
            updated["role_code"],
            invite_url,
            expires_at,
        )
    except (OSError, smtplib.SMTPException) as exc:
        logger.exception("No se pudo reenviar la invitación %s", invitation_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo enviar el correo de invitación") from exc
    return _invitation_payload(updated, invite_url)


@router.delete("/organizations/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        invitation = await _load_invitation_for_email(db, context, invitation_id)
        if invitation["status"] != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La invitación ya no está pendiente")
        await db.execute(
            text("""
                UPDATE organization_invitations
                SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = :invitation_id AND organization_id = :organization_id
            """),
            {"invitation_id": str(invitation_id), "organization_id": str(context.organization_id)},
        )


@router.get("/invitations/{token}", response_model=InvitationPreviewResponse)
async def preview_invitation(token: str, db: AsyncSession = Depends(get_db)) -> InvitationPreviewResponse:
    async with db.begin():
        result = await db.execute(
            text("SELECT * FROM get_organization_invitation_by_token(:token_hash)"),
            {"token_hash": _token_hash(token)},
        )
        invitation = result.mappings().one_or_none()
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitación no encontrada")
    return dict(invitation)


@router.post("/invitations/{token}/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    token: str,
    payload: AcceptInvitationRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user_id: UUID | None = Depends(get_optional_current_user_id),
) -> AcceptInvitationResponse:
    token_hash = _token_hash(token)
    async with db.begin():
        preview_result = await db.execute(
            text("SELECT * FROM get_organization_invitation_by_token(:token_hash)"),
            {"token_hash": token_hash},
        )
        preview = preview_result.mappings().one_or_none()
        if preview is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitación no encontrada")
        if preview["status"] != "pending":
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="La invitación ya no está disponible")
        if preview["requires_login"] and current_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Debe iniciar sesión con el email de la invitación antes de aceptarla",
            )

        await set_rls_context(db, None, current_user_id)
        try:
            result = await db.execute(
                text("""
                    SELECT *
                    FROM accept_organization_invitation(
                        :token_hash,
                        :password_hash,
                        :full_name
                    )
                """),
                {
                    "token_hash": token_hash,
                    "password_hash": hash_password(payload.password) if not preview["requires_login"] and payload.password else None,
                    "full_name": payload.full_name,
                },
            )
            accepted = dict(result.mappings().one())
            access_token = None
            if accepted["created_user"]:
                access_token = await create_user_session(db, accepted["user_id"])
        except DBAPIError as exc:
            code = _db_error_code(exc)
            if code == "42501":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El usuario autenticado no coincide con la invitación") from exc
            if code == "P0001":
                raise HTTPException(status_code=status.HTTP_410_GONE, detail="La invitación ya no está disponible") from exc
            if code == "22023":
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Define una contraseña y un nombre para crear la cuenta") from exc
            if code == "23505":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El usuario ya pertenece a la organización") from exc
            raise

    if access_token:
        from app.core.security import set_auth_cookie

        set_auth_cookie(response, access_token)
    return {
        "access_token": access_token,
        "user_id": accepted["user_id"],
        "organization_id": accepted["organization_id"],
        "organization_user_id": accepted["organization_user_id"],
        "role_code": accepted["role_code"],
        "created_user": accepted["created_user"],
    }


@router.get("/organizations/current/access", response_model=OrganizationAccessResponse)
async def current_access(
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> OrganizationAccessResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        result = await db.execute(
            text("""
                SELECT rd.code AS role_code, r.permissions
                FROM organization_user_roles our
                JOIN roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
                JOIN role_definitions rd ON rd.id = r.role_definition_id
                WHERE our.organization_id = :organization_id
                  AND our.organization_user_id = :organization_user_id
                ORDER BY CASE rd.code
                    WHEN 'owner' THEN 1
                    WHEN 'administrator' THEN 2
                    WHEN 'operator' THEN 3
                    WHEN 'referee' THEN 4
                    ELSE 5
                END
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "organization_user_id": str(context.organization_user_id),
            },
        )
        access = result.mappings().one_or_none()
    if access is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol activo no encontrado")
    return {
        "organization_id": context.organization_id,
        "organization_user_id": context.organization_user_id,
        "user_id": context.user_id,
        "role_code": access["role_code"],
        "permissions": list(access["permissions"] or []),
    }


@router.get("/organizations/members", response_model=list[MemberResponse])
async def list_members(
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        result = await db.execute(
            text("""
                SELECT ou.id AS organization_user_id,
                       u.id AS user_id,
                       u.email,
                       u.full_name,
                       ou.is_active,
                       COALESCE(MIN(rd.code), 'viewer') AS role_code,
                       ou.created_at
                FROM organization_users ou
                JOIN users u ON u.id = ou.user_id
                LEFT JOIN organization_user_roles our
                  ON our.organization_user_id = ou.id
                 AND our.organization_id = ou.organization_id
                LEFT JOIN roles r
                  ON r.id = our.role_id
                 AND r.organization_id = ou.organization_id
                LEFT JOIN role_definitions rd ON rd.id = r.role_definition_id
                WHERE ou.organization_id = :organization_id
                GROUP BY ou.id, u.id
                ORDER BY u.full_name, u.email
            """),
            {"organization_id": str(context.organization_id)},
        )
        return [dict(row) for row in result.mappings().all()]


@router.patch("/organizations/members/{organization_user_id}/role", response_model=MemberResponse)
async def update_member_role(
    organization_user_id: UUID,
    payload: UpdateMemberRoleRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        target_result = await db.execute(
            text("""
                SELECT ou.id, ou.user_id,
                       COALESCE((
                           SELECT rd.code
                           FROM organization_user_roles our
                           JOIN roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
                           JOIN role_definitions rd ON rd.id = r.role_definition_id
                           WHERE our.organization_user_id = ou.id
                             AND our.organization_id = ou.organization_id
                           ORDER BY CASE rd.code
                               WHEN 'owner' THEN 1
                               WHEN 'administrator' THEN 2
                               WHEN 'operator' THEN 3
                               WHEN 'referee' THEN 4
                               ELSE 5
                           END
                           LIMIT 1
                       ), 'viewer') AS role_code
                FROM organization_users ou
                WHERE ou.id = :member_id AND ou.organization_id = :organization_id
                FOR UPDATE OF ou
            """),
            {"member_id": str(organization_user_id), "organization_id": str(context.organization_id)},
        )
        target = target_result.mappings().one_or_none()
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Miembro no encontrado")
        if target["role_code"] == "owner":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El rol owner no se puede reasignar")

        role_result = await db.execute(
            text("""
                INSERT INTO roles (organization_id, role_definition_id, name, permissions)
                SELECT :organization_id, rd.id, rd.name, rd.system_permissions
                FROM role_definitions rd
                WHERE rd.code = :role_code
                ON CONFLICT (organization_id, name) DO UPDATE
                    SET role_definition_id = EXCLUDED.role_definition_id,
                        permissions = EXCLUDED.permissions
                RETURNING id
            """),
            {"organization_id": str(context.organization_id), "role_code": payload.role_code},
        )
        role_id = role_result.scalar_one_or_none()
        if role_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rol inválido")
        await db.execute(
            text("DELETE FROM organization_user_roles WHERE organization_user_id = :member_id AND organization_id = :organization_id"),
            {"member_id": str(organization_user_id), "organization_id": str(context.organization_id)},
        )
        await db.execute(
            text("""
                INSERT INTO organization_user_roles (organization_id, organization_user_id, role_id)
                VALUES (:organization_id, :member_id, :role_id)
            """),
            {
                "organization_id": str(context.organization_id),
                "member_id": str(organization_user_id),
                "role_id": str(role_id),
            },
        )
        await db.execute(
            text("""
                INSERT INTO administrative_audit_logs
                    (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
                VALUES (:organization_id, 'organization_users', :member_id, 'CHANGE_MEMBER_ROLE',
                        CAST(:payload AS jsonb), :actor_member_id)
            """),
            {
                "organization_id": str(context.organization_id),
                "member_id": str(organization_user_id),
                "payload": f'{{"role_code":"{payload.role_code}"}}',
                "actor_member_id": str(context.organization_user_id),
            },
        )
        return await _load_member(db, context.organization_id, organization_user_id)


@router.patch("/organizations/members/{organization_user_id}/status", response_model=MemberResponse)
async def update_member_status(
    organization_user_id: UUID,
    payload: UpdateMemberActiveRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_member_management(db, context)
        target_result = await db.execute(
            text("""
                SELECT ou.is_active,
                       COALESCE((
                           SELECT rd.code
                           FROM organization_user_roles our
                           JOIN roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
                           JOIN role_definitions rd ON rd.id = r.role_definition_id
                           WHERE our.organization_user_id = ou.id
                             AND our.organization_id = ou.organization_id
                           ORDER BY CASE rd.code
                               WHEN 'owner' THEN 1
                               WHEN 'administrator' THEN 2
                               WHEN 'operator' THEN 3
                               WHEN 'referee' THEN 4
                               ELSE 5
                           END
                           LIMIT 1
                       ), 'viewer') AS role_code
                FROM organization_users ou
                WHERE ou.id = :member_id AND ou.organization_id = :organization_id
                FOR UPDATE OF ou
            """),
            {"member_id": str(organization_user_id), "organization_id": str(context.organization_id)},
        )
        target = target_result.mappings().one_or_none()
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Miembro no encontrado")
        if not payload.is_active and target["role_code"] == "owner":
            active_owner_result = await db.execute(
                text("""
                    SELECT COUNT(*)
                    FROM organization_users ou
                    JOIN organization_user_roles our ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
                    JOIN roles r ON r.id = our.role_id AND r.organization_id = ou.organization_id
                    JOIN role_definitions rd ON rd.id = r.role_definition_id
                    WHERE ou.organization_id = :organization_id
                      AND ou.is_active = TRUE
                      AND rd.code = 'owner'
                """),
                {"organization_id": str(context.organization_id)},
            )
            if int(active_owner_result.scalar_one()) <= 1:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La organización debe conservar un owner activo")
        await db.execute(
            text("""
                UPDATE organization_users
                SET is_active = :is_active
                WHERE id = :member_id AND organization_id = :organization_id
            """),
            {
                "member_id": str(organization_user_id),
                "organization_id": str(context.organization_id),
                "is_active": payload.is_active,
            },
        )
        await db.execute(
            text("""
                INSERT INTO administrative_audit_logs
                    (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
                VALUES (:organization_id, 'organization_users', :member_id, 'SET_MEMBER_ACTIVE',
                        CAST(:payload AS jsonb), :actor_member_id)
            """),
            {
                "organization_id": str(context.organization_id),
                "member_id": str(organization_user_id),
                "payload": f'{{"is_active":{str(payload.is_active).lower()}}}',
                "actor_member_id": str(context.organization_user_id),
            },
        )
        return await _load_member(db, context.organization_id, organization_user_id)


async def _load_member(db: AsyncSession, organization_id: UUID, member_id: UUID) -> dict:
    result = await db.execute(
        text("""
            SELECT ou.id AS organization_user_id,
                   u.id AS user_id,
                   u.email,
                   u.full_name,
                   ou.is_active,
                   COALESCE(MIN(rd.code), 'viewer') AS role_code,
                   ou.created_at
            FROM organization_users ou
            JOIN users u ON u.id = ou.user_id
            LEFT JOIN organization_user_roles our
              ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
            LEFT JOIN roles r ON r.id = our.role_id AND r.organization_id = ou.organization_id
            LEFT JOIN role_definitions rd ON rd.id = r.role_definition_id
            WHERE ou.id = :member_id AND ou.organization_id = :organization_id
            GROUP BY ou.id, u.id
        """),
        {"member_id": str(member_id), "organization_id": str(organization_id)},
    )
    member = result.mappings().one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Miembro no encontrado")
    return dict(member)
