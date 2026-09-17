from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.matches.schemas import MatchEventPayload, MatchLineupEntry, SaveMatchLineupRequest
from app.modules.tournaments.schemas import (
    CreateMatchRequest,
    CreateRosterPlayerRequest,
    PublicMatchResponse,
    PublicStageResponse,
    PublicTournamentResponse,
)


def test_own_goal_requires_a_different_beneficiary():
    with pytest.raises(ValidationError):
        MatchEventPayload(
            client_event_id="event-1",
            event_type="own_goal",
            team_id=uuid4(),
            player_id=uuid4(),
            minute=12,
            segment_id=uuid4(),
        )


def test_lineup_rejects_duplicate_rosters():
    roster_id = uuid4()
    with pytest.raises(ValidationError):
        SaveMatchLineupRequest(
            segment_id=uuid4(),
            entries=[
                {"roster_id": roster_id, "role": "starter"},
                {"roster_id": roster_id, "role": "substitute"},
            ],
        )


def test_substitute_cannot_have_a_tactical_position():
    with pytest.raises(ValidationError):
        MatchLineupEntry(roster_id=uuid4(), role="substitute", position_slot="ST")


def test_lineup_accepts_two_distinct_team_formations():
    request = SaveMatchLineupRequest(
        segment_id=uuid4(),
        entries=[{"roster_id": uuid4(), "role": "starter"}],
        team_lineups=[
            {"team_id": uuid4(), "formation_code": "4-3-3"},
            {"team_id": uuid4(), "formation_code": "4-4-2"},
        ],
    )

    assert len(request.team_lineups) == 2


def test_roster_rejects_future_birth_date():
    with pytest.raises(ValidationError):
        CreateRosterPlayerRequest(
            team_id=uuid4(),
            first_name="Future",
            last_name="Player",
            national_id="future-1",
            birth_date=date.today() + timedelta(days=1),
            dorsal_number=1,
        )


def test_roster_rejects_client_supplied_photo_url():
    with pytest.raises(ValidationError, match="endpoint de fotos"):
        CreateRosterPlayerRequest(
            team_id=uuid4(),
            first_name="Photo",
            last_name="Player",
            national_id="photo-1",
            birth_date=date(2000, 1, 2),
            dorsal_number=1,
            photo_url="https://example.com/player.jpg",
        )


def test_match_requires_a_scheduled_datetime():
    with pytest.raises(ValidationError):
        CreateMatchRequest(version_id=uuid4(), stage_id=uuid4())


def test_match_rejects_a_naive_scheduled_datetime():
    with pytest.raises(ValidationError):
        CreateMatchRequest(
            version_id=uuid4(),
            stage_id=uuid4(),
            match_date=datetime(2026, 9, 7, 15, 30),
        )


def test_public_tournament_response_exposes_ordered_stage_metadata():
    league = PublicStageResponse(
        id=uuid4(),
        name="Liga",
        stage_type="swiss",
        stage_order=1,
    )
    knockout = PublicStageResponse(
        id=uuid4(),
        name="Playoffs",
        stage_type="single_elimination",
        stage_order=2,
    )

    response = PublicTournamentResponse(
        id=uuid4(),
        name="Copa",
        season="2026",
        start_date=date(2026, 9, 7),
        status="published",
        stages=[league, knockout],
    )

    assert [stage.stage_type for stage in response.stages] == ["swiss", "single_elimination"]
    assert [stage.stage_order for stage in response.stages] == [1, 2]


def test_public_match_response_exposes_bracket_code():
    response = PublicMatchResponse(
        id=uuid4(),
        tournament_id=uuid4(),
        stage_id=uuid4(),
        stage_name="Playoffs",
        stage_order=1,
        bracket_code="QF1",
        status="finished",
    )

    assert response.bracket_code == "QF1"
