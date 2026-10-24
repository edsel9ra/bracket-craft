"""Cliente del proveedor de Google: URL de autorización y canje (RF-2, RF-5, RNF-2, RNF-4).

``authorization_url`` construye la única dirección que ve el navegador: el
``client_id``, la dirección de retorno exacta, ``response_type=code``, el scope
mínimo y el estado; nunca el secreto ni un token. ``exchange_code`` canjea el
código en el servidor con un timeout de 5 s por llamada, el presupuesto de 10 s
del intento, un tope de 8 KiB y sin reintentos (D-12): los fallos de red,
timeout y 5xx son ``GoogleUnavailable``; los 4xx (incluido ``invalid_grant``) y
el exceso de tamaño son ``GoogleIdentityInvalid``.

Las pruebas usan ``httpx.MockTransport``: no hay red ni llamadas al proveedor.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.modules.identity.google_provider import (
    ATTEMPT_BUDGET_SECONDS,
    AUTHORIZATION_ENDPOINT,
    MAX_IDENTITY_RESPONSE_BYTES,
    PROVIDER_TIMEOUT_SECONDS,
    SCOPE,
    TOKEN_ENDPOINT,
    GoogleIdentityInvalid,
    GoogleUnavailable,
    authorization_url,
    exchange_code,
    remaining_seconds,
)

CLIENT_ID = "bracket-craft.apps.googleusercontent.com"
CLIENT_SECRET = "client-secret-not-in-any-url"
REDIRECT_URI = "http://localhost:8000/api/v1/auth/google/callback"


def provider_settings(**overrides) -> SimpleNamespace:
    values = {
        "google_client_id": CLIENT_ID,
        "google_client_secret": CLIENT_SECRET,
        "google_audience": CLIENT_ID,
        "google_redirect_uri": REDIRECT_URI,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def form_fields(raw: bytes) -> dict[str, list[str]]:
    return parse_qs(raw.decode("ascii"))


class CountingStream(httpx.AsyncByteStream):
    """Stream that counts the bytes the caller actually pulls."""

    def __init__(self, chunk: bytes, chunks: int) -> None:
        self.chunk = chunk
        self.chunks = chunks
        self.consumed = 0
        self.chunks_read = 0

    async def __aiter__(self):
        for _ in range(self.chunks):
            self.chunks_read += 1
            self.consumed += len(self.chunk)
            yield self.chunk


# ---------------------------------------------------------------------------
# Constantes del plan §5.4
# ---------------------------------------------------------------------------


def test_provider_constants_match_the_plan():
    assert PROVIDER_TIMEOUT_SECONDS == 5.0
    assert ATTEMPT_BUDGET_SECONDS == 10.0
    assert MAX_IDENTITY_RESPONSE_BYTES == 8 * 1024
    assert SCOPE == "openid email profile"
    assert AUTHORIZATION_ENDPOINT == "https://accounts.google.com/o/oauth2/v2/auth"
    assert TOKEN_ENDPOINT == "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# URL de autorización
# ---------------------------------------------------------------------------


def test_authorization_url_has_exactly_the_documented_parameters():
    url = authorization_url(provider_settings(), state="state-value-123")

    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.netloc == "accounts.google.com"
    assert parts.path == "/o/oauth2/v2/auth"
    assert parse_qs(parts.query) == {
        "client_id": [CLIENT_ID],
        "redirect_uri": [REDIRECT_URI],
        "response_type": ["code"],
        "scope": ["openid email profile"],
        "state": ["state-value-123"],
    }


def test_authorization_url_never_carries_the_secret_or_a_token():
    url = authorization_url(provider_settings(), state="state-value-123")
    query = parse_qs(urlsplit(url).query)

    assert CLIENT_SECRET not in url
    assert "client_secret" not in query
    assert "access_token" not in query
    assert "id_token" not in query
    assert "code" not in query


def test_authorization_url_encodes_state_as_a_single_parameter():
    state = "a b+c/d=é&state=2"

    url = authorization_url(provider_settings(), state=state)
    query = parse_qs(urlsplit(url).query)

    assert query["state"] == [state]
    assert len(query["state"]) == 1


def test_authorization_url_uses_the_redirect_uri_verbatim():
    redirect = "https://api.example.test/api/v1/auth/google/callback?fixed=1"

    url = authorization_url(
        provider_settings(google_redirect_uri=redirect), state="state"
    )

    assert parse_qs(urlsplit(url).query)["redirect_uri"] == [redirect]


@pytest.mark.parametrize("redirect", [None, "", "   "])
def test_authorization_url_fails_closed_without_a_redirect_uri(redirect):
    with pytest.raises(GoogleUnavailable):
        authorization_url(
            provider_settings(google_redirect_uri=redirect), state="state"
        )


def test_authorization_url_fails_closed_without_a_client_id():
    with pytest.raises(GoogleUnavailable):
        authorization_url(provider_settings(google_client_id=None), state="state")


# ---------------------------------------------------------------------------
# Presupuesto: puro y nunca negativo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("deadline", "now", "expected"),
    [
        (100.0, 40.0, 60.0),
        (100.0, 100.0, 0.0),
        (100.0, 150.0, 0.0),
        (100.0, 99.5, 0.5),
        (0.0, 0.0, 0.0),
    ],
)
def test_remaining_seconds_never_goes_negative(deadline, now, expected):
    assert remaining_seconds(deadline, now) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Canje correcto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_posts_the_documented_form_and_returns_raw_body():
    seen: dict[str, object] = {}
    body = b'{"id_token": "raw-token"}'

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, content=body)

    async with client_for(handler) as client:
        result = await exchange_code(
            provider_settings(),
            code="authorization-code",
            deadline=time.monotonic() + 100,
            client=client,
        )

    assert result == body
    assert seen["method"] == "POST"
    assert seen["url"] == TOKEN_ENDPOINT
    assert form_fields(seen["body"]) == {
        "grant_type": ["authorization_code"],
        "code": ["authorization-code"],
        "client_id": [CLIENT_ID],
        "client_secret": [CLIENT_SECRET],
        "redirect_uri": [REDIRECT_URI],
    }
    # A fresh deadline leaves the per-call 5 s timeout untouched.
    assert seen["timeout"]["read"] == pytest.approx(PROVIDER_TIMEOUT_SECONDS)


@pytest.mark.asyncio
async def test_exchange_code_returns_the_body_without_parsing_it():
    body = b"not json at all"

    async with client_for(lambda request: httpx.Response(200, content=body)) as client:
        result = await exchange_code(
            provider_settings(),
            code="code",
            deadline=time.monotonic() + 100,
            client=client,
        )

    assert result == body


@pytest.mark.asyncio
async def test_exchange_code_reduces_the_timeout_to_the_remaining_budget():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, content=b"{}")

    async with client_for(handler) as client:
        await exchange_code(
            provider_settings(),
            code="code",
            deadline=time.monotonic() + 2,
            client=client,
        )

    assert 0 < seen["timeout"]["read"] <= 2.0


@pytest.mark.asyncio
async def test_exchange_code_does_not_call_the_provider_without_budget():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"{}")

    async with client_for(handler) as client:
        with pytest.raises(GoogleUnavailable):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() - 1,
                client=client,
            )

    assert calls == 0


# ---------------------------------------------------------------------------
# Tope de 8 KiB: corta en cuanto se supera
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_accepts_exactly_8_kib():
    body = b"x" * MAX_IDENTITY_RESPONSE_BYTES

    async with client_for(lambda request: httpx.Response(200, content=body)) as client:
        result = await exchange_code(
            provider_settings(),
            code="code",
            deadline=time.monotonic() + 100,
            client=client,
        )

    assert result == body


@pytest.mark.asyncio
async def test_exchange_code_rejects_one_byte_over_8_kib():
    body = b"x" * (MAX_IDENTITY_RESPONSE_BYTES + 1)

    async with client_for(lambda request: httpx.Response(200, content=body)) as client:
        with pytest.raises(GoogleIdentityInvalid):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() + 100,
                client=client,
            )


@pytest.mark.asyncio
async def test_exchange_code_stops_reading_a_huge_stream_early():
    stream = CountingStream(b"x" * 512, 100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with client_for(handler) as client:
        with pytest.raises(GoogleIdentityInvalid):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() + 100,
                client=client,
            )

    # It aborted around the first 8 KiB instead of draining the 50 KiB body.
    assert stream.consumed < len(stream.chunk) * stream.chunks
    assert stream.consumed <= MAX_IDENTITY_RESPONSE_BYTES + len(stream.chunk)


# ---------------------------------------------------------------------------
# Errores: proveedor no disponible frente a prueba no válida, sin reintentos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 502, 503])
async def test_exchange_code_maps_5xx_to_unavailable_without_retrying(status):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=b'{"error": "backend"}')

    async with client_for(handler) as client:
        with pytest.raises(GoogleUnavailable):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() + 100,
                client=client,
            )

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_exchange_code_maps_4xx_to_identity_invalid(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=b'{"error": "invalid_grant"}')

    async with client_for(handler) as client:
        with pytest.raises(GoogleIdentityInvalid):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() + 100,
                client=client,
            )


@pytest.mark.asyncio
async def test_exchange_code_maps_an_unexpected_redirect_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.test"})

    async with client_for(handler) as client:
        with pytest.raises(GoogleUnavailable):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() + 100,
                client=client,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("too slow"),
        httpx.ConnectTimeout("too slow"),
        httpx.ConnectError("network down"),
        httpx.RemoteProtocolError("broken response"),
    ],
)
async def test_exchange_code_maps_network_errors_and_timeouts_to_unavailable(error):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    async with client_for(handler) as client:
        with pytest.raises(GoogleUnavailable):
            await exchange_code(
                provider_settings(),
                code="code",
                deadline=time.monotonic() + 100,
                client=client,
            )


@pytest.mark.asyncio
async def test_exchange_code_errors_do_not_leak_the_code_secret_or_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=(
                b'{"error": "invalid_grant", "error_description": '
                b'"sensitive-code-value ' + CLIENT_SECRET.encode() + b'"}'
            ),
        )

    async with client_for(handler) as client:
        with pytest.raises(GoogleIdentityInvalid) as failure:
            await exchange_code(
                provider_settings(),
                code="sensitive-code-value",
                deadline=time.monotonic() + 100,
                client=client,
            )

    message = str(failure.value)
    assert "sensitive-code-value" not in message
    assert CLIENT_SECRET not in message
    assert "invalid_grant" not in message
