from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from app.core import redis_client
from app.core import rate_limit
from app import main
from starlette.requests import Request


@pytest.mark.asyncio
async def test_lazy_client_is_reused_and_closed_once(monkeypatch):
    client = AsyncMock()
    calls = []
    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.setattr(redis_client.Redis, "from_url", lambda *a, **kw: calls.append(kw) or client)
    assert redis_client.get_redis_client() is client
    assert redis_client.get_redis_client() is client
    assert len(calls) == 1
    assert calls[0]["decode_responses"] is True
    await redis_client.close_redis_client()
    await redis_client.close_redis_client()
    client.aclose.assert_awaited_once()
    assert redis_client._client is None
    assert redis_client.get_redis_client() is client
    assert len(calls) == 2
    await redis_client.close_redis_client()


@pytest.mark.asyncio
async def test_unused_client_does_not_need_closing(monkeypatch):
    monkeypatch.setattr(redis_client, "_client", None)
    await redis_client.close_redis_client()
    assert redis_client._client is None


@pytest.mark.asyncio
async def test_rate_limit_stays_fail_closed_without_closing_pool(monkeypatch):
    client = AsyncMock()
    client.eval.side_effect = ConnectionError("offline")
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: client)
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 42)})
    with pytest.raises(HTTPException) as failure:
        await rate_limit.enforce_rate_limit(request, "login", 1, 60)
    assert failure.value.status_code == 503
    client.aclose.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("offline", [False, True])
async def test_readiness_reuses_pool_and_reports_failure(monkeypatch, offline):
    client = AsyncMock()
    if offline:
        client.ping.side_effect = ConnectionError("offline")
    db = AsyncMock()
    db.__aenter__.return_value = db
    monkeypatch.setattr(main, "SessionFactory", lambda: db)
    monkeypatch.setattr(main, "get_redis_client", lambda: client)
    if offline:
        with pytest.raises(HTTPException) as failure:
            await main.readiness()
        assert failure.value.status_code == 503
        assert failure.value.detail["checks"] == {"database": "ok", "redis": "error"}
    else:
        assert await main.readiness() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}
    client.aclose.assert_not_awaited()
