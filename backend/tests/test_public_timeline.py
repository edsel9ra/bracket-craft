"""Funciones puras de la cronología pública del partido (spec 037, T2)."""

import pytest

from app.modules.tournaments.public_timeline import (
    build_public_timeline,
    public_player_names,
    public_red_card_type,
    timeline_availability,
)

HOME, AWAY, OTHER = "team-home", "team-away", "team-other"
S1, S2, S3 = "seg-1", "seg-2", "seg-3"
SEGMENTS = [
    {"id": S1, "match_id": "m1", "segment_number": 1},
    {"id": S2, "match_id": "m1", "segment_number": 2},
]
NAMES = public_player_names(
    [
        {"player_id": f"p{i}", "first_name": f"Nombre{i}", "last_name": f"Apellido{i}",
         "dorsal_number": i, "photo_url": "x"}
        for i in range(1, 9)
    ]
)


def match(home=0, away=0, status="finished", resolution="regular", **extra):
    return {"id": "m1", "status": status, "resolution_type": resolution, "home_team_id": HOME,
            "away_team_id": AWAY, "home_score": home, "away_score": away, **extra}


def event(eid, etype, team=HOME, player="p1", minute=10, added=0, segment=S1, **extra):
    return {"id": eid, "match_id": "m1", "event_type": etype, "team_id": team, "player_id": player,
            "minute": minute, "added_minute": added, "segment_id": segment, "is_voided": False,
            "metadata": {}, **extra}


def build(events, m=None, segments=SEGMENTS):
    return build_public_timeline(m or match(), events, segments, NAMES)


@pytest.mark.parametrize(
    ("status", "resolution", "expected"),
    [
        ("scheduled", None, "pending"),
        ("live", None, "pending"),
        ("suspended", None, "pending"),
        ("finished", "regular", "available"),
        ("finished", "extra_time", "available"),
        ("finished", "penalties", "available"),
        ("finished", None, "available"),
        ("finished", "walkover", "not_played"),
        ("finished", "administrative", "not_played"),
        ("administrative_resolution", "administrative", "not_played"),
    ],
)
def test_availability_by_status_and_resolution(status, resolution, expected):
    assert timeline_availability(status, resolution) == expected


@pytest.mark.parametrize("status", ["live", "suspended", "scheduled"])
def test_pending_match_never_publishes_events(status):
    result = build([event("e1", "goal")], match(1, 0, status=status, resolution=None))
    assert result == {"match_id": "m1", "availability": "pending", "score_consistent": True,
                      "segment_numbers": [], "events": []}


def test_walkover_publishes_no_events():
    result = build([event("e1", "goal")], match(3, 0, resolution="walkover"))
    assert result["availability"] == "not_played" and result["events"] == []


def test_only_public_types_and_exact_event_keys():
    events = [
        event("e1", "goal", metadata={"assist_player_id": "p2"}, assist_player_id="p2"),
        event("e2", "foul", minute=11),
        event("e3", "yellow_card", minute=12),
    ]
    result = build(events, match(1, 0))
    assert [e["event_type"] for e in result["events"]] == ["goal", "yellow_card"]
    assert set(result["events"][0]) == {
        "event_type", "minute", "added_minute", "segment_number", "team_id",
        "beneficiary_team_id", "red_card_type", "player", "player_in",
    }
    assert result["events"][0]["player"] == {"player_id": "p1", "first_name": "Nombre1",
                                             "last_name": "Apellido1", "profile_available": False}
    assert "p2" not in repr(result)


def test_only_fouls_is_empty_available_timeline():
    result = build([event("e1", "foul")])
    assert result["availability"] == "available" and result["events"] == []
    assert result["score_consistent"] is True


def test_order_by_segment_minute_added_and_stable_tiebreak():
    events = [
        event("e4", "yellow_card", minute=5, segment=S2),
        event("e3", "yellow_card", minute=45, added=2),
        event("e2", "yellow_card", minute=45, added=1),
        event("e1b", "yellow_card", minute=10),
        event("e1a", "yellow_card", minute=10, player="p2"),
    ]
    first = build(events)
    second = build(list(reversed(events)))
    assert first == second
    assert [(e["segment_number"], e["minute"], e["added_minute"], e["player"]["player_id"])
            for e in first["events"]] == [
        (1, 10, 0, "p2"), (1, 10, 0, "p1"), (1, 45, 1, "p1"), (1, 45, 2, "p1"), (2, 5, 0, "p1"),
    ]
    assert first["segment_numbers"] == [1, 2]


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"red_card_type": "direct_red"}, "direct_red"),
        ({"red_card_type": "double_yellow_red"}, "double_yellow_red"),
        ('{"red_card_type": "direct_red"}', "direct_red"),
        ({}, None),
        ({"red_card_type": "otra"}, None),
        ({"red_card_type": ["direct_red"]}, None),
        ({"red_card_type": {"type": "direct_red"}}, None),
        ("no-json", None),
        (None, None),
    ],
)
def test_red_card_type_from_report_without_inference(metadata, expected):
    assert public_red_card_type("red_card", metadata) == expected
    assert public_red_card_type("yellow_card", metadata) is None


def test_own_goal_credits_beneficiary_and_infers_opponent():
    events = [
        event("e1", "own_goal", team=HOME, beneficiary_team_id=AWAY),
        event("e2", "own_goal", team=AWAY, player="p3", minute=20),
    ]
    result = build(events, match(1, 1))
    assert [e["beneficiary_team_id"] for e in result["events"]] == [AWAY, HOME]
    assert result["score_consistent"] is True


def test_own_goal_with_foreign_beneficiary_is_orphan():
    result = build([event("e1", "own_goal", beneficiary_team_id=OTHER)], match(0, 1))
    assert result["events"] == [] and result["score_consistent"] is False


def test_substitution_publishes_player_out_and_in():
    sub = event("e1", "substitution", player="p1", player_out_id="p1", player_in_id="p8")
    result = build([sub])
    item = result["events"][0]
    assert item["player"]["player_id"] == "p1"
    assert item["player_in"] == {"player_id": "p8", "first_name": "Nombre8", "last_name": "Apellido8",
                                 "profile_available": False}


def test_profile_available_marks_only_listed_players():
    """Spec 038 RF-009: el indicador sale del conjunto del torneo, sin inferirlo."""

    sub = event("e1", "substitution", player="p1", player_out_id="p1", player_in_id="p8")
    goal = event("e2", "goal", minute=30)
    result = build_public_timeline(match(1, 0), [sub, goal], SEGMENTS, NAMES, {"p8"})
    by_type = {item["event_type"]: item for item in result["events"]}
    assert by_type["substitution"]["player"]["profile_available"] is False
    assert by_type["substitution"]["player_in"]["profile_available"] is True
    assert by_type["goal"]["player"]["profile_available"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {"segment_id": S3},
        {"team_id": OTHER},
        {"player_id": "desconocido"},
        {"is_voided": True},
    ],
)
def test_orphan_or_voided_events_are_excluded_without_failing(bad):
    result = build([event("e1", "goal", **bad), event("e2", "goal", minute=30)], match(2, 0))
    assert len(result["events"]) == 1 and result["score_consistent"] is False


def test_substitution_with_unknown_player_in_is_orphan():
    sub = event("e1", "substitution", player_out_id="p1", player_in_id="nadie")
    assert build([sub])["events"] == []


def test_score_consistency_with_extra_time_excludes_shootout():
    events = [
        event("e1", "goal", minute=30),
        event("e2", "penalty_goal", team=AWAY, player="p3", minute=100, segment=S2),
    ]
    result = build(events, match(1, 1, resolution="penalties", home_penalties=4, away_penalties=3))
    assert result["score_consistent"] is True
    assert build(events[:1], match(1, 1))["score_consistent"] is False


def test_events_of_other_matches_and_segments_are_ignored():
    foreign = dict(event("e1", "goal"), match_id="m2")
    other_segment = {"id": "seg-x", "match_id": "m2", "segment_number": 9}
    result = build([foreign], segments=[*SEGMENTS, other_segment])
    assert result["events"] == [] and result["segment_numbers"] == [1, 2]
