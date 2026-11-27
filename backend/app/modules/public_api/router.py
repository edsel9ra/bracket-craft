"""Publica sin sesión el documento OpenAPI del catálogo v1 (spec 051, RF-002)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.modules.public_api.openapi import build_public_openapi

router = APIRouter(tags=["public-api"])


@router.get("/public/openapi.json", include_in_schema=False)
async def public_openapi(request: Request) -> dict[str, Any]:
    state = request.app.state
    document = getattr(state, "public_openapi", None)
    if document is None:
        document = build_public_openapi(request.app)
        state.public_openapi = document
    return document
