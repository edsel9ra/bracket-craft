from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import (
    APPLIED_RULE_KEYS,
    DEPRECATED_RULE_KEYS,
    RULES_SCHEMA,
    effective_roster_lock_matchday,
    effective_stage_rules,
    effective_substitutions,
    normalize_rules_config,
    validate_rules_config,
)
from app.modules.rules_engine.schemas import (
    TournamentRulesConfig,
    UpdateRulesConfigRequest,
)

GAME_FORMAT_CATALOG = ["5v5", "7v7", "9v9", "11v11"]
NEW_RULE_KEYS = {"game_format", "min_players_per_team", "max_players_per_team"}
ROSTER_LIMIT_FIELDS = ["min_players_per_team", "max_players_per_team"]


def _config_320() -> dict:
    """A pre-3.3.0 config: deprecated blocks, no top-level lock, no minutes."""
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["schema_version"] = "3.2.0"
    config.pop("roster_lock_matchday", None)
    config["transfers"] = {
        "allow_mid_season_transfers": True,
        "same_matchday_participation_allowed": False,
        "roster_lock_matchday": None,
    }
    config["stage_defaults"].pop("regular_time_minutes", None)
    config["stage_defaults"].pop("extra_time_minutes", None)
    return config


def _config_330() -> dict:
    config = _config_320()
    config["schema_version"] = "3.3.0"
    config.pop("transfers", None)
    config["roster_lock_matchday"] = None
    return config


def test_every_schema_key_is_classified_as_applied_or_deprecated():
    properties = set(RULES_SCHEMA["properties"])

    assert not APPLIED_RULE_KEYS & DEPRECATED_RULE_KEYS
    assert properties == APPLIED_RULE_KEYS | DEPRECATED_RULE_KEYS
    assert {"substitutions", "roster_lock_matchday", "stage_defaults"} <= APPLIED_RULE_KEYS
    assert NEW_RULE_KEYS <= APPLIED_RULE_KEYS
    assert DEPRECATED_RULE_KEYS == {"transfers"}
    assert {"regular_time_minutes", "extra_time_minutes"} <= set(
        RULES_SCHEMA["properties"]["stage_defaults"]["properties"]
    )


def test_default_config_is_330_without_transfers():
    assert DEFAULT_RULES_CONFIG["schema_version"] == "3.3.0"
    assert "transfers" not in DEFAULT_RULES_CONFIG
    assert DEFAULT_RULES_CONFIG["roster_lock_matchday"] is None
    assert DEFAULT_RULES_CONFIG["substitutions"] == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }
    assert DEFAULT_RULES_CONFIG["stage_defaults"]["regular_time_minutes"] == 90
    assert DEFAULT_RULES_CONFIG["stage_defaults"]["extra_time_minutes"] == 120
    validate_rules_config(DEFAULT_RULES_CONFIG)


def test_320_with_deprecated_blocks_is_valid_and_normalized():
    config = _config_320()
    validate_rules_config(config)

    normalized = normalize_rules_config(config)

    assert normalized["schema_version"] == "3.3.0"
    assert "transfers" not in normalized
    assert normalized["substitutions"] == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }
    assert normalized["roster_lock_matchday"] is None
    assert normalized["stage_defaults"]["regular_time_minutes"] == 90
    assert "extra_time_minutes" not in normalized["stage_defaults"]
    validate_rules_config(normalized)


def test_330_without_deprecated_blocks_is_valid():
    config = _config_330()
    validate_rules_config(config)

    normalized = normalize_rules_config(config)

    assert normalized == normalize_rules_config(config)
    assert normalized["schema_version"] == "3.3.0"
    assert normalized["substitutions"]["max_per_team"] == 5


def test_320_without_minutes_reads_default_pair_without_rewriting():
    config = _config_320()
    original = deepcopy(config)

    effective = effective_stage_rules(config, None)

    assert effective["regular_time_minutes"] == 90
    assert effective["extra_time_minutes"] == 120
    assert config == original
    assert "regular_time_minutes" not in config["stage_defaults"]


def test_unknown_schema_version_is_rejected():
    config = _config_330()
    config["schema_version"] = "3.1.0"
    with pytest.raises(ValueError, match="schema_version"):
        validate_rules_config(config)


def test_missing_substitutions_uses_read_defaults():
    config = _config_330()
    config.pop("substitutions")

    validate_rules_config(config)

    assert effective_substitutions(config) == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }


def test_missing_substitutions_is_materialized_when_normalizing():
    config = _config_330()
    config.pop("substitutions")

    normalized = normalize_rules_config(config)

    assert normalized["substitutions"] == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }


def test_roster_lock_is_promoted_from_inherited_block():
    config = _config_320()
    config["transfers"]["roster_lock_matchday"] = 4

    assert effective_roster_lock_matchday(config) == 4
    normalized = normalize_rules_config(config)
    assert normalized["roster_lock_matchday"] == 4
    assert "transfers" not in normalized


def test_roster_lock_top_level_only_is_kept():
    config = _config_320()
    config["roster_lock_matchday"] = 6
    config["transfers"]["roster_lock_matchday"] = None

    assert effective_roster_lock_matchday(config) == 6
    assert normalize_rules_config(config)["roster_lock_matchday"] == 6


def test_roster_lock_both_present_prefers_top_level():
    config = _config_320()
    config["roster_lock_matchday"] = 6
    config["transfers"]["roster_lock_matchday"] = 4

    assert effective_roster_lock_matchday(config) == 6
    normalized = normalize_rules_config(config)
    assert normalized["roster_lock_matchday"] == 6
    assert "transfers" not in normalized


def test_roster_lock_requires_positive_integer():
    config = _config_330()
    config["roster_lock_matchday"] = 0
    with pytest.raises(ValueError, match="roster_lock_matchday"):
        validate_rules_config(config)


@pytest.mark.parametrize("regular", [0, 180])
def test_regular_time_minutes_out_of_range_is_rejected(regular: int):
    config = _config_330()
    config["stage_defaults"]["regular_time_minutes"] = regular

    with pytest.raises(ValueError, match="regular_time_minutes"):
        validate_rules_config(config)


def test_regular_time_minutes_upper_bound_is_valid():
    config = _config_330()
    config["stage_defaults"]["regular_time_minutes"] = 179
    config["stage_defaults"]["extra_time_enabled"] = True
    config["stage_defaults"]["extra_time_minutes"] = 180

    validate_rules_config(config)

    normalized = normalize_rules_config(config)
    assert normalized["stage_defaults"]["regular_time_minutes"] == 179
    assert normalized["stage_defaults"]["extra_time_minutes"] == 180


@pytest.mark.parametrize("extra", [90, 181])
def test_extra_time_minutes_must_exceed_regular_and_stay_within_180(extra: int):
    config = _config_330()
    config["stage_defaults"]["extra_time_enabled"] = True
    config["stage_defaults"]["regular_time_minutes"] = 90
    config["stage_defaults"]["extra_time_minutes"] = extra

    with pytest.raises(ValueError, match="extra_time_minutes"):
        validate_rules_config(config)


def test_extra_time_disabled_does_not_validate_extra_minutes():
    config = _config_330()
    config["stage_defaults"]["regular_time_minutes"] = 150
    config["stage_defaults"]["extra_time_enabled"] = False
    config["stage_defaults"]["extra_time_minutes"] = 181

    validate_rules_config(config)

    normalized = normalize_rules_config(config)
    assert normalized["stage_defaults"]["regular_time_minutes"] == 150
    # The declared value is kept but not validated nor materialized anew.
    assert normalized["stage_defaults"]["extra_time_minutes"] == 181


def test_extra_time_disabled_does_not_materialize_extra_minutes():
    config = _config_330()
    config["stage_defaults"]["regular_time_minutes"] = 150
    config["stage_defaults"]["extra_time_enabled"] = False

    normalized = normalize_rules_config(config)

    assert normalized["stage_defaults"]["regular_time_minutes"] == 150
    assert "extra_time_minutes" not in normalized["stage_defaults"]


def test_extra_time_enabled_materializes_default_pair_when_missing():
    config = _config_330()
    config["stage_defaults"]["extra_time_enabled"] = True

    normalized = normalize_rules_config(config)

    assert normalized["stage_defaults"]["regular_time_minutes"] == 90
    assert normalized["stage_defaults"]["extra_time_minutes"] == 120


def test_enabled_extra_time_with_regular_150_without_extra_is_rejected_without_120():
    config = _config_330()
    config["stage_defaults"]["extra_time_enabled"] = True
    config["stage_defaults"]["regular_time_minutes"] = 150

    with pytest.raises(ValueError, match="extra_time_minutes") as excinfo:
        normalize_rules_config(config)

    message = str(excinfo.value)
    assert "stage_defaults" in message
    assert "150" in message
    # The default 120 is never written to complete an invalid pair.
    assert "extra_time_minutes" not in config["stage_defaults"]


def test_partial_stage_override_is_valid_and_resolved_per_key():
    config = _config_330()
    config["stage_defaults"]["extra_time_enabled"] = True
    config["stage_defaults"]["regular_time_minutes"] = 90
    config["stage_defaults"]["extra_time_minutes"] = 120
    stage_id = uuid4()
    config["stage_overrides"] = {
        str(stage_id): {
            "extra_time_enabled": True,
            "extra_time_minutes": 180,
        }
    }

    validate_rules_config(config)

    effective = effective_stage_rules(config, stage_id)
    assert effective["regular_time_minutes"] == 90
    assert effective["extra_time_minutes"] == 180


def test_invalid_partial_stage_override_is_rejected_naming_scope():
    config = _config_330()
    config["stage_defaults"]["extra_time_enabled"] = True
    config["stage_defaults"]["regular_time_minutes"] = 90
    config["stage_defaults"]["extra_time_minutes"] = 120
    stage_id = uuid4()
    config["stage_overrides"] = {
        str(stage_id): {"regular_time_minutes": 150}
    }

    with pytest.raises(ValueError, match="extra_time_minutes") as excinfo:
        validate_rules_config(config)

    assert str(stage_id) in str(excinfo.value)


def test_partial_override_with_extra_time_disabled_accepts_regular_150():
    config = _config_330()
    stage_id = uuid4()
    config["stage_overrides"] = {
        str(stage_id): {
            "extra_time_enabled": False,
            "regular_time_minutes": 150,
        }
    }

    validate_rules_config(config)

    effective = effective_stage_rules(config, stage_id)
    assert effective["extra_time_enabled"] is False
    assert effective["regular_time_minutes"] == 150


def test_tournament_rules_model_accepts_320_and_emits_330():
    request = TournamentRulesConfig.model_validate(_config_320())

    dumped = request.model_dump(mode="json")
    assert dumped["schema_version"] == "3.3.0"
    assert "transfers" not in dumped
    assert dumped["substitutions"]["max_per_team"] == 5
    validate_rules_config(dumped)


def test_tournament_rules_model_accepts_330_without_optional_blocks():
    config = _config_330()
    config.pop("substitutions")
    config.pop("transfers", None)

    request = TournamentRulesConfig.model_validate(config)

    dumped = request.model_dump(mode="json")
    assert dumped["schema_version"] == "3.3.0"
    assert dumped["substitutions"] == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }
    assert "transfers" not in dumped


# --- H4-T01: game_format, min/max players per team (RF-042, RF-043, RF-044) ---


def _config_without_new_keys() -> dict:
    config = _config_330()
    for key in NEW_RULE_KEYS:
        config.pop(key, None)
    return config


def test_new_keys_are_applied_schema_properties_with_a_closed_format_catalog():
    properties = RULES_SCHEMA["properties"]

    assert NEW_RULE_KEYS <= APPLIED_RULE_KEYS
    assert NEW_RULE_KEYS <= set(properties)
    assert properties["game_format"]["enum"] == GAME_FORMAT_CATALOG
    assert properties["min_players_per_team"] == {"type": "integer", "minimum": 0}
    assert properties["max_players_per_team"] == {"type": "integer", "minimum": 0}
    assert properties["engine_version"]["const"] == "2026.1"
    assert DEFAULT_RULES_CONFIG["game_format"] == "11v11"
    assert DEFAULT_RULES_CONFIG["engine_version"] == "2026.1"


def test_old_config_without_new_keys_is_valid_and_normalizes_without_limits():
    config = _config_without_new_keys()

    assert not NEW_RULE_KEYS & set(config)
    validate_rules_config(config)

    normalized = normalize_rules_config(config)

    assert normalized["game_format"] == "11v11"
    assert normalized["min_players_per_team"] == 0
    assert normalized["max_players_per_team"] == 0
    assert normalized["engine_version"] == "2026.1"
    validate_rules_config(normalized)


def test_new_keys_do_not_change_any_existing_default():
    normalized = normalize_rules_config(_config_330())

    assert normalized["points_system"] == {"win": 3, "draw": 1, "loss": 0}
    assert normalized["substitutions"] == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }
    assert normalized["roster_lock_matchday"] is None
    assert normalized["stage_defaults"]["regular_time_minutes"] == 90
    assert normalized["engine_version"] == "2026.1"


@pytest.mark.parametrize("game_format", GAME_FORMAT_CATALOG)
def test_each_closed_game_format_is_valid_and_preserved(game_format: str):
    config = _config_330()
    config["game_format"] = game_format

    validate_rules_config(config)

    assert normalize_rules_config(config)["game_format"] == game_format


@pytest.mark.parametrize(
    "game_format",
    ["4v4", "6v6", "8v8", "11", "11v11 ", " 11v11", "futsal", "", 11, None],
)
def test_game_format_outside_the_catalog_is_rejected(game_format):
    config = _config_330()
    config["game_format"] = game_format

    with pytest.raises(ValueError, match="game_format"):
        validate_rules_config(config)


@pytest.mark.parametrize("field", ROSTER_LIMIT_FIELDS)
@pytest.mark.parametrize("value", [0, 1, 11, 30, 99])
def test_non_negative_roster_limits_are_valid(field: str, value: int):
    config = _config_330()
    config[field] = value

    validate_rules_config(config)

    normalized = normalize_rules_config(config)
    assert normalized[field] == value
    validate_rules_config(normalized)


@pytest.mark.parametrize("field", ROSTER_LIMIT_FIELDS)
@pytest.mark.parametrize("value", [-1, -20, 1.5, 11.5, "12", "", None, True])
def test_invalid_roster_limits_are_rejected(field: str, value):
    config = _config_330()
    config[field] = value

    with pytest.raises(ValueError, match=field):
        validate_rules_config(config)


def test_minimum_greater_than_maximum_is_rejected():
    config = _config_330()
    config["min_players_per_team"] = 18
    config["max_players_per_team"] = 17

    with pytest.raises(ValueError, match="min_players_per_team") as excinfo:
        validate_rules_config(config)

    assert "max_players_per_team" in str(excinfo.value)


def test_minimum_equal_to_maximum_is_valid():
    config = _config_330()
    config["min_players_per_team"] = 11
    config["max_players_per_team"] = 11

    validate_rules_config(config)

    normalized = normalize_rules_config(config)
    assert normalized["min_players_per_team"] == 11
    assert normalized["max_players_per_team"] == 11


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [(0, 0), (0, 5), (30, 0), (None, 4), (4, None)],
)
def test_zero_or_absent_limit_means_no_limit_and_skips_the_pair_rule(minimum, maximum):
    config = _config_330()
    if minimum is None:
        config.pop("min_players_per_team", None)
    else:
        config["min_players_per_team"] = minimum
    if maximum is None:
        config.pop("max_players_per_team", None)
    else:
        config["max_players_per_team"] = maximum

    validate_rules_config(config)

    normalized = normalize_rules_config(config)
    assert normalized["min_players_per_team"] == (minimum or 0)
    assert normalized["max_players_per_team"] == (maximum or 0)


def test_only_minimum_is_kept_with_maximum_unlimited():
    config = _config_330()
    config.pop("max_players_per_team", None)
    config["min_players_per_team"] = 11

    normalized = normalize_rules_config(config)

    assert normalized["min_players_per_team"] == 11
    assert normalized["max_players_per_team"] == 0


def test_only_maximum_is_kept_with_minimum_unlimited():
    config = _config_330()
    config.pop("min_players_per_team", None)
    config["max_players_per_team"] = 25

    normalized = normalize_rules_config(config)

    assert normalized["min_players_per_team"] == 0
    assert normalized["max_players_per_team"] == 25


def test_both_limits_zero_mean_no_limit():
    config = _config_330()
    config["min_players_per_team"] = 0
    config["max_players_per_team"] = 0

    validate_rules_config(config)

    normalized = normalize_rules_config(config)
    assert normalized["min_players_per_team"] == 0
    assert normalized["max_players_per_team"] == 0


def test_tournament_rules_model_defaults_old_config_to_11v11_without_limits():
    request = TournamentRulesConfig.model_validate(_config_without_new_keys())

    assert request.game_format == "11v11"
    assert request.min_players_per_team == 0
    assert request.max_players_per_team == 0

    dumped = request.model_dump(mode="json")
    assert dumped["game_format"] == "11v11"
    assert dumped["min_players_per_team"] == 0
    assert dumped["max_players_per_team"] == 0
    validate_rules_config(dumped)


@pytest.mark.parametrize("field", ROSTER_LIMIT_FIELDS)
def test_empty_string_limit_is_rejected_by_the_request_model(field: str):
    config = _config_330()
    config[field] = ""

    with pytest.raises(ValidationError):
        TournamentRulesConfig.model_validate(config)


def test_game_format_outside_catalog_is_rejected_by_the_request_model():
    config = _config_330()
    config["game_format"] = "4v4"

    with pytest.raises(ValidationError, match="game_format"):
        TournamentRulesConfig.model_validate(config)


def test_minimum_greater_than_maximum_is_rejected_by_the_request_model():
    config = _config_330()
    config["min_players_per_team"] = 18
    config["max_players_per_team"] = 17

    with pytest.raises(ValidationError, match="min_players_per_team"):
        TournamentRulesConfig.model_validate(config)


async def _patch_rules_status(config: dict) -> int:
    """PATCH a minimal app so the real request-validation path returns its status."""
    api = FastAPI()

    @api.patch("/rules")
    def patch_rules(payload: UpdateRulesConfigRequest) -> dict:
        return {"ok": True}

    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/rules", json={"rules_config": config})
    return response.status_code


@pytest.mark.parametrize("field", ROSTER_LIMIT_FIELDS)
async def test_empty_string_limit_is_422_at_the_api_boundary(field: str):
    config = _config_330()
    config[field] = ""

    assert await _patch_rules_status(config) == 422


async def test_invalid_configuration_is_422_at_the_api_boundary():
    invalid_cases = []
    for field in ROSTER_LIMIT_FIELDS:
        negative = _config_330()
        negative[field] = -1
        invalid_cases.append(negative)
    out_of_catalog = _config_330()
    out_of_catalog["game_format"] = "4v4"
    invalid_cases.append(out_of_catalog)
    inverted_pair = _config_330()
    inverted_pair["min_players_per_team"] = 18
    inverted_pair["max_players_per_team"] = 17
    invalid_cases.append(inverted_pair)

    for config in invalid_cases:
        assert await _patch_rules_status(config) == 422


async def test_valid_configuration_is_accepted_at_the_api_boundary():
    config = _config_330()
    config["game_format"] = "7v7"
    config["min_players_per_team"] = 10
    config["max_players_per_team"] = 16

    assert await _patch_rules_status(config) == 200
