import asyncio

import pytest

from app import main as main_module
from app.core.outbox import OUTBOX_STREAM
from app.main import (
    RESYNC,
    RelayState,
    emit_gap_resync,
    emit_join_resync,
    new_resync_event_id,
    relay_cycle,
    relay_loop,
    resync_rooms,
    sio,
    stream_id_gt,
)


ORGANIZATION_ID = "org-1"


def envelope_fields(event_id):
    return {
        "event": (
            '{"organization_id": "org-1", "event_type": "MATCH_UPDATED", '
            f'"payload": {{"match_id": "match-1"}}, "event_id": "{event_id}"}}'
        )
    }


class StaticStreamRedis:
    def __init__(self, entries):
        self.entries = list(entries)
        self.xread_calls: list[str] = []

    async def xrange(self, name, count=1):
        return self.entries[:count]

    async def xrevrange(self, name, count=1):
        return list(reversed(self.entries))[:count]

    async def xread(self, streams, count=100, block=1000):
        start = streams[OUTBOX_STREAM]
        self.xread_calls.append(start)
        pending = [entry for entry in self.entries if stream_id_gt(entry[0], start)]
        return [(OUTBOX_STREAM, pending[:count])] if pending else []


class StoppingRedis:
    def __init__(self, stop):
        self.stop = stop
        self.closed = False

    async def xrange(self, name, count=1):
        return []

    async def xrevrange(self, name, count=1):
        return []

    async def info(self, section="default"):
        return {"run_id": "run-1"}

    async def xread(self, streams, count=100, block=1000):
        self.stop.set()
        return []

    async def aclose(self):
        self.closed = True


def test_new_resync_event_id_is_unique_and_has_the_resync_prefix():
    identifiers = {new_resync_event_id() for _ in range(20)}

    assert len(identifiers) == 20
    assert all(identifier.startswith("resync:") for identifier in identifiers)


def test_resync_rooms_derives_and_deduplicates_rooms():
    sessions = {
        "s1": {"scope": "organization", "organization_id": "org-1"},
        "s2": {"scope": "organization", "organization_id": "org-1"},
        "s3": {"scope": "public", "tournament_id": "tournament-1"},
        "s4": {"scope": "public", "tournament_id": "tournament-1"},
        "s5": {"scope": "public", "tournament_id": "tournament-2"},
        "s6": {},
        "s7": {"scope": "organization"},
        "s8": {"scope": "public", "tournament_id": ""},
        "s9": {"scope": "unknown", "organization_id": "org-2"},
    }

    assert resync_rooms(sessions) == [
        "organization:org-1",
        "tournament:tournament-1",
        "tournament:tournament-2",
    ]


async def test_emit_gap_resync_emits_once_per_room_with_the_minimal_payload(
    monkeypatch,
):
    sessions = {
        "s1": {"scope": "organization", "organization_id": "org-1"},
        "s2": {"scope": "organization", "organization_id": "org-1"},
        "s3": {"scope": "public", "tournament_id": "tournament-1"},
    }
    calls = []

    async def fake_emit(event, payload, room=None, **kwargs):
        calls.append({"event": event, "payload": payload, "room": room})

    monkeypatch.setattr(sio, "emit", fake_emit)

    await emit_gap_resync("STREAM_TRIMMED", sessions)

    assert [call["room"] for call in calls] == [
        "organization:org-1",
        "tournament:tournament-1",
    ]
    assert [call["event"] for call in calls] == [RESYNC, RESYNC]
    payloads = [call["payload"] for call in calls]
    assert payloads[0] == payloads[1]
    assert set(payloads[0]) == {"event_id", "reason"}
    assert payloads[0]["event_id"].startswith("resync:")
    assert payloads[0]["reason"] == "STREAM_TRIMMED"


async def test_each_gap_emission_uses_a_new_event_id(monkeypatch):
    sessions = {"s1": {"scope": "organization", "organization_id": "org-1"}}
    calls = []

    async def fake_emit(event, payload, room=None, **kwargs):
        calls.append(payload["event_id"])

    monkeypatch.setattr(sio, "emit", fake_emit)

    await emit_gap_resync("REDIS_RESET", sessions)
    await emit_gap_resync("REDIS_RESET", sessions)

    assert len(calls) == 2
    assert calls[0].startswith("resync:")
    assert calls[0] != calls[1]


async def test_emit_gap_resync_without_clients_emits_nothing_and_stores_nothing(
    monkeypatch,
):
    calls = []
    generated = []

    async def fake_emit(*args, **kwargs):
        calls.append((args, kwargs))

    def fake_new_event_id():
        generated.append("resync:test")
        return "resync:test"

    monkeypatch.setattr(sio, "emit", fake_emit)
    monkeypatch.setattr(main_module, "new_resync_event_id", fake_new_event_id)

    await emit_gap_resync("REDIS_RESET", {})
    await emit_gap_resync("STREAM_TRIMMED", {"s1": {}, "s2": {"scope": "unknown"}})

    assert calls == []
    assert generated == []


async def test_emit_gap_resync_logs_a_failure_and_continues_with_other_rooms(
    monkeypatch,
):
    sessions = {
        "s1": {"scope": "organization", "organization_id": "org-1"},
        "s2": {"scope": "public", "tournament_id": "tournament-1"},
    }
    calls = []

    async def flaky_emit(event, payload, room=None, **kwargs):
        calls.append(room)
        if room == "organization:org-1":
            raise RuntimeError("socket failure")

    monkeypatch.setattr(sio, "emit", flaky_emit)

    await emit_gap_resync("REDIS_RESET", sessions)

    assert calls == ["organization:org-1", "tournament:tournament-1"]


@pytest.mark.parametrize(
    ("sid", "metadata"),
    [
        ("sid-org", {"scope": "organization", "organization_id": "org-1"}),
        ("sid-public", {"scope": "public", "tournament_id": "tournament-1"}),
    ],
)
async def test_emit_join_resync_targets_only_the_joining_socket(
    monkeypatch, sid, metadata
):
    calls = []

    async def fake_emit(event, payload, room=None, to=None, **kwargs):
        calls.append({"event": event, "payload": payload, "to": to, "room": room})

    monkeypatch.setattr(main_module, "connected_socket_sessions", {sid: metadata})
    monkeypatch.setattr(sio, "emit", fake_emit)

    await emit_join_resync(sid)

    assert len(calls) == 1
    assert calls[0]["event"] == RESYNC
    assert calls[0]["to"] == sid
    assert calls[0]["room"] is None
    assert set(calls[0]["payload"]) == {"event_id", "reason"}
    assert calls[0]["payload"]["event_id"].startswith("resync:")
    assert calls[0]["payload"]["reason"] == "JOIN"


async def test_emit_join_resync_uses_a_new_event_id_per_emission(monkeypatch):
    identifiers = []

    async def fake_emit(event, payload, room=None, to=None, **kwargs):
        identifiers.append(payload["event_id"])

    monkeypatch.setattr(
        main_module,
        "connected_socket_sessions",
        {"sid-org": {"scope": "organization", "organization_id": "org-1"}},
    )
    monkeypatch.setattr(sio, "emit", fake_emit)

    await emit_join_resync("sid-org")
    await emit_join_resync("sid-org")

    assert len(identifiers) == 2
    assert identifiers[0] != identifiers[1]


async def test_emit_join_resync_ignores_an_unknown_socket(monkeypatch):
    calls = []

    async def fake_emit(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(main_module, "connected_socket_sessions", {})
    monkeypatch.setattr(sio, "emit", fake_emit)

    await emit_join_resync("missing-sid")

    assert calls == []


async def test_relay_loop_emits_relay_start_when_sockets_are_connected(monkeypatch):
    monkeypatch.setattr(main_module, "RELAY_RETRY_SECONDS", 0)
    stop = asyncio.Event()
    sessions = {"s1": {"scope": "organization", "organization_id": "org-1"}}
    calls = []

    async def fake_emit_gap(reason, sessions_arg=None):
        calls.append((reason, sessions_arg))

    monkeypatch.setattr(main_module, "connected_socket_sessions", sessions)
    monkeypatch.setattr(main_module, "emit_gap_resync", fake_emit_gap)

    await asyncio.wait_for(
        relay_loop(
            redis_factory=lambda url, decode_responses=True: StoppingRedis(stop),
            stop=stop,
        ),
        timeout=5,
    )

    assert calls == [("RELAY_START", sessions)]


async def test_relay_loop_does_not_emit_relay_start_without_sockets(monkeypatch):
    monkeypatch.setattr(main_module, "RELAY_RETRY_SECONDS", 0)
    stop = asyncio.Event()
    calls = []

    async def fake_emit_gap(reason, sessions_arg=None):
        calls.append((reason, sessions_arg))

    monkeypatch.setattr(main_module, "connected_socket_sessions", {})
    monkeypatch.setattr(main_module, "emit_gap_resync", fake_emit_gap)

    await asyncio.wait_for(
        relay_loop(
            redis_factory=lambda url, decode_responses=True: StoppingRedis(stop),
            stop=stop,
        ),
        timeout=5,
    )

    assert calls == []


async def test_a_gap_emits_one_resync_per_connected_room_and_advances(monkeypatch):
    sessions = {
        "s1": {"scope": "organization", "organization_id": "org-1"},
        "s2": {"scope": "public", "tournament_id": "tournament-1"},
    }
    calls = []
    emitted = []

    async def fake_emit(event, payload, room=None, **kwargs):
        calls.append({"event": event, "payload": payload, "room": room})

    async def emit(event):
        emitted.append(event)

    monkeypatch.setattr(main_module, "connected_socket_sessions", sessions)
    monkeypatch.setattr(sio, "emit", fake_emit)
    redis = StaticStreamRedis(
        [("5-0", envelope_fields("evt-5")), ("9-0", envelope_fields("evt-9"))]
    )
    state = RelayState(position="1-0", run_id="run-1", started=True)

    await relay_cycle(redis, state, emit, emit_gap_resync, current_run_id="run-1")

    assert [call["room"] for call in calls] == [
        "organization:org-1",
        "tournament:tournament-1",
    ]
    assert [call["event"] for call in calls] == [RESYNC, RESYNC]
    assert calls[0]["payload"] == calls[1]["payload"]
    assert calls[0]["payload"]["reason"] == "STREAM_TRIMMED"
    assert set(calls[0]["payload"]) == {"event_id", "reason"}
    assert state.position == "9-0"
    assert emitted == []
    assert redis.xread_calls == []


async def test_a_failing_resync_emit_does_not_interrupt_the_relay(monkeypatch):
    sessions = {
        "s1": {"scope": "organization", "organization_id": "org-1"},
        "s2": {"scope": "public", "tournament_id": "tournament-1"},
    }
    calls = []

    async def failing_emit(event, payload, room=None, **kwargs):
        calls.append(room)
        raise RuntimeError("socket failure")

    monkeypatch.setattr(main_module, "connected_socket_sessions", sessions)
    monkeypatch.setattr(sio, "emit", failing_emit)
    redis = StaticStreamRedis(
        [("5-0", envelope_fields("evt-5")), ("9-0", envelope_fields("evt-9"))]
    )
    state = RelayState(position="1-0", run_id="run-1", started=True)

    async def emit(event):
        raise AssertionError("no se debe reemitir el backlog")

    await relay_cycle(redis, state, emit, emit_gap_resync, current_run_id="run-1")

    assert calls == ["organization:org-1", "tournament:tournament-1"]
    assert state.position == "9-0"
    assert redis.xread_calls == []
