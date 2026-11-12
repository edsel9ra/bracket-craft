from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.matches.schemas import CloseMatchReportDTO


class CreateRectificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposed_report: CloseMatchReportDTO
    reason: str = Field(min_length=1)
    evidence: str = Field(min_length=1)

    @field_validator("reason", "evidence")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El texto no puede estar vacío")
        return value


class RectificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    match_id: UUID
    base_version_number: int
    proposed_report: dict[str, Any]
    reason: str
    evidence: str | None
    requested_by_user_id: UUID
    requested_by_member_id: UUID
    requested_at: datetime
    status: Literal["pending", "rejected", "withdrawn", "published"]
    withdrawn_at: datetime | None
    resulting_version_id: UUID | None


class ReportEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    segment_id: UUID
    team_id: UUID
    beneficiary_team_id: UUID | None
    player_id: UUID
    event_type: str
    minute: int
    added_minute: int
    client_event_id: str
    assist_player_id: UUID | None
    player_out_id: UUID | None
    player_in_id: UUID | None
    metadata: dict[str, Any]
    is_voided: bool
    voided_at: datetime | None
    voided_by_member_id: UUID | None
    void_reason: str | None
    created_at: datetime


class ReportContentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_type: str | None
    resolution_reason: str | None
    home_score_regular: int | None
    away_score_regular: int | None
    home_score: int | None
    away_score: int | None
    home_penalties: int | None
    away_penalties: int | None
    winner_team_id: UUID | None
    events: list[ReportEventResponse]


class ReportVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_id: UUID
    version_number: int
    published_at: datetime | None
    published_by_user_id: UUID | None
    request_id: UUID | None
    reason: str | None
    evidence: str | None
    report: ReportContentResponse
