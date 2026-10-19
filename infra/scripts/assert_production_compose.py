#!/usr/bin/env python3
"""Aserciones estructurales sobre la configuración combinada de producción.

La función :func:`validate_production_config` recibe la salida de
``docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json``
y devuelve una lista de errores. No ejecuta Docker ni lee el entorno: es pura y
se puede probar sin Docker.

Uso en CI/local::

    docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
        | python infra/scripts/assert_production_compose.py -

    python infra/scripts/assert_production_compose.py --compose-version "$(docker compose version --short)"

El script falla (código de salida 1) si algún servicio publica puertos, si
``api``/``worker``/``web`` montan código del host, si ``db``/``db-migrate``
montan algo distinto de ``./infra/postgres`` en solo lectura, si las redes no
son las esperadas, si la red externa del proxy no está declarada como externa o
si los comandos no son de producción.

Requiere Docker Compose 2.24.4 o superior (``!reset``/``!override`` y
comparación de parche) cuando se usa ``--compose-version``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

MINIMUM_COMPOSE_VERSION = "2.24.4"

#: Red interna del stack.
STACK_NETWORK = "internal"
#: Red externa del proxy (nombre configurable con PROXY_NETWORK).
PROXY_NETWORK = "edge"

#: Servicios que en producción ejecutan solo artefactos construidos.
PRODUCTION_CODE_SERVICES = ("api", "worker", "web")
#: Servicios que pueden conservar montajes de infraestructura de PostgreSQL.
INFRA_POSTGRES_SERVICES = ("db", "db-migrate")

#: Volumen de datos que debe declararse y seguir montado en producción.
DATA_VOLUMES = {
    "postgres_data": "db",
    "redis_data": "redis",
    "storage_data": "storage",
}

CODE_ROOTS = ("backend", "frontend", "infra")
INFRA_POSTGRES_ROOT = "infra/postgres"

WEB_PRODUCTION_COMMAND = ["node", ".output/server/index.mjs"]


def parse_semver(version: str) -> tuple[int, int, int]:
    """Convierte ``2.24.4``, ``v5.5.1`` o ``2.24`` en una tupla de tres enteros.

    Ignora sufijos de pre-release/build (``2.24.4-desktop.1``). Lanza
    ``ValueError`` si la versión no es numérica.
    """

    raw = str(version).strip()
    if raw[:1] in {"v", "V"}:
        raw = raw[1:]
    core = raw.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".") if core else []
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Versión de Compose no válida: {version!r}")
    numbers = [int(part) for part in parts]
    numbers.extend([0] * (3 - len(numbers)))
    return (numbers[0], numbers[1], numbers[2])


def version_at_least(version: str, minimum: str) -> bool:
    """Compara mayor, menor y parche: ``2.24.3 < 2.24.4`` y ``2.24.4 >= 2.24.4``."""

    return parse_semver(version) >= parse_semver(minimum)


def _normalize_source(source: Any) -> str:
    text = str(source).replace("\\", "/").strip()
    if not text:
        return ""
    return text.rstrip("/") or "/"


def _has_path_segments(path: Any, root: str) -> bool:
    """Indica si ``root`` aparece como secuencia contigua de segmentos en ``path``.

    Sirve para comparar tanto rutas relativas (``./infra/postgres``) como las
    absolutas que renderiza Compose (``/srv/bracket-craft/infra/postgres``).
    """

    segments = [segment for segment in _normalize_source(path).split("/") if segment]
    wanted = [segment for segment in root.split("/") if segment]
    if not wanted or len(segments) < len(wanted):
        return False
    width = len(wanted)
    return any(segments[index : index + width] == wanted for index in range(len(segments) - width + 1))


def _command_tokens(command: Any) -> list[str]:
    if command is None:
        return []
    if isinstance(command, str):
        return command.split()
    if isinstance(command, Sequence):
        return [str(token) for token in command]
    return []


def _describe_ports(ports: Any) -> str:
    if not isinstance(ports, Sequence) or isinstance(ports, (str, bytes)):
        return str(ports)
    descriptions: list[str] = []
    for port in ports:
        if isinstance(port, Mapping):
            published = port.get("published")
            target = port.get("target")
            host_ip = port.get("host_ip")
            description = f"{published or '?'}->{target or '?'}"
            if host_ip:
                description += f" ({host_ip})"
            descriptions.append(description)
        else:
            descriptions.append(str(port))
    return ", ".join(descriptions)


def _validate_networks(name: str, service: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    networks = service.get("networks")
    actual = set(networks.keys()) if isinstance(networks, Mapping) else set()
    expected = {STACK_NETWORK, PROXY_NETWORK} if name == "web" else {STACK_NETWORK}
    unexpected = actual - expected
    missing = expected - actual
    if unexpected:
        errors.append(
            f"{name}: red(es) no permitida(s) {sorted(unexpected)}; "
            f"se esperaba {sorted(expected)}"
        )
    if missing:
        errors.append(
            f"{name}: falta(n) la(s) red(es) {sorted(missing)}; "
            f"se esperaba {sorted(expected)}"
        )
    return errors


def _validate_volumes(
    name: str, service: Mapping[str, Any], errors: list[str]
) -> None:
    volumes = service.get("volumes") or []
    if not isinstance(volumes, Sequence) or isinstance(volumes, (str, bytes)):
        errors.append(f"{name}: la lista de volúmenes no es válida")
        return
    for volume in volumes:
        if not isinstance(volume, Mapping):
            errors.append(f"{name}: montaje no válido: {volume!r}")
            continue
        volume_type = volume.get("type")
        source = _normalize_source(volume.get("source") or "")
        target = volume.get("target")
        read_only = bool(volume.get("read_only"))

        if name in PRODUCTION_CODE_SERVICES:
            if volume_type == "bind":
                errors.append(
                    f"{name}: monta código del host ({source or '?'} -> {target or '?'})"
                )
            elif volume_type == "volume" and not source:
                errors.append(
                    f"{name}: monta un volumen anónimo ({target or '?'}) que puede "
                    "sombrear los artefactos construidos"
                )
        elif name in INFRA_POSTGRES_SERVICES:
            if volume_type == "bind":
                if not _has_path_segments(source, INFRA_POSTGRES_ROOT):
                    errors.append(
                        f"{name}: montaje bind no permitido ({source or '?'} -> "
                        f"{target or '?'}); solo se permite {INFRA_POSTGRES_ROOT} "
                        "en solo lectura"
                    )
                elif not read_only:
                    errors.append(
                        f"{name}: el montaje de {source} debe ser de solo lectura "
                        "(read_only: true)"
                    )
        else:
            if volume_type == "bind" and any(
                _has_path_segments(source, root) for root in CODE_ROOTS
            ):
                errors.append(
                    f"{name}: monta código del host ({source or '?'} -> "
                    f"{target or '?'})"
                )


def validate_production_config(config: Mapping[str, Any]) -> list[str]:
    """Devuelve los errores de la configuración combinada de producción.

    Una lista vacía significa que la configuración cumple RF-006, RF-007 y
    RF-009. La función no ejecuta Docker ni depende del entorno.
    """

    errors: list[str] = []
    services = config.get("services")
    if not isinstance(services, Mapping) or not services:
        return ["La configuración no declara servicios"]

    for name, service in services.items():
        if not isinstance(service, Mapping):
            continue

        ports = service.get("ports")
        if ports:
            errors.append(
                f"{name}: publica puertos en el host ({_describe_ports(ports)})"
            )

        errors.extend(_validate_networks(name, service))
        _validate_volumes(name, service, errors)

    api_command = _command_tokens((services.get("api") or {}).get("command"))
    if not api_command:
        errors.append("api: no declara un comando de producción")
    elif "--reload" in api_command:
        errors.append("api: arranca con recarga automática (--reload)")

    web_command = _command_tokens((services.get("web") or {}).get("command"))
    if web_command != WEB_PRODUCTION_COMMAND:
        errors.append(
            "web: el comando debe ser "
            f"{' '.join(WEB_PRODUCTION_COMMAND)!r} (recibido: "
            f"{' '.join(web_command) or 'ninguno'!r})"
        )

    networks = config.get("networks")
    networks = networks if isinstance(networks, Mapping) else {}
    edge = networks.get(PROXY_NETWORK)
    if not isinstance(edge, Mapping):
        errors.append(
            f"networks.{PROXY_NETWORK}: no está declarada la red externa del proxy"
        )
    else:
        if edge.get("external") is not True:
            errors.append(
                f"networks.{PROXY_NETWORK}: debe declararse como external: true "
                "(red externa del proxy)"
            )
        if not edge.get("name"):
            errors.append(
                f"networks.{PROXY_NETWORK}: debe declarar un nombre configurable "
                "(PROXY_NETWORK)"
            )

    internal = networks.get(STACK_NETWORK)
    if not isinstance(internal, Mapping):
        errors.append(f"networks.{STACK_NETWORK}: falta la red interna del stack")
    elif internal.get("external") is True:
        errors.append(f"networks.{STACK_NETWORK}: no puede ser una red externa")

    declared_volumes = config.get("volumes")
    declared_volumes = (
        declared_volumes if isinstance(declared_volumes, Mapping) else {}
    )
    for volume_name, service_name in DATA_VOLUMES.items():
        if volume_name not in declared_volumes:
            errors.append(f"volumes: falta el volumen de datos {volume_name}")
        service = services.get(service_name) or {}
        volumes = service.get("volumes") or []
        mounted = any(
            isinstance(volume, Mapping)
            and volume.get("type") in (None, "volume")
            and _normalize_source(volume.get("source") or "") == volume_name
            for volume in (volumes if isinstance(volumes, Sequence) else [])
        )
        if not mounted:
            errors.append(
                f"{service_name}: no monta el volumen de datos {volume_name}"
            )

    return errors


def _load_config(path: str) -> Mapping[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Valida la configuración combinada dev+producción de Docker Compose "
            "y la versión mínima de Compose (2.24.4)."
        )
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="JSON renderizado por 'docker compose config --format json'; usa - para stdin",
    )
    parser.add_argument(
        "--compose-version",
        default=None,
        help="Versión instalada de Docker Compose (p. ej. $(docker compose version --short))",
    )
    parser.add_argument(
        "--minimum-compose-version",
        default=MINIMUM_COMPOSE_VERSION,
        help=f"Versión mínima exigida (por defecto {MINIMUM_COMPOSE_VERSION})",
    )
    args = parser.parse_args(argv)

    if args.config is None and args.compose_version is None:
        args.config = "-"

    exit_code = 0

    if args.compose_version:
        try:
            supported = version_at_least(
                args.compose_version, args.minimum_compose_version
            )
        except ValueError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if not supported:
            print(
                "ERROR: Docker Compose "
                f"{args.compose_version} no cumple el mínimo "
                f"{args.minimum_compose_version} requerido por !reset/!override. "
                "Actualiza Docker Compose.",
                file=sys.stderr,
            )
            exit_code = 1
        else:
            print(
                "OK: Docker Compose "
                f"{args.compose_version} >= {args.minimum_compose_version}"
            )

    if args.config is not None:
        try:
            config = _load_config(args.config)
        except (OSError, json.JSONDecodeError) as error:
            print(f"ERROR: no se pudo leer la configuración: {error}", file=sys.stderr)
            return 1

        errors = validate_production_config(config)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if errors:
            print(
                f"ERROR: la configuración combinada de producción tiene "
                f"{len(errors)} incumplimiento(s)",
                file=sys.stderr,
            )
            exit_code = 1
        else:
            print(
                "OK: la configuración combinada de producción no publica puertos, "
                "no monta código del host y usa las redes esperadas"
            )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
