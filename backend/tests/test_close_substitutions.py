"""Closing with substitutions, segment projection and operation payload (doubles).

These tests exercise the closing service, the ``POST /segments`` route and the
operation route without PostgreSQL. The session is a recording double: it
answers the reads the service needs and records every statement, so the tests
can assert that a business violation is rejected *before* any write and that
the ``GET /operation`` path never writes.

The pure engine (intervals, re-entry, limits and windows) is covered in
``test_substitutions_rules.py``; here it is composed exactly as the closing
service consumes it, so both entry points share one source of truth.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.tenancy import AuthContext
from app.modules.matches import router as matches_router
from app.modules.matches.errors import ASSIST_PLAYER_INVALID
from app.modules.matches.schemas import (
    CloseMatchReportDTO,
    CreateMatchSegmentRequest,
    MatchEventPayload,
)
from app.modules.matches.service import (
    NO_LINEUP_NOTICE,
    CloseMatchReportService,
    replay_report_state,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.substitutions import (
    MatchEvent,
    Segment,
    SubstitutionError,
    SubstitutionErrorCode,
    SubstitutionLimits,
)
from tests.event_ids import event_id

ORGANIZATION_ID = UUID(int=9001)
USER_ID = UUID(int=9002)
MEMBER_ID = UUID(int=9003)
TOURNAMENT_ID = UUID(int=9100)
VERSION_ID = UUID(int=9101)
STAGE_ID = UUID(int=9102)
MATCH_ID = UUID(int=9103)
SEGMENT_1 = UUID(int=9104)
SEGMENT_2 = UUID(int=9105)
HOME = UUID(int=9200)
AWAY = UUID(int=9201)

MATCH_DATE = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def starter(number: int, team: UUID = HOME) -> UUID:
    return UUID(int=(number if team == HOME else 300 + number))


def substitute(number: int, team: UUID = HOME) -> UUID:
    return UUID(int=(100 + number if team == HOME else 400 + number))


def roster_rows(
    *,
    team: UUID = HOME,
    starters: int = 11,
    substitutes: int = 3,
    entered_minute: dict[UUID, int] | None = None,
    left_minute: dict[UUID, int] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for index in range(1, starters + 1):
        player_id = starter(index, team)
        rows.append(
            {
                "player_id": player_id,
                "team_id": team,
                "role": "starter",
                "is_valid": True,
                "is_active": True,
                "valid_from": MATCH_DATE,
                "valid_to": None,
                "eligible_from": MATCH_DATE,
                "entered_minute": (entered_minute or {}).get(player_id),
                "left_minute": (left_minute or {}).get(player_id),
            }
        )
    for index in range(1, substitutes + 1):
        player_id = substitute(index, team)
        rows.append(
            {
                "player_id": player_id,
                "team_id": team,
                "role": "substitute",
                "is_valid": True,
                "is_active": True,
                "valid_from": MATCH_DATE,
                "valid_to": None,
                "eligible_from": MATCH_DATE,
                "entered_minute": (entered_minute or {}).get(player_id),
                "left_minute": (left_minute or {}).get(player_id),
            }
        )
    return rows


def substitution_event(
    out_id: UUID,
    in_id: UUID,
    *,
    minute: int,
    added_minute: int = 0,
    team: UUID = HOME,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="substitution",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_id=out_id,
        player_out_id=out_id,
        player_in_id=in_id,
        segment_id=segment_id,
    )


def player_event(
    event_type: str,
    player_id: UUID,
    *,
    minute: int,
    team: UUID = HOME,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type=event_type,
        team_id=team,
        minute=minute,
        index=index,
        player_id=player_id,
        segment_id=segment_id,
    )


def payload(
    out_id: UUID,
    in_id: UUID,
    *,
    minute: int,
    team: UUID = HOME,
    segment_id: UUID = SEGMENT_1,
    client_event_id: str = "sub-1",
    added_minute: int = 0,
) -> MatchEventPayload:
    return MatchEventPayload(
        # RF-015: la etiqueta se convierte en un UUID estable.
        client_event_id=event_id(client_event_id),
        event_type="substitution",
        team_id=team,
        player_id=out_id,
        player_out_id=out_id,
        player_in_id=in_id,
        minute=minute,
        added_minute=added_minute,
        segment_id=segment_id,
    )


def goal_payload(
    player_id: UUID,
    *,
    assist_player_id: UUID | None = None,
    minute: int,
    team: UUID = HOME,
    segment_id: UUID = SEGMENT_1,
    client_event_id: str = "goal-1",
) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id(client_event_id),
        event_type="goal",
        team_id=team,
        player_id=player_id,
        assist_player_id=assist_player_id,
        minute=minute,
        segment_id=segment_id,
    )


def red_card_payload(
    player_id: UUID,
    *,
    minute: int,
    red_card_type: str = "direct_red",
    team: UUID = HOME,
    segment_id: UUID = SEGMENT_1,
    client_event_id: str = "red-1",
) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id(client_event_id),
        event_type="red_card",
        team_id=team,
        player_id=player_id,
        minute=minute,
        segment_id=segment_id,
        metadata={"red_card_type": red_card_type},
    )


def rules_config(**substitutions: object) -> dict:
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "regular_time_minutes": 90,
        "extra_time_minutes": 120,
    }
    config["substitutions"] = {"max_per_team": 5, "max_windows": 3, "allow_reentry": False, **substitutions}
    return config


def regular_report(events: list[MatchEventPayload], *, home: int = 0, away: int = 0) -> CloseMatchReportDTO:
    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=home,
        away_score_regular=away,
        home_score=home,
        away_score=away,
        winner_team_id=None,
        events=events,
    )


# ---------------------------------------------------------------------------
# Recording doubles
# ---------------------------------------------------------------------------


class StopExecution(Exception):
    """Stop a route once the assertion point has been reached."""


class Result:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = list(rows or [])
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        assert self._rows, "se esperaba una fila"
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class Transaction:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class RecordingSession:
    """AsyncSession double that records every statement and parameter set."""

    def __init__(self, **kwargs):
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        for key, value in kwargs.items():
            setattr(self, key, value)

    def begin(self):
        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    @property
    def writes(self) -> list[str]:
        prefixes = ("INSERT", "UPDATE", "DELETE")
        return [sql for sql in self.statements if sql.upper().startswith(prefixes)]

    def parameters(self, fragment: str) -> list[dict]:
        return [params for sql, params in self.calls if fragment in sql]

    def handle(self, sql: str, params: dict) -> Result:
        raise AssertionError(f"consulta no esperada: {sql}")


class CloseSession(RecordingSession):
    """Answers the reads the closing service issues before writing."""

    def __init__(
        self,
        *,
        match=None,
        rosters=None,
        segments=None,
        active_segment=None,
        teams=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.match = match
        self.rosters = rosters if rosters is not None else []
        # Equipos de la organización que el doble conoce (RF-014). Un id ausente
        # se interpreta como «de otra organización».
        self.teams = list(teams or [])
        self.segments = segments if segments is not None else [
            {"id": SEGMENT_1, "segment_number": 1, "minute_start": 0, "minute_end": None, "status": "active"}
        ]
        self.active_segment = active_segment

    def handle(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "SELECT id, tournament_id, tournament_version_id, stage_id, bracket_code" in sql:
            return Result(
                rows=[
                    {
                        "id": MATCH_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "tournament_version_id": VERSION_ID,
                        "stage_id": STAGE_ID,
                        "bracket_code": None,
                    }
                ]
            )
        if "SELECT id" in sql and "FROM teams" in sql:
            requested = {str(team) for team in params.get("team_ids") or []}
            return Result(
                rows=[
                    {"id": team}
                    for team in self.teams
                    if str(team) in requested
                ]
            )
        if "SELECT id, tournament_version_id" in sql and "FROM stages" in sql:
            return Result(rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}])
        if "SELECT status" in sql and "FROM tournament_versions" in sql:
            return Result(scalar="published")
        if "FROM advancement_links" in sql:
            return Result(rows=[])
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql:
            return Result(rows=[{"id": MATCH_ID}])
        if "FOR UPDATE OF m" in sql:
            return Result(rows=[self.match])
        if "FROM roles r" in sql:
            return Result(scalar=1)
        if "pg_advisory_xact_lock" in sql:
            return Result()
        if "FROM match_segments" in sql and "status = 'active'" in sql:
            segment = self.active_segment or self.segments[-1]
            return Result(rows=[{"id": segment["id"], "minute_start": segment["minute_start"]}])
        if "FROM match_rosters mr" in sql:
            return Result(rows=self.rosters)
        if "FROM match_segments" in sql:
            return Result(rows=self.segments)
        if "FROM player_suspensions" in sql:
            return Result(rows=[])
        raise StopExecution(sql)


def match_row(config: dict | None = None, **overrides) -> dict:
    row = {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "tournament_version_id": VERSION_ID,
        "matchday": 1,
        "match_date": MATCH_DATE,
        "bracket_code": None,
        "status": "scheduled",
        "stage_id": STAGE_ID,
        "home_team_id": HOME,
        "away_team_id": AWAY,
        "rules_config": config or rules_config(),
        "version_status": "published",
    }
    row.update(overrides)
    return row


def build_session(*, config=None, rosters=None, segments=None, teams=None, **overrides) -> CloseSession:
    return CloseSession(
        match=match_row(config, **overrides),
        rosters=rosters if rosters is not None else roster_rows() + roster_rows(team=AWAY),
        segments=segments,
        teams=teams,
    )


async def close(session: CloseSession, report: CloseMatchReportDTO) -> dict:
    return await CloseMatchReportService(session).execute(context(), MATCH_ID, report)


# ---------------------------------------------------------------------------
# Event contract (422 before the handler)
# ---------------------------------------------------------------------------


def test_substitution_event_requires_both_players():
    with pytest.raises(ValidationError, match="player_out_id y player_in_id"):
        MatchEventPayload(
            client_event_id=event_id("contract-1"),
            event_type="substitution",
            team_id=HOME,
            player_id=starter(1),
            minute=30,
            segment_id=SEGMENT_1,
        )


def test_substitution_event_requires_the_incoming_player():
    with pytest.raises(ValidationError, match="player_out_id y player_in_id"):
        MatchEventPayload(
            client_event_id=event_id("contract-2"),
            event_type="substitution",
            team_id=HOME,
            player_id=starter(1),
            player_out_id=starter(1),
            minute=30,
            segment_id=SEGMENT_1,
        )


def test_substitution_event_rejects_the_same_player_leaving_and_entering():
    with pytest.raises(ValidationError, match="distintos"):
        MatchEventPayload(
            client_event_id=event_id("contract-3"),
            event_type="substitution",
            team_id=HOME,
            player_id=starter(1),
            player_out_id=starter(1),
            player_in_id=starter(1),
            minute=30,
            segment_id=SEGMENT_1,
        )


def test_substitution_event_requires_player_id_to_match_the_outgoing_player():
    with pytest.raises(ValidationError, match="player_id debe coincidir"):
        MatchEventPayload(
            client_event_id=event_id("contract-4"),
            event_type="substitution",
            team_id=HOME,
            player_id=starter(2),
            player_out_id=starter(1),
            player_in_id=substitute(1),
            minute=30,
            segment_id=SEGMENT_1,
        )


def test_a_regular_event_cannot_carry_substitution_players():
    with pytest.raises(ValidationError, match="solo aplican a una sustitución"):
        MatchEventPayload(
            client_event_id=event_id("contract-5"),
            event_type="goal",
            team_id=HOME,
            player_id=starter(1),
            player_out_id=starter(1),
            player_in_id=substitute(1),
            minute=30,
            segment_id=SEGMENT_1,
        )


def test_duplicate_client_event_ids_are_rejected_in_the_same_report():
    event = payload(starter(1), substitute(1), minute=30, client_event_id="duplicated")

    with pytest.raises(ValidationError, match="client_event_id duplicados"):
        regular_report([event, event])


def test_duplicate_client_event_ids_differing_only_in_case_are_rejected():
    # La identidad del evento no distingue caja (RF-012): es el mismo UUID.
    label = "duplicated-case"
    lower = payload(starter(1), substitute(1), minute=30, client_event_id=label)
    upper = lower.model_copy(update={"client_event_id": lower.client_event_id.upper()})

    with pytest.raises(ValidationError, match="client_event_id duplicados"):
        regular_report([lower, upper])


def test_the_event_contract_is_accepted_and_keeps_backwards_compatibility():
    event = payload(starter(1), substitute(1), minute=30)
    goal = MatchEventPayload(
        client_event_id=event_id("contract-6"),
        event_type="goal",
        team_id=HOME,
        player_id=starter(1),
        minute=30,
        segment_id=SEGMENT_1,
    )

    assert event.player_out_id == starter(1)
    assert event.player_in_id == substitute(1)
    assert goal.player_out_id is None and goal.player_in_id is None


# ---------------------------------------------------------------------------
# Closing validates the whole report before writing (409)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_without_starters_is_rejected_before_writing():
    session = build_session(rosters=roster_rows(starters=0) + roster_rows(team=AWAY))

    with pytest.raises(SubstitutionError) as error:
        await close(session, regular_report([]))

    assert error.value.code is SubstitutionErrorCode.NO_LINEUP
    assert "planilla" in str(error.value)
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_rejects_an_outgoing_player_that_is_not_on_the_field():
    session = build_session()
    not_on_field = substitute(1)
    report = regular_report(
        [payload(not_on_field, substitute(2), minute=30, client_event_id="invalid-out")]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.PLAYER_OUT_NOT_ON_FIELD
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_rejects_an_incoming_player_already_on_the_field():
    session = build_session()
    report = regular_report(
        [payload(starter(1), starter(2), minute=30, client_event_id="invalid-in")]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.PLAYER_IN_ALREADY_ON_FIELD
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_rejects_a_player_from_another_team():
    session = build_session()
    report = regular_report(
        [
            MatchEventPayload(
                client_event_id=event_id("other-team"),
                event_type="substitution",
                team_id=AWAY,
                player_id=starter(1),
                player_out_id=starter(1),
                player_in_id=substitute(1),
                minute=30,
                segment_id=SEGMENT_1,
            )
        ]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_goal_after_the_player_left_is_rejected_before_writing():
    session = build_session()
    report = regular_report(
        [
            payload(starter(1), substitute(1), minute=60, client_event_id="leave-1"),
            MatchEventPayload(
                client_event_id=event_id("goal-after-exit"),
                event_type="goal",
                team_id=HOME,
                player_id=starter(1),
                minute=65,
                segment_id=SEGMENT_1,
            ),
        ],
        home=1,
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.PLAYER_NOT_ON_FIELD
    assert "intervalos" in str(error.value)
    assert session.writes == []


@pytest.mark.asyncio
async def test_a_card_before_the_player_entered_is_rejected_before_writing():
    session = build_session()
    report = regular_report(
        [
            MatchEventPayload(
                client_event_id=event_id("card-before-entry"),
                event_type="yellow_card",
                team_id=HOME,
                player_id=substitute(1),
                minute=30,
                segment_id=SEGMENT_1,
            ),
            payload(substitute(2), substitute(1), minute=60, client_event_id="entry-1"),
        ]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.PLAYER_NOT_ON_FIELD
    assert session.writes == []


@pytest.mark.asyncio
async def test_roster_minutes_that_contradict_the_intervals_are_rejected():
    session = build_session(
        rosters=roster_rows(left_minute={starter(1): 70}) + roster_rows(team=AWAY)
    )
    report = regular_report(
        [payload(starter(1), substitute(1), minute=60, client_event_id="minutes-conflict")]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT
    assert session.writes == []


# ---------------------------------------------------------------------------
# Limits, windows and re-entry at the closing boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_rejects_a_substitution_beyond_the_team_limit():
    session = build_session(config=rules_config(max_per_team=1))
    report = regular_report(
        [
            payload(starter(1), substitute(1), minute=30, client_event_id="limit-1"),
            payload(starter(2), substitute(2), minute=40, client_event_id="limit-2"),
        ]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.SUBSTITUTIONS_EXHAUSTED
    assert "saldo 0" in str(error.value)
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_rejects_a_new_window_beyond_the_window_limit():
    session = build_session(config=rules_config(max_windows=1))
    report = regular_report(
        [
            payload(starter(1), substitute(1), minute=30, client_event_id="window-1"),
            payload(starter(2), substitute(2), minute=40, client_event_id="window-2"),
        ]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.WINDOWS_EXHAUSTED
    assert "saldo 0" in str(error.value)
    assert session.writes == []


@pytest.mark.asyncio
async def test_two_changes_in_the_same_window_share_the_window_budget():
    session = build_session(config=rules_config(max_per_team=2, max_windows=1))
    report = regular_report(
        [
            payload(starter(1), substitute(1), minute=30, client_event_id="same-1"),
            payload(starter(2), substitute(2), minute=30, client_event_id="same-2"),
        ]
    )

    state = replay_report_state(
        session.rosters,
        [
            substitution_event(starter(1), substitute(1), minute=30, index=0),
            substitution_event(starter(2), substitute(2), minute=30, index=1),
        ],
        [HOME, AWAY],
        SubstitutionLimits(max_per_team=2, max_windows=1),
    )

    assert state.usage[HOME].substitutions == 2
    assert state.usage[HOME].windows_used == 1

    # The same report must pass the closing validation: only the persistence is
    # intercepted, so a window violation would surface before it.
    service = CloseMatchReportService(session)

    async def stop_before_persisting(*args, **kwargs):
        raise StopExecution("persist")

    service._persist_events = stop_before_persisting
    with pytest.raises(StopExecution):
        await service.execute(context(), MATCH_ID, report)

    assert session.writes == []


@pytest.mark.asyncio
async def test_close_rejects_reentry_when_the_configuration_forbids_it():
    session = build_session()
    report = regular_report(
        [
            payload(starter(1), substitute(1), minute=30, client_event_id="reentry-1"),
            payload(substitute(1), starter(1), minute=45, client_event_id="reentry-2"),
        ]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.REENTRY_NOT_ALLOWED
    assert session.writes == []


def test_reentry_is_accepted_when_the_configuration_allows_it():
    limits = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True)
    state = replay_report_state(
        roster_rows() + roster_rows(team=AWAY),
        [
            substitution_event(starter(1), substitute(1), minute=30, index=0),
            substitution_event(substitute(1), starter(1), minute=45, index=1),
        ],
        [HOME, AWAY],
        limits,
    )

    assert state.usage[HOME].substitutions == 2
    assert state.states[HOME].is_on_field(starter(1)) is True
    assert state.states[HOME].is_on_field(substitute(1)) is False
    assert len(state.states[HOME].intervals_for(starter(1))) == 2


@pytest.mark.asyncio
async def test_max_per_team_zero_disables_substitutions():
    session = build_session(config=rules_config(max_per_team=0))
    report = regular_report(
        [payload(starter(1), substitute(1), minute=30, client_event_id="zero-1")]
    )

    with pytest.raises(SubstitutionError) as error:
        await close(session, report)

    assert error.value.code is SubstitutionErrorCode.SUBSTITUTIONS_EXHAUSTED
    assert session.writes == []


def test_an_ejected_player_cannot_be_substituted_nor_reenter():
    state = replay_report_state(
        roster_rows() + roster_rows(team=AWAY),
        [player_event("red_card", starter(3), minute=20)],
        [HOME, AWAY],
        SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True),
    )

    assert state.states[HOME].is_ejected(starter(3)) is True
    assert state.states[HOME].is_on_field(starter(3)) is False

    with pytest.raises(SubstitutionError) as error:
        replay_report_state(
            roster_rows() + roster_rows(team=AWAY),
            [
                player_event("red_card", starter(3), minute=20, index=0),
                substitution_event(starter(3), substitute(1), minute=30, index=1),
            ],
            [HOME, AWAY],
            SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True),
        )

    assert error.value.code is SubstitutionErrorCode.PLAYER_EJECTED


# ---------------------------------------------------------------------------
# client_event_id idempotency (double)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_identical_persisted_event_is_reused_without_inserting():
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    existing_id = UUID(int=9500)
    session.handle = _idempotent_handle(
        session,
        {
            event_id("retry-identical"): {
                "id": existing_id,
                "event_type": "substitution",
                "team_id": HOME,
                "beneficiary_team_id": None,
                "player_id": starter(1),
                "player_out_id": starter(1),
                "player_in_id": substitute(1),
                "minute": 30,
                "added_minute": 0,
                "segment_id": SEGMENT_1,
                "assist_player_id": None,
                "metadata": {},
            }
        },
    )
    report = regular_report(
        [payload(starter(1), substitute(1), minute=30, client_event_id="retry-identical")]
    )

    persisted = await CloseMatchReportService(session)._persist_events(
        context(),
        session.match,
        report,
        session.rosters,
        [
            {"id": SEGMENT_1, "segment_number": 1, "minute_start": 0, "minute_end": None, "status": "active"}
        ],
    )

    assert [row["id"] for row in persisted] == [existing_id]
    assert not any(sql.startswith("INSERT INTO match_events") for sql in session.statements)


@pytest.mark.asyncio
async def test_a_retry_with_the_same_client_id_and_different_data_is_immutable():
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    session.handle = _idempotent_handle(
        session,
        {
            event_id("retry-conflict"): {
                "id": UUID(int=9501),
                "event_type": "substitution",
                "team_id": HOME,
                "beneficiary_team_id": None,
                "player_id": starter(1),
                "player_out_id": starter(1),
                "player_in_id": substitute(1),
                "minute": 30,
                "added_minute": 0,
                "segment_id": SEGMENT_1,
                "assist_player_id": None,
                "metadata": {},
            }
        },
    )
    report = regular_report(
        [payload(starter(2), substitute(2), minute=30, client_event_id="retry-conflict")]
    )

    with pytest.raises(ValueError, match="inmutable"):
        await CloseMatchReportService(session)._persist_events(
            context(),
            session.match,
            report,
            session.rosters,
            [
                {"id": SEGMENT_1, "segment_number": 1, "minute_start": 0, "minute_end": None, "status": "active"}
            ],
        )

    assert not any(sql.startswith("INSERT INTO match_events") for sql in session.statements)


@pytest.mark.asyncio
async def test_a_retry_with_a_different_metadata_is_immutable():
    # D-10: la comparación incluye `metadata`; antes se reutilizaba en silencio.
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    session.handle = _idempotent_handle(
        session,
        {
            event_id("retry-metadata"): _red_card_row(metadata={"red_card_type": "direct_red"})
        },
    )
    report = regular_report(
        [
            red_card_payload(
                starter(1), minute=30, client_event_id="retry-metadata",
                red_card_type="double_yellow_red",
            )
        ]
    )

    with pytest.raises(ValueError, match="inmutable"):
        await _persist(session, report)

    assert not any(sql.startswith("INSERT INTO match_events") for sql in session.statements)


@pytest.mark.asyncio
async def test_empty_and_null_metadata_are_the_same_persisted_event():
    # `{}` y `None` son la misma información adicional (D-10): el reintento que
    # omite la `metadata` reutiliza la fila que la guardó vacía.
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    existing_id = UUID(int=9510)
    session.handle = _idempotent_handle(
        session,
        {event_id("retry-empty-metadata"): _goal_row(row_id=existing_id)},
    )
    report = regular_report(
        [goal_payload(starter(2), minute=30, client_event_id="retry-empty-metadata")],
        home=1,
    )

    persisted = await _persist(session, report)

    assert [row["id"] for row in persisted] == [existing_id]
    assert not any(sql.startswith("INSERT INTO match_events") for sql in session.statements)


@pytest.mark.asyncio
async def test_a_retry_with_a_different_assist_is_immutable():
    # La asistencia entra en la comparación de idempotencia (RF-012).
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    session.handle = _idempotent_handle(
        session,
        {event_id("retry-assist"): _goal_row(assist_player_id=None)},
    )
    report = regular_report(
        [
            goal_payload(
                starter(2), assist_player_id=starter(3), minute=30,
                client_event_id="retry-assist",
            )
        ],
        home=1,
    )

    with pytest.raises(ValueError, match="inmutable"):
        await _persist(session, report)

    assert not any(sql.startswith("INSERT INTO match_events") for sql in session.statements)


@pytest.mark.asyncio
async def test_a_retry_in_a_different_case_is_the_same_persisted_event():
    # RF-015 acepta el UUID en mayúsculas y minúsculas; la escritura y la
    # comparación usan la forma canónica, así que no se duplica la fila.
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    existing_id = UUID(int=9520)
    session.handle = _idempotent_handle(
        session,
        {event_id("retry-case"): _goal_row(row_id=existing_id)},
    )
    goal = goal_payload(starter(2), minute=30, client_event_id="retry-case")
    goal = goal.model_copy(update={"client_event_id": goal.client_event_id.upper()})
    report = regular_report([goal], home=1)

    persisted = await _persist(session, report)

    assert [row["id"] for row in persisted] == [existing_id]
    assert not any(sql.startswith("INSERT INTO match_events") for sql in session.statements)


def _red_card_row(*, metadata: dict, row_id: UUID | None = None) -> dict:
    return {
        "id": row_id or UUID(int=9503),
        "event_type": "red_card",
        "team_id": HOME,
        "beneficiary_team_id": None,
        "player_id": starter(1),
        "player_out_id": None,
        "player_in_id": None,
        "minute": 30,
        "added_minute": 0,
        "segment_id": SEGMENT_1,
        "assist_player_id": None,
        "metadata": metadata,
    }


def _goal_row(
    *, assist_player_id: UUID | None = None, row_id: UUID | None = None
) -> dict:
    return {
        "id": row_id or UUID(int=9530),
        "event_type": "goal",
        "team_id": HOME,
        "beneficiary_team_id": None,
        "player_id": starter(2),
        "player_out_id": None,
        "player_in_id": None,
        "minute": 30,
        "added_minute": 0,
        "segment_id": SEGMENT_1,
        "assist_player_id": assist_player_id,
        "metadata": {},
    }


async def _persist(session, report):
    return await CloseMatchReportService(session)._persist_events(
        context(),
        session.match,
        report,
        session.rosters,
        [
            {"id": SEGMENT_1, "segment_number": 1, "minute_start": 0, "minute_end": None, "status": "active"}
        ],
    )


def _idempotent_handle(session: CloseSession, existing: dict[str, dict]):
    base_handle = CloseSession.handle

    def handle(sql: str, params: dict) -> Result:
        if "client_event_id = :client_event_id" in sql:
            row = existing.get(params.get("client_event_id"))
            return Result(rows=[row] if row else [])
        if sql.startswith("INSERT INTO match_events"):
            event = params
            return Result(
                rows=[
                    {
                        "id": UUID(int=9502),
                        "event_type": event["event_type"],
                        "team_id": UUID(str(event["team_id"])),
                        "beneficiary_team_id": None,
                        "player_id": UUID(str(event["player_id"])),
                        "player_out_id": UUID(str(event["player_out_id"])) if event.get("player_out_id") else None,
                        "player_in_id": UUID(str(event["player_in_id"])) if event.get("player_in_id") else None,
                        "minute": event["minute"],
                        "added_minute": event["added_minute"],
                        "segment_id": UUID(str(event["segment_id"])),
                        "assist_player_id": (
                            UUID(str(event["assist_player_id"]))
                            if event.get("assist_player_id")
                            else None
                        ),
                    }
                ]
            )
        return base_handle(session, sql, params)

    return handle


# ---------------------------------------------------------------------------
# Segment projection and POST /segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_segment_state_is_recalculated_by_segment_number_not_by_minute():
    segments = [
        {"id": SEGMENT_2, "segment_number": 2, "minute_start": 45, "minute_end": None, "status": "active"},
        {"id": SEGMENT_1, "segment_number": 1, "minute_start": 0, "minute_end": 45, "status": "completed"},
    ]
    session = CloseSession(match=match_row(), rosters=roster_rows() + roster_rows(team=AWAY))
    events = [
        {
            "id": UUID(int=9600),
            "event_type": "substitution",
            "team_id": HOME,
            "minute": 10,
            "added_minute": 0,
            "player_id": starter(1),
            "player_out_id": starter(1),
            "player_in_id": substitute(1),
            "segment_id": SEGMENT_2,
        },
        {
            "id": UUID(int=9601),
            "event_type": "substitution",
            "team_id": HOME,
            "minute": 60,
            "added_minute": 0,
            "player_id": starter(2),
            "player_out_id": starter(2),
            "player_in_id": substitute(2),
            "segment_id": SEGMENT_1,
        },
    ]

    def handle(sql: str, params: dict) -> Result:
        if "FROM match_events" in sql:
            return Result(rows=events)
        if sql.startswith("INSERT INTO match_segment_team_state"):
            return Result()
        raise StopExecution(sql)

    session.handle = handle
    service = CloseMatchReportService(session)
    limits = SubstitutionLimits(max_per_team=5, max_windows=3)

    balances = await service._rewrite_segment_team_state(
        context(), session.match, segments, limits
    )

    # The segment with the lower number holds the lower consumption even when
    # its events happen later on the clock.
    assert [(row.segment_id, row.team_id) for row in balances] == [
        (SEGMENT_1, HOME),
        (SEGMENT_1, AWAY),
        (SEGMENT_2, HOME),
        (SEGMENT_2, AWAY),
    ]
    assert balances[0].substitutions_remaining == 4
    assert balances[0].substitution_windows_remaining == 2
    assert balances[2].substitutions_remaining == 3
    assert balances[2].substitution_windows_remaining == 1
    upserts = session.parameters("INSERT INTO match_segment_team_state")
    assert [row["segment_id"] for row in upserts] == [str(SEGMENT_1), str(SEGMENT_1), str(SEGMENT_2), str(SEGMENT_2)]
    assert [row["substitutions_remaining"] for row in upserts] == [4, 5, 3, 5]


@pytest.mark.asyncio
async def test_post_segments_creates_state_rows_for_the_present_teams(monkeypatch):
    match = {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "status": "scheduled",
        "home_team_id": HOME,
        "away_team_id": None,
        "rules_config": rules_config(),
    }
    session = RecordingSession()

    async def fake_load(
        db, context_, match_id, require_operation_permission=True, lock=True
    ):
        return match

    monkeypatch.setattr(matches_router, "_load_operation_match", fake_load)
    inserted: dict[str, dict] = {}

    def handle(sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "ORDER BY segment_number DESC" in sql:
            return Result(rows=[])
        if "FROM match_segments" in sql and "status = 'active'" in sql:
            return Result(rows=[])
        if sql.startswith("INSERT INTO match_segments"):
            inserted["segment"] = params
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
        raise StopExecution(sql)

    session.handle = handle
    response = await matches_router.create_match_segment(
        MATCH_ID,
        CreateMatchSegmentRequest(segment_number=1, minute_start=0),
        context(),
        session,
    )

    assert response["id"] == SEGMENT_1
    state_rows = session.parameters("INSERT INTO match_segment_team_state")
    assert [row["team_id"] for row in state_rows] == [str(HOME)]
    assert state_rows[0]["substitutions_remaining"] == 5
    assert state_rows[0]["substitution_windows_remaining"] == 3
    assert state_rows[0]["segment_id"] == str(SEGMENT_1)


# ---------------------------------------------------------------------------
# GET /operation
# ---------------------------------------------------------------------------


def _operation_session(event_rows: list[dict]) -> RecordingSession:
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
            return Result(rows=event_rows)
        raise StopExecution(sql)

    session.handle = handle
    return session


async def _call_operation(monkeypatch, session, lineup: list[dict]):
    match = {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "status": "scheduled",
        "home_team_id": HOME,
        "away_team_id": AWAY,
        "rules_config": rules_config(max_per_team=4, max_windows=2),
    }

    async def fake_load(
        db, context_, match_id, require_operation_permission=True, lock=True
    ):
        return match

    async def fake_lineup(db, organization_id, match_id):
        return lineup

    async def fake_tactical(db, organization_id, match_id):
        return []

    monkeypatch.setattr(matches_router, "_load_operation_match", fake_load)
    monkeypatch.setattr(matches_router, "_load_match_lineup", fake_lineup)
    monkeypatch.setattr(matches_router, "_load_match_tactical_lineups", fake_tactical)
    return await matches_router.get_match_operation(MATCH_ID, context(), session)


@pytest.mark.asyncio
async def test_operation_exposes_substitutions_without_writing(monkeypatch):
    lineup = roster_rows() + roster_rows(team=AWAY)
    events = [
        {
            "id": UUID(int=9700),
            "client_event_id": "op-1",
            "event_type": "substitution",
            "team_id": HOME,
            "beneficiary_team_id": None,
            "player_id": starter(1),
            "player_out_id": starter(1),
            "player_in_id": substitute(1),
            "minute": 30,
            "added_minute": 0,
            "segment_id": SEGMENT_1,
            "metadata": {},
            "is_voided": False,
            "created_at": MATCH_DATE,
        }
    ]
    session = _operation_session(events)

    response = await _call_operation(monkeypatch, session, lineup)

    assert session.writes == []
    substitutions = response["substitutions"]
    assert substitutions["max_per_team"] == 4
    assert substitutions["max_windows"] == 2
    assert substitutions["allow_reentry"] is False
    teams = {row["team_id"]: row for row in substitutions["teams"]}
    home = teams[HOME]
    assert starter(1) not in home["on_field"]
    assert substitute(1) in home["on_field"]
    assert starter(1) in home["bench"]
    assert (home["substitutions_used"], home["substitutions_remaining"]) == (1, 3)
    assert (home["windows_used"], home["windows_remaining"]) == (1, 1)
    assert home["can_register"] is True


@pytest.mark.asyncio
async def test_operation_without_lineup_returns_empty_lists_and_the_notice(monkeypatch):
    session = _operation_session([])

    response = await _call_operation(monkeypatch, session, [])

    assert session.writes == []
    substitutions = response["substitutions"]
    for row in substitutions["teams"]:
        assert row["on_field"] == []
        assert row["bench"] == []
        assert row["can_register"] is False
        assert row["reason"] == NO_LINEUP_NOTICE


# ---------------------------------------------------------------------------
# Assist and the single identifier rule (spec 015, T5: RF-003, RF-008, RF-014)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_translates_an_assist_from_the_other_team_to_the_coded_409():
    session = build_session()
    report = regular_report(
        [
            goal_payload(
                starter(2),
                assist_player_id=starter(3, AWAY),
                minute=30,
                client_event_id="assist-other-team",
            )
        ],
        home=1,
    )

    with pytest.raises(HTTPException) as error:
        await matches_router.close_match(MATCH_ID, report, context(), session)

    assert error.value.status_code == 409
    assert error.value.code == ASSIST_PLAYER_INVALID
    assert isinstance(error.value.detail, str) and error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_translates_an_assist_outside_the_match_roster_to_the_coded_409():
    session = build_session()
    report = regular_report(
        [
            goal_payload(
                starter(2),
                assist_player_id=UUID(int=999),
                minute=30,
                client_event_id="assist-outsider",
            )
        ],
        home=1,
    )

    with pytest.raises(HTTPException) as error:
        await matches_router.close_match(MATCH_ID, report, context(), session)

    assert error.value.status_code == 409
    assert error.value.code == ASSIST_PLAYER_INVALID
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_accepts_a_goal_with_a_valid_assist():
    session = build_session()
    report = regular_report(
        [
            goal_payload(
                starter(2),
                assist_player_id=starter(3),
                minute=30,
                client_event_id="assist-valid",
            )
        ],
        home=1,
    )
    service = CloseMatchReportService(session)

    async def stop_before_persisting(*args, **kwargs):
        raise StopExecution("persist")

    service._persist_events = stop_before_persisting
    with pytest.raises(StopExecution):
        await service.execute(context(), MATCH_ID, report)

    assert session.writes == []


@pytest.mark.asyncio
async def test_close_keeps_the_plain_409_for_a_scorer_outside_the_roster():
    """El goleador conserva el mensaje de pertenencia y **no** lleva ``code``."""

    session = build_session()
    report = regular_report(
        [
            goal_payload(
                UUID(int=999),
                minute=30,
                client_event_id="scorer-outsider",
            )
        ],
        home=1,
    )

    with pytest.raises(HTTPException) as error:
        await matches_router.close_match(MATCH_ID, report, context(), session)

    assert error.value.status_code == 409
    assert getattr(error.value, "code", None) is None
    assert isinstance(error.value.detail, str) and error.value.detail
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_answers_404_for_a_segment_of_another_organization():
    session = build_session()
    report = regular_report(
        [
            goal_payload(
                starter(2),
                minute=30,
                segment_id=UUID(int=7777),
                client_event_id="foreign-segment",
            )
        ],
        home=1,
    )

    with pytest.raises(HTTPException) as error:
        await matches_router.close_match(MATCH_ID, report, context(), session)

    assert error.value.status_code == 404
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_answers_404_for_a_team_of_another_organization():
    session = build_session()
    report = regular_report(
        [
            goal_payload(
                starter(2),
                minute=30,
                team=UUID(int=5555),
                client_event_id="foreign-team",
            )
        ],
        home=1,
    )

    with pytest.raises(HTTPException) as error:
        await matches_router.close_match(MATCH_ID, report, context(), session)

    assert error.value.status_code == 404
    assert session.writes == []


@pytest.mark.asyncio
async def test_close_answers_409_for_a_team_of_the_organization_that_does_not_play():
    other_team = UUID(int=5556)
    session = build_session(teams=[other_team])
    report = regular_report(
        [
            goal_payload(
                starter(2),
                minute=30,
                team=other_team,
                client_event_id="other-team-not-playing",
            )
        ],
        home=1,
    )

    with pytest.raises(HTTPException) as error:
        await matches_router.close_match(MATCH_ID, report, context(), session)

    assert error.value.status_code == 409
    assert "no participa" in str(error.value.detail)
    assert session.writes == []
