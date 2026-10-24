"""Pruebas del contrato de configuración variable→servicio (spec 008, RF-003).

Carga ``infra/scripts/check_env_contract.py`` con ``importlib`` como las
pruebas de los otros scripts de infraestructura. Todas las entradas son
sintéticas o temporales: no se ejecuta Docker ni se usa red.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra" / "scripts" / "check_env_contract.py"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

#: Variables que R20 recuperó para la API (documentadas antes sin efecto).
RECOVERED_API_VARIABLES = (
    "JWT_ALGORITHM",
    "GOOGLE_AUDIENCE",
    "CSRF_COOKIE_NAME",
    "CSRF_TOKEN_TTL_SECONDS",
    "MAX_REQUEST_BODY_BYTES",
    "STORAGE_SIGNING_ENDPOINT_URL",
    "STORAGE_PRESIGN_SECONDS",
)

#: Variables que solo existían en la composición y ahora están documentadas.
DOCUMENTED_RATE_LIMITS = ("AUTH_LOGIN_RATE_LIMIT", "AUTH_REGISTER_RATE_LIMIT")

#: Variables del flujo de Google que deben llegar solo a la API y estar
#: documentadas en ``.env.example`` (spec 013, T6).
GOOGLE_API_VARIABLES = ("GOOGLE_REDIRECT_URI",)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("check_env_contract", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_env_contract", module)
    spec.loader.exec_module(module)
    return module


contract_module = _load_module()
CONTRACT = contract_module.DEFAULT_CONTRACT


def _documented() -> dict[str, str]:
    return contract_module.parse_env_example(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"))


def _config(contract: Any = None, *, production: bool = False) -> dict[str, Any]:
    """JSON mínimo con la forma de ``docker compose config --format json``."""

    contract = contract or CONTRACT
    services: dict[str, Any] = {}
    for name in contract.service_env:
        required = contract.required(name, production)
        environment = {variable: "valor" for variable in sorted(required)}
        if "APP_ENV" in environment:
            environment["APP_ENV"] = "production" if production else "development"
        services[name] = {"environment": environment}
    return {"services": services}


def _errors(config: dict[str, Any], documented: Any = None, profile: str = "auto") -> list[str]:
    return contract_module.validate(
        config,
        set(documented if documented is not None else _documented()),
        CONTRACT,
        profile,
    )


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_self_test_detects_every_divergence() -> None:
    assert contract_module.main(["--self-test"]) == 0


def test_environment_contract_passes_for_development_and_production() -> None:
    assert _errors(_config(production=False), profile="development") == []
    assert _errors(_config(production=True), profile="production") == []


def test_detects_production_profile_from_app_env() -> None:
    assert contract_module.detect_profile(_config(production=True)) == "production"
    assert contract_module.detect_profile(_config(production=False)) == "development"
    assert contract_module.resolve_profile({"services": {}}, "development") == "development"


def test_documented_variable_without_effect_names_variable_and_service() -> None:
    config = _config()
    for variable in RECOVERED_API_VARIABLES:
        del config["services"]["api"]["environment"][variable]

    errors = _errors(config, profile="development")

    assert errors
    for variable in RECOVERED_API_VARIABLES:
        assert any(variable in error and "api" in error for error in errors)


def test_declared_variable_without_documentation_names_variable_and_service() -> None:
    config = _config()
    config["services"]["api"]["environment"]["UNDOCUMENTED_TOKEN"] = "x"

    errors = _errors(config, profile="development")

    assert len(errors) == 1
    assert "api" in errors[0]
    assert "UNDOCUMENTED_TOKEN" in errors[0]
    assert "no documentada" in errors[0]


def test_variable_attributed_to_another_service_is_rejected() -> None:
    config = _config()
    config["services"]["web"]["environment"]["STORAGE_BUCKET"] = "bucket"

    errors = _errors(config, profile="development")

    assert len(errors) == 1
    assert "web" in errors[0]
    assert "STORAGE_BUCKET" in errors[0]
    assert "api" in errors[0]


def test_documented_variable_without_consumer_is_rejected() -> None:
    documented = set(_documented()) | {"ORPHAN_SETTING"}

    errors = _errors(_config(), documented, profile="development")

    assert any("ORPHAN_SETTING" in error and "no tiene consumidor" in error for error in errors)


def test_unknown_service_must_be_added_to_the_map() -> None:
    config = _config()
    config["services"]["proxy"] = {"environment": {}}

    errors = _errors(config, profile="development")

    assert any("proxy" in error and "sin mapa" in error for error in errors)


def test_exceptions_are_tolerated_and_production_extras_are_required() -> None:
    config = _config(production=True)
    config["services"]["db-migrate"]["environment"]["PGPASSWORD"] = "pw"
    assert _errors(config, profile="production") == []

    del config["services"]["worker"]["environment"]["JWT_SECRET"]
    errors = _errors(config, profile="production")
    assert any("worker" in error and "JWT_SECRET" in error for error in errors)


def test_documented_rate_limits_and_recovered_variables_are_in_the_map() -> None:
    for variable in RECOVERED_API_VARIABLES + DOCUMENTED_RATE_LIMITS + GOOGLE_API_VARIABLES:
        assert variable in CONTRACT.service_env["api"]
        assert variable in _documented()


def test_google_redirect_uri_is_only_consumed_by_the_api() -> None:
    config = _config()
    assert "GOOGLE_REDIRECT_URI" in config["services"]["api"]["environment"]
    for service in ("worker", "web", "db", "db-migrate"):
        assert "GOOGLE_REDIRECT_URI" not in config["services"][service]["environment"]

    del config["services"]["api"]["environment"]["GOOGLE_REDIRECT_URI"]
    errors = _errors(config, profile="development")

    assert any(
        "api" in error and "GOOGLE_REDIRECT_URI" in error and "sin efecto" in error
        for error in errors
    )


def test_non_service_consumers_are_declared_separately_from_compose_services() -> None:
    # El one-off de cifrado y el navegador no son servicios de Compose, pero el
    # contrato los declara para atribuir sus variables.
    assert CONTRACT.non_service_consumers("DATABASE_ADMIN_URL") == (
        "encrypt-birth-dates",
    )
    assert CONTRACT.non_service_consumers("PLAYER_DATA_KEY") == (
        "encrypt-birth-dates",
    )
    assert CONTRACT.non_service_consumers("NUXT_PUBLIC_API_BASE") == ("browser",)
    assert CONTRACT.non_service_consumers("NUXT_PUBLIC_SOCKET_BASE") == ("browser",)
    assert "encrypt-birth-dates" in CONTRACT.consumers(
        "PLAYER_DATA_KEY", production=True
    )
    assert "browser" in CONTRACT.consumers("NUXT_PUBLIC_API_BASE", production=False)
    assert "DATABASE_ADMIN_URL" in CONTRACT.exceptions


def test_env_example_covers_the_contract() -> None:
    assert contract_module.validate_documented(_documented(), CONTRACT) == []


def test_env_example_parser_ignores_comments_and_rejects_malformed_lines() -> None:
    parsed = contract_module.parse_env_example(
        "# comentario\n\nA=1\nB = dos \n# C=3\nD=\n"
    )

    assert parsed == {"A": "1", "B": "dos", "D": ""}
    with pytest.raises(ValueError):
        contract_module.parse_env_example("SIN_ASIGNACION\n")


def test_service_environment_accepts_mapping_list_and_nulls() -> None:
    assert contract_module.service_environment({}) == {}
    assert contract_module.service_environment({"environment": {"A": None, "B": 1}}) == {
        "A": "",
        "B": "1",
    }
    assert contract_module.service_environment({"environment": ["A=1", "B="]}) == {
        "A": "1",
        "B": "",
    }
    with pytest.raises(ValueError):
        contract_module.service_environment({"environment": ["A"]})


def test_main_reads_a_config_file_and_fails_on_a_mutated_copy(tmp_path: Path) -> None:
    documented = "\n".join(
        f"{variable}=valor"
        for variable in sorted(set(_documented()))
    )
    env_example = _write(tmp_path, ".env.example", documented + "\n")
    config = _config()
    config_path = _write(tmp_path, "config.json", json.dumps(config))

    assert (
        contract_module.main(
            [str(config_path), "--env-example", str(env_example), "--profile", "development"]
        )
        == 0
    )

    mutated = deepcopy(config)
    del mutated["services"]["api"]["environment"]["JWT_ALGORITHM"]
    mutated_path = _write(tmp_path, "mutated.json", json.dumps(mutated))

    assert (
        contract_module.main(
            [str(mutated_path), "--env-example", str(env_example), "--profile", "development"]
        )
        == 1
    )
