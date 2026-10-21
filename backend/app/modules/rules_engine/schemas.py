from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import normalize_rules_config


class TournamentRulesConfig(BaseModel):
    schema_version: str = "3.3.0"
    engine_version: str = "2026.1"
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
        for name, value in normalized.items():
            setattr(self, name, value)
        # Deprecated block: accepted on input, never written back.
        self.transfers = None
        return self


class CreateTournamentRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    season: str = Field(min_length=1, max_length=20)
    start_date: date
    rules_config: TournamentRulesConfig = Field(
        default_factory=lambda: TournamentRulesConfig.model_validate(DEFAULT_RULES_CONFIG)
    )


class UpdateRulesConfigRequest(BaseModel):
    rules_config: TournamentRulesConfig
