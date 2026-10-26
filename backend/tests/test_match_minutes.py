"""Effective match minutes from ``rules_config`` (T008, RF-040/042/043/045/048).

Pure helpers plus doubles for the three entry points that need the effective
maximum: the closing validation, ``POST /segments`` and ``interrupt``, and the
``GET /operation`` limits block. No PostgreSQL is required here; the opt-in
integration for the 40/100 boundary lives in ``test_substitutions.py``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.matches import router as matches_router
from app.modules.matches.errors import (
    RESOLUTION_NOT_ENABLED,
    RESOLUTION_NOT_ENABLED_DETAIL,
    ResolutionNotEnabled,
    resolution_not_enabled_body,
)
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
    resolution_enabled,
    validate_event_minute,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from tests.event_ids import event_id

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
    penalties_enabled: bool = False,
    stage_overrides: dict | None = None,
) -> dict:
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"].update(
        {
            "regular_time_minutes": regular,
            "extra_time_minutes": extra,
            "extra_time_enabled": extra_time_enabled,
            "penalties_enabled": penalties_enabled,
        }
    )
    config["stage_overrides"] = stage_overrides or {}
    return config


def goal_event(minute: int, *, added_minute: int = 0) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id(f"goal-{minute}-{added_minute}"),
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
# Resolution enabled by the effective stage configuration (P5, RF-032)
# ---------------------------------------------------------------------------


def test_resolution_enabled_always_admits_regular_walkover_and_administrative():
    minutes = effective_match_minutes(
        rules_config(extra_time_enabled=False, penalties_enabled=False), None
    )

    assert resolution_enabled(minutes, "regular") is True
    assert resolution_enabled(minutes, "walkover") is True
    assert resolution_enabled(minutes, "administrative") is True


def test_resolution_enabled_follows_the_effective_extra_time_flag():
    enabled = effective_match_minutes(rules_config(extra_time_enabled=True), None)
    disabled = effective_match_minutes(rules_config(extra_time_enabled=False), None)

    assert resolution_enabled(enabled, "extra_time") is True
    assert resolution_enabled(disabled, "extra_time") is False


def test_resolution_enabled_follows_the_effective_penalties_flag():
    enabled = effective_match_minutes(rules_config(penalties_enabled=True), None)
    disabled = effective_match_minutes(rules_config(penalties_enabled=False), None)

    # Penalties depend on their own flag, never on the extra time one.
    assert resolution_enabled(enabled, "penalties") is True
    assert resolution_enabled(disabled, "penalties") is False


def test_resolution_enabled_reads_the_stage_override_not_the_version_defaults():
    config = rules_config(
        extra_time_enabled=False,
        stage_overrides={str(STAGE_ID): {"extra_time_enabled": True}},
    )

    overridden = effective_match_minutes(config, STAGE_ID)
    inherited = effective_match_minutes(config, OTHER_STAGE_ID)

    assert resolution_enabled(overridden, "extra_time") is True
    assert resolution_enabled(inherited, "extra_time") is False


def test_the_unified_resolution_error_is_a_409_with_a_stable_code():
    error = ResolutionNotEnabled()

    assert error.status_code == 409
    assert error.code == RESOLUTION_NOT_ENABLED
    assert resolution_not_enabled_body(error) == {
        "detail": RESOLUTION_NOT_ENABLED_DETAIL,
        "code": RESOLUTION_NOT_ENABLED,
    }


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
        "max_minute_regular": 40,
        "max_minute_extra": 100,
        "extra_time_enabled": True,
        "penalties_enabled": False,
        # spec 016 (RF-005): la pareja efectiva del walkover, aditiva.
        "walkover_score": {"winner": 3, "loser": 0},
    }


async def _operation_limits(monkeypatch, config: dict) -> dict:
    async def fake_lineup(db, organization_id, match_id):
        return []

    async def fake_tactical(db, organization_id, match_id):
        return []

    monkeypatch.setattr(matches_router, "_load_operation_match", _loader(_match(config)))
    monkeypatch.setattr(matches_router, "_load_match_lineup", fake_lineup)
    monkeypatch.setattr(matches_router, "_load_match_tactical_lineups", fake_tactical)

    response = await matches_router.get_match_operation(
        MATCH_ID, context(), _operation_session()
    )
    return response["limits"]


@pytest.mark.asyncio
async def test_operation_limits_add_the_new_fields_with_the_read_defaults(monkeypatch):
    limits = await _operation_limits(monkeypatch, rules_config())

    # The four legacy fields keep their exact meaning.
    assert limits["regular_time_minutes"] == 90
    assert limits["extra_time_minutes"] == 120
    assert limits["max_minute"] == 90
    assert limits["added_minute_max"] == 30
    # The additive fields resolve the same effective configuration.
    assert limits["max_minute_regular"] == 90
    assert limits["max_minute_extra"] is None
    assert limits["extra_time_enabled"] is False
    assert limits["penalties_enabled"] is False


@pytest.mark.asyncio
async def test_operation_limits_resolve_the_stage_override_and_its_flags(monkeypatch):
    config = rules_config(
        regular=90,
        extra=120,
        extra_time_enabled=True,
        penalties_enabled=True,
        stage_overrides={
            str(STAGE_ID): {
                "regular_time_minutes": 40,
                "extra_time_minutes": 100,
            }
        },
    )

    limits = await _operation_limits(monkeypatch, config)

    assert limits["regular_time_minutes"] == 40
    assert limits["extra_time_minutes"] == 100
    assert limits["max_minute"] == 100
    assert limits["max_minute_regular"] == 40
    assert limits["max_minute_extra"] == 100
    assert limits["extra_time_enabled"] is True
    assert limits["penalties_enabled"] is True


@pytest.mark.asyncio
async def test_operation_limits_null_the_extra_maximum_when_the_stage_disables_it(monkeypatch):
    config = rules_config(
        regular=90,
        extra=120,
        extra_time_enabled=True,
        stage_overrides={str(STAGE_ID): {"extra_time_enabled": False}},
    )

    limits = await _operation_limits(monkeypatch, config)

    assert limits["extra_time_minutes"] == 120
    assert limits["max_minute"] == 90
    assert limits["max_minute_regular"] == 90
    assert limits["max_minute_extra"] is None
    assert limits["extra_time_enabled"] is False


def test_effective_minutes_expose_penalties_enabled_per_stage():
    config = rules_config(
        penalties_enabled=True,
        stage_overrides={str(OTHER_STAGE_ID): {"penalties_enabled": False}},
    )

    assert effective_match_minutes(config, None)["penalties_enabled"] is True
    assert effective_match_minutes(config, STAGE_ID)["penalties_enabled"] is True
    assert effective_match_minutes(config, OTHER_STAGE_ID)["penalties_enabled"] is False


# ---------------------------------------------------------------------------
# Close route: unified 409 and the untouched structural 422 (P5, RF-032)
# ---------------------------------------------------------------------------


CLOSE_BODY = {
    "resolution_type": "extra_time",
    "home_score_regular": 0,
    "away_score_regular": 0,
    "home_score": 1,
    "away_score": 0,
    "winner_team_id": str(HOME),
}


@asynccontextmanager
async def close_client():
    """HTTP client over the real app with the session and identity overridden."""

    async def database():
        yield object()

    async def auth():
        return context()

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = auth
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_auth_context, None)


@pytest.mark.asyncio
async def test_the_close_route_answers_the_unified_409_with_its_code(monkeypatch):
    async def reject(self, context_, match_id, dto):
        raise ResolutionNotEnabled()

    monkeypatch.setattr(matches_router.CloseMatchReportService, "execute", reject)

    async with close_client() as client:
        response = await client.post(
            f"/api/v1/matches/{MATCH_ID}/close", json=CLOSE_BODY
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": RESOLUTION_NOT_ENABLED_DETAIL,
        "code": RESOLUTION_NOT_ENABLED,
    }


@pytest.mark.asyncio
async def test_the_close_route_still_rejects_an_out_of_range_minute_with_422(monkeypatch):
    called = False

    async def should_not_run(self, context_, match_id, dto):  # pragma: no cover
        nonlocal called
        called = True

    monkeypatch.setattr(matches_router.CloseMatchReportService, "execute", should_not_run)
    body = {
        **CLOSE_BODY,
        "events": [
            {
                "client_event_id": event_id("out-of-range"),
                "event_type": "goal",
                "team_id": str(HOME),
                "player_id": str(PLAYER),
                "minute": 181,
                "segment_id": str(SEGMENT_1),
            }
        ],
    }

    async with close_client() as client:
        response = await client.post(
            f"/api/v1/matches/{MATCH_ID}/close", json=body
        )

    assert response.status_code == 422
    assert called is False
    # The sanitized validation body never echoes the rejected input.
    assert "181" not in response.text


# ---------------------------------------------------------------------------
# Optional resolution in segments and interruptions (SG-1, P1, P5, RF-032)
# ---------------------------------------------------------------------------
#
# Orden de validación de las dos rutas (el mismo del cierre y del plan §3.3):
# sesión y organización → partido y estado → permiso de operación (dentro de
# ``_load_operation_match``) → resolución habilitada (409) → rango de minuto
# (422) → escritura.


@pytest.mark.asyncio
async def test_the_segment_route_without_resolution_keeps_the_stage_maximum(monkeypatch):
    """P1: sin el campo, el máximo es el de la fase y el resultado no cambia."""

    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(regular=90, extra=120, extra_time_enabled=True))),
    )

    without_field = await matches_router.create_match_segment(
        MATCH_ID,
        CreateMatchSegmentRequest(segment_number=1, minute_start=95),
        context(),
        _segment_session(),
    )

    assert without_field["minute_start"] == 95

    # El mismo minuto con la resolución prevista reglamentaria sale del máximo
    # de esa resolución: 422 de rango, sin escrituras.
    session = _segment_session()
    with pytest.raises(HTTPException) as error:
        await matches_router.create_match_segment(
            MATCH_ID,
            CreateMatchSegmentRequest(
                segment_number=1, minute_start=95, resolution_type="regular"
            ),
            context(),
            session,
        )

    assert error.value.status_code == 422
    assert "máximo de 90" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_the_segment_route_with_extra_time_resolution_uses_that_maximum(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(regular=90, extra=120, extra_time_enabled=True))),
    )

    accepted = await matches_router.create_match_segment(
        MATCH_ID,
        CreateMatchSegmentRequest(
            segment_number=1, minute_start=120, resolution_type="extra_time"
        ),
        context(),
        _segment_session(),
    )

    assert accepted["minute_start"] == 120

    session = _segment_session()
    with pytest.raises(HTTPException) as error:
        await matches_router.create_match_segment(
            MATCH_ID,
            CreateMatchSegmentRequest(
                segment_number=1, minute_start=121, resolution_type="extra_time"
            ),
            context(),
            session,
        )

    assert error.value.status_code == 422
    assert "máximo de 120" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["extra_time", "penalties"])
async def test_the_segment_route_rejects_a_resolution_the_stage_does_not_enable(
    monkeypatch, resolution
):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(extra_time_enabled=False, penalties_enabled=False))),
    )
    session = _segment_session()

    with pytest.raises(ResolutionNotEnabled) as error:
        await matches_router.create_match_segment(
            MATCH_ID,
            CreateMatchSegmentRequest(
                segment_number=1, minute_start=10, resolution_type=resolution
            ),
            context(),
            session,
        )

    assert error.value.status_code == 409
    assert error.value.code == RESOLUTION_NOT_ENABLED
    assert error.value.detail == RESOLUTION_NOT_ENABLED_DETAIL
    assert session.writes == []


@pytest.mark.asyncio
async def test_the_unified_409_wins_over_the_range_422_on_a_segment(monkeypatch):
    """La resolución habilitada se comprueba antes del rango de minuto."""

    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(regular=90, extra=120, extra_time_enabled=False))),
    )
    session = _segment_session()

    with pytest.raises(ResolutionNotEnabled):
        await matches_router.create_match_segment(
            MATCH_ID,
            CreateMatchSegmentRequest(
                segment_number=1, minute_start=200, resolution_type="extra_time"
            ),
            context(),
            session,
        )

    assert session.writes == []


@pytest.mark.asyncio
async def test_an_interruption_without_resolution_keeps_the_stage_maximum(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(regular=40, extra=100, extra_time_enabled=True))),
    )

    without_field = await matches_router.interrupt_match_segment(
        MATCH_ID,
        SEGMENT_1,
        InterruptMatchSegmentRequest(reason="weather", minute=95),
        context(),
        _interrupt_session(),
    )

    assert without_field["minute"] == 95

    session = _interrupt_session()
    with pytest.raises(HTTPException) as error:
        await matches_router.interrupt_match_segment(
            MATCH_ID,
            SEGMENT_1,
            InterruptMatchSegmentRequest(
                reason="weather", minute=95, resolution_type="regular"
            ),
            context(),
            session,
        )

    assert error.value.status_code == 422
    assert "máximo de 40" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_an_interruption_with_extra_time_resolution_reads_that_maximum(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(regular=40, extra=100, extra_time_enabled=True))),
    )

    accepted = await matches_router.interrupt_match_segment(
        MATCH_ID,
        SEGMENT_1,
        InterruptMatchSegmentRequest(
            reason="weather", minute=100, resolution_type="extra_time"
        ),
        context(),
        _interrupt_session(),
    )

    assert accepted["minute"] == 100

    session = _interrupt_session()
    with pytest.raises(HTTPException) as error:
        await matches_router.interrupt_match_segment(
            MATCH_ID,
            SEGMENT_1,
            InterruptMatchSegmentRequest(
                reason="weather", minute=101, resolution_type="extra_time"
            ),
            context(),
            session,
        )

    assert error.value.status_code == 422
    assert "máximo de 100" in error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_an_interruption_rejects_a_resolution_the_stage_does_not_enable(monkeypatch):
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(regular=90, extra=120, extra_time_enabled=False))),
    )
    session = _interrupt_session()

    with pytest.raises(ResolutionNotEnabled) as error:
        await matches_router.interrupt_match_segment(
            MATCH_ID,
            SEGMENT_1,
            InterruptMatchSegmentRequest(
                reason="weather", minute=50, resolution_type="extra_time"
            ),
            context(),
            session,
        )

    assert error.value.status_code == 409
    assert error.value.code == RESOLUTION_NOT_ENABLED
    assert error.value.detail == RESOLUTION_NOT_ENABLED_DETAIL
    # Nada se escribe: no hay interrupción ni actualización del segmento.
    assert session.writes == []


class _RouteSession:
    """Sesión mínima para ejercer el handler HTTP sin base de datos."""

    def begin(self):
        return Transaction()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            f"/api/v1/matches/{MATCH_ID}/segments",
            {
                "segment_number": 1,
                "minute_start": 10,
                "resolution_type": "extra_time",
            },
        ),
        (
            f"/api/v1/matches/{MATCH_ID}/segments/{SEGMENT_1}/interrupt",
            {"reason": "weather", "minute": 50, "resolution_type": "extra_time"},
        ),
    ],
)
async def test_both_routes_answer_the_identical_unified_409(monkeypatch, path, body):
    """P5: el mismo código y el mismo mensaje en crear segmento e interrumpir."""

    async def no_rls(db, organization_id, user_id):
        return None

    async def database():
        yield _RouteSession()

    monkeypatch.setattr(matches_router, "set_rls_context", no_rls)
    monkeypatch.setattr(
        matches_router,
        "_load_operation_match",
        _loader(_match(rules_config(extra_time_enabled=False))),
    )

    async def auth():
        return context()

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = auth
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.post(path, json=body)
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_auth_context, None)

    assert response.status_code == 409
    assert response.json() == {
        "detail": RESOLUTION_NOT_ENABLED_DETAIL,
        "code": RESOLUTION_NOT_ENABLED,
    }


def test_the_optional_resolution_keeps_the_structural_422_of_both_requests():
    with pytest.raises(ValidationError):
        CreateMatchSegmentRequest(segment_number=1, minute_start=-1)
    with pytest.raises(ValidationError):
        CreateMatchSegmentRequest(
            segment_number=1, minute_start=10, resolution_type="overtime"
        )
    with pytest.raises(ValidationError):
        InterruptMatchSegmentRequest(reason="weather", minute=-1)
    with pytest.raises(ValidationError):
        InterruptMatchSegmentRequest(
            reason="weather", minute=10, resolution_type="overtime"
        )
    # El campo sigue siendo opcional (P1).
    assert CreateMatchSegmentRequest(segment_number=1, minute_start=10).resolution_type is None
    assert InterruptMatchSegmentRequest(reason="weather", minute=10).resolution_type is None
