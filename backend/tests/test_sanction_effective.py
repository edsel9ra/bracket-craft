from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.sanction_appeals.effective import (
    EffectiveResolution,
    MatchTiming,
    plan_application,
    project_duration,
)


@pytest.mark.parametrize("status", ["active", "served", "appealed", "cancelled"])
def test_duration_original_without_resolution(status):
    result = project_duration(3, 1, status=status)
    assert result.original_duration == result.effective_duration == 3
    assert result.served_count == 1
    assert result.status == status
    assert result.remaining == (0 if status == "cancelled" else 2)
    assert not result.pending_effect
    assert result.blocking == (status == "active")


@pytest.mark.parametrize("served", [0, 1, 2, 4])
def test_duration_reduction_preserves_serves_and_no_credit(served):
    result = project_duration(3, served, resolution=EffectiveResolution("reduce", 2, applied=True))
    assert result.original_duration == 3
    assert result.effective_duration == 2
    assert result.served_count == served
    assert result.remaining == max(0, 2 - served)
    assert result.status == ("active" if served < 2 else "served")


def test_duration_pending_annulment_declaration_and_legacy():
    pending = EffectiveResolution("reduce", 1)
    assert project_duration(3, 0, resolution=pending).effective_duration == 3
    assert project_duration(3, 0, resolution=pending).pending_effect
    excluded = replace(pending, excluded=True)
    assert not project_duration(3, 0, resolution=excluded).pending_effect
    annulled = project_duration(3, 2, resolution=EffectiveResolution("annul", applied=True))
    assert (annulled.effective_duration, annulled.remaining, annulled.status) == (0, 0, "cancelled")
    declared = project_duration(3, 3, status="served", resolution=EffectiveResolution("reduce", 1, declarative=True))
    assert (declared.effective_duration, declared.served_count, declared.remaining, declared.status) == (1, 3, 0, "served")
    assert not declared.pending_effect
    assert project_duration(3, 0, status="appealed").status == "appealed"
    assert not project_duration(3, 0, status="appealed").blocking
    zero = project_duration(3, 0, resolution=EffectiveResolution("reduce", 0, applied=True))
    assert (zero.remaining, zero.status) == (0, "served")


@pytest.mark.parametrize("original,served,resolution", [
    (0, 0, None), (True, 0, None), (3, -1, None), (3, False, None),
    (3, 0, EffectiveResolution("reduce", 3)), (3, 0, EffectiveResolution("reduce", -1)),
    (3, 0, EffectiveResolution("reduce")), (3, 0, EffectiveResolution("annul", 1)),
    (3, 0, EffectiveResolution("increase", 4)),
])
def test_duration_invalid_facts_rejected(original, served, resolution):
    with pytest.raises(ValueError):
        project_duration(original, served, resolution=resolution)


DECISION = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)


def test_temporal_waits_for_real_opening_not_schedule_or_rescheduling():
    match = MatchTiming(has_started=False, scheduled_at=DECISION - timedelta(days=1))
    waiting = plan_application(DECISION, DECISION, match)
    assert waiting.pending_effect and not waiting.should_apply
    assert waiting == plan_application(DECISION, DECISION, replace(match, scheduled_at=DECISION + timedelta(days=2)))
    opening = plan_application(DECISION, DECISION, match, opening=True)
    assert opening.should_apply and not opening.preserve_existing
    before = plan_application(DECISION, DECISION - timedelta(seconds=1), match, opening=True)
    assert not before.should_apply and not before.pending_effect


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_temporal_started_match_never_gets_a_new_application(offset):
    match = MatchTiming(has_started=True, first_started_at=DECISION + timedelta(seconds=offset), snapshot_exists=True)
    result = plan_application(DECISION, DECISION + timedelta(seconds=5), match, opening=True)
    assert result.preserve_existing
    assert not result.should_apply and not result.requires_review


def test_temporal_legacy_preserves_accredited_restriction_without_inventing_dates():
    unknown = plan_application(DECISION, DECISION, MatchTiming(has_started=True))
    assert unknown.requires_review and unknown.preserve_existing
    assert not unknown.should_apply and not unknown.pending_effect
    before = MatchTiming(has_started=True, first_started_at=DECISION - timedelta(seconds=1))
    assert not plan_application(DECISION, DECISION, before).requires_review
    missing = MatchTiming(has_started=True, first_started_at=DECISION + timedelta(seconds=1))
    assert plan_application(DECISION, DECISION + timedelta(seconds=2), missing).requires_review


@pytest.mark.parametrize("declarative,excluded", [(True, False), (False, True)])
def test_temporal_declarations_and_excluded_resolutions_do_not_invent_match(declarative, excluded):
    result = plan_application(DECISION, DECISION, MatchTiming(has_started=False),
        opening=True, declarative=declarative, excluded=excluded)
    assert not result.should_apply and not result.pending_effect


@pytest.mark.parametrize("decision,as_of,match", [
    (DECISION.replace(tzinfo=None), DECISION, MatchTiming(False)),
    (DECISION, DECISION.replace(tzinfo=None), MatchTiming(False)),
    (DECISION, DECISION, MatchTiming(True, first_started_at=DECISION + timedelta(seconds=1))),
    (DECISION, DECISION, MatchTiming(False, first_started_at=DECISION)),
    (DECISION, DECISION, MatchTiming(True, first_started_at=DECISION.replace(tzinfo=None))),
])
def test_temporal_invalid_or_unproven_boundaries_rejected(decision, as_of, match):
    with pytest.raises(ValueError):
        plan_application(decision, as_of, match)
