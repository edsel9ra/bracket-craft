"""Documento OpenAPI de la API pública v1 (spec 051, RF-002, RF-004, RNF-002)."""

import pytest
from httpx import ASGITransport, AsyncClient
from openapi_spec_validator import validate

from app.main import api
from app.modules.matches.live_public import PublicClockFields, SuspendedPublicMatchResponse
from app.modules.public_api import catalog
from app.modules.public_api.openapi import build_public_openapi
from test_public_field_allowlist import EXPECTED_FIELDS

CLOCK_FIELDS = set(PublicClockFields.model_fields)
# Proyecciones del partido en vivo de la 036: mismas claves que la 020 más el reloj,
# y las 14 claves exactas del partido suspendido.
ALLOWED_FIELDS = {
    **EXPECTED_FIELDS,
    "ClassicPublicMatchResponse": EXPECTED_FIELDS["PublicMatchResponse"],
    "LivePublicMatchResponse": EXPECTED_FIELDS["PublicMatchResponse"] | CLOCK_FIELDS,
    "SuspendedPublicMatchResponse": set(SuspendedPublicMatchResponse.model_fields),
}
ERROR_SCHEMAS = {"PublicError", "HTTPValidationError", "ValidationError"}


@pytest.fixture(scope="module")
def document():
    return build_public_openapi(api)


def test_document_is_valid_openapi_3_1(document):
    assert document["openapi"].startswith("3.1.")
    validate(document)


def test_document_is_identified_as_v1(document):
    assert document["info"]["version"] == "v1"


def test_document_contains_exactly_the_catalog(document):
    operations = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        for method in item
    }
    assert operations == set(catalog.PUBLIC_API_V1)


def test_document_has_no_workspace_auth_or_platform_routes(document):
    for path in document["paths"]:
        assert path.startswith("/api/v1/tournaments/public"), path
        assert "share-image" not in path


def test_every_operation_documents_success_and_errors(document):
    for path, item in document["paths"].items():
        operation = item["get"]
        assert "200" in operation["responses"], path
        if "{" in path:
            not_found = operation["responses"]["404"]
            ref = not_found["content"]["application/json"]["schema"]["$ref"]
            assert ref == "#/components/schemas/PublicError"
        assert "422" in operation["responses"], path


def test_every_operation_documents_the_proxy_rate_limit(document):
    for path, item in document["paths"].items():
        too_many = item["get"]["responses"]["429"]
        ref = too_many["content"]["application/json"]["schema"]["$ref"]
        assert ref == "#/components/schemas/PublicError", path
        assert too_many["headers"]["Retry-After"]["schema"] == {"type": "integer"}, path


def test_operations_carry_no_internal_notes(document):
    for path, item in document["paths"].items():
        operation = item["get"]
        assert "description" not in operation, path
        assert operation["tags"] == ["public-api-v1"], path


def test_every_response_schema_is_in_the_closed_allowlist(document):
    schemas = document["components"]["schemas"]
    for name, schema in schemas.items():
        if name in ERROR_SCHEMAS:
            continue
        assert name in ALLOWED_FIELDS, f"esquema fuera de la lista cerrada: {name}"
        properties = set(schema.get("properties", {}))
        extra = properties - ALLOWED_FIELDS[name]
        assert not extra, f"{name}: campos fuera de la lista cerrada: {sorted(extra)}"


def test_error_schema_only_has_detail(document):
    schema = document["components"]["schemas"]["PublicError"]
    assert set(schema["properties"]) == {"detail"}
    assert schema["required"] == ["detail"]


def test_build_fails_when_a_catalog_route_is_missing():
    from fastapi import FastAPI

    with pytest.raises(RuntimeError, match="/api/v1/tournaments/public"):
        build_public_openapi(FastAPI())


@pytest.mark.asyncio
async def test_endpoint_serves_document_without_session():
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get(catalog.OPENAPI_PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "set-cookie" not in response.headers
    assert response.json() == build_public_openapi(api)
