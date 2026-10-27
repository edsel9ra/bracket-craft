from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.rules_engine.defaults import (
    DEFAULT_GAME_FORMAT,
    DEFAULT_MAX_PLAYERS_PER_TEAM,
    DEFAULT_MIN_PLAYERS_PER_TEAM,
    DEFAULT_RULES_CONFIG,
)
from app.modules.rules_engine.engine import (
    normalize_rules_config,
    validate_walkover_score,
)


class TournamentRulesConfig(BaseModel):
    # Spec 019 (plan §6 D-2): solo se cierra el primer nivel; los bloques
    # internos conservan su validador propio y ``transfers`` se sigue aceptando
    # en la entrada.
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "3.3.0"
    engine_version: str = "2026.1"
    game_format: str = DEFAULT_GAME_FORMAT
    min_players_per_team: int = Field(default=DEFAULT_MIN_PLAYERS_PER_TEAM, ge=0, strict=True)
    max_players_per_team: int = Field(default=DEFAULT_MAX_PLAYERS_PER_TEAM, ge=0, strict=True)
    points_system: dict[str, int]
    ranking_pipeline: list[dict[str, Any]]
    substitutions: dict[str, Any] | None = None
    roster_lock_matchday: int | None = Field(default=None, ge=1)
    discipline: dict[str, Any]
    transfers: dict[str, Any] | None = Field(default=None, exclude=True)
    stage_defaults: dict[str, Any]
    stage_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> "TournamentRulesConfig":
        raw = self.model_dump(exclude_none=True)
        if self.transfers is not None:
            raw["transfers"] = self.transfers
        normalized = normalize_rules_config(raw)
        # RF-011: saving and updating rules is a configuration limit; the pair
        # is validated here only, never inside ``validate_rules_config`` (D-2).
        validate_walkover_score(normalized)
        for name, value in normalized.items():
            setattr(self, name, value)
        # Deprecated block: accepted on input, never written back.
        self.transfers = None
        return self


class CreateTournamentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    season: str = Field(min_length=1, max_length=20)
    start_date: date
    rules_config: TournamentRulesConfig = Field(
        default_factory=lambda: TournamentRulesConfig.model_validate(DEFAULT_RULES_CONFIG)
    )


class UpdateRulesConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules_config: TournamentRulesConfig
