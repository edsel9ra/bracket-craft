from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.tournaments.scheduling import (
    build_double_elimination_bracket,
    build_round_robin_schedule,
    build_single_elimination_bracket,
    build_swiss_pairings,
    distribute_groups,
)


START_DATE = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)


def team_ids(count: int) -> list[UUID]:
    return [UUID(int=index) for index in range(1, count + 1)]


def bracket_signature(bracket):
    return [
        (
            match.code,
            match.round_number,
            match.home.team_id,
            match.home.source_match_code,
            match.away.team_id,
            match.away.source_match_code,
            match.match_date,
        )
        for match in bracket.matches
    ]


def test_single_elimination_builds_complete_eight_team_bracket():
    bracket = build_single_elimination_bracket(
        team_ids(8),
        seed=42,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    assert bracket.bracket_size == 8
    assert bracket.round_count == 3
    assert [match.code for match in bracket.matches] == [
        "QF1",
        "QF2",
        "QF3",
        "QF4",
        "SF1",
        "SF2",
        "FINAL",
    ]
    assert len(bracket.advancement_links) == 6
    assert all(match.home.team_id or match.home.source_match_code for match in bracket.matches)
    assert all(match.away.team_id or match.away.source_match_code for match in bracket.matches)


def test_seed_reproduces_draw_and_dates():
    first = build_single_elimination_bracket(
        team_ids(8),
        seed=123,
        start_date=START_DATE,
        round_interval_days=5,
        match_interval_hours=3,
    )
    repeated = build_single_elimination_bracket(
        team_ids(8),
        seed=123,
        start_date=START_DATE,
        round_interval_days=5,
        match_interval_hours=3,
    )
    different = build_single_elimination_bracket(
        team_ids(8),
        seed=124,
        start_date=START_DATE,
        round_interval_days=5,
        match_interval_hours=3,
    )

    assert bracket_signature(first) == bracket_signature(repeated)
    assert bracket_signature(first) != bracket_signature(different)
    assert first.matches[4].match_date == START_DATE.replace(day=23)
    assert first.matches[-1].match_date == START_DATE.replace(day=28)


def test_three_team_bracket_resolves_one_bye_without_creating_one_sided_matches():
    bracket = build_single_elimination_bracket(
        team_ids(3),
        seed=7,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    assert bracket.bracket_size == 4
    assert bracket.round_count == 2
    assert len(bracket.matches) == 2
    assert len(bracket.advancement_links) == 1
    assert [match.code for match in bracket.matches] == ["SF1", "FINAL"]
    assert bracket.matches[-1].home.source_match_code == "SF1" or bracket.matches[-1].away.source_match_code == "SF1"
    assert all(match.home.team_id or match.home.source_match_code for match in bracket.matches)
    assert all(match.away.team_id or match.away.source_match_code for match in bracket.matches)


@pytest.mark.parametrize(
    "count, message",
    [
        (0, "dos equipos"),
        (1, "dos equipos"),
    ],
)
def test_bracket_requires_two_teams(count: int, message: str):
    with pytest.raises(ValueError, match=message):
        build_single_elimination_bracket(
            team_ids(count),
            seed=1,
            start_date=START_DATE,
            round_interval_days=7,
            match_interval_hours=2,
        )


def test_bracket_rejects_duplicate_teams():
    ids = team_ids(2)
    with pytest.raises(ValueError, match="repetidos"):
        build_single_elimination_bracket(
            [ids[0], ids[0]],
            seed=1,
            start_date=START_DATE,
            round_interval_days=7,
            match_interval_hours=2,
        )


def test_round_robin_supports_single_and_double_legs_without_duplicate_pairings():
    ids = team_ids(4)
    single = build_round_robin_schedule(
        ids,
        seed=9,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
        legs=1,
    )
    double = build_round_robin_schedule(
        ids,
        seed=9,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
        legs=2,
    )

    single_pairs = {frozenset((match.home_team_id, match.away_team_id)) for match in single.matches}
    double_pairs = [frozenset((match.home_team_id, match.away_team_id)) for match in double.matches]
    assert len(single.matches) == 6
    assert len(single_pairs) == 6
    assert len(double.matches) == 12
    assert all(double_pairs.count(pair) == 2 for pair in single_pairs)


def test_group_draw_places_one_selected_head_in_each_group():
    ids = team_ids(8)
    draw = distribute_groups(ids, group_count=2, seed=10, head_team_ids=ids[:2])

    assert len(draw.groups) == 2
    assert all(len(group) == 4 for group in draw.groups)
    assert {group[0] for group in draw.groups} == set(ids[:2])
    assert set().union(*draw.groups) == set(ids)


def test_swiss_pairings_do_not_repeat_rivals_across_rounds():
    ids = team_ids(8)
    prior_pairs = set()
    home_counts = {}
    away_counts = {}
    for round_number in range(1, 5):
        pairings = build_swiss_pairings(
            ids,
            standings=[],
            prior_pairs=prior_pairs,
            seed=round_number,
            round_number=round_number,
            home_counts=home_counts,
            away_counts=away_counts,
            home_target=2,
            away_target=2,
        )
        for pairing in pairings:
            if pairing.home_team_id is None:
                continue
            pair = frozenset((pairing.home_team_id, pairing.away_team_id))
            assert pair not in prior_pairs
            prior_pairs.add(pair)
            home_counts[pairing.home_team_id] = home_counts.get(pairing.home_team_id, 0) + 1
            away_counts[pairing.away_team_id] = away_counts.get(pairing.away_team_id, 0) + 1

    assert len(prior_pairs) == 16
    assert set(home_counts.values()) == {2}
    assert set(away_counts.values()) == {2}


def test_swiss_36_team_format_balances_four_home_and_four_away_matches():
    ids = team_ids(36)
    prior_pairs = set()
    home_counts = {}
    away_counts = {}

    for round_number in range(1, 9):
        pairings = build_swiss_pairings(
            ids,
            standings=[],
            prior_pairs=prior_pairs,
            seed=round_number,
            round_number=round_number,
            home_counts=home_counts,
            away_counts=away_counts,
            home_target=4,
            away_target=4,
        )
        for pairing in pairings:
            pair = frozenset((pairing.home_team_id, pairing.away_team_id))
            assert pair not in prior_pairs
            prior_pairs.add(pair)
            home_counts[pairing.home_team_id] = home_counts.get(pairing.home_team_id, 0) + 1
            away_counts[pairing.away_team_id] = away_counts.get(pairing.away_team_id, 0) + 1

    assert len(prior_pairs) == 144
    assert set(home_counts.values()) == {4}
    assert set(away_counts.values()) == {4}


def test_swiss_gives_an_odd_field_bye_to_the_lowest_ranked_team_first():
    ids = team_ids(5)
    standings = [
        {"team_id": team_id, "points": 10 - index, "won": 3 - index % 2, "rank": index + 1}
        for index, team_id in enumerate(ids)
    ]

    pairings = build_swiss_pairings(
        ids,
        standings=standings,
        prior_pairs=set(),
        seed=4,
        round_number=1,
        bye_counts={},
    )

    assert next(pairing.bye_team_id for pairing in pairings if pairing.bye_team_id) == ids[-1]


def test_double_elimination_builds_losers_bracket_and_reset_marker():
    bracket = build_double_elimination_bracket(
        team_ids(8),
        seed=12,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    assert bracket.reset_code == "GF2"
    assert bracket.matches[-1].code == "GF1"
    assert bracket.matches[-1].lane == "final"
    assert any(link.outcome == "loser" for link in bracket.advancement_links)
    assert len(bracket.matches) == 14
