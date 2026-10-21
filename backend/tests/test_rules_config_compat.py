from copy import deepcopy
from uuid import uuid4

import pytest

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
from app.modules.rules_engine.schemas import TournamentRulesConfig


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
