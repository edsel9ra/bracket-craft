"""Catálogo cerrado del contrato público v1 (spec 051, RF-001, RF-005, DA-1)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

CONTRACT_VERSION = "v1"
OPENAPI_PATH = "/api/v1/public/openapi.json"

PUBLIC_API_V1: tuple[tuple[str, str], ...] = (
    ("GET", "/api/v1/tournaments/public"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/standings"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/matches"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/matches/{match_id}"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/matches/{match_id}/timeline"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/player-stats"),
    ("GET", "/api/v1/tournaments/public/{tournament_id}/team-stats"),
    ("GET", "/api/v1/tournaments/public/players/{player_id}"),
)

_UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_READ_METHODS = frozenset({"GET", "OPTIONS"})


def _compile(template: str) -> re.Pattern[str]:
    parts = re.split(r"\{[a-z_]+\}", template)
    return re.compile("^" + _UUID.join(re.escape(part) for part in parts) + "$")


_PATTERNS = tuple(_compile(path) for _, path in PUBLIC_API_V1) + (_compile(OPENAPI_PATH),)


def is_public_read(method: str, path: str) -> bool:
    """True solo para GET/OPTIONS de una lectura del catálogo o de su documento OpenAPI."""

    if method.upper() not in _READ_METHODS:
        return False
    return any(pattern.match(path) for pattern in _PATTERNS)


def catalog_route_contexts(routes: Iterable[object]) -> list[RouteContext]:
    """Rutas efectivas (con el prefijo de cada router incluido) que forman el catálogo."""

    catalog = set(PUBLIC_API_V1)
    return [
        context
        for context in iter_route_contexts(list(routes))
        if isinstance(context.original_route, APIRoute)
        and any((method, context.path_format) in catalog for method in context.methods or ())
    ]


def missing_routes(routes: Iterable[object]) -> list[tuple[str, str]]:
    present = {
        (method, context.path_format)
        for context in catalog_route_contexts(routes)
        for method in context.methods or ()
    }
    return sorted(set(PUBLIC_API_V1) - present)
