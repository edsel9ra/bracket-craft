"""Latido del worker del outbox (spec 008, RF-014).

El worker escribe un fichero de latido cada pocos segundos. Su healthcheck
comprueba la frescura de ese fichero: mide que el bucle avanza, no que haya
eventos que procesar. Este módulo solo usa la biblioteca estándar para que el
healthcheck pueda importarlo sin cargar la base de datos ni Redis.
"""

import logging
import os
import time

logger = logging.getLogger(__name__)

#: El healthcheck considera insano un latido de más de 90 s (RF-014).
HEARTBEAT_MAX_AGE_SECONDS = 90

#: Cadencia del latido; muy por debajo del límite de frescura de 90 s.
HEARTBEAT_INTERVAL_SECONDS = 10

#: Ruta escribible por el usuario ``app`` dentro del contenedor.
DEFAULT_HEARTBEAT_PATH = "/tmp/bracket-craft-worker-heartbeat"

HEARTBEAT_PATH_ENV = "WORKER_HEARTBEAT_PATH"


def heartbeat_path() -> str:
    """Ruta efectiva del latido, configurable por entorno."""

    return os.environ.get(HEARTBEAT_PATH_ENV) or DEFAULT_HEARTBEAT_PATH


def heartbeat_is_fresh(mtime_epoch: float, now_epoch: float, max_age: float) -> bool:
    """Indica si un latido con ``mtime_epoch`` es fresco en ``now_epoch``.

    Recibe el instante actual: no lee el reloj. Un ``mtime`` en el futuro se
    considera fresco para no producir un falso negativo por desfase de reloj.
    El límite es inclusivo.
    """

    age = now_epoch - mtime_epoch
    if age < 0:
        return True
    return age <= max_age


def heartbeat_is_due(
    last_epoch: float | None, now_epoch: float, interval: float
) -> bool:
    """Indica si toca volver a publicar el latido (sin leer el reloj)."""

    if last_epoch is None:
        return True
    if now_epoch < last_epoch:
        return True
    return now_epoch - last_epoch >= interval


def heartbeat_is_fresh_at_path(
    path: str | os.PathLike[str] | None = None,
    now_epoch: float | None = None,
    max_age: float = HEARTBEAT_MAX_AGE_SECONDS,
) -> bool:
    """Frescura del fichero de latido; ausente o inaccesible no es fresco."""

    if now_epoch is None:
        now_epoch = time.time()
    try:
        mtime = os.stat(heartbeat_path() if path is None else path).st_mtime
    except OSError:
        return False
    return heartbeat_is_fresh(mtime, now_epoch, max_age)


def publish_heartbeat(
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Escribe el latido de forma atómica (fichero temporal + ``os.replace``)."""

    target = os.fspath(heartbeat_path() if path is None else path)
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = f"{target}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(f"{int(time.time())}\n")
    os.replace(temporary, target)
