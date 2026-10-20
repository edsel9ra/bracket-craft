"""Engine timeouts, pool sizing and startup logging (RF-008, RF-009, RF-010).

The application engine must apply the approved constants as effective values:
a 15 s statement timeout, a 30 s idle-in-transaction timeout and a 10 + 10 pool
with a 10 s wait. The startup log reports those numbers once and never the
connection URL, user, host or credentials. The opt-in counterpart lives in
``test_database_timeouts.py``.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from db_helpers import application_database_url, database_tests_enabled

from app import main as main_module
from app.core import database as database_module
from app.core.config import get_settings
from app.core.database import (
    DB_IDLE_IN_TRANSACTION_TIMEOUT_MS,
    DB_MAX_OVERFLOW,
    DB_POOL_SIZE,
    DB_POOL_TIMEOUT_SECONDS,
    DB_STATEMENT_TIMEOUT_MS,
    engine,
    engine_options,
    log_database_configuration,
)


def test_timeout_and_pool_constants_are_the_approved_values():
    assert DB_STATEMENT_TIMEOUT_MS == 15_000
    assert DB_IDLE_IN_TRANSACTION_TIMEOUT_MS == 30_000
    assert DB_POOL_SIZE == 10
    assert DB_MAX_OVERFLOW == 10
    assert DB_POOL_TIMEOUT_SECONDS == 10


def test_engine_options_return_exactly_the_effective_configuration():
    assert engine_options() == {
        "pool_size": 10,
        "max_overflow": 10,
        "pool_timeout": 10,
        "connect_args": {
            "server_settings": {
                "statement_timeout": "15000",
                "idle_in_transaction_session_timeout": "30000",
            }
        },
    }


def test_application_engine_uses_the_declared_pool_and_pre_ping():
    pool = engine.pool

    assert pool.size() == DB_POOL_SIZE == 10
    assert pool._max_overflow == DB_MAX_OVERFLOW == 10
    assert pool._timeout == DB_POOL_TIMEOUT_SECONDS == 10
    assert pool._pre_ping is True
    assert engine.dialect.is_async is True


def test_startup_log_reports_the_five_values_once_without_connection_data(caplog):
    settings = get_settings()

    with caplog.at_level(logging.INFO, logger="app.core.database"):
        log_database_configuration()

    records = [
        record
        for record in caplog.records
        if record.name == "app.core.database"
    ]
    assert len(records) == 1
    message = records[0].getMessage()

    assert "15000" in message
    assert "30000" in message
    assert "pool_size=10" in message
    assert "max_overflow=10" in message
    assert "pool_timeout=10" in message

    # No URL, user, host, database name or credentials.
    assert settings.database_url not in message
    assert "postgresql" not in message.lower()
    assert "@" not in message
    for fragment in (
        "bracket_app",
        "localhost",
        "password",
        "asyncpg",
    ):
        assert fragment not in message.lower()


def test_engine_options_are_reusable_and_do_not_share_mutable_state():
    first = engine_options()
    first["connect_args"]["server_settings"]["statement_timeout"] = "1"
    second = engine_options()

    assert second["connect_args"]["server_settings"]["statement_timeout"] == "15000"
    assert database_module.engine is engine


POOL_EXHAUSTED_DETAIL = "Servicio temporalmente no disponible"


@asynccontextmanager
async def app_client(raise_app_exceptions: bool = True):
    async with AsyncClient(
        transport=ASGITransport(
            app=main_module.api, raise_app_exceptions=raise_app_exceptions
        ),
        base_url="http://test",
    ) as client:
        yield client


def register_temporary_route(path: str, endpoint):
    route = APIRoute(path, endpoint, methods=["GET"])
    main_module.api.router.routes.append(route)
    return route


def _raise_pool_timeout() -> None:
    raise PoolTimeoutError(
        "QueuePool limit of size 10 overflow 10 reached, connection timed out, "
        "timeout 10.00; statement: SELECT national_id FROM players "
        "WHERE organization_id = 'org-sensitive'"
    )


async def test_pool_exhaustion_returns_503_with_one_stable_warning(caplog):
    route = register_temporary_route("/__test__/pool-timeout", _raise_pool_timeout)
    try:
        with caplog.at_level(logging.WARNING, logger="app.main"):
            async with app_client() as client:
                response = await client.get("/__test__/pool-timeout")
    finally:
        main_module.api.router.routes.remove(route)

    assert response.status_code == 503
    assert response.json() == {"detail": POOL_EXHAUSTED_DETAIL}

    warnings = [
        record
        for record in caplog.records
        if record.name == "app.main" and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert message == "Pool de conexiones agotado"
    for fragment in ("SELECT", "national_id", "org-sensitive", "QueuePool", "postgres"):
        assert fragment not in message


async def test_a_successful_route_does_not_log_pool_warnings(caplog):
    async def ok():
        return {"ok": True}

    route = register_temporary_route("/__test__/pool-ok", ok)
    try:
        with caplog.at_level(logging.WARNING, logger="app.main"):
            async with app_client() as client:
                response = await client.get("/__test__/pool-ok")
    finally:
        main_module.api.router.routes.remove(route)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert [
        record
        for record in caplog.records
        if "Pool de conexiones agotado" in record.getMessage()
    ] == []


async def test_dbapi_errors_keep_the_sanitized_500_handler(caplog):
    def raise_dbapi() -> None:
        cause = Exception("failing row contains sensitive data")
        cause.sqlstate = "23502"
        raise DBAPIError("INSERT INTO players VALUES ('secret')", {}, cause)

    route = register_temporary_route("/__test__/dbapi-error", raise_dbapi)
    try:
        with caplog.at_level(logging.ERROR, logger="app.main"):
            async with app_client() as client:
                response = await client.get("/__test__/dbapi-error")
    finally:
        main_module.api.router.routes.remove(route)

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno del servidor"}
    assert "23502" in caplog.text
    assert "secret" not in response.text


def test_pool_timeout_handler_is_registered_separately_from_dbapi():
    handlers = main_module.api.exception_handlers

    assert handlers[PoolTimeoutError] is main_module._pool_timeout_exception_handler
    assert handlers[DBAPIError] is main_module._dbapi_exception_handler
    assert PoolTimeoutError is not DBAPIError
    assert not issubclass(PoolTimeoutError, DBAPIError)


async def test_lifespan_logs_the_database_configuration_once(monkeypatch):
    calls: list[str] = []

    async def fake_relay():
        await asyncio.Event().wait()

    async def fake_revalidate():
        await asyncio.Event().wait()

    async def fake_validate():
        calls.append("validate")

    def fake_log():
        calls.append("log")

    monkeypatch.setattr(main_module, "relay_loop", fake_relay)
    monkeypatch.setattr(main_module, "_revalidate_socket_sessions", fake_revalidate)
    monkeypatch.setattr(main_module, "validate_application_role", fake_validate)
    monkeypatch.setattr(main_module, "log_database_configuration", fake_log)
    monkeypatch.setattr(main_module, "settings", SimpleNamespace(app_env="production"))

    async with main_module.lifespan(main_module.api):
        assert calls.count("log") == 1
        assert calls.count("validate") == 1

    assert calls.count("log") == 1


@pytest.mark.skipif(
    not database_tests_enabled(),
    reason="RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas",
)
async def test_pool_exhaustion_raises_sqlalchemy_timeout_within_the_wait():
    # The production engine keeps its 10 + 10 pool; this test proves the
    # observable condition with an isolated, deliberately small pool.
    test_engine = create_async_engine(
        application_database_url(),
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    try:
        async with test_engine.connect() as first:
            await first.execute(text("SELECT 1"))
            with pytest.raises(PoolTimeoutError):
                async with asyncio.timeout(5):
                    async with test_engine.connect() as second:
                        await second.execute(text("SELECT 1"))
    finally:
        await test_engine.dispose()
