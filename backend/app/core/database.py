import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


# Session and pool limits are backend constants (P-4): no environment variable,
# no Compose change. They apply per process: API worker, outbox worker and seed.
DB_STATEMENT_TIMEOUT_MS = 15_000
DB_IDLE_IN_TRANSACTION_TIMEOUT_MS = 30_000
DB_POOL_SIZE = 10
DB_MAX_OVERFLOW = 10
DB_POOL_TIMEOUT_SECONDS = 10

logger = logging.getLogger(__name__)


def engine_options() -> dict:
    """Return the explicit pool and server-session options for the engine."""

    return {
        "pool_size": DB_POOL_SIZE,
        "max_overflow": DB_MAX_OVERFLOW,
        "pool_timeout": DB_POOL_TIMEOUT_SECONDS,
        "connect_args": {
            "server_settings": {
                "statement_timeout": str(DB_STATEMENT_TIMEOUT_MS),
                "idle_in_transaction_session_timeout": str(
                    DB_IDLE_IN_TRANSACTION_TIMEOUT_MS
                ),
            }
        },
    }


def log_database_configuration() -> None:
    """Log the effective values once at startup; never the URL or credentials."""

    logger.info(
        "Configuración de base de datos efectiva: statement_timeout=%dms "
        "idle_in_transaction_session_timeout=%dms pool_size=%d "
        "max_overflow=%d pool_timeout=%ds",
        DB_STATEMENT_TIMEOUT_MS,
        DB_IDLE_IN_TRANSACTION_TIMEOUT_MS,
        DB_POOL_SIZE,
        DB_MAX_OVERFLOW,
        DB_POOL_TIMEOUT_SECONDS,
    )


settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    **engine_options(),
)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def validate_application_role() -> None:
    """Fail closed if the application connects with a role that bypasses RLS."""

    async with engine.connect() as connection:
        result = await connection.execute(
            text("""
                SELECT r.rolsuper, r.rolbypassrls
                FROM pg_roles r
                WHERE r.rolname = CURRENT_USER
            """)
        )
        role = result.mappings().one_or_none()
    if role is None or role["rolsuper"] or role["rolbypassrls"]:
        raise RuntimeError("La conexión de la aplicación debe usar un rol no superusuario sin BYPASSRLS")


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
