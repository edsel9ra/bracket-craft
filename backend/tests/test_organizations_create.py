"""Alta de organización desde una sesión sin organización (RF-23…RF-26).

El endpoint reutiliza el router ya registrado en ``app/main.py``. Las pruebas usan
una base falsa (patrón de ``test_organizations_order.py``): comprueban el orden
contexto RLS → guarda de organización previa → alta, que los rechazos no
escriben, el código aditivo del slug ocupado y que el 422 no repite la entrada.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.main import api

USER_ID = UUID("00000000-0000-4000-8000-0000000000aa")
ORG_ID = UUID("00000000-0000-4000-8000-0000000000bb")
MEMBER_ID = UUID("00000000-0000-4000-8000-0000000000cc")
EXISTING_ORG_ID = UUID("00000000-0000-4000-8000-0000000000dd")

VALID_BODY = {"name": "Liga Nueva", "slug": "liga-nueva"}


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeResult:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = list(rows or [])

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.rows[0]


class FakeUniqueViolation(Exception):
    """Imita el error de PostgreSQL de la unicidad funcional del slug."""

    sqlstate = "23505"
    constraint_name = "uq_organizations_slug_ci"


class FakeDatabase:
    def __init__(
        self,
        *,
        existing_organization: bool = False,
        slug_taken: bool = False,
    ) -> None:
        self.existing_organization = existing_organization
        self.slug_taken = slug_taken
        self.created = False
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, params=None, *args, **kwargs):
        sql = str(statement)
        values = dict(params or {})
        self.statements.append((sql, values))
        if "list_user_organizations" in sql:
            if self.created:
                return FakeResult(
                    [
                        {
                            "id": ORG_ID,
                            "name": "Liga Nueva",
                            "slug": "liga-nueva",
                            "organization_user_id": MEMBER_ID,
                        }
                    ]
                )
            return FakeResult(
                [{"id": EXISTING_ORG_ID, "name": "Existente"}]
                if self.existing_organization
                else []
            )
        if "create_organization_with_owner" in sql:
            if self.slug_taken:
                raise IntegrityError(
                    "SELECT create_organization_with_owner(...)",
                    values,
                    FakeUniqueViolation("duplicate key value violates unique constraint"),
                )
            self.created = True
            return FakeResult([ORG_ID])
        return FakeResult([])

    def used(self, fragment: str) -> bool:
        return any(fragment in sql for sql, _params in self.statements)


@pytest.fixture
async def client():
    api.dependency_overrides.clear()
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as value:
        yield value
    api.dependency_overrides.clear()


def use_signed_in_user(user_id: UUID = USER_ID) -> None:
    async def fake_user():
        return user_id

    api.dependency_overrides[get_current_user_id] = fake_user


def use_database(database: FakeDatabase) -> FakeDatabase:
    async def fake_database():
        yield database

    api.dependency_overrides[get_db] = fake_database
    return database


@pytest.mark.asyncio
async def test_create_organization_returns_the_summary_and_the_owner_membership(
    client,
):
    use_signed_in_user()
    database = use_database(FakeDatabase())

    response = await client.post("/api/v1/organizations", json=VALID_BODY)

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "id": str(ORG_ID),
        "name": "Liga Nueva",
        "slug": "liga-nueva",
        "organization_user_id": str(MEMBER_ID),
    }
    # RLS context first, then the guard, then the SECURITY DEFINER create call.
    set_config_indexes = [
        index
        for index, (sql, _params) in enumerate(database.statements)
        if "set_config" in sql
    ]
    guard_index = next(
        index
        for index, (sql, _params) in enumerate(database.statements)
        if "list_user_organizations" in sql
    )
    create_index = next(
        index
        for index, (sql, _params) in enumerate(database.statements)
        if "create_organization_with_owner" in sql
    )
    # The user context (two set_config calls) precedes the guard; the new
    # organization context is set again before reading the created row.
    assert len([index for index in set_config_indexes if index < guard_index]) == 2
    assert max(set_config_indexes) > create_index
    assert guard_index < create_index
    create_params = next(
        params
        for sql, params in database.statements
        if "create_organization_with_owner" in sql
    )
    assert create_params == {
        "name": "Liga Nueva",
        "slug": "liga-nueva",
        "user_id": str(USER_ID),
    }


@pytest.mark.asyncio
async def test_create_organization_rejects_an_account_that_already_has_one(client):
    use_signed_in_user()
    database = use_database(FakeDatabase(existing_organization=True))

    response = await client.post("/api/v1/organizations", json=VALID_BODY)

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]
    assert "code" not in body
    assert not database.used("create_organization_with_owner")
    assert not database.used("INSERT INTO public.organizations")


@pytest.mark.asyncio
async def test_create_organization_reports_a_taken_slug_with_the_additive_code(client):
    use_signed_in_user()
    database = use_database(FakeDatabase(slug_taken=True))

    response = await client.post("/api/v1/organizations", json=VALID_BODY)

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "ORGANIZATION_SLUG_TAKEN"
    assert isinstance(body["detail"], str)
    assert response.headers["cache-control"] == "no-store"
    # The message never reveals the existing organization.
    assert str(EXISTING_ORG_ID) not in response.text
    assert "Existente" not in response.text
    assert database.used("create_organization_with_owner")


@pytest.mark.asyncio
async def test_create_organization_requires_a_session(client):
    database = use_database(FakeDatabase())

    response = await client.post("/api/v1/organizations", json=VALID_BODY)

    assert response.status_code == 401
    assert database.statements == []


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Liga Nueva", "slug": "Not Valid!"},
        {"name": "Liga Nueva", "slug": "a"},
        {"name": "x", "slug": "ok"},
        {"name": "Liga Nueva"},
        {"slug": "ok"},
    ],
)
@pytest.mark.asyncio
async def test_create_organization_rejects_invalid_bodies_without_echoing_them(
    client, body
):
    use_signed_in_user()
    database = use_database(FakeDatabase())

    response = await client.post("/api/v1/organizations", json=body)

    assert response.status_code == 422
    assert "Not Valid!" not in response.text
    assert "input" not in response.text
    assert "ctx" not in response.text
    assert database.statements == []


def test_organizations_router_is_already_registered():
    operations = api.openapi()["paths"]["/api/v1/organizations"]

    assert {"get", "post"} <= set(operations)
