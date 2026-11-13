"""Pure projections; callers supply ledger facts and temporal boundaries."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EffectiveResolution:
    action: str
    new_duration: int | None = None
    applied: bool = False
    declarative: bool = False
    excluded: bool = False


@dataclass(frozen=True, slots=True)
class DurationProjection:
    original_duration: int
    effective_duration: int
    served_count: int
    remaining: int
    status: str
    pending_effect: bool

    @property
    def blocking(self) -> bool:
        return self.status == "active" and self.remaining > 0


def project_duration(
    original_duration: int,
    served_count: int,
    *,
    status: str = "active",
    resolution: EffectiveResolution | None = None,
) -> DurationProjection:
    if type(original_duration) is not int or original_duration < 1:
        raise ValueError("Original duration must be a positive integer")
    if type(served_count) is not int or served_count < 0:
        raise ValueError("Served count must be a nonnegative integer")
    if status not in {"active", "served", "appealed", "cancelled"}:
        raise ValueError("Invalid suspension status")
    effective_duration = original_duration
    pending = False
    if resolution is not None:
        if resolution.action == "reduce":
            if type(resolution.new_duration) is not int or not 0 <= resolution.new_duration < original_duration:
                raise ValueError("A reduction must decrease duration without credit")
        elif resolution.action != "annul" or resolution.new_duration is not None:
            raise ValueError("Invalid resolution measure")
        if not resolution.excluded:
            pending = not (resolution.applied or resolution.declarative)
            if not pending:
                if resolution.action == "annul":
                    effective_duration, status = 0, "cancelled"
                else:
                    effective_duration = resolution.new_duration
                    if status == "active" and served_count >= effective_duration:
                        status = "served"
    remaining = 0 if status == "cancelled" else max(0, effective_duration - served_count)
    return DurationProjection(original_duration, effective_duration, served_count, remaining, status, pending)


@dataclass(frozen=True, slots=True)
class MatchTiming:
    has_started: bool
    first_started_at: datetime | None = None
    scheduled_at: datetime | None = None
    snapshot_exists: bool = False


@dataclass(frozen=True, slots=True)
class ApplicationPlan:
    should_apply: bool
    pending_effect: bool
    preserve_existing: bool
    requires_review: bool


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("A timezone-aware instant is required")


def plan_application(
    decision_at: datetime,
    as_of: datetime,
    match: MatchTiming,
    *,
    opening: bool = False,
    declarative: bool = False,
    excluded: bool = False,
) -> ApplicationPlan:
    _require_aware(decision_at)
    _require_aware(as_of)
    if match.scheduled_at is not None:
        _require_aware(match.scheduled_at)
    if match.first_started_at is not None:
        _require_aware(match.first_started_at)
        if not match.has_started or match.first_started_at > as_of:
            raise ValueError("First opening must be an established past boundary")
    if excluded or declarative or as_of < decision_at or match.snapshot_exists:
        return ApplicationPlan(False, False, True, False)
    if match.has_started:
        review = match.first_started_at is None or match.first_started_at > decision_at
        return ApplicationPlan(False, False, True, review)
    if opening:
        return ApplicationPlan(True, False, False, False)
    return ApplicationPlan(False, True, True, False)
