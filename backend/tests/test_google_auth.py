"""Inicio del flujo de Google (`POST /auth/google/start`, RF-1, RF-2, RF-6, RF-9, RF-14, RF-31).

El endpoint no se conecta a Google ni a Redis real: el proveedor, el rate limit
y el cliente Redis se sustituyen por dobles. La base de datos también es falsa
para la comprobación de «ya vinculada». Se comprueban el contrato de la
respuesta, la cookie de estado, las guardas (deshabilitado, sesión, ya
vinculada, límite de intentos, Redis caído), la normalización del destino y que
un inicio nuevo descarta el intento anterior.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import text

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_user_session,
    decode_access_token_claims,
    get_current_user_id,
    get_optional_current_user_id,
)
from app.main import api
from app.modules.identity import router as identity_router
from app.modules.identity.account_rules import LinkOutcome, LoginOutcome
from app.modules.identity.google_accounts import (
    LinkRejected,
    LoginRejected,
    LoginResult,
    SessionAccountInvalid,
)
from app.modules.identity.google_claims import GoogleIdentity
from app.modules.identity.google_provider import (
    GoogleIdentityInvalid,
    GoogleUnavailable,
)
from app.modules.identity.google_state import (
    GoogleAttempt,
    consume_attempt,
    save_attempt,
    state_cache_key,
)
from db_helpers import create_test_organization, create_test_user

USER_ID = UUID("00000000-0000-4000-8000-0000000000aa")
REDIRECT_URI = "http://localhost:8000/api/v1/auth/google/callback"
STATE_COOKIE = "bc_oauth_state"
STATE_PATH = "/api/v1/auth/google"


def provider_settings(**overrides) -> SimpleNamespace:
    values = {
        "google_oauth_enabled": True,
        "google_client_id": "bracket-craft.apps.googleusercontent.com",
        "google_client_secret": "client-secret-not-in-the-url",
        "google_audience": "bracket-craft.apps.googleusercontent.com",
        "google_redirect_uri": REDIRECT_URI,
        "auth_login_rate_limit": 10,
        "max_request_body_bytes": 1024 * 1024,
        "redis_url": "redis://redis:6379/0",
        "cookie_secure": False,
        "auth_cookie_name": "bc_access_token",
        "auth_cookie_samesite": "lax",
        "csrf_cookie_name": "bc_csrf_token",
        "frontend_base_url": "http://localhost:3000",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.deleted: list[str] = []
        self.closed = False
        self.fail_set = False

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.fail_set:
            raise RedisError("Redis no disponible")
        self.values[key] = value
        self.set_calls.append((key, value, ex))
        return True

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        return int(self.values.pop(key, None) is not None)

    async def aclose(self) -> None:
        self.closed = True


class FakeResult:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeDatabase:
    def __init__(self, *, linked: bool = False) -> None:
        self.linked = linked
        self.queries: list[str] = []

    async def execute(self, statement, *args, **kwargs):
        self.queries.append(str(statement))
        if "auth_identities" in str(statement):
            return FakeResult([1] if self.linked else [])
        return FakeResult()


class RateLimitSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: HTTPException | None = None
        self.errors_by_bucket: dict[str, HTTPException] = {}

    async def __call__(self, request, bucket, limit, window_seconds, **kwargs):
        self.calls.append((bucket, limit, window_seconds, kwargs))
        error = self.errors_by_bucket.get(bucket, self.error)
        if error is not None:
            raise error


@pytest.fixture
async def client():
    api.dependency_overrides.clear()
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as value:
        yield value
    api.dependency_overrides.clear()


@pytest.fixture
def rate_limit(monkeypatch) -> RateLimitSpy:
    spy = RateLimitSpy()
    monkeypatch.setattr(identity_router, "enforce_rate_limit", spy)
    return spy


@pytest.fixture
def fake_redis(monkeypatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(
        identity_router.Redis, "from_url", lambda *args, **kwargs: redis
    )
    return redis


def use_settings(monkeypatch, **overrides) -> SimpleNamespace:
    value = provider_settings(**overrides)
    monkeypatch.setattr(identity_router, "get_settings", lambda: value)
    return value


def override_session(*, user_id: UUID | None = None, linked: bool = False) -> FakeDatabase:
    database = FakeDatabase(linked=linked)

    async def fake_user():
        return user_id

    async def fake_database():
        yield database

    api.dependency_overrides[get_optional_current_user_id] = fake_user
    api.dependency_overrides[get_db] = fake_database
    return database


async def csrf_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.get("/api/v1/auth/csrf")
    return {"X-CSRF-Token": response.headers["X-CSRF-Token"]}


def state_cookie_header(response) -> str:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{STATE_COOKIE}="):
            return header
    raise AssertionError(f"falta la cookie {STATE_COOKIE}: {response.headers}")


# ---------------------------------------------------------------------------
# Contrato de éxito
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_the_authorization_url_and_the_state_cookie(
    client, monkeypatch, rate_limit, fake_redis
):
    settings = use_settings(monkeypatch)
    override_session()

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "login", "redirect": "/workspace"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"authorization_url"}
    url = urlsplit(body["authorization_url"])
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["client_id"] == [settings.google_client_id]
    assert query["redirect_uri"] == [settings.google_redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email profile"]
    assert settings.google_client_secret not in body["authorization_url"]

    cookie = state_cookie_header(response)
    state = response.cookies.get(STATE_COOKIE)
    assert state
    assert query["state"] == [state]
    assert f"{STATE_COOKIE}={state}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert f"Path={STATE_PATH}" in cookie
    assert "Max-Age=600" in cookie
    assert "Secure" not in cookie

    assert response.headers["cache-control"] == "no-store"
    assert rate_limit.calls[0][:3] == ("google", settings.auth_login_rate_limit, 60)

    key = state_cache_key(state)
    record = json.loads(fake_redis.values[key])
    assert record["flow"] == "login"
    assert record["destination"] == "/workspace"
    assert record["user_id"] is None
    assert record["state_hash"] == key.rsplit(":", 1)[-1]
    assert fake_redis.set_calls == [(key, fake_redis.values[key], 600)]
    assert fake_redis.closed is True


@pytest.mark.asyncio
async def test_start_marks_the_cookie_secure_outside_development(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch, cookie_secure=True)
    override_session()

    response = await client.post(
        "/api/v1/auth/google/start",
        json={},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    assert "Secure" in state_cookie_header(response)


@pytest.mark.asyncio
async def test_start_defaults_to_the_login_flow(client, monkeypatch, rate_limit, fake_redis):
    use_settings(monkeypatch)
    override_session()

    response = await client.post(
        "/api/v1/auth/google/start",
        json={},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    state = response.cookies.get(STATE_COOKIE)
    record = json.loads(fake_redis.values[state_cache_key(state)])
    assert record["flow"] == "login"
    assert record["destination"] is None


@pytest.mark.asyncio
async def test_start_normalizes_an_unsafe_redirect_to_null(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "login", "redirect": "//evil.test/takeover"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    state = response.cookies.get(STATE_COOKIE)
    record = json.loads(fake_redis.values[state_cache_key(state)])
    assert record["destination"] is None


@pytest.mark.asyncio
async def test_start_rejects_an_unknown_flow_with_422(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "other"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert fake_redis.set_calls == []


# ---------------------------------------------------------------------------
# Guardas antes de escribir
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_is_unavailable_without_google_and_never_calls_provider_or_redis(
    client, monkeypatch, rate_limit
):
    use_settings(monkeypatch, google_oauth_enabled=False)
    database = override_session(user_id=None)
    provider_calls: list[object] = []
    redis_calls: list[object] = []

    monkeypatch.setattr(
        identity_router,
        "authorization_url",
        lambda *args, **kwargs: provider_calls.append(args),
    )
    monkeypatch.setattr(
        identity_router.Redis,
        "from_url",
        lambda *args, **kwargs: redis_calls.append(args),
    )

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "link"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "GOOGLE_UNAVAILABLE"
    assert not any(
        header.startswith(f"{STATE_COOKIE}=")
        for header in response.headers.get_list("set-cookie")
    )
    assert provider_calls == []
    assert redis_calls == []
    assert database.queries == []
    assert rate_limit.calls


@pytest.mark.asyncio
async def test_start_requires_a_session_for_the_link_flow(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    database = override_session(user_id=None)

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "link"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticación requerida"}
    assert response.headers["cache-control"] == "no-store"
    assert fake_redis.set_calls == []
    assert database.queries == []


@pytest.mark.asyncio
async def test_start_rejects_the_link_flow_when_the_account_is_already_linked(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session(user_id=USER_ID, linked=True)

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "link"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "GOOGLE_ALREADY_LINKED"
    assert response.headers["cache-control"] == "no-store"
    assert fake_redis.set_calls == []


@pytest.mark.asyncio
async def test_start_allows_the_link_flow_when_the_account_has_no_identity(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    database = override_session(user_id=USER_ID, linked=False)

    response = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "link", "redirect": "/account/google"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 200, response.text
    assert database.queries
    state = response.cookies.get(STATE_COOKIE)
    record = json.loads(fake_redis.values[state_cache_key(state)])
    assert record["flow"] == "link"
    assert record["user_id"] == str(USER_ID)
    assert record["destination"] == "/account/google"


# ---------------------------------------------------------------------------
# Límite de intentos y Redis caído
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_429_with_the_code_and_retry_after(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()
    rate_limit.error = HTTPException(
        status_code=429,
        detail="Demasiadas solicitudes",
        headers={"Retry-After": "60"},
    )

    response = await client.post(
        "/api/v1/auth/google/start",
        json={},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "60"
    assert response.headers["cache-control"] == "no-store"
    assert fake_redis.set_calls == []


@pytest.mark.asyncio
async def test_start_returns_429_with_retry_after_even_if_the_limiter_omits_it(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()
    rate_limit.error = HTTPException(status_code=429, detail="Demasiadas solicitudes")

    response = await client.post(
        "/api/v1/auth/google/start",
        json={},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_start_maps_a_rate_limit_redis_failure_to_unavailable(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()
    rate_limit.error = HTTPException(
        status_code=503, detail="El control de acceso no está disponible"
    )

    response = await client.post(
        "/api/v1/auth/google/start",
        json={},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "GOOGLE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_start_is_unavailable_when_redis_rejects_the_attempt(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()
    fake_redis.fail_set = True

    response = await client.post(
        "/api/v1/auth/google/start",
        json={},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "GOOGLE_UNAVAILABLE"
    assert response.headers["cache-control"] == "no-store"
    assert fake_redis.closed is True


# ---------------------------------------------------------------------------
# Un inicio nuevo invalida el anterior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_starts_discard_the_first_state(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    override_session()
    csrf = await csrf_headers(client)

    first = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "login"},
        headers=csrf,
    )
    assert first.status_code == 200, first.text
    first_state = first.cookies.get(STATE_COOKIE)
    first_key = state_cache_key(first_state)
    assert first_key in fake_redis.values

    second = await client.post(
        "/api/v1/auth/google/start",
        json={"flow": "login"},
        headers=csrf,
    )
    assert second.status_code == 200, second.text
    second_state = second.cookies.get(STATE_COOKIE)

    assert second_state != first_state
    assert first_key not in fake_redis.values
    assert fake_redis.deleted == [first_key]
    assert await consume_attempt(fake_redis, first_state) is None
    second_key = state_cache_key(second_state)
    assert second_key in fake_redis.values
    assert await consume_attempt(fake_redis, second_state) is not None


# ---------------------------------------------------------------------------
# Retorno del proveedor (T12)
# ---------------------------------------------------------------------------

PRESENTED_SESSION_ID = UUID("00000000-0000-4000-8000-0000000000bb")
NEW_SESSION_TOKEN = "new-session-token"
FRONTEND = "http://localhost:3000"


class CallbackTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class CallbackDatabase:
    """Respuesta mínima a las consultas del callback (revocación incluida)."""

    def __init__(self, sessions: dict[str, object] | None = None) -> None:
        self.sessions: dict[str, object] = dict(sessions or {})
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        return CallbackTransaction()

    async def execute(self, statement, params=None, *args, **kwargs):
        sql = str(statement)
        values = dict(params or {})
        self.statements.append((sql, values))
        if "revoked_at = CURRENT_TIMESTAMP" in sql:
            session_id = str(values.get("session_id"))
            if self.sessions.get(session_id) is None:
                self.sessions[session_id] = "revoked"
        return FakeResult([])


class CallbackSpy:
    def __init__(self) -> None:
        self.identity = GoogleIdentity(
            subject="google-subject-callback",
            email="callback@example.test",
            email_verified=True,
            name="Callback Person",
        )
        self.result = LoginResult(
            outcome=LoginOutcome.LINKED,
            user_id=USER_ID,
            organization_id=None,
            session_token=NEW_SESSION_TOKEN,
        )
        self.exchange_error: Exception | None = None
        self.parse_error: Exception | None = None
        self.resolve_error: Exception | None = None
        self.link_result = LinkOutcome.LINK
        self.link_error: Exception | None = None
        self.exchange_calls: list[dict] = []
        self.parse_calls: list[dict] = []
        self.resolve_calls: list[GoogleIdentity] = []
        self.link_calls: list[dict] = []


def configure_callback(monkeypatch) -> CallbackSpy:
    spy = CallbackSpy()

    async def exchange(settings, *, code, deadline, client):
        spy.exchange_calls.append({"code": code, "deadline": deadline})
        if spy.exchange_error is not None:
            raise spy.exchange_error
        return b"provider-body"

    def parse(raw, *, client_id, now, **kwargs):
        spy.parse_calls.append({"raw": raw, "client_id": client_id, "now": now})
        if spy.parse_error is not None:
            raise spy.parse_error
        return spy.identity

    async def resolve(db, identity_value):
        spy.resolve_calls.append(identity_value)
        if spy.resolve_error is not None:
            raise spy.resolve_error
        return spy.result

    async def link(db, *, user_id, identity):
        spy.link_calls.append({"user_id": user_id, "identity": identity})
        if spy.link_error is not None:
            raise spy.link_error
        return spy.link_result

    monkeypatch.setattr(identity_router, "exchange_code", exchange)
    monkeypatch.setattr(identity_router, "parse_identity_claims", parse)
    monkeypatch.setattr(identity_router, "resolve_login", resolve)
    monkeypatch.setattr(identity_router, "link_identity", link)
    return spy


def override_callback_db(database: CallbackDatabase) -> CallbackDatabase:
    async def fake_database():
        yield database

    api.dependency_overrides[get_db] = fake_database
    return database


async def seed_attempt(redis: FakeRedis, state: str, **overrides) -> None:
    values = {
        "flow": "login",
        "destination": "/workspace",
        "user_id": None,
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    values.update(overrides)
    await save_attempt(redis, state, GoogleAttempt(**values))


async def callback_request(
    client: AsyncClient,
    *,
    state: str | None = None,
    code: str | None = "auth-code",
    error: str | None = None,
    extra: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
):
    params: dict[str, str] = {}
    if state is not None:
        params["state"] = state
    if code is not None:
        params["code"] = code
    if error is not None:
        params["error"] = error
    params.update(extra or {})
    for name, value in (cookies or {}).items():
        client.cookies.set(name, value)
    try:
        return await client.get(
            "/api/v1/auth/google/callback", params=params
        )
    finally:
        for name in (cookies or {}):
            client.cookies.delete(name)


def redirect_query(response) -> dict[str, list[str]]:
    return parse_qs(urlsplit(response.headers["location"]).query)


def assert_no_session_cookie(response) -> None:
    assert not any(
        header.startswith("bc_access_token=")
        for header in response.headers.get_list("set-cookie")
    )


def assert_state_cookie_deleted(response) -> None:
    headers = [
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith(f"{STATE_COOKIE}=")
    ]
    assert headers
    assert any("Max-Age=0" in header for header in headers)


@pytest.mark.asyncio
async def test_callback_logs_in_redirects_to_the_destination_and_revokes_the_old_session(
    client, monkeypatch, rate_limit, fake_redis
):
    settings = use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    database = override_callback_db(
        CallbackDatabase({str(PRESENTED_SESSION_ID): None})
    )
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state, destination="/workspace/tournaments/1")
    presented = create_access_token(USER_ID, PRESENTED_SESSION_ID)

    response = await callback_request(
        client,
        state=state,
        code="auth-code",
        extra={"scope": "ignored", "authuser": "0"},
        cookies={STATE_COOKIE: state, "bc_access_token": presented},
    )

    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(f"{FRONTEND}/auth/callback?")
    assert redirect_query(response)["next"] == ["/workspace/tournaments/1"]
    # No account, provider or attempt data travels in the redirect.
    for secret in (
        spy.identity.email,
        spy.identity.subject,
        "auth-code",
        state,
        NEW_SESSION_TOKEN,
    ):
        assert secret not in location
    assert "code=" not in location

    cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = next(
        header for header in cookie_headers if header.startswith("bc_access_token=")
    )
    assert f"bc_access_token={NEW_SESSION_TOKEN}" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "Path=/" in session_cookie
    assert_state_cookie_deleted(response)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    # The attempt is single use and the presented browser session is revoked,
    # without touching any other session.
    assert state_cache_key(state) not in fake_redis.values
    assert database.sessions[str(PRESENTED_SESSION_ID)] == "revoked"
    assert len(database.sessions) == 1

    assert [call["code"] for call in spy.exchange_calls] == ["auth-code"]
    assert 0 < spy.exchange_calls[0]["deadline"] - time.monotonic() <= 10
    assert spy.parse_calls[0]["client_id"] == settings.google_audience
    assert spy.parse_calls[0]["now"].tzinfo is not None
    assert spy.resolve_calls == [spy.identity]

    assert [call[0] for call in rate_limit.calls] == ["google", "google-identity"]
    assert rate_limit.calls[1][1] == settings.auth_login_rate_limit
    assert rate_limit.calls[1][2] == 60
    assert rate_limit.calls[1][3]["account_identifier"] == spy.identity.subject
    assert spy.identity.subject not in fake_redis.set_calls[0][0]


@pytest.mark.parametrize(
    ("destination", "organization_id", "expected"),
    [
        (None, None, "/organization"),
        (None, UUID("00000000-0000-4000-8000-0000000000cc"), "/workspace"),
        ("//evil.test", None, "/organization"),
        ("/account/google", None, "/account/google"),
        ("/account/google", UUID("00000000-0000-4000-8000-0000000000cc"), "/account/google"),
    ],
)
@pytest.mark.asyncio
async def test_callback_uses_the_validated_destination_or_the_default(
    client, monkeypatch, rate_limit, fake_redis, destination, organization_id, expected
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.result = LoginResult(
        outcome=LoginOutcome.LINKED,
        user_id=USER_ID,
        organization_id=organization_id,
        session_token=NEW_SESSION_TOKEN,
    )
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state, destination=destination)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.status_code == 302, response.text
    assert redirect_query(response)["next"] == [expected]


@pytest.mark.asyncio
async def test_callback_cancellation_consumes_the_attempt_and_keeps_login(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client,
        state=state,
        error="access_denied",
        cookies={STATE_COOKIE: state},
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_CANCELLED"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert state_cache_key(state) not in fake_redis.values
    assert spy.exchange_calls == []
    assert_no_session_cookie(response)
    assert_state_cookie_deleted(response)


@pytest.mark.parametrize("provider_error", ["access_denied", "server_error", "temporarily_unavailable"])
@pytest.mark.asyncio
async def test_callback_maps_any_provider_error_to_cancelled(
    client, monkeypatch, rate_limit, fake_redis, provider_error
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client,
        state=state,
        error=provider_error,
        cookies={STATE_COOKIE: state},
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_CANCELLED"
    assert spy.exchange_calls == []


@pytest.mark.asyncio
async def test_callback_rejects_a_missing_query_state(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(client, cookies={STATE_COOKIE: state})

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_STATE_INVALID"
    assert spy.exchange_calls == []
    assert_no_session_cookie(response)
    assert state_cache_key(state) in fake_redis.values


@pytest.mark.asyncio
async def test_callback_rejects_a_missing_browser_cookie(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(client, state=state)

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_STATE_INVALID"
    assert spy.exchange_calls == []


@pytest.mark.asyncio
async def test_callback_rejects_a_state_from_another_browser(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    other = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: other}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_STATE_INVALID"
    assert spy.exchange_calls == []
    assert state_cache_key(state) in fake_redis.values


@pytest.mark.asyncio
async def test_callback_rejects_an_unknown_state(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_STATE_INVALID"
    assert spy.exchange_calls == []


@pytest.mark.asyncio
async def test_callback_rejects_an_expired_attempt(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis,
        state,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_STATE_INVALID"
    assert spy.exchange_calls == []
    assert state_cache_key(state) not in fake_redis.values


@pytest.mark.asyncio
async def test_callback_consumes_the_state_only_once(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    first = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )
    second = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert first.status_code == 302
    assert second.headers["location"] == (
        f"{FRONTEND}/login?error=GOOGLE_STATE_INVALID"
    )
    assert len(spy.exchange_calls) == 1
    assert_no_session_cookie(second)


@pytest.mark.asyncio
async def test_callback_rejects_a_missing_code_without_contacting_the_provider(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, code=None, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/login?error=GOOGLE_IDENTITY_INVALID"
    )
    assert spy.exchange_calls == []
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_callback_is_unavailable_without_google_and_does_not_touch_redis(
    client, monkeypatch, rate_limit
):
    use_settings(monkeypatch, google_oauth_enabled=False)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    redis_calls: list[object] = []
    monkeypatch.setattr(
        identity_router.Redis,
        "from_url",
        lambda *args, **kwargs: redis_calls.append(args),
    )

    response = await callback_request(client, state="state", cookies={STATE_COOKIE: "state"})

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_UNAVAILABLE"
    assert spy.exchange_calls == []
    assert redis_calls == []
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_callback_maps_provider_unavailable(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.exchange_error = GoogleUnavailable("down")
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_UNAVAILABLE"
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_callback_maps_an_invalid_exchange(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.exchange_error = GoogleIdentityInvalid("invalid_grant")
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/login?error=GOOGLE_IDENTITY_INVALID"
    )
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_callback_maps_invalid_identity_claims(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.parse_error = GoogleIdentityInvalid("bad claims")
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/login?error=GOOGLE_IDENTITY_INVALID"
    )
    assert spy.resolve_calls == []
    assert_no_session_cookie(response)


@pytest.mark.parametrize(
    "code",
    [
        LoginOutcome.DISABLED.value,
        LoginOutcome.PASSWORD_ACCOUNT.value,
        LoginOutcome.GOOGLE_ONLY_ACCOUNT.value,
        LoginOutcome.INCONSISTENT.value,
    ],
)
@pytest.mark.asyncio
async def test_callback_redirects_every_login_rejection_with_its_catalog_code(
    client, monkeypatch, rate_limit, fake_redis, code
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.resolve_error = LoginRejected(LoginOutcome(code))
    override_callback_db(CallbackDatabase())
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error={code}"
    assert_no_session_cookie(response)
    assert state_cache_key(state) not in fake_redis.values


@pytest.mark.asyncio
async def test_callback_returns_rate_limited_on_the_first_bucket(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    rate_limit.error = HTTPException(status_code=429, detail="Demasiadas solicitudes")
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=RATE_LIMITED"
    assert spy.exchange_calls == []
    assert state_cache_key(state) in fake_redis.values


@pytest.mark.asyncio
async def test_callback_returns_rate_limited_on_the_identity_bucket(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    rate_limit.errors_by_bucket["google-identity"] = HTTPException(
        status_code=429, detail="Demasiadas solicitudes"
    )
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=RATE_LIMITED"
    assert spy.resolve_calls == []
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_callback_does_not_revoke_any_session_on_failure(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.resolve_error = LoginRejected(LoginOutcome.DISABLED)
    database = override_callback_db(
        CallbackDatabase({str(PRESENTED_SESSION_ID): None})
    )
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state)
    presented = create_access_token(USER_ID, PRESENTED_SESSION_ID)

    response = await callback_request(
        client,
        state=state,
        cookies={STATE_COOKIE: state, "bc_access_token": presented},
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/login?error=ACCOUNT_DISABLED"
    )
    assert database.sessions[str(PRESENTED_SESSION_ID)] is None
    assert_no_session_cookie(response)


class SavepointSession:
    """Delegates to the test session, turning ``begin()`` into a savepoint."""

    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.mark.asyncio
async def test_callback_revokes_only_the_presented_session_in_postgres(
    client, db_session, monkeypatch, rate_limit, fake_redis
):
    """RF-27/D-13 con base real: solo el ``jti`` presentado queda revocado."""

    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    user_id = await create_test_user(db_session)
    presented = await create_user_session(db_session, user_id)
    other = await create_user_session(db_session, user_id)
    presented_claims = decode_access_token_claims(presented)
    other_claims = decode_access_token_claims(other)

    async def fake_database():
        yield SavepointSession(db_session)

    api.dependency_overrides[get_db] = fake_database
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state, destination=None)

    response = await callback_request(
        client,
        state=state,
        cookies={STATE_COOKIE: state, "bc_access_token": presented},
    )

    assert response.status_code == 302, response.text
    assert redirect_query(response)["next"] == ["/organization"]

    presented_revoked = (
        await db_session.execute(
            text("SELECT revoked_at FROM public.user_sessions WHERE id = :id"),
            {"id": presented_claims["jti"]},
        )
    ).scalar_one()
    other_revoked = (
        await db_session.execute(
            text("SELECT revoked_at FROM public.user_sessions WHERE id = :id"),
            {"id": other_claims["jti"]},
        )
    ).scalar_one()
    assert presented_revoked is not None
    assert other_revoked is None


# ---------------------------------------------------------------------------
# Vinculación desde una sesión iniciada (T13)
# ---------------------------------------------------------------------------


def override_optional_session(user_id: UUID | None) -> None:
    async def fake_user():
        return user_id

    api.dependency_overrides[get_optional_current_user_id] = fake_user


def override_required_session(user_id: UUID | None) -> None:
    async def fake_user():
        return user_id

    api.dependency_overrides[get_current_user_id] = fake_user


async def _link_callback(
    client,
    fake_redis,
    monkeypatch,
    *,
    attempt_user_id: str | None = str(USER_ID),
    session_user_id: UUID | None = USER_ID,
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    database = override_callback_db(CallbackDatabase())
    override_optional_session(session_user_id)
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis,
        state,
        flow="link",
        user_id=attempt_user_id,
        destination=None,
    )
    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )
    return response, spy, database, state


@pytest.mark.asyncio
async def test_link_callback_links_and_redirects_without_a_session_cookie(
    client, monkeypatch, rate_limit, fake_redis
):
    response, spy, database, state = await _link_callback(
        client, fake_redis, monkeypatch
    )

    assert response.status_code == 302, response.text
    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?notice=GOOGLE_LINK_SUCCESS"
    )
    assert_no_session_cookie(response)
    assert_state_cookie_deleted(response)
    assert spy.link_calls == [{"user_id": USER_ID, "identity": spy.identity}]
    assert spy.resolve_calls == []
    assert not any(
        "UPDATE public.user_sessions" in sql for sql, _params in database.statements
    )
    assert state_cache_key(state) not in fake_redis.values


@pytest.mark.asyncio
async def test_link_callback_is_idempotent_and_does_not_emit_a_session(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.link_result = LinkOutcome.IDEMPOTENT
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis, state, flow="link", user_id=str(USER_ID), destination=None
    )

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?notice=GOOGLE_LINK_SUCCESS"
    )
    assert_no_session_cookie(response)
    assert spy.link_calls


@pytest.mark.parametrize(
    "code",
    [
        LinkOutcome.GOOGLE_ALREADY_LINKED.value,
        LinkOutcome.LINK_IDENTITY_TAKEN.value,
        LinkOutcome.LINK_EMAIL_MISMATCH.value,
    ],
)
@pytest.mark.asyncio
async def test_link_callback_redirects_every_rejection_to_the_account_screen(
    client, monkeypatch, rate_limit, fake_redis, code
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.link_error = LinkRejected(LinkOutcome(code))
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis, state, flow="link", user_id=str(USER_ID), destination=None
    )

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?error={code}"
    )
    assert_no_session_cookie(response)
    assert_state_cookie_deleted(response)
    assert spy.resolve_calls == []


@pytest.mark.parametrize(
    ("attempt_user_id", "session_user_id"),
    [
        (str(uuid4()), USER_ID),
        (None, USER_ID),
        (str(USER_ID), None),
    ],
)
@pytest.mark.asyncio
async def test_link_callback_fails_closed_when_the_attempt_does_not_own_the_session(
    client, monkeypatch, rate_limit, fake_redis, attempt_user_id, session_user_id
):
    response, spy, _database, state = await _link_callback(
        client,
        fake_redis,
        monkeypatch,
        attempt_user_id=attempt_user_id,
        session_user_id=session_user_id,
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?error=GOOGLE_IDENTITY_INVALID"
    )
    assert_no_session_cookie(response)
    assert spy.link_calls == []
    assert state_cache_key(state) not in fake_redis.values


@pytest.mark.asyncio
async def test_link_callback_fails_closed_when_the_session_account_is_invalid(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.link_error = SessionAccountInvalid("gone")
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis, state, flow="link", user_id=str(USER_ID), destination=None
    )

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?error=GOOGLE_IDENTITY_INVALID"
    )
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_link_callback_sends_provider_failures_to_the_account_screen(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    spy.exchange_error = GoogleUnavailable("down")
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis, state, flow="link", user_id=str(USER_ID), destination=None
    )

    response = await callback_request(
        client, state=state, cookies={STATE_COOKIE: state}
    )

    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?error=GOOGLE_UNAVAILABLE"
    )
    assert spy.link_calls == []
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_link_status_requires_a_session(client, monkeypatch):
    use_settings(monkeypatch)
    override_session()

    response = await client.get("/api/v1/auth/google/link")

    assert response.status_code == 401
    assert "linked" not in response.json()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.asyncio
async def test_link_status_returns_only_the_linked_boolean(
    client, monkeypatch, linked
):
    use_settings(monkeypatch)
    override_required_session(USER_ID)
    override_callback_db(FakeDatabase(linked=linked))

    response = await client.get("/api/v1/auth/google/link")

    assert response.status_code == 200
    assert response.json() == {"linked": linked}
    assert set(response.json()) == {"linked"}
    assert response.headers["cache-control"] == "no-store"
    # No account data of any kind is exposed.
    assert "@" not in response.text
    assert str(USER_ID) not in response.text


# ---------------------------------------------------------------------------
# Estado de Google y sesión actual (T14)
# ---------------------------------------------------------------------------

ALFA_ORG = UUID("00000000-0000-4000-8000-000000000001")
ZULU_ORG = UUID("00000000-0000-4000-8000-0000000000ff")


class SessionDatabase:
    """Registra el orden de las sentencias y responde al listado de organizaciones."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        return CallbackTransaction()

    async def execute(self, statement, params=None, *args, **kwargs):
        sql = str(statement)
        self.statements.append((sql, dict(params or {})))
        if "list_user_organizations" in sql:
            return FakeResult(self.rows)
        return FakeResult()


def override_database(database) -> None:
    async def fake_database():
        yield database

    api.dependency_overrides[get_db] = fake_database


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_google_status_reports_only_the_boolean(client, monkeypatch, enabled):
    settings = use_settings(monkeypatch, google_oauth_enabled=enabled)

    response = await client.get("/api/v1/auth/google/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": enabled}
    assert set(response.json()) == {"enabled"}
    assert response.headers["cache-control"] == "no-store"
    # Neither the client id, the secret nor the redirect URI are exposed.
    assert settings.google_client_id not in response.text
    assert settings.google_client_secret not in response.text
    assert settings.google_redirect_uri not in response.text


@pytest.mark.asyncio
async def test_google_status_needs_no_session(client, monkeypatch):
    use_settings(monkeypatch, google_oauth_enabled=True)

    response = await client.get("/api/v1/auth/google/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


@pytest.mark.asyncio
async def test_session_returns_the_user_and_the_first_organization(
    client, monkeypatch
):
    use_settings(monkeypatch)
    database = SessionDatabase(
        [
            {"id": ZULU_ORG, "name": "Zulu Session"},
            {"id": ALFA_ORG, "name": "Alfa Session"},
        ]
    )
    override_required_session(USER_ID)
    override_database(database)

    response = await client.get("/api/v1/auth/session")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "user_id": str(USER_ID),
        "organization_id": str(ALFA_ORG),
    }
    assert set(response.json()) == {"user_id", "organization_id"}
    assert response.headers["cache-control"] == "no-store"
    assert "@" not in response.text

    # RLS context inside the transaction and before the organization listing.
    set_config_indexes = [
        index
        for index, (sql, _params) in enumerate(database.statements)
        if "set_config" in sql
    ]
    listing_index = next(
        index
        for index, (sql, _params) in enumerate(database.statements)
        if "list_user_organizations" in sql
    )
    assert len(set_config_indexes) == 2
    assert max(set_config_indexes) < listing_index

    organization_value = next(
        params["value"]
        for sql, params in database.statements
        if "app.current_organization_id" in sql
    )
    user_value = next(
        params["value"]
        for sql, params in database.statements
        if "app.current_user_id" in sql
    )
    assert organization_value == ""
    assert user_value == str(USER_ID)


@pytest.mark.asyncio
async def test_session_without_organizations_returns_null(client, monkeypatch):
    use_settings(monkeypatch)
    override_required_session(USER_ID)
    override_database(SessionDatabase([]))

    response = await client.get("/api/v1/auth/session")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "user_id": str(USER_ID),
        "organization_id": None,
    }


@pytest.mark.asyncio
async def test_session_requires_a_valid_cookie(client):
    override_database(SessionDatabase([]))

    response = await client.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert "user_id" not in response.json()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_session_uses_the_stable_order_in_postgres(client, db_session):
    user_id = await create_test_user(db_session)
    await create_test_organization(db_session, user_id, name="Zulu Session")
    alfa = await create_test_organization(db_session, user_id, name="Alfa Session")

    async def fake_database():
        yield SavepointSession(db_session)

    api.dependency_overrides[get_db] = fake_database
    override_required_session(user_id)

    response = await client.get("/api/v1/auth/session")

    assert response.status_code == 200, response.text
    assert response.json()["organization_id"] == str(alfa)
    assert response.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# Retiro del camino anterior (T15, RF-3, RNF-9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": "provider-access-token"},
        {"access_token": "provider-access-token", "organization_name": "Org", "organization_slug": "org"},
        {},
        None,
    ],
)
@pytest.mark.asyncio
async def test_retired_google_login_returns_410_without_reading_the_body(
    client, monkeypatch, payload
):
    calls: list[str] = []

    def forbidden(name):
        def fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"no debe invocarse: {name}")

        return fail

    async def forbidden_db():
        calls.append("db")
        raise AssertionError("no debe abrir la base")
        yield  # pragma: no cover

    monkeypatch.setattr(identity_router, "enforce_rate_limit", forbidden("rate_limit"))
    monkeypatch.setattr(identity_router.Redis, "from_url", forbidden("redis"))
    monkeypatch.setattr(identity_router, "exchange_code", forbidden("provider"))
    api.dependency_overrides[get_db] = forbidden_db

    headers = await csrf_headers(client)
    if payload is None:
        response = await client.post(
            "/api/v1/auth/google",
            content=b"{not-json",
            headers={**headers, "Content-Type": "application/json"},
        )
    else:
        response = await client.post(
            "/api/v1/auth/google", json=payload, headers=headers
        )

    assert response.status_code == 410, response.text
    body = response.json()
    assert body["code"] == "GOOGLE_IDENTITY_INVALID"
    assert isinstance(body["detail"], str)
    assert body["detail"]
    assert response.headers.get_list("set-cookie") == []
    assert response.headers["cache-control"] == "no-store"
    assert calls == []


# ---------------------------------------------------------------------------
# Cancelación en el retorno: el flujo decide la pantalla (C-4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_cancellation_routes_to_the_account_screen_and_consumes_the_attempt(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    await seed_attempt(
        fake_redis, state, flow="link", user_id=str(USER_ID), destination=None
    )

    response = await callback_request(
        client,
        state=state,
        code=None,
        error="access_denied",
        cookies={STATE_COOKIE: state},
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        f"{FRONTEND}/account/google?error=GOOGLE_CANCELLED"
    )
    assert response.headers["referrer-policy"] == "no-referrer"
    assert state_cache_key(state) not in fake_redis.values
    assert spy.exchange_calls == []
    assert spy.link_calls == []
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_login_cancellation_keeps_the_login_screen_and_consumes_the_attempt(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state, flow="login", destination=None)

    response = await callback_request(
        client,
        state=state,
        code=None,
        error="access_denied",
        cookies={STATE_COOKIE: state},
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_CANCELLED"
    assert state_cache_key(state) not in fake_redis.values
    assert spy.exchange_calls == []
    assert_no_session_cookie(response)


@pytest.mark.asyncio
async def test_cancellation_with_a_state_from_another_browser_keeps_login(
    client, monkeypatch, rate_limit, fake_redis
):
    use_settings(monkeypatch)
    spy = configure_callback(monkeypatch)
    override_callback_db(CallbackDatabase())
    override_optional_session(USER_ID)
    state = f"state-{uuid4().hex}"
    other = f"state-{uuid4().hex}"
    await seed_attempt(fake_redis, state, flow="link", user_id=str(USER_ID))

    response = await callback_request(
        client,
        state=state,
        code=None,
        error="access_denied",
        cookies={STATE_COOKIE: other},
    )

    assert response.headers["location"] == f"{FRONTEND}/login?error=GOOGLE_CANCELLED"
    assert spy.exchange_calls == []
    assert spy.link_calls == []
    assert_no_session_cookie(response)
