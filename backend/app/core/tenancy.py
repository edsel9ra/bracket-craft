from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.security import get_current_user_id


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    organization_id: UUID
    organization_user_id: UUID


async def get_auth_context(
    organization_id: UUID | None = Header(default=None, alias="X-Organization-ID"),
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe indicar X-Organization-ID",
        )

    async with db.begin():
        await set_rls_context(db, organization_id, user_id)
        membership_check = await db.execute(
            text("SELECT fn_verify_user_org_membership(:organization_id)"),
            {"organization_id": str(organization_id)},
        )
        if not membership_check.scalar_one():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Membresía no válida")
        result = await db.execute(
            text("""
                SELECT ou.id
                FROM organization_users ou
                WHERE ou.organization_id = :organization_id
                  AND ou.user_id = :user_id
                  AND ou.is_active = TRUE
                  AND EXISTS (
                      SELECT 1
                      FROM organization_user_roles our
                      JOIN roles r
                        ON r.id = our.role_id
                       AND r.organization_id = our.organization_id
                      WHERE our.organization_id = ou.organization_id
                        AND our.organization_user_id = ou.id
                  )
            """),
            {"organization_id": str(organization_id), "user_id": str(user_id)},
        )
        membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Membresía o rol activo no válido")

    return AuthContext(user_id=user_id, organization_id=organization_id, organization_user_id=membership)
