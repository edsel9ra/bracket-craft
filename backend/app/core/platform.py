from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.security import get_current_user_id


@dataclass(frozen=True)
class PlatformContext:
    user_id: UUID
    role_code: str


async def get_platform_context(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PlatformContext:
    async with db.begin():
        await set_rls_context(db, None, user_id)
        result = await db.execute(text("SELECT user_id, role_code FROM get_platform_admin_context()"))
        context = result.mappings().one_or_none()

    if context is None or context["role_code"] is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrador de plataforma requerido")
    return PlatformContext(user_id=context["user_id"], role_code=context["role_code"])


def require_platform_write(context: PlatformContext) -> None:
    if context.role_code != "platform_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso de escritura de plataforma requerido")
