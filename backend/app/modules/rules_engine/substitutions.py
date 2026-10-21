"""Pure substitution engine for match reports (RF-012 to RF-015).

This module is the single source of truth for the on-field state derived from
the match roster plus the events of the report. It performs no I/O, reads no
clock and keeps no global state: every function receives everything it needs.

Invariants
----------
* The initial XI is the set of valid ``starter`` entries of ``match_rosters``.
* The state of a player is a **union of intervals** ``[entry, exit)`` measured
  in effective minutes (``minute + added_minute``), so a player may leave and
  re-enter and every one of his intervals is honoured independently.
* A red card closes the open interval and ejects the player for the rest of
  the match: an ejected player never re-enters.
* Events are applied in the canonical order ``(minute, added_minute, index)``,
  where ``index`` is the position of the event inside the report (the stable
  tie-breaker). The derived state is therefore independent of the input order.
* Substitutions and windows are counted **per team and per match**. A window is
  a distinct ``(segment_id, minute, added_minute)`` key, so several changes in
  the same segment and minute consume a single window.
* Legacy ``substitution`` events without ``player_out_id``/``player_in_id`` are
  informational: they consume neither substitutions nor windows and do not
  change the on-field state (RF-034).

Errors are raised as :class:`SubstitutionError`, a ``ValueError`` subclass with
a stable :class:`SubstitutionErrorCode`. The closing service maps every
business violation to ``409``; the code exists to build the message and to test
the exact reason.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from app.modules.rules_engine.defaults import DEFAULT_SUBSTITUTIONS

RED_CARD = "red_card"
SUBSTITUTION = "substitution"

__all__ = [
    "LimitBalance",
    "Interval",
    "MatchEvent",
    "OnFieldState",
    "RED_CARD",
    "RosterEntry",
    "SUBSTITUTION",
    "Segment",
    "SegmentBalance",
    "SubstitutionError",
    "SubstitutionErrorCode",
    "SubstitutionLimits",
    "TeamUsage",
    "apply_red_card",
    "apply_substitution",
    "build_on_field",
    "canonical_event_order",
    "check_substitution_limits",
    "has_lineup",
    "remaining_limits",
    "segment_balances",
    "starter_player_ids",
    "team_usage",
    "validate_player_on_field",
    "validate_roster_minutes",
    "validate_substitution",
]


class SubstitutionErrorCode(str, Enum):
    """Stable reason codes; every one of them is a business ``409``."""

    NO_LINEUP = "no_lineup"
    TEAM_MISMATCH = "team_mismatch"
    PLAYER_NOT_IN_ROSTER = "player_not_in_roster"
    SAME_PLAYER = "same_player"
    PLAYER_EJECTED = "player_ejected"
    PLAYER_OUT_NOT_ON_FIELD = "player_out_not_on_field"
    PLAYER_IN_ALREADY_ON_FIELD = "player_in_already_on_field"
    REENTRY_NOT_ALLOWED = "reentry_not_allowed"
    SUBSTITUTIONS_EXHAUSTED = "substitutions_exhausted"
    WINDOWS_EXHAUSTED = "windows_exhausted"
    PLAYER_NOT_ON_FIELD = "player_not_on_field"
    ROSTER_MINUTES_CONFLICT = "roster_minutes_conflict"


class SubstitutionError(ValueError):
    """Domain error with a code the API layer can map to ``409``."""

    def __init__(self, code: SubstitutionErrorCode, message: str):
        super().__init__(message)
        self.code = code


# --- Input model -----------------------------------------------------------


@dataclass(frozen=True)
class RosterEntry:
    """Minimal view of one ``match_rosters`` row for a single team."""

    player_id: UUID
    team_id: UUID
    role: str = "starter"
    is_valid: bool = True
    entered_minute: int | None = None
    left_minute: int | None = None


@dataclass(frozen=True)
class MatchEvent:
    """Minimal, database-free view of one ``match_events`` row."""

    event_type: str
    team_id: UUID
    minute: int
    added_minute: int = 0
    index: int = 0
    player_id: UUID | None = None
    player_out_id: UUID | None = None
    player_in_id: UUID | None = None
    segment_id: UUID | None = None

    @classmethod
    def from_mapping(cls, event: Mapping[str, Any], *, index: int = 0) -> "MatchEvent":
        """Build an event from a mapped row or a dumped payload."""

        return cls(
            event_type=str(event["event_type"]),
            team_id=_as_uuid(event["team_id"]),
            minute=int(event["minute"]),
            added_minute=int(event.get("added_minute") or 0),
            index=index,
            player_id=_as_optional_uuid(event.get("player_id")),
            player_out_id=_as_optional_uuid(event.get("player_out_id")),
            player_in_id=_as_optional_uuid(event.get("player_in_id")),
            segment_id=_as_optional_uuid(event.get("segment_id")),
        )

    @property
    def effective_minute(self) -> int:
        return self.minute + self.added_minute

    @property
    def order_key(self) -> tuple[int, int, int]:
        return (self.minute, self.added_minute, self.index)

    @property
    def is_substitution_with_pair(self) -> bool:
        return (
            self.event_type == SUBSTITUTION
            and self.player_out_id is not None
            and self.player_in_id is not None
        )


@dataclass(frozen=True)
class Interval:
    """Half-open ``[start, end)`` interval in effective minutes.

    ``end`` is ``None`` while the player is still on the field.
    """

    start: int
    end: int | None = None

    def contains(self, minute: int) -> bool:
        return minute >= self.start and (self.end is None or minute < self.end)


@dataclass(frozen=True)
class SubstitutionLimits:
    """Effective ``rules_config.substitutions`` block."""

    max_per_team: int
    max_windows: int
    allow_reentry: bool = False

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> "SubstitutionLimits":
        """Read the limits from the effective block, defaulting missing keys."""

        merged = {**DEFAULT_SUBSTITUTIONS, **dict(config or {})}
        return cls(
            max_per_team=int(merged["max_per_team"]),
            max_windows=int(merged["max_windows"]),
            allow_reentry=bool(merged["allow_reentry"]),
        )


@dataclass(frozen=True)
class Segment:
    """Minimal view of one ``match_segments`` row."""

    id: UUID
    segment_number: int


@dataclass(frozen=True)
class TeamUsage:
    """Substitutions and distinct windows already consumed by one team."""

    substitutions: int = 0
    windows: tuple[tuple[UUID | None, int, int], ...] = ()

    @property
    def windows_used(self) -> int:
        return len(self.windows)

    def merge(self, other: "TeamUsage") -> "TeamUsage":
        return TeamUsage(
            substitutions=self.substitutions + other.substitutions,
            windows=_sorted_windows({*self.windows, *other.windows}),
        )


@dataclass(frozen=True)
class LimitBalance:
    """Remaining substitutions/windows of one team at a point of the match."""

    max_per_team: int
    max_windows: int
    substitutions_used: int
    windows_used: int
    substitutions_remaining: int
    windows_remaining: int

    @property
    def is_exhausted(self) -> bool:
        return self.substitutions_remaining <= 0 or self.windows_remaining <= 0


@dataclass(frozen=True)
class SegmentBalance:
    """Balance after a segment, ready to upsert into ``match_segment_team_state``."""

    segment_id: UUID
    segment_number: int
    team_id: UUID
    substitutions_remaining: int
    substitution_windows_remaining: int


@dataclass(frozen=True)
class OnFieldState:
    """Deterministic on-field state of one team at the end of the report."""

    team_id: UUID
    roster: Mapping[UUID, RosterEntry]
    intervals: Mapping[UUID, tuple[Interval, ...]]
    on_field: frozenset[UUID]
    ejected: frozenset[UUID]

    def intervals_for(self, player_id: UUID) -> tuple[Interval, ...]:
        return tuple(self.intervals.get(player_id, ()))

    def is_in_roster(self, player_id: UUID) -> bool:
        return player_id in self.roster

    def is_on_field(self, player_id: UUID) -> bool:
        return player_id in self.on_field

    def is_ejected(self, player_id: UUID) -> bool:
        return player_id in self.ejected

    def has_been_on_field(self, player_id: UUID) -> bool:
        return bool(self.intervals.get(player_id))

    def is_on_field_at(self, player_id: UUID, minute: int) -> bool:
        return any(interval.contains(minute) for interval in self.intervals_for(player_id))

    def bench(self) -> frozenset[UUID]:
        """Roster players who are neither on the field nor ejected."""

        return frozenset(self.roster) - self.on_field - self.ejected


# --- Builders and transitions ---------------------------------------------


def canonical_event_order(events: Iterable[MatchEvent]) -> tuple[MatchEvent, ...]:
    """Total order ``(minute, added_minute, index in the report)``."""

    return tuple(sorted(events, key=lambda event: event.order_key))


def _valid_entries(
    roster: Iterable[RosterEntry],
    team_id: UUID,
) -> dict[UUID, RosterEntry]:
    return {
        entry.player_id: entry
        for entry in roster
        if entry.is_valid and entry.team_id == team_id
    }


def starter_player_ids(
    roster: Iterable[RosterEntry],
    team_id: UUID,
) -> tuple[UUID, ...]:
    """Valid starters of a team, in a deterministic order."""

    entries = _valid_entries(roster, team_id)
    return tuple(
        sorted(
            (player_id for player_id, entry in entries.items() if entry.role == "starter"),
            key=str,
        )
    )


def has_lineup(roster: Iterable[RosterEntry], team_id: UUID) -> bool:
    """Whether the team has at least one valid starter."""

    return bool(starter_player_ids(roster, team_id))


def _close_interval(
    intervals: dict[UUID, list[Interval]],
    player_id: UUID,
    minute: int,
) -> None:
    history = intervals.get(player_id)
    if not history or history[-1].end is not None:
        return
    current = history[-1]
    # Defensive clamp: an out-of-order acta never produces an inverted interval.
    history[-1] = Interval(start=current.start, end=max(minute, current.start))


def _freeze(intervals: dict[UUID, list[Interval]]) -> dict[UUID, tuple[Interval, ...]]:
    return {player_id: tuple(history) for player_id, history in intervals.items()}


def build_on_field(
    roster: Iterable[RosterEntry],
    events: Sequence[MatchEvent],
    team_id: UUID,
) -> OnFieldState:
    """Derive the on-field state of one team from its lineup and events.

    Raises :class:`SubstitutionError` with ``NO_LINEUP`` when the team has no
    valid starters: without a lineup the state cannot be determined (RF-012).
    """

    entries = _valid_entries(roster, team_id)
    starters = [player_id for player_id, entry in entries.items() if entry.role == "starter"]
    if not starters:
        raise SubstitutionError(
            SubstitutionErrorCode.NO_LINEUP,
            "No hay planilla para determinar el estado en campo",
        )

    intervals: dict[UUID, list[Interval]] = {
        player_id: [Interval(start=0)] for player_id in starters
    }
    on_field = set(starters)
    ejected: set[UUID] = set()

    for event in canonical_event_order(events):
        if event.team_id != team_id:
            continue
        minute = event.effective_minute
        if event.event_type == RED_CARD:
            if event.player_id is None:
                continue
            _close_interval(intervals, event.player_id, minute)
            on_field.discard(event.player_id)
            ejected.add(event.player_id)
        elif event.event_type == SUBSTITUTION:
            if not event.is_substitution_with_pair:
                # Legacy event: informational, never changes the state.
                continue
            _close_interval(intervals, event.player_out_id, minute)
            on_field.discard(event.player_out_id)
            intervals.setdefault(event.player_in_id, []).append(Interval(start=minute))
            on_field.add(event.player_in_id)

    return OnFieldState(
        team_id=team_id,
        roster=entries,
        intervals=_freeze(intervals),
        on_field=frozenset(on_field),
        ejected=frozenset(ejected),
    )


def apply_substitution(
    state: OnFieldState,
    player_out_id: UUID,
    player_in_id: UUID,
    minute: int,
) -> OnFieldState:
    """Apply one substitution without validating it (callers validate first)."""

    intervals = {player_id: list(history) for player_id, history in state.intervals.items()}
    _close_interval(intervals, player_out_id, minute)
    intervals.setdefault(player_in_id, []).append(Interval(start=minute))
    on_field = set(state.on_field)
    on_field.discard(player_out_id)
    on_field.add(player_in_id)
    return replace(state, intervals=_freeze(intervals), on_field=frozenset(on_field))


def apply_red_card(
    state: OnFieldState,
    player_id: UUID,
    minute: int,
) -> OnFieldState:
    """Eject a player, closing his open interval (if any)."""

    intervals = {player_id_key: list(history) for player_id_key, history in state.intervals.items()}
    _close_interval(intervals, player_id, minute)
    return replace(
        state,
        intervals=_freeze(intervals),
        on_field=frozenset(state.on_field - {player_id}),
        ejected=frozenset(state.ejected | {player_id}),
    )


# --- Validation ------------------------------------------------------------


def _window_key(window: tuple[UUID | None, int, int]) -> tuple[str, int, int]:
    segment_id, minute, added_minute = window
    return (str(segment_id) if segment_id is not None else "", minute, added_minute)


def _sorted_windows(
    windows: Iterable[tuple[UUID | None, int, int]],
) -> tuple[tuple[UUID | None, int, int], ...]:
    return tuple(sorted(windows, key=_window_key))


def team_usage(events: Iterable[MatchEvent], team_id: UUID) -> TeamUsage:
    """Substitutions and windows consumed by a team (legacy events excluded)."""

    substitutions = 0
    windows: set[tuple[UUID | None, int, int]] = set()
    for event in events:
        if event.team_id != team_id or not event.is_substitution_with_pair:
            continue
        substitutions += 1
        windows.add((event.segment_id, event.minute, event.added_minute))
    return TeamUsage(substitutions=substitutions, windows=_sorted_windows(windows))


def remaining_limits(limits: SubstitutionLimits, usage: TeamUsage) -> LimitBalance:
    """Remaining counters, never negative, for one team."""

    return LimitBalance(
        max_per_team=limits.max_per_team,
        max_windows=limits.max_windows,
        substitutions_used=usage.substitutions,
        windows_used=usage.windows_used,
        substitutions_remaining=max(limits.max_per_team - usage.substitutions, 0),
        windows_remaining=max(limits.max_windows - usage.windows_used, 0),
    )


def check_substitution_limits(limits: SubstitutionLimits, usage: TeamUsage) -> None:
    """Reject a substitution that would exceed a limit, naming it and the balance."""

    if usage.substitutions >= limits.max_per_team:
        raise SubstitutionError(
            SubstitutionErrorCode.SUBSTITUTIONS_EXHAUSTED,
            "El equipo alcanzó el máximo de "
            f"{limits.max_per_team} sustituciones "
            f"(usadas {usage.substitutions}, saldo "
            f"{max(limits.max_per_team - usage.substitutions, 0)})",
        )
    if usage.windows_used >= limits.max_windows:
        raise SubstitutionError(
            SubstitutionErrorCode.WINDOWS_EXHAUSTED,
            "El equipo alcanzó el máximo de "
            f"{limits.max_windows} ventanas de sustitución "
            f"(usadas {usage.windows_used}, saldo "
            f"{max(limits.max_windows - usage.windows_used, 0)})",
        )


def validate_substitution(
    state: OnFieldState,
    limits: SubstitutionLimits,
    usage: TeamUsage,
    player_out_id: UUID,
    player_in_id: UUID,
    *,
    team_id: UUID | None = None,
) -> None:
    """Validate one substitution against the state and the limits.

    The limits are checked first, so ``max_per_team = 0`` always disables the
    operation even when the state is invalid too (RF-010, case 6).
    """

    check_substitution_limits(limits, usage)

    if team_id is not None and team_id != state.team_id:
        raise SubstitutionError(
            SubstitutionErrorCode.TEAM_MISMATCH,
            f"El equipo {team_id} no coincide con el equipo de la planilla "
            f"{state.team_id}",
        )

    for player_id in (player_out_id, player_in_id):
        if not state.is_in_roster(player_id):
            raise SubstitutionError(
                SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER,
                f"El jugador {player_id} no está en la plantilla del equipo",
            )

    if player_out_id == player_in_id:
        raise SubstitutionError(
            SubstitutionErrorCode.SAME_PLAYER,
            "El jugador que sale y el que entra deben ser distintos",
        )

    for player_id in (player_out_id, player_in_id):
        if state.is_ejected(player_id):
            raise SubstitutionError(
                SubstitutionErrorCode.PLAYER_EJECTED,
                f"El jugador {player_id} está expulsado",
            )

    if not state.is_on_field(player_out_id):
        raise SubstitutionError(
            SubstitutionErrorCode.PLAYER_OUT_NOT_ON_FIELD,
            f"El jugador {player_out_id} no está en campo",
        )

    if state.is_on_field(player_in_id):
        raise SubstitutionError(
            SubstitutionErrorCode.PLAYER_IN_ALREADY_ON_FIELD,
            f"El jugador {player_in_id} ya está en campo",
        )

    if not limits.allow_reentry and state.has_been_on_field(player_in_id):
        raise SubstitutionError(
            SubstitutionErrorCode.REENTRY_NOT_ALLOWED,
            f"El jugador {player_in_id} ya estuvo en campo y la reentrada "
            "no está permitida",
        )


def validate_player_on_field(
    state: OnFieldState,
    player_id: UUID,
    minute: int,
    added_minute: int = 0,
) -> None:
    """Require an event minute to fall inside the player's interval union."""

    if not state.is_on_field_at(player_id, minute + added_minute):
        raise SubstitutionError(
            SubstitutionErrorCode.PLAYER_NOT_ON_FIELD,
            f"El evento del jugador {player_id} está fuera de sus intervalos "
            "en campo",
        )


def validate_roster_minutes(
    state: OnFieldState,
    player_id: UUID,
    *,
    entered_minute: int | None = None,
    left_minute: int | None = None,
) -> None:
    """Contrast ``match_rosters`` minutes only when there is no re-entry.

    With a single interval the planilla cannot contradict the derived
    intervals; with re-entry the derived intervals prevail (RF-012).
    """

    intervals = state.intervals_for(player_id)
    if len(intervals) == 0:
        # The player never reached the field. If the planilla declares any
        # minute, both sources contradict each other (RF-017).
        if entered_minute is not None or left_minute is not None:
            raise SubstitutionError(
                SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT,
                f"Los minutos de la planilla del jugador {player_id} contradicen "
                "sus intervalos en campo",
            )
        return
    if len(intervals) != 1:
        return

    interval = intervals[0]
    if entered_minute is not None and interval.start > 0 and entered_minute != interval.start:
        raise SubstitutionError(
            SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT,
            f"Los minutos de la planilla del jugador {player_id} contradicen "
            "sus intervalos en campo",
        )
    if left_minute is not None and interval.end != left_minute:
        raise SubstitutionError(
            SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT,
            f"Los minutos de la planilla del jugador {player_id} contradicen "
            "sus intervalos en campo",
        )


# --- Segment projection ----------------------------------------------------


def segment_balances(
    segments: Iterable[Segment],
    events: Iterable[MatchEvent],
    team_ids: Iterable[UUID],
    limits: SubstitutionLimits,
) -> tuple[SegmentBalance, ...]:
    """Per-segment balance of every team, accumulated by ``segment_number``.

    The row of a segment holds the remaining counters **after** that segment,
    ordered by ``segment_number`` (never by minute) so the closing service can
    rewrite ``match_segment_team_state`` without decrementing blindly.
    """

    ordered_segments = sorted(segments, key=lambda segment: (segment.segment_number, str(segment.id)))
    ordered_teams = sorted(set(team_ids), key=str)
    event_list = list(events)
    cumulative = {team_id: TeamUsage() for team_id in ordered_teams}

    balances: list[SegmentBalance] = []
    for segment in ordered_segments:
        for team_id in ordered_teams:
            segment_usage = team_usage(
                (
                    event
                    for event in event_list
                    if event.segment_id == segment.id and event.team_id == team_id
                ),
                team_id,
            )
            cumulative[team_id] = cumulative[team_id].merge(segment_usage)
            balance = remaining_limits(limits, cumulative[team_id])
            balances.append(
                SegmentBalance(
                    segment_id=segment.id,
                    segment_number=segment.segment_number,
                    team_id=team_id,
                    substitutions_remaining=balance.substitutions_remaining,
                    substitution_windows_remaining=balance.windows_remaining,
                )
            )
    return tuple(balances)


# --- Helpers ---------------------------------------------------------------


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _as_optional_uuid(value: Any) -> UUID | None:
    return None if value is None else _as_uuid(value)
