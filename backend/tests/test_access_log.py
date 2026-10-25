"""Log de acceso saneado (RNF-5, D-11).

La línea de acceso lleva solo método, ruta sin consulta ni fragmento y estado:
nunca cabeceras, cookies, cuerpo, ``Referer`` ni los parámetros de la consulta
(``code``, ``state``, tokens). El middleware sustituye al log por defecto de
Uvicorn, que escribe la petición completa.
"""

from __future__ import annotations

import logging
import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.access_log import access_log_record
from app.main import api

ACCESS_LINE = re.compile(r"^access method=\S+ path=\S* status=\d{3}$")


@pytest.fixture
async def client():
    api.dependency_overrides.clear()
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as value:
        yield value
    api.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Formateador puro
# ---------------------------------------------------------------------------


def test_access_log_record_drops_the_query_and_keeps_the_status():
    line = access_log_record(
        "GET", "/api/v1/auth/google/callback?code=secret-code&state=secret-state", 302
    )

    assert line == "access method=GET path=/api/v1/auth/google/callback status=302"
    assert "?" not in line
    assert "secret-code" not in line
    assert "secret-state" not in line


def test_access_log_record_drops_the_fragment_too():
    line = access_log_record("GET", "/workspace?tab=1#equipos", 200)

    assert line == "access method=GET path=/workspace status=200"


def test_access_log_record_keeps_a_path_without_query():
    assert access_log_record("DELETE", "/api/v1/matches/1", 204) == (
        "access method=DELETE path=/api/v1/matches/1 status=204"
    )


def test_access_log_record_normalizes_the_method():
    assert access_log_record("post", "/api/v1/auth/google/start", 200) == (
        "access method=POST path=/api/v1/auth/google/start status=200"
    )


def test_access_log_record_preserves_server_errors():
    assert access_log_record("GET", "/health", 500).endswith("status=500")


@pytest.mark.parametrize(
    "line",
    [
        access_log_record("GET", "/", 200),
        access_log_record("POST", "/x?y=1#z", 422),
        access_log_record("GET", "/api/v1/auth/google/status?code=abc", 200),
    ],
)
def test_access_log_record_format_is_stable_and_grepable(line):
    assert ACCESS_LINE.match(line)
    assert "Referer" not in line
    assert "Cookie" not in line


# ---------------------------------------------------------------------------
# Middleware real
# ---------------------------------------------------------------------------


async def _access_lines(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("access ")
    ]


@pytest.mark.asyncio
async def test_middleware_logs_the_path_without_the_query(client, caplog):
    with caplog.at_level(logging.INFO):
        response = await client.get(
            "/api/v1/auth/google/status?code=SECRET-CODE&state=SECRET-STATE"
        )

    assert response.status_code == 200
    lines = await _access_lines(caplog)
    assert any(
        "method=GET" in line
        and "path=/api/v1/auth/google/status" in line
        and "status=200" in line
        for line in lines
    )
    assert lines
    for line in lines:
        assert "SECRET-CODE" not in line
        assert "SECRET-STATE" not in line
        assert "?" not in line


@pytest.mark.asyncio
async def test_middleware_logs_not_found_without_the_query(client, caplog):
    with caplog.at_level(logging.INFO):
        response = await client.get("/api/v1/does-not-exist?token=SECRET-TOKEN")

    assert response.status_code == 404
    lines = await _access_lines(caplog)
    assert any(
        "path=/api/v1/does-not-exist" in line and "status=404" in line
        for line in lines
    )
    assert all("SECRET-TOKEN" not in line and "?" not in line for line in lines)


@pytest.mark.asyncio
async def test_middleware_logs_csrf_rejections_without_the_query(client, caplog):
    with caplog.at_level(logging.INFO):
        response = await client.post("/api/v1/auth/register?token=SECRET-TOKEN", json={})

    assert response.status_code == 403
    lines = await _access_lines(caplog)
    assert any(
        "method=POST" in line
        and "path=/api/v1/auth/register" in line
        and "status=403" in line
        for line in lines
    )
    assert all("SECRET-TOKEN" not in line and "?" not in line for line in lines)
