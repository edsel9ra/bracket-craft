"""Pure substitution engine: on-field intervals, reentry, limits and balances.

These tests are database-free: they only exercise the deterministic rules of
RF-012 to RF-015 (initial XI, interval union with re-entry, red cards,
substitution validation, per-team substitution/window limits and the
per-segment balance projection). The closing service and the operation screen
consume the same functions, so a green suite here means one single source of
truth for the on-field state.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.rules_engine.substitutions import (
    Interval,
    LimitBalance,
    MatchEvent,
    OnFieldState,
    RosterEntry,
    Segment,
    SegmentBalance,
    SubstitutionError,
    SubstitutionErrorCode,
    SubstitutionLimits,
    TeamUsage,
    apply_red_card,
    apply_substitution,
    build_on_field,
    canonical_event_order,
    check_substitution_limits,
    has_lineup,
    remaining_limits,
    segment_balances,
    starter_player_ids,
    team_usage,
    validate_player_on_field,
    validate_roster_minutes,
    validate_substitution,
)

TEAM = UUID(int=1)
RIVAL = UUID(int=2)
SEGMENT_1 = UUID(int=501)
SEGMENT_2 = UUID(int=502)

DEFAULT_LIMITS = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=False)
NO_USAGE = TeamUsage(substitutions=0, windows=())


def starter(number: int, team: UUID = TEAM) -> UUID:
    """Starters are 1-11 for the home team and 201-211 for the rival."""

    return UUID(int=(number if team == TEAM else 200 + number))


def substitute(number: int, team: UUID = TEAM) -> UUID:
    """Substitutes are 101-103 for the home team and 301-303 for the rival."""

    return UUID(int=(100 + number if team == TEAM else 300 + number))


def starter_ids(count: int = 11, team: UUID = TEAM) -> list[UUID]:
    return [starter(index, team) for index in range(1, count + 1)]


def lineup(
    *,
    team: UUID = TEAM,
    starters: int = 11,
    substitutes: int = 3,
    valid: bool = True,
) -> list[RosterEntry]:
    entries = [
        RosterEntry(
            player_id=starter(index, team),
            team_id=team,
            role="starter",
            is_valid=valid,
        )
        for index in range(1, starters + 1)
    ]
    entries += [
        RosterEntry(
            player_id=substitute(index, team),
            team_id=team,
            role="substitute",
            is_valid=valid,
        )
        for index in range(1, substitutes + 1)
    ]
    return entries


def substitution_event(
    out_id: UUID,
    in_id: UUID,
    *,
    minute: int,
    added_minute: int = 0,
    team: UUID = TEAM,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="substitution",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_out_id=out_id,
        player_in_id=in_id,
        segment_id=segment_id,
    )


def red_card_event(
    player_id: UUID,
    *,
    minute: int,
    added_minute: int = 0,
    team: UUID = TEAM,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="red_card",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_id=player_id,
        segment_id=segment_id,
    )


def goal_event(
    player_id: UUID,
    *,
    minute: int,
    added_minute: int = 0,
    team: UUID = TEAM,
    segment_id: UUID = SEGMENT_1,
    index: int = 0,
) -> MatchEvent:
    return MatchEvent(
        event_type="goal",
        team_id=team,
        minute=minute,
        added_minute=added_minute,
        index=index,
        player_id=player_id,
        segment_id=segment_id,
    )


def error_code(callable_):
    with pytest.raises(SubstitutionError) as error:
        callable_()
    return error.value.code


# --- Interval primitives ----------------------------------------------------


def test_interval_is_half_open_from_entry_to_exit():
    interval = Interval(start=60, end=70)

    assert interval.contains(59) is False
    assert interval.contains(60) is True
    assert interval.contains(69) is True
    assert interval.contains(70) is False


def test_open_interval_has_no_exit():
    interval = Interval(start=0)

    assert interval.contains(0) is True
    assert interval.contains(120) is True


# --- Initial XI and lineup -------------------------------------------------


def test_initial_eleven_comes_from_the_valid_starters():
    roster = lineup()
    state = build_on_field(roster, [], TEAM)

    assert isinstance(state, OnFieldState)
    assert state.on_field == frozenset(starter_ids())
    assert state.bench() == frozenset(
        {substitute(1), substitute(2), substitute(3)}
    )
    assert state.ejected == frozenset()
    for player_id in starter_ids():
        assert state.intervals_for(player_id) == (Interval(start=0),)
        assert state.is_on_field(player_id) is True


def test_invalid_roster_entries_are_ignored():
    roster = lineup(valid=False)

    assert has_lineup(roster, TEAM) is False
    assert starter_player_ids(roster, TEAM) == ()
    assert error_code(lambda: build_on_field(roster, [], TEAM)) is SubstitutionErrorCode.NO_LINEUP


def test_team_without_lineup_or_starters_reports_no_lineup():
    assert has_lineup([], TEAM) is False
    with pytest.raises(SubstitutionError) as error:
        build_on_field([], [], TEAM)
    assert error.value.code is SubstitutionErrorCode.NO_LINEUP
    assert "planilla" in str(error.value)

    with pytest.raises(SubstitutionError):
        build_on_field(lineup(starters=0), [], TEAM)


def test_lineup_helpers_are_deterministic_and_team_scoped():
    roster = lineup() + lineup(team=RIVAL)

    assert has_lineup(roster, RIVAL) is True
    assert starter_player_ids(roster, TEAM) == tuple(sorted(starter_ids(), key=str))
    assert starter_player_ids(lineup(team=RIVAL), TEAM) == ()


# --- Substitutions and red cards ------------------------------------------


def test_substitution_closes_the_out_interval_and_opens_the_in_interval():
    out_id, in_id = starter(1), substitute(1)
    state = build_on_field(
        lineup(),
        [substitution_event(out_id, in_id, minute=60)],
        TEAM,
    )

    assert state.intervals_for(out_id) == (Interval(start=0, end=60),)
    assert state.intervals_for(in_id) == (Interval(start=60),)
    assert state.is_on_field(out_id) is False
    assert state.is_on_field(in_id) is True
    assert out_id not in state.on_field and in_id in state.on_field
    assert state.bench() == frozenset({substitute(2), substitute(3), out_id})


def test_apply_substitution_advances_the_state_without_touching_the_original():
    state = build_on_field(lineup(), [], TEAM)
    out_id, in_id = starter(2), substitute(2)

    updated = apply_substitution(state, out_id, in_id, 55)

    assert state.intervals_for(out_id) == (Interval(start=0),)
    assert updated.intervals_for(out_id) == (Interval(start=0, end=55),)
    assert updated.intervals_for(in_id) == (Interval(start=55),)
    assert updated.is_on_field(in_id) is True


def test_red_card_closes_the_interval_and_ejects_the_player():
    ejected = starter(3)
    state = build_on_field(lineup(), [red_card_event(ejected, minute=30)], TEAM)

    assert state.intervals_for(ejected) == (Interval(start=0, end=30),)
    assert state.is_ejected(ejected) is True
    assert state.is_on_field(ejected) is False
    assert ejected not in state.bench()


def test_red_card_does_not_create_an_interval_for_a_bench_player():
    benched = substitute(1)
    state = build_on_field(lineup(), [red_card_event(benched, minute=20)], TEAM)

    assert state.intervals_for(benched) == ()
    assert state.is_ejected(benched) is True
    assert state.is_on_field(benched) is False


def test_apply_red_card_matches_build_on_field():
    ejected = starter(4)
    built = build_on_field(lineup(), [red_card_event(ejected, minute=30, added_minute=2)], TEAM)
    applied = apply_red_card(build_on_field(lineup(), [], TEAM), ejected, 32)

    assert applied.intervals_for(ejected) == built.intervals_for(ejected)
    assert applied.ejected == built.ejected
    assert applied.on_field == built.on_field


def test_canonical_order_uses_minute_then_added_minute_then_acta_index():
    events = [
        goal_event(starter(1), minute=45, added_minute=0, index=9),
        goal_event(starter(2), minute=45, added_minute=0, index=2),
        goal_event(starter(3), minute=30, added_minute=5, index=1),
        goal_event(starter(4), minute=46, added_minute=0, index=0),
    ]

    ordered = canonical_event_order(events)

    assert [event.index for event in ordered] == [1, 2, 9, 0]
    assert [event.minute for event in ordered] == [30, 45, 45, 46]


def test_on_field_state_does_not_depend_on_the_input_event_order():
    out_id, in_id = starter(5), substitute(3)
    events = [
        substitution_event(out_id, in_id, minute=60, index=7),
        red_card_event(starter(6), minute=25, index=3),
        goal_event(starter(7), minute=10, index=1),
    ]

    forward = build_on_field(lineup(), events, TEAM)
    backward = build_on_field(lineup(), list(reversed(events)), TEAM)

    assert forward.on_field == backward.on_field
    assert forward.ejected == backward.ejected
    assert forward.intervals == backward.intervals


# --- Interval union and re-entry (RF-012, RF-014) --------------------------


def test_reentry_builds_a_union_of_intervals_and_validates_each_one():
    returning, first_substitute = starter(1), substitute(1)
    events = [
        substitution_event(returning, first_substitute, minute=60, index=1),
        substitution_event(first_substitute, returning, minute=70, index=2),
    ]

    state = build_on_field(lineup(), events, TEAM)

    assert state.intervals_for(returning) == (
        Interval(start=0, end=60),
        Interval(start=70),
    )
    # A goal at 65 belongs to the player who entered at 60, never to the one
    # who left at 60: the union of intervals, not a single interval.
    validate_player_on_field(state, first_substitute, 65)
    assert error_code(lambda: validate_player_on_field(state, returning, 65)) is (
        SubstitutionErrorCode.PLAYER_NOT_ON_FIELD
    )
    validate_player_on_field(state, returning, 70)
    validate_player_on_field(state, returning, 75)


def test_player_that_never_entered_has_no_interval_for_events():
    state = build_on_field(lineup(), [], TEAM)

    assert error_code(
        lambda: validate_player_on_field(state, substitute(1), 10)
    ) is SubstitutionErrorCode.PLAYER_NOT_ON_FIELD


def test_goal_before_entry_and_after_exit_are_rejected():
    out_id, in_id = starter(2), substitute(2)
    state = build_on_field(lineup(), [substitution_event(out_id, in_id, minute=60)], TEAM)

    assert error_code(lambda: validate_player_on_field(state, out_id, 61)) is (
        SubstitutionErrorCode.PLAYER_NOT_ON_FIELD
    )
    assert error_code(lambda: validate_player_on_field(state, in_id, 59)) is (
        SubstitutionErrorCode.PLAYER_NOT_ON_FIELD
    )
    validate_player_on_field(state, in_id, 87, 2)


def test_reentry_is_rejected_when_the_configuration_forbids_it():
    returning, in_id = starter(1), substitute(1)
    state = build_on_field(
        lineup(),
        [substitution_event(returning, in_id, minute=60)],
        TEAM,
    )

    assert error_code(
        lambda: validate_substitution(state, DEFAULT_LIMITS, NO_USAGE, in_id, returning)
    ) is SubstitutionErrorCode.REENTRY_NOT_ALLOWED


def test_reentry_is_accepted_when_the_configuration_allows_it():
    returning, in_id = starter(1), substitute(1)
    limits = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True)
    state = build_on_field(
        lineup(),
        [substitution_event(returning, in_id, minute=60)],
        TEAM,
    )
    usage = team_usage([substitution_event(returning, in_id, minute=60)], TEAM)

    validate_substitution(state, limits, usage, in_id, returning)

    updated = apply_substitution(state, in_id, returning, 70)
    assert updated.intervals_for(returning) == (Interval(start=0, end=60), Interval(start=70))


def test_reentry_still_requires_the_player_to_be_off_the_field():
    limits = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True)
    state = build_on_field(lineup(), [], TEAM)
    out_id, in_id = starter(1), substitute(1)

    validate_substitution(state, limits, NO_USAGE, out_id, in_id)

    state = apply_substitution(state, out_id, in_id, 60)
    # The substitute is already on the field: he cannot enter twice.
    assert error_code(
        lambda: validate_substitution(
            state,
            limits,
            TeamUsage(1, ((SEGMENT_1, 60, 0),)),
            starter(2),
            in_id,
        )
    ) is SubstitutionErrorCode.PLAYER_IN_ALREADY_ON_FIELD


# --- Substitution validation (RF-013, RF-014) ------------------------------


def test_substitution_requires_both_players_in_the_team_roster():
    state = build_on_field(lineup(), [], TEAM)

    assert error_code(
        lambda: validate_substitution(state, DEFAULT_LIMITS, NO_USAGE, UUID(int=999), substitute(1))
    ) is SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER
    assert error_code(
        lambda: validate_substitution(state, DEFAULT_LIMITS, NO_USAGE, starter(1), UUID(int=999))
    ) is SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER


def test_substitution_rejects_a_different_team():
    state = build_on_field(lineup(), [], TEAM)

    assert error_code(
        lambda: validate_substitution(
            state,
            DEFAULT_LIMITS,
            NO_USAGE,
            starter(1),
            substitute(1),
            team_id=RIVAL,
        )
    ) is SubstitutionErrorCode.TEAM_MISMATCH


def test_substitution_rejects_the_same_player():
    state = build_on_field(lineup(), [], TEAM)

    assert error_code(
        lambda: validate_substitution(state, DEFAULT_LIMITS, NO_USAGE, starter(1), starter(1))
    ) is SubstitutionErrorCode.SAME_PLAYER


def test_substitution_requires_the_outgoing_player_to_be_on_the_field():
    state = build_on_field(lineup(), [], TEAM)
    already_out = starter(1)
    state = apply_substitution(state, already_out, substitute(1), 30)

    assert error_code(
        lambda: validate_substitution(state, DEFAULT_LIMITS, NO_USAGE, already_out, substitute(2))
    ) is SubstitutionErrorCode.PLAYER_OUT_NOT_ON_FIELD


def test_ejected_players_cannot_leave_or_return():
    limits = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True)
    ejected = starter(5)
    state = build_on_field(lineup(), [red_card_event(ejected, minute=30)], TEAM)

    assert error_code(
        lambda: validate_substitution(state, limits, NO_USAGE, ejected, substitute(1))
    ) is SubstitutionErrorCode.PLAYER_EJECTED
    assert error_code(
        lambda: validate_substitution(state, limits, NO_USAGE, starter(1), ejected)
    ) is SubstitutionErrorCode.PLAYER_EJECTED


def test_valid_substitution_passes_with_a_fresh_substitute():
    state = build_on_field(lineup(), [], TEAM)

    validate_substitution(state, DEFAULT_LIMITS, NO_USAGE, starter(1), substitute(1))


# --- Usage, windows and limits (RF-015) ------------------------------------


def test_two_changes_in_the_same_segment_and_minute_share_one_window():
    events = [
        substitution_event(starter(1), substitute(1), minute=60, index=1),
        substitution_event(starter(2), substitute(2), minute=60, index=2),
    ]

    usage = team_usage(events, TEAM)

    assert usage.substitutions == 2
    assert usage.windows_used == 1
    assert usage.windows == ((SEGMENT_1, 60, 0),)


def test_a_different_added_minute_opens_a_new_window():
    events = [
        substitution_event(starter(1), substitute(1), minute=60, added_minute=0, index=1),
        substitution_event(starter(2), substitute(2), minute=60, added_minute=3, index=2),
    ]

    assert team_usage(events, TEAM).windows_used == 2


def test_a_different_segment_opens_a_new_window():
    events = [
        substitution_event(starter(1), substitute(1), minute=60, segment_id=SEGMENT_1, index=1),
        substitution_event(starter(2), substitute(2), minute=60, segment_id=SEGMENT_2, index=2),
    ]

    assert team_usage(events, TEAM).windows_used == 2


def test_usage_is_counted_per_team():
    events = [
        substitution_event(starter(1), substitute(1), minute=60, index=1),
        substitution_event(
            starter(1, RIVAL),
            substitute(1, RIVAL),
            minute=60,
            team=RIVAL,
            index=2,
        ),
        substitution_event(
            starter(2, RIVAL),
            substitute(2, RIVAL),
            minute=70,
            team=RIVAL,
            index=3,
        ),
    ]

    assert team_usage(events, TEAM) == TeamUsage(1, ((SEGMENT_1, 60, 0),))
    assert team_usage(events, RIVAL) == TeamUsage(
        2,
        ((SEGMENT_1, 60, 0), (SEGMENT_1, 70, 0)),
    )


def test_legacy_substitutions_without_out_and_in_do_not_count():
    legacy = MatchEvent(
        event_type="substitution",
        team_id=TEAM,
        minute=60,
        player_id=starter(1),
        segment_id=SEGMENT_1,
    )
    state = build_on_field(lineup(), [legacy], TEAM)

    assert team_usage([legacy], TEAM) == TeamUsage(0, ())
    assert state.on_field == frozenset(starter_ids())
    assert state.intervals_for(starter(1)) == (Interval(start=0),)


def test_max_per_team_limit_reports_the_remaining_balance():
    limits = SubstitutionLimits(max_per_team=2, max_windows=3, allow_reentry=False)
    usage = TeamUsage(2, ((SEGMENT_1, 60, 0), (SEGMENT_1, 70, 0)))
    state = build_on_field(lineup(), [], TEAM)

    with pytest.raises(SubstitutionError) as error:
        validate_substitution(state, limits, usage, starter(1), substitute(1))

    assert error.value.code is SubstitutionErrorCode.SUBSTITUTIONS_EXHAUSTED
    assert "sustituciones" in str(error.value)
    assert "2" in str(error.value)
    assert "saldo 0" in str(error.value)


def test_max_per_team_zero_disables_substitutions():
    limits = SubstitutionLimits(max_per_team=0, max_windows=3, allow_reentry=True)
    state = build_on_field(lineup(), [], TEAM)

    with pytest.raises(SubstitutionError) as error:
        validate_substitution(state, limits, NO_USAGE, starter(1), substitute(1))

    assert error.value.code is SubstitutionErrorCode.SUBSTITUTIONS_EXHAUSTED
    assert "saldo 0" in str(error.value)


def test_max_windows_limit_reports_the_remaining_balance():
    limits = SubstitutionLimits(max_per_team=5, max_windows=1, allow_reentry=False)
    usage = TeamUsage(1, ((SEGMENT_1, 60, 0),))
    state = build_on_field(lineup(), [], TEAM)

    with pytest.raises(SubstitutionError) as error:
        validate_substitution(state, limits, usage, starter(1), substitute(1))

    assert error.value.code is SubstitutionErrorCode.WINDOWS_EXHAUSTED
    assert "ventanas" in str(error.value)
    assert "saldo 0" in str(error.value)


def test_max_windows_zero_rejects_every_substitution():
    limits = SubstitutionLimits(max_per_team=5, max_windows=0, allow_reentry=False)
    state = build_on_field(lineup(), [], TEAM)

    assert error_code(
        lambda: validate_substitution(state, limits, NO_USAGE, starter(1), substitute(1))
    ) is SubstitutionErrorCode.WINDOWS_EXHAUSTED


def test_limits_are_checked_before_the_on_field_state():
    limits = SubstitutionLimits(max_per_team=0, max_windows=3, allow_reentry=False)
    state = build_on_field(lineup(), [], TEAM)

    # The outgoing player is not on the field either, but the exhausted limit
    # is the reported reason: max_per_team = 0 disables the whole operation.
    assert error_code(
        lambda: validate_substitution(state, limits, NO_USAGE, substitute(2), substitute(1))
    ) is SubstitutionErrorCode.SUBSTITUTIONS_EXHAUSTED


def test_remaining_limits_are_computed_and_never_negative():
    limits = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=True)
    usage = TeamUsage(2, ((SEGMENT_1, 60, 0),))
    balance = remaining_limits(limits, usage)

    assert isinstance(balance, LimitBalance)
    assert (balance.substitutions_used, balance.substitutions_remaining) == (2, 3)
    assert (balance.windows_used, balance.windows_remaining) == (1, 2)
    assert balance.is_exhausted is False

    overused = remaining_limits(
        limits,
        TeamUsage(
            7,
            (
                (SEGMENT_1, 10, 0),
                (SEGMENT_2, 20, 0),
                (SEGMENT_2, 30, 0),
                (SEGMENT_2, 40, 0),
            ),
        ),
    )
    assert (overused.substitutions_remaining, overused.windows_remaining) == (0, 0)
    assert overused.is_exhausted is True


def test_check_substitution_limits_accepts_usage_below_the_limits():
    check_substitution_limits(DEFAULT_LIMITS, TeamUsage(1, ((SEGMENT_1, 60, 0),)))

    with pytest.raises(SubstitutionError):
        check_substitution_limits(
            SubstitutionLimits(max_per_team=0, max_windows=3, allow_reentry=False),
            NO_USAGE,
        )


def test_limits_are_read_from_the_effective_substitutions_block():
    assert SubstitutionLimits.from_config({}) == DEFAULT_LIMITS
    assert SubstitutionLimits.from_config(
        {"max_per_team": 3, "max_windows": 2, "allow_reentry": True}
    ) == SubstitutionLimits(max_per_team=3, max_windows=2, allow_reentry=True)
    assert SubstitutionLimits.from_config({"max_per_team": 1}).max_windows == 3


# --- Per-segment balances (RF-016 projection) ------------------------------


def test_segment_balances_accumulate_by_segment_number_not_by_minute():
    first, second = Segment(id=SEGMENT_1, segment_number=1), Segment(id=SEGMENT_2, segment_number=2)
    events = [
        substitution_event(starter(1), substitute(1), minute=60, segment_id=SEGMENT_1, index=1),
        substitution_event(starter(2), substitute(2), minute=10, segment_id=SEGMENT_2, index=2),
        substitution_event(starter(3), substitute(3), minute=20, segment_id=SEGMENT_2, index=3),
    ]
    limits = SubstitutionLimits(max_per_team=5, max_windows=3, allow_reentry=False)

    # Deliberately reversed input: the projection sorts by segment_number.
    balances = segment_balances([second, first], events, [TEAM], limits)

    assert balances == (
        SegmentBalance(
            segment_id=SEGMENT_1,
            segment_number=1,
            team_id=TEAM,
            substitutions_remaining=4,
            substitution_windows_remaining=2,
        ),
        SegmentBalance(
            segment_id=SEGMENT_2,
            segment_number=2,
            team_id=TEAM,
            substitutions_remaining=2,
            substitution_windows_remaining=0,
        ),
    )


def test_segment_balances_cover_every_segment_and_team():
    segments = [
        Segment(id=SEGMENT_1, segment_number=1),
        Segment(id=SEGMENT_2, segment_number=2),
    ]
    events = [
        substitution_event(
            starter(1, RIVAL),
            substitute(1, RIVAL),
            minute=55,
            team=RIVAL,
            segment_id=SEGMENT_2,
            index=1,
        )
    ]

    balances = segment_balances(segments, events, [TEAM, RIVAL], DEFAULT_LIMITS)

    assert [(row.segment_number, row.team_id) for row in balances] == [
        (1, TEAM),
        (1, RIVAL),
        (2, TEAM),
        (2, RIVAL),
    ]
    assert balances[0].substitutions_remaining == 5
    assert balances[1].substitutions_remaining == 5
    assert balances[2].substitutions_remaining == 5
    assert balances[3].substitutions_remaining == 4


def test_segment_balances_ignore_legacy_and_foreign_segment_events():
    segments = [Segment(id=SEGMENT_1, segment_number=1)]
    legacy = MatchEvent(
        event_type="substitution",
        team_id=TEAM,
        minute=30,
        player_id=starter(1),
        segment_id=SEGMENT_1,
    )
    elsewhere = substitution_event(
        starter(1),
        substitute(1),
        minute=30,
        segment_id=SEGMENT_2,
    )

    balances = segment_balances(segments, [legacy, elsewhere], [TEAM], DEFAULT_LIMITS)

    assert balances == (
        SegmentBalance(
            segment_id=SEGMENT_1,
            segment_number=1,
            team_id=TEAM,
            substitutions_remaining=5,
            substitution_windows_remaining=3,
        ),
    )


# --- Roster minutes contrast (RF-012) --------------------------------------


def test_roster_minutes_are_contrasted_only_with_a_single_interval():
    out_id = starter(1)
    state = build_on_field(lineup(), [substitution_event(out_id, substitute(1), minute=60)], TEAM)

    validate_roster_minutes(state, out_id, entered_minute=None, left_minute=60)
    assert error_code(
        lambda: validate_roster_minutes(state, out_id, entered_minute=None, left_minute=70)
    ) is SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT

    returning = starter(2)
    reentry = build_on_field(
        lineup(),
        [
            substitution_event(returning, substitute(2), minute=60, index=1),
            substitution_event(substitute(2), returning, minute=70, index=2),
        ],
        TEAM,
    )
    # With re-entry the derived intervals prevail: the planilla is not compared.
    validate_roster_minutes(reentry, returning, entered_minute=10, left_minute=20)


def test_missing_roster_minutes_do_not_contradict_the_intervals():
    state = build_on_field(lineup(), [], TEAM)

    validate_roster_minutes(state, starter(1), entered_minute=None, left_minute=None)


def test_roster_minutes_without_intervals_are_rejected():
    state = build_on_field(lineup(), [], TEAM)
    unused = substitute(1)

    assert state.intervals_for(unused) == ()
    validate_roster_minutes(state, unused, entered_minute=None, left_minute=None)
    assert error_code(
        lambda: validate_roster_minutes(state, unused, entered_minute=60)
    ) is SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT
    assert error_code(
        lambda: validate_roster_minutes(state, unused, left_minute=60)
    ) is SubstitutionErrorCode.ROSTER_MINUTES_CONFLICT


# --- Mapping helpers -------------------------------------------------------


def test_match_event_can_be_built_from_a_row_mapping():
    event = MatchEvent.from_mapping(
        {
            "event_type": "substitution",
            "team_id": str(TEAM),
            "minute": 60,
            "added_minute": 2,
            "player_id": str(starter(1)),
            "player_out_id": str(starter(1)),
            "player_in_id": str(substitute(1)),
            "segment_id": str(SEGMENT_1),
        },
        index=4,
    )

    assert event.team_id == TEAM
    assert event.player_in_id == substitute(1)
    assert event.effective_minute == 62
    assert event.index == 4
    assert event.is_substitution_with_pair is True
