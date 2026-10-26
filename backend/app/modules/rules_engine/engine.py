from copy import deepcopy
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping
from uuid import UUID

from jsonschema import Draft7Validator

from app.modules.rules_engine.defaults import (
    DEFAULT_EXTRA_TIME_MINUTES,
    DEFAULT_GAME_FORMAT,
    DEFAULT_MAX_PLAYERS_PER_TEAM,
    DEFAULT_MIN_PLAYERS_PER_TEAM,
    DEFAULT_REGULAR_TIME_MINUTES,
    DEFAULT_STAGE_RULES,
    DEFAULT_SUBSTITUTIONS,
    GAME_FORMAT_CATALOG,
)


# RF-005: single source of truth for the top-level `rules_config` keys.
# Every key of ``RULES_SCHEMA["properties"]`` must be classified here as
# either applied or deprecated (``transfers``).
APPLIED_RULE_KEYS = frozenset({
    "schema_version",
    "engine_version",
    "game_format",
    "min_players_per_team",
    "max_players_per_team",
    "points_system",
    "ranking_pipeline",
    "substitutions",
    "discipline",
    "roster_lock_matchday",
    "stage_defaults",
    "stage_overrides",
})
DEPRECATED_RULE_KEYS = frozenset({"transfers"})


RULES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version", "engine_version", "points_system", "ranking_pipeline",
        "discipline", "stage_defaults", "stage_overrides",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"enum": ["3.2.0", "3.3.0"]},
        "engine_version": {"const": "2026.1"},
        # RF-042: purely declarative; it never derives nor bounds the limits.
        "game_format": {"enum": list(GAME_FORMAT_CATALOG)},
        # RF-044: 0 (or absent) means "no limit"; no extra ceiling is invented.
        "min_players_per_team": {"type": "integer", "minimum": 0},
        "max_players_per_team": {"type": "integer", "minimum": 0},
        "points_system": {
            "type": "object",
            "required": ["win", "draw", "loss"],
            "additionalProperties": False,
            "properties": {
                "win": {"type": "integer", "minimum": 0},
                "draw": {"type": "integer", "minimum": 0},
                "loss": {"type": "integer", "minimum": 0},
            },
        },
        "ranking_pipeline": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["step", "criterion", "params"],
                "additionalProperties": False,
                "properties": {
                    "step": {"type": "integer", "minimum": 1},
                    "criterion": {
                        "type": "string",
                        "enum": [
                            "points", "head_to_head", "goal_difference", "goals_for",
                            "goals_against", "fair_play_points", "random_draw",
                        ],
                    },
                    "params": {"type": "object"},
                },
            },
        },
        "substitutions": {
            "type": "object",
            "required": ["max_per_team", "max_windows", "allow_reentry"],
            "additionalProperties": False,
            "properties": {
                "max_per_team": {"type": "integer", "minimum": 0},
                "max_windows": {"type": "integer", "minimum": 0},
                "allow_reentry": {"type": "boolean"},
            },
        },
        "discipline": {
            "type": "object",
            "required": [
                "yellow_card_limit", "yellow_card_suspension_matches",
                "direct_red_suspension_matches", "clear_yellows_on_stage_change",
                "fair_play_penalties",
            ],
            "additionalProperties": False,
            "properties": {
                "yellow_card_limit": {"type": "integer", "minimum": 1},
                "yellow_card_suspension_matches": {"type": "integer", "minimum": 1},
                "direct_red_suspension_matches": {"type": "integer", "minimum": 1},
                "clear_yellows_on_stage_change": {"type": "boolean"},
                "fair_play_penalties": {
                    "type": "object",
                    "required": ["yellow_card", "double_yellow_red", "direct_red"],
                    "additionalProperties": False,
                    "properties": {
                        "yellow_card": {"type": "integer", "minimum": 0},
                        "double_yellow_red": {"type": "integer", "minimum": 0},
                        "direct_red": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        "roster_lock_matchday": {"type": ["integer", "null"], "minimum": 1},
        "transfers": {
            # Deprecated block: accepted and ignored, never written back.
            "type": "object",
        },
        "stage_defaults": {
            "type": "object",
            "required": ["extra_time_enabled", "penalties_enabled", "walkover_score"],
            "additionalProperties": False,
            "properties": {
                "extra_time_enabled": {"type": "boolean"},
                "penalties_enabled": {"type": "boolean"},
                "regular_time_minutes": {"type": "integer", "minimum": 1, "maximum": 179},
                "extra_time_minutes": {"type": "integer"},
                "walkover_score": {
                    "type": "object",
                    "required": ["winner", "loser"],
                    "additionalProperties": False,
                    "properties": {
                        "winner": {"type": "integer", "minimum": 0},
                        "loser": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        "stage_overrides": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "extra_time_enabled": {"type": "boolean"},
                    "penalties_enabled": {"type": "boolean"},
                    "regular_time_minutes": {"type": "integer", "minimum": 1, "maximum": 179},
                    "extra_time_minutes": {"type": "integer"},
                    "walkover_score": {
                        "type": "object",
                        "required": ["winner", "loser"],
                        "additionalProperties": False,
                        "properties": {
                            "winner": {"type": "integer", "minimum": 0},
                            "loser": {"type": "integer", "minimum": 0},
                        },
                    },
                },
            },
        },
    },
}


def effective_substitutions(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return the applied substitution limits, with read-time defaults."""
    declared = config.get("substitutions") or {}
    return {**deepcopy(DEFAULT_SUBSTITUTIONS), **deepcopy(dict(declared))}


def effective_roster_lock_matchday(config: Mapping[str, Any]) -> int | None:
    """Return the top-level matchday lock, falling back to the deprecated block."""
    top_level = config.get("roster_lock_matchday")
    if top_level is not None:
        return top_level
    transfers = config.get("transfers")
    if isinstance(transfers, Mapping):
        return transfers.get("roster_lock_matchday")
    return None


def _merged_stage_rules(
    config: Mapping[str, Any],
    override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    effective = deepcopy(DEFAULT_STAGE_RULES)
    effective.update(deepcopy(dict(config.get("stage_defaults") or {})))
    if override:
        effective.update(deepcopy(dict(override)))
    return effective


def effective_stage_rules(config: Mapping[str, Any], stage_id: UUID | str | None) -> dict[str, Any]:
    """Resolve stage minutes/flags key by key: defaults, stage_defaults, override."""
    overrides = config.get("stage_overrides") or {}
    override = overrides.get(str(stage_id)) if stage_id is not None else None
    return _merged_stage_rules(config, override)


def _validate_stage_minutes(scope: str, effective: Mapping[str, Any]) -> None:
    regular = effective.get("regular_time_minutes")
    if type(regular) is not int or not 1 <= regular <= 179:
        raise ValueError(
            f"{scope}: regular_time_minutes debe estar entre 1 y 179 "
            f"(par {regular}/{effective.get('extra_time_minutes')})"
        )
    if effective.get("extra_time_enabled"):
        extra = effective.get("extra_time_minutes")
        if type(extra) is not int or not regular < extra <= 180:
            raise ValueError(
                f"{scope}: extra_time_minutes debe ser mayor que regular_time_minutes "
                f"y menor o igual a 180 (par {regular}/{extra})"
            )


def validate_effective_rules(config: Mapping[str, Any]) -> None:
    """Validate the effective minutes pair for stage defaults and every override."""
    _validate_stage_minutes("stage_defaults", _merged_stage_rules(config))
    for stage_id, override in (config.get("stage_overrides") or {}).items():
        _validate_stage_minutes(f"stage_id {stage_id}", _merged_stage_rules(config, override))


def _walkover_pair(effective: Mapping[str, Any]) -> tuple[Any, Any]:
    score = effective.get("walkover_score")
    if not isinstance(score, Mapping):
        score = DEFAULT_STAGE_RULES["walkover_score"]
    return score.get("winner"), score.get("loser")


def validate_walkover_score(config: Mapping[str, Any]) -> None:
    """Require a leading winner in the walkover pair of every scope (RF-011).

    Deliberately **not** called from ``validate_rules_config``: that validator
    also runs when closing a match report, when recalculating the standings and
    when cloning a version, so revalidating here would break every resolution
    and every table of a version published with a historical pair (and an
    uncaught ``ValueError`` while cloning would be a 500). D-2 of the plan.
    """

    scopes = [("stage_defaults", _merged_stage_rules(config))]
    overrides = config.get("stage_overrides") or {}
    # Stable order (RNF-006): the first incoherent scope is always the same one.
    for stage_id in sorted(overrides, key=str):
        scopes.append((f"stage_id {stage_id}", _merged_stage_rules(config, overrides[stage_id])))

    for scope, effective in scopes:
        winner, loser = _walkover_pair(effective)
        pair = f"{winner}-{loser}"
        if (
            type(winner) is not int
            or type(loser) is not int
            or winner < 0
            or loser < 0
        ):
            raise ValueError(
                "Configuración de reglas inválida: "
                f"{scope}: el marcador de walkover requiere dos enteros no negativos "
                f"(par {pair})"
            )
        if winner <= loser:
            raise ValueError(
                "Configuración de reglas inválida: "
                f"{scope}: el marcador de walkover requiere un ganador por delante "
                f"(par {pair})"
            )


def normalize_rules_config(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Emit a 3.3.0 config: explicit substitutions, promoted lock, no transfers."""
    config = deepcopy(dict(raw))

    declared_substitutions = config.get("substitutions")
    config["substitutions"] = {
        **deepcopy(DEFAULT_SUBSTITUTIONS),
        **deepcopy(dict(declared_substitutions or {})),
    }

    inherited_lock = None
    transfers = config.get("transfers")
    if isinstance(transfers, Mapping):
        inherited_lock = transfers.get("roster_lock_matchday")
    if config.get("roster_lock_matchday") is None and inherited_lock is not None:
        config["roster_lock_matchday"] = inherited_lock
    config.setdefault("roster_lock_matchday", None)
    config.pop("transfers", None)

    config.setdefault("game_format", DEFAULT_GAME_FORMAT)
    config.setdefault("min_players_per_team", DEFAULT_MIN_PLAYERS_PER_TEAM)
    config.setdefault("max_players_per_team", DEFAULT_MAX_PLAYERS_PER_TEAM)

    config["schema_version"] = "3.3.0"
    config["stage_defaults"] = dict(config.get("stage_defaults") or {})

    # Validate the effective pair before materializing any default.
    validate_rules_config(config)

    stage_defaults = config["stage_defaults"]
    stage_defaults.setdefault("regular_time_minutes", DEFAULT_REGULAR_TIME_MINUTES)
    if stage_defaults.get("extra_time_enabled"):
        stage_defaults.setdefault("extra_time_minutes", DEFAULT_EXTRA_TIME_MINUTES)
    return config


def validate_rules_config(config: dict[str, Any]) -> None:
    errors = sorted(Draft7Validator(RULES_SCHEMA).iter_errors(config), key=lambda error: list(error.path))
    if errors:
        details = []
        for error in errors:
            path = ".".join(str(part) for part in error.path)
            details.append(f"{path}: {error.message}" if path else error.message)
        raise ValueError("Configuración de reglas inválida: " + "; ".join(details))

    # RF-044: only when both limits are greater than zero; 0 = no limit.
    minimum = config.get("min_players_per_team") or 0
    maximum = config.get("max_players_per_team") or 0
    if minimum and maximum and minimum > maximum:
        raise ValueError(
            "Configuración de reglas inválida: min_players_per_team "
            f"({minimum}) no puede ser mayor que max_players_per_team ({maximum})"
        )

    pipeline = config["ranking_pipeline"]
    steps = [item["step"] for item in pipeline]
    criteria = [item["criterion"] for item in pipeline]
    expected = list(range(1, len(pipeline) + 1))
    if steps != expected:
        raise ValueError(f"Los pasos del pipeline deben ser secuenciales: {expected}")
    if len(criteria) != len(set(criteria)):
        raise ValueError("No se permiten criterios duplicados")
    if criteria[0] != "points":
        raise ValueError("points debe ser el primer criterio")
    if "random_draw" in criteria and criteria[-1] != "random_draw":
        raise ValueError("random_draw debe ser el último criterio")
    for item in pipeline:
        if item["criterion"] == "head_to_head":
            rounds_expected = item["params"].get("total_rounds_expected")
            if type(rounds_expected) is not int or rounds_expected not in {1, 2}:
                raise ValueError("head_to_head requiere total_rounds_expected igual a 1 o 2")

    validate_effective_rules(config)


def remap_stage_overrides(
    config: Mapping[str, Any],
    stage_map: Mapping[str, UUID | str],
) -> dict[str, Any]:
    """Copy a rules config while moving per-stage overrides to cloned stage IDs."""
    cloned = deepcopy(dict(config))
    overrides = cloned.get("stage_overrides")
    if not isinstance(overrides, dict):
        return cloned

    cloned["stage_overrides"] = {
        str(stage_map.get(str(stage_id), stage_id)): override
        for stage_id, override in overrides.items()
    }
    return cloned


@dataclass(frozen=True)
class MatchOutcome:
    home_score: int
    away_score: int
    winner_team_id: UUID | None
    home_penalties: int | None
    away_penalties: int | None


def _goal_credit(event: dict[str, Any]) -> UUID:
    if event["event_type"] == "own_goal":
        return UUID(str(event["beneficiary_team_id"]))
    return UUID(str(event["team_id"]))


def compute_match_outcome(
    config: dict[str, Any],
    events: list[dict[str, Any]],
    resolution_type: str,
    home_team_id: UUID,
    away_team_id: UUID,
    home_score_regular: int,
    away_score_regular: int,
    home_score: int | None,
    away_score: int | None,
    home_penalties: int | None,
    away_penalties: int | None,
    winner_team_id: UUID | None,
) -> MatchOutcome:
    validate_rules_config(config)
    participants = {home_team_id, away_team_id}
    if winner_team_id is not None and winner_team_id not in participants:
        raise ValueError("El ganador informado no participa en el partido")
    stage_defaults = config["stage_defaults"]
    if resolution_type == "extra_time" and not stage_defaults["extra_time_enabled"]:
        raise ValueError("La prórroga no está habilitada para esta fase")
    if resolution_type == "penalties" and not stage_defaults["penalties_enabled"]:
        raise ValueError("Los penales no están habilitados para esta fase")
    if resolution_type in {"walkover", "administrative"}:
        if winner_team_id is None:
            raise ValueError("La resolución requiere un ganador")
        score = config["stage_defaults"]["walkover_score"]
        if resolution_type == "walkover":
            expected_home = score["winner"] if winner_team_id == home_team_id else score["loser"]
            expected_away = score["winner"] if winner_team_id == away_team_id else score["loser"]
            if (home_score_regular, away_score_regular) != (expected_home, expected_away):
                raise ValueError("El marcador de walkover no coincide con la configuración")
            if home_score is not None and home_score != expected_home:
                raise ValueError("El marcador final de walkover no coincide con la configuración")
            if away_score is not None and away_score != expected_away:
                raise ValueError("El marcador final de walkover no coincide con la configuración")
            return MatchOutcome(
                home_score=expected_home,
                away_score=expected_away,
                winner_team_id=winner_team_id,
                home_penalties=None,
                away_penalties=None,
            )
        if home_score is None or away_score is None:
            raise ValueError("La resolución administrativa requiere marcador final")
        if (home_score_regular, away_score_regular) != (home_score, away_score):
            raise ValueError("La resolución administrativa requiere un único marcador final")
        return MatchOutcome(home_score, away_score, winner_team_id, None, None)

    counted_goals: defaultdict[UUID, int] = defaultdict(int)
    for event in events:
        if event["event_type"] in {"goal", "own_goal", "penalty_goal"}:
            counted_goals[_goal_credit(event)] += 1

    event_home_goals = counted_goals[home_team_id]
    event_away_goals = counted_goals[away_team_id]
    if resolution_type == "regular" and (event_home_goals != home_score_regular or event_away_goals != away_score_regular):
        raise ValueError("El marcador no coincide con los eventos de gol")
    if resolution_type == "regular" and (
        (home_score is not None and home_score != home_score_regular)
        or (away_score is not None and away_score != away_score_regular)
    ):
        raise ValueError("Un partido regular no puede tener marcador de prórroga")

    final_home = home_score if home_score is not None else event_home_goals
    final_away = away_score if away_score is not None else event_away_goals
    if final_home < home_score_regular or final_away < away_score_regular:
        raise ValueError("El marcador final no puede ser menor al reglamentario")

    if resolution_type == "penalties":
        if home_penalties is None or away_penalties is None or final_home != final_away:
            raise ValueError("Los penales requieren empate después de la prórroga")
        if home_penalties == away_penalties:
            raise ValueError("La tanda de penales debe tener un ganador")
        winner = home_team_id if home_penalties > away_penalties else away_team_id
    elif final_home == final_away:
        winner = None
    else:
        winner = home_team_id if final_home > final_away else away_team_id

    if winner_team_id is not None and winner_team_id != winner:
        raise ValueError("El ganador informado no coincide con el marcador")

    return MatchOutcome(final_home, final_away, winner, home_penalties, away_penalties)


def evaluate_suspensions(
    config: dict[str, Any],
    current_events: list[dict[str, Any]],
    historical_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    yellow_limit = config["discipline"]["yellow_card_limit"]
    direct_red_matches = config["discipline"]["direct_red_suspension_matches"]
    yellow_matches = config["discipline"]["yellow_card_suspension_matches"]
    all_events = [*historical_events, *current_events]
    yellows: defaultdict[UUID, int] = defaultdict(int)
    result: list[dict[str, Any]] = []

    for event in all_events:
        player_id = event.get("player_id")
        if not player_id:
            continue
        player_uuid = UUID(str(player_id))
        if event["event_type"] == "yellow_card":
            yellows[player_uuid] += 1
            if yellows[player_uuid] % yellow_limit == 0:
                result.append({
                    "player_id": player_uuid,
                    "source_event_id": UUID(str(event["id"])),
                    "matches_suspended": yellow_matches,
                    "scope": "organization",
                    "reason": "yellow_card_accumulation",
                })
        elif event["event_type"] == "red_card":
            metadata = event.get("metadata") or {}
            is_double_yellow = metadata.get("red_card_type") == "double_yellow_red"
            result.append({
                "player_id": player_uuid,
                "source_event_id": UUID(str(event["id"])),
                "matches_suspended": direct_red_matches,
                "scope": "organization",
                "reason": "double_yellow_red" if is_double_yellow else "direct_red_card",
            })

    unique: dict[str, dict[str, Any]] = {}
    for item in result:
        unique[f"{item['player_id']}:{item['source_event_id']}:{item['reason']}"] = item
    return list(unique.values())


def deterministic_tie_value(seed: str, team_id: UUID) -> str:
    return sha256(f"{seed}:{team_id}".encode("utf-8")).hexdigest()
