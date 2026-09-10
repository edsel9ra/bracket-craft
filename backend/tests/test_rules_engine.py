from uuid import UUID, uuid4

import pytest

from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import (
    compute_match_outcome,
    evaluate_suspensions,
    remap_stage_overrides,
    validate_rules_config,
)
from app.modules.rules_engine.schemas import CreateTournamentRequest, TournamentRulesConfig


def test_default_rules_are_valid():
    validate_rules_config(DEFAULT_RULES_CONFIG)


def test_stage_overrides_are_remapped_when_stage_ids_are_cloned():
    old_group = uuid4()
    old_final = uuid4()
    new_group = uuid4()
    new_final = uuid4()
    config = {
        **DEFAULT_RULES_CONFIG,
        "stage_overrides": {
            str(old_group): {"extra_time_enabled": True},
            str(old_final): {"penalties_enabled": True},
        },
    }

    cloned = remap_stage_overrides(config, {
        str(old_group): new_group,
        str(old_final): new_final,
    })

    assert cloned["stage_overrides"] == {
        str(new_group): {"extra_time_enabled": True},
        str(new_final): {"penalties_enabled": True},
    }
    assert config["stage_overrides"] == {
        str(old_group): {"extra_time_enabled": True},
        str(old_final): {"penalties_enabled": True},
    }


def test_tournament_request_uses_typed_default_rules():
    request = CreateTournamentRequest(name="Test", season="2026", start_date="2026-01-01")

    assert isinstance(request.rules_config, TournamentRulesConfig)
    validate_rules_config(request.rules_config.model_dump())


def test_penalties_use_score_after_extra_time():
    home = uuid4()
    away = uuid4()
    config = {
        **DEFAULT_RULES_CONFIG,
        "stage_defaults": {
            **DEFAULT_RULES_CONFIG["stage_defaults"],
            "penalties_enabled": True,
        },
    }
    outcome = compute_match_outcome(
        config,
        [],
        "penalties",
        home,
        away,
        1,
        1,
        2,
        2,
        4,
        3,
        home,
    )
    assert outcome.winner_team_id == home
    assert outcome.home_score == 2
    assert outcome.away_score == 2


def test_pipeline_requires_points_first():
    invalid = {**DEFAULT_RULES_CONFIG, "ranking_pipeline": [
        {"step": 1, "criterion": "goals_for", "params": {}},
    ]}
    with pytest.raises(ValueError):
        validate_rules_config(invalid)


def test_regular_match_cannot_report_extra_time_score():
    home = uuid4()
    away = uuid4()
    with pytest.raises(ValueError):
        compute_match_outcome(
            DEFAULT_RULES_CONFIG,
            [],
            "regular",
            home,
            away,
            1,
            0,
            2,
            0,
            None,
            None,
            home,
        )


def test_rules_reject_unknown_ranking_criterion():
    invalid = {
        **DEFAULT_RULES_CONFIG,
        "ranking_pipeline": [
            {"step": 1, "criterion": "unknown", "params": {}},
        ],
    }
    with pytest.raises(ValueError):
        validate_rules_config(invalid)


def test_head_to_head_requires_round_count():
    invalid = {
        **DEFAULT_RULES_CONFIG,
        "ranking_pipeline": [
            {"step": 1, "criterion": "points", "params": {}},
            {"step": 2, "criterion": "head_to_head", "params": {}},
        ],
    }
    with pytest.raises(ValueError):
        validate_rules_config(invalid)


def test_penalty_shootout_cannot_be_tied():
    home = uuid4()
    away = uuid4()
    config = {
        **DEFAULT_RULES_CONFIG,
        "stage_defaults": {
            **DEFAULT_RULES_CONFIG["stage_defaults"],
            "penalties_enabled": True,
        },
    }
    with pytest.raises(ValueError, match="debe tener un ganador"):
        compute_match_outcome(config, [], "penalties", home, away, 1, 1, 1, 1, 4, 4, away)


def test_match_report_rejects_duplicate_client_event_ids():
    team_id = uuid4()
    player_id = uuid4()
    segment_id = uuid4()
    event = MatchEventPayload(
        client_event_id="same-event",
        event_type="yellow_card",
        team_id=team_id,
        player_id=player_id,
        minute=10,
        segment_id=segment_id,
    )
    with pytest.raises(ValueError, match="client_event_id duplicados"):
        CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=0,
            away_score_regular=0,
            events=[event, event],
        )


def test_administrative_resolution_requires_a_non_empty_reason():
    with pytest.raises(ValueError, match="requiere una razón"):
        CloseMatchReportDTO(
            resolution_type="administrative",
            home_score_regular=0,
            away_score_regular=0,
            home_score=0,
            away_score=0,
            winner_team_id=uuid4(),
        )


def test_regular_resolution_does_not_accept_an_administrative_reason():
    with pytest.raises(ValueError, match="solo aplica"):
        CloseMatchReportDTO(
            resolution_type="regular",
            home_score_regular=1,
            away_score_regular=0,
            reason="Forfeit",
        )


def test_penalty_resolution_requires_a_tied_score_and_distinct_shootout_score():
    with pytest.raises(ValueError, match="empatado"):
        CloseMatchReportDTO(
            resolution_type="penalties",
            home_score_regular=1,
            away_score_regular=1,
            home_penalties=4,
            away_penalties=3,
            winner_team_id=uuid4(),
        )


def test_match_event_goals_must_match_the_reported_regular_score():
    home = uuid4()
    away = uuid4()
    event = MatchEventPayload(
        client_event_id="goal-1",
        event_type="goal",
        team_id=home,
        player_id=uuid4(),
        minute=12,
        segment_id=uuid4(),
    )
    report = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=0,
        away_score_regular=0,
        events=[event],
    )

    with pytest.raises(ValueError, match="no coincide"):
        CloseMatchReportService._validate_event_score_consistency(report, home, away)


def test_sporting_resolution_cannot_report_goals_without_goal_events():
    home = uuid4()
    away = uuid4()
    report = CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=1,
        away_score_regular=0,
    )

    with pytest.raises(ValueError, match="no coincide"):
        CloseMatchReportService._validate_event_score_consistency(report, home, away)


def test_administrative_resolution_can_set_a_score_without_events():
    home = uuid4()
    away = uuid4()
    report = CloseMatchReportDTO(
        resolution_type="administrative",
        home_score_regular=1,
        away_score_regular=0,
        home_score=1,
        away_score=0,
        winner_team_id=home,
        reason="Sancion administrativa",
    )

    CloseMatchReportService._validate_event_score_consistency(report, home, away)


def test_match_outcome_rejects_a_winner_outside_the_match():
    home = uuid4()
    away = uuid4()

    with pytest.raises(ValueError, match="no participa"):
        compute_match_outcome(
            DEFAULT_RULES_CONFIG,
            [],
            "administrative",
            home,
            away,
            0,
            0,
            0,
            0,
            None,
            None,
            uuid4(),
        )


def test_suspensions_are_created_for_card_thresholds_and_red_cards():
    player_yellow = uuid4()
    player_red = uuid4()
    source_yellow = uuid4()
    source_red = uuid4()
    config = {
        **DEFAULT_RULES_CONFIG,
        "discipline": {
            **DEFAULT_RULES_CONFIG["discipline"],
            "yellow_card_limit": 2,
        },
    }
    historical = [
        {"id": uuid4(), "player_id": player_yellow, "event_type": "yellow_card"},
    ]
    current = [
        {"id": source_yellow, "player_id": player_yellow, "event_type": "yellow_card"},
        {"id": source_red, "player_id": player_red, "event_type": "red_card"},
    ]

    suspensions = evaluate_suspensions(config, current, historical)

    assert {item["player_id"] for item in suspensions} == {player_yellow, player_red}
    assert next(item for item in suspensions if item["player_id"] == player_yellow)["reason"] == "yellow_card_accumulation"
    assert next(item for item in suspensions if item["player_id"] == player_red)["reason"] == "direct_red_card"
