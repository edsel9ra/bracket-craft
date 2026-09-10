from copy import deepcopy
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping
from uuid import UUID

from jsonschema import Draft7Validator

from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG


RULES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version", "engine_version", "points_system", "ranking_pipeline",
        "substitutions", "discipline", "transfers", "stage_defaults", "stage_overrides",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": "3.2.0"},
        "engine_version": {"const": "2026.1"},
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
        "transfers": {
            "type": "object",
            "required": [
                "allow_mid_season_transfers", "same_matchday_participation_allowed",
                "roster_lock_matchday",
            ],
            "additionalProperties": False,
            "properties": {
                "allow_mid_season_transfers": {"type": "boolean"},
                "same_matchday_participation_allowed": {"type": "boolean"},
                "roster_lock_matchday": {"type": ["integer", "null"], "minimum": 1},
            },
        },
        "stage_defaults": {
            "type": "object",
            "required": ["extra_time_enabled", "penalties_enabled", "walkover_score"],
            "additionalProperties": False,
            "properties": {
                "extra_time_enabled": {"type": "boolean"},
                "penalties_enabled": {"type": "boolean"},
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


def validate_rules_config(config: dict[str, Any]) -> None:
    errors = sorted(Draft7Validator(RULES_SCHEMA).iter_errors(config), key=lambda error: list(error.path))
    if errors:
        raise ValueError("Configuración de reglas inválida: " + "; ".join(error.message for error in errors))

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
