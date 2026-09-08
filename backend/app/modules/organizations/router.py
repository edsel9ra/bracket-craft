from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.security import get_current_user_id
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.organizations.schemas import CurrentOrganizationResponse, OrganizationSummaryResponse


router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("")
async def list_organizations(
    user_id=Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, None, user_id)
        result = await db.execute(
            text("""
                SELECT id, name, slug, organization_user_id
                FROM list_user_organizations()
            """),
        )
        return [dict(row) for row in result.mappings().all()]


@router.get("/current", response_model=CurrentOrganizationResponse)
async def current_organization(
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> CurrentOrganizationResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        result = await db.execute(text("SELECT id, name, slug FROM get_current_organization()"))
        organization = result.mappings().one_or_none()
        if organization is None:
            raise HTTPException(status_code=404, detail="Organización no encontrada")
        return dict(organization)
