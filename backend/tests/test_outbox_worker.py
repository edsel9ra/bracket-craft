import inspect
import json
import uuid
from datetime import datetime

import pytest
from redis.asyncio import Redis

from app.core.outbox import OUTBOX_STREAM, OUTBOX_STREAM_MAXLEN
from app.workers.outbox import build_stream_message, publish_stream_event


EVENT_ID = "3f1c0f2e-8a4b-4d7c-9e6f-1a2b3c4d5e6f"
ORGANIZATION_ID = "0b7d5a4c-2e1f-4a3b-8c9d-6e5f4a3b2c1d"


def make_event(**overrides):
    event = {
        "id": EVENT_ID,
        "organization_id": ORGANIZATION_ID,
        "event_type": "MATCH_CLOSED",
        "payload": {"match_id": "match-1", "tournament_id": "tournament-1"},
    }
    event.update(overrides)
    return event


class FakeRedis:
    """Registra las llamadas de ``xadd`` sin conexión real."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[dict] = []
        self.error = error

    async def xadd(self, name, fields, **kwargs):
        self.calls.append({"name": name, "fields": fields, "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        return "1700000000000-0"


def test_outbox_stream_maxlen_is_the_fixed_cap():
    assert OUTBOX_STREAM_MAXLEN == 10_000


def test_build_stream_message_carries_the_envelope_contract():
    event = make_event()

    message = build_stream_message(event)

    assert isinstance(message, str)
    decoded = json.loads(message)
    assert set(decoded) == {
        "event_id",
        "id",
        "organization_id",
        "event_type",
        "payload",
    }
    assert decoded["event_id"] == EVENT_ID
    assert decoded["id"] == EVENT_ID
    assert decoded["event_id"] == decoded["id"]
    assert decoded["organization_id"] == ORGANIZATION_ID
    assert decoded["event_type"] == "MATCH_CLOSED"
    assert decoded["payload"] == {
        "match_id": "match-1",
        "tournament_id": "tournament-1",
    }
    # El payload de dominio no cambia y el evento de origen no se muta.
    assert decoded["payload"] == event["payload"]
    assert event == make_event()


def test_build_stream_message_stringifies_non_string_identifiers():
    identifier = uuid.uuid4()
    organization_id = uuid.uuid4()

    decoded = json.loads(
        build_stream_message(make_event(id=identifier, organization_id=organization_id))
    )

    assert decoded["id"] == str(identifier)
    assert decoded["event_id"] == str(identifier)
    assert decoded["organization_id"] == str(organization_id)


def test_build_stream_message_uses_default_str_for_non_serializable_payload():
    closed_at = datetime(2026, 10, 19, 12, 30, 45)
    identifier = uuid.uuid4()
    event = make_event(
        payload={
            "match_id": "match-1",
            "closed_at": closed_at,
            "reviewed_by": identifier,
        }
    )

    decoded = json.loads(build_stream_message(event))

    assert decoded["payload"]["match_id"] == "match-1"
    assert decoded["payload"]["closed_at"] == "2026-10-19 12:30:45"
    assert decoded["payload"]["reviewed_by"] == str(identifier)


async def test_publish_stream_event_uses_maxlen_and_the_event_field():
    redis = FakeRedis()
    event = make_event()

    await publish_stream_event(redis, event)

    assert len(redis.calls) == 1
    call = redis.calls[0]
    assert call["name"] == OUTBOX_STREAM
    assert set(call["fields"]) == {"event"}
    assert json.loads(call["fields"]["event"]) == json.loads(build_stream_message(event))
    assert call["kwargs"]["maxlen"] == 10_000
    assert call["kwargs"]["approximate"] is True
    assert "limit" not in call["kwargs"]
    assert "minid" not in call["kwargs"]


def test_the_installed_redis_client_accepts_the_publish_kwargs():
    # ``approximate=True`` es el modo que produce ``MAXLEN ~`` en redis-py;
    # si una versión futura renombrara los argumentos, esta prueba lo detecta.
    signature = inspect.signature(Redis.xadd)

    assert "maxlen" in signature.parameters
    assert "approximate" in signature.parameters
    signature.bind(
        object(),
        OUTBOX_STREAM,
        {"event": "{}"},
        maxlen=OUTBOX_STREAM_MAXLEN,
        approximate=True,
    )


async def test_publish_stream_event_propagates_xadd_failures():
    # No se captura la excepción: ``process_once`` debe poder ejecutar
    # ``fail_outbox_event`` y no completar el evento.
    redis = FakeRedis(error=RuntimeError("redis unavailable"))

    with pytest.raises(RuntimeError, match="redis unavailable"):
        await publish_stream_event(redis, make_event())

    assert len(redis.calls) == 1
