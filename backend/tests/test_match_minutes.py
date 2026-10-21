"""Effective match minutes from ``rules_config`` (T008, RF-040/042/043/045/048).

Pure helpers plus doubles for the three entry points that need the effective
maximum: the closing validation, ``POST /segments`` and ``interrupt``, and the
``GET /operation`` limits block. No PostgreSQL is required here; the opt-in
integration for the 40/100 boundary lives in ``test_substitutions.py``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.tenancy import AuthContext
from app.modules.matches import router as matches_router
from app.modules.matches.schemas import (
    CloseMatchReportDTO,
    CreateMatchSegmentRequest,
    InterruptMatchSegmentRequest,
    MatchEventPayload,
)
from app.modules.matches.service import (
    CloseMatchReportService,
    effective_match_minutes,
    maximum_minute_for_resolution,
    validate_event_minute,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG

ORGANIZATION_ID = UUID(int=8001)
USER_ID = UUID(int=8002)
MEMBER_ID = UUID(int=8003)
TOURNAMENT_ID = UUID(int=8100)
STAGE_ID = UUID(int=8101)
OTHER_STAGE_ID = UUID(int=8102)
MATCH_ID = UUID(int=8103)
SEGMENT_1 = UUID(int=8104)
HOME = UUID(int=8200)
AWAY = UUID(int=8201)
PLAYER = UUID(int=8300)
MATCH_DATE = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def rules_config(
    *,
    regular: int = 90,
    extra: int = 120,
    extra_time_enabled: bool = False,
    stage_overrides: dict | None = None,
) -> dict:
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"].update(
        {
            "regular_time_minutes": regular,
            "extra_time_minutes": extra,
            "extra_time_enabled": extra_time_enabled,
        }
    )
    config["stage_overrides"] = stage_overrides or {}
    return config


def goal_event(minute: int, *, added_minute: int = 0) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=f"goal-{minute}-{added_minute}",
        event_type="goal",
        team_id=HOME,
        player_id=PLAYER,
        minute=minute,
        added_minute=added_minute,
        segment_id=SEGMENT_1,
    )


# ---------------------------------------------------------------------------
# Effective limits
# ---------------------------------------------------------------------------


def test_a_320_config_without_minutes_reads_the_default_pair():
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["schema_version"] = "3.2.0"
    config["stage_defaults"].pop("regular_time_minutes", None)
    config["stage_defaults"].pop("extra_time_minutes", None)
    config["stage_defaults"]["extra_time_enabled"] = False

    limits = effective_match_minutes(config, None)

    assert limits["regular_time_minutes"] == 90
    assert limits["extra_time_minutes"] == 120
    # Extra time is disabled, so the possible maximum is the regular time.
    assert limits["max_minute"] == 90
    assert limits["added_minute_max"] == 30


def test_extra_time_enabled_raises_the_possible_maximum_to_the_extra_time():
    limits = effective_match_minutes(
        rules_config(regular=40, extra=100, extra_time_enabled=True), None
    )

    assert limits["regular_time_minutes"] == 40
    assert limits["extra_time_minutes"] == 100
    assert limits["max_minute"] == 100


def test_stage_override_changes_both_minutes_for_that_stage_only():
    config = rules_config(
        regular=90,
        extra=120,
        extra_time_enabled=True,
        stage_overrides={
            str(STAGE_ID): {
                "regular_time_minutes": 40,
                "extra_time_minutes": 100,
            }
        },
    )

    overridden = effective_match_minutes(config, STAGE_ID)
    other = effective_match_minutes(config, OTHER_STAGE_ID)

    assert (overridden["regular_time_minutes"], overridden["extra_time_minutes"]) == (40, 100)
    assert overridden["max_minute"] == 100
    assert (other["regular_time_minutes"], other["extra_time_minutes"]) == (90, 120)
    assert other["max_minute"] == 120


def test_a_partial_override_only_changes_the_declared_key():
    config = rules_config(
        regular=90,
        extra=120,
        extra_time_enabled=True,
        stage_overrides={str(STAGE_ID): {"extra_time_minutes": 130}},
    )

    limits = effective_match_minutes(config, STAGE_ID)

    assert limits["regular_time_minutes"] == 90
    assert limits["extra_time_minutes"] == 130
    assert limits["max_minute"] == 130


def test_the_resolution_maximum_uses_extra_time_only_when_it_is_needed_and_enabled():
    enabled = effective_match_minutes(
        rules_config(regular=40, extra=100, extra_time_enabled=True), None
    )
    disabled = effective_match_minutes(
        rules_config(regular=40, extra=100, extra_time_enabled=False), None
    )

    assert maximum_minute_for_resolution(enabled, "regular") == 40
    assert maximum_minute_for_resolution(enabled, "extra_time") == 100
    assert maximum_minute_for_resolution(enabled, "penalties") == 100
    assert maximum_minute_for_resolution(disabled, "regular") == 40
    assert maximum_minute_for_resolution(disabled, "extra_time") == 40
    assert maximum_minute_for_resolution(disabled, "penalties") == 40


# ---------------------------------------------------------------------------
# minute + added_minute
# ---------------------------------------------------------------------------


def test_ninety_plus_two_is_valid_in_the_final_minute():
    validate_event_minute(90, 2, maximum=90)
    validate_event_minute(120, 2, maximum=120)


def test_eighty_nine_plus_thirty_exceeds_the_regular_maximum():
    with pytest.raises(ValueError, match="máximo de 90"):
        validate_event_minute(89, 30, maximum=90)


def test_120_plus_31_is_rejected_structurally_before_the_handler():
    with pytest.raises(ValidationError):
        goal_event(120, added_minute=31)


def test_an_event_beyond_the_effective_maximum_is_rejected():
    with pytest.raises(ValueError, match="máximo de 100"):
        validate_event_minute(101, 0, maximum=100)
    with pytest.raises(ValueError, match="máximo de 40"):
        validate_event_minute(50, 0, maximum=40)


def test_a_regular_time_match_does_not_admit_extra_time_minutes():
    limits = effective_match_minutes(
        rules_config(regular=90, extra=120, extra_time_enabled=False), None
    )

    with pytest.raises(ValueError, match="máximo de 90"):
        validate_event_minute(95, 0, maximum=maximum_minute_for_resolution(limits, "regular"))
    with pytest.raises(ValueError, match="máximo de 90"):
        validate_event_minute(
            95, 0, maximum=maximum_minute_for_resolution(limits, "extra_time")
        )


# ---------------------------------------------------------------------------
# Regular/extra-time goal boundary
# ---------------------------------------------------------------------------


def test_a_goal_in_minute_50_is_extra_time_with_40_100():
    report = CloseMatchReportDTO(
        resolution_type="extra_time",
        home_score_regular=0,
        away_score_regular=0,
        home_score=1,
        away_score=0,
        winner_team_id=HOME,
        events=[goal_event(50)],
    )

    CloseMatchReportService._validate_event_score_consistency(
        report, HOME, AWAY, regular_time_minutes=40
    )


def test_a_goal_in_minute_50_is_regular_with_90_120():
    regular_report = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=1,
        away_score_regular=0,
        events=[goal_event(50)],
    )
    CloseMatchReportService._validate_event_score_consistency(
        regular_report, HOME, AWAY, regular_time_minutes=90
    )

    # With a 40-minute regular time the same goal is extra time, so it can no
    # longer feed the regular score.
    mismatched_report = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=1,
        away_score_regular=0,
        events=[goal_event(50)],
    )
    with pytest.raises(ValueError, match="no coincide"):
        CloseMatchReportService._validate_event_score_consistency(
            mismatched_report, HOME, AWAY, regular_time_minutes=40
        )


# ---------------------------------------------------------------------------
# Closing validation (doubles)
# ---------------------------------------------------------------------------


def test_closing_accepts_segment_95_with_extra_time_and_rejects_it_without():
    segments = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 95,
            "minute_end": None,
            "status": "active",
        }
    ]
    dto = SimpleNamespace(resolution_type="extra_time", events=[])
    enabled = effective_match_minutes(
        rules_config(regular=90, extra=120, extra_time_enabled=True), None
    )
    disabled = effective_match_minutes(
        rules_config(regular=90, extra=120, extra_time_enabled=False), None
    )

    CloseMatchReportService._validate_segments(dto, segments, enabled)

    with pytest.raises(ValueError, match="máximo de 90"):
        CloseMatchReportService._validate_segments(dto, segments, disabled)


def test_closing_rejects_an_event_whose_minute_plus_added_exceeds_the_maximum():
    segments = [
        {
            "id": SEGMENT_1,
            "segment_number": 1,
            "minute_start": 0,
            "minute_end": None,
            "status": "active",
        }
    ]
    minutes = effective_match_minutes(
        rules_config(regular=90, extra=120, extra_time_enabled=False), None
    )
    dto = SimpleNamespace(resolution_type="regular", events=[goal_event(89, added_minute=30)])
    with pytest.raises(ValueError, match="máximo de 90"):
        CloseMatchReportService._validate_segments(dto, segments, minutes)

    dto_ok = SimpleNamespace(resolution_type="regular", events=[goal_event(90, added_minute=2)])
    CloseMatchReportService._validate_segments(dto_ok, segments, minutes)


# ---------------------------------------------------------------------------
# POST /segments and interrupt (doubles)
# ---------------------------------------------------------------------------


class Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RecordingSession:
    def __init__(self):
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def begin(self):
        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    @property
    def writes(self) -> list[str]:
        return [
            sql for sql in self.statements
            if sql.upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]


def _loader(match: dict):
    async def load(db, context_, match_id, require_operation_permission=True, lock=True):
        return match

    return load


def _match(config: dict) -> dict:
    return {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "stage_id": STAGE_ID,
        "status": "scheduled",
        "home_team_id": HOME,
        "away_team_id": AWAY,
        "rules_config": config,
    }


def _segment_session() -> RecordingSession:
    session = RecordingSession()

    def handle(sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "ORDER BY segment_number DESC" in sql:
            return Result(rows=[])
        if "FROM match_segments" in sql and "status = 'active'" in sql:
            return Result(rows=[])
        if sql.startswith("INSERT INTO match_segments"):
            return Result(
                rows=[
                    {
                        "id": SEGMENT_1,
                        "segment_number": params["segment_number"],
                        "minute_start": params["minute_start"],
                        "minute_end": None,
                        "status": "active",
                    }
                ]
            )
        if sql.startswith("INSERT INTO match_segment_team_state"):
            return Result()
        raise AssertionError(f"consulta no esperada: {sql}")

    session.handle = handle
    return session


@pytest.mark.asyncio
async def test_the_segment_route_accepts_minute_95_with_extra_time(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(
            _match(rules_config(regular=90, extra=120, extra_time_enabled=True))
        ),
    )
    session = _segment_session()

    response = await matches_router.create_match_segment(
        MATCH_ID,
        CreateMatchSegmentRequest(segment_number=1, minute_start=95),
        context(),
        session,
    )

    assert response["minute_start"] == 95


@pytest.mark.asyncio
async def test_the_segment_route_rejects_minute_95_without_extra_time(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(
            _match(rules_config(regular=90, extra=120, extra_time_enabled=False))
        ),
    )
    session = _segment_session()

    with pytest.raises(HTTPException) as error:
        await matches_router.create_match_segment(
            MATCH_ID,
            CreateMatchSegmentRequest(segment_number=1, minute_start=95),
            context(),
            session,
        )

    assert error.value.status_code == 422
    assert "máximo de 90" in error.value.detail
    assert not any(sql.startswith("INSERT INTO") for sql in session.statements)


def _interrupt_session() -> RecordingSession:
    session = RecordingSession()

    def handle(sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "FROM match_segments" in sql:
            return Result(rows=[{"id": SEGMENT_1, "minute_start": 0, "status": "active"}])
        if sql.startswith("INSERT INTO match_segment_interruptions"):
            return Result(
                rows=[
                    {
                        "id": UUID(int=8400),
                        "match_id": MATCH_ID,
                        "segment_id": SEGMENT_1,
                        "reason": params["reason"],
                        "minute": params["minute"],
                        "notes": params["notes"],
                        "created_at": MATCH_DATE,
                    }
                ]
            )
        if sql.startswith("UPDATE match_segments"):
            return Result()
        if sql.startswith("INSERT INTO administrative_audit_logs"):
            return Result()
        raise AssertionError(f"consulta no esperada: {sql}")

    session.handle = handle
    return session


@pytest.mark.asyncio
async def test_an_interruption_beyond_the_maximum_is_rejected(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(
            _match(rules_config(regular=90, extra=120, extra_time_enabled=True))
        ),
    )
    session = _interrupt_session()

    with pytest.raises(HTTPException) as error:
        await matches_router.interrupt_match_segment(
            MATCH_ID,
            SEGMENT_1,
            InterruptMatchSegmentRequest(reason="weather", minute=125),
            context(),
            session,
        )

    assert error.value.status_code == 422
    assert "máximo de 120" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_an_interruption_within_the_maximum_is_recorded(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(
            _match(rules_config(regular=90, extra=120, extra_time_enabled=True))
        ),
    )
    session = _interrupt_session()

    response = await matches_router.interrupt_match_segment(
        MATCH_ID,
        SEGMENT_1,
        InterruptMatchSegmentRequest(reason="weather", minute=118),
        context(),
        session,
    )

    assert response["minute"] == 118


# ---------------------------------------------------------------------------
# GET /operation limits (double)
# ---------------------------------------------------------------------------


def _operation_session() -> RecordingSession:
    session = RecordingSession()

    def handle(sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "FROM match_segments" in sql:
            return Result(rows=[])
        if "FROM match_officials" in sql:
            return Result(rows=[])
        if "FROM organization_users ou" in sql:
            return Result(rows=[])
        if "FROM match_segment_interruptions" in sql:
            return Result(rows=[])
        if "FROM rosters r" in sql:
            return Result(rows=[])
        if "FROM match_events me" in sql:
            return Result(rows=[])
        raise AssertionError(f"consulta no esperada: {sql}")

    session.handle = handle
    return session


@pytest.mark.asyncio
async def test_operation_exposes_the_effective_limits_with_the_stage_override(monkeypatch):
    config = rules_config(
        regular=90,
        extra=120,
        extra_time_enabled=True,
        stage_overrides={
            str(STAGE_ID): {
                "regular_time_minutes": 40,
                "extra_time_minutes": 100,
            }
        },
    )

    async def fake_lineup(db, organization_id, match_id):
        return []

    async def fake_tactical(db, organization_id, match_id):
        return []

    monkeypatch.setattr(matches_router, "_load_operation_match", _loader(_match(config)))
    monkeypatch.setattr(matches_router, "_load_match_lineup", fake_lineup)
    monkeypatch.setattr(matches_router, "_load_match_tactical_lineups", fake_tactical)
    session = _operation_session()

    response = await matches_router.get_match_operation(MATCH_ID, context(), session)

    assert session.writes == []
    assert response["limits"] == {
        "regular_time_minutes": 40,
        "extra_time_minutes": 100,
        "max_minute": 100,
        "added_minute_max": 30,
    }
