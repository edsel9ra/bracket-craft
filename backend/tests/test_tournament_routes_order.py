from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.tenancy import get_auth_context
from app.main import api
from app.modules.tournaments.routes.teams import list_tournament_teams


PREFIX = "/api/v1/tournaments"
OPERATIONS = {
    ("POST", ""),
    ("GET", ""),
    ("GET", "/{tournament_id}/versions"),
    ("POST", "/{tournament_id}/versions"),
    ("PATCH", "/{tournament_id}/versions/{version_id}"),
    ("PATCH", "/{tournament_id}/versions/{version_id}/rules"),
    ("POST", "/{version_id}/publish"),
    ("GET", "/{tournament_id}/stages"),
    ("POST", "/{tournament_id}/stages"),
    ("GET", "/{tournament_id}/stages/{stage_id}/teams"),
    ("POST", "/{tournament_id}/stages/{stage_id}/teams"),
    ("DELETE", "/{tournament_id}/stages/{stage_id}/teams/{team_id}"),
    ("GET", "/{tournament_id}/teams"),
    ("POST", "/{tournament_id}/teams"),
    ("POST", "/{tournament_id}/teams/bulk"),
    ("GET", "/{tournament_id}/rosters"),
    ("POST", "/{tournament_id}/rosters"),
    ("POST", "/{tournament_id}/rosters/bulk"),
    ("POST", "/{tournament_id}/rosters/{roster_id}/photo"),
    ("PATCH", "/{tournament_id}/rosters/{roster_id}/photo-consent"),
    ("PATCH", "/{tournament_id}/rosters/{roster_id}/status"),
    ("POST", "/{tournament_id}/matches/generate"),
    ("POST", "/{tournament_id}/matches/draw"),
    ("GET", "/{tournament_id}/matches"),
    ("POST", "/{tournament_id}/matches"),
    ("GET", "/public"),
    ("GET", "/public/{tournament_id}"),
    ("GET", "/public/{tournament_id}/standings"),
    ("GET", "/public/{tournament_id}/matches"),
    ("GET", "/public/{tournament_id}/player-stats"),
    ("GET", "/public/{tournament_id}/team-stats"),
}


def test_all_31_tournament_operations_remain_registered():
    crest_path = PREFIX + "/{tournament_id}/teams/{team_id}/crest"
    actual = {
        (method.upper(), path.removeprefix(PREFIX))
        for path, operations in api.openapi()["paths"].items()
        if path.startswith(PREFIX) and path != crest_path
        for method in operations
        if method in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    }
    assert len(actual) == 31
    assert actual == OPERATIONS


async def test_private_team_route_still_precedes_public_tournament(monkeypatch):
    async def unauthorized():
        raise HTTPException(status_code=401)

    monkeypatch.setitem(api.dependency_overrides, get_auth_context, unauthorized)
    selected = []

    async def capture_endpoint(scope, receive, send):
        await api(scope, receive, send)
        selected.append(scope.get("endpoint"))

    async with AsyncClient(
        transport=ASGITransport(app=capture_endpoint), base_url="http://test"
    ) as client:
        response = await client.get(PREFIX + "/public/teams")

    assert response.status_code == 401
    assert selected == [list_tournament_teams]
