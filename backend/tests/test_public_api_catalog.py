"""Catálogo cerrado de la API pública v1 (spec 051, RF-001, RF-005, DA-1)."""

from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, iter_route_contexts

from app.main import api
from app.modules.public_api import catalog

EXPECTED = {
    ("GET", "/api/v1/tournaments/public"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/standings"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/matches"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/matches/{match_id}"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/matches/{match_id}/timeline"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/player-stats"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/team-stats"),
    ("GET", "/api/v1/tournaments/public/players/{player_id}"),
}

SESSION_DEPENDENCIES = {"get_auth_context", "get_current_user", "get_platform_admin"}


def test_catalog_has_exactly_the_nine_reads():
    assert set(catalog.PUBLIC_API_V1) == EXPECTED
    assert len(catalog.PUBLIC_API_V1) == 9


def test_catalog_path_is_versioned_v1():
    assert all(path.startswith("/api/v1/") for _, path in catalog.PUBLIC_API_V1)
    assert catalog.OPENAPI_PATH == "/api/v1/public/openapi.json"
    assert catalog.CONTRACT_VERSION == "v1"


def _routes():
    return {
        (method, context.path_format): context
        for context in iter_route_contexts(api.routes)
        if isinstance(context.original_route, APIRoute)
        for method in context.methods
    }


def _dependency_names(dependant):
    names = set()
    for dep in dependant.dependencies:
        names.add(getattr(dep.call, "__name__", ""))
        names |= _dependency_names(dep)
    return names


def test_every_catalog_read_exists_without_session_dependency():
    routes = _routes()
    for key in EXPECTED:
        assert key in routes, f"falta {key}"
        assert not _dependency_names(routes[key].dependant) & SESSION_DEPENDENCIES, key


def test_missing_catalog_route_is_reported():
    assert catalog.missing_routes(api.routes) == []
    assert catalog.missing_routes([]) == sorted(EXPECTED)


@pytest.mark.parametrize("method,path", sorted(EXPECTED))
def test_is_public_read_accepts_catalog_with_uuids(method, path):
    concrete = (
        path.replace("{tournament_id}", str(uuid4()))
        .replace("{match_id}", str(uuid4()))
        .replace("{player_id}", str(uuid4()))
    )
    assert catalog.is_public_read("GET", concrete)
    assert catalog.is_public_read("OPTIONS", concrete)


def test_is_public_read_accepts_the_openapi_document():
    assert catalog.is_public_read("GET", catalog.OPENAPI_PATH)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/tournaments/public/share-image"),
        ("GET", f"/api/v1/tournaments/public/{uuid4()}/share-image"),
        ("GET", f"/api/v1/tournaments/public/{uuid4()}/matches/{uuid4()}/share-image"),
        ("GET", "/api/v1/tournaments/public/not-a-uuid"),
        ("GET", f"/api/v1/tournaments/public/{uuid4()}/standings/extra"),
        ("GET", "/api/v1/tournaments/public/"),
        ("POST", "/api/v1/tournaments/public"),
        ("DELETE", f"/api/v1/tournaments/public/{uuid4()}"),
        ("GET", "/api/v1/tournaments"),
        ("GET", f"/api/v1/tournaments/{uuid4()}/matches"),
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/platform/organizations"),
        ("GET", "/openapi.json"),
    ],
)
def test_is_public_read_rejects_everything_else(method, path):
    assert not catalog.is_public_read(method, path)
