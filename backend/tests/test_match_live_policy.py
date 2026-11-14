from dataclasses import replace
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from app.modules.matches import live_policy as policy
from app.modules.matches.live_schemas import LiveCommand, LiveEventPayload, LiveResultDTO
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG


ORG, MEMBER, MATCH, OTHER = (uuid4() for _ in range(4))
VIEW = "VIEW_MATCH_LIVE_DRAFT"
OPERATE = "OPERATE_MATCH_LIVE"
CONTEXT = policy.AccessContext(ORG, MEMBER, True)


def access_path(role="operator", permissions=(VIEW, OPERATE), assigned=()):
    return policy.AccessPath(ORG, MEMBER, role, frozenset(permissions), frozenset(assigned))


@pytest.mark.parametrize("permissions, expected", [
    ((), (False, False)), ((VIEW,), (True, False)),
    ((OPERATE,), (False, True)), ((VIEW, OPERATE), (True, True)),
])
def test_access_separates_read_from_write(permissions, expected):
    result = policy.evaluate_access(CONTEXT, ORG, MATCH, (access_path(permissions=permissions),))
    assert (result.can_view, result.can_operate) == expected


@pytest.mark.parametrize("role, assigned, expected", [
    ("owner", (), True), ("administrator", (), True), ("operator", (), True),
    ("referee", (MATCH,), True), ("referee", (), False),
    ("referee", (OTHER,), False), ("viewer", (), False),
    ("viewer", (MATCH,), True),
])
def test_access_requires_an_independent_valid_path(role, assigned, expected):
    assert policy.evaluate_access(CONTEXT, ORG, MATCH, (access_path(role, assigned=assigned),)) == policy.LiveCapabilities(expected, expected)


def test_access_multi_role_does_not_combine_permission_with_another_assignment():
    paths = (access_path("referee"), access_path("viewer", (), (MATCH,)))
    assert policy.evaluate_access(CONTEXT, ORG, MATCH, paths) == policy.LiveCapabilities()
    assert policy.evaluate_access(CONTEXT, ORG, MATCH, paths + (access_path(),)) == policy.LiveCapabilities(True, True)
    assert policy.evaluate_access(CONTEXT, ORG, MATCH, (access_path("viewer", ()),)) == policy.LiveCapabilities()


@pytest.mark.parametrize("context", [
    replace(CONTEXT, organization_id=OTHER), replace(CONTEXT, organization_id=None),
    replace(CONTEXT, organization_user_id=None), replace(CONTEXT, active=False),
])
def test_access_incomplete_or_foreign_context_fails_closed(context):
    assert policy.evaluate_access(context, ORG, MATCH, (access_path(),)) == policy.LiveCapabilities()


def test_access_empty_and_foreign_paths_fail_closed():
    assert policy.evaluate_access(CONTEXT, ORG, MATCH, ()) == policy.LiveCapabilities()
    paths = (replace(access_path(), organization_id=OTHER), replace(access_path(), organization_user_id=OTHER))
    assert policy.evaluate_access(CONTEXT, ORG, MATCH, paths) == policy.LiveCapabilities()


NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def reference(**changes):
    return replace(policy.ClockReference(MATCH, 1, 123_456, "running", NOW), **changes)


def test_observe_clock_without_reference():
    assert policy.observe_clock(None, NOW) == policy.ClockObservation(None, None, "not_started", NOW)


@pytest.mark.parametrize("delta, expected", [(0, 0), (876_543, 0), (876_544, 1), (1_876_544, 2), (-1_000_000, 0)])
def test_observe_clock_running_uses_integer_microseconds(delta, expected):
    assert policy.observe_clock(reference(), NOW + timedelta(microseconds=delta)).elapsed_seconds == expected


def test_observe_clock_paused_never_advances_or_mutates_reference():
    ref = reference(state="paused", anchor_at=None, elapsed_us=1_999_999)
    before = replace(ref)
    assert policy.observe_clock(ref, NOW).elapsed_seconds == 1
    assert policy.observe_clock(ref, NOW + timedelta(days=10)).elapsed_seconds == 1
    assert ref == before


@pytest.mark.parametrize("ref, observed", [
    (None, NOW.replace(tzinfo=None)),
    (reference(anchor_at=NOW.replace(tzinfo=None)), NOW),
    (reference(anchor_at=NOW.astimezone(timezone(timedelta(hours=1)))), NOW),
    (reference(state="paused"), NOW), (reference(anchor_at=None), NOW),
    (reference(elapsed_us=-1), NOW), (reference(segment_number=0), NOW),
])
def test_observe_clock_rejects_invalid_reference_or_non_utc_time(ref, observed):
    with pytest.raises(ValueError):
        policy.observe_clock(ref, observed)


SEGMENT = policy.SegmentFacts("live", MATCH, 1, True)


def clock_command(kind, **body):
    return TypeAdapter(LiveCommand).validate_python({"type": kind, "command_id": uuid4(), "expected_revision": 0, **body})


def test_control_clock_start_pause_resume_retains_fractional_microseconds():
    ref = policy.reduce_clock(None, clock_command("start_clock", segment_id=MATCH), NOW, SEGMENT)
    assert ref == reference(elapsed_us=0)
    for index in range(1, 11):
        at = NOW + timedelta(microseconds=index * 123_456)
        ref = policy.reduce_clock(ref, clock_command("pause_clock"), at, SEGMENT)
        assert ref.elapsed_us == index * 123_456
        assert ref.anchor_at is None
        ref = policy.reduce_clock(ref, clock_command("resume_clock"), at, SEGMENT)
        assert ref.anchor_at == at
    assert policy.observe_clock(ref, at).elapsed_seconds == 1


@pytest.mark.parametrize("running", [True, False])
def test_control_clock_correction_changes_only_reference(running):
    original = reference() if running else reference(state="paused", anchor_at=None)
    facts = [{"minute": 12, "added_minute": 3, "segment_id": MATCH}]
    before = [dict(fact) for fact in facts]
    at = NOW + timedelta(seconds=30)
    updated = policy.reduce_clock(original, clock_command("correct_clock", segment_id=MATCH, elapsed_us=7_654_321), at, SEGMENT)
    assert updated.elapsed_us == 7_654_321
    assert updated.state == original.state
    assert updated.anchor_at == (at if running else None)
    assert original == (reference() if running else reference(state="paused", anchor_at=None))
    assert facts == before


def test_control_clock_new_segment_requires_explicit_start():
    next_segment = policy.SegmentFacts("live", OTHER, 2, True)
    paused = reference(state="paused", anchor_at=None)
    updated = policy.reduce_clock(paused, clock_command("start_clock", segment_id=OTHER), NOW, next_segment)
    assert updated == policy.ClockReference(OTHER, 2, 0, "running", NOW)


@pytest.mark.parametrize("ref, command, segment", [
    (None, clock_command("pause_clock"), SEGMENT),
    (None, clock_command("resume_clock"), SEGMENT),
    (None, clock_command("correct_clock", segment_id=MATCH, elapsed_us=0), SEGMENT),
    (reference(), clock_command("start_clock", segment_id=MATCH), SEGMENT),
    (reference(), clock_command("resume_clock"), SEGMENT),
    (reference(state="paused", anchor_at=None), clock_command("pause_clock"), SEGMENT),
    (reference(), clock_command("correct_clock", segment_id=OTHER, elapsed_us=0), SEGMENT),
    (reference(), clock_command("pause_clock"), replace(SEGMENT, active=False)),
    (reference(), clock_command("pause_clock"), replace(SEGMENT, segment_id=OTHER)),
    (None, clock_command("start_clock", segment_id=MATCH), replace(SEGMENT, segment_number=0)),
    *[(reference(), clock_command(kind, **body), replace(SEGMENT, match_status="suspended")) for kind, body in [
        ("start_clock", {"segment_id": MATCH}), ("pause_clock", {}), ("resume_clock", {}),
        ("correct_clock", {"segment_id": MATCH, "elapsed_us": 0}),
    ]],
])
def test_control_clock_rejects_incompatible_state_or_segment(ref, command, segment):
    with pytest.raises(ValueError):
        policy.reduce_clock(ref, command, NOW, segment)


def test_control_clock_rejects_naive_time():
    with pytest.raises(ValueError):
        policy.reduce_clock(reference(), clock_command("pause_clock"), NOW.replace(tzinfo=None), SEGMENT)


TRANSITION = policy.TransitionFacts(True, MATCH, OTHER)


def test_transition_full_lifecycle_preserves_segment_and_draft():
    draft = ("accepted-fact",)
    live = policy.decide_live_transition(policy.LiveState("scheduled"), "start", TRANSITION, NOW)
    assert live == policy.LiveState("live")
    live = replace(live, clock=reference())
    suspended = policy.decide_live_transition(live, "suspend", TRANSITION, NOW + timedelta(microseconds=876_544))
    assert suspended == policy.LiveState("suspended", reference(state="paused", anchor_at=None, elapsed_us=1_000_000))
    resumed = policy.decide_live_transition(suspended, "resume", TRANSITION, NOW + timedelta(days=2))
    assert resumed == replace(suspended, status="live")
    assert resumed.clock.segment_id == MATCH
    assert draft == ("accepted-fact",)
    assert live.clock == reference()


@pytest.mark.parametrize("clock", [None, reference(state="paused", anchor_at=None)])
def test_transition_suspend_and_resume_without_a_running_clock(clock):
    suspended = policy.decide_live_transition(policy.LiveState("live", clock), "suspend", TRANSITION, NOW)
    assert suspended.clock == clock
    assert policy.decide_live_transition(suspended, "resume", TRANSITION, NOW).clock == clock


@pytest.mark.parametrize("facts", [
    replace(TRANSITION, version_published=False), replace(TRANSITION, home_team_id=None),
    replace(TRANSITION, away_team_id=None), replace(TRANSITION, away_team_id=MATCH),
    replace(TRANSITION, report_confirmed=True),
])
@pytest.mark.parametrize("current, command", [("scheduled", "start"), ("live", "suspend"), ("suspended", "resume")])
def test_transition_rejects_unavailable_match_facts(facts, current, command):
    with pytest.raises(ValueError):
        policy.decide_live_transition(policy.LiveState(current), command, facts, NOW)


@pytest.mark.parametrize("current", ["finished", "walkover", "cancelled", "abandoned", "postponed", "unknown"])
@pytest.mark.parametrize("command", ["start", "suspend", "resume"])
def test_transition_rejects_terminal_and_unknown_states(current, command):
    with pytest.raises(ValueError):
        policy.decide_live_transition(policy.LiveState(current), command, TRANSITION, NOW)


@pytest.mark.parametrize("current, command", [("live", "start"), ("scheduled", "resume"), ("suspended", "suspend"), ("live", "close")])
def test_transition_rejects_wrong_order(current, command):
    with pytest.raises(ValueError):
        policy.decide_live_transition(policy.LiveState(current), command, TRANSITION, NOW)


def test_transition_requires_injected_utc_time_even_without_clock():
    with pytest.raises(ValueError):
        policy.decide_live_transition(policy.LiveState("scheduled"), "start", TRANSITION, NOW.replace(tzinfo=None))


@pytest.mark.parametrize("status, command", [("scheduled", "start"), ("suspended", "resume")])
def test_transition_rejects_impossible_running_clock(status, command):
    with pytest.raises(ValueError):
        policy.decide_live_transition(policy.LiveState(status, reference()), command, TRANSITION, NOW)


def goal(kind="goal", **changes):
    return LiveEventPayload.model_validate({
        "event_type": kind, "client_event_id": str(uuid4()), "team_id": MATCH,
        "player_id": MEMBER, "minute": 1, "segment_id": ORG, **changes,
    })


def score(events=(), rules=None, teams=(MATCH, OTHER)):
    return policy.derive_provisional_score(tuple(events), rules or deepcopy(DEFAULT_RULES_CONFIG), teams)


def test_provisional_score_empty_and_non_scoring_facts_are_zero():
    assert score() == (0, 0)
    assert score([goal("yellow_card"), goal("red_card"), goal("foul")]) == (0, 0)


def test_provisional_score_counts_goals_own_goals_and_in_play_penalties():
    events = [goal(), goal("penalty_goal"), goal("own_goal", beneficiary_team_id=OTHER)]
    before = deepcopy(events)
    assert score(events) == (2, 1)
    assert events == before
    assert score([goal("own_goal", team_id=OTHER, beneficiary_team_id=MATCH)]) == (1, 0)


def test_provisional_score_rebuilds_after_correction_and_removal():
    first, second = goal(), goal(team_id=OTHER)
    assert score([first, second]) == (1, 1)
    corrected = second.model_copy(update={"team_id": MATCH})
    assert score([first, corrected]) == (2, 0)
    assert score([corrected]) == (1, 0)
    assert score() == (0, 0)


@pytest.mark.parametrize("events, teams", [
    ([goal(team_id=ORG)], (MATCH, OTHER)),
    ([goal("foul", team_id=ORG)], (MATCH, OTHER)),
    ([goal("own_goal", beneficiary_team_id=ORG)], (MATCH, OTHER)),
    ([], (MATCH, MATCH)),
])
def test_provisional_score_rejects_incompatible_teams(events, teams):
    with pytest.raises(ValueError):
        score(events, teams=teams)


def test_provisional_score_uses_existing_config_validation_without_new_sporting_constants():
    rules = deepcopy(DEFAULT_RULES_CONFIG)
    rules["stage_defaults"]["regular_time_minutes"] = 7
    before = deepcopy(rules)
    assert score([goal(minute=0)], rules=rules) == (1, 0)
    assert rules == before
    rules["stage_defaults"]["regular_time_minutes"] = 0
    with pytest.raises(ValueError):
        score(rules=rules)


def result(**changes):
    return LiveResultDTO.model_validate({"resolution_type": "regular", "home_score_regular": 1, "away_score_regular": 0, **changes})


def fingerprint(events=(), candidate=None, revision=1):
    return policy.review_fingerprint(tuple(events), candidate or result(), revision)


def test_review_fingerprint_is_canonical_and_stable_for_distinct_event_times():
    first, second = goal(minute=5), goal("yellow_card", minute=2)
    before = deepcopy([first, second])
    digest = fingerprint([first, second])
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest == fingerprint([second, first])
    assert [first, second] == before
    upper = first.model_copy(update={"client_event_id": first.client_event_id.upper()})
    assert fingerprint([upper, second]) == digest


def test_review_fingerprint_preserves_existing_payload_order_for_ties():
    first, second = goal(), goal("yellow_card")
    assert fingerprint([first, second]) != fingerprint([second, first])


def test_review_fingerprint_invalidates_subsets_removed_corrected_result_and_revision():
    first, second = goal(), goal("yellow_card")
    digest = fingerprint([first, second])
    assert digest != fingerprint([first])
    assert digest != fingerprint([])
    assert digest != fingerprint([first, second.model_copy(update={"minute": 2})])
    assert digest != fingerprint([first, second], result(home_score_regular=2))
    assert digest != fingerprint([first, second], revision=2)
    assert fingerprint([]) == fingerprint([])


def test_review_fingerprint_ignores_clock_observation_and_controls():
    events = (goal(),)
    digest = fingerprint(events)
    ref = reference()
    assert policy.observe_clock(ref, NOW) != policy.observe_clock(ref, NOW + timedelta(seconds=2))
    corrected = policy.reduce_clock(ref, clock_command("correct_clock", segment_id=MATCH, elapsed_us=0), NOW, SEGMENT)
    assert corrected != ref
    assert fingerprint(events) == digest


@pytest.mark.parametrize("revision", [-1, True, 1.5])
def test_review_fingerprint_rejects_invalid_revision(revision):
    with pytest.raises(ValueError):
        fingerprint(revision=revision)


def test_review_fingerprint_rejects_duplicate_fact_identities():
    event = goal()
    with pytest.raises(ValueError):
        fingerprint([event, event])
