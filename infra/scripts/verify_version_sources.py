#!/usr/bin/env python3
"""Puerta de compatibilidad de las versiones de referencia de Bracket Craft.

Comprueba que todas las fuentes técnicas y documentales declaren la misma
combinación (Python 3.14, Node 24 y pnpm 12.12.1) y que el lockfile del
frontend fije el gestor de paquetes en esa versión sin cambiar dependencias
del proyecto.

La verificación es pura: recibe el contenido de los archivos como texto y no
ejecuta Docker, pnpm ni Python. Las pruebas ejecutables de compatibilidad
(instalar dependencias, tests, typecheck, build, imágenes y auditorías) se
mantienen en la puerta de T007 y en CI.

Uso::

    python infra/scripts/verify_version_sources.py
    python infra/scripts/verify_version_sources.py --exclude-constitution
    python infra/scripts/verify_version_sources.py --root /ruta/al/repo

La constitución se excluye en el commit técnico de R04 porque su enmienda va
en un entregable separado y revisado (T008).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PYTHON_REFERENCE = "3.14"
NODE_REFERENCE = "24"
PNPM_REFERENCE = "12.12.1"
MINIMUM_COMPOSE_VERSION = "2.24.4"

#: Rutas relativas a la raíz del repositorio.
SOURCE_PATHS = {
    "ci": Path(".github/workflows/ci.yml"),
    "backend_dockerfile": Path("backend/Dockerfile"),
    "frontend_dockerfile": Path("frontend/Dockerfile"),
    "package_json": Path("frontend/package.json"),
    "pnpm_lockfile": Path("frontend/pnpm-lock.yaml"),
    "agents": Path("AGENTS.md"),
    "readme": Path("README.md"),
    "constitution": Path("docs/constitution.md"),
}

REQUIRED_SOURCES = tuple(
    key for key in SOURCE_PATHS if key != "constitution"
)


def parse_semver(version: str) -> tuple[int, int, int]:
    """Convierte ``3.14``, ``v24.11.1`` o ``12.12.1`` en una tupla de enteros.

    Ignora sufijos de pre-release/build (``3.14.0-rc1``). Lanza ``ValueError``
    si la versión no es numérica.
    """

    raw = str(version).strip()
    if raw[:1] in {"v", "V"}:
        raw = raw[1:]
    core = raw.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".") if core else []
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Versión no válida: {version!r}")
    numbers = [int(part) for part in parts]
    numbers.extend([0] * (3 - len(numbers)))
    return (numbers[0], numbers[1], numbers[2])


def version_at_least(version: str, minimum: str) -> bool:
    """Compara mayor, menor y parche: ``3.13.9 < 3.14`` y ``3.14 >= 3.14``."""

    return parse_semver(version) >= parse_semver(minimum)


def _matches_python(version: str) -> bool:
    return parse_semver(version)[:2] == parse_semver(PYTHON_REFERENCE)[:2]


def _matches_node(version: str) -> bool:
    return parse_semver(version)[0] == parse_semver(NODE_REFERENCE)[0]


def _matches_pnpm(version: str) -> bool:
    return parse_semver(version) == parse_semver(PNPM_REFERENCE)


def _doc_version_patterns() -> tuple[tuple[str, str], ...]:
    return (
        ("Python", r"\bPython\s+(\d+(?:\.\d+){0,2})"),
        ("Node", r"\bNode(?:\.js)?\s+(\d+(?:\.\d+){0,2})"),
        ("pnpm", r"\bpnpm\s+(\d+\.\d+\.\d+)"),
    )


def _validate_documentation(
    label: str, text: str, *, require_infrastructure: bool = True
) -> list[str]:
    errors: list[str] = []
    for name, pattern in _doc_version_patterns():
        matches = re.findall(pattern, text)
        if not matches:
            reference = {
                "Python": PYTHON_REFERENCE,
                "Node": NODE_REFERENCE,
                "pnpm": PNPM_REFERENCE,
            }[name]
            errors.append(
                f"{label}: no declara la versión de referencia {name} {reference}"
            )
            continue
        for version in matches:
            valid = {
                "Python": _matches_python,
                "Node": _matches_node,
                "pnpm": _matches_pnpm,
            }[name](version)
            if not valid:
                expected = {
                    "Python": PYTHON_REFERENCE,
                    "Node": NODE_REFERENCE,
                    "pnpm": PNPM_REFERENCE,
                }[name]
                errors.append(
                    f"{label}: declara {name} {version}; se esperaba {expected}"
                )
    if require_infrastructure and MINIMUM_COMPOSE_VERSION not in text:
        errors.append(
            f"{label}: no declara Docker Compose {MINIMUM_COMPOSE_VERSION} o superior"
        )
    if require_infrastructure and "PROXY_NETWORK" not in text:
        errors.append(
            f"{label}: no declara el prerrequisito de la red externa (PROXY_NETWORK)"
        )
    return errors


def _validate_ci(text: str) -> list[str]:
    errors: list[str] = []

    python_versions = re.findall(
        r"python-version:\s*['\"]?([^'\"\s]+)", text
    )
    if not python_versions:
        errors.append("ci.yml: no declara python-version")
    for version in python_versions:
        if not _matches_python(version):
            errors.append(
                f"ci.yml: usa Python {version}; se esperaba {PYTHON_REFERENCE} "
                "en todos los jobs que instalan Python"
            )

    node_versions = re.findall(r"node-version:\s*['\"]?([^'\"\s]+)", text)
    if not node_versions:
        errors.append("ci.yml: no declara node-version")
    for version in node_versions:
        if not _matches_node(version):
            errors.append(
                f"ci.yml: usa Node {version}; se esperaba {NODE_REFERENCE}"
            )

    pnpm_versions: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "pnpm/action-setup@" not in line:
            continue
        for following in lines[index + 1 : index + 4]:
            match = re.match(
                r"\s*version:\s*['\"]?([^'\"\s]+)", following
            )
            if match:
                pnpm_versions.append(match.group(1))
                break
        else:
            errors.append(
                "ci.yml: pnpm/action-setup no declara una versión explícita"
            )

    if not pnpm_versions:
        errors.append("ci.yml: no usa pnpm/action-setup")
    for version in pnpm_versions:
        if not _matches_pnpm(version):
            errors.append(
                f"ci.yml: usa pnpm {version}; se esperaba {PNPM_REFERENCE} "
                "en todos los usos de pnpm/action-setup"
            )
    return errors


def _dockerfile_base_version(text: str, image: str) -> list[str]:
    pattern = rf"^FROM\s+{re.escape(image)}:([^\s]+)"
    return [match.group(1).split("-", 1)[0] for match in re.finditer(
        pattern, text, flags=re.MULTILINE
    )]


def _validate_backend_dockerfile(text: str) -> list[str]:
    versions = _dockerfile_base_version(text, "python")
    if not versions:
        return ["backend/Dockerfile: no declara una imagen base FROM python:<versión>"]
    return [
        f"backend/Dockerfile: usa Python {version}; se esperaba {PYTHON_REFERENCE}"
        for version in versions
        if not _matches_python(version)
    ]


def _validate_frontend_dockerfile(text: str) -> list[str]:
    versions = _dockerfile_base_version(text, "node")
    if not versions:
        return ["frontend/Dockerfile: no declara una imagen base FROM node:<versión>"]
    return [
        f"frontend/Dockerfile: usa Node {version}; se esperaba {NODE_REFERENCE}"
        for version in versions
        if not _matches_node(version)
    ]


def _validate_package_json(text: str) -> list[str]:
    try:
        package = json.loads(text)
    except json.JSONDecodeError as error:
        return [f"frontend/package.json: JSON no válido: {error}"]
    package_manager = str(package.get("packageManager") or "")
    if not package_manager.startswith("pnpm@"):
        return [
            "frontend/package.json: packageManager debe declarar pnpm@"
            f"{PNPM_REFERENCE}"
        ]
    version = package_manager.split("@", 1)[1]
    if not _matches_pnpm(version):
        return [
            f"frontend/package.json: packageManager declara pnpm@{version}; "
            f"se esperaba pnpm@{PNPM_REFERENCE}"
        ]
    return []


def _first_yaml_document(text: str) -> str:
    return text.split("\n---\n", 1)[0]


def _second_yaml_document(text: str) -> str:
    parts = text.split("\n---\n", 1)
    return parts[1] if len(parts) > 1 else ""


def _parse_importer_dependencies(text: str) -> dict[str, str]:
    """Extrae las dependencias del importer raíz del lockfile de proyecto."""

    document = _second_yaml_document(text)
    dependencies: dict[str, str] = {}
    section: str | None = None
    current: str | None = None

    for line in document.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if not stripped:
            continue
        if indent == 4 and stripped in {"dependencies:", "devDependencies:"}:
            section = stripped[:-1]
            current = None
            continue
        if indent <= 4:
            section = None
            current = None
            continue
        if section is None:
            continue
        if indent == 6 and stripped.endswith(":"):
            current = stripped[:-1].strip("'\"")
            continue
        if (
            indent == 8
            and current
            and stripped.startswith("specifier:")
        ):
            dependencies[current] = (
                stripped.split(":", 1)[1].strip().strip("'\"")
            )
            current = None
    return dependencies


def _project_dependencies(package_json: str) -> dict[str, str]:
    try:
        package = json.loads(package_json)
    except json.JSONDecodeError:
        return {}
    result: dict[str, str] = {}
    for key in ("dependencies", "devDependencies"):
        section = package.get(key)
        if isinstance(section, Mapping):
            result.update({str(name): str(spec) for name, spec in section.items()})
    return result


def validate_lockfile(pnpm_lockfile: str, package_json: str) -> list[str]:
    """Valida el pin del gestor y la coherencia de dependencias del lockfile.

    Falla si el pin del gestor no es ``pnpm@12.12.1`` o si el bloque de
    dependencias del proyecto (más allá del pin) no coincide con
    ``package.json``.
    """

    errors: list[str] = []
    manager_match = re.search(
        r"packageManagerDependencies:\s*\n"
        r"\s*pnpm:\s*\n"
        r"\s*specifier:\s*(\S+)\s*\n"
        r"\s*version:\s*(\S+)",
        pnpm_lockfile,
    )
    if manager_match is None:
        errors.append(
            "frontend/pnpm-lock.yaml: no declara packageManagerDependencies para pnpm"
        )
    else:
        specifier, version = manager_match.groups()
        if not _matches_pnpm(specifier):
            errors.append(
                f"frontend/pnpm-lock.yaml: packageManagerDependencies declara "
                f"pnpm {specifier}; se esperaba {PNPM_REFERENCE}"
            )
        if not _matches_pnpm(version):
            errors.append(
                f"frontend/pnpm-lock.yaml: packageManagerDependencies resuelve "
                f"pnpm {version}; se esperaba {PNPM_REFERENCE}"
            )

    first_document = _first_yaml_document(pnpm_lockfile)
    if f"pnpm@{PNPM_REFERENCE}:" not in first_document:
        errors.append(
            "frontend/pnpm-lock.yaml: falta el bloque resuelto "
            f"pnpm@{PNPM_REFERENCE} del gestor de paquetes"
        )
    stale_manager_versions = {
        version
        for version in re.findall(
            r"(?:@pnpm/exe\.[^\s@]+@|^\s*pnpm@)(\d+\.\d+\.\d+):?",
            first_document,
            flags=re.MULTILINE,
        )
        if version != PNPM_REFERENCE
    }
    for version in sorted(stale_manager_versions):
        errors.append(
            "frontend/pnpm-lock.yaml: conserva el gestor resuelto "
            f"pnpm {version}; se esperaba {PNPM_REFERENCE}"
        )

    locked = _parse_importer_dependencies(pnpm_lockfile)
    declared = _project_dependencies(package_json)
    if locked or declared:
        for name in sorted(set(declared) | set(locked)):
            if name not in locked:
                errors.append(
                    f"frontend/pnpm-lock.yaml: falta la dependencia {name} "
                    "declarada en package.json"
                )
            elif name not in declared:
                errors.append(
                    f"frontend/pnpm-lock.yaml: resuelve {name}, que no está "
                    "declarada en package.json"
                )
            elif locked[name] != declared[name]:
                errors.append(
                    f"frontend/pnpm-lock.yaml: {name} usa el specifier "
                    f"{locked[name]}; package.json declara {declared[name]}"
                )
    return errors


def validate_version_sources(sources: Mapping[str, str]) -> list[str]:
    """Devuelve las discrepancias de versiones entre fuentes."""

    errors: list[str] = []
    for key in REQUIRED_SOURCES:
        if key not in sources or not sources[key].strip():
            errors.append(f"Falta la fuente obligatoria: {key}")

    if sources.get("ci"):
        errors.extend(_validate_ci(sources["ci"]))
    if sources.get("backend_dockerfile"):
        errors.extend(_validate_backend_dockerfile(sources["backend_dockerfile"]))
    if sources.get("frontend_dockerfile"):
        errors.extend(_validate_frontend_dockerfile(sources["frontend_dockerfile"]))
    if sources.get("package_json"):
        errors.extend(_validate_package_json(sources["package_json"]))
    if sources.get("agents"):
        errors.extend(_validate_documentation("AGENTS.md", sources["agents"]))
    if sources.get("readme"):
        errors.extend(_validate_documentation("README.md", sources["readme"]))
    if sources.get("constitution"):
        errors.extend(
            _validate_documentation(
                "docs/constitution.md",
                sources["constitution"],
                require_infrastructure=False,
            )
        )
    return errors


def validate_compatibility_gate(sources: Mapping[str, str]) -> list[str]:
    """Puerta completa: fuentes de versión + pin y dependencias del lockfile."""

    errors = validate_version_sources(sources)
    lockfile = sources.get("pnpm_lockfile") or ""
    package_json = sources.get("package_json") or ""
    if lockfile:
        errors.extend(validate_lockfile(lockfile, package_json))
    return errors


def collect_sources(root: Path, *, include_constitution: bool = True) -> dict[str, str]:
    """Lee las fuentes desde ``root``. Omite la constitución si se excluye."""

    sources: dict[str, str] = {}
    for key, relative in SOURCE_PATHS.items():
        if key == "constitution" and not include_constitution:
            continue
        path = root / relative
        if path.exists():
            sources[key] = path.read_text(encoding="utf-8")
    return sources


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verifica que CI, Dockerfiles, package.json, el lockfile, AGENTS, "
            "README y (opcionalmente) la constitución declaren Python 3.14, "
            "Node 24 y pnpm 12.12.1."
        )
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Raíz del repositorio (por defecto, el directorio del script)",
    )
    parser.add_argument(
        "--exclude-constitution",
        action="store_true",
        help="No valida docs/constitution.md (commit técnico de R04)",
    )
    args = parser.parse_args(argv)

    sources = collect_sources(
        Path(args.root), include_constitution=not args.exclude_constitution
    )
    errors = validate_compatibility_gate(sources)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(
            f"ERROR: {len(errors)} discrepancia(s) de versiones de referencia",
            file=sys.stderr,
        )
        return 1
    print(
        "OK: Python "
        f"{PYTHON_REFERENCE}, Node {NODE_REFERENCE} y pnpm {PNPM_REFERENCE} "
        "coinciden en las fuentes verificadas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
