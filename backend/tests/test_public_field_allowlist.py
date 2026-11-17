"""Verificación automática de la lista cerrada de campos públicos (spec 020, RF-015/RF-016)."""

from app.modules.tournaments.schemas import (
    PublicLineupPlayerResponse,
    PublicMatchLineupResponse,
    PublicMatchTimelineResponse,
    PublicMatchResponse,
    PublicPlayerProfileResponse,
    PublicPlayerProfileTotalsResponse,
    PublicPlayerProfileTournamentResponse,
    PublicPlayerStatsResponse,
    PublicSlotOriginResponse,
    PublicStageResponse,
    PublicStandingResponse,
    PublicTeamLineupResponse,
    PublicTeamStatsResponse,
    PublicTimelineEventResponse,
    PublicTimelinePlayerResponse,
    PublicTournamentResponse,
    PublicTournamentSummaryResponse,
    PublicTournamentTeamResponse,
)

EXPECTED_FIELDS = {
    "PublicTournamentSummaryResponse": {"id", "name", "season", "start_date", "status"},
    "PublicStageResponse": {"id", "name", "stage_type", "stage_order"},
    "PublicTournamentTeamResponse": {"team_id", "name", "short_code", "crest_url"},
    "PublicTournamentResponse": {"id", "name", "season", "start_date", "status", "stages", "teams"},
    "PublicStandingResponse": {
        "tournament_id", "stage_id", "stage_name", "stage_order", "group_id", "group_name",
        "team_id", "team_name", "short_code", "played", "won", "drawn", "lost",
        "goals_for", "goals_against", "goal_difference", "points", "fair_play_points",
        "rank", "calculated_at", "crest_url",
    },
    "PublicLineupPlayerResponse": {
        "player_id", "first_name", "last_name", "dorsal_number", "role",
        "position_slot", "photo_url",
    },
    "PublicTeamLineupResponse": {
        "team_id", "team_name", "formation_code", "segment_number", "crest_url", "starters", "substitutes",
    },
    "PublicMatchLineupResponse": {"home", "away"},
    "PublicMatchResponse": {
        "id", "tournament_id", "stage_id", "stage_name", "stage_order", "group_id",
        "group_name", "bracket_code", "matchday", "match_date", "home_team_id",
        "home_team_name", "home_team_short_code", "away_team_id", "away_team_name",
        "away_team_short_code", "home_team_crest_url", "away_team_crest_url",
        "home_score_regular", "away_score_regular", "home_score", "away_score",
        "home_penalties", "away_penalties", "winner_team_id", "status",
        "resolution_type", "lineup", "rectified_at",
        # Spec 040 §8: cambio no aditivo declarado; nulos en plazas resueltas.
        "home_origin", "away_origin",
    },
    "PublicSlotOriginResponse": {"kind", "group_name", "position", "ordinal"},
    "PublicPlayerStatsResponse": {
        "rank", "player_id", "first_name", "last_name", "team_name", "team_id",
        "goals", "yellow_cards", "red_cards", "clean_sheets", "matches_played",
        "photo_url", "profile_available",
    },
    "PublicTeamStatsResponse": {
        "rank", "team_id", "team_name", "short_code", "crest_url",
        "goals_for", "goals_against", "clean_sheets", "fair_play_points",
    },
    "PublicTimelinePlayerResponse": {"player_id", "first_name", "last_name", "profile_available"},
    "PublicTimelineEventResponse": {
        "event_type", "minute", "added_minute", "segment_number", "team_id",
        "beneficiary_team_id", "red_card_type", "player", "player_in",
    },
    "PublicMatchTimelineResponse": {
        "match_id", "availability", "score_consistent", "segment_numbers", "events",
    },
    "PublicPlayerProfileResponse": {
        "player_id", "first_name", "last_name", "photo_url", "totals", "tournaments",
    },
    "PublicPlayerProfileTournamentResponse": {
        "tournament_id", "tournament_name", "team_id", "team_name",
        "matches_played", "goals", "yellow_cards", "red_cards", "clean_sheets",
    },
    "PublicPlayerProfileTotalsResponse": {
        "matches_played", "goals", "yellow_cards", "red_cards", "clean_sheets",
    },
}

MODELS = {
    "PublicTournamentSummaryResponse": PublicTournamentSummaryResponse,
    "PublicStageResponse": PublicStageResponse,
    "PublicTournamentTeamResponse": PublicTournamentTeamResponse,
    "PublicTournamentResponse": PublicTournamentResponse,
    "PublicStandingResponse": PublicStandingResponse,
    "PublicLineupPlayerResponse": PublicLineupPlayerResponse,
    "PublicTeamLineupResponse": PublicTeamLineupResponse,
    "PublicMatchLineupResponse": PublicMatchLineupResponse,
    "PublicMatchResponse": PublicMatchResponse,
    "PublicSlotOriginResponse": PublicSlotOriginResponse,
    "PublicPlayerStatsResponse": PublicPlayerStatsResponse,
    "PublicTeamStatsResponse": PublicTeamStatsResponse,
    "PublicTimelinePlayerResponse": PublicTimelinePlayerResponse,
    "PublicTimelineEventResponse": PublicTimelineEventResponse,
    "PublicMatchTimelineResponse": PublicMatchTimelineResponse,
    "PublicPlayerProfileResponse": PublicPlayerProfileResponse,
    "PublicPlayerProfileTournamentResponse": PublicPlayerProfileTournamentResponse,
    "PublicPlayerProfileTotalsResponse": PublicPlayerProfileTotalsResponse,
}

PROFILE_FORBIDDEN_FIELDS = {
    "dorsal_number", "position", "position_slot", "role", "photo_consent", "is_active",
    "valid_from", "rank", "assists", "assist_player_id",
}

TIMELINE_FORBIDDEN_FIELDS = {
    "assist_player_id", "metadata", "dorsal_number", "photo_url", "id", "segment_id",
    "version_id", "client_event_id", "is_voided", "void_reason", "notes",
}

SENSITIVE_FIELDS = {
    "national_id", "document", "document_number", "birth_date", "birth_date_encrypted",
    "age", "age_at_reference", "age_reference_year", "logo_url", "crest_object_key",
    "photo_object_key", "object_key", "storage_key", "resolution_reason", "reason",
    "walkover_reason", "suspension", "suspensions", "sanction", "sanctions", "audit",
    "audit_log", "member", "members", "organization_id", "user_id", "email", "phone",
    "address", "national_id_number",
}


def test_public_model_field_sets_match_allowlist():
    for name, model in MODELS.items():
        actual = set(model.model_fields.keys())
        expected = EXPECTED_FIELDS[name]
        extra = actual - expected
        missing = expected - actual
        assert not extra, f"{name}: campos fuera de la lista cerrada: {sorted(extra)}"
        assert not missing, f"{name}: campos declarados que faltan: {sorted(missing)}"


def test_no_sensitive_fields_in_public_models():
    all_fields = set()
    for model in MODELS.values():
        all_fields.update(model.model_fields.keys())
    leaked = all_fields & SENSITIVE_FIELDS
    assert not leaked, f"Campos sensibles en modelos públicos: {sorted(leaked)}"


def test_all_public_models_covered():
    import app.modules.tournaments.schemas as schemas

    public_models = {
        attr for attr in dir(schemas)
        if attr.startswith("Public") and attr.endswith("Response")
    }
    assert public_models == set(MODELS.keys()), (
        "Modelos públicos sin cubrir o sobrantes: "
        f"{sorted(public_models ^ set(MODELS.keys()))}"
    )


def test_timeline_models_never_expose_assist_dorsal_photo_or_internal_ids():
    for model in (PublicTimelinePlayerResponse, PublicTimelineEventResponse, PublicMatchTimelineResponse):
        leaked = set(model.model_fields) & TIMELINE_FORBIDDEN_FIELDS
        assert not leaked, f"{model.__name__}: {sorted(leaked)}"


def test_timeline_models_reject_extra_keys():
    import pytest
    from pydantic import ValidationError

    player = {"player_id": "30000000-0000-4000-8000-000000000001", "first_name": "A", "last_name": "B"}
    with pytest.raises(ValidationError):
        PublicTimelinePlayerResponse(**player, dorsal_number=9)
    with pytest.raises(ValidationError):
        PublicMatchTimelineResponse(
            match_id=player["player_id"], availability="pending", assist_player_id=player["player_id"]
        )


def test_profile_models_never_expose_dorsal_position_or_consent():
    for model in (
        PublicPlayerProfileResponse, PublicPlayerProfileTournamentResponse, PublicPlayerProfileTotalsResponse,
    ):
        leaked = set(model.model_fields) & PROFILE_FORBIDDEN_FIELDS
        assert not leaked, f"{model.__name__}: {sorted(leaked)}"


def test_profile_models_reject_extra_keys():
    import pytest
    from pydantic import ValidationError

    ident = "30000000-0000-4000-8000-000000000001"
    totals = {"matches_played": 0, "goals": 0, "yellow_cards": 0, "red_cards": 0, "clean_sheets": 0}
    row = {"tournament_id": ident, "tournament_name": "T", "team_id": ident, "team_name": "E", **totals}
    profile = {"player_id": ident, "first_name": "A", "last_name": "B", "photo_url": None,
               "totals": totals, "tournaments": [row]}
    assert PublicPlayerProfileResponse(**profile).tournaments[0].team_name == "E"
    with pytest.raises(ValidationError):
        PublicPlayerProfileResponse(**profile, organization_id=ident)
    with pytest.raises(ValidationError):
        PublicPlayerProfileTournamentResponse(**row, dorsal_number=9)
    with pytest.raises(ValidationError):
        PublicPlayerProfileTotalsResponse(**totals, assists=1)
    with pytest.raises(ValidationError):
        PublicTimelinePlayerResponse(player_id=ident, first_name="A", last_name="B", profile_available="yes")


def test_profile_available_defaults_to_closed_false():
    ident = "30000000-0000-4000-8000-000000000001"
    assert PublicTimelinePlayerResponse(player_id=ident, first_name="A", last_name="B").profile_available is False
    stats = PublicPlayerStatsResponse(rank=1, player_id=ident, first_name="A", last_name="B")
    assert stats.profile_available is False
