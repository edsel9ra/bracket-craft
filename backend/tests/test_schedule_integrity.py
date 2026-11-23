"""Pure checks for generated schedules before they are written (spec 042, RF-006)."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.modules.tournaments.pairings import max_meetings_per_pair
from app.modules.tournaments.schedule_integrity import (
    PlannedMatch,
    ScheduleIntegrityError,
    check_generated_schedule,
)
from app.modules.tournaments.scheduling import (
    build_double_elimination_bracket,
    build_round_robin_schedule,
    build_single_elimination_bracket,
    distribute_groups,
)

START = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
A, B, C, D = (uuid4() for _ in range(4))


def planned(code: str, home: UUID | None, away: UUID | None, group: UUID | None = None) -> PlannedMatch:
    return PlannedMatch(code=code, home_team_id=home, away_team_id=away, group_id=group)


def test_repeated_code_is_rejected_even_without_a_pair_limit():
    with pytest.raises(ScheduleIntegrityError) as error:
        check_generated_schedule([planned("SF1", A, B), planned("SF1", C, D)], max_meetings=None)
    assert error.value.kind == "code"
    assert error.value.code == "SF1"


def test_elimination_allows_repeated_pairs_and_empty_slots():
    check_generated_schedule(
        [planned("GF1", A, B), planned("GF2", B, A), planned("F1", None, None), planned("F2", None, None)],
        max_meetings=None,
    )


def test_pair_over_the_limit_is_rejected_regardless_of_orientation():
    with pytest.raises(ScheduleIntegrityError) as error:
        check_generated_schedule([planned("RR1-1", A, B), planned("RR2-1", B, A)], max_meetings=1)
    assert error.value.kind == "pair"
    assert error.value.pair == frozenset({A, B})


def test_two_legs_allow_the_reversed_meeting_but_not_a_third_one():
    two_legs = [planned("RR1-1", A, B), planned("RR2-1", B, A)]
    check_generated_schedule(two_legs, max_meetings=2)
    with pytest.raises(ScheduleIntegrityError):
        check_generated_schedule([*two_legs, planned("RR3-1", A, B)], max_meetings=2)


def test_pairs_are_counted_per_group():
    group_one, group_two = uuid4(), uuid4()
    check_generated_schedule(
        [planned("G1-1", A, B, group_one), planned("G2-1", A, B, group_two)], max_meetings=1
    )


def test_prior_pairs_are_added_to_the_planned_ones():
    check_generated_schedule([planned("SW2-1", A, C)], max_meetings=1, prior_pairs=[(None, A, B)])
    with pytest.raises(ScheduleIntegrityError) as error:
        check_generated_schedule([planned("SW2-1", B, A)], max_meetings=1, prior_pairs=[(None, A, B)])
    assert error.value.kind == "pair"


def test_matches_without_both_teams_never_count_as_a_pair():
    check_generated_schedule(
        [planned("SW2-1", A, None), planned("SW2-2", A, None)],
        max_meetings=1,
        prior_pairs=[(None, A, None)],
    )


def test_error_messages_are_the_planned_409_details():
    code_error = ScheduleIntegrityError("code", code="RR1-1")
    pair_error = ScheduleIntegrityError("pair", pair=frozenset({A, B}))
    assert code_error.detail == "El calendario generado repite el código de partido RR1-1"
    assert pair_error.detail == (
        "El calendario generado supera el máximo de enfrentamientos entre dos equipos de la fase"
    )


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 2**40])
@pytest.mark.parametrize("team_count", [3, 4, 7, 8])
@pytest.mark.parametrize("legs", [1, 2])
def test_current_round_robin_and_group_generators_pass(seed, team_count, legs):
    teams = [uuid4() for _ in range(team_count)]
    limit = max_meetings_per_pair("round_robin", legs)
    schedule = build_round_robin_schedule(
        teams, seed=seed, start_date=START, round_interval_days=7, match_interval_hours=2, legs=legs
    )
    check_generated_schedule(
        [planned(m.code, m.home_team_id, m.away_team_id) for m in schedule.matches], max_meetings=limit
    )

    if team_count >= 4:
        draw = distribute_groups(teams, group_count=2, seed=seed)
        plan = []
        for number, group_teams in enumerate(draw.groups, start=1):
            group_id = uuid4()
            group_schedule = build_round_robin_schedule(
                list(group_teams), seed=seed + number, start_date=START, round_interval_days=7,
                match_interval_hours=2, legs=legs, code_prefix=f"G{number}",
            )
            plan += [planned(m.code, m.home_team_id, m.away_team_id, group_id) for m in group_schedule.matches]
        check_generated_schedule(plan, max_meetings=max_meetings_per_pair("custom_group", legs))


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 2**40])
@pytest.mark.parametrize(
    ("builder", "team_count"),
    [
        *((build_single_elimination_bracket, count) for count in (2, 3, 5, 8, 13)),
        *((build_double_elimination_bracket, count) for count in (4, 8, 16)),
    ],
)
def test_current_elimination_generators_pass(seed, builder, team_count):
    bracket = builder(
        [uuid4() for _ in range(team_count)], seed=seed, start_date=START,
        round_interval_days=7, match_interval_hours=2,
    )
    plan = [planned(m.code, m.home.team_id, m.away.team_id) for m in bracket.matches]
    if bracket.reset_code is not None:
        plan.append(planned(bracket.reset_code, None, None))
    check_generated_schedule(plan, max_meetings=max_meetings_per_pair("single_elimination", None))
