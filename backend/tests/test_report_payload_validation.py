"""The closing report's pure validation contract and immutable loaded inputs."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from itertools import combinations

from fastapi import HTTPException
import pytest

from app.modules.matches import service as match_service
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.matches.service import (
    ReportPayloadSnapshot, load_report_payload_snapshot, validate_report_payload,
)
from test_close_validation_order import (
    DECLARED_STEPS, build_report, build_session, base_state, context,
)

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
PAYLOAD_DEFECTS = [(step, defect) for step, _, defect in DECLARED_STEPS if step >= 5]


def proposed_report(*defects):
    state = base_state()
    expected = [defect(state) for defect in defects]
    session = build_session(state)
    snapshot = ReportPayloadSnapshot(
        match=session.match,
        rosters=session.rosters,
        segments=session.segments,
        known_team_ids=frozenset(session.teams),
        has_suspended_players=session.suspended,
        require_active_segment=True,
        active_segment_id=session.segments[0]["id"] if session.active_segment_available else None,
    )
    return snapshot, build_report(state), expected


def assert_rejection(snapshot, payload, expected):
    before = payload.model_dump()
    with pytest.raises((ValueError, LookupError, HTTPException)) as caught:
        validate_report_payload(snapshot, payload, NOW)
    error = caught.value
    status = error.status_code if isinstance(error, HTTPException) else 404 if isinstance(error, LookupError) else 409
    code = getattr(error, "code", None) if isinstance(error, HTTPException) else None
    assert (status, code) == (expected.status, expected.code)
    assert expected.fragment in str(error.detail if isinstance(error, HTTPException) else error)
    assert payload.model_dump() == before


@pytest.mark.parametrize("defect", [defect for _, defect in PAYLOAD_DEFECTS], ids=lambda defect: defect.__name__)
def test_current_close_rejections_keep_their_codes(defect):
    snapshot, payload, expected = proposed_report(defect)
    assert_rejection(snapshot, payload, expected[0])


@pytest.mark.parametrize("earlier,later", [
    (first, second) for (step1, first), (step2, second) in combinations(PAYLOAD_DEFECTS, 2)
    if step1 < step2
], ids=lambda defect: defect.__name__)
def test_payload_validation_keeps_the_close_precedence(earlier, later):
    snapshot, payload, expected = proposed_report(earlier, later)
    assert_rejection(snapshot, payload, expected[0])


def test_valid_empty_report_is_deterministic_and_does_not_mutate_inputs():
    snapshot, payload, _ = proposed_report()
    before = payload.model_dump()
    outcome = validate_report_payload(snapshot, payload, NOW)
    assert (outcome.home_score, outcome.away_score, outcome.winner_team_id) == (0, 0, None)
    assert validate_report_payload(snapshot, payload, NOW.replace(year=2040)) == outcome
    assert payload.model_dump() == before


def test_snapshot_is_deeply_immutable_and_detached_from_loaded_rows():
    state = base_state()
    session = build_session(state)
    snapshot = ReportPayloadSnapshot(session.match, session.rosters, session.segments)
    session.match["rules_config"]["stage_defaults"]["extra_time_enabled"] = True
    assert snapshot.match["rules_config"]["stage_defaults"]["extra_time_enabled"] is False
    with pytest.raises(FrozenInstanceError):
        snapshot.match = {}
    with pytest.raises(TypeError):
        snapshot.match["rules_config"]["stage_defaults"]["extra_time_enabled"] = True
    with pytest.raises(TypeError):
        snapshot.rosters[0]["is_active"] = False
    with pytest.raises(TypeError):
        snapshot.segments[0]["status"] = "interrupted"


def test_validator_never_reads_the_clock(monkeypatch):
    snapshot, payload, _ = proposed_report()
    monkeypatch.setattr(match_service, "datetime", None)
    assert validate_report_payload(snapshot, payload, NOW).home_score == 0


def test_walkover_reuses_the_derived_score_without_rosters_or_segments():
    snapshot, _, _ = proposed_report()
    payload = CloseMatchReportDTO(
        resolution_type="walkover", winner_team_id=snapshot.match["home_team_id"], reason="no_show"
    )
    snapshot = ReportPayloadSnapshot(snapshot.match, (), ())
    outcome = validate_report_payload(snapshot, payload, NOW)
    assert (outcome.home_score, outcome.away_score) == (3, 0)


@pytest.mark.asyncio
async def test_snapshot_loader_only_reads_and_takes_no_locks():
    state = base_state()
    session = build_session(state)
    snapshot = await load_report_payload_snapshot(session, context(), session.match, build_report(state))
    assert snapshot.rosters == tuple(session.rosters)
    assert snapshot.segments == tuple(session.segments)
    assert session.writes == []
    assert not any("FOR UPDATE" in sql or "pg_advisory" in sql for sql in session.statements)
