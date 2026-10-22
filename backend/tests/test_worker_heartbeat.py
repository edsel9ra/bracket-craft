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


# --- Sonda de outbox en la verificación operativa (spec 011, RF-003) ---------
# Pruebas baratas, sin contenedores: fijan el contrato estático del script, su
# orden (guard antes de congelar) y, con un ``docker`` de mentira, que un
# entorno no desarrollo/local sale 2 sin tocar el worker.


def shell_block(text: str, start: str) -> str:
    """Devuelve el bloque ``if``/``fi`` que contiene ``start``."""

    start_index = text.index(start)
    end = text.index("\nfi\n", start_index)
    return text[start_index:end]


def cleanup_block(text: str) -> str:
    """Devuelve el cuerpo de ``cleanup()`` del script."""

    match = re.search(r"\ncleanup\(\) \{\n(.*?)\n\}\n", text, re.DOTALL)
    assert match is not None
    return match.group(1)


def probe_step_block(text: str) -> str:
    """Devuelve el paso 7 (sonda) del script, desde su inserción al final."""

    return text[text.index("scripts.outbox_probe insert") :]


def verification_code(text: str) -> str:
    """Devuelve el código del script, sin la cabecera de documentación."""

    return text.split("\nset -eu\n", 1)[1]


def test_operational_verification_script_guards_the_environment_before_the_worker():
    text = verify_script_text()
    code = verification_code(text)

    guard_line = next(
        line for line in code.splitlines() if "scripts.outbox_probe guard" in line
    )
    # El guard corre dentro del contenedor (configuración efectiva del worker).
    assert "worker_exec" in guard_line
    assert "--force" not in text

    guard_index = code.index(guard_line)
    # Paso 0: antes de esperar el estado sano y antes de congelar el PID 1.
    assert guard_index < code.index('info "Paso 1')
    assert guard_index < code.index("kill -STOP 1")
    assert guard_index < code.index("wait_for_status healthy")

    # Un entorno no desarrollo/local es «no ejecutable» (código 2, sin escrituras).
    block = shell_block(code, "scripts.outbox_probe guard")
    assert "not_executable" in block


def test_operational_verification_script_declares_the_probe_budget():
    text = verify_script_text()

    assert "WORKER_PROBE_TIMEOUT=${WORKER_PROBE_TIMEOUT:-120}" in text
    assert "WORKER_PROBE_POLL_INTERVAL=${WORKER_PROBE_POLL_INTERVAL:-2}" in text
    # Se validan como enteros positivos en el bucle existente de los tiempos.
    assert '"WORKER_PROBE_TIMEOUT=$WORKER_PROBE_TIMEOUT"' in text
    assert '"WORKER_PROBE_POLL_INTERVAL=$WORKER_PROBE_POLL_INTERVAL"' in text

    # La cabecera documenta el paso nuevo, sus variables y los códigos 0/1/2.
    header = text.split("\nset -eu\n", 1)[0]
    assert "WORKER_PROBE_TIMEOUT" in header
    assert "WORKER_PROBE_POLL_INTERVAL" in header
    assert "sonda" in header.lower()
    assert "0  " in header and "1  " in header and "2  " in header


def test_operational_verification_script_probes_after_the_recovery():
    text = verify_script_text()
    code = verification_code(text)
    insert_index = code.index("scripts.outbox_probe insert")

    # Paso 7: solo después de reanudar y de comprobar que no hubo reinicio.
    assert insert_index > code.index('info "Paso 4')
    assert insert_index > code.index('info "Paso 5')
    assert insert_index > code.index('info "Paso 6')

    block = probe_step_block(code)
    assert "scripts.outbox_probe status" in block
    assert '--id "$PROBE_ID"' in block
    assert '--marker "$PROBE_MARKER"' in block
    assert "WORKER_PROBE_TIMEOUT" in block
    assert "WORKER_PROBE_POLL_INTERVAL" in block

    # pending/processing se siguen esperando; processed es éxito y failed falla.
    assert "status=processed" in block
    assert "status=failed" in block
    assert "status=retrying" in block
    assert "status=missing" in block

    # Marcador único por corrida: instante, PID y azar.
    marker_line = next(
        line
        for line in code.splitlines()
        if line.startswith("PROBE_MARKER=") and "/dev/urandom" in line
    )
    assert "date +%s" in marker_line
    assert "$$" in marker_line


def test_operational_verification_script_deletes_the_probe_on_exit():
    text = verify_script_text()
    block = cleanup_block(text)

    assert "scripts.outbox_probe delete" in block
    assert '--id "$PROBE_ID"' in block
    assert '--marker "$PROBE_MARKER"' in block
    # La limpieza reanuda el bucle antes de tocar la cola.
    assert block.index("kill -CONT 1") < block.index("scripts.outbox_probe delete")
    # Un borrado imposible no puede quedar en verde: informa y sale 1.
    assert "status=1" in block
    assert "PROBE_MARKER" in block


def test_operational_verification_script_exits_2_on_non_development_environment(
    tmp_path,
):
    # ``docker`` de mentira: el guard del worker responde 2 (entorno no dev) y
    # el script debe salir 2 sin congelar ni esperar el healthcheck.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.log"
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
case "$1" in
    info) exit 0 ;;
    --version) printf 'Docker version 27.0.0\\n'; exit 0 ;;
    inspect)
        case "$3" in
            '{{.Id}}') printf 'abc123\\n' ;;
            '{{.State.Running}}') printf 'true\\n' ;;
            '{{.RestartCount}}|{{.State.StartedAt}}|{{.State.Pid}}') printf '0|now|1\\n' ;;
            *) printf '\\n' ;;
        esac
        exit 0
        ;;
    exec)
        case "$*" in
            *'scripts.outbox_probe guard'*) printf 'no ejecutable: APP_ENV=production\\n'; exit 2 ;;
            *) exit 0 ;;
        esac
        ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = {key: value for key, value in os.environ.items() if key != "WORKER_TARGET"}
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DOCKER_CALLS"] = str(calls)

    result = subprocess.run(
        [shutil.which("sh"), str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "NO EJECUTADA" in result.stderr
    assert "no ejecutable" in (result.stdout + result.stderr).lower()
    recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
    # Ni congelación ni espera del healthcheck: el guard es lo único que corre.
    assert "kill" not in recorded
    assert "STOP" not in recorded
    assert "Health" not in recorded
    assert "STOP" not in result.stdout


# ``docker`` de mentira que recorre la verificación completa: el healthcheck
# sigue al fichero ``frozen`` (sano, insano al congelar y sano al reanudar), el
# latido avanza en cada lectura y los casos de la sonda los aporta cada prueba.
# Así se ejercita el paso 7 sin Docker real y sin tocar los datos demo.
FAKE_DOCKER_HEAD = """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
state_dir=$(dirname "$DOCKER_CALLS")
case "$1" in
    info) exit 0 ;;
    --version) printf 'Docker version 27.0.0\\n'; exit 0 ;;
    inspect)
        case "$3" in
            '{{.Id}}') printf 'abc123\\n' ;;
            '{{.State.Running}}') printf 'true\\n' ;;
            '{{.RestartCount}}|{{.State.StartedAt}}|{{.State.Pid}}') printf '0|now|1\\n' ;;
            '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')
                if [ -f "$state_dir/frozen" ]; then
                    printf 'unhealthy\\n'
                else
                    printf 'healthy\\n'
                fi
                ;;
            *) printf '\\n' ;;
        esac
        exit 0
        ;;
    exec)
        case "$*" in
            *'scripts.outbox_probe guard'*) printf 'APP_ENV=development\\n'; exit 0 ;;
            *'kill -STOP 1'*) : > "$state_dir/frozen"; exit 0 ;;
            *'kill -CONT 1'*) rm -f "$state_dir/frozen"; exit 0 ;;
            *'/proc/1/status'*)
                if [ -f "$state_dir/frozen" ]; then
                    printf 'T\\n'
                else
                    printf 'S\\n'
                fi
                exit 0
                ;;
            *'st_mtime'*)
                beats=$(cat "$state_dir/beats" 2>/dev/null || printf '0')
                beats=$((beats + 1))
                printf '%s\\n' "$beats" > "$state_dir/beats"
                printf '%s\\n' "$((beats * 100))"
                exit 0
                ;;
"""

FAKE_DOCKER_TAIL = """            *) exit 0 ;;
        esac
        ;;
esac
exit 0
"""


def run_verification_with_fake_docker(
    tmp_path: Path, probe_cases: str
) -> tuple[subprocess.CompletedProcess, str]:
    """Ejecuta el script con un ``docker`` de mentira y devuelve el resultado."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.log"
    docker = bin_dir / "docker"
    docker.write_text(
        FAKE_DOCKER_HEAD + probe_cases + FAKE_DOCKER_TAIL,
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = {key: value for key, value in os.environ.items() if key != "WORKER_TARGET"}
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DOCKER_CALLS"] = str(calls)

    result = subprocess.run(
        [shutil.which("sh"), str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
    return result, recorded


def test_operational_verification_script_reports_missing_demo_data_as_not_executable():
    code = verification_code(verify_script_text())
    block = probe_step_block(code)
    insert_section = block[: block.index('progress "sonda insertada')]

    # La inserción distingue «no ejecutable» (2) de un fallo de comportamiento.
    assert "scripts.outbox_probe insert" in insert_section
    assert "insert_status=$?" in insert_section
    assert '"$insert_status" -eq 2' in insert_section
    assert "not_executable" in insert_section
    assert "datos demo" in insert_section
    assert 'fail "no se pudo insertar la sonda' in insert_section

    # La consulta del estado también propaga 2 en lugar de «salida inesperada».
    status_branch = block[block.index('if [ "$probe_status" -eq 2 ]') :]
    assert "not_executable" in status_branch
    assert 'fail "la sonda devolvió una salida inesperada' in status_branch


def test_operational_verification_script_exits_2_when_demo_data_is_missing(tmp_path):
    probe_cases = """            *'scripts.outbox_probe insert'*)
                printf 'no ejecutable: no existe el usuario demo demo.owner@bracketcraft.dev\\n' >&2
                exit 2
                ;;
"""
    result, recorded = run_verification_with_fake_docker(tmp_path, probe_cases)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "NO EJECUTADA" in result.stderr
    assert "datos demo" in result.stderr
    # La sonda no se insertó y, al no haber identificador, no hubo borrado.
    assert "outbox_probe insert" in recorded
    assert "outbox_probe delete" not in recorded


def test_operational_verification_script_exits_2_when_the_probe_is_not_executable(
    tmp_path,
):
    probe_cases = """            *'scripts.outbox_probe insert'*)
                printf '0d0f4d1c-1111-4222-8333-444455556666 worker-probe\\n'
                exit 0
                ;;
            *'scripts.outbox_probe status'*|*'scripts.outbox_probe delete'*)
                printf 'no ejecutable: sin datos demo\\n' >&2
                exit 2
                ;;
"""
    result, recorded = run_verification_with_fake_docker(tmp_path, probe_cases)

    # El 2 del estado y del borrado prevalece sobre el «fallo de comportamiento».
    assert result.returncode == 2, result.stdout + result.stderr
    assert "NO EJECUTADA" in result.stderr
    assert "dejó de ser ejecutable" in result.stderr
    assert "outbox_probe status" in recorded
    assert "outbox_probe delete" in recorded
