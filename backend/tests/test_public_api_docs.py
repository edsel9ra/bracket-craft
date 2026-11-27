"""Guías ES/EN de la API pública y ejemplo del proxy (spec 051, RF-003, RF-007, RF-011, RF-011b, RNF-003)."""

import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import TypeAdapter

from app.main import api
from app.modules.public_api import catalog

ROOT = Path(__file__).resolve().parents[2]
GUIDES = {"es": ROOT / "docs" / "api-publica.md", "en": ROOT / "docs" / "api-publica.en.md"}
PROXY_DOC = ROOT / "docs" / "despliegue-proxy-tiempo-real.md"
HISTORY_HEADINGS = {"es": "## Historial de cambios", "en": "## Changelog"}
LIMIT_HEADINGS = {"es": "## Límite de peticiones", "en": "## Rate limit"}
VERSION_HEADINGS = {"es": "## Política de versiones", "en": "## Versioning policy"}

OPERATIONS = {
    "list_tournaments": "/api/v1/tournaments/public",
    "tournament": "/api/v1/tournaments/public/{tournament_id}",
    "standings": "/api/v1/tournaments/public/{tournament_id}/standings",
    "matches": "/api/v1/tournaments/public/{tournament_id}/matches",
    "match": "/api/v1/tournaments/public/{tournament_id}/matches/{match_id}",
    "timeline": "/api/v1/tournaments/public/{tournament_id}/matches/{match_id}/timeline",
    "player_stats": "/api/v1/tournaments/public/{tournament_id}/player-stats",
    "team_stats": "/api/v1/tournaments/public/{tournament_id}/team-stats",
    "player_profile": "/api/v1/tournaments/public/players/{player_id}",
}
EXAMPLE = re.compile(r"<!-- ejemplo: (?P<operation>[a-z_]+) -->\s*```json\n(?P<body>.*?)\n```", re.S)


def _guide(lang: str) -> str:
    return GUIDES[lang].read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def _examples(lang: str) -> list[tuple[str, str]]:
    return [(match["operation"], match["body"]) for match in EXAMPLE.finditer(_guide(lang))]


def _response_models():
    models = {}
    for context in iter_route_contexts(api.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and "GET" in context.methods:
            models[context.path_format] = route.response_model
    return models


def _concrete(path: str) -> str:
    return re.sub(r"\{[a-z_]+\}", lambda _: str(uuid4()), path)


def test_operations_are_the_catalog():
    assert sorted(OPERATIONS.values()) == sorted(path for _, path in catalog.PUBLIC_API_V1)


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_guide_has_one_example_per_operation(lang):
    operations = [operation for operation, _ in _examples(lang)]
    assert sorted(operations) == sorted(OPERATIONS)


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_every_example_validates_against_its_response_model(lang):
    models = _response_models()
    for operation, body in _examples(lang):
        model = models[OPERATIONS[operation]]
        assert model is not None, operation
        TypeAdapter(model).validate_json(body)


def test_both_guides_share_the_same_examples():
    assert _examples("es") == _examples("en")


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_guide_documents_base_url_errors_and_contract(lang):
    text = _guide(lang)
    for expected in (
        catalog.OPENAPI_PATH,
        "/api/v1/tournaments/public",
        "Torneo público no encontrado",
        "404",
        "422",
        "429",
        "Retry-After",
        "limit",
        "offset",
        "Access-Control-Allow-Origin: *",
        "docs/api-publica/openapi-v1.json",
    ):
        assert expected in text, expected
    for path in OPERATIONS.values():
        assert f"GET {path}" in text, path
    assert "share-image" not in text


@pytest.mark.parametrize("lang", sorted(GUIDES))
def test_guide_versioning_policy_and_dated_history(lang):
    text = _guide(lang)
    policy = _section(text, VERSION_HEADINGS[lang])
    assert "v1" in policy and "v2" in policy
    history = _section(text, HISTORY_HEADINGS[lang])
    entries = re.findall(r"^- \*\*(\d{4}-\d{2}-\d{2})\*\* · `v1`", history, re.M)
    assert entries, history
    assert entries == sorted(entries)


def _nginx_block() -> str:
    text = PROXY_DOC.read_text(encoding="utf-8")
    section = _section(text, "## Límite de la API pública (spec 051)")
    blocks = re.findall(r"```nginx\n(.*?)\n```", section, re.S)
    assert len(blocks) == 1
    return blocks[0]


def _nginx_location() -> re.Pattern[str]:
    match = re.search(r'location ~ "(?P<regex>[^"]+)" \{', _nginx_block())
    assert match
    return re.compile(match["regex"])


def test_proxy_example_limits_per_ip_with_429_and_retry_after():
    block = _nginx_block()
    zone = re.search(r"limit_req_zone \$binary_remote_addr zone=public_api:\d+m rate=(\d+)r/m;", block)
    burst = re.search(r"limit_req zone=public_api burst=(\d+) nodelay;", block)
    assert zone and burst
    assert "limit_req_status 429;" in block
    assert re.search(r"add_header Retry-After \d+ always;", block)
    assert 'add_header Access-Control-Allow-Origin "*" always;' in block
    assert "proxy_pass http://api:8000;" in block
    for lang in GUIDES:
        limit = _section(_guide(lang), LIMIT_HEADINGS[lang])
        assert zone[1] in limit and burst[1] in limit


def test_proxy_location_covers_exactly_the_catalog():
    location = _nginx_location()
    accepted = [_concrete(path) for _, path in catalog.PUBLIC_API_V1] + [catalog.OPENAPI_PATH]
    rejected = [
        "/api/v1/tournaments/public/share-image",
        _concrete("/api/v1/tournaments/public/{t}/share-image"),
        _concrete("/api/v1/tournaments/public/{t}/matches/{m}/share-image"),
        "/api/v1/tournaments/public/no-es-uuid",
        _concrete("/api/v1/tournaments/public/{t}/standings/extra"),
        "/api/v1/tournaments",
        "/api/v1/auth/me",
        _concrete("/api/v1/matches/{m}/live"),
        "/api/v1/public/openapi.json/extra",
        "/api/v1/tournaments/publicx",
    ]
    for path in accepted:
        assert location.search(path), path
        assert catalog.is_public_read("GET", path)
    for path in rejected:
        assert not location.search(path), path
        assert not catalog.is_public_read("GET", path)


def test_proxy_section_explains_that_ssr_skips_the_proxy():
    text = PROXY_DOC.read_text(encoding="utf-8")
    section = _section(text, "## Límite de la API pública (spec 051)")
    assert "NUXT_API_INTERNAL_BASE" in section
    assert "^~" in section
