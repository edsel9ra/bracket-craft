#!/usr/bin/env python3
"""Aserciones estructurales sobre la configuración renderizada de Compose.

La función :func:`validate_production_config` recibe la salida de
``docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json``
y devuelve una lista de errores. :func:`validate_development_config` hace lo
propio con la salida de ``docker compose config --format json`` (perfil de
desarrollo). Ninguna ejecuta Docker ni lee el entorno: son puras y se pueden
probar sin Docker.

Uso en CI/local::

    # Producción (perfil por defecto): merge dev+producción.
    docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
        | python infra/scripts/assert_production_compose.py -

    # Desarrollo: puerto de API en loopback, web publicado como hoy y healthchecks.
    docker compose config --format json \
        | python infra/scripts/assert_production_compose.py --profile development -

    python infra/scripts/assert_production_compose.py --compose-version "$(docker compose version --short)"

El script falla (código de salida 1) si algún servicio publica puertos fuera de
lo esperado, si ``api``/``worker``/``web`` montan código del host, si
``db``/``db-migrate`` montan algo distinto de ``./infra/postgres`` en solo
lectura, si las redes no son las esperadas, si la red externa del proxy no está
declarada como externa, si los comandos no son de producción, si falta la
verificación de salud de ``api``/``worker``/``web``, si ``web`` no espera a que
la API esté sana o si ``web`` se ejecuta como raíz en producción. En desarrollo
exige además el puerto de la API en la interfaz local y la publicación intacta
del servicio web.

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

#: Perfiles de configuración validables.
PROFILE_DEVELOPMENT = "development"
PROFILE_PRODUCTION = "production"
PROFILES = (PROFILE_DEVELOPMENT, PROFILE_PRODUCTION)

#: Servicios con verificación de salud propia (RF-014).
HEALTHCHECK_SERVICES = ("api", "worker", "web")

#: Interfaces que cuentan como acceso local.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

#: Puerto del servicio web en desarrollo: punto de entrada del desarrollador.
WEB_DEVELOPMENT_PORT = 3000
#: Puerto de la API en desarrollo (solo interfaz local, RF-013).
API_DEVELOPMENT_PORT = 8000
#: Servicios de datos que en desarrollo publican solo en la interfaz local.
DEVELOPMENT_DATA_SERVICES = ("db", "redis", "storage")


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


def _port_entries(service: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Devuelve los mapeos de puerto renderizados (ignora formas no válidas)."""

    ports = service.get("ports")
    if not isinstance(ports, Sequence) or isinstance(ports, (str, bytes)):
        return []
    return [port for port in ports if isinstance(port, Mapping)]


def _port_label(port: Mapping[str, Any]) -> str:
    return f"{port.get('published') or '?'}->{port.get('target') or '?'}"


def _validate_healthchecks(
    services: Mapping[str, Any], errors: list[str]
) -> None:
    for name in HEALTHCHECK_SERVICES:
        service = services.get(name)
        if not isinstance(service, Mapping):
            errors.append(f"{name}: no está declarado en la configuración (RF-014)")
            continue
        healthcheck = service.get("healthcheck")
        if not isinstance(healthcheck, Mapping):
            errors.append(
                f"{name}: falta la verificación de salud (healthcheck) (RF-014)"
            )
            continue
        test = healthcheck.get("test")
        empty = test is None or not str(test).strip()
        if isinstance(test, Sequence) and not isinstance(test, (str, bytes)):
            empty = len(test) == 0
        if empty:
            errors.append(
                f"{name}: la verificación de salud no declara un comando de "
                "prueba (healthcheck.test) (RF-014)"
            )


def _validate_web_waits_for_api(
    services: Mapping[str, Any], errors: list[str]
) -> None:
    web = services.get("web")
    depends_on = web.get("depends_on") if isinstance(web, Mapping) else None
    api = depends_on.get("api") if isinstance(depends_on, Mapping) else None
    condition = api.get("condition") if isinstance(api, Mapping) else None
    if condition != "service_healthy":
        errors.append(
            "web: debe esperar a que la API esté sana al arrancar "
            "(depends_on.api.condition: service_healthy) (RF-014)"
        )


def _is_root_user(user: Any) -> bool:
    text = str(user).strip()
    if not text:
        return True
    uid = text.split(":", 1)[0].strip()
    return uid in {"", "0", "root"}


def _validate_web_user(services: Mapping[str, Any], errors: list[str]) -> None:
    web = services.get("web")
    if not isinstance(web, Mapping):
        errors.append(
            "web: no está declarado en la configuración de producción (RF-002)"
        )
        return
    user = web.get("user")
    if user is None or not str(user).strip():
        errors.append(
            "web: no declara un usuario no-root en producción (user ausente) "
            "(RF-002)"
        )
        return
    if _is_root_user(user):
        errors.append(
            f"web: se ejecuta como raíz en producción (user: {user}) (RF-002)"
        )


def _validate_development_ports(
    services: Mapping[str, Any], errors: list[str]
) -> None:
    api = services.get("api")
    if not isinstance(api, Mapping):
        errors.append(
            "api: no está declarado en la configuración de desarrollo (RF-013)"
        )
    else:
        matching = [
            port
            for port in _port_entries(api)
            if str(port.get("target")) == str(API_DEVELOPMENT_PORT)
        ]
        if not matching:
            errors.append(
                f"api: no publica el puerto {API_DEVELOPMENT_PORT} en la "
                "interfaz local (RF-013)"
            )
        else:
            for port in matching:
                host_ip = str(port.get("host_ip") or "")
                if host_ip not in LOOPBACK_HOSTS:
                    errors.append(
                        f"api: publica el puerto {API_DEVELOPMENT_PORT} fuera "
                        "de la interfaz local (host_ip: "
                        f"{host_ip or 'todas las interfaces'}) (RF-013)"
                    )
                elif str(port.get("published")) != str(API_DEVELOPMENT_PORT):
                    errors.append(
                        "api: el puerto publicado debe ser "
                        f"{API_DEVELOPMENT_PORT} en la interfaz local "
                        f"(recibido: {_port_label(port)}) (RF-013)"
                    )

    web = services.get("web")
    if not isinstance(web, Mapping):
        errors.append(
            "web: no está declarado en la configuración de desarrollo (RF-013)"
        )
    else:
        matching = [
            port
            for port in _port_entries(web)
            if str(port.get("target")) == str(WEB_DEVELOPMENT_PORT)
        ]
        if not matching:
            errors.append(
                f"web: no publica el puerto {WEB_DEVELOPMENT_PORT} (punto de "
                "entrada del desarrollador) (RF-013)"
            )
        else:
            for port in matching:
                host_ip = str(port.get("host_ip") or "")
                if host_ip in LOOPBACK_HOSTS:
                    errors.append(
                        "web: la publicación de desarrollo debe conservar "
                        f"{WEB_DEVELOPMENT_PORT}:{WEB_DEVELOPMENT_PORT} "
                        "accesible fuera del loopback (recibido: "
                        f"{_port_label(port)} en {host_ip}) (RF-013)"
                    )
                elif str(port.get("published")) != str(WEB_DEVELOPMENT_PORT):
                    errors.append(
                        "web: el puerto publicado en desarrollo debe ser "
                        f"{WEB_DEVELOPMENT_PORT} (recibido: "
                        f"{_port_label(port)}) (RF-013)"
                    )

    for name in DEVELOPMENT_DATA_SERVICES:
        service = services.get(name)
        if not isinstance(service, Mapping):
            errors.append(
                f"{name}: no está declarado en la configuración de desarrollo "
                "(RF-013)"
            )
            continue
        entries = _port_entries(service)
        if not entries:
            errors.append(
                f"{name}: no publica su puerto en la interfaz local (RF-013)"
            )
            continue
        for port in entries:
            host_ip = str(port.get("host_ip") or "")
            if host_ip not in LOOPBACK_HOSTS:
                errors.append(
                    f"{name}: publica el puerto {port.get('target') or '?'} "
                    "fuera de la interfaz local (host_ip: "
                    f"{host_ip or 'todas las interfaces'}) (RF-013)"
                )
                break


def validate_development_config(config: Mapping[str, Any]) -> list[str]:
    """Devuelve los errores de la configuración renderizada de desarrollo.

    Una lista vacía significa que la API solo se publica en la interfaz local,
    el servicio web conserva su publicación y ``api``/``worker``/``web``
    declaran verificación de salud (RF-013, RF-014). La función no ejecuta
    Docker ni depende del entorno.
    """

    services = config.get("services")
    if not isinstance(services, Mapping) or not services:
        return ["La configuración no declara servicios"]

    errors: list[str] = []
    _validate_development_ports(services, errors)
    _validate_healthchecks(services, errors)
    _validate_web_waits_for_api(services, errors)
    return errors


def validate_production_config(config: Mapping[str, Any]) -> list[str]:
    """Devuelve los errores de la configuración combinada de producción.

    Una lista vacía significa que la configuración cumple RF-002, RF-006,
    RF-007, RF-009 y RF-014. La función no ejecuta Docker ni depende del
    entorno.
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

    _validate_healthchecks(services, errors)
    _validate_web_user(services, errors)
    _validate_web_waits_for_api(services, errors)

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
            "Valida la configuración renderizada de Docker Compose (desarrollo "
            "o merge dev+producción), sus verificaciones de salud y la versión "
            "mínima de Compose (2.24.4). Por defecto valida producción."
        )
    )
    parser.add_argument(
        "config",
        nargs="?",
        default=None,
        help="JSON renderizado por 'docker compose config --format json'; usa - para stdin",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=PROFILE_PRODUCTION,
        help=(
            "Perfil a validar. 'production' (por defecto) exige el merge "
            "dev+producción: sin puertos publicados, sin código del host, web "
            "no-root y healthchecks en api/worker/web. 'development' exige la "
            "API en 127.0.0.1, el web publicado como hoy (3000:3000), los "
            "servicios de datos en la interfaz local y los mismos healthchecks."
        ),
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

        if args.profile == PROFILE_DEVELOPMENT:
            errors = validate_development_config(config)
        else:
            errors = validate_production_config(config)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if args.profile == PROFILE_DEVELOPMENT:
            if errors:
                print(
                    "ERROR: la configuración de desarrollo tiene "
                    f"{len(errors)} incumplimiento(s)",
                    file=sys.stderr,
                )
                exit_code = 1
            else:
                print(
                    "OK: la configuración de desarrollo publica la API solo en "
                    "la interfaz local, conserva la publicación del web y "
                    "declara las verificaciones de salud"
                )
        elif errors:
            print(
                f"ERROR: la configuración combinada de producción tiene "
                f"{len(errors)} incumplimiento(s)",
                file=sys.stderr,
            )
            exit_code = 1
        else:
            print(
                "OK: la configuración combinada de producción no publica puertos, "
                "no monta código del host, usa las redes esperadas, ejecuta el "
                "web sin privilegios y declara las verificaciones de salud"
            )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
