import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError
from starlette.requests import Request

from app.main import _request_validation_exception_handler
from app.modules.matches import live_schemas as schemas
from app.modules.matches.schemas import EVENT_TYPES, MatchEventPayload


COMMAND, SEGMENT, EVENT, TEAM, PLAYER = (uuid4() for _ in range(5))


def command(kind="start", **body):
    return {"type": kind, "command_id": str(COMMAND), "expected_revision": 0, **body}


def event_payload(kind="goal", **changes):
    return {
        "client_event_id": str(EVENT), "event_type": kind,
        "team_id": str(TEAM), "player_id": str(PLAYER),
        "minute": 0, "segment_id": str(SEGMENT), **changes,
    }


@pytest.mark.parametrize("kind, body", [
    ("start", {}), ("suspend", {}), ("resume", {}), ("pause_clock", {}), ("resume_clock", {}),
    ("start_clock", {"segment_id": str(SEGMENT)}),
    ("correct_clock", {"segment_id": str(SEGMENT), "elapsed_us": 1_234_567}),
    ("add_event", {"event": event_payload()}),
    ("correct_event", {"event_id": str(EVENT), "event": event_payload(minute=1)}),
    ("remove_event", {"event_id": str(EVENT)}),
])
def test_command_closed_union_round_trip(kind, body):
    parsed = TypeAdapter(schemas.LiveCommand).validate_python(command(kind, **body))
    assert parsed.type == kind
    assert parsed.command_id == COMMAND
    assert parsed.expected_revision == 0


@pytest.mark.parametrize("payload", [
    {}, {"type": "start"}, command("unknown"), command(command_id="bad"),
    command(expected_revision=-1), command(expected_revision=True), command(expected_revision="1"),
    command("start", segment_id=str(SEGMENT)), command("pause_clock", elapsed_us=0),
    command("start_clock"), command("correct_clock", segment_id=str(SEGMENT)),
    command("correct_clock", segment_id=str(SEGMENT), elapsed_us=-1),
    command("correct_clock", segment_id=str(SEGMENT), elapsed_us=1.5),
    command("add_event"), command("remove_event", event_id="bad"),
    command("remove_event", event_id=str(EVENT), event=event_payload()),
    command("correct_event", event_id=str(EVENT)), command(untrusted="secret-probe"),
])
def test_command_rejects_empty_extra_and_incompatible_fields(payload):
    with pytest.raises(ValidationError):
        TypeAdapter(schemas.LiveCommand).validate_python(payload)


def test_command_capabilities_and_ack_are_minimal_and_strict():
    access = schemas.LiveAccessResponse(can_view=False, can_operate=True, can_close=False, available=True)
    assert set(access.model_dump()) == {"can_view", "can_operate", "can_close", "available"}
    ack = schemas.LiveCommandAck(command_id=COMMAND, revision=1)
    assert set(ack.model_dump()) == {"command_id", "revision"}
    for model, payload in [
        (schemas.LiveAccessResponse, {**access.model_dump(), "events": []}),
        (schemas.LiveAccessResponse, {**access.model_dump(), "can_view": 1}),
        (schemas.LiveCommandAck, {**ack.model_dump(), "revision": True}),
    ]:
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.asyncio
async def test_command_uses_existing_sanitized_422_handler_without_a_router():
    with pytest.raises(ValidationError) as caught:
        TypeAdapter(schemas.LiveCommand).validate_python(command(expected_revision="secret-probe"))
    response = await _request_validation_exception_handler(
        Request({"type": "http", "path": "/test-only", "headers": []}),
        RequestValidationError(caught.value.errors()),
    )
    assert response.status_code == 422
    assert "secret-probe" not in response.body.decode()
    assert all(set(error) == {"type", "loc", "msg"} for error in json.loads(response.body)["detail"])


def report(**changes):
    return {"resolution_type": "regular", "home_score_regular": 0, "away_score_regular": 0, **changes}


@pytest.mark.parametrize("kind", EVENT_TYPES)
def test_report_reuses_full_event_catalog_and_payload(kind):
    changes = {}
    if kind == "own_goal":
        changes["beneficiary_team_id"] = str(uuid4())
    if kind == "substitution":
        changes.update(player_out_id=str(PLAYER), player_in_id=str(uuid4()))
    payload = event_payload(kind, **changes)
    dto = schemas.LiveReportDTO.model_validate(report(events=[payload]))
    assert isinstance(dto.events[0], MatchEventPayload)
    assert dto.events[0].event_type == kind


def test_report_normalizes_identity_and_rejects_duplicates():
    payload = event_payload(client_event_id=str(EVENT).upper())
    dto = schemas.LiveReportDTO.model_validate(report(events=[payload]))
    assert dto.events[0].client_event_id == str(EVENT)
    with pytest.raises(ValidationError):
        schemas.LiveReportDTO.model_validate(report(events=[payload, event_payload()]))


@pytest.mark.parametrize("count", [0, 500])
def test_report_accepts_empty_and_maximum_draft(count):
    events = [event_payload(client_event_id=str(uuid4())) for _ in range(count)]
    assert len(schemas.LiveReportDTO.model_validate(report(events=events)).events) == count


@pytest.mark.parametrize("changes", [
    {"events": [event_payload(client_event_id=str(uuid4())) for _ in range(501)]},
    {"events": [event_payload(metadata={"private-probe": "secret"})]},
    {"events": [event_payload("shootout_goal")]}, {"public_events": []},
])
def test_report_rejects_oversize_unknown_metadata_and_f13(changes):
    with pytest.raises(ValidationError):
        schemas.LiveReportDTO.model_validate(report(**changes))


def test_report_review_and_close_contracts_require_receipt_without_client_events():
    review = schemas.LiveReviewRequest(expected_content_revision=1, result=report())
    assert review.expected_content_revision == 1
    close = schemas.LiveCloseRequest(live_review_id=EVENT, result=report())
    assert close.live_review_id == EVENT
    for model, payload in [
        (schemas.LiveCloseRequest, {"result": report()}),
        (schemas.LiveCloseRequest, {"live_review_id": "bad", "result": report()}),
        (schemas.LiveCloseRequest, {"live_review_id": EVENT, "match_id": TEAM, "result": report()}),
        (schemas.LiveCloseRequest, {"live_review_id": EVENT, "result": report(events=[])}),
        (schemas.LiveReviewRequest, {"expected_content_revision": 0, "result": report(events=[event_payload()])}),
    ]:
        with pytest.raises(ValidationError):
            model.model_validate(payload)


def test_report_close_contract_round_trip_does_not_send_empty_client_events():
    dto = schemas.LiveCloseRequest(live_review_id=EVENT, result=report())
    assert "events" not in dto.model_dump(mode="json")["result"]
    assert schemas.LiveCloseRequest.model_validate_json(dto.model_dump_json()) == dto


def test_command_snapshot_read_contract_has_explicit_uninitialized_state():
    snapshot = schemas.LiveSnapshotResponse(initialized=False, status="scheduled")
    assert snapshot.events == []
    assert snapshot.revision is None
    assert snapshot.content_revision is None
    assert snapshot.home_score is None and snapshot.away_score is None
    assert snapshot.clock is None


def initialized_snapshot():
    return {
        "initialized": True, "status": "live", "revision": 1, "content_revision": 0,
        "events": [], "home_score": 0, "away_score": 0,
        "clock": {"state": "not_started", "observed_at": datetime(2026, 11, 13, tzinfo=timezone.utc)},
    }


def test_command_snapshot_read_contract_accepts_initialized_empty_draft():
    snapshot = schemas.LiveSnapshotResponse.model_validate(initialized_snapshot())
    assert snapshot.events == []
    assert snapshot.clock.state == "not_started"
    assert schemas.LiveSnapshotResponse.model_validate_json(snapshot.model_dump_json()) == snapshot


@pytest.mark.parametrize("changes", [
    {"initialized": False}, {"initialized": "true"}, {"revision": None}, {"home_score": -1},
    {"events": [], "unknown": "secret-probe"},
    {"clock": {"state": "running", "observed_at": "2026-11-13T00:00:00Z"}},
    {"clock": {"state": "not_started", "observed_at": "2026-11-13T00:00:00"}},
    {"status": "suspended", "clock": {"state": "running", "segment_id": str(SEGMENT), "segment_number": 1, "elapsed_us": 0, "anchor_at": "2026-11-13T00:00:00Z", "observed_at": "2026-11-13T00:00:00Z"}},
])
def test_command_snapshot_read_contract_rejects_inconsistent_or_extra_data(changes):
    with pytest.raises(ValidationError):
        schemas.LiveSnapshotResponse.model_validate({**initialized_snapshot(), **changes})


@pytest.mark.parametrize("running", [False, True])
def test_command_snapshot_read_contract_preserves_clock_reference(running):
    at = "2026-11-13T00:00:00Z"
    clock = {"state": "running" if running else "paused", "segment_id": str(SEGMENT), "segment_number": 1, "elapsed_us": 1_234_567, "anchor_at": at if running else None, "observed_at": at}
    snapshot = schemas.LiveSnapshotResponse.model_validate({**initialized_snapshot(), "clock": clock})
    assert snapshot.clock.segment_id == SEGMENT
    assert snapshot.clock.elapsed_us == 1_234_567


@pytest.mark.parametrize("clock", [
    {"state": "not_started", "segment_id": str(SEGMENT)},
    {"state": "paused", "segment_id": str(SEGMENT), "segment_number": 1, "elapsed_us": 0, "anchor_at": "2026-11-13T00:00:00Z"},
    {"state": "paused", "segment_id": str(SEGMENT), "segment_number": 0, "elapsed_us": 0},
    {"state": "not_started", "observed_at": "2026-11-13T00:00:00+01:00"},
])
def test_command_clock_read_contract_rejects_invalid_reference(clock):
    with pytest.raises(ValidationError):
        schemas.LiveClockResponse.model_validate({"observed_at": "2026-11-13T00:00:00Z", **clock})
