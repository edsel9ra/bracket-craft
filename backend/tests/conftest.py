"""Shared fixtures for the backend test suite.

The PostgreSQL fixtures are opt-in via ``RUN_DATABASE_TESTS=1`` and expect a
``DATABASE_URL`` that connects with the application role (``bracket_app``).
Migration tests also need ``DATABASE_ADMIN_URL`` with an administrator role;
when the database suite is enabled and that URL is missing, they fail loudly
instead of skipping. Each test runs inside a transaction that is rolled back at
the end, so tests create their own organizations and never depend on demo data
or execution order.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from db_helpers import (
    TenantContext,
    admin_database_url,
    application_database_url,
    create_tenant_owner,
    database_tests_enabled,
)


@pytest.fixture
def database_admin_url():
    """Return the administrator URL needed to apply migrations in a throwaway DB."""

    if not database_tests_enabled():
        pytest.skip("RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas")

    url = admin_database_url()
    if not url:
        pytest.fail(
            "DATABASE_ADMIN_URL es obligatorio cuando RUN_DATABASE_TESTS=1: "
            "las pruebas de migración necesitan un rol administrador para crear "
            "una base temporal y aplicar las migraciones.",
            pytrace=False,
        )
    return url


@pytest.fixture
async def db_session():
    """Yield an async session bound to a transaction that is always rolled back."""

    if not database_tests_enabled():
        pytest.skip("RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas")

    engine = create_async_engine(application_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def tenant_factory(db_session):
    """Return a factory that creates an isolated organization and owner per call."""

    async def factory(full_name: str = "Harness Owner") -> TenantContext:
        return await create_tenant_owner(db_session, full_name=full_name)

    return factory


@pytest.fixture
async def tenant_context(tenant_factory) -> TenantContext:
    """Create one organization and owner, leaving the RLS context active."""

    return await tenant_factory()
