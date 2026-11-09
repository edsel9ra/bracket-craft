import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security_headers import SecurityHeadersMiddleware
from app.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["development", "dev", " LOCAL ", "production", "staging"])
@pytest.mark.parametrize("path,expected", [("/docs", 200), ("/missing", 404), ("/failure", 500)])
async def test_headers_cover_success_missing_and_server_errors(environment, path, expected):
    api = FastAPI()

    @api.get("/failure")
    async def failure():
        raise RuntimeError("fallo de prueba")

    secured = SecurityHeadersMiddleware(api, app_env=environment)
    async with AsyncClient(transport=ASGITransport(app=secured, raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == expected
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert ("Strict-Transport-Security" in response.headers) == (environment.strip().lower() not in {"development", "dev", "local"})
    if "Strict-Transport-Security" in response.headers:
        assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


@pytest.mark.asyncio
async def test_preserves_stricter_oauth_referrer_policy():
    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 302, "headers": [(b"referrer-policy", b"no-referrer")]})
        await send({"type": "http.response.body", "body": b""})

    async with AsyncClient(transport=ASGITransport(app=SecurityHeadersMiddleware(endpoint, app_env="development")), base_url="http://test") as client:
        response = await client.get("/")
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_real_application_docs_and_socketio_http_responses_have_headers():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        docs = await client.get("/docs")
        socket = await client.get("/socket.io/?EIO=invalid&transport=polling")
    assert docs.status_code == 200
    assert "SwaggerUIBundle" in docs.text
    assert socket.status_code == 400
    for response in (docs, socket):
        assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.asyncio
async def test_websocket_and_lifespan_pass_through_unchanged():
    sent = []

    async def endpoint(scope, receive, send):
        await send({"type": "websocket.accept" if scope["type"] == "websocket" else "lifespan.startup.complete"})

    async def receive():
        return {}

    async def send(message):
        sent.append(message)

    middleware = SecurityHeadersMiddleware(endpoint, app_env="production")
    await middleware({"type": "websocket"}, receive, send)
    await middleware({"type": "lifespan"}, receive, send)
    assert sent == [{"type": "websocket.accept"}, {"type": "lifespan.startup.complete"}]
