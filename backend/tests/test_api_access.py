from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.main import api, app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as value:
        yield value


@pytest.fixture
async def socketio_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value


class EmptyResult:
    def mappings(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None


class EmptyDatabase:
    async def execute(self, *args, **kwargs):
        return EmptyResult()


class MappingResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class PlatformAccessDatabase:
    def __init__(self, role_code):
        self.role_code = role_code

    def begin(self):
        return FakeTransaction()

    async def execute(self, statement, *args, **kwargs):
        if "get_platform_admin_context" in str(statement):
            return MappingResult({"role_code": self.role_code})
        return EmptyResult()


async def empty_db():
    yield EmptyDatabase()


@pytest.mark.asyncio
async def test_private_tournaments_require_authentication(client):
    response = await client.get("/api/v1/tournaments")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_lineup_publication_requires_authentication(client):
    response = await client.patch(
        "/api/v1/matches/00000000-0000-0000-0000-000000000000/lineup/publication",
        json={
            "segment_id": "00000000-0000-0000-0000-000000000000",
            "team_id": "00000000-0000-0000-0000-000000000000",
            "is_public": True,
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_platform_admin_requires_authentication(client):
    response = await client.get("/api/v1/platform/users")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_platform_access_requires_authentication(client):
    response = await client.get("/api/v1/platform/access")

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role_code", "allowed"),
    [("platform_admin", True), (None, False)],
)
async def test_platform_access_reports_status_without_forbidden(client, role_code, allowed):
    user_id = uuid4()

    async def current_user():
        return user_id

    async def database():
        yield PlatformAccessDatabase(role_code)

    api.dependency_overrides[get_current_user_id] = current_user
    api.dependency_overrides[get_db] = database
    try:
        response = await client.get("/api/v1/platform/access")
    finally:
        api.dependency_overrides.pop(get_current_user_id, None)
        api.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json() == {"allowed": allowed}


@pytest.mark.asyncio
async def test_public_tournament_projections_are_anonymous(client):
    missing_id = "00000000-0000-0000-0000-000000000000"

    api.dependency_overrides[get_db] = empty_db
    try:
        listing = await client.get("/api/v1/tournaments/public")
        standings = await client.get(f"/api/v1/tournaments/public/{missing_id}/standings")
        matches = await client.get(f"/api/v1/tournaments/public/{missing_id}/matches")
    finally:
        api.dependency_overrides.pop(get_db, None)

    assert listing.status_code == 200
    assert isinstance(listing.json(), list)
    assert standings.status_code == 404
    assert matches.status_code == 404


@pytest.mark.asyncio
async def test_http_api_is_reachable_through_socketio_asgi_app(socketio_client):
    response = await socketio_client.get("/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_csrf_bootstrap_returns_one_consistent_cookie_and_header(client):
    bootstrap = await client.get("/api/v1/auth/csrf")
    token = bootstrap.json()["csrf_token"]

    assert bootstrap.headers["X-CSRF-Token"] == token
    csrf_cookies = [
        cookie for cookie in bootstrap.headers.get_list("set-cookie") if cookie.startswith("bc_csrf_token=")
    ]
    assert len(csrf_cookies) == 1
    assert f"bc_csrf_token={token};" in csrf_cookies[0]

    missing_header = await client.post("/api/v1/auth/logout")
    assert missing_header.status_code == 403

    valid_request = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": token},
    )
    assert valid_request.status_code == 204
