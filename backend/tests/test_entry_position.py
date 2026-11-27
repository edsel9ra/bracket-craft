"""Posición de entrada y penal atajado sin I/O (spec 052, T3: RF-008, RF-010, RF-015)."""

from uuid import uuid4

import pytest

from app.modules.matches.errors import ENTRY_POSITION_INVALID, EntryPositionInvalid
from app.modules.matches.live_policy import derive_provisional_score
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import validate_entry_positions
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from test_public_timeline import build, event, match as timeline_match

HOME, AWAY, SEGMENT = uuid4(), uuid4(), uuid4()


def substitution(position: str | None) -> MatchEventPayload:
    out_id, in_id = uuid4(), uuid4()
    return MatchEventPayload(
        client_event_id=str(uuid4()), event_type="substitution", team_id=HOME,
        player_id=out_id, player_out_id=out_id, player_in_id=in_id,
        player_in_position=position, minute=60, segment_id=SEGMENT,
    )


def report(*events: MatchEventPayload) -> CloseMatchReportDTO:
    return CloseMatchReportDTO(
        resolution_type="regular", home_score_regular=0, away_score_regular=0, events=list(events)
    )


def match_of(game_format: str | None) -> dict:
    config = {} if game_format is None else {"game_format": game_format}
    return {"rules_config": config}


@pytest.mark.parametrize(
    ("game_format", "position"),
    [("5v5", "ST"), ("5v5", "GK"), ("7v7", "LCB"), ("11v11", "LWB"), (None, "LWB"), ("9v9", None)],
)
def test_a_position_of_the_game_format_is_accepted(game_format, position):
    validate_entry_positions(report(substitution(position)), match_of(game_format))


@pytest.mark.parametrize(
    ("game_format", "position"), [("5v5", "LWB"), ("7v7", "CAM"), ("11v11", "SW"), (None, "XX")]
)
def test_a_position_outside_the_game_format_is_a_coded_422(game_format, position):
    with pytest.raises(EntryPositionInvalid) as rejected:
        validate_entry_positions(report(substitution("GK"), substitution(position)), match_of(game_format))

    assert rejected.value.status_code == 422
    assert rejected.value.code == ENTRY_POSITION_INVALID
    assert position not in str(rejected.value.detail)


def test_a_penalty_saved_never_changes_the_provisional_score():
    saved = MatchEventPayload(
        client_event_id=str(uuid4()), event_type="penalty_saved", team_id=AWAY,
        player_id=uuid4(), minute=70, segment_id=SEGMENT,
    )

    assert derive_provisional_score((saved, substitution("ST")), DEFAULT_RULES_CONFIG, (HOME, AWAY)) == (0, 0)


def test_the_public_timeline_hides_the_penalty_saved_and_the_entry_position():
    events = [
        event("e1", "goal"),
        event("e2", "penalty_saved", team="team-away", player="p3", minute=20),
        event("e3", "substitution", minute=60, player="p1", player_out_id="p1", player_in_id="p2",
              player_in_position="ST"),
    ]

    result = build(events, timeline_match(1, 0))

    assert [item["event_type"] for item in result["events"]] == ["goal", "substitution"]
    assert all("player_in_position" not in str(item) and "ST" not in str(item) for item in result["events"])
    assert result["score_consistent"] is True
