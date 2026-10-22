"""Pruebas de la utilidad de la sonda de outbox (spec 011, RF-003, parte pura).

Siempre activas y sin base de datos: cubren las funciones puras del guard de
entorno, del marcador, de la clasificación y del presupuesto, más las
propiedades del fuente que mantienen la utilidad dentro del rol de aplicación
(sin ``DATABASE_ADMIN_URL``) y con contexto RLS explícito.

Las funciones de lógica temporal reciben el instante por parámetro: aquí se
comprueba tanto su resultado como que no leen el reloj.
"""

import ast
import inspect
from pathlib import Path

import pytest

from scripts import outbox_probe
from scripts.outbox_probe import (
    PROBE_EVENT_TYPE,
    PROBE_VERIFICATION,
    ProbeNotExecutableError,
    classify_probe,
    current_probe_marker,
    environment_allows_probe,
    main,
    probe_deadline,
    probe_exhausted,
    probe_marker,
    run_guard,
)

# ``fail_outbox_event`` devuelve el evento a ``pending`` con 5 s de espera hasta
# que ``attempts >= 5``; el presupuesto de la sonda (WORKER_PROBE_TIMEOUT, 120 s
# en el script de verificación) tiene que cubrir esos cinco intentos.
MAX_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 5
PROBE_TIMEOUT_SECONDS = 120

SOURCE = Path(inspect.getfile(outbox_probe)).read_text(encoding="utf-8")


def _code_only(source: str) -> str:
    """Return the executable code: docstrings and comments are not behaviour."""

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


class _SessionFactorySentinel:
    """Sustituto de ``SessionFactory`` que falla si el guard dejó llegar la escritura."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("la sonda no debe abrir una sesión fuera de desarrollo/local")


@pytest.mark.parametrize("app_env", ["development", "dev", "local", "  DEV  ", "Local"])
def test_environment_allows_probe_accepts_development_environments(app_env: str) -> None:
    assert environment_allows_probe(app_env) is True


@pytest.mark.parametrize(
    "app_env",
    ["production", "prod", "staging", "testing", "", "   ", None, "developmentish"],
)
def test_environment_allows_probe_rejects_anything_else(app_env) -> None:
    assert environment_allows_probe(app_env) is False


def test_guard_returns_the_effective_environment_in_development() -> None:
    assert run_guard("  Development ") == "APP_ENV=development"


@pytest.mark.parametrize("app_env", ["production", None, ""])
def test_guard_rejects_with_a_typed_error(app_env) -> None:
    with pytest.raises(ProbeNotExecutableError) as raised:
        run_guard(app_env)

    message = str(raised.value)
    assert "no ejecutable" in message.lower()
    assert "<vacío>" in message or "production" in message


def test_guard_command_exits_two_without_writing(monkeypatch, capsys) -> None:
    sentinel = _SessionFactorySentinel()
    monkeypatch.setattr(outbox_probe, "current_app_env", lambda: "production")
    monkeypatch.setattr(outbox_probe, "SessionFactory", sentinel)

    assert main(["guard"]) == 2
    assert sentinel.calls == 0
    assert "no ejecutable" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["insert", "--marker", "worker-probe-1-2-deadbeef"],
        ["status", "--id", "0d0f4d1c-1111-4222-8333-444455556666", "--marker", "m"],
        ["delete", "--id", "0d0f4d1c-1111-4222-8333-444455556666", "--marker", "m"],
    ],
)
def test_every_write_command_repeats_the_guard_without_a_session(
    argv, monkeypatch, capsys
) -> None:
    sentinel = _SessionFactorySentinel()
    monkeypatch.setattr(outbox_probe, "current_app_env", lambda: "staging")
    monkeypatch.setattr(outbox_probe, "SessionFactory", sentinel)

    assert main(argv) == 2
    assert sentinel.calls == 0
    assert "no ejecutable" in capsys.readouterr().err.lower()


def test_probe_marker_is_built_from_its_arguments() -> None:
    assert (
        probe_marker(1700000000, 4242, "0a1b2c3d")
        == "worker-probe-1700000000-4242-0a1b2c3d"
    )


def test_probe_marker_differs_between_consecutive_runs() -> None:
    first = current_probe_marker()
    second = current_probe_marker()

    assert first != second
    assert first.startswith("worker-probe-")
    assert second.startswith("worker-probe-")


def test_probe_marker_requires_all_three_inputs() -> None:
    parameters = list(inspect.signature(probe_marker).parameters.values())

    assert len(parameters) == 3
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("pending", "retrying"),
        ("processing", "retrying"),
        ("processed", "processed"),
        ("failed", "failed"),
    ],
)
def test_classify_probe_maps_the_persisted_state(status: str, expected: str) -> None:
    assert classify_probe({"status": status}) == expected


def test_classify_probe_reports_a_missing_row() -> None:
    assert classify_probe(None) == "missing"


def test_classify_probe_keeps_waiting_on_an_unknown_state() -> None:
    # Sin evidencia de éxito ni de fallo se sigue esperando; el presupuesto acota.
    assert classify_probe({"status": "unexpected"}) == "retrying"


def test_classify_probe_treats_a_row_without_state_as_unresolved() -> None:
    assert classify_probe({}) == "retrying"


def test_probe_deadline_adds_the_timeout_to_the_inserted_instant() -> None:
    assert probe_deadline(1000.0, PROBE_TIMEOUT_SECONDS) == 1120.0


def test_probe_exhausted_compares_the_injected_instants() -> None:
    deadline = probe_deadline(1000.0, PROBE_TIMEOUT_SECONDS)

    assert probe_exhausted(1119.999, deadline) is False
    assert probe_exhausted(1120.0, deadline) is True
    assert probe_exhausted(1200.0, deadline) is True


def test_the_probe_budget_covers_every_outbox_retry() -> None:
    deadline = probe_deadline(1000.0, PROBE_TIMEOUT_SECONDS)

    # Cuatro reintentos de 5 s más el intento que agota los cinco: 25 s.
    assert probe_exhausted(1000.0 + MAX_ATTEMPTS * RETRY_DELAY_SECONDS, deadline) is False
    assert MAX_ATTEMPTS * RETRY_DELAY_SECONDS < PROBE_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "function",
    [probe_deadline, probe_exhausted, environment_allows_probe, classify_probe],
)
def test_the_temporal_functions_never_read_the_clock(function) -> None:
    source = inspect.getsource(function)

    for forbidden in ("time.time", "time.monotonic", "datetime.now", "utcnow", "date.today"):
        assert forbidden not in source


def test_the_probe_values_are_the_declared_ones() -> None:
    assert PROBE_EVENT_TYPE == "VERIFICATION_OUTBOX_PROBE"
    assert PROBE_VERIFICATION == "spec-011"


def test_the_demo_identity_mirrors_the_seed() -> None:
    from scripts.seed_demo import DEMO_ORGANIZATION_SLUG, DEMO_USER_EMAIL

    assert outbox_probe.DEMO_USER_EMAIL == DEMO_USER_EMAIL
    assert outbox_probe.DEMO_ORGANIZATION_SLUG == DEMO_ORGANIZATION_SLUG


def test_the_utility_resolves_the_demo_tenant_with_the_application_role() -> None:
    assert "list_user_organizations()" in SOURCE
    assert "set_rls_context(" in SOURCE
    assert "LOWER(email) = :email" in SOURCE


def test_the_utility_never_uses_the_administrator_role() -> None:
    code = _code_only(SOURCE)

    assert "DATABASE_ADMIN_URL" not in code
    assert "create_async_engine" not in code
    assert "postgresql+asyncpg://postgres" not in code


def test_the_utility_does_not_swallow_unexpected_errors() -> None:
    code = _code_only(SOURCE)

    assert "except Exception" not in code
    assert "except BaseException" not in code
