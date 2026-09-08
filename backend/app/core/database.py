from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def set_rls_context(session: AsyncSession, organization_id: UUID | None, user_id: UUID | None) -> None:
    await session.execute(
        text("SELECT set_config('app.current_organization_id', :value, true)"),
        {"value": str(organization_id) if organization_id else ""},
    )
    await session.execute(
        text("SELECT set_config('app.current_user_id', :value, true)"),
        {"value": str(user_id) if user_id else ""},
    )


@asynccontextmanager
async def transaction(session: AsyncSession):
    async with session.begin():
        yield session
