from uuid import uuid4

from app.modules.standings.head_to_head import MatchRecord, resolve_head_to_head


def match(home, away, home_score, away_score, winner=None, finished=True):
    return MatchRecord(home, away, home_score, away_score, finished, winner)


def test_head_to_head_orders_complete_single_round_mini_table():
    team_a, team_b, team_c = uuid4(), uuid4(), uuid4()
    matches = [
        match(team_a, team_b, 2, 0, team_a),
        match(team_b, team_c, 1, 0, team_b),
        match(team_c, team_a, 3, 0, team_c),
    ]

    assert resolve_head_to_head({team_a, team_b, team_c}, matches, 1) == [team_c, team_a, team_b]


def test_head_to_head_skips_incomplete_mini_table_and_preserves_order():
    team_a, team_b, team_c = uuid4(), uuid4(), uuid4()
    matches = [
        match(team_a, team_b, 1, 0, team_a),
        match(team_b, team_c, 1, 0, team_b),
    ]
    fallback = [team_b, team_c, team_a]

    assert resolve_head_to_head({team_a, team_b, team_c}, matches, 1, fallback_order=fallback) == fallback


def test_head_to_head_requires_both_legs_for_double_round_robin():
    team_a, team_b = uuid4(), uuid4()
    matches = [
        match(team_a, team_b, 1, 0, team_a),
        match(team_b, team_a, 2, 0, team_b),
    ]

    assert resolve_head_to_head({team_a, team_b}, matches, 2) == [team_b, team_a]


def test_head_to_head_requires_each_pair_to_have_the_expected_rounds():
    team_a, team_b, team_c = uuid4(), uuid4(), uuid4()
    matches = [
        match(team_a, team_b, 1, 0, team_a),
        match(team_a, team_b, 2, 0, team_a),
        match(team_b, team_c, 1, 0, team_b),
    ]

    assert resolve_head_to_head(
        {team_a, team_b, team_c}, matches, 1, fallback_order=[team_c, team_a, team_b]
    ) == [team_c, team_a, team_b]


def test_head_to_head_uses_configured_points_and_penalty_winner():
    team_a, team_b = uuid4(), uuid4()
    matches = [match(team_a, team_b, 1, 1, team_a)]

    assert resolve_head_to_head(
        {team_a, team_b},
        matches,
        1,
        points_system={"win": 2, "draw": 0, "loss": 0},
    ) == [team_a, team_b]
