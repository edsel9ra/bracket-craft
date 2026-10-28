"""Verificación automática de la lista cerrada de campos públicos (spec 020, RF-015/RF-016)."""

from app.modules.tournaments.schemas import (
    PublicLineupPlayerResponse,
    PublicMatchLineupResponse,
    PublicMatchResponse,
    PublicPlayerStatsResponse,
    PublicStageResponse,
    PublicStandingResponse,
    PublicTeamLineupResponse,
    PublicTeamStatsResponse,
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
        "resolution_type", "lineup",
    },
    "PublicPlayerStatsResponse": {
        "rank", "player_id", "first_name", "last_name", "team_name", "team_id",
        "goals", "yellow_cards", "red_cards", "clean_sheets", "matches_played",
        "photo_url",
    },
    "PublicTeamStatsResponse": {
        "rank", "team_id", "team_name", "short_code", "crest_url",
        "goals_for", "goals_against", "clean_sheets", "fair_play_points",
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
    "PublicPlayerStatsResponse": PublicPlayerStatsResponse,
    "PublicTeamStatsResponse": PublicTeamStatsResponse,
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
