"""Versión única del producto (RF-018, R32d / M6).

La versión se declara una sola vez en ``backend/pyproject.toml``
(``[project].version``) y ``backend/app/main.py`` la lee con ``tomllib`` para
``FastAPI(version=...)``. La documentación de la API la expone en
``/openapi.json`` (y Swagger UI la muestra en ``/docs``). La versión del
contrato de reglas (``engine_version`` 2026.1) es otra y no se mezcla.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import PRODUCT_VERSION, api
from app.modules.rule_contract import ENGINE_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
PYPROJECT_PATH = BACKEND_ROOT / "pyproject.toml"
MAIN_PATH = BACKEND_ROOT / "app" / "main.py"

SEMVER = re.compile(r"\b\d+\.\d+\.\d+\b")


def declared_version() -> str:
    with PYPROJECT_PATH.open("rb") as pyproject:
        return tomllib.load(pyproject)["project"]["version"]


def test_pyproject_declares_the_product_version():
    with PYPROJECT_PATH.open("rb") as pyproject:
        project = tomllib.load(pyproject)["project"]

    assert project["name"]
    assert SEMVER.fullmatch(project["version"])


def test_fastapi_uses_the_declared_version_without_an_independent_literal():
    version = declared_version()
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert PRODUCT_VERSION == version
    assert api.version == version
    # Ningún literal semver independiente en el punto de entrada.
    assert SEMVER.findall(source) == []
    assert not re.search(r"version\s*=\s*[\"']", source)


def test_no_other_product_version_literal_lives_in_the_backend():
    version = declared_version()
    offenders = []
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        if version in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


@pytest.mark.asyncio
async def test_openapi_exposes_the_declared_version():
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == declared_version()
    assert response.json()["info"]["version"] == api.version


@pytest.mark.asyncio
async def test_docs_serves_the_spec_that_shows_the_declared_version():
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        docs = await client.get("/docs")
        assert docs.status_code == 200
        assert "/openapi.json" in docs.text

        spec_url = re.search(r"url:\s*['\"]([^'\"]*openapi\.json)['\"]", docs.text)
        assert spec_url is not None
        spec = await client.get(spec_url.group(1))

    assert spec.status_code == 200
    assert spec.json()["info"]["version"] == declared_version()


def test_engine_version_is_independent_from_the_product_version():
    assert ENGINE_VERSION == "2026.1"
    assert declared_version() != ENGINE_VERSION
    assert api.version != ENGINE_VERSION
    assert api.openapi()["info"]["version"] != ENGINE_VERSION
