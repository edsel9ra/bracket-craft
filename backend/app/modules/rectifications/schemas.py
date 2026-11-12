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


class RectificationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1)
    expected_base_version: int = Field(ge=1)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El motivo no puede estar vacío")
        return value


class CloseCompetitiveImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El motivo no puede estar vacío")
        return value.strip()


class CompetitiveImpactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    version_id: UUID
    match_id: UUID
    affected_items: list[dict[str, Any]]
    status: Literal["open", "closed"]
    resolution: Literal["keep_as_played"] | None
    reason: str | None
    closed_by_user_id: UUID | None
    closed_at: datetime | None
    created_at: datetime


class PlatformAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_admin_email: str
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El motivo no puede estar vacío")
        return value.strip()


class PlatformAuthorizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    request_id: UUID
    granted_by_member_id: UUID
    platform_admin_user_id: UUID
    reason: str
    granted_at: datetime
    revoked_at: datetime | None
    consumed_at: datetime | None


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


class FieldDifference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    before: Any
    after: Any


class EventDifference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_event_id: str
    fields: list[FieldDifference]


class EventDifferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added: list[dict[str, Any]]
    removed: list[dict[str, Any]]
    changed: list[EventDifference]


class ReportDifference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[FieldDifference]
    events: EventDifferences


class RectificationDetailResponse(RectificationResponse):
    diff: ReportDifference


class OrganizationListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tournament_id: UUID | None = None
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RectificationListQuery(OrganizationListQuery):
    status: Literal["pending", "rejected", "withdrawn", "published"] | None = None


class CompetitiveImpactListQuery(OrganizationListQuery):
    status: Literal["open", "closed"] | None = None


class RectificationPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RectificationResponse]
    total: int
    limit: int
    offset: int


class CompetitiveImpactPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CompetitiveImpactResponse]
    total: int
    limit: int
    offset: int


class RectificationPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: ReportVersionResponse
    effects: list[dict[str, Any]]
    expected_base_version: int


class PlatformRectificationDetailResponse(RectificationDetailResponse):
    current_version: ReportVersionResponse
