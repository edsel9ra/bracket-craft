"""Acceso con contraseña de una cuenta solo-Google (RF-30, RNF-12).

Una cuenta creada con Google no tiene contraseña: el login con correo y
contraseña debe rechazarla con el **401 genérico** de siempre, sin `code`, sin
cookie de sesión y sin escribir nada. El flujo con Google no cambia el contrato
del acceso con contraseña (RNF-9).
"""

from __future__ import annotations

from threading import get_ident
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import Response
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.database import get_db
from app.core.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.main import api
from app.modules.identity import router as identity_router
from app.modules.identity.schemas import RegisterRequest

USER_ID = UUID("00000000-0000-4000-8000-0000000000aa")


def test_dummy_hash_uses_the_recommended_argon2_parameters():
    assert DUMMY_PASSWORD_HASH.split("$")[1:4] == hash_password("prueba").split("$")[1:4]
    assert verify_password("otra-contraseña", DUMMY_PASSWORD_HASH) is False


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeResult:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeDatabase:
    """Responde a la consulta del login y registra cualquier escritura."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, params=None, *args, **kwargs):
        sql = str(statement)
        self.statements.append((sql, dict(params or {})))
        if "FROM users" in sql:
            return FakeResult(self.rows)
        return FakeResult([])


@pytest.fixture
async def client():
    api.dependency_overrides.clear()
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as value:
        yield value
    api.dependency_overrides.clear()


async def csrf_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.get("/api/v1/auth/csrf")
    return {"X-CSRF-Token": response.headers["X-CSRF-Token"]}


@pytest.mark.asyncio
async def test_password_login_rejects_a_google_only_account_without_writing(
    client, monkeypatch
):
    database = FakeDatabase([{"id": USER_ID, "password_hash": None}])

    async def fake_database():
        yield database

    async def no_rate_limit(*args, **kwargs):
        return None

    async def forbidden_session(*args, **kwargs):
        raise AssertionError("no debe emitirse una sesión para una cuenta sin contraseña")

    api.dependency_overrides[get_db] = fake_database
    monkeypatch.setattr(identity_router, "enforce_rate_limit", no_rate_limit)
    monkeypatch.setattr(identity_router, "create_user_session", forbidden_session)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "solo.google@bracketcraft.dev", "password": "cualquier-cosa"},
        headers=await csrf_headers(client),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales inválidas"}
    assert "code" not in response.json()
    assert response.headers.get_list("set-cookie") == []

    # Only the lookup ran: no user session and no other write.
    assert any("FROM users" in sql for sql, _params in database.statements)
    assert not any(
        statement.upper().lstrip().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement, _params in database.statements
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,expected_hash", [
    ([], DUMMY_PASSWORD_HASH),
    ([{"id": USER_ID, "password_hash": None}], DUMMY_PASSWORD_HASH),
    ([{"id": USER_ID, "password_hash": ""}], DUMMY_PASSWORD_HASH),
    ([{"id": USER_ID, "password_hash": "hash-de-cuenta"}], "hash-de-cuenta"),
])
async def test_login_always_verifies_a_hash_before_generic_rejection(client, monkeypatch, rows, expected_hash):
    database = FakeDatabase(rows)
    calls = []
    loop_thread = get_ident()

    async def fake_database():
        yield database

    async def no_rate_limit(*args, **kwargs):
        return None

    def verify(value, hashed):
        assert get_ident() != loop_thread
        calls.append((value, hashed))
        return False

    api.dependency_overrides[get_db] = fake_database
    monkeypatch.setattr(identity_router, "enforce_rate_limit", no_rate_limit)
    monkeypatch.setattr(identity_router, "verify_password", verify)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "ausente@example.com", "password": "prueba-contraseña"},
        headers=await csrf_headers(client),
    )
    assert calls == [("prueba-contraseña", expected_hash)]
    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales inválidas"}
    assert response.headers.get_list("set-cookie") == []
    assert len(database.statements) == 1


@pytest.mark.asyncio
async def test_registration_hashes_in_a_worker_before_opening_the_transaction(monkeypatch):
    database = AsyncMock()
    database.begin = MagicMock(return_value=FakeTransaction())
    user = MagicMock()
    user.scalar_one.return_value = USER_ID
    database.execute.return_value = user
    loop_thread = get_ident()

    def hash_in_worker(value):
        assert get_ident() != loop_thread
        database.begin.assert_not_called()
        assert value == "prueba-contraseña"
        return "hash-de-cuenta"

    monkeypatch.setattr(identity_router, "enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(identity_router, "hash_password", hash_in_worker)
    monkeypatch.setattr(identity_router, "_create_organization", AsyncMock(return_value=USER_ID))
    monkeypatch.setattr(identity_router, "create_user_session", AsyncMock(return_value="session-token"))
    result = await identity_router.register(
        RegisterRequest(
            email="nuevo@example.com", password="prueba-contraseña", full_name="Nuevo Usuario",
            organization_name="Organización", organization_slug="organizacion",
        ),
        Request({"type": "http", "headers": []}), Response(), database,
    )
    assert result.user_id == str(USER_ID)
    assert database.execute.call_args.args[1]["password_hash"] == "hash-de-cuenta"


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [{"id": USER_ID, "password_hash": None}], [{"id": USER_ID, "password_hash": ""}]])
async def test_dummy_hash_match_can_never_create_a_session(client, monkeypatch, rows):
    database = FakeDatabase(rows)

    async def fake_database():
        yield database

    async def no_rate_limit(*args, **kwargs):
        return None

    api.dependency_overrides[get_db] = fake_database
    monkeypatch.setattr(identity_router, "enforce_rate_limit", no_rate_limit)
    monkeypatch.setattr(identity_router, "verify_password", lambda value, hashed: True)
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ausente@example.com", "password": "prueba-contraseña"},
        headers=await csrf_headers(client),
    )
    assert response.status_code == 401
    assert response.headers.get_list("set-cookie") == []
    assert len(database.statements) == 1
