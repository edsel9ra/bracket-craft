"""Documento OpenAPI 3.1 que contiene solo el catálogo público v1 (spec 051, RF-002)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from app.modules.public_api.catalog import CONTRACT_VERSION, catalog_route_contexts, missing_routes

TITLE = "Bracket Craft — API pública"
DESCRIPTION = (
    "Lecturas públicas de torneos, sin sesión ni credenciales. "
    "Guía: docs/api-publica.md (ES) y docs/api-publica.en.md (EN)."
)
PUBLIC_ERROR_SCHEMA: dict[str, Any] = {
    "title": "PublicError",
    "type": "object",
    "properties": {"detail": {"type": "string", "title": "Detail"}},
    "required": ["detail"],
}
NOT_FOUND = {
    "description": "Recurso inexistente o no visible públicamente; las dos respuestas son idénticas.",
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PublicError"}}},
}


def build_public_openapi(app: FastAPI) -> dict[str, Any]:
    missing = missing_routes(app.routes)
    if missing:
        raise RuntimeError(f"Faltan rutas del catálogo público: {missing}")
    routes = catalog_route_contexts(app.routes)
    document = get_openapi(
        title=TITLE,
        version=CONTRACT_VERSION,
        openapi_version="3.1.0",
        description=DESCRIPTION,
        routes=routes,
        servers=[{"url": "/"}],
    )
    document.setdefault("components", {}).setdefault("schemas", {})["PublicError"] = PUBLIC_ERROR_SCHEMA
    for path, item in document["paths"].items():
        operation = item["get"]
        # Los docstrings de las rutas son notas internas del equipo, no del contrato.
        operation.pop("description", None)
        operation["tags"] = ["public-api-v1"]
        if "{" in path:
            operation["responses"]["404"] = NOT_FOUND
    return json.loads(json.dumps(document))
