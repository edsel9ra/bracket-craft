"""Pruebas unitarias del validador de la configuración combinada de producción.

El validador es una función pura sobre la salida de
``docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json``.
No requiere Docker ni base de datos.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra" / "scripts" / "assert_production_compose.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "assert_production_compose", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("assert_production_compose", module)
    spec.loader.exec_module(module)
    return module


assertions = _load_module()


def _service(
    *,
    ports: list[dict[str, Any]] | None = None,
    volumes: list[dict[str, Any]] | None = None,
    networks: dict[str, Any] | None = None,
    command: list[str] | None = None,
    healthcheck: dict[str, Any] | None = None,
    user: Any = None,
    depends_on: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service: dict[str, Any] = {}
    if command is not None:
        service["command"] = command
    if ports is not None:
        service["ports"] = ports
    if volumes is not None:
        service["volumes"] = volumes
    if networks is not None:
        service["networks"] = networks
    if healthcheck is not None:
        service["healthcheck"] = healthcheck
    if user is not None:
        service["user"] = user
    if depends_on is not None:
        service["depends_on"] = depends_on
    return service


def _healthcheck() -> dict[str, Any]:
    """Forma mínima de un healthcheck renderizado por Compose."""

    return {
        "test": ["CMD-SHELL", "true"],
        "interval": "10s",
        "timeout": "5s",
        "retries": 3,
    }


def _published(host_ip: str | None, published: str, target: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "mode": "ingress",
        "published": published,
        "target": target,
        "protocol": "tcp",
    }
    if host_ip is not None:
        entry["host_ip"] = host_ip
    return entry


def _web_waits_for_api() -> dict[str, Any]:
    return {"api": {"condition": "service_healthy", "required": True}}


def _bind(source: str, target: str, *, read_only: bool = False) -> dict[str, Any]:
    volume: dict[str, Any] = {"type": "bind", "source": source, "target": target}
    if read_only:
        volume["read_only"] = True
    return volume


def _named_volume(source: str, target: str) -> dict[str, Any]:
    return {"type": "volume", "source": source, "target": target}


def _render_service_networks(names: list[str]) -> dict[str, Any]:
    return {name: None for name in names}


def _valid_config() -> dict[str, Any]:
    """Configuración combinada correcta, con las formas reales del JSON de Compose."""

    internal = _render_service_networks(["internal"])
    internal_and_edge = _render_service_networks(["internal", "edge"])

    return {
        "services": {
            "db": _service(
                volumes=[
                    _named_volume("postgres_data", "/var/lib/postgresql/data"),
                    _bind(
                        "/repo/infra/postgres/init",
                        "/docker-entrypoint-initdb.d",
                        read_only=True,
                    ),
                ],
                networks=deepcopy(internal),
            ),
            "db-migrate": _service(
                volumes=[
                    _bind(
                        "/repo/infra/postgres",
                        "/migrations",
                        read_only=True,
                    )
                ],
                networks=deepcopy(internal),
            ),
            "api": _service(
                volumes=[],
                networks=deepcopy(internal),
                command=[
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                    "--workers",
                    "2",
                ],
                healthcheck=_healthcheck(),
            ),
            "worker": _service(
                volumes=[],
                networks=deepcopy(internal),
                command=["python", "-m", "app.workers.outbox"],
                healthcheck=_healthcheck(),
            ),
            "redis": _service(
                volumes=[_named_volume("redis_data", "/data")],
                networks=deepcopy(internal),
            ),
            "storage": _service(
                volumes=[_named_volume("storage_data", "/data")],
                networks=deepcopy(internal),
            ),
            "web": _service(
                volumes=[],
                networks=deepcopy(internal_and_edge),
                command=["node", ".output/server/index.mjs"],
                healthcheck=_healthcheck(),
                user="node",
                depends_on=_web_waits_for_api(),
            ),
        },
        "volumes": {
            "postgres_data": None,
            "redis_data": None,
            "storage_data": None,
        },
        "networks": {
            "internal": {"name": "bracket-craft_internal"},
            "edge": {"name": "edge", "external": True},
        },
    }


def _errors(config: dict[str, Any]) -> list[str]:
    return assertions.validate_production_config(config)


def _valid_development_config() -> dict[str, Any]:
    """Configuración renderizada de desarrollo, con las formas reales del JSON.

    El ``web`` publica ``3000:3000`` sin ``host_ip`` (todas las interfaces) y
    conserva la excepción de usuario raíz de desarrollo (NFR-012).
    """

    return {
        "services": {
            "db": _service(
                ports=[_published("127.0.0.1", "5432", 5432)],
                volumes=[
                    _named_volume("postgres_data", "/var/lib/postgresql/data"),
                    _bind(
                        "./infra/postgres/init",
                        "/docker-entrypoint-initdb.d",
                        read_only=True,
                    ),
                ],
                healthcheck=_healthcheck(),
            ),
            "db-migrate": _service(
                volumes=[
                    _bind("./infra/postgres", "/migrations", read_only=True)
                ],
            ),
            "api": _service(
                ports=[_published("127.0.0.1", "8000", 8000)],
                volumes=[
                    _bind("./backend", "/app"),
                    _bind("./infra", "/infra", read_only=True),
                ],
                healthcheck=_healthcheck(),
            ),
            "worker": _service(
                volumes=[_bind("./backend", "/app")],
                command=["python", "-m", "app.workers.outbox"],
                healthcheck=_healthcheck(),
            ),
            "redis": _service(
                ports=[_published("127.0.0.1", "6379", 6379)],
                volumes=[_named_volume("redis_data", "/data")],
                healthcheck=_healthcheck(),
            ),
            "storage": _service(
                ports=[
                    _published("127.0.0.1", "9000", 9000),
                    _published("127.0.0.1", "9001", 8888),
                ],
                volumes=[_named_volume("storage_data", "/data")],
                healthcheck=_healthcheck(),
            ),
            "web": _service(
                ports=[_published(None, "3000", 3000)],
                volumes=[
                    _bind("./frontend", "/app"),
                    {"type": "volume", "target": "/app/node_modules"},
                ],
                command=["pnpm", "run", "dev"],
                healthcheck=_healthcheck(),
                user="0:0",
                depends_on=_web_waits_for_api(),
            ),
        }
    }


def _dev_errors(config: dict[str, Any]) -> list[str]:
    return assertions.validate_development_config(config)


# ---------------------------------------------------------------------------
# Puertos
# ---------------------------------------------------------------------------


def test_valid_config_has_no_errors() -> None:
    assert _errors(_valid_config()) == []


def test_detects_published_port() -> None:
    config = _valid_config()
    config["services"]["db"]["ports"] = [
        {"mode": "ingress", "published": "5432", "target": 5432, "protocol": "tcp"}
    ]

    errors = _errors(config)

    assert errors
    assert any("db" in error and "puerto" in error.lower() for error in errors)


def test_detects_published_port_with_host_ip() -> None:
    config = _valid_config()
    config["services"]["web"]["ports"] = [
        {
            "mode": "ingress",
            "host_ip": "127.0.0.1",
            "published": "3000",
            "target": 3000,
            "protocol": "tcp",
        }
    ]

    errors = _errors(config)

    assert any("web" in error and "puerto" in error.lower() for error in errors)


def test_detects_published_port_on_every_service() -> None:
    for name in _valid_config()["services"]:
        config = _valid_config()
        config["services"][name]["ports"] = [
            {"mode": "ingress", "published": "1234", "target": 1234}
        ]
        assert any(name in error for error in _errors(config)), name


# ---------------------------------------------------------------------------
# Montajes de código
# ---------------------------------------------------------------------------


def test_detects_backend_bind_in_api() -> None:
    config = _valid_config()
    config["services"]["api"]["volumes"] = [_bind("/repo/backend", "/app")]

    errors = _errors(config)

    assert any("api" in error and "backend" in error for error in errors)


def test_detects_frontend_bind_in_web() -> None:
    config = _valid_config()
    config["services"]["web"]["volumes"] = [_bind("./frontend", "/app")]

    errors = _errors(config)

    assert any("web" in error and "frontend" in error for error in errors)


def test_detects_infra_bind_in_worker() -> None:
    config = _valid_config()
    config["services"]["worker"]["volumes"] = [
        _bind("/repo/infra", "/infra", read_only=True)
    ]

    errors = _errors(config)

    assert any("worker" in error and "infra" in error for error in errors)


def test_rejects_anonymous_code_volume_in_web() -> None:
    config = _valid_config()
    config["services"]["web"]["volumes"] = [
        {"type": "volume", "target": "/app/node_modules"}
    ]

    errors = _errors(config)

    assert any("web" in error for error in errors)


def test_accepts_read_only_infra_postgres_mounts_in_db_services() -> None:
    config = _valid_config()

    assert _errors(config) == []


def test_rejects_bind_of_code_in_db() -> None:
    config = _valid_config()
    config["services"]["db"]["volumes"].append(_bind("/repo/backend", "/app"))

    errors = _errors(config)

    assert any("db" in error and "backend" in error for error in errors)


def test_rejects_writable_infra_postgres_mount_in_db_migrate() -> None:
    config = _valid_config()
    config["services"]["db-migrate"]["volumes"] = [
        _bind("/repo/infra/postgres", "/migrations", read_only=False)
    ]

    errors = _errors(config)

    assert any("db-migrate" in error for error in errors)


# ---------------------------------------------------------------------------
# Redes
# ---------------------------------------------------------------------------


def test_requires_edge_network_only_on_web() -> None:
    config = _valid_config()
    config["services"]["web"]["networks"] = _render_service_networks(["internal"])

    errors = _errors(config)

    assert any("web" in error and "edge" in error for error in errors)


def test_rejects_edge_network_on_api() -> None:
    config = _valid_config()
    config["services"]["api"]["networks"] = _render_service_networks(
        ["internal", "edge"]
    )

    errors = _errors(config)

    assert any("api" in error and "edge" in error for error in errors)


def test_rejects_service_left_on_default_network() -> None:
    config = _valid_config()
    config["services"]["db"]["networks"] = _render_service_networks(["default"])

    errors = _errors(config)

    assert any("db" in error for error in errors)


def test_rejects_service_without_networks() -> None:
    config = _valid_config()
    config["services"]["worker"].pop("networks")

    errors = _errors(config)

    assert any("worker" in error for error in errors)


def test_requires_edge_external() -> None:
    config = _valid_config()
    config["networks"]["edge"]["external"] = False

    errors = _errors(config)

    assert any("edge" in error and "external" in error for error in errors)


def test_requires_internal_network_declared() -> None:
    config = _valid_config()
    del config["networks"]["internal"]

    errors = _errors(config)

    assert any("internal" in error for error in errors)


# ---------------------------------------------------------------------------
# Comandos de producción
# ---------------------------------------------------------------------------


def test_rejects_api_reload() -> None:
    config = _valid_config()
    config["services"]["api"]["command"] = [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--reload",
    ]

    errors = _errors(config)

    assert any("api" in error and "reload" in error for error in errors)


def test_rejects_web_dev_command() -> None:
    config = _valid_config()
    config["services"]["web"]["command"] = ["pnpm", "run", "dev"]

    errors = _errors(config)

    assert any("web" in error for error in errors)


def test_rejects_web_command_as_string_without_build() -> None:
    config = _valid_config()
    config["services"]["web"]["command"] = "pnpm run dev"

    errors = _errors(config)

    assert any("web" in error for error in errors)


def test_accepts_shell_string_production_commands() -> None:
    config = _valid_config()
    config["services"]["api"]["command"] = (
        "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"
    )
    config["services"]["web"]["command"] = "node .output/server/index.mjs"

    assert _errors(config) == []


# ---------------------------------------------------------------------------
# Volúmenes de datos
# ---------------------------------------------------------------------------


def test_requires_data_volumes_declared() -> None:
    config = _valid_config()
    del config["volumes"]["postgres_data"]

    errors = _errors(config)

    assert any("postgres_data" in error for error in errors)


def test_requires_postgres_data_mounted_in_db() -> None:
    config = _valid_config()
    config["services"]["db"]["volumes"] = [
        volume
        for volume in config["services"]["db"]["volumes"]
        if volume.get("source") != "postgres_data"
    ]

    errors = _errors(config)

    assert any("db" in error and "postgres_data" in error for error in errors)


# ---------------------------------------------------------------------------
# Verificaciones de salud y orden de arranque
# ---------------------------------------------------------------------------


def test_production_requires_healthchecks() -> None:
    for name in ("api", "worker", "web"):
        config = _valid_config()
        del config["services"][name]["healthcheck"]

        errors = _errors(config)

        assert any(name in error and "healthcheck" in error for error in errors), name


def test_production_rejects_healthcheck_without_test() -> None:
    config = _valid_config()
    config["services"]["worker"]["healthcheck"] = {"test": []}

    errors = _errors(config)

    assert any("worker" in error and "healthcheck" in error for error in errors)


def test_production_requires_web_to_wait_for_healthy_api() -> None:
    config = _valid_config()
    config["services"]["web"]["depends_on"] = {
        "api": {"condition": "service_started", "required": True}
    }

    errors = _errors(config)

    assert any("web" in error and "API" in error for error in errors)


# ---------------------------------------------------------------------------
# Usuario del servicio web en producción
# ---------------------------------------------------------------------------


def test_production_rejects_web_running_as_root() -> None:
    for user in ("0", "0:0", "root", "root:root"):
        config = _valid_config()
        config["services"]["web"]["user"] = user

        errors = _errors(config)

        assert any("web" in error and "raíz" in error for error in errors), user


def test_production_requires_web_user_declared() -> None:
    config = _valid_config()
    del config["services"]["web"]["user"]

    errors = _errors(config)

    assert any("web" in error and "usuario" in error for error in errors)


def test_production_accepts_non_root_web_users() -> None:
    for user in ("node", "1000", "1000:1000"):
        config = _valid_config()
        config["services"]["web"]["user"] = user

        assert _errors(config) == [], user


# ---------------------------------------------------------------------------
# Perfil de desarrollo (RF-013)
# ---------------------------------------------------------------------------


def test_valid_development_config_has_no_errors() -> None:
    assert _dev_errors(_valid_development_config()) == []


def test_development_requires_api_on_loopback() -> None:
    config = _valid_development_config()
    config["services"]["api"]["ports"] = [_published(None, "8000", 8000)]

    errors = _dev_errors(config)

    assert any("api" in error and "interfaz local" in error for error in errors)
    assert any("api" in error and "todas las interfaces" in error for error in errors)


def test_development_rejects_api_on_all_interfaces() -> None:
    config = _valid_development_config()
    config["services"]["api"]["ports"] = [_published("0.0.0.0", "8000", 8000)]

    errors = _dev_errors(config)

    assert any("api" in error and "interfaz local" in error for error in errors)


def test_development_requires_api_port_published() -> None:
    config = _valid_development_config()
    config["services"]["api"].pop("ports")

    errors = _dev_errors(config)

    assert any("api" in error and "8000" in error for error in errors)


def test_development_keeps_web_publication() -> None:
    config = _valid_development_config()
    config["services"]["web"].pop("ports")

    errors = _dev_errors(config)

    assert any("web" in error and "3000" in error for error in errors)


def test_development_rejects_web_published_only_on_loopback() -> None:
    config = _valid_development_config()
    config["services"]["web"]["ports"] = [_published("127.0.0.1", "3000", 3000)]

    errors = _dev_errors(config)

    assert any("web" in error and "3000" in error for error in errors)


def test_development_keeps_data_services_on_loopback() -> None:
    for name in ("db", "redis", "storage"):
        config = _valid_development_config()
        first = config["services"][name]["ports"][0]
        first["host_ip"] = "0.0.0.0"

        errors = _dev_errors(config)

        assert any(name in error and "interfaz local" in error for error in errors), name


def test_development_requires_healthchecks() -> None:
    for name in ("api", "worker", "web"):
        config = _valid_development_config()
        del config["services"][name]["healthcheck"]

        errors = _dev_errors(config)

        assert any(name in error and "healthcheck" in error for error in errors), name


def test_development_requires_web_to_wait_for_healthy_api() -> None:
    config = _valid_development_config()
    config["services"]["web"]["depends_on"] = {}

    errors = _dev_errors(config)

    assert any("web" in error and "API" in error for error in errors)


def test_production_rejects_development_config() -> None:
    """Sin ``--profile development`` el perfil por defecto sigue siendo producción."""

    errors = _errors(_valid_development_config())

    assert any("api" in error and "puerto" in error.lower() for error in errors)


# ---------------------------------------------------------------------------
# Versión de Compose
# ---------------------------------------------------------------------------


def test_parse_semver() -> None:
    assert assertions.parse_semver("2.24.4") == (2, 24, 4)
    assert assertions.parse_semver("v5.5.1") == (5, 5, 1)
    assert assertions.parse_semver("2.24") == (2, 24, 0)
    assert assertions.parse_semver("2.24.4-desktop.1") == (2, 24, 4)


def test_version_at_least_compares_patch() -> None:
    assert assertions.version_at_least("2.24.3", "2.24.4") is False
    assert assertions.version_at_least("2.24.4", "2.24.4") is True
    assert assertions.version_at_least("2.24.10", "2.24.4") is True
    assert assertions.version_at_least("2.24", "2.24.4") is False
    assert assertions.version_at_least("2.23.99", "2.24.4") is False
    assert assertions.version_at_least("v5.5.1", "2.24.4") is True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> int:
    return assertions.main(argv)


def test_cli_accepts_valid_config_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_valid_config()), encoding="utf-8")

    assert _run_cli([str(path)]) == 0


def test_cli_fails_on_invalid_config_file(tmp_path: Path) -> None:
    config = _valid_config()
    config["services"]["api"]["ports"] = [
        {"mode": "ingress", "published": "8000", "target": 8000}
    ]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    assert _run_cli([str(path)]) == 1


def test_cli_fails_when_compose_is_too_old(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_valid_config()), encoding="utf-8")

    assert _run_cli([str(path), "--compose-version", "2.24.3"]) == 1
    assert _run_cli([str(path), "--compose-version", "2.24.4"]) == 0
    assert _run_cli([str(path), "--compose-version", "v5.5.1"]) == 0


def test_cli_validates_development_profile(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_valid_development_config()), encoding="utf-8")

    assert _run_cli([str(path), "--profile", "development"]) == 0


def test_cli_development_profile_fails_on_api_on_all_interfaces(
    tmp_path: Path,
) -> None:
    config = _valid_development_config()
    config["services"]["api"]["ports"] = [_published("0.0.0.0", "8000", 8000)]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    assert _run_cli([str(path), "--profile", "development"]) == 1


def test_cli_development_profile_fails_on_missing_healthcheck(
    tmp_path: Path,
) -> None:
    config = _valid_development_config()
    del config["services"]["worker"]["healthcheck"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    assert _run_cli([str(path), "--profile", "development"]) == 1


def test_cli_production_profile_fails_on_root_web(tmp_path: Path) -> None:
    config = _valid_config()
    config["services"]["web"]["user"] = "0:0"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    assert _run_cli([str(path), "--profile", "production"]) == 1


def test_cli_default_profile_is_production(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_valid_development_config()), encoding="utf-8")

    # La invocación existente (sin perfil) sigue validando producción.
    assert _run_cli([str(path)]) == 1
