DEFAULT_SUBSTITUTIONS = {
    "max_per_team": 5,
    "max_windows": 3,
    "allow_reentry": False,
}

# RF-042: closed game format catalog; 11v11 preserves compatibility.
GAME_FORMAT_CATALOG = ("5v5", "7v7", "9v9", "11v11")
DEFAULT_GAME_FORMAT = "11v11"

# RF-044: 0 (or an absent key) means "no limit".
DEFAULT_MIN_PLAYERS_PER_TEAM = 0
DEFAULT_MAX_PLAYERS_PER_TEAM = 0

DEFAULT_REGULAR_TIME_MINUTES = 90
DEFAULT_EXTRA_TIME_MINUTES = 120

DEFAULT_STAGE_RULES = {
    "extra_time_enabled": False,
    "penalties_enabled": False,
    "regular_time_minutes": DEFAULT_REGULAR_TIME_MINUTES,
    "extra_time_minutes": DEFAULT_EXTRA_TIME_MINUTES,
    "walkover_score": {"winner": 3, "loser": 0},
}

DEFAULT_RULES_CONFIG = {
    "schema_version": "3.3.0",
    "engine_version": "2026.1",
    "game_format": DEFAULT_GAME_FORMAT,
    "min_players_per_team": DEFAULT_MIN_PLAYERS_PER_TEAM,
    "max_players_per_team": DEFAULT_MAX_PLAYERS_PER_TEAM,
    "points_system": {"win": 3, "draw": 1, "loss": 0},
    "ranking_pipeline": [
        {"step": 1, "criterion": "points", "params": {}},
        {"step": 2, "criterion": "head_to_head", "params": {"total_rounds_expected": 1}},
        {"step": 3, "criterion": "goal_difference", "params": {}},
        {"step": 4, "criterion": "goals_for", "params": {}},
        {"step": 5, "criterion": "fair_play_points", "params": {}},
    ],
    "substitutions": dict(DEFAULT_SUBSTITUTIONS),
    "roster_lock_matchday": None,
    "discipline": {
        "yellow_card_limit": 3,
        "yellow_card_suspension_matches": 1,
        "direct_red_suspension_matches": 1,
        "clear_yellows_on_stage_change": True,
        "fair_play_penalties": {"yellow_card": 1, "double_yellow_red": 3, "direct_red": 3},
    },
    "stage_defaults": {
        "extra_time_enabled": False,
        "penalties_enabled": False,
        "regular_time_minutes": DEFAULT_REGULAR_TIME_MINUTES,
        "extra_time_minutes": DEFAULT_EXTRA_TIME_MINUTES,
        "walkover_score": {"winner": 3, "loser": 0},
    },
    "stage_overrides": {},
}
