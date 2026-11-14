"""Pure, inert policies for the shared live-match draft."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from app.modules.matches.live_schemas import (
    LiveCorrectClockCommand,
    LivePauseResumeClockCommand,
    LiveReportDTO,
    LiveResultDTO,
    LiveStartClockCommand,
)
from app.modules.matches.schemas import MatchEventPayload
from app.modules.rules_engine.engine import compute_match_outcome, count_event_goals
from app.modules.rules_engine.substitutions import MatchEvent, canonical_event_order


@dataclass(frozen=True)
class AccessContext:
    organization_id: UUID | None
    organization_user_id: UUID | None
    active: bool


@dataclass(frozen=True)
class AccessPath:
    """A current role grant and assignments resolved for this member and tenant."""

    organization_id: UUID
    organization_user_id: UUID
    role_code: str
    permissions: frozenset[str]
    assigned_match_ids: frozenset[UUID] = frozenset()


@dataclass(frozen=True)
class LiveCapabilities:
    can_view: bool = False
    can_operate: bool = False


def evaluate_access(
    context: AccessContext,
    organization_id: UUID,
    match_id: UUID,
    paths: tuple[AccessPath, ...],
) -> LiveCapabilities:
    if (
        not context.active
        or context.organization_id != organization_id
        or context.organization_user_id is None
    ):
        return LiveCapabilities()
    permissions = set()
    for path in paths:
        if (
            path.organization_id == organization_id
            and path.organization_user_id == context.organization_user_id
            and (
                path.role_code in {"owner", "administrator", "operator"}
                or match_id in path.assigned_match_ids
            )
        ):
            permissions.update(path.permissions)
    return LiveCapabilities(
        can_view="VIEW_MATCH_LIVE_DRAFT" in permissions,
        can_operate="OPERATE_MATCH_LIVE" in permissions,
    )


@dataclass(frozen=True)
class ClockReference:
    segment_id: UUID
    segment_number: int
    elapsed_us: int
    state: Literal["running", "paused"]
    anchor_at: datetime | None = None


@dataclass(frozen=True)
class ClockObservation:
    segment_number: int | None
    elapsed_seconds: int | None
    state: Literal["not_started", "running", "paused"]
    observed_at: datetime


def observe_clock(reference: ClockReference | None, observed_at: datetime) -> ClockObservation:
    _require_utc(observed_at)
    if reference is None:
        return ClockObservation(None, None, "not_started", observed_at)
    elapsed_us = _elapsed_us(reference, observed_at)
    return ClockObservation(reference.segment_number, elapsed_us // 1_000_000, reference.state, observed_at)


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("El instante debe ser UTC aware")


def _elapsed_us(reference: ClockReference, observed_at: datetime) -> int:
    if (
        type(reference.elapsed_us) is not int or reference.elapsed_us < 0
        or type(reference.segment_number) is not int or reference.segment_number < 1
        or reference.state not in {"running", "paused"}
        or (reference.state == "running") != (reference.anchor_at is not None)
    ):
        raise ValueError("Referencia de reloj inválida")
    if reference.anchor_at is None:
        return reference.elapsed_us
    _require_utc(reference.anchor_at)
    delta = observed_at - reference.anchor_at
    delta_us = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    return reference.elapsed_us + max(0, delta_us)


@dataclass(frozen=True)
class SegmentFacts:
    match_status: str
    segment_id: UUID
    segment_number: int
    active: bool


def reduce_clock(
    reference: ClockReference | None,
    command: LiveStartClockCommand | LivePauseResumeClockCommand | LiveCorrectClockCommand,
    accepted_at: datetime,
    segment_facts: SegmentFacts,
) -> ClockReference:
    _require_utc(accepted_at)
    if (
        segment_facts.match_status != "live" or not segment_facts.active
        or type(segment_facts.segment_number) is not int or segment_facts.segment_number < 1
    ):
        raise ValueError("El reloj requiere un segmento activo de un partido live")
    if reference is not None:
        _elapsed_us(reference, accepted_at)
    if command.type == "start_clock":
        if command.segment_id != segment_facts.segment_id:
            raise ValueError("Segmento ajeno o inactivo")
        if reference is not None and (
            reference.state == "running" or reference.segment_id == command.segment_id
        ):
            raise ValueError("El reloj ya fue iniciado")
        return ClockReference(command.segment_id, segment_facts.segment_number, 0, "running", accepted_at)
    if reference is None:
        raise ValueError("El reloj no fue iniciado")
    if (
        reference.segment_id != segment_facts.segment_id
        or reference.segment_number != segment_facts.segment_number
    ):
        raise ValueError("La referencia no corresponde al segmento activo")
    if command.type == "pause_clock" and reference.state == "running":
        return replace(reference, elapsed_us=_elapsed_us(reference, accepted_at), state="paused", anchor_at=None)
    if command.type == "resume_clock" and reference.state == "paused":
        return replace(reference, state="running", anchor_at=accepted_at)
    if command.type == "correct_clock" and command.segment_id == reference.segment_id:
        return replace(reference, elapsed_us=command.elapsed_us, anchor_at=accepted_at if reference.state == "running" else None)
    raise ValueError("Control de reloj incompatible con el estado actual")


@dataclass(frozen=True)
class TransitionFacts:
    version_published: bool
    home_team_id: UUID | None
    away_team_id: UUID | None
    report_confirmed: bool = False


@dataclass(frozen=True)
class LiveState:
    status: str
    clock: ClockReference | None = None


def decide_live_transition(
    current: LiveState,
    command: Literal["start", "suspend", "resume"],
    facts: TransitionFacts,
    accepted_at: datetime,
) -> LiveState:
    _require_utc(accepted_at)
    if (
        not facts.version_published or facts.report_confirmed
        or facts.home_team_id is None or facts.away_team_id is None
        or facts.home_team_id == facts.away_team_id
    ):
        raise ValueError("El partido no está disponible para operación live")
    target = {("scheduled", "start"): "live", ("live", "suspend"): "suspended", ("suspended", "resume"): "live"}.get((current.status, command))
    if target is None:
        raise ValueError("Transición live no permitida")
    clock = current.clock
    if clock is not None:
        elapsed_us = _elapsed_us(clock, accepted_at)
        if command == "suspend":
            clock = replace(clock, elapsed_us=elapsed_us, state="paused", anchor_at=None)
        elif command == "resume" and clock.state != "paused":
            raise ValueError("Un partido suspendido requiere un reloj detenido")
        elif command == "start":
            raise ValueError("Un partido programado no puede tener reloj iniciado")
    return LiveState(target, clock)


def derive_provisional_score(
    events: tuple[MatchEventPayload, ...],
    rules: dict,
    teams: tuple[UUID, UUID],
) -> tuple[int, int]:
    """Derive the tally, not eligibility or the final report validation."""
    home, away = teams
    if home == away:
        raise ValueError("El partido requiere dos participantes distintos")
    participants = {home, away}
    for event in events:
        if event.team_id not in participants or (
            event.beneficiary_team_id is not None and event.beneficiary_team_id not in participants
        ):
            raise ValueError("El hecho referencia un equipo que no participa")
    payloads = [event.model_dump(mode="python") for event in events]
    counted = count_event_goals(payloads)
    outcome = compute_match_outcome(
        config=rules, events=payloads, resolution_type="regular",
        home_team_id=home, away_team_id=away,
        home_score_regular=counted.get(home, 0), away_score_regular=counted.get(away, 0),
        home_score=None, away_score=None, home_penalties=None, away_penalties=None,
        winner_team_id=None,
    )
    return outcome.home_score, outcome.away_score


def review_fingerprint(
    events: tuple[MatchEventPayload, ...], result: LiveResultDTO, content_revision: int,
) -> str:
    if type(content_revision) is not int or content_revision < 0:
        raise ValueError("Revisión de contenido inválida")
    report = LiveReportDTO.model_validate({
        **result.model_dump(mode="json", exclude={"events"}),
        "events": [event.model_dump(mode="json") for event in events],
    })
    ordered = canonical_event_order(
        MatchEvent.from_mapping(event.model_dump(), index=index)
        for index, event in enumerate(report.events)
    )
    content = {
        "content_revision": content_revision,
        "result": report.model_dump(mode="json", exclude={"events"}),
        "events": [report.events[event.index].model_dump(mode="json") for event in ordered],
    }
    return sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
