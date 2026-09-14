from collections import Counter
from uuid import uuid4

from app.modules.matches.formations import FORMATION_SLOTS
from scripts.seed_demo import (
    ADVANCEMENT_SPECS,
    MATCH_SPECS,
    PLAYER_SPECS,
    RosterRecord,
    TEAM_SPECS,
    _goal_events,
    validate_demo_definition,
)


def test_demo_definition_has_a_complete_eight_team_bracket():
    validate_demo_definition()

    assert len(TEAM_SPECS) == 8
    assert len(MATCH_SPECS) == 7
    assert len(ADVANCEMENT_SPECS) == 6
    assert [match.code for match in MATCH_SPECS[:4]] == ["QF1", "QF2", "QF3", "QF4"]
    assert [match.code for match in MATCH_SPECS[4:]] == ["SF1", "SF2", "FINAL"]


def test_demo_has_twelve_players_and_valid_formations_per_team():
    players_by_team = Counter(player.team_code for player in PLAYER_SPECS)

    assert players_by_team == {team.code: 12 for team in TEAM_SPECS}
    assert all(
        formation in FORMATION_SLOTS
        for match in MATCH_SPECS[:4]
        for formation in (match.home_formation, match.away_formation)
    )
    assert all(
        sorted(player.dorsal_number for player in PLAYER_SPECS if player.team_code == team.code)
        == list(range(1, 13))
        for team in TEAM_SPECS
    )


def test_demo_goal_events_match_the_declared_quarterfinal_score():
    match = MATCH_SPECS[3]
    home_team_id = uuid4()
    away_team_id = uuid4()
    home_players = tuple(
        RosterRecord(roster_id=uuid4(), player_id=uuid4(), dorsal_number=index + 1)
        for index in range(12)
    )
    away_players = tuple(
        RosterRecord(roster_id=uuid4(), player_id=uuid4(), dorsal_number=index + 1)
        for index in range(12)
    )

    events = _goal_events(
        match,
        uuid4(),
        home_team_id,
        away_team_id,
        home_players,
        away_players,
    )

    assert len(events) == 5
    assert Counter(event.team_id for event in events) == {
        home_team_id: match.home_score,
        away_team_id: match.away_score,
    }
