from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import validate_rules_config


class TournamentRulesConfig(BaseModel):
    schema_version: str = "3.2.0"
    engine_version: str = "2026.1"
    points_system: dict[str, int]
    ranking_pipeline: list[dict[str, Any]]
    substitutions: dict[str, Any]
    discipline: dict[str, Any]
    transfers: dict[str, Any]
    stage_defaults: dict[str, Any]
    stage_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_config(self) -> "TournamentRulesConfig":
        validate_rules_config(self.model_dump())
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
