"""Estado de un solo uso del flujo de Google en Redis (RF-6, RF-9, RNF-5).

El registro vive en Redis con TTL de 600 s y se consume de forma atómica con
``GETDEL``: el primer retorno gana y el segundo no ve nada. La clave es
``sha256(state)`` para que Redis nunca guarde el valor reutilizable del estado
ni lo escriba un registro (RNF-5); el registro solo lleva el hash, el flujo, el
destino ya validado, el usuario (solo en ``link``) y su caducidad.

Las pruebas usan un Redis falso en memoria (mismo estilo que el ``FakeRedis`` de
``test_hardening.py``) inyectado como parámetro: el módulo no crea conexiones.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import RedisError

from app.modules.identity.google_state import (
    ATTEMPT_TTL_SECONDS,
    GoogleAttempt,
    attempt_is_valid,
    consume_attempt,
    discard_attempt,
    new_state,
    save_attempt,
    state_cache_key,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
EXPIRES_AT = NOW + timedelta(seconds=ATTEMPT_TTL_SECONDS)
STATE_KEY_PREFIX = "bracket-craft:oauth:state:"


class FakeRedis:
    """Minimal in-memory Redis supporting ``set(ex=...)``, ``getdel`` and ``delete``."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.getdel_calls: list[str] = []
        self.delete_calls: list[str] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        self.set_calls.append((key, value, ex))
        return True

    async def getdel(self, key: str) -> str | None:
        self.getdel_calls.append(key)
        self.expirations.pop(key, None)
        return self.values.pop(key, None)

    async def delete(self, key: str) -> int:
        self.delete_calls.append(key)
        self.expirations.pop(key, None)
        return int(self.values.pop(key, None) is not None)


def make_attempt(**overrides) -> GoogleAttempt:
    values = {
        "flow": "login",
        "destination": "/workspace/tournaments/00000000-0000-0000-0000-000000000001",
        "user_id": None,
        "expires_at": EXPIRES_AT,
    }
    values.update(overrides)
    return GoogleAttempt(**values)


def digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Estado: generación y clave derivada
# ---------------------------------------------------------------------------


def test_new_state_is_cryptographically_shaped_and_urlsafe():
    state = new_state()

    # ``secrets.token_urlsafe(48)`` -> 64 caracteres sin relleno.
    assert len(state) >= 43
    assert re.fullmatch(r"[A-Za-z0-9_-]+", state)


def test_new_state_does_not_repeat_in_a_small_sample():
    states = {new_state() for _ in range(200)}

    assert len(states) == 200


def test_state_cache_key_is_the_sha256_of_the_state():
    state = new_state()

    key = state_cache_key(state)

    assert key == STATE_KEY_PREFIX + digest(state)
    assert state not in key
    assert key == state_cache_key(state)


def test_state_cache_key_differs_for_different_states():
    first = new_state()
    second = new_state()

    assert state_cache_key(first) != state_cache_key(second)


# ---------------------------------------------------------------------------
# Guardar el intento: TTL 600 y valor sin el estado crudo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_attempt_sets_the_record_with_ttl_600():
    redis = FakeRedis()
    state = new_state()
    attempt = make_attempt()

    await save_attempt(redis, state, attempt)

    assert ATTEMPT_TTL_SECONDS == 600
    assert len(redis.set_calls) == 1
    key, value, ex = redis.set_calls[0]
    assert key == state_cache_key(state)
    assert ex == ATTEMPT_TTL_SECONDS == 600
    assert redis.expirations[key] == 600

    record = json.loads(value)
    assert record == {
        "state_hash": digest(state),
        "flow": "login",
        "destination": attempt.destination,
        "user_id": None,
        "expires_at": EXPIRES_AT.isoformat(),
    }


@pytest.mark.asyncio
async def test_save_attempt_never_stores_the_raw_state():
    redis = FakeRedis()
    state = new_state()

    await save_attempt(redis, state, make_attempt())

    key, value, _ex = redis.set_calls[0]
    assert state not in key
    assert state not in value
    # Only the non-reusable digest appears.
    assert digest(state) in value


@pytest.mark.asyncio
async def test_save_attempt_keeps_the_user_only_for_the_link_flow():
    redis = FakeRedis()
    state = new_state()
    user_id = "00000000-0000-0000-0000-0000000000aa"

    await save_attempt(redis, state, make_attempt(flow="link", user_id=user_id))
    link_record = json.loads(redis.set_calls[0][1])

    assert link_record["flow"] == "link"
    assert link_record["user_id"] == user_id

    other = new_state()
    await save_attempt(redis, other, make_attempt(flow="login", user_id=None))
    login_record = json.loads(redis.set_calls[1][1])

    assert login_record["flow"] == "login"
    assert login_record["user_id"] is None


@pytest.mark.asyncio
async def test_save_attempt_preserves_a_missing_destination():
    redis = FakeRedis()

    await save_attempt(redis, new_state(), make_attempt(destination=None))

    assert json.loads(redis.set_calls[0][1])["destination"] is None


# ---------------------------------------------------------------------------
# Vigencia con el reloj inyectado
# ---------------------------------------------------------------------------


def test_attempt_is_valid_compares_expires_at_with_the_injected_now():
    attempt = make_attempt(expires_at=EXPIRES_AT)

    assert attempt_is_valid(attempt, now=EXPIRES_AT - timedelta(seconds=1)) is True
    assert attempt_is_valid(attempt, now=EXPIRES_AT) is False
    assert attempt_is_valid(attempt, now=EXPIRES_AT + timedelta(seconds=1)) is False


def test_attempt_is_valid_treats_a_naive_expiry_as_utc():
    naive_expiry = EXPIRES_AT.replace(tzinfo=None)
    attempt = make_attempt(expires_at=naive_expiry)

    assert attempt_is_valid(attempt, now=NOW) is True
    assert attempt_is_valid(attempt, now=EXPIRES_AT + timedelta(seconds=1)) is False


# ---------------------------------------------------------------------------
# Consumo atómico: el primero gana
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_attempt_returns_the_record_only_once():
    redis = FakeRedis()
    state = new_state()
    attempt = make_attempt(flow="link", user_id="00000000-0000-0000-0000-0000000000aa")
    await save_attempt(redis, state, attempt)

    first = await consume_attempt(redis, state)
    second = await consume_attempt(redis, state)

    assert first == attempt
    assert first is not None
    assert first.state_hash == digest(state)
    assert second is None
    assert redis.getdel_calls == [state_cache_key(state), state_cache_key(state)]
    assert state_cache_key(state) not in redis.values


@pytest.mark.asyncio
async def test_consume_attempt_returns_none_when_the_state_was_never_saved():
    redis = FakeRedis()

    assert await consume_attempt(redis, new_state()) is None


@pytest.mark.asyncio
async def test_consume_attempt_returns_an_expired_record_and_the_caller_decides():
    redis = FakeRedis()
    state = new_state()
    expired = make_attempt(expires_at=NOW - timedelta(seconds=1))
    await save_attempt(redis, state, expired)

    consumed = await consume_attempt(redis, state)

    assert consumed == expired
    assert attempt_is_valid(consumed, now=NOW) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored",
    [
        "not json",
        "[]",
        '"text"',
        "null",
        '{"flow": "login"}',
        json.dumps(
            {
                "state_hash": "x",
                "flow": "other",
                "destination": None,
                "user_id": None,
                "expires_at": EXPIRES_AT.isoformat(),
            }
        ),
        json.dumps(
            {
                "state_hash": "x",
                "flow": "login",
                "destination": None,
                "user_id": None,
                "expires_at": "not-a-date",
            }
        ),
        json.dumps(
            {
                "state_hash": 1,
                "flow": "login",
                "destination": None,
                "user_id": None,
                "expires_at": EXPIRES_AT.isoformat(),
            }
        ),
    ],
)
async def test_consume_attempt_fails_closed_on_a_corrupted_record(stored):
    redis = FakeRedis()
    state = new_state()
    key = state_cache_key(state)
    redis.values[key] = stored

    assert await consume_attempt(redis, state) is None
    assert key not in redis.values


# ---------------------------------------------------------------------------
# Descarte
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_attempt_deletes_the_key():
    redis = FakeRedis()
    state = new_state()
    await save_attempt(redis, state, make_attempt())

    await discard_attempt(redis, state)

    assert redis.delete_calls == [state_cache_key(state)]
    assert state_cache_key(state) not in redis.values
    assert await consume_attempt(redis, state) is None


@pytest.mark.asyncio
async def test_discard_attempt_is_harmless_when_the_state_does_not_exist():
    redis = FakeRedis()
    state = new_state()

    await discard_attempt(redis, state)

    assert redis.delete_calls == [state_cache_key(state)]


@pytest.mark.asyncio
async def test_discard_attempt_does_not_raise_when_redis_fails():
    class FailingRedis(FakeRedis):
        async def delete(self, key: str) -> int:
            raise RedisError("Redis no disponible")

    state = new_state()

    # Best-effort: un fallo al borrar no convierte la cancelación en un error.
    await discard_attempt(FailingRedis(), state)
