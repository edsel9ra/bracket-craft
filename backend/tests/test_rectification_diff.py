from copy import deepcopy
from uuid import UUID

import pytest

from app.modules.rectifications.diff import diff_reports


def event(identity="a", **changes):
    return {"client_event_id": identity, "event_type": "goal", "minute": 10,
            "team_id": "home", "player_id": "player", "segment_id": "segment", **changes}


def test_empty_and_identical_reports():
    assert diff_reports({}, {}) == {"fields": [], "events": {"added": [], "removed": [], "changed": []}}
    report = {"home_score": 1, "events": [event()]}
    assert diff_reports(report, deepcopy(report))["fields"] == []
    assert diff_reports(report, deepcopy(report))["events"] == {"added": [], "removed": [], "changed": []}


def test_field_and_event_changes_are_complete_and_do_not_mutate_inputs():
    before = {"home_score": 1, "winner_team_id": "home", "events": [event(), event("b")]}
    after = {"home_score": 2, "winner_team_id": "away", "events": [event(minute=20), event("c")]}
    original = deepcopy((before, after))
    diff = diff_reports(before, after)
    assert diff["fields"] == [
        {"field": "home_score", "before": 1, "after": 2},
        {"field": "winner_team_id", "before": "home", "after": "away"},
    ]
    assert [e["client_event_id"] for e in diff["events"]["added"]] == ["c"]
    assert [e["client_event_id"] for e in diff["events"]["removed"]] == ["b"]
    assert diff["events"]["changed"] == [{"client_event_id": "a", "fields": [{"field": "minute", "before": 10, "after": 20}]}]
    assert (before, after) == original


def test_normalization_ignores_storage_fields_voided_events_order_and_uuid_types():
    identity = "aaaaaaaa-0000-4000-8000-000000000001"
    team = UUID("00000000-0000-4000-8000-000000000002")
    before = {"winner_team_id": team, "events": [event(identity, team_id=team,
        id="storage", metadata={}, added_minute=0), event("voided", is_voided=True), event("b")]}
    after = {"winner_team_id": str(team), "events": [event("b"), event(identity.upper(), team_id=str(team))]}
    assert diff_reports(before, after) == {"fields": [], "events": {"added": [], "removed": [], "changed": []}}


@pytest.mark.parametrize("field", ["resolution_type", "resolution_reason", "home_score_regular",
    "away_score_regular", "home_score", "away_score", "home_penalties", "away_penalties", "winner_team_id"])
def test_every_report_field_is_compared(field):
    assert diff_reports({field: None}, {field: "changed"})["fields"] == [{"field": field, "before": None, "after": "changed"}]


@pytest.mark.parametrize("field,value", [("assist_player_id", "assistant"), ("beneficiary_team_id", "away"),
    ("player_out_id", "out"), ("player_in_id", "in"), ("metadata", {"red_card_type": "direct_red"}),
    ("segment_id", "second"), ("added_minute", 1), ("team_id", "away"), ("player_id", "other"), ("event_type", "foul")])
def test_every_event_content_field_is_compared(field, value):
    result = diff_reports({"events": [event()]}, {"events": [event(**{field: value})]})
    assert result["events"]["changed"][0]["fields"][0]["field"] == field


def test_duplicate_event_id_is_rejected_not_silently_overwritten():
    with pytest.raises(ValueError, match="client_event_id"):
        diff_reports({"events": [event("a"), event("a")]}, {})


def test_historical_event_ids_are_case_sensitive_like_database_uniqueness():
    before = {"events": [event("A"), event("a", minute=11)]}
    after = {"events": [event("a", minute=20)]}
    difference = diff_reports(before, after)["events"]
    assert difference["added"] == []
    assert [row["client_event_id"] for row in difference["removed"]] == ["A"]
    assert difference["removed"][0]["minute"] == 10
    assert difference["changed"] == [{"client_event_id": "a",
        "fields": [{"field": "minute", "before": 11, "after": 20}]}]
    assert [row["client_event_id"] for row in diff_reports(before, {})["events"]["removed"]] == ["A", "a"]


def test_case_only_event_identity_change_is_removal_and_addition():
    difference = diff_reports({"events": [event("A")]}, {"events": [event("a")]})["events"]
    assert [row["client_event_id"] for row in difference["added"]] == ["a"]
    assert [row["client_event_id"] for row in difference["removed"]] == ["A"]
    assert difference["changed"] == []


def test_proposed_uuid_case_is_canonicalized_before_matching_existing_events():
    identity = "aaaaaaaa-0000-4000-8000-000000000001"
    difference = diff_reports({"events": [event(identity)]},
        {"events": [event(identity.upper(), minute=20)]})["events"]
    assert difference == {"added": [], "removed": [], "changed": [
        {"client_event_id": identity, "fields": [{"field": "minute", "before": 10, "after": 20}]}]}


def test_historical_uuid_case_is_not_canonicalized():
    identity = "AAAAAAAA-0000-4000-8000-000000000001"
    difference = diff_reports({"events": [event(identity)]}, {"events": [event(identity)]})["events"]
    assert [row["client_event_id"] for row in difference["removed"]] == [identity]
    assert [row["client_event_id"] for row in difference["added"]] == [identity.lower()]
    assert difference["changed"] == []


def test_duplicate_canonical_proposed_event_ids_are_rejected():
    identity = "aaaaaaaa-0000-4000-8000-000000000001"
    with pytest.raises(ValueError, match="client_event_id"):
        diff_reports({}, {"events": [event(identity), event(identity.upper())]})
