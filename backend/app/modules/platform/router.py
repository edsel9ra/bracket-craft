from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.platform import PlatformContext, get_platform_context, require_platform_write
from app.core.security import get_current_user_id
from app.modules.platform.schemas import (
    CreateMembershipRequest,
    OutboxReprocessRequest,
    PlatformListResponse,
    PlatformAccessResponse,
    SetActiveRequest,
)


router = APIRouter(prefix="/platform", tags=["platform-admin"])


def _translate_platform_error(exc: DBAPIError) -> HTTPException | None:
    code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    if code == "42501":
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso de plataforma requerido")
    if code == "23514":
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La operación viola una regla de seguridad")
    return None


async def _list_rows(
    db: AsyncSession,
    context: PlatformContext,
    statement: str,
    params: dict,
) -> list[dict]:
    async with db.begin():
        await set_rls_context(db, None, context.user_id)
        result = await db.execute(text(statement), params)
        return [dict(row) for row in result.mappings().all()]


async def _set_active(
    db: AsyncSession,
    context: PlatformContext,
    statement: str,
    params: dict,
) -> bool:
    require_platform_write(context)
    try:
        async with db.begin():
            await set_rls_context(db, None, context.user_id)
            result = await db.execute(text(statement), params)
            return bool(result.scalar_one())
    except DBAPIError as exc:
        translated = _translate_platform_error(exc)
        if translated:
            raise translated from exc
        raise


@router.get("/access", response_model=PlatformAccessResponse)
async def get_platform_access(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async with db.begin():
        await set_rls_context(db, None, user_id)
        result = await db.execute(text("SELECT role_code FROM get_platform_admin_context()"))
        context = result.mappings().one_or_none()
    return {"allowed": bool(context and context["role_code"])}


@router.get("/users", response_model=PlatformListResponse)
async def list_platform_users(
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=100),
) -> dict:
    rows = await _list_rows(
        db,
        context,
        "SELECT * FROM platform_list_users(:limit, :offset, :search)",
        {"limit": limit, "offset": offset, "search": search},
    )
    return {"items": rows, "limit": limit, "offset": offset}


@router.get("/organizations", response_model=PlatformListResponse)
async def list_platform_organizations(
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=100),
) -> dict:
    rows = await _list_rows(
        db,
        context,
        "SELECT * FROM platform_list_organizations(:limit, :offset, :search)",
        {"limit": limit, "offset": offset, "search": search},
    )
    return {"items": rows, "limit": limit, "offset": offset}


@router.get("/audit", response_model=PlatformListResponse)
async def list_platform_audit_logs(
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    rows = await _list_rows(
        db,
        context,
        "SELECT * FROM platform_list_audit_logs(:limit, :offset)",
        {"limit": limit, "offset": offset},
    )
    return {"items": rows, "limit": limit, "offset": offset}


@router.post("/outbox/reprocess", response_model=dict)
async def reprocess_outbox(
    payload: OutboxReprocessRequest,
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    require_platform_write(context)
    async with db.begin():
        await set_rls_context(db, None, context.user_id)
        result = await db.execute(
            text("SELECT requeue_outbox_events(:limit)"),
            {"limit": payload.limit},
        )
        return {"requeued": int(result.scalar_one())}


@router.get("/organizations/{organization_id}/members", response_model=PlatformListResponse)
async def list_platform_memberships(
    organization_id: UUID,
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    rows = await _list_rows(
        db,
        context,
        "SELECT * FROM platform_list_memberships(:organization_id, :limit, :offset)",
        {"organization_id": str(organization_id), "limit": limit, "offset": offset},
    )
    return {"items": rows, "limit": limit, "offset": offset}


@router.post("/organizations/{organization_id}/members", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_platform_membership(
    organization_id: UUID,
    payload: CreateMembershipRequest,
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    require_platform_write(context)
    try:
        async with db.begin():
            await set_rls_context(db, None, context.user_id)
            result = await db.execute(
                text("SELECT platform_create_membership(:organization_id, :user_id, :role_code)"),
                {
                    "organization_id": str(organization_id),
                    "user_id": str(payload.user_id),
                    "role_code": payload.role_code,
                },
            )
            membership_id = result.scalar_one()
    except DBAPIError as exc:
        translated = _translate_platform_error(exc)
        if translated:
            raise translated from exc
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code == "23505":
            raise HTTPException(status_code=409, detail="El usuario ya pertenece a la organización") from exc
        raise
    return {"id": str(membership_id), "organization_id": str(organization_id), "user_id": str(payload.user_id)}


@router.patch("/users/{user_id}/status", response_model=dict)
async def set_platform_user_status(
    user_id: UUID,
    payload: SetActiveRequest,
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    updated = await _set_active(
        db,
        context,
        "SELECT platform_set_user_active(:user_id, :is_active)",
        {"user_id": str(user_id), "is_active": payload.is_active},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"id": str(user_id), "is_active": payload.is_active}


@router.patch("/organizations/{organization_id}/status", response_model=dict)
async def set_platform_organization_status(
    organization_id: UUID,
    payload: SetActiveRequest,
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    updated = await _set_active(
        db,
        context,
        "SELECT platform_set_organization_active(:organization_id, :is_active)",
        {"organization_id": str(organization_id), "is_active": payload.is_active},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Organización no encontrada")
    return {"id": str(organization_id), "is_active": payload.is_active}


@router.patch("/organizations/{organization_id}/members/{organization_user_id}/status", response_model=dict)
async def set_platform_membership_status(
    organization_id: UUID,
    organization_user_id: UUID,
    payload: SetActiveRequest,
    context: PlatformContext = Depends(get_platform_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    updated = await _set_active(
        db,
        context,
        "SELECT platform_set_membership_active(:organization_id, :organization_user_id, :is_active)",
        {
            "organization_id": str(organization_id),
            "organization_user_id": str(organization_user_id),
            "is_active": payload.is_active,
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Membresía no encontrada")
    return {"id": str(organization_user_id), "is_active": payload.is_active}
