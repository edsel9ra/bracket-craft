"""Buffer del cuerpo: cuerpo completo frente a desconexión a mitad (RF-022).

Una petición cuyo cliente se desconecta antes de terminar el cuerpo no puede
procesarse como completa. El buffer distingue tres resultados (completo,
demasiado grande y desconectado) y el middleware, ante una desconexión, no llama
al manejador ni deja una respuesta de dominio: solo cierra la petición.

Estas pruebas son unitarias: construyen el ``Request`` ASGI con un ``receive``
controlado, sin red ni base de datos.
"""

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.main import (
    CLIENT_CLOSED_REQUEST,
    BodyBufferResult,
    _buffer_request_body,
    csrf_and_request_size_middleware,
)


def http_scope(
    method: str = "POST",
    path: str = "/api/v1/test",
    headers: dict[str, str] | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "scheme": "http",
        "http_version": "1.1",
    }


def buffered_request(messages: list[dict], headers: dict[str, str] | None = None) -> Request:
    remaining = list(messages)

    async def receive():
        return remaining.pop(0) if remaining else {"type": "http.disconnect"}

    return Request(http_scope(headers=headers), receive)


# ---------------------------------------------------------------------------
# El buffer distingue completo, demasiado grande y desconectado
# ---------------------------------------------------------------------------


async def test_complete_body_across_chunks_is_buffered_and_replayed():
    request = buffered_request(
        [
            {"type": "http.request", "body": b'{"ok":', "more_body": True},
            {"type": "http.request", "body": b"true}", "more_body": False},
        ]
    )

    result = await _buffer_request_body(request, 64)

    assert result is BodyBufferResult.COMPLETE
    downstream = Request(request.scope, request.receive)
    assert await downstream.body() == b'{"ok":true}'


async def test_body_over_the_limit_is_reported_as_too_large():
    request = buffered_request(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ]
    )

    assert await _buffer_request_body(request, 5) is BodyBufferResult.TOO_LARGE


async def test_disconnect_after_a_partial_body_is_not_a_complete_body():
    request = buffered_request(
        [
            {"type": "http.request", "body": b'{"ok":', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    result = await _buffer_request_body(request, 64)

    assert result is BodyBufferResult.DISCONNECTED
    # El cuerpo parcial no se instala como cuerpo completo de la petición.
    assert getattr(request, "_body", None) is None


async def test_disconnect_before_any_body_is_not_a_complete_body():
    request = buffered_request([{"type": "http.disconnect"}])

    assert await _buffer_request_body(request, 64) is BodyBufferResult.DISCONNECTED


# ---------------------------------------------------------------------------
# Middleware: sin manejador, sin resultado de dominio y cierre de la petición
# ---------------------------------------------------------------------------


async def run_middleware(request: Request):
    handled: list[Request] = []

    async def call_next(current: Request):
        handled.append(current)
        return JSONResponse({"ok": True})

    response = await csrf_and_request_size_middleware(request, call_next)
    return response, handled


async def test_disconnect_mid_body_does_not_run_the_handler():
    request = buffered_request(
        [
            {"type": "http.request", "body": b'{"ok":', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    response, handled = await run_middleware(request)

    assert handled == []
    assert response.status_code == CLIENT_CLOSED_REQUEST == 499
    assert response.body == b""
    assert b"ok" not in response.body


async def test_complete_body_still_runs_the_handler_once():
    request = buffered_request(
        [{"type": "http.request", "body": b'{"ok":true}', "more_body": False}]
    )

    response, handled = await run_middleware(request)

    assert len(handled) == 1
    assert response.status_code == 200
    assert await handled[0].body() == b'{"ok":true}'


def small_limit(monkeypatch, max_bytes: int) -> None:
    from app.main import get_settings

    base = get_settings()
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: base.model_copy(update={"max_request_body_bytes": max_bytes}),
    )


async def test_declared_content_length_over_the_limit_keeps_returning_413(monkeypatch):
    small_limit(monkeypatch, 8)
    request = buffered_request(
        [{"type": "http.request", "body": b"", "more_body": False}],
        headers={"Content-Length": "9"},
    )

    response, handled = await run_middleware(request)

    assert handled == []
    assert response.status_code == 413


async def test_chunked_body_over_the_limit_keeps_returning_413(monkeypatch):
    small_limit(monkeypatch, 8)
    request = buffered_request(
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ]
    )

    response, handled = await run_middleware(request)

    assert handled == []
    assert response.status_code == 413


async def test_disconnect_message_without_partial_body_is_also_closed():
    request = buffered_request([{"type": "http.disconnect"}])

    response, handled = await run_middleware(request)

    assert handled == []
    assert response.status_code == CLIENT_CLOSED_REQUEST
    assert response.body == b""


@pytest.mark.parametrize(
    "message",
    [
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.request", "body": b"{}", "more_body": False},
    ],
)
async def test_empty_but_complete_bodies_are_processed(message):
    request = buffered_request([message])

    _response, handled = await run_middleware(request)

    assert len(handled) == 1
