#!/usr/bin/env python3
"""Contrato de configuración variable→servicio de Bracket Craft (spec 008, RF-003).

Lee por entrada estándar el JSON de ``docker compose config --format json``
(el de desarrollo o el del merge ``-f docker-compose.yml -f
docker-compose.production.yml``) y comprueba tres cosas:

1. **Variable documentada sin efecto.** Toda variable del mapa
   servicio→variables (con sus extras de producción) debe llegar al contenedor
   que la consume en el perfil correspondiente.
2. **Variable declarada sin documentar.** Todo lo que un servicio de la
   composición declara debe estar documentado en ``.env.example`` (o ser una
   excepción legítima).
3. **Variable atribuida a otro servicio.** Una variable documentada para un
   servicio no puede aparecer en el entorno de otro que no la consume; y toda
   variable documentada en ``.env.example`` debe nombrar al menos un consumidor
   (contenedor, trabajo puntual o navegador) o ser una excepción.

Sin Docker, sin PyYAML y sin red: solo biblioteca estándar (``json``, ``sys``,
``re``, ``pathlib``, ``argparse``).

Uso::

    docker compose config --format json | python3 infra/scripts/check_env_contract.py -

    docker compose -f docker-compose.yml -f docker-compose.production.yml \\
        config --format json | python3 infra/scripts/check_env_contract.py --profile production -

    python3 infra/scripts/check_env_contract.py --self-test

El perfil (``development``/``production``) se detecta por ``APP_ENV=production``
en el JSON; ``--profile`` lo fuerza. El modo ``--self-test`` construye casos
sintéticos y no lee Docker ni el repositorio: devuelve 1 si el contrato no
detecta lo que debe detectar.

El script falla (código 1) con el nombre de la variable y del servicio.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_EXAMPLE = REPO_ROOT / ".env.example"

PROFILE_AUTO = "auto"
PROFILE_DEVELOPMENT = "development"
PROFILE_PRODUCTION = "production"
PROFILES = (PROFILE_AUTO, PROFILE_DEVELOPMENT, PROFILE_PRODUCTION)

_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Variables que recibe el servicio de API (``docker-compose.yml``, servicio
#: ``api``). Es el consumidor principal de la configuración: toda variable
#: documentada que afecte al comportamiento de la aplicación debe estar aquí.
API_ENV = frozenset(
    {
        "APP_ENV",
        "AUTH_COOKIE_SAMESITE",
        "AUTH_COOKIE_SECURE",
        "AUTH_LOGIN_RATE_LIMIT",
        "AUTH_REGISTER_RATE_LIMIT",
        "CORS_ALLOWED_ORIGINS",
        "CSRF_COOKIE_NAME",
        "CSRF_TOKEN_TTL_SECONDS",
        "DATABASE_URL",
        "FRONTEND_BASE_URL",
        "GOOGLE_AUDIENCE",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "INVITATION_EXPIRE_HOURS",
        "INVITATION_TOKEN_KEY",
        "JWT_ALGORITHM",
        "JWT_AUDIENCE",
        "JWT_EXPIRE_MINUTES",
        "JWT_ISSUER",
        "JWT_SECRET",
        "MAX_REQUEST_BODY_BYTES",
        "PLAYER_DATA_KEY",
        "REDIS_URL",
        "SMTP_FROM",
        "SMTP_HOST",
        "SMTP_PASSWORD",
        "SMTP_PORT",
        "SMTP_TIMEOUT_SECONDS",
        "SMTP_USERNAME",
        "SMTP_USE_TLS",
        "STORAGE_ACCESS_KEY",
        "STORAGE_BUCKET",
        "STORAGE_ENDPOINT_URL",
        "STORAGE_MAX_ARCHIVE_BYTES",
        "STORAGE_MAX_ARCHIVE_FILES",
        "STORAGE_MAX_IMAGE_BYTES",
        "STORAGE_PRESIGN_SECONDS",
        "STORAGE_PROVIDER",
        "STORAGE_PUBLIC_BASE_URL",
        "STORAGE_REGION",
        "STORAGE_SECRET_KEY",
        "STORAGE_SIGNING_ENDPOINT_URL",
    }
)

#: Variables del worker del outbox. Solo necesita la conexión de datos y Redis
#: en desarrollo; fuera de desarrollo también instancia ``Settings``, de ahí las
#: dos claves de producción de ``PRODUCTION_ONLY_ENV``.
WORKER_ENV = frozenset({"APP_ENV", "DATABASE_URL", "REDIS_URL"})

#: Variables del servidor Nuxt. ``CI`` la fija el compose de desarrollo.
WEB_ENV = frozenset(
    {"CI", "NUXT_API_INTERNAL_BASE", "NUXT_PUBLIC_API_BASE", "NUXT_PUBLIC_SOCKET_BASE"}
)

#: Credenciales y parámetros que consume el servicio de base de datos.
DB_ENV = frozenset(
    {"APP_ENV", "BRACKET_DB_PASSWORD", "POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_USER"}
)

#: Trabajo de migraciones (``db-migrate``).
DB_MIGRATE_ENV = frozenset(
    {"MIGRATION_TARGET", "PLATFORM_ADMIN_EMAIL", "POSTGRES_DB", "POSTGRES_USER"}
)

#: Consumidores que no son servicios de Compose. No tienen ``environment`` en el
#: JSON renderizado, así que no se validan contra él; el mapa los declara para
#: atribuir sus variables y distinguirlas de una variable sin consumidor.
NON_SERVICE_CONSUMERS: Mapping[str, frozenset[str]] = {
    # Trabajo puntual de cifrado de fechas de nacimiento: recibe
    # ``DATABASE_ADMIN_URL`` y ``PLAYER_DATA_KEY`` con ``docker compose run
    # --no-deps -e ...`` y nunca se inyectan a la API.
    "encrypt-birth-dates": frozenset({"DATABASE_ADMIN_URL", "PLAYER_DATA_KEY"}),
    # Navegador: consume las variables públicas que el servidor Nuxt expone en
    # el HTML; no viajan en el entorno de ningún contenedor.
    "browser": frozenset({"NUXT_PUBLIC_API_BASE", "NUXT_PUBLIC_SOCKET_BASE"}),
}


@dataclass(frozen=True)
class Contract:
    """Mapa servicio→variables y lista cerrada de excepciones legítimas."""

    service_env: Mapping[str, frozenset[str]]
    production_only: Mapping[str, frozenset[str]]
    exceptions: Mapping[str, str]
    non_service: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def allowed(self, service: str) -> frozenset[str]:
        """Variables que el servicio puede declarar en cualquier perfil."""

        return self.service_env.get(service, frozenset()) | self.production_only.get(
            service, frozenset()
        )

    def required(self, service: str, production: bool) -> frozenset[str]:
        """Variables que el servicio debe declarar en el perfil indicado."""

        required = self.service_env.get(service, frozenset())
        if production:
            required |= self.production_only.get(service, frozenset())
        return required

    def non_service_consumers(self, variable: str) -> tuple[str, ...]:
        """Consumidores no-servicio (one-off o navegador) de ``variable``."""

        return tuple(
            sorted(
                consumer
                for consumer, variables in self.non_service.items()
                if variable in variables
            )
        )

    def consumers(self, variable: str, production: bool) -> tuple[str, ...]:
        """Servicios y consumidores no-servicio que reciben ``variable``."""

        services = (
            service
            for service in self.service_env
            if variable in self.required(service, production)
        )
        return tuple(sorted(set(services) | set(self.non_service_consumers(variable))))

    def mapped(self) -> frozenset[str]:
        """Todas las variables que el mapa asocia a un consumidor conocido."""

        variables: set[str] = set()
        for service in self.service_env:
            variables |= self.allowed(service)
        for consumer_variables in self.non_service.values():
            variables |= consumer_variables
        return frozenset(variables)


DEFAULT_CONTRACT = Contract(
    service_env={
        "api": API_ENV,
        "worker": WORKER_ENV,
        "web": WEB_ENV,
        "db": DB_ENV,
        "db-migrate": DB_MIGRATE_ENV,
        # Redis y el almacenamiento S3 no reciben configuración: su topología
        # sale de la línea de comandos del propio servicio.
        "redis": frozenset(),
        "storage": frozenset(),
    },
    production_only={
        # Fuera de desarrollo el worker instancia ``Settings``, que exige las
        # claves de firma (ver ``backend/app/core/config.py``).
        "worker": frozenset({"JWT_SECRET", "PLAYER_DATA_KEY"}),
        # Marca de ejecución de Node que fija el overlay de producción.
        "web": frozenset({"NODE_ENV"}),
        # El trabajo de migraciones no declara APP_ENV en desarrollo; el overlay
        # de producción lo fija para que ``migrate.sh`` lo propague.
        "db-migrate": frozenset({"APP_ENV"}),
    },
    exceptions={
        # --- Credenciales y parámetros de PostgreSQL ---
        # psql del trabajo de migraciones lee PGPASSWORD; se deriva de
        # POSTGRES_PASSWORD en docker-compose.yml y no se documenta aparte.
        "PGPASSWORD": "contraseña de psql en el trabajo de migraciones (alias de POSTGRES_PASSWORD)",
        # Cadena de conexión del rol de aplicación: Compose la deriva de
        # POSTGRES_DB/BRACKET_DB_PASSWORD en desarrollo y el overlay de producción
        # la exige con `:?`. No se documenta como valor para no fijar credenciales.
        "DATABASE_URL": "conexión a PostgreSQL derivada por Compose; obligatoria en producción (`:?`)",
        # --- Trabajo puntual de cifrado ---
        # Solo llega por `-e DATABASE_ADMIN_URL` al contenedor one-off
        # `python -m scripts.encrypt_birth_dates` (declarado en
        # NON_SERVICE_CONSUMERS); nunca se inyecta a la API. Se mantiene fuera de
        # la paridad con `.env.example` porque es un valor operativo, no un
        # default documentado.
        "DATABASE_ADMIN_URL": "conexión administrativa del one-off de cifrado (nunca inyectada a la API)",
        # --- Variables del servicio web ---
        # Marca de integración continua del servidor Nuxt (valor fijo del compose
        # de desarrollo, no configurable por el operador).
        "CI": "marca de integración continua del servidor Nuxt (fija en el compose de desarrollo)",
        # Marca de ejecución de Node/Nuxt fijada por el overlay de producción.
        "NODE_ENV": "marca de ejecución de Node/Nuxt fijada por el overlay de producción",
        # --- Valores de pruebas o entornos locales ---
        # El contrato compara nombres, no valores: las variables dummy del merge
        # de CI y los defaults de desarrollo viven en el entorno del operador y
        # no se declaran aquí. Si una prueba futura inyecta una variable propia,
        # añádela a esta lista con su motivo.
    },
    non_service=NON_SERVICE_CONSUMERS,
)


def parse_env_example(text: str) -> dict[str, str]:
    """Devuelve las asignaciones ``CLAVE=valor`` no comentadas de ``.env.example``.

    Las líneas comentadas (como ``# DATABASE_ADMIN_URL=...``) no documentan un
    default: se ignoran, igual que en un archivo ``.env`` real.
    """

    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, value = stripped.partition("=")
        name = name.strip()
        if not separator or not _VARIABLE_PATTERN.match(name):
            raise ValueError(
                f"línea {line_number} de .env.example no es una asignación CLAVE=valor: {line!r}"
            )
        values[name] = value.strip()
    return values


def service_environment(service: Mapping[str, Any]) -> dict[str, str]:
    """Normaliza el ``environment`` de un servicio renderizado por Compose.

    Acepta el mapa que produce ``config --format json`` y, por si cambia el
    formato, la lista ``CLAVE=valor``. Los valores ``null`` se tratan como
    cadena vacía.
    """

    environment = service.get("environment")
    if environment is None:
        return {}
    if isinstance(environment, Mapping):
        return {
            str(name): "" if value is None else str(value)
            for name, value in environment.items()
        }
    if isinstance(environment, Sequence) and not isinstance(environment, (str, bytes)):
        parsed: dict[str, str] = {}
        for entry in environment:
            name, separator, value = str(entry).partition("=")
            if not separator:
                raise ValueError(f"entrada de entorno sin valor: {entry!r}")
            parsed[name] = value
        return parsed
    raise ValueError(f"environment con formato no reconocido: {environment!r}")


def detect_profile(config: Mapping[str, Any]) -> str:
    """``production`` si algún servicio declara ``APP_ENV=production``."""

    services = config.get("services")
    if not isinstance(services, Mapping):
        return PROFILE_DEVELOPMENT
    for service in services.values():
        if not isinstance(service, Mapping):
            continue
        try:
            environment = service_environment(service)
        except ValueError:
            continue
        if environment.get("APP_ENV", "").strip().lower() == PROFILE_PRODUCTION:
            return PROFILE_PRODUCTION
    return PROFILE_DEVELOPMENT


def resolve_profile(config: Mapping[str, Any], profile: str) -> str:
    """Aplica ``--profile`` o detecta el perfil a partir del JSON."""

    if profile in (None, PROFILE_AUTO):
        return detect_profile(config)
    return profile


def _describe_extra(
    variable: str,
    service: str,
    contract: Contract,
    production: bool,
) -> str:
    consumers = contract.consumers(variable, production)
    if consumers:
        return (
            f"{service}: {variable} no está documentada para este servicio "
            f"(la consumen: {', '.join(consumers)})"
        )
    return f"{service}: {variable} está declarada y no documentada en .env.example"


def validate_service_declarations(
    config: Mapping[str, Any],
    contract: Contract = DEFAULT_CONTRACT,
    production: bool = False,
) -> list[str]:
    """Comprueba que cada servicio recibe exactamente su configuración documentada."""

    errors: list[str] = []
    services = config.get("services")
    if not isinstance(services, Mapping) or not services:
        return ["La configuración no declara servicios"]

    known = set(contract.service_env)
    for name in sorted(services):
        if name not in known:
            errors.append(
                f"{name}: servicio sin mapa de variables documentadas; "
                "añádelo a service_env en infra/scripts/check_env_contract.py"
            )

    for name in sorted(known):
        if name not in services:
            errors.append(
                f"{name}: el mapa de configuración declara un servicio ausente "
                "de la composición"
            )

    for name in sorted(known & set(services)):
        service = services[name]
        if not isinstance(service, Mapping):
            errors.append(f"{name}: la definición del servicio no es válida")
            continue
        try:
            declared = set(service_environment(service))
        except ValueError as error:
            errors.append(f"{name}: {error}")
            continue
        required = contract.required(name, production)
        allowed = contract.allowed(name)
        for variable in sorted(required - declared):
            errors.append(
                f"{name}: falta {variable}, documentada para este servicio y no "
                "inyectada (variable documentada sin efecto)"
            )
        for variable in sorted(declared - allowed):
            if variable in contract.exceptions:
                continue
            errors.append(_describe_extra(variable, name, contract, production))
    return errors


def validate_documented(
    documented: Iterable[str],
    contract: Contract = DEFAULT_CONTRACT,
) -> list[str]:
    """Comprueba la paridad entre ``.env.example`` y el mapa.

    Toda variable documentada debe nombrar un consumidor o ser una excepción, y
    toda variable del mapa debe estar documentada salvo que sea una excepción.
    """

    errors: list[str] = []
    documented_variables = set(documented)
    mapped = contract.mapped()

    for variable in sorted(documented_variables - mapped - set(contract.exceptions)):
        errors.append(
            f".env.example: {variable} está documentada y no tiene consumidor "
            "conocido (variable documentada sin efecto); añádela al mapa o a las "
            "excepciones de infra/scripts/check_env_contract.py"
        )
    for variable in sorted(mapped - documented_variables - set(contract.exceptions)):
        errors.append(
            f".env.example: falta {variable}, que un servicio declara "
            "(variable declarada sin documentar)"
        )
    return errors


def validate(
    config: Mapping[str, Any],
    documented: Iterable[str],
    contract: Contract = DEFAULT_CONTRACT,
    profile: str = PROFILE_AUTO,
) -> list[str]:
    """Errores del contrato para un JSON de Compose y un ``.env.example``."""

    resolved = resolve_profile(config, profile)
    return validate_service_declarations(
        config, contract, production=resolved == PROFILE_PRODUCTION
    ) + validate_documented(documented, contract)


def _load_config(path: str) -> Mapping[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# --- Self-test (sin Docker, sin .env.example, sin red) ------------------------

SELF_TEST_CONTRACT = Contract(
    service_env={
        "api": frozenset({"API_SECRET", "API_DEBUG", "APP_ENV"}),
        "worker": frozenset({"APP_ENV", "DATABASE_URL"}),
        "web": frozenset({"PUBLIC_URL"}),
        "db": frozenset({"POSTGRES_DB"}),
        "db-migrate": frozenset({"MIGRATION_TARGET"}),
    },
    production_only={"worker": frozenset({"WORKER_KEY"})},
    exceptions={
        "PGPASSWORD": "contraseña de psql del trabajo de migraciones",
        "ADMIN_DATABASE_URL": "conexión administrativa del one-off",
    },
    non_service={
        "encrypt-birth-dates": frozenset({"ADMIN_DATABASE_URL"}),
        "browser": frozenset({"BROWSER_FLAG"}),
    },
)

SELF_TEST_DOCUMENTED = frozenset(
    {
        "API_SECRET",
        "API_DEBUG",
        "APP_ENV",
        "BROWSER_FLAG",
        "DATABASE_URL",
        "PUBLIC_URL",
        "POSTGRES_DB",
        "MIGRATION_TARGET",
        "WORKER_KEY",
    }
)


def _self_test_config(*, production: bool = False) -> dict[str, Any]:
    services: dict[str, Any] = {
        "api": {
            "environment": {
                "API_SECRET": "secreto",
                "API_DEBUG": "0",
                "APP_ENV": "production" if production else "development",
            }
        },
        "worker": {
            "environment": {
                "APP_ENV": "production" if production else "development",
                "DATABASE_URL": "postgresql+asyncpg://app:pw@db:5432/app",
            }
        },
        "web": {"environment": {"PUBLIC_URL": "http://localhost:3000"}},
        "db": {"environment": {"POSTGRES_DB": "app"}},
        "db-migrate": {"environment": {"MIGRATION_TARGET": ""}},
    }
    if production:
        services["worker"]["environment"]["WORKER_KEY"] = "clave"
    return {"services": services}


def _self_test_cases() -> list[tuple[str, dict[str, Any], frozenset[str], str, bool, tuple[str, ...]]]:
    valid_development = _self_test_config()
    valid_production = _self_test_config(production=True)

    missing_effect = _self_test_config()
    del missing_effect["services"]["api"]["environment"]["API_DEBUG"]

    undocumented = _self_test_config()
    undocumented["services"]["api"]["environment"]["UNDOCUMENTED_TOKEN"] = "x"

    misattributed = _self_test_config()
    misattributed["services"]["web"]["environment"]["DATABASE_URL"] = "x"

    tolerated_exception = _self_test_config()
    tolerated_exception["services"]["db-migrate"]["environment"]["PGPASSWORD"] = "pw"

    missing_production_key = _self_test_config(production=True)
    del missing_production_key["services"]["worker"]["environment"]["WORKER_KEY"]

    return [
        (
            "configuración válida de desarrollo",
            valid_development,
            SELF_TEST_DOCUMENTED,
            PROFILE_DEVELOPMENT,
            True,
            (),
        ),
        (
            "configuración válida de producción",
            valid_production,
            SELF_TEST_DOCUMENTED,
            PROFILE_PRODUCTION,
            True,
            (),
        ),
        (
            "variable documentada sin efecto en el servicio",
            missing_effect,
            SELF_TEST_DOCUMENTED,
            PROFILE_DEVELOPMENT,
            False,
            ("api", "API_DEBUG", "sin efecto"),
        ),
        (
            "variable declarada sin documentar",
            undocumented,
            SELF_TEST_DOCUMENTED,
            PROFILE_DEVELOPMENT,
            False,
            ("api", "UNDOCUMENTED_TOKEN", "no documentada"),
        ),
        (
            "variable atribuida a otro servicio",
            misattributed,
            SELF_TEST_DOCUMENTED,
            PROFILE_DEVELOPMENT,
            False,
            ("web", "DATABASE_URL", "la consumen: worker"),
        ),
        (
            "variable documentada sin consumidor",
            valid_development,
            SELF_TEST_DOCUMENTED | {"ORPHAN_SETTING"},
            PROFILE_DEVELOPMENT,
            False,
            ("ORPHAN_SETTING", "no tiene consumidor"),
        ),
        (
            "excepción legítima tolerada",
            tolerated_exception,
            SELF_TEST_DOCUMENTED,
            PROFILE_DEVELOPMENT,
            True,
            (),
        ),
        (
            "variable de producción ausente",
            missing_production_key,
            SELF_TEST_DOCUMENTED,
            PROFILE_PRODUCTION,
            False,
            ("worker", "WORKER_KEY", "sin efecto"),
        ),
        (
            "variable documentada con consumidor no-servicio",
            valid_development,
            SELF_TEST_DOCUMENTED,
            PROFILE_DEVELOPMENT,
            True,
            (),
        ),
        (
            "perfil detectado desde APP_ENV",
            valid_production,
            SELF_TEST_DOCUMENTED,
            PROFILE_AUTO,
            True,
            (),
        ),
    ]


def run_self_test() -> int:
    """Comprueba que el contrato detecta cada divergencia y acepta lo válido."""

    failures = 0
    for label, config, documented, profile, should_pass, fragments in _self_test_cases():
        errors = validate(config, documented, SELF_TEST_CONTRACT, profile)
        passed = not errors
        ok = passed is should_pass
        if ok and not should_pass:
            missing = [
                fragment
                for fragment in fragments
                if not any(fragment in error for error in errors)
            ]
            if missing:
                ok = False
                print(
                    f"FALLO: {label}: los errores no nombran {missing}: {errors}",
                    file=sys.stderr,
                )
        if ok:
            print(f"OK: {label} ({'pasa' if should_pass else 'falla'})")
        else:
            failures += 1
            print(
                f"FALLO: {label}: se esperaba {'pasar' if should_pass else 'fallar'} "
                f"y se obtuvo {errors or 'sin errores'}",
                file=sys.stderr,
            )

    if failures:
        print(f"ERROR: self-test con {failures} caso(s) incorrecto(s)", file=sys.stderr)
        return 1
    print("OK: self-test del contrato de configuración")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Comprueba el contrato variable→servicio y la paridad con .env.example "
            "sobre el JSON de 'docker compose config --format json'."
        )
    )
    parser.add_argument(
        "config",
        nargs="?",
        default="-",
        help="JSON renderizado por Compose (por defecto, - para stdin)",
    )
    parser.add_argument(
        "--env-example",
        type=Path,
        default=DEFAULT_ENV_EXAMPLE,
        help="Archivo de entorno documentado (por defecto .env.example de la raíz)",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=PROFILE_AUTO,
        help="Perfil de la configuración; 'auto' lo detecta por APP_ENV",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Ejecuta casos sintéticos sin Docker ni .env.example",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    try:
        documented = parse_env_example(args.env_example.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"ERROR: no se pudo leer {args.env_example}: {error}", file=sys.stderr)
        return 1

    try:
        config = _load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: no se pudo leer la configuración: {error}", file=sys.stderr)
        return 1

    if not isinstance(config, Mapping):
        print("ERROR: la configuración JSON no es un objeto", file=sys.stderr)
        return 1

    profile = resolve_profile(config, args.profile)
    errors = validate(config, set(documented), DEFAULT_CONTRACT, profile)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(
            f"ERROR: el contrato de configuración tiene {len(errors)} "
            f"incumplimiento(s) (perfil: {profile})",
            file=sys.stderr,
        )
        return 1

    services = config.get("services") or {}
    print(
        "OK: contrato de configuración cumplido "
        f"({len(services)} servicios, {len(documented)} variables documentadas, "
        f"perfil: {profile})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
