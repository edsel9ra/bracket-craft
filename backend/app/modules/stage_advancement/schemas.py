from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.stage_advancement.origins import BEST_OF_POSITION, GROUP_POSITION, MAX_SLOTS, MIN_SLOTS

STRICT = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SlotOriginIn(BaseModel):
    model_config = STRICT

    kind: Literal["group_position", "best_of_position"]
    source_stage_id: UUID
    position: int = Field(ge=1, le=999)
    group_id: UUID | None = None
    ordinal: int | None = Field(default=None, ge=1, le=999)

    @model_validator(mode="after")
    def check_kind_fields(self) -> "SlotOriginIn":
        if self.kind == GROUP_POSITION and self.ordinal is not None:
            raise ValueError("Una posición de grupo no lleva ordinal")
        if self.kind == BEST_OF_POSITION and (self.ordinal is None or self.group_id is not None):
            raise ValueError("«Mejores N.º» necesita un ordinal y ningún grupo")
        return self


class SlotOriginOut(SlotOriginIn):
    seed: int


class SlotOriginsUpdateRequest(BaseModel):
    model_config = STRICT

    origins: list[SlotOriginIn] = Field(min_length=MIN_SLOTS, max_length=MAX_SLOTS)
    start_date: datetime
    round_interval_days: int = Field(default=7, ge=1, le=365)
    match_interval_hours: int = Field(default=2, ge=1, le=168)
    replace_existing: bool = False


class SourceGroupOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID | None
    name: str | None
    size: int


class SourceStageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    stage_type: str
    groups: list[SourceGroupOut]


class SlotOriginsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID
    stage_type: str
    status: Literal["editable", "frozen", "resolved"]
    origins: list[SlotOriginOut]
    source_stages: list[SourceStageOut]


class SlotOriginsTemplateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_stage_id: UUID
    slots_count: int
    origins: list[SlotOriginOut]


class SlotPreviewOut(SlotOriginOut):
    team_id: UUID | None
    team_name: str | None
    reason: str | None


class SourceStageStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    finished: bool


class ResolutionPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: UUID
    fingerprint: str
    resolvable: bool
    slots: list[SlotPreviewOut]
    source_stages: list[SourceStageStateOut]


class ResolutionConfirmRequest(BaseModel):
    model_config = STRICT

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResolutionResponse(ResolutionPreviewResponse):
    resolution_id: UUID
    resolved_at: datetime
