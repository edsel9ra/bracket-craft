"""Orden estable de organizaciones (RF-017, R32c).

El servidor devuelve las organizaciones de la persona siempre en el mismo
orden: por nombre y, en empate, por identificador. La elección de la
organización inicial al iniciar sesión usa exactamente el mismo criterio, así
que dos inicios consecutivos devuelven la misma organización aunque el
almacenamiento devuelva las filas en otro orden. La memoria de la última
organización usada es responsabilidad del navegador (008C).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import get_current_user_id, hash_password
from app.main import api
from app.modules.identity import router as identity_router
from app.modules.organizations.ordering import ordered_organizations


ORG_ALFA_LOW = UUID("00000000-0000-0000-0000-000000000001")
ORG_ALFA_HIGH = UUID("00000000-0000-0000-0000-0000000000ff")
ORG_BETA = UUID("00000000-0000-0000-0000-000000000010")
USER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
PASSWORD = "Demo1234!"
PASSWORD_HASH = hash_password(PASSWORD)


def organization(suffix: str, name: str) -> dict:
    return {
        "id": UUID(f"00000000-0000-0000-0000-{suffix}"),
        "name": name,
        "slug": f"slug-{suffix}",
        "organization_user_id": uuid4(),
    }


def ids(rows) -> list[str]:
    return [str(row["id"]) for row in rows]


# Orden de almacenamiento deliberadamente inverso al esperado.
STORED_ROWS = [
    organization("0000000000ff", "Alfa"),
    organization("000000000010", "Beta"),
    organization("000000000001", "Alfa"),
]
EXPECTED_IDS = [
    str(ORG_ALFA_LOW),
    str(ORG_ALFA_HIGH),
    str(ORG_BETA),
]


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeResult:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0]["id"] if self.rows else None


class OrganizationsDatabase:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, *args, **kwargs):
        if "list_user_organizations" in str(statement):
            return FakeResult(self.rows)
        return FakeResult()


class LoginDatabase:
    """Responde al login con el usuario y las organizaciones en el orden dado."""

    def __init__(self, organization_orders: list[list[dict]]):
        self.organization_orders = list(organization_orders)

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "FROM users" in sql and "password_hash" in sql:
            return FakeResult([{"id": USER_ID, "password_hash": PASSWORD_HASH}])
        if "list_user_organizations" in sql:
            return FakeResult(self.organization_orders.pop(0))
        return FakeResult()


async def _no_rate_limit(*args, **kwargs):
    return None


@pytest.fixture
async def client():
    api.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as value:
        yield value
    api.dependency_overrides.clear()


def test_order_is_name_then_identifier_independent_of_storage_order():
    forward = ordered_organizations(STORED_ROWS)
    backward = ordered_organizations(list(reversed(STORED_ROWS)))

    assert ids(forward) == EXPECTED_IDS
    assert ids(backward) == EXPECTED_IDS


def test_order_ties_break_by_identifier_not_by_insertion():
    rows = [
        organization("0000000000ff", "Misma"),
        organization("000000000001", "Misma"),
    ]

    assert ids(ordered_organizations(rows)) == [
        str(UUID("00000000-0000-0000-0000-000000000001")),
        str(UUID("00000000-0000-0000-0000-0000000000ff")),
    ]


@pytest.mark.asyncio
async def test_organizations_endpoint_returns_the_stable_order(client):
    database = OrganizationsDatabase(STORED_ROWS)
    user_id = uuid4()

    async def fake_database():
        yield database

    async def fake_user():
        return user_id

    api.dependency_overrides[get_db] = fake_database
    api.dependency_overrides[get_current_user_id] = fake_user

    response = await client.get("/api/v1/organizations")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == EXPECTED_IDS


@pytest.mark.asyncio
async def test_two_logins_return_the_same_initial_organization(client, monkeypatch):
    monkeypatch.setattr(identity_router, "enforce_rate_limit", _no_rate_limit)
    database = LoginDatabase([STORED_ROWS, list(reversed(STORED_ROWS))])

    async def fake_database():
        yield database

    api.dependency_overrides[get_db] = fake_database

    csrf_response = await client.get("/api/v1/auth/csrf")
    csrf_token = csrf_response.headers["X-CSRF-Token"]

    first = await client.post(
        "/api/v1/auth/login",
        json={"email": "persona@bracketcraft.dev", "password": PASSWORD},
        headers={"X-CSRF-Token": csrf_token},
    )
    second = await client.post(
        "/api/v1/auth/login",
        json={"email": "persona@bracketcraft.dev", "password": PASSWORD},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["organization_id"] == str(ORG_ALFA_LOW)
    assert second.json()["organization_id"] == first.json()["organization_id"]
