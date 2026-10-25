"""Estado de un solo uso del flujo de Google en Redis (RF-6, RF-9, RNF-5).

Redis (ya dependencia del rate limit y del outbox) guarda el intento antes de
verificar ninguna identidad, con TTL de 600 s y consumo atómico ``GETDEL``: dos
retornos simultáneos solo pueden consumir el registro una vez. La clave es
``sha256(state)``, de modo que el valor reutilizable del estado nunca se usa como
clave ni se escribe en el registro ni en un log.

El módulo no crea conexiones: el cliente se inyecta como parámetro (el router
lo construye con ``Redis.from_url(settings.redis_url)``). ``attempt_is_valid``
compara con el ``now`` inyectado y no lee el reloj.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from redis.exceptions import RedisError

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones, sin conexión
    from redis.asyncio import Redis

STATE_KEY_PREFIX = "bracket-craft:oauth:state:"

# Caducidad del intento: 10 minutos, garantizada dos veces (TTL de Redis y
# ``expires_at`` del registro).
ATTEMPT_TTL_SECONDS = 600

# ``secrets.token_urlsafe(48)`` produce 64 caracteres URL-safe sin relleno.
STATE_BYTES = 48

_FLOWS = frozenset({"login", "link"})


@dataclass(frozen=True)
class GoogleAttempt:
    """Intento en curso: solo lo necesario para resolver el retorno.

    No lleva correo, nombre, token ni ningún dato de la cuenta. ``state_hash``
    es el SHA-256 del estado: se guarda en el registro para poder correlacionarlo
    con su clave sin conservar el valor reutilizable. Lo rellena
    ``save_attempt`` y queda fuera de la igualdad (la clave ya vincula el
    registro con el estado).
    """

    flow: Literal["login", "link"]
    destination: str | None
    user_id: str | None
    expires_at: datetime
    state_hash: str = field(default="", compare=False, repr=False)


def new_state() -> str:
    """Devuelve un estado impredecible y URL-safe."""

    return secrets.token_urlsafe(STATE_BYTES)


def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def state_cache_key(state: str) -> str:
    """Clave de Redis del intento: prefijo + SHA-256 del estado."""

    return STATE_KEY_PREFIX + _state_digest(state)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def attempt_is_valid(attempt: GoogleAttempt, *, now: datetime) -> bool:
    """Indica si ``attempt`` sigue vigente en ``now`` (reloj inyectado)."""

    if not isinstance(now, datetime):
        return False
    return _as_utc(attempt.expires_at) > _as_utc(now)


def _record(attempt: GoogleAttempt) -> dict[str, object]:
    """Forma serializada; ninguna clave contiene datos personales ni el estado crudo."""

    return {
        "state_hash": attempt.state_hash,
        "flow": attempt.flow,
        "destination": attempt.destination,
        "user_id": None if attempt.user_id is None else str(attempt.user_id),
        "expires_at": attempt.expires_at.isoformat(),
    }


def _attempt_from_record(payload: object) -> GoogleAttempt:
    """Reconstruye el intento o falla cerrado con ``ValueError``."""

    if not isinstance(payload, dict):
        raise ValueError("El registro del intento no es un objeto JSON.")

    state_hash = payload["state_hash"]
    flow = payload["flow"]
    destination = payload["destination"]
    user_id = payload["user_id"]
    expires_at = payload["expires_at"]

    if not isinstance(state_hash, str) or not state_hash:
        raise ValueError("El registro del intento no tiene un hash de estado.")
    if flow not in _FLOWS:
        raise ValueError("El registro del intento tiene un flujo desconocido.")
    if destination is not None and not isinstance(destination, str):
        raise ValueError("El registro del intento tiene un destino inválido.")
    if user_id is not None and not isinstance(user_id, str):
        raise ValueError("El registro del intento tiene un usuario inválido.")
    if not isinstance(expires_at, str):
        raise ValueError("El registro del intento no tiene caducidad.")
    parsed_expiry = datetime.fromisoformat(expires_at)

    return GoogleAttempt(
        flow=flow,
        destination=destination,
        user_id=user_id,
        expires_at=parsed_expiry,
        state_hash=state_hash,
    )


async def save_attempt(redis: Redis, state: str, attempt: GoogleAttempt) -> None:
    """Guarda el intento con ``EX 600``; recalcula el hash del estado."""

    record = replace(attempt, state_hash=_state_digest(state))
    await redis.set(
        state_cache_key(state),
        json.dumps(_record(record), separators=(",", ":"), ensure_ascii=False),
        ex=ATTEMPT_TTL_SECONDS,
    )


async def consume_attempt(redis: Redis, state: str) -> GoogleAttempt | None:
    """Consume el intento con ``GETDEL``: solo el primer retorno lo obtiene.

    Devuelve ``None`` si el estado no existe, ya se consumió o el registro está
    corrupto (falla cerrada). La caducidad lógica la decide ``attempt_is_valid``.
    """

    raw = await redis.getdel(state_cache_key(state))
    if raw is None:
        return None

    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str):
        return None

    try:
        return _attempt_from_record(json.loads(raw))
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        return None


async def discard_attempt(redis: Redis, state: str) -> None:
    """Borra el intento (``DEL``); un fallo de Redis no interrumpe la cancelación."""

    try:
        await redis.delete(state_cache_key(state))
    except RedisError:
        # Best-effort (plan §6.5): el TTL y la caducidad del registro siguen
        # cerrando el intento aunque el borrado no llegue a Redis.
        return
