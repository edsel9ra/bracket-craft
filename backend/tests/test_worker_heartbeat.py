"""Latido del worker del outbox (spec 008, RF-014).

El worker publica un fichero de latido para que su healthcheck mida que el
bucle avanza, no que haya trabajo. La frescura se calcula con un helper puro
que recibe el instante actual: nada dentro del helper lee el reloj.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.workers import heartbeat as heartbeat_module
from app.workers import outbox
from app.workers.heartbeat import (
    DEFAULT_HEARTBEAT_PATH,
    HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_MAX_AGE_SECONDS,
    heartbeat_is_due,
    heartbeat_is_fresh,
    heartbeat_is_fresh_at_path,
    publish_heartbeat,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VERIFY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "verify_worker_loop_health.sh"
BACKEND_APP = Path(__file__).resolve().parents[1] / "app"


class StopLoop(Exception):
    """Detiene el bucle del worker en las pruebas."""


class FakeSettings:
    """Ajustes mínimos que ``outbox.main`` consulta al arrancar."""

    app_env = "development"


class FakeClock:
    """Reloj inyectado: las pruebas no leen el reloj real."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


def worker_healthcheck_block() -> str:
    """Devuelve el bloque YAML del healthcheck del servicio ``worker``."""

    text = COMPOSE_PATH.read_text(encoding="utf-8")
    worker_start = text.index("\n  worker:")
    healthcheck_start = text.index("\n    healthcheck:", worker_start)
    remainder = text[healthcheck_start + 1 :]
    next_key = re.search(r"\n    [a-z][a-z0-9_]*:", remainder)
    return remainder if next_key is None else remainder[: next_key.start()]


def test_heartbeat_inside_max_age_is_fresh():
    assert heartbeat_is_fresh(1_000.0, 1_029.0, 30) is True


def test_heartbeat_beyond_max_age_is_stale():
    assert heartbeat_is_fresh(1_000.0, 1_030.1, 30) is False


def test_heartbeat_exact_boundary_is_fresh():
    # El límite es inclusivo: justo en max_age todavía se considera fresco.
    assert heartbeat_is_fresh(1_000.0, 1_030.0, 30) is True


def test_heartbeat_uses_the_injected_now():
    # Mismo mtime, distinto instante actual: el helper no lee el reloj.
    assert heartbeat_is_fresh(2_000.0, 2_010.0, 30) is True
    assert heartbeat_is_fresh(2_000.0, 2_100.0, 30) is False


def test_heartbeat_with_future_mtime_is_not_a_false_negative():
    # Un reloj ligeramente adelantado en el escritor no debe marcar insano.
    assert heartbeat_is_fresh(1_005.0, 1_000.0, 30) is True


def test_missing_heartbeat_file_is_not_fresh(tmp_path):
    # Bucle detenido antes de completar su primera vuelta: no hay latido que medir.
    assert heartbeat_is_fresh_at_path(tmp_path / "ausente", now_epoch=1_000.0) is False


def test_inaccessible_heartbeat_file_is_not_fresh(monkeypatch, tmp_path):
    def denied(_path):
        raise PermissionError("sin permiso")

    monkeypatch.setattr(heartbeat_module.os, "stat", denied)

    assert heartbeat_is_fresh_at_path(tmp_path / "latido", now_epoch=1_000.0) is False


def test_default_heartbeat_expires_after_ninety_seconds(tmp_path, monkeypatch):
    path = tmp_path / "latido"
    publish_heartbeat(path)
    now = os.stat(path).st_mtime

    assert HEARTBEAT_MAX_AGE_SECONDS == 90
    assert heartbeat_is_fresh_at_path(path, now_epoch=now + 30) is True
    assert heartbeat_is_fresh_at_path(path, now_epoch=now + 90) is True
    assert heartbeat_is_fresh_at_path(path, now_epoch=now + 91) is False


def test_default_max_age_boundary_is_inclusive_and_the_next_instant_is_stale():
    # Límite inclusivo con la constante efectiva: 90 s fresco, 90 s + épsilon no.
    assert (
        heartbeat_is_fresh(
            1_000.0,
            1_000.0 + HEARTBEAT_MAX_AGE_SECONDS,
            HEARTBEAT_MAX_AGE_SECONDS,
        )
        is True
    )
    assert (
        heartbeat_is_fresh(
            1_000.0,
            1_000.0 + HEARTBEAT_MAX_AGE_SECONDS + 0.001,
            HEARTBEAT_MAX_AGE_SECONDS,
        )
        is False
    )


def test_max_age_and_interval_are_single_constants_with_enough_margin():
    assert HEARTBEAT_MAX_AGE_SECONDS == 90
    assert HEARTBEAT_INTERVAL_SECONDS == 10
    # Margen mínimo de nueve latidos perdidos antes de declarar el bucle detenido.
    assert HEARTBEAT_MAX_AGE_SECONDS >= 9 * HEARTBEAT_INTERVAL_SECONDS


def test_max_age_constant_is_defined_only_once_in_the_application():
    definitions = [
        path
        for path in BACKEND_APP.rglob("*.py")
        if "HEARTBEAT_MAX_AGE_SECONDS =" in path.read_text(encoding="utf-8")
    ]

    assert definitions == [BACKEND_APP / "workers" / "heartbeat.py"]


def test_healthcheck_uses_the_single_max_age_constant_and_keeps_its_interval():
    block = worker_healthcheck_block()
    command_lines = [
        line for line in block.splitlines() if "heartbeat_is_fresh_at_path" in line
    ]

    assert len(command_lines) == 1
    command = command_lines[0]
    # La comprobación importa la constante única en lugar de repetir el número.
    assert "HEARTBEAT_MAX_AGE_SECONDS" in command
    assert "max_age=HEARTBEAT_MAX_AGE_SECONDS" in command
    assert "90" not in command
    # El intervalo de la comprobación (10 s) se conserva; no hay que retirarlo.
    assert "interval: 10s" in block


def test_module_docstring_states_the_stopped_loop_semantics():
    docstring = " ".join((heartbeat_module.__doc__ or "").split())

    assert (
        "El bucle se considera detenido cuando no completa una vuelta en 90 s"
        in docstring
    )
    assert "haya o no eventos" in docstring
    assert (
        "un fallo de dependencia con el bucle girando no cuenta como detenido"
        in docstring
    )


def test_default_heartbeat_path_lives_under_tmp():
    assert DEFAULT_HEARTBEAT_PATH.startswith("/tmp/")


def test_heartbeat_path_is_configurable_by_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(tmp_path / "otro-latido"))

    assert heartbeat_module.heartbeat_path() == str(tmp_path / "otro-latido")


def test_heartbeat_is_due_at_interval_or_without_previous_beat():
    assert heartbeat_is_due(None, 1_000.0, 10) is True
    assert heartbeat_is_due(1_000.0, 1_009.0, 10) is False
    assert heartbeat_is_due(1_000.0, 1_010.0, 10) is True
    # Un salto del reloj hacia atrás no puede silenciar el latido.
    assert heartbeat_is_due(1_000.0, 900.0, 10) is True


def test_publish_heartbeat_refreshes_the_file(tmp_path):
    path = tmp_path / "latido"

    publish_heartbeat(path)
    first = os.stat(path).st_mtime
    publish_heartbeat(path)
    second = os.stat(path).st_mtime

    assert second >= first
    assert heartbeat_is_fresh_at_path(path, now_epoch=os.stat(path).st_mtime) is True


async def test_loop_blocked_more_than_max_age_is_stale_and_recovers(
    monkeypatch, tmp_path
):
    path = tmp_path / "latido"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(path))
    monkeypatch.setattr(outbox, "get_settings", lambda: FakeSettings())

    clock = FakeClock()
    published: list[float] = []
    observations: list[tuple[str, bool]] = []
    turns: list[int] = []
    real_publish = heartbeat_module.publish_heartbeat

    def recording_publish(*_args, **_kwargs):
        real_publish()
        published.append(clock.now)

    async def process_without_events():
        # Sin eventos: la vuelta termina igualmente y el proceso sigue vivo.
        turns.append(1)
        return 0

    async def fake_sleep(_seconds):
        if len(turns) == 1:
            # Vuelta 1 (t=0): publica el latido y no hay eventos. La siguiente
            # vuelta empieza al cumplirse la cadencia de 10 s.
            clock.now = HEARTBEAT_INTERVAL_SECONDS
            return
        if len(turns) == 2:
            # Vuelta 2 (t=10): publica al empezar y, desde fuera, el bucle pasa
            # más de 90 s sin completar la siguiente vuelta (proceso vivo).
            clock.now = published[-1] + HEARTBEAT_MAX_AGE_SECONDS + 1
            observations.append(
                (
                    "bloqueado",
                    heartbeat_is_fresh(
                        published[-1], clock.now, HEARTBEAT_MAX_AGE_SECONDS
                    ),
                )
            )
            return
        # Vuelta 3: la publicación se reanuda en el mismo proceso.
        observations.append(
            (
                "reanudado",
                heartbeat_is_fresh(published[-1], clock.now, HEARTBEAT_MAX_AGE_SECONDS),
            )
        )
        raise StopLoop

    monkeypatch.setattr(outbox, "time", clock)
    monkeypatch.setattr(outbox, "publish_heartbeat", recording_publish)
    monkeypatch.setattr(outbox, "process_once", process_without_events)
    monkeypatch.setattr(outbox.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        await outbox.main()

    # Mismo proceso, sin reiniciar: publica a los 0 s, a los 10 s y al reanudarse.
    assert published == [0.0, 10.0, 101.0]
    assert observations == [("bloqueado", False), ("reanudado", True)]
    assert path.exists()


async def test_worker_main_publishes_heartbeat_even_when_processing_fails(
    monkeypatch, tmp_path
):
    path = tmp_path / "latido"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(path))
    monkeypatch.setattr(outbox, "get_settings", lambda: FakeSettings())

    clock = FakeClock()
    published: list[float] = []
    failures: list[float] = []
    real_publish = heartbeat_module.publish_heartbeat

    def recording_publish(*_args, **_kwargs):
        real_publish()
        published.append(clock.now)

    async def failing_process_once():
        # Base de datos caída: ``claim_outbox_events`` lanza y la vuelta acaba
        # con error, pero el bucle sigue girando.
        failures.append(clock.now)
        raise RuntimeError("base de datos caída")

    async def fake_sleep(_seconds):
        if len(failures) >= 3:
            raise StopLoop
        clock.now += HEARTBEAT_INTERVAL_SECONDS

    monkeypatch.setattr(outbox, "time", clock)
    monkeypatch.setattr(outbox, "publish_heartbeat", recording_publish)
    monkeypatch.setattr(outbox, "process_once", failing_process_once)
    monkeypatch.setattr(outbox.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        await outbox.main()

    # Al menos tres vueltas fallidas con el bucle girando: no es un bucle detenido.
    assert len(failures) == 3
    # El latido se publica al empezar cada vuelta, sin depender del procesamiento.
    assert published == [0.0, 10.0, 20.0]
    assert (
        heartbeat_is_fresh(published[-1], clock.now, HEARTBEAT_MAX_AGE_SECONDS)
        is True
    )
    assert path.exists()
    assert heartbeat_is_fresh_at_path(path, now_epoch=os.stat(path).st_mtime) is True


# --- Verificación operativa con contenedores (spec 009, RF-011) ---------------
# Pruebas baratas, sin Docker: el script se ejecuta a mano contra una pila viva
# y estos tests solo fijan su contrato estático y su sintaxis POSIX.


def verify_script_text() -> str:
    """Devuelve el código del script de verificación operativa."""

    return VERIFY_SCRIPT.read_text(encoding="utf-8")


def test_operational_verification_script_is_valid_posix_sh():
    assert VERIFY_SCRIPT.is_file()

    text = verify_script_text()
    assert text.splitlines()[0] == "#!/bin/sh"
    assert "\nset -eu\n" in text

    shell = shutil.which("sh")
    if shell is None:  # pragma: no cover - el entorno de CI siempre tiene sh
        pytest.skip("sh no está disponible")

    result = subprocess.run(
        [shell, "-n", str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_operational_verification_script_freezes_only_the_loop_process():
    text = verify_script_text()

    # Congela el bucle (PID 1 del contenedor) y lo reanuda; nunca el contenedor
    # completo, que también pararía el proceso del healthcheck.
    assert "kill -STOP 1" in text
    assert "kill -CONT 1" in text
    assert "docker pause" not in text
    assert "docker unpause" not in text
    # Dos usos de SIGCONT: el del flujo normal y el del trap de limpieza.
    assert text.count("kill -CONT 1") >= 2
    assert "trap cleanup EXIT" in text
    # El estado se lee del orquestador, no de una simulación.
    assert "{{.State.Health.Status}}" in text


def test_operational_verification_script_declares_exit_codes_and_timeouts():
    text = verify_script_text()

    # Códigos de salida: 0 verificado, 1 fallo, 2 no ejecutable.
    assert "NO EJECUTADA" in text
    assert "exit 2" in text
    assert "exit 1" in text
    # Valores por defecto del contrato de la tarea (T7).
    assert "WORKER_TARGET=${WORKER_TARGET:-bracket-craft-worker-1}" in text
    assert (
        "WORKER_HEALTH_UNHEALTHY_TIMEOUT=${WORKER_HEALTH_UNHEALTHY_TIMEOUT:-180}"
        in text
    )
    assert (
        "WORKER_HEALTH_RECOVERY_TIMEOUT=${WORKER_HEALTH_RECOVERY_TIMEOUT:-120}"
        in text
    )


def test_operational_verification_script_is_not_automated_in_ci():
    # RF-011 exige declarar la verificación, no automatizarla en CI.
    text = verify_script_text()
    assert ".github" not in text
    assert "ci.yml" not in text

    assert CI_PATH.is_file()
    assert "verify_worker_loop_health" not in CI_PATH.read_text(encoding="utf-8")
