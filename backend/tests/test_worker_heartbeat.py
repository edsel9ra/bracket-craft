"""Latido del worker del outbox (spec 008, RF-014).

El worker publica un fichero de latido para que su healthcheck mida que el
bucle avanza, no que haya trabajo. La frescura se calcula con un helper puro
que recibe el instante actual: nada dentro del helper lee el reloj.
"""

import os

import pytest

from app.workers import heartbeat as heartbeat_module
from app.workers import outbox
from app.workers.heartbeat import (
    DEFAULT_HEARTBEAT_PATH,
    HEARTBEAT_MAX_AGE_SECONDS,
    heartbeat_is_due,
    heartbeat_is_fresh,
    heartbeat_is_fresh_at_path,
    publish_heartbeat,
)


class StopLoop(Exception):
    """Detiene el bucle del worker en las pruebas."""


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


async def test_worker_main_publishes_heartbeat_even_when_processing_fails(
    monkeypatch, tmp_path
):
    path = tmp_path / "latido"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(path))

    class FakeSettings:
        app_env = "development"

    monkeypatch.setattr(outbox, "get_settings", lambda: FakeSettings())

    calls: list[int] = []

    async def failing_process_once():
        calls.append(1)
        raise RuntimeError("base de datos caída")

    async def fake_sleep(_seconds):
        if len(calls) >= 2:
            raise StopLoop
        return None

    monkeypatch.setattr(outbox, "process_once", failing_process_once)
    monkeypatch.setattr(outbox.asyncio, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        await outbox.main()

    assert len(calls) >= 2
    assert path.exists()
    assert heartbeat_is_fresh_at_path(path, now_epoch=os.stat(path).st_mtime) is True
