from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.locking import lock_discipline


async def test_coordinator_serializes_same_tenant_and_releases_on_rollback(database_admin_url):
    engine = create_async_engine(database_admin_url)
    org = uuid4()
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            async with first.begin():
                await lock_discipline(first, org)
                async with second.begin():
                    await second.execute(text("SET LOCAL lock_timeout='100ms'"))
                    await lock_discipline(second, uuid4())
                with pytest.raises(DBAPIError, match="lock timeout"):
                    async with second.begin():
                        await second.execute(text("SET LOCAL lock_timeout='100ms'"))
                        await lock_discipline(second, org)
            async with second.begin():
                await second.execute(text("SET LOCAL lock_timeout='100ms'"))
                await lock_discipline(second, org)
    finally:
        await engine.dispose()
