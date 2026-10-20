"""Pruebas de la puerta de compatibilidad de versiones de referencia (R04).

El validador es una función pura sobre el contenido de las fuentes técnicas y
documentales. No ejecuta Docker, pnpm ni Python: comprueba que todas las
fuentes declaren Python 3.14, Node 24 y pnpm 12.12.1, y que el pin del gestor
de paquetes del lockfile coincida sin alterar dependencias del proyecto.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra" / "scripts" / "verify_version_sources.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "verify_version_sources", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("verify_version_sources", module)
    spec.loader.exec_module(module)
    return module


versions = _load_module()

VALID_CI = """\
jobs:
  backend:
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.14'
  frontend:
    steps:
      - uses: pnpm/action-setup@v4
        with:
          version: 12.12.1
      - uses: actions/setup-node@v4
        with:
          node-version: '24'
  security:
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.14'
      - uses: pnpm/action-setup@v4
        with:
          version: 12.12.1
"""

VALID_BACKEND_DOCKERFILE = "FROM python:3.14-slim\n"

VALID_FRONTEND_DOCKERFILE = "FROM node:24-alpine AS build\n"

VALID_PACKAGE_JSON = """\
{
  "packageManager": "pnpm@12.12.1",
  "dependencies": {
    "nuxt": "^4.6.1"
  },
  "devDependencies": {
    "typescript": "^5.9.3"
  }
}
"""

VALID_TWO_DOCUMENT_WORKSPACE = """\
allowBuilds:
  esbuild: true
"""

VALID_PNPM_WORKSPACE = """\
# pnpm no escribe el documento de autogestión; CI fija la versión.
pmOnFail: ignore
allowBuilds:
  esbuild: true
"""

VALID_LOCKFILE = """\
---
lockfileVersion: '9.0'

importers:

  .:
    configDependencies: {}
    packageManagerDependencies:
      pnpm:
        specifier: 12.12.1
        version: 12.12.1

packages:

  pnpm@12.12.1:
    resolution: {integrity: sha512-fake}

snapshots:

  pnpm@12.12.1: {}

---
lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      nuxt:
        specifier: ^4.6.1
        version: 4.6.1
    devDependencies:
      typescript:
        specifier: ^5.9.3
        version: 5.9.3

packages: {}
"""

VALID_SINGLE_DOCUMENT_LOCKFILE = """\
lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

importers:

  .:
    dependencies:
      nuxt:
        specifier: ^4.6.1
        version: 4.6.2
    devDependencies:
      typescript:
        specifier: ^5.9.3
        version: 5.9.3

packages: {}
"""

VALID_AGENTS = (
    "Python 3.14, Node 24 y pnpm 12.12.1. "
    "Docker Compose 2.24.4 o superior y PROXY_NETWORK."
)

VALID_README = (
    "Versiones de referencia: Python 3.14, Node 24 y pnpm 12.12.1. "
    "Docker Compose 2.24.4 o superior y PROXY_NETWORK."
)

VALID_CONSTITUTION = "Python 3.14, Node 24 y pnpm 12.12.1."


def _sources(**overrides: str) -> dict[str, str]:
    sources = {
        "ci": VALID_CI,
        "backend_dockerfile": VALID_BACKEND_DOCKERFILE,
        "frontend_dockerfile": VALID_FRONTEND_DOCKERFILE,
        "package_json": VALID_PACKAGE_JSON,
        "pnpm_lockfile": VALID_LOCKFILE,
        "pnpm_workspace": VALID_TWO_DOCUMENT_WORKSPACE,
        "agents": VALID_AGENTS,
        "readme": VALID_README,
        "constitution": VALID_CONSTITUTION,
    }
    sources.update(overrides)
    return sources


def test_parse_semver_compara_mayor_menor_y_parche() -> None:
    assert versions.parse_semver("v3.14.4") == (3, 14, 4)
    assert versions.parse_semver("24") == (24, 0, 0)
    assert versions.parse_semver("12.12.1") == (12, 12, 1)


def test_version_at_least_cubre_python_node_y_pnpm() -> None:
    assert versions.version_at_least("3.14.0", "3.14") is True
    assert versions.version_at_least("3.13.9", "3.14") is False
    assert versions.version_at_least("24.11.1", "24") is True
    assert versions.version_at_least("22.22.1", "24") is False
    assert versions.version_at_least("12.12.1", "12.12.1") is True
    assert versions.version_at_least("12.12.0", "12.12.1") is False


def test_fuentes_validas_no_producen_errores() -> None:
    assert versions.validate_compatibility_gate(_sources()) == []


def test_repositorio_actual_cumple_sin_constitucion() -> None:
    sources = versions.collect_sources(REPO_ROOT, include_constitution=False)
    assert versions.validate_compatibility_gate(sources) == []


def test_detecta_python_de_ci_desalineado() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(ci=VALID_CI.replace("python-version: '3.14'", "python-version: '3.12'", 1))
    )
    assert any("Python" in error and "3.12" in error for error in errors)


def test_detecta_pnpm_de_ci_desalineado() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(ci=VALID_CI.replace("version: 12.12.1", "version: 12.11.2", 1))
    )
    assert any("pnpm" in error and "12.11.2" in error for error in errors)


def test_detecta_node_de_ci_desalineado() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(ci=VALID_CI.replace("node-version: '24'", "node-version: '22'"))
    )
    assert any("Node" in error and "22" in error for error in errors)


def test_detecta_dockerfile_de_backend_desalineado() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(backend_dockerfile="FROM python:3.12-slim\n")
    )
    assert any("backend/Dockerfile" in error and "3.12" in error for error in errors)


def test_detecta_package_manager_desalineado() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(package_json=VALID_PACKAGE_JSON.replace("pnpm@12.12.1", "pnpm@12.11.2"))
    )
    assert any("package.json" in error and "12.11.2" in error for error in errors)


def test_detecta_documentacion_con_version_obsoleta() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(readme=VALID_README.replace("Node 24", "Node 22"))
    )
    assert any("README" in error and "Node" in error for error in errors)


def test_detecta_documentacion_sin_versiones() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(agents="Docker Compose 2.24.4 y PROXY_NETWORK.")
    )
    assert any("AGENTS" in error and "Python" in error for error in errors)


def test_detecta_pin_de_lockfile_desalineado() -> None:
    lockfile = VALID_LOCKFILE.replace("specifier: 12.12.1", "specifier: 12.11.2", 1)
    errors = versions.validate_compatibility_gate(_sources(pnpm_lockfile=lockfile))
    assert any("pnpm-lock.yaml" in error and "12.11.2" in error for error in errors)


def test_detecta_lockfile_con_dependencias_incompatibles() -> None:
    lockfile = VALID_LOCKFILE.replace("specifier: ^4.6.1", "specifier: ^4.5.0")
    errors = versions.validate_compatibility_gate(_sources(pnpm_lockfile=lockfile))
    assert any("nuxt" in error and "^4.5.0" in error for error in errors)


def test_excluir_constitucion_omite_su_validacion() -> None:
    sources = _sources(constitution="Python 3.12, Node 22 y pnpm 12.11.2.")
    sources.pop("constitution")
    assert versions.validate_compatibility_gate(sources) == []


def test_lockfile_de_un_documento_valido_pasa() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(
            pnpm_lockfile=VALID_SINGLE_DOCUMENT_LOCKFILE,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert errors == []


def test_lockfile_de_un_documento_sin_pm_on_fail_falla() -> None:
    errors = versions.validate_compatibility_gate(
        _sources(
            pnpm_lockfile=VALID_SINGLE_DOCUMENT_LOCKFILE,
            pnpm_workspace=VALID_TWO_DOCUMENT_WORKSPACE,
        )
    )
    assert any(
        "pmOnFail" in error and "ignore" in error for error in errors
    ), errors


def test_lockfile_de_un_documento_sin_workspace_falla_con_mensaje() -> None:
    sources = _sources(pnpm_lockfile=VALID_SINGLE_DOCUMENT_LOCKFILE)
    sources.pop("pnpm_workspace")
    errors = versions.validate_compatibility_gate(sources)
    assert any(
        "pnpm-workspace.yaml" in error and "no está disponible" in error
        for error in errors
    ), errors


def test_lockfile_de_un_documento_sin_package_manager_falla() -> None:
    package_json = VALID_PACKAGE_JSON.replace(
        '  "packageManager": "pnpm@12.12.1",\n', ""
    )
    errors = versions.validate_compatibility_gate(
        _sources(
            package_json=package_json,
            pnpm_lockfile=VALID_SINGLE_DOCUMENT_LOCKFILE,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any("packageManager" in error for error in errors), errors


def test_lockfile_de_un_documento_con_pin_distinto_falla() -> None:
    package_json = VALID_PACKAGE_JSON.replace("pnpm@12.12.1", "pnpm@12.11.2")
    errors = versions.validate_compatibility_gate(
        _sources(
            package_json=package_json,
            pnpm_lockfile=VALID_SINGLE_DOCUMENT_LOCKFILE,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any(
        "package.json" in error and "12.11.2" in error for error in errors
    ), errors


def test_lockfile_de_un_documento_con_pin_con_rango_falla() -> None:
    package_json = VALID_PACKAGE_JSON.replace("pnpm@12.12.1", "pnpm@^12.12.1")
    errors = versions.validate_compatibility_gate(
        _sources(
            package_json=package_json,
            pnpm_lockfile=VALID_SINGLE_DOCUMENT_LOCKFILE,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any(
        "package.json" in error and "pnpm@^12.12.1" in error for error in errors
    ), errors


def test_lockfile_de_un_documento_sin_dependencia_resuelta_falla() -> None:
    lockfile = VALID_SINGLE_DOCUMENT_LOCKFILE.replace(
        """    devDependencies:
      typescript:
        specifier: ^5.9.3
        version: 5.9.3
""",
        "",
    )
    errors = versions.validate_compatibility_gate(
        _sources(
            pnpm_lockfile=lockfile,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any(
        "typescript" in error and "falta la dependencia" in error
        for error in errors
    ), errors


def test_lockfile_de_un_documento_sin_version_resuelta_falla() -> None:
    lockfile = VALID_SINGLE_DOCUMENT_LOCKFILE.replace(
        "version: 4.6.2", ""
    )
    errors = versions.validate_compatibility_gate(
        _sources(
            pnpm_lockfile=lockfile,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any(
        "nuxt" in error and "versión" in error for error in errors
    ), errors


def test_lockfile_de_un_documento_con_package_manager_dependencies_falla() -> None:
    lockfile = VALID_SINGLE_DOCUMENT_LOCKFILE.replace(
        "importers:\n\n  .:",
        """importers:

  .:
    packageManagerDependencies:
      pnpm:
        specifier: 12.12.1
        version: 12.12.1""",
    )
    errors = versions.validate_compatibility_gate(
        _sources(
            pnpm_lockfile=lockfile,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any(
        "packageManagerDependencies" in error and "un solo documento" in error
        for error in errors
    ), errors


def test_lockfile_de_dos_documentos_con_pm_on_fail_se_rechaza() -> None:
    # Decisión de T4b: con `pmOnFail: ignore` declarado, RF-008 exige un
    # lockfile de un solo documento. Un lockfile de dos documentos en ese
    # estado contradice la declaración y Trivy dejaría de auditar el frontend,
    # así que se rechaza en lugar de aceptarse por la rama de dos documentos.
    errors = versions.validate_compatibility_gate(
        _sources(
            pnpm_lockfile=VALID_LOCKFILE,
            pnpm_workspace=VALID_PNPM_WORKSPACE,
        )
    )
    assert any(
        "pmOnFail" in error and "un solo documento" in error for error in errors
    ), errors
