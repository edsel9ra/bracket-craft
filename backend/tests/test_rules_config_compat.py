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


# --- Spec 019 (T2): RF-004 — primer nivel cerrado, bloque deprecado y mapa abierto ---


async def test_undeclared_top_level_key_in_rules_config_is_422_at_the_api_boundary():
    """RF-003/RF-004: an undeclared first-level key is 422, never dropped silently.

    Before spec 019 the request model discarded it (200 with the key gone). The
    422 comes from the Pydantic body model (``TournamentRulesConfig`` with
    ``extra="forbid"``, nested in ``UpdateRulesConfigRequest``), the very layer
    FastAPI uses to validate the body before the handler runs; the engine
    (``RULES_SCHEMA``/``validate_rules_config``) is not in the request path.
    """

    config = _config_330()
    config["zzz_undeclared_key"] = 1

    assert await _patch_rules_status(config) == 422


def test_undeclared_top_level_key_is_extra_forbidden_in_the_request_model():
    """RF-001: even an explicit ``null`` is a value, not an absence."""

    config = _config_330()
    config["zzz_undeclared_key"] = None

    with pytest.raises(ValidationError) as excinfo:
        TournamentRulesConfig.model_validate(config)

    extra_errors = [
        error
        for error in excinfo.value.errors()
        if error["type"] == "extra_forbidden"
        and list(error["loc"]) == ["zzz_undeclared_key"]
    ]
    assert extra_errors, [error["type"] for error in excinfo.value.errors()]


async def test_deprecated_transfers_block_is_still_accepted_and_promoted():
    """RF-004: the deprecated block is still accepted, open inside and promoted."""

    config = _config_320()
    config["transfers"]["roster_lock_matchday"] = 4
    config["transfers"]["free_operator_note"] = "clave libre del bloque deprecado"

    request = TournamentRulesConfig.model_validate(config)

    assert request.roster_lock_matchday == 4
    assert request.transfers is None
    assert "transfers" not in request.model_dump(mode="json")

    assert await _patch_rules_status(config) == 200


def test_stage_overrides_index_is_still_an_open_map():
    """RF-004: arbitrary per-stage index keys are tolerated by model and engine."""

    config = _config_330()
    index_keys = {str(uuid4()), "custom-operator-index"}
    config["stage_overrides"] = {
        key: {"extra_time_enabled": False} for key in index_keys
    }

    validate_rules_config(config)

    request = TournamentRulesConfig.model_validate(config)
    assert set(request.stage_overrides) == index_keys


def test_key_inside_a_stage_override_is_still_rejected():
    """RF-004 boundary: the open map is the index, not the override contents."""

    config = _config_330()
    config["stage_overrides"] = {str(uuid4()): {"zzz_internal_key": 1}}

    with pytest.raises(ValidationError):
        TournamentRulesConfig.model_validate(config)

    with pytest.raises(ValueError, match="stage_overrides"):
        validate_rules_config(config)


# --- Spec 019 (cierre de I-3): RNF-006 — barrido de comportamiento por bloque ---
#
# RNF-006: por cada bloque alcanzable de ``rules_config`` se construye un cuerpo con
# una clave extra y se exige el rechazo **con el validador propio** de la
# configuración, excluyendo únicamente los tres mapas abiertos de RF-004.
#
# Qué capa cierra cada bloque (medido, no supuesto): ``TournamentRulesConfig`` declara
# los bloques como ``dict[str, Any]``/``list[dict[str, Any]]``, así que la bandera
# ``extra="forbid"`` solo cubre el primer nivel; quien cierra los bloques en ejecución
# es el motor (``RULES_SCHEMA`` con ``additionalProperties: false``, invocado por
# ``validate_rules_config``), y el modelo de petición los rechaza porque su
# ``model_validator(mode="after")`` llama a ``normalize_rules_config`` →
# ``validate_rules_config``. Por eso cada caso se comprueba en los tres pisos:
# motor, modelo de petición y frontera HTTP (422 del caso límite 26).

EXTRA_BLOCK_KEY = "zzz_undeclared_block_key"
FREE_OPEN_KEY = "zzz_free_open_key"


def _closed_block_paths(schema: dict, prefix: str = "") -> set[str]:
    """Paths of every object that ``RULES_SCHEMA`` closes with ``additionalProperties: false``.

    ``<root>`` is the first level; ``[]`` marks an array item and ``{}`` the *value*
    of a map whose index stays open.
    """

    paths: set[str] = set()
    additional = schema.get("additionalProperties")
    if additional is False:
        paths.add(prefix or "<root>")
    for name, subschema in (schema.get("properties") or {}).items():
        paths |= _closed_block_paths(subschema, f"{prefix}.{name}" if prefix else name)
    items = schema.get("items")
    if isinstance(items, dict):
        paths |= _closed_block_paths(items, f"{prefix}[]")
    if isinstance(additional, dict):
        paths |= _closed_block_paths(additional, f"{prefix}{{}}")
    return paths


def _closed_block_container(config: dict, path: str) -> dict:
    """Return the live mapping of the closed block ``path`` inside ``config``."""

    if path == "<root>":
        return config
    if path == "ranking_pipeline[]":
        return config["ranking_pipeline"][0]
    if path.startswith("stage_overrides{}"):
        overrides = config.setdefault("stage_overrides", {})
        if not overrides:
            overrides[str(uuid4())] = {"extra_time_enabled": False}
        value = next(iter(overrides.values()))
        if path == "stage_overrides{}.walkover_score":
            return value.setdefault("walkover_score", {"winner": 3, "loser": 0})
        return value
    node = config
    for token in path.split("."):
        node = node[token]
    return node


def _block_path_segments(path: str) -> list[str]:
    """Meaningful tokens of a derived path, to be found in the engine message."""

    return [
        segment
        for segment in path.replace("{}", "").replace("[]", "").split(".")
        if segment and segment != "<root>"
    ]


# Literal list of the closed blocks with a committed rejection case in this module.
# ``test_every_closed_block_of_rules_schema_has_a_rejection_case`` compares it with the
# paths derived from ``RULES_SCHEMA``, so a new closed block fails with an explicit
# message instead of sneaking in without a case (RNF-006: "falla si un cuerpo o un
# bloque nuevo no aplica la regla").
CLOSED_BLOCK_PATHS = frozenset({
    "<root>",
    "points_system",
    "ranking_pipeline[]",
    "substitutions",
    "discipline",
    "discipline.fair_play_penalties",
    "stage_defaults",
    "stage_defaults.walkover_score",
    "stage_overrides{}",
    "stage_overrides{}.walkover_score",
})


def test_every_closed_block_of_rules_schema_has_a_rejection_case():
    """RNF-006: no puede nacer un bloque cerrado sin su caso de rechazo."""

    derived = _closed_block_paths(RULES_SCHEMA)
    missing = sorted(derived - set(CLOSED_BLOCK_PATHS))
    stale = sorted(set(CLOSED_BLOCK_PATHS) - derived)
    assert not missing and not stale, (
        "RNF-006: los bloques cerrados de RULES_SCHEMA y los probados en este módulo "
        f"divergen. Bloques sin caso de rechazo: {missing or 'ninguno'}; "
        f"casos sin bloque en el esquema: {stale or 'ninguno'}."
    )


@pytest.mark.parametrize("block", sorted(CLOSED_BLOCK_PATHS))
async def test_extra_key_in_a_closed_block_is_rejected_by_its_own_validator(block: str):
    """RNF-006/RF-002: one extra key per closed block, rejected by its own validator."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    _closed_block_container(config, block)[EXTRA_BLOCK_KEY] = 1

    # 1) The own validator: RULES_SCHEMA closes the block and names the path.
    with pytest.raises(ValueError) as engine_error:
        validate_rules_config(config)
    message = str(engine_error.value)
    assert EXTRA_BLOCK_KEY in message
    for segment in _block_path_segments(block):
        assert segment in message, f"{block}: la ruta {segment!r} no aparece en {message!r}"

    # 2) The request model rejects too, because it delegates to that validator
    #    (the blocks stay ``dict[str, Any]``; the flag only closes the first level).
    with pytest.raises(ValidationError) as model_error:
        TournamentRulesConfig.model_validate(config)
    assert EXTRA_BLOCK_KEY in str(model_error.value)

    # 3) HTTP boundary: 422 (spec 019 case 26), written nowhere.
    assert await _patch_rules_status(config) == 422


# --- RF-004: los tres mapas abiertos, la única excepción del barrido ---


def _free_key_in_tiebreak_params(config: dict) -> None:
    """Open map 1: ``params`` of a ranking pipeline step accepts free keys."""

    config["ranking_pipeline"][0]["params"][FREE_OPEN_KEY] = "valor libre"


def _assert_tiebreak_params_survive(request: TournamentRulesConfig) -> None:
    dumped = request.model_dump()
    assert dumped["ranking_pipeline"][0]["params"][FREE_OPEN_KEY] == "valor libre"


def _free_key_in_override_index(config: dict) -> None:
    """Open map 2: the ``stage_overrides`` index (the value stays closed)."""

    config["stage_overrides"] = {FREE_OPEN_KEY: {"extra_time_enabled": False}}


def _assert_override_index_survives(request: TournamentRulesConfig) -> None:
    assert FREE_OPEN_KEY in request.stage_overrides


def _free_key_in_deprecated_transfers(config: dict) -> None:
    """Open map 3: the content of the deprecated ``transfers`` block."""

    config["transfers"] = {
        FREE_OPEN_KEY: "valor libre del bloque deprecado",
        "roster_lock_matchday": None,
    }


def _assert_transfers_accepted_not_written_back(request: TournamentRulesConfig) -> None:
    # Accepted on input with free keys, never written back (RF-003).
    assert request.transfers is None
    assert FREE_OPEN_KEY not in request.model_dump()


OPEN_MAP_CASES = (
    ("ranking_pipeline[].params", _free_key_in_tiebreak_params, _assert_tiebreak_params_survive),
    ("stage_overrides index", _free_key_in_override_index, _assert_override_index_survives),
    ("transfers content", _free_key_in_deprecated_transfers, _assert_transfers_accepted_not_written_back),
)


@pytest.mark.parametrize(
    ("open_map", "inject_free_key", "verify_survives"),
    OPEN_MAP_CASES,
    ids=[case[0] for case in OPEN_MAP_CASES],
)
async def test_the_three_open_maps_of_rf004_accept_a_free_key(
    open_map: str,
    inject_free_key,
    verify_survives,
):
    """RF-004/RNF-006: the sweep excludes exactly these three open maps."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    inject_free_key(config)

    # The own validator does not close them.
    validate_rules_config(config)

    request = TournamentRulesConfig.model_validate(config)
    verify_survives(request)

    assert await _patch_rules_status(config) == 200
