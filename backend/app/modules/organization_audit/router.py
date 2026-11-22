from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.organization_audit.schemas import (
    OrganizationAuditActor,
    OrganizationAuditPage,
    OrganizationAuditQuery,
)
from app.modules.organization_audit.service import OrganizationAuditService

router = APIRouter(prefix="/organization-audit", tags=["organization-audit"])

# El mismo 403 que una membresía no válida: no revela si hay entradas (RF-002).
FORBIDDEN = "Membresía o rol activo no válido"


@router.get("", response_model=OrganizationAuditPage)
async def list_organization_audit(
    filters: OrganizationAuditQuery = Query(),
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    try:
        return await OrganizationAuditService(db).list(context, filters)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=FORBIDDEN) from exc


@router.get("/actors", response_model=list[OrganizationAuditActor])
async def list_organization_audit_actors(
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    try:
        return await OrganizationAuditService(db).actors(context)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=FORBIDDEN) from exc
