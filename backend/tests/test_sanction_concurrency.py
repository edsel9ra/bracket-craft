from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.locking import lock_discipline
from app.modules.matches import router as match_router, service as match_service
from test_rectification_flow import UNCONFIRMED, proposal
from test_rectification_flow import flow as flow


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


@pytest.mark.parametrize("opening", [True, False])
async def test_match_lock_takes_coordinator_before_row_locks(flow, monkeypatch, opening):
    order = []

    async def coordinator(*args, **kwargs):
        order.append("coordinator")
        await lock_discipline(*args, **kwargs)

    async def first_row_lock(*args, **kwargs):
        order.append("row")
        raise RuntimeError("stop after lock order probe")

    target = match_router if opening else match_service
    monkeypatch.setattr(target, "lock_discipline", coordinator, raising=False)
    monkeypatch.setattr(target, "_load_operation_match" if opening else "lock_stage_and_version", first_row_lock)
    path = f"/api/v1/matches/{UNCONFIRMED}/" + ("segments" if opening else "close")
    body = {"segment_number": 1, "minute_start": 0} if opening else proposal()["proposed_report"]
    with pytest.raises(RuntimeError, match="stop after lock order probe"):
        await flow.client.post(path, json=body)
    assert order == ["coordinator", "row"]
