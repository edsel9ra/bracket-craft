"""Sanitization of validation and database errors (RF-012).

The date of birth and the national document must never reach a response body
or an application log. FastAPI's default 422 includes the rejected ``input``
and a ``ctx`` with the original error object, and the default database error
traceback can include the failing row (``Failing row contains ...``).

These tests exercise the handlers in ``app.main`` both directly and through the
real HTTP stack, and confirm that the routers' existing ``IntegrityError`` to
409 translations keep working.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.requests import Request

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import (
    _dbapi_exception_handler,
    _request_validation_exception_handler,
    api,
)

SENSITIVE_DATE = "2999-01-01"
SENSITIVE_DOCUMENT = "1029384756"
LOG_LEAK_FRAGMENTS = (
    SENSITIVE_DATE,
    SENSITIVE_DOCUMENT,
    "2000-01-01",
    "failing row contains",
    "insert into players",
    "parameters",
    "ana perez",
)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "headers": [],
        }
    )


def _context() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        organization_user_id=uuid4(),
    )


def _override_dependencies(database) -> None:
    async def auth_context() -> AuthContext:
        return _context()

    async def session():
        yield database

    api.dependency_overrides[get_auth_context] = auth_context
    api.dependency_overrides[get_db] = session


def _clear_overrides() -> None:
    api.dependency_overrides.pop(get_auth_context, None)
    api.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as value:
        yield value


async def test_validation_error_response_drops_input_and_ctx():
    exc = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "birth_date"),
                "msg": "Value error, birth_date no puede estar en el futuro",
                "input": SENSITIVE_DATE,
                "ctx": {"error": ValueError(SENSITIVE_DATE)},
                "url": "https://errors.pydantic.dev/2.12/v/value_error",
            },
            {
                "type": "string_too_short",
                "loc": ("body", "national_id"),
                "msg": "String should have at least 3 characters",
                "input": SENSITIVE_DOCUMENT,
                "ctx": {"min_length": 3},
            },
        ]
    )

    response = await _request_validation_exception_handler(_request(), exc)

    assert response.status_code == 422
    body = response.body.decode()
    assert SENSITIVE_DATE not in body
    assert SENSITIVE_DOCUMENT not in body
    errors = json.loads(body)["detail"]
    assert len(errors) == 2
    for error in errors:
        assert set(error) == {"type", "loc", "msg"}
    assert errors[0]["loc"] == ["body", "birth_date"]
    assert errors[1]["loc"] == ["body", "national_id"]


async def test_real_request_with_future_birth_date_returns_sanitized_422(client):
    _override_dependencies(object())
    try:
        response = await client.post(
            f"/api/v1/tournaments/{uuid4()}/rosters",
            json={
                "team_id": str(uuid4()),
                "first_name": "Ana",
                "last_name": "Pérez",
                "national_id": SENSITIVE_DOCUMENT,
                "birth_date": SENSITIVE_DATE,
                "dorsal_number": 10,
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422
    assert SENSITIVE_DATE not in response.text
    assert SENSITIVE_DOCUMENT not in response.text
    errors = response.json()["detail"]
    birth_date_errors = [error for error in errors if "birth_date" in error["loc"]]
    assert birth_date_errors
    for error in birth_date_errors:
        assert set(error) == {"type", "loc", "msg"}
        assert error["msg"] == "Value error, birth_date no puede estar en el futuro"


class _FakeDatabaseCause(Exception):
    sqlstate = "23502"


def _raise_database_error() -> None:
    raise DBAPIError(
        "INSERT INTO players (birth_date, national_id) VALUES ('2000-01-01', '1029384756')",
        {"birth_date": "2000-01-01", "national_id": "1029384756"},
        _FakeDatabaseCause("Failing row contains 2000-01-01, 1029384756, Ana Perez"),
    )


async def test_unhandled_dbapi_error_returns_generic_500_without_pii_in_logs(client, caplog):
    route = APIRoute("/__test__/database-error", _raise_database_error, methods=["GET"])
    api.router.routes.append(route)
    try:
        with caplog.at_level(logging.ERROR, logger="app.main"):
            response = await client.get("/__test__/database-error")
    finally:
        api.router.routes.remove(route)

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno del servidor"}
    assert "23502" in caplog.text
    logs = caplog.text.lower()
    for fragment in LOG_LEAK_FRAGMENTS:
        assert fragment.lower() not in logs


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def mappings(self):
        return self


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _IntegrityFailureDatabase:
    """Answer the permission checks and fail on the stage insert."""

    def begin(self):
        return _Transaction()

    async def execute(self, statement, parameters=None):
        sql = " ".join(str(statement).split())
        if "set_config" in sql:
            return _ScalarResult(None)
        if "FROM tournaments" in sql:
            return _ScalarResult(1)
        if "FROM roles" in sql:
            return _ScalarResult(1)
        if "FROM tournament_versions" in sql:
            return _ScalarResult("draft")
        if "INSERT INTO stages" in sql:
            raise IntegrityError(
                "INSERT INTO stages (...) VALUES (...)",
                parameters,
                Exception("duplicate key value violates unique constraint"),
            )
        raise AssertionError(f"Consulta inesperada en la prueba: {sql}")


async def test_router_translated_integrity_error_keeps_409(client):
    _override_dependencies(_IntegrityFailureDatabase())
    try:
        response = await client.post(
            f"/api/v1/tournaments/{uuid4()}/stages",
            json={
                "version_id": str(uuid4()),
                "name": "Fase única",
                "stage_type": "round_robin",
                "stage_order": 1,
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 409
    assert response.json() == {"detail": "No se pudo crear la fase"}


# ---------------------------------------------------------------------------
# ZZ409: published-structure trigger mapped to 409 by SQLSTATE (RF-020/RF-021)
# ---------------------------------------------------------------------------

ZZ409_DETAIL = "La versión publicada es inmutable"
ZZ409_RAW_MESSAGE = (
    "INSERT INTO stage_teams (team_id) VALUES ('2000-01-01', '1029384756')"
)
ZZ409_PARAMETERS = {
    "team_id": "2000-01-01",
    "national_id": "1029384756",
    "full_name": "Ana Perez",
}
ZZ409_DRIVER_MESSAGE = (
    "No se pueden insertar estructuras en una versión publicada. "
    "Failing row contains 2000-01-01, 1029384756, Ana Perez"
)


class _PublishedStructureCause(Exception):
    sqlstate = "ZZ409"


def _zz409_error() -> DBAPIError:
    return DBAPIError(
        ZZ409_RAW_MESSAGE,
        ZZ409_PARAMETERS,
        _PublishedStructureCause(ZZ409_DRIVER_MESSAGE),
    )


async def test_zz409_sqlstate_returns_sanitized_409(caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        response = await _dbapi_exception_handler(_request(), _zz409_error())

    assert response.status_code == 409
    body = json.loads(response.body)
    assert body == {"detail": ZZ409_DETAIL}

    # Neither the response nor the log carries SQL, parameters, PII or the
    # driver message: the decision is made by SQLSTATE, not by the text.
    exposed = f"{response.body.decode()} {caplog.text}".lower()
    for fragment in (
        *LOG_LEAK_FRAGMENTS,
        "stage_teams",
        "insert into",
        "failing row",
        "ana perez",
        "no se pueden insertar estructuras",
    ):
        assert fragment.lower() not in exposed
    assert "zz409" in caplog.text.lower()


async def test_zz409_through_the_http_stack_returns_409(client, caplog):
    def raise_zz409() -> None:
        raise _zz409_error()

    route = APIRoute("/__test__/zz409", raise_zz409, methods=["GET"])
    api.router.routes.append(route)
    try:
        with caplog.at_level(logging.WARNING, logger="app.main"):
            response = await client.get("/__test__/zz409")
    finally:
        api.router.routes.remove(route)

    assert response.status_code == 409
    assert response.json() == {"detail": ZZ409_DETAIL}
    exposed = f"{response.text} {caplog.text}".lower()
    for fragment in LOG_LEAK_FRAGMENTS:
        assert fragment.lower() not in exposed


class _OtherDatabaseCause(Exception):
    sqlstate = "42501"


async def test_only_zz409_is_translated_to_409(caplog):
    other = DBAPIError(
        "DELETE FROM tournament_user_roles WHERE id = '2000-01-01'",
        {"id": "2000-01-01"},
        _OtherDatabaseCause("permission denied for table tournament_user_roles"),
    )

    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = await _dbapi_exception_handler(_request(), other)

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Error interno del servidor"}
    assert "42501" in caplog.text
    assert "permission denied for table" not in caplog.text.lower()
