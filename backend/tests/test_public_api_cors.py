"""CORS de la API pública v1 (spec 051, RF-008, RF-009, RF-009b, RF-010).

Las lecturas del catálogo y su documento aceptan cualquier origen, solo GET y
sin credenciales. El origen configurado del sitio y el resto de la API, incluidas
las imágenes de la 043, conservan el CORS de siempre.
"""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import allowed_origins, api, app
from app.modules.public_api import catalog
from db_helpers import clear_rls_context, set_tenant_context
from test_public_access_matrix import (
    _create_tournament,
    _public_api,
    _publish_tournament,
    _register_team,
    _skip_if_no_db,
)

FOREIGN = "https://terceros.example.org"
SITE = allowed_origins[0]


def _concrete(path: str) -> str:
    return (
        path.replace("{tournament_id}", str(uuid4()))
        .replace("{match_id}", str(uuid4()))
        .replace("{player_id}", str(uuid4()))
    )


CATALOG_PATHS = [_concrete(path) for _, path in catalog.PUBLIC_API_V1] + [catalog.OPENAPI_PATH]
SHARE_IMAGES = [
    "/api/v1/tournaments/public/share-image",
    f"/api/v1/tournaments/public/{uuid4()}/share-image",
    f"/api/v1/tournaments/public/{uuid4()}/matches/{uuid4()}/share-image",
]
PRIVATE_PATHS = ["/api/v1/tournaments", "/api/v1/auth/me"]


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _preflight_headers(origin: str, method: str = "GET", headers: str | None = None):
    result = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers:
        result["Access-Control-Request-Headers"] = headers
    return result


def _assert_open_without_credentials(response):
    assert response.headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-credentials" not in response.headers
    assert "Origin" in response.headers.get("vary", "")


def test_site_origin_is_configured_and_foreign_is_not():
    assert FOREIGN not in allowed_origins
    assert "*" not in allowed_origins


@pytest.mark.parametrize("path", CATALOG_PATHS)
async def test_preflight_from_any_origin_allows_only_get(path):
    async with _client() as client:
        response = await client.options(path, headers=_preflight_headers(FOREIGN))
    assert response.status_code == 204
    _assert_open_without_credentials(response)
    assert response.headers["access-control-allow-methods"] == "GET"
    assert "access-control-allow-headers" not in response.headers


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_preflight_rejects_other_methods(method):
    async with _client() as client:
        response = await client.options(CATALOG_PATHS[1], headers=_preflight_headers(FOREIGN, method))
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("header", ["Authorization", "X-Organization-ID", "X-CSRF-Token", "Cookie"])
async def test_preflight_rejects_authentication_headers(header):
    async with _client() as client:
        response = await client.options(
            CATALOG_PATHS[1], headers=_preflight_headers(FOREIGN, headers=f"Accept, {header}")
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_preflight_accepts_safelisted_headers():
    async with _client() as client:
        response = await client.options(
            CATALOG_PATHS[1], headers=_preflight_headers(FOREIGN, headers="accept, accept-language")
        )
    assert response.status_code == 204
    _assert_open_without_credentials(response)


async def test_get_document_from_any_origin():
    async with _client() as client:
        response = await client.get(catalog.OPENAPI_PATH, headers={"Origin": FOREIGN})
    assert response.status_code == 200
    _assert_open_without_credentials(response)
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_get_without_origin_is_also_open():
    async with _client() as client:
        response = await client.get(catalog.OPENAPI_PATH)
    _assert_open_without_credentials(response)


async def test_errors_of_catalog_reads_are_readable_from_any_origin():
    path = f"/api/v1/tournaments/public/{uuid4()}/standings?limit=0"
    async with _client() as client:
        response = await client.get(path, headers={"Origin": FOREIGN})
    assert response.status_code == 422
    _assert_open_without_credentials(response)


async def test_options_without_preflight_headers_is_not_answered_by_cors():
    async with _client() as client:
        response = await client.options(catalog.OPENAPI_PATH, headers={"Origin": FOREIGN})
    assert response.status_code == 405


@pytest.mark.parametrize("path", SHARE_IMAGES + PRIVATE_PATHS)
async def test_rest_of_api_keeps_closed_preflight_for_foreign_origins(path):
    async with _client() as client:
        preflight = await client.options(path, headers=_preflight_headers(FOREIGN))
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


@pytest.mark.parametrize("path", SHARE_IMAGES[:1] + PRIVATE_PATHS)
async def test_rest_of_api_does_not_open_responses_to_foreign_origins(path):
    async with _client() as client:
        simple = await client.get(path, headers={"Origin": FOREIGN})
    assert "access-control-allow-origin" not in simple.headers


@pytest.mark.parametrize("path", [CATALOG_PATHS[1], catalog.OPENAPI_PATH, PRIVATE_PATHS[0]])
async def test_site_origin_keeps_current_cors_with_credentials(path):
    async with _client() as client:
        preflight = await client.options(path, headers=_preflight_headers(SITE, "GET"))
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == SITE
    assert preflight.headers["access-control-allow-credentials"] == "true"


async def test_site_origin_get_keeps_credentials():
    async with _client() as client:
        response = await client.get(catalog.OPENAPI_PATH, headers={"Origin": SITE})
    assert response.headers["access-control-allow-origin"] == SITE
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_catalog_reads_from_foreign_origin_match_same_origin(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Public CORS Owner")
    await set_tenant_context(db_session, tenant)
    published_id, version_id, _ = await _create_tournament(db_session, tenant, label="cors")
    await _register_team(db_session, tenant, published_id)
    await _publish_tournament(db_session, published_id, version_id)
    draft_id, _, _ = await _create_tournament(db_session, tenant, label="cors-draft")
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        for path in (
            "/api/v1/tournaments/public",
            f"/api/v1/tournaments/public/{published_id}",
            f"/api/v1/tournaments/public/{published_id}/standings",
        ):
            plain = await client.get(path)
            foreign = await client.get(path, headers={"Origin": FOREIGN})
            assert foreign.status_code == plain.status_code == 200
            assert foreign.json() == plain.json()
        for tournament_id in (draft_id, uuid4()):
            path = f"/api/v1/tournaments/public/{tournament_id}"
            plain = await client.get(path)
            foreign = await client.get(path, headers={"Origin": FOREIGN})
            assert plain.status_code == foreign.status_code == 404
            assert plain.json() == foreign.json() == {"detail": "Torneo público no encontrado"}


def test_cors_middleware_wraps_the_application():
    names = [middleware.cls.__name__ for middleware in api.user_middleware]
    assert names.index("PublicReadCorsMiddleware") < names.index("CORSMiddleware")
