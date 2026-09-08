DEFAULT_RULES_CONFIG = {
    "schema_version": "3.2.0",
    "engine_version": "2026.1",
    "points_system": {"win": 3, "draw": 1, "loss": 0},
    "ranking_pipeline": [
        {"step": 1, "criterion": "points", "params": {}},
        {"step": 2, "criterion": "head_to_head", "params": {"total_rounds_expected": 1}},
        {"step": 3, "criterion": "goal_difference", "params": {}},
        {"step": 4, "criterion": "goals_for", "params": {}},
        {"step": 5, "criterion": "fair_play_points", "params": {}},
    ],
    "substitutions": {"max_per_team": 5, "max_windows": 3, "allow_reentry": False},
    "discipline": {
        "yellow_card_limit": 3,
        "yellow_card_suspension_matches": 1,
        "direct_red_suspension_matches": 1,
        "clear_yellows_on_stage_change": True,
        "fair_play_penalties": {"yellow_card": 1, "double_yellow_red": 3, "direct_red": 3},
    },
    "transfers": {
        "allow_mid_season_transfers": True,
        "same_matchday_participation_allowed": False,
        "roster_lock_matchday": None,
    },
    "stage_defaults": {
        "extra_time_enabled": False,
        "penalties_enabled": False,
        "walkover_score": {"winner": 3, "loser": 0},
    },
    "stage_overrides": {},
}
