import hashlib
from contextlib import asynccontextmanager
from threading import get_ident
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import Response
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError
from starlette.requests import Request

from app import main
from app.core import rate_limit
from app.core.database import get_db
from app.core.security import create_access_token
from app.modules.invitations import router as invitations
from app.modules.invitations.schemas import AcceptInvitationRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome,expected_status", [(1, 429), (ConnectionError("offline"), 503)])
async def test_acceptance_is_limited_before_database_authentication_or_hashing(monkeypatch, outcome, expected_status):
    redis = AsyncMock()
    if isinstance(outcome, Exception):
        redis.eval.side_effect = outcome
    else:
        redis.eval.return_value = outcome
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: redis)
    database = MagicMock(side_effect=AssertionError("no database before rate limit"))
    hashing = MagicMock(side_effect=AssertionError("no hashing before rate limit"))
    main.api.dependency_overrides[get_db] = database
    monkeypatch.setattr(invitations, "hash_password", hashing)
    try:
        async with AsyncClient(transport=ASGITransport(app=main.api), base_url="http://test") as client:
            csrf = await client.get("/api/v1/auth/csrf")
            response = await client.post(
                "/api/v1/invitations/secret-invitation/accept",
                json={"password": "contraseña-segura", "full_name": "Invitado"},
                headers={
                    "Authorization": f"Bearer {create_access_token(uuid4(), uuid4())}",
                    "X-CSRF-Token": csrf.headers["X-CSRF-Token"],
                },
            )
    finally:
        main.api.dependency_overrides.pop(get_db, None)
    assert response.status_code == expected_status
    if expected_status == 429:
        assert response.headers["Retry-After"] == "60"
    database.assert_not_called()
    hashing.assert_not_called()
    args = redis.eval.call_args.args
    token_hash = hashlib.sha256(b"secret-invitation").hexdigest()
    expected_keys = [
        "bracket-craft:rate:" + hashlib.sha256(value.encode()).hexdigest()
        for value in ["invitation_accept:ip:127.0.0.1", f"invitation_accept:connection:{token_hash}"]
    ]
    assert args[1:4] == (2, *expected_keys)
    limit = str(invitations.get_settings().auth_login_rate_limit)
    assert args[4:] == ("60", limit, limit)
    assert "secret-invitation" not in repr(args)


@pytest.mark.asyncio
async def test_acceptance_checks_body_size_before_redis(monkeypatch):
    redis = AsyncMock()
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: redis)
    request = Request({"type": "http", "headers": [(b"content-length", b"999999999")]})
    with pytest.raises(main.HTTPException) as failure:
        await invitations._limit_invitation_accept("secret", request)
    assert failure.value.status_code == 413
    redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_preview_does_not_use_the_rate_limiter(monkeypatch):
    database = AsyncMock()
    database.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = None
    database.execute.return_value = result

    async def get_database():
        yield database

    limiter = AsyncMock(side_effect=AssertionError("preview must not be limited"))
    monkeypatch.setattr(invitations, "enforce_rate_limit", limiter)
    main.api.dependency_overrides[get_db] = get_database
    try:
        async with AsyncClient(transport=ASGITransport(app=main.api), base_url="http://test") as client:
            response = await client.get("/api/v1/invitations/unknown")
    finally:
        main.api.dependency_overrides.pop(get_db, None)
    assert response.status_code == 404
    database.execute.assert_awaited_once()
    limiter.assert_not_awaited()


def test_existing_rate_limit_keys_remain_compatible():
    request = Request({"type": "http", "headers": [], "client": ("192.0.2.1", 1234)})
    identities = ["login:ip:192.0.2.1", "login:account:user@example.com", "login:connection:connection-1"]
    assert rate_limit.build_rate_limit_keys(request, "login", " User@Example.COM ", "connection-1") == [
        "bracket-craft:rate:" + hashlib.sha256(value.encode()).hexdigest() for value in identities
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("preview,status", [(None, 404), ({"status": "expired"}, 410),
                                           ({"status": "pending", "requires_login": True}, 401)])
async def test_acceptance_rejections_do_not_hash(monkeypatch, preview, status):
    database = AsyncMock()
    database.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = preview
    database.execute.return_value = result
    hashing = MagicMock(side_effect=AssertionError("no hash for rejected invitation"))
    monkeypatch.setattr(invitations, "hash_password", hashing)
    with pytest.raises(main.HTTPException) as failure:
        await invitations.accept_invitation("secret", AcceptInvitationRequest(), Response(), database, None)
    assert failure.value.status_code == status
    hashing.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("password", [None, "contraseña-segura"])
async def test_acceptance_hashes_in_a_worker_between_transactions(monkeypatch, password):
    loop_thread = get_ident()
    active = False
    calls = []

    @asynccontextmanager
    async def transaction():
        nonlocal active
        assert not active
        active = True
        try:
            yield
        finally:
            active = False

    def hash_in_worker(value):
        assert get_ident() != loop_thread
        assert not active
        calls.append(value)
        return "hashed-password"

    accepted = {"user_id": uuid4(), "organization_id": uuid4(), "organization_user_id": uuid4(),
                "role_code": "viewer", "created_user": True}
    preview_result = MagicMock()
    preview_result.mappings.return_value.one_or_none.return_value = {"status": "pending", "requires_login": False}
    accepted_result = MagicMock()
    accepted_result.mappings.return_value.one.return_value = accepted
    database = AsyncMock()
    database.begin = transaction
    database.execute.side_effect = [preview_result, accepted_result]
    monkeypatch.setattr(invitations, "hash_password", hash_in_worker)
    monkeypatch.setattr(invitations, "set_rls_context", AsyncMock())
    monkeypatch.setattr(invitations, "create_user_session", AsyncMock(return_value="session-token"))
    response = Response()
    result = await invitations.accept_invitation(
        "secret", AcceptInvitationRequest(password=password, full_name="Invitado"), response, database, None,
    )
    assert result == accepted
    assert calls == ([password] if password else [])
    assert database.execute.call_args.args[1]["password_hash"] == ("hashed-password" if password else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [1, ConnectionError("offline")])
async def test_public_socket_rejects_excess_or_redis_failure_before_database(monkeypatch, outcome):
    redis = AsyncMock()
    if isinstance(outcome, Exception):
        redis.eval.side_effect = outcome
    else:
        redis.eval.return_value = outcome
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: redis)
    factory = MagicMock(side_effect=AssertionError("no database for rejected socket"))
    monkeypatch.setattr(main, "SessionFactory", factory)
    assert await main.connect("limited", {"asgi.scope": {"client": ("192.0.2.1", 1234)}},
                              {"tournament_id": str(uuid4())}) is False
    factory.assert_not_called()
    assert redis.eval.call_args.args[1:] == (
        1, "bracket-craft:rate:" + hashlib.sha256(b"socket_public:ip:192.0.2.1").hexdigest(), "60", "60",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("environ,host", [
    ({"asgi.scope": {"client": ("192.0.2.1", 1234)}, "REMOTE_ADDR": "127.0.0.1",
      "HTTP_X_FORWARDED_FOR": "untrusted"}, "192.0.2.1"),
    ({"REMOTE_ADDR": "192.0.2.2"}, "192.0.2.2"),
    ({}, "unknown"),
])
@pytest.mark.parametrize("visible", [False, True])
async def test_public_socket_uses_client_ip_and_preserves_visibility(monkeypatch, environ, host, visible):
    redis = AsyncMock()
    redis.eval.return_value = 0
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: redis)
    database = AsyncMock()
    database.__aenter__.return_value = database
    database.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.scalar_one_or_none.return_value = 1 if visible else None
    database.execute.return_value = result
    monkeypatch.setattr(main, "SessionFactory", lambda: database)
    monkeypatch.setattr(main, "connected_socket_sessions", {})
    save = AsyncMock()
    room = AsyncMock()
    resync = AsyncMock()
    monkeypatch.setattr(main.sio, "save_session", save)
    monkeypatch.setattr(main.sio, "enter_room", room)
    monkeypatch.setattr(main, "emit_join_resync", resync)
    tournament = str(uuid4())
    assert await main.connect("public", environ, {"tournament_id": tournament}) is visible
    key = "bracket-craft:rate:" + hashlib.sha256(f"socket_public:ip:{host}".encode()).hexdigest()
    assert redis.eval.call_args.args[2] == key
    database.execute.assert_awaited_once()
    if visible:
        save.assert_awaited_once_with("public", {"scope": "public", "tournament_id": tournament})
        room.assert_awaited_once_with("public", f"tournament:{tournament}")
        resync.assert_awaited_once_with("public")
    else:
        save.assert_not_awaited()
        room.assert_not_awaited()
        resync.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", [None, {}, {"tournament_id": "invalid"}])
async def test_invalid_socket_auth_does_not_query_or_limit(monkeypatch, auth):
    limiter = AsyncMock()
    factory = MagicMock()
    monkeypatch.setattr(main, "enforce_identity_rate_limit", limiter)
    monkeypatch.setattr(main, "SessionFactory", factory)
    assert await main.connect("invalid", {}, auth) is False
    limiter.assert_not_awaited()
    factory.assert_not_called()
