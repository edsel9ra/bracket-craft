"""Inert response union; production public routes keep their existing model."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.tournaments.schemas import PublicMatchResponse


class PublicClockFields(BaseModel):
    is_provisional: Literal[True] = True
    clock_segment_number: int | None
    clock_elapsed_seconds: int | None
    clock_state: Literal["not_started", "running", "paused"]
    clock_observed_at: AwareDatetime


class SuspendedPublicMatchResponse(PublicClockFields):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tournament_id: UUID
    home_team_id: UUID
    home_team_name: str
    away_team_id: UUID
    away_team_name: str
    status: Literal["suspended"]
    home_score: int
    away_score: int
    clock_state: Literal["not_started", "paused"]


class LivePublicMatchResponse(PublicMatchResponse, PublicClockFields):
    status: Literal["live"]


class ClassicPublicMatchResponse(PublicMatchResponse):
    status: Literal["scheduled", "finished", "cancelled", "administrative_resolution"]


PublicMatchStateResponse = Annotated[
    SuspendedPublicMatchResponse | LivePublicMatchResponse | ClassicPublicMatchResponse,
    Field(discriminator="status"),
]
