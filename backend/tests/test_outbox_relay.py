import asyncio
import json
import logging

import pytest

from app import main as main_module
from app.core.outbox import OUTBOX_STREAM
from app.main import (
    ParsedEvent,
    RelayState,
    build_realtime_payload,
    emit_domain_event,
    parse_envelope,
    parse_run_id,
    read_run_id,
    relay_cycle,
    relay_loop,
    resolve_tail,
    sio,
    stream_id_gt,
)


ORGANIZATION_ID = "org-1"


def envelope_fields(
    *,
    event_type="MATCH_UPDATED",
    organization_id=ORGANIZATION_ID,
    payload=None,
    **identifier_fields,
):
    data = {
        "organization_id": organization_id,
        "event_type": event_type,
        "payload": {"match_id": "match-1"} if payload is None else payload,
    }
    data.update(identifier_fields)
    return {"event": json.dumps(data)}


def field_with_event_id(event_id, **kwargs):
    return envelope_fields(event_id=event_id, **kwargs)


class FakeStreamRedis:
    """Stream acotado en memoria con la semántica mínima de ``XREVRANGE``/``XREAD``."""

    def __init__(self, entries=None):
        self.entries = list(entries or [])
        self.xread_calls: list[dict] = []
        self.xrevrange_calls = 0
        self.closed = False

    async def xrevrange(self, name, count=1):
        self.xrevrange_calls += 1
        return list(reversed(self.entries))[:count]

    async def xrange(self, name, count=1):
        return self.entries[:count]

    async def xread(self, streams, count=100, block=1000):
        start = streams[OUTBOX_STREAM]
        self.xread_calls.append({"start": start, "count": count, "block": block})
        pending = [entry for entry in self.entries if stream_id_gt(entry[0], start)]
        return [(OUTBOX_STREAM, pending[:count])] if pending else []

    async def aclose(self):
        self.closed = True


def recording_emit():
    events = []

    async def emit(event):
        events.append(event)

    return events, emit


async def test_first_cycle_starts_at_the_tail_and_does_not_replay_history():
    redis = FakeStreamRedis(
        [
            ("1-0", field_with_event_id("evt-1")),
            ("2-0", field_with_event_id("evt-2")),
        ]
    )
    emitted, emit = recording_emit()
    state = RelayState()

    await relay_cycle(redis, state, emit)

    assert emitted == []
    assert state.started is True
    assert state.position == "2-0"
    assert redis.xread_calls == [{"start": "2-0", "count": 100, "block": 1000}]

    redis.entries.append(("3-0", field_with_event_id("evt-3")))
    await relay_cycle(redis, state, emit)

    assert [event.event_id for event in emitted] == ["evt-3"]
    assert state.position == "3-0"


async def test_first_cycle_on_an_empty_stream_delivers_the_first_new_entry():
    redis = FakeStreamRedis()
    emitted, emit = recording_emit()
    state = RelayState()

    await relay_cycle(redis, state, emit)

    assert emitted == []
    assert state.started is True
    assert state.position is None
    assert redis.xread_calls[0]["start"] == "0-0"

    redis.entries.append(("1-0", field_with_event_id("evt-1")))
    await relay_cycle(redis, state, emit)

    assert [event.event_id for event in emitted] == ["evt-1"]
    assert state.position == "1-0"


async def test_resolve_tail_returns_the_last_entry_or_none():
    empty = FakeStreamRedis()
    populated = FakeStreamRedis(
        [("1-0", field_with_event_id("evt-1")), ("2-0", field_with_event_id("evt-2"))]
    )

    assert await resolve_tail(empty) is None
    assert await resolve_tail(populated) == "2-0"


class ScriptedRedis:
    """Cliente guionizado: sirve lotes de ``xread`` y cierra el bucle al agotarse."""

    def __init__(self, tail, batches, stop):
        self.entries = [(tail, {"event": "{}"})] if tail is not None else []
        self.batches = list(batches)
        self.stop = stop
        self.starts: list[str] = []
        self.xrevrange_calls = 0
        self.closed = False

    async def xrevrange(self, name, count=1):
        self.xrevrange_calls += 1
        return list(reversed(self.entries))[:count]

    async def xrange(self, name, count=1):
        return self.entries[:count]

    async def xread(self, streams, count=100, block=1000):
        self.starts.append(streams[OUTBOX_STREAM])
        if self.batches:
            batch = self.batches.pop(0)
            for _, entries in batch:
                self.entries.extend(entries)
            return batch
        self.stop.set()
        return []

    async def aclose(self):
        self.closed = True


async def test_relay_loop_retries_and_resolves_the_tail_on_the_first_connection(
    monkeypatch,
):
    monkeypatch.setattr(main_module, "RELAY_RETRY_SECONDS", 0)
    stop = asyncio.Event()
    emitted, emit = recording_emit()
    monkeypatch.setattr(main_module, "emit_domain_event", emit)

    attempts = {"count": 0}
    clients: list[ScriptedRedis] = []

    def factory(url, decode_responses=True):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("redis unavailable")
        client = ScriptedRedis(
            tail="8-0",
            batches=[
                [],
                [(OUTBOX_STREAM, [("9-0", field_with_event_id("evt-9"))])],
            ],
            stop=stop,
        )
        clients.append(client)
        return client

    await asyncio.wait_for(relay_loop(redis_factory=factory, stop=stop), timeout=5)

    assert attempts["count"] == 3
    # El acumulado hasta "8-0" nunca se emite; solo la entrada posterior.
    assert [event.event_id for event in emitted] == ["evt-9"]
    assert clients[0].xrevrange_calls >= 1
    assert clients[0].starts[0] == "8-0"
    assert clients[0].closed is True


class RecoveringRedis:
    """Cliente que puede fallar en lectura y comparte el stream entre conexiones."""

    def __init__(self, entries, stop, fail_reads=0):
        self.entries = entries
        self.stop = stop
        self.fail_reads = fail_reads
        self.starts: list[str] = []
        self.closed = False

    async def xrevrange(self, name, count=1):
        return list(reversed(self.entries))[:count]

    async def xrange(self, name, count=1):
        return self.entries[:count]

    async def xread(self, streams, count=100, block=1000):
        start = streams[OUTBOX_STREAM]
        self.starts.append(start)
        if self.fail_reads:
            self.fail_reads -= 1
            raise ConnectionError("connection lost")
        pending = [entry for entry in self.entries if stream_id_gt(entry[0], start)]
        if pending:
            return [(OUTBOX_STREAM, pending[:count])]
        self.stop.set()
        return []

    async def aclose(self):
        self.closed = True


async def test_live_connection_loss_keeps_the_position_and_resends_retained_entries(
    monkeypatch,
):
    monkeypatch.setattr(main_module, "RELAY_RETRY_SECONDS", 0)
    stop = asyncio.Event()
    emitted, emit = recording_emit()
    monkeypatch.setattr(main_module, "emit_domain_event", emit)

    entries = [("1-0", field_with_event_id("evt-1"))]
    clients: list[RecoveringRedis] = []

    def factory(url, decode_responses=True):
        client = RecoveringRedis(entries, stop, fail_reads=1 if not clients else 0)
        if clients:
            # Publicados mientras el proceso estaba sin conexión.
            entries.extend(
                [
                    ("2-0", field_with_event_id("evt-2")),
                    ("3-0", field_with_event_id("evt-3")),
                ]
            )
        clients.append(client)
        return client

    await asyncio.wait_for(relay_loop(redis_factory=factory, stop=stop), timeout=5)

    assert [event.event_id for event in emitted] == ["evt-2", "evt-3"]
    assert clients[0].starts == ["1-0"]
    assert clients[1].starts[0] == "1-0"
    assert clients[0].closed is True
    assert clients[1].closed is True


async def test_position_advances_entry_by_entry_so_a_failure_repeats_at_most_one():
    redis = FakeStreamRedis()
    state = RelayState()
    emitted, emit = recording_emit()

    # Arranque con el stream vacío: la posición queda lista para el primer evento.
    await relay_cycle(redis, state, emit)
    redis.entries.extend(
        [
            ("1-0", field_with_event_id("evt-1")),
            ("2-0", field_with_event_id("evt-2")),
        ]
    )

    async def failing_emit(event):
        emitted.append(event.event_id)
        if event.event_id == "evt-2":
            raise RuntimeError("emit failed")

    with pytest.raises(RuntimeError, match="emit failed"):
        await relay_cycle(redis, state, failing_emit)

    # La posición se avanzó tras "evt-1" y no antes de emitir "evt-2".
    assert state.position == "1-0"
    assert emitted == ["evt-1", "evt-2"]

    emitted_after_retry = []

    async def emit(event):
        emitted_after_retry.append(event.event_id)

    await relay_cycle(redis, state, emit)

    assert emitted_after_retry == ["evt-2"]
    assert state.position == "2-0"


@pytest.mark.parametrize(
    ("identifier_fields", "expected"),
    [
        ({"event_id": "evt-1"}, "evt-1"),
        ({"id": "legacy-1"}, "legacy-1"),
        ({"event_id": None, "id": "legacy-2"}, "legacy-2"),
        ({"event_id": "", "id": "legacy-3"}, "legacy-3"),
        ({"event_id": 123, "id": "legacy-4"}, "legacy-4"),
        ({"event_id": ["evt"], "id": "legacy-5"}, "legacy-5"),
        ({"event_id": "evt-server", "id": "evt-legacy"}, "evt-server"),
        ({}, None),
        ({"event_id": None}, None),
        ({"event_id": 123}, None),
        ({"event_id": ""}, None),
        ({"id": 123}, None),
    ],
)
def test_parse_envelope_resolves_the_delivery_identifier(identifier_fields, expected):
    event = parse_envelope(envelope_fields(**identifier_fields))

    assert event is not None
    assert event.event_id == expected


def test_parse_envelope_preserves_the_domain_fields():
    payload = {"match_id": "match-1", "tournament_id": "tournament-1"}
    event = parse_envelope(
        envelope_fields(event_type="MATCH_CLOSED", payload=payload, event_id="evt-1")
    )

    assert event == ParsedEvent(
        event_id="evt-1",
        organization_id=ORGANIZATION_ID,
        event_type="MATCH_CLOSED",
        payload=payload,
    )


@pytest.mark.parametrize(
    "fields",
    [
        None,
        {},
        {"event": None},
        {"event": "{}"},
        {"event": "not-json"},
        {"event": json.dumps(["not", "an", "object"])},
        {"event": json.dumps({"organization_id": ORGANIZATION_ID})},
        {
            "event": json.dumps(
                {
                    "organization_id": ORGANIZATION_ID,
                    "event_type": "",
                    "payload": {},
                }
            )
        },
        {
            "event": json.dumps(
                {
                    "organization_id": ORGANIZATION_ID,
                    "event_type": 7,
                    "payload": {},
                }
            )
        },
        {
            "event": json.dumps(
                {
                    "event_type": "MATCH_UPDATED",
                    "payload": {},
                }
            )
        },
        {
            "event": json.dumps(
                {
                    "organization_id": ORGANIZATION_ID,
                    "event_type": "MATCH_UPDATED",
                    "payload": ["not", "an", "object"],
                }
            )
        },
    ],
)
def test_parse_envelope_returns_none_for_malformed_entries(fields):
    assert parse_envelope(fields) is None


def test_parse_envelope_warns_without_identifier_and_never_logs_the_payload(caplog):
    payload = {"match_id": "match-sensitive", "tournament_id": "tournament-1"}

    with caplog.at_level(logging.WARNING, logger="app.main"):
        event = parse_envelope(envelope_fields(payload=payload))

    assert event is not None
    assert event.event_id is None
    assert "sin event_id" in caplog.text
    assert "match-sensitive" not in caplog.text
    assert ORGANIZATION_ID not in caplog.text


def test_parse_envelope_does_not_warn_when_it_has_a_valid_identifier(caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        event = parse_envelope(envelope_fields(event_id="evt-1"))

    assert event is not None
    assert event.event_id == "evt-1"
    assert "sin event_id" not in caplog.text


def test_build_realtime_payload_keeps_domain_fields_and_adds_the_server_event_id():
    payload = {"match_id": "match-1", "tournament_id": "tournament-1"}

    result = build_realtime_payload(payload, "evt-1")

    assert result == {
        "match_id": "match-1",
        "tournament_id": "tournament-1",
        "event_id": "evt-1",
    }
    assert payload == {"match_id": "match-1", "tournament_id": "tournament-1"}


def test_build_realtime_payload_drops_a_domain_event_id():
    payload = {"event_id": "domain-id", "match_id": "match-1"}

    assert build_realtime_payload(payload, "server-id") == {
        "match_id": "match-1",
        "event_id": "server-id",
    }
    assert payload["event_id"] == "domain-id"

    assert build_realtime_payload(payload, None) == {"match_id": "match-1"}


async def test_emit_domain_event_uses_the_same_event_id_in_organization_and_tournament(
    monkeypatch,
):
    calls = []

    async def fake_emit(event, payload, room=None):
        calls.append({"event": event, "payload": payload, "room": room})

    monkeypatch.setattr(sio, "emit", fake_emit)
    event = ParsedEvent(
        event_id="evt-1",
        organization_id=ORGANIZATION_ID,
        event_type="MATCH_UPDATED",
        payload={"match_id": "match-1", "tournament_id": "tournament-1"},
    )

    await emit_domain_event(event)

    assert [call["room"] for call in calls] == [
        f"organization:{ORGANIZATION_ID}",
        "tournament:tournament-1",
    ]
    assert [call["event"] for call in calls] == ["MATCH_UPDATED", "MATCH_UPDATED"]
    assert calls[0]["payload"] == calls[1]["payload"] == {
        "match_id": "match-1",
        "tournament_id": "tournament-1",
        "event_id": "evt-1",
    }


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("MATCH_UPDATED", {"match_id": "match-1"}),
        ("SEASON_CLOSED", {"tournament_id": "tournament-1"}),
    ],
)
async def test_emit_domain_event_only_targets_the_organization_when_not_public(
    monkeypatch, event_type, payload
):
    calls = []

    async def fake_emit(event, payload, room=None):
        calls.append({"event": event, "payload": payload, "room": room})

    monkeypatch.setattr(sio, "emit", fake_emit)
    event = ParsedEvent(
        event_id="evt-1",
        organization_id=ORGANIZATION_ID,
        event_type=event_type,
        payload=payload,
    )

    await emit_domain_event(event)

    assert [call["room"] for call in calls] == [f"organization:{ORGANIZATION_ID}"]


async def test_emit_domain_event_without_identifier_keeps_the_domain_payload(
    monkeypatch,
):
    calls = []

    async def fake_emit(event, payload, room=None):
        calls.append({"event": event, "payload": payload, "room": room})

    monkeypatch.setattr(sio, "emit", fake_emit)
    event = ParsedEvent(
        event_id=None,
        organization_id=ORGANIZATION_ID,
        event_type="MATCH_UPDATED",
        payload={"match_id": "match-1", "tournament_id": "tournament-1"},
    )

    await emit_domain_event(event)

    assert calls[0]["payload"] == {
        "match_id": "match-1",
        "tournament_id": "tournament-1",
    }


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("10-0", "9-9", True),
        ("9-9", "10-0", False),
        ("2-0", "2-0", False),
        ("1-10", "1-9", True),
        ("0-1", "0-0", True),
    ],
)
def test_stream_id_gt_compares_milliseconds_then_sequence(left, right, expected):
    assert stream_id_gt(left, right) is expected


class ContinuityRedis:
    """Stream estático para probar las comprobaciones de continuidad."""

    def __init__(self, entries, info=None):
        self.entries = list(entries)
        self.info_value = info
        self.xread_calls: list[str] = []
        self.info_calls = 0

    async def xrange(self, name, count=1):
        return self.entries[:count]

    async def xrevrange(self, name, count=1):
        return list(reversed(self.entries))[:count]

    async def xread(self, streams, count=100, block=1000):
        start = streams[OUTBOX_STREAM]
        self.xread_calls.append(start)
        pending = [entry for entry in self.entries if stream_id_gt(entry[0], start)]
        return [(OUTBOX_STREAM, pending[:count])] if pending else []

    async def info(self, section="default"):
        self.info_calls += 1
        if isinstance(self.info_value, Exception):
            raise self.info_value
        return self.info_value


class NoInfoRedis(ContinuityRedis):
    async def info(self, section="default"):
        raise RuntimeError("INFO disabled")


def recording_resync():
    reasons = []

    async def emit_resync(reason):
        reasons.append(reason)

    return reasons, emit_resync


async def test_stream_trimmed_emits_resync_and_skips_the_retained_backlog():
    redis = ContinuityRedis(
        [
            ("5-0", field_with_event_id("evt-5")),
            ("9-0", field_with_event_id("evt-9")),
        ]
    )
    emitted, emit = recording_emit()
    reasons, emit_resync = recording_resync()
    state = RelayState(position="1-1", run_id="run-1", started=True)

    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-1")

    assert reasons == ["STREAM_TRIMMED"]
    assert emitted == []
    assert redis.xread_calls == []
    assert state.position == "9-0"


async def test_changed_run_id_emits_redis_reset_and_jumps_to_the_tail():
    redis = ContinuityRedis(
        [
            ("1-0", field_with_event_id("evt-1")),
            ("2-0", field_with_event_id("evt-2")),
        ]
    )
    emitted, emit = recording_emit()
    reasons, emit_resync = recording_resync()
    state = RelayState(position="1-0", run_id="run-1", started=True)

    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-2")

    assert reasons == ["REDIS_RESET"]
    assert state.position == "2-0"
    assert state.run_id == "run-2"
    assert emitted == []
    assert redis.xread_calls == []


async def test_position_beyond_the_last_entry_emits_redis_reset():
    redis = ContinuityRedis(
        [
            ("1-0", field_with_event_id("evt-1")),
            ("9-0", field_with_event_id("evt-9")),
        ]
    )
    emitted, emit = recording_emit()
    reasons, emit_resync = recording_resync()
    state = RelayState(position="12-0", run_id="run-1", started=True)

    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-1")

    assert reasons == ["REDIS_RESET"]
    assert state.position == "9-0"
    assert redis.xread_calls == []


async def test_empty_stream_with_a_previous_position_emits_redis_reset():
    redis = ContinuityRedis([])
    emitted, emit = recording_emit()
    reasons, emit_resync = recording_resync()
    state = RelayState(position="9-0", run_id="run-1", started=True)

    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-1")

    assert reasons == ["REDIS_RESET"]
    assert state.position is None
    assert redis.xread_calls == []

    # Sin posición previa, el siguiente ciclo no vuelve a emitir y lee desde 0-0.
    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-1")

    assert reasons == ["REDIS_RESET"]
    assert redis.xread_calls == ["0-0"]


async def test_the_resync_emission_does_not_retrigger_on_the_next_cycle():
    redis = ContinuityRedis(
        [
            ("5-0", field_with_event_id("evt-5")),
            ("9-0", field_with_event_id("evt-9")),
        ]
    )
    emitted, emit = recording_emit()
    reasons, emit_resync = recording_resync()
    state = RelayState(position="1-0", run_id="run-1", started=True)

    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-1")
    assert reasons == ["STREAM_TRIMMED"]
    assert state.position == "9-0"

    await relay_cycle(redis, state, emit, emit_resync, current_run_id="run-1")

    assert reasons == ["STREAM_TRIMMED"]
    assert state.position == "9-0"
    assert redis.xread_calls == ["9-0"]
    assert emitted == []


async def test_missing_run_id_falls_back_to_the_position_checks():
    redis = NoInfoRedis(
        [
            ("5-0", field_with_event_id("evt-5")),
            ("9-0", field_with_event_id("evt-9")),
        ]
    )
    reasons, emit_resync = recording_resync()
    state = RelayState(position="1-0", run_id="run-1", started=True)
    emitted, emit = recording_emit()

    assert await read_run_id(redis) is None

    await relay_cycle(redis, state, emit, emit_resync, current_run_id=None)

    assert reasons == ["STREAM_TRIMMED"]
    assert state.position == "9-0"
    assert state.run_id == "run-1"


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({"run_id": "run-1"}, "run-1"),
        ("run_id:run-2\nredis_version:8.0.0\n", "run-2"),
        ({"run_id": None}, None),
        ({"run_id": 123}, None),
        ({}, None),
        ("redis_version:8.0.0\n", None),
        (None, None),
    ],
)
def test_parse_run_id_tolerates_missing_or_malformed_info(info, expected):
    assert parse_run_id(info) == expected


async def test_read_run_id_returns_none_when_info_has_no_run_id():
    redis = ContinuityRedis([], info={"redis_version": "8.0.0"})

    assert await read_run_id(redis) is None
    assert redis.info_calls == 1
