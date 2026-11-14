"""Strict contracts for F1; not registered with any production router."""

from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload, client_event_identity


Revision = Annotated[int, Field(strict=True, ge=0)]
ElapsedMicroseconds = Annotated[int, Field(strict=True, ge=0)]


class LiveCommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_revision: Revision


class LiveStateCommand(LiveCommandBase):
    type: Literal["start", "suspend", "resume"]


class LiveStartClockCommand(LiveCommandBase):
    type: Literal["start_clock"]
    segment_id: UUID


class LivePauseResumeClockCommand(LiveCommandBase):
    type: Literal["pause_clock", "resume_clock"]


class LiveCorrectClockCommand(LiveCommandBase):
    type: Literal["correct_clock"]
    segment_id: UUID
    elapsed_us: ElapsedMicroseconds


class LiveEventPayload(MatchEventPayload):
    @field_validator("client_event_id")
    @classmethod
    def canonical_identity(cls, value: str) -> str:
        return client_event_identity(value)


class LiveAddEventCommand(LiveCommandBase):
    type: Literal["add_event"]
    event: LiveEventPayload


class LiveCorrectEventCommand(LiveCommandBase):
    type: Literal["correct_event"]
    event_id: UUID
    event: LiveEventPayload


class LiveRemoveEventCommand(LiveCommandBase):
    type: Literal["remove_event"]
    event_id: UUID


LiveCommand = Annotated[
    LiveStateCommand | LiveStartClockCommand | LivePauseResumeClockCommand
    | LiveCorrectClockCommand | LiveAddEventCommand | LiveCorrectEventCommand
    | LiveRemoveEventCommand,
    Field(discriminator="type"),
]


class LiveAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    can_view: bool = Field(strict=True)
    can_operate: bool = Field(strict=True)
    can_close: bool = Field(strict=True)
    available: bool = Field(strict=True)


class LiveCommandAck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    revision: Revision


class LiveReportDTO(CloseMatchReportDTO):
    events: list[LiveEventPayload] = Field(default_factory=list, max_length=500)


class LiveResultDTO(CloseMatchReportDTO):
    events: list[MatchEventPayload] = Field(default_factory=list, max_length=0, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def no_client_events(cls, value):
        if isinstance(value, dict) and "events" in value:
            raise ValueError("El resultado no admite hechos del cliente")
        if isinstance(value, CloseMatchReportDTO) and value.events:
            raise ValueError("El resultado no admite hechos del cliente")
        return value


class LiveReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_revision: Revision
    result: LiveResultDTO


class LiveCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    live_review_id: UUID
    result: LiveResultDTO


class LiveClockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["not_started", "running", "paused"]
    segment_id: UUID | None = None
    segment_number: Annotated[int, Field(strict=True, ge=1)] | None = None
    elapsed_us: ElapsedMicroseconds | None = None
    anchor_at: AwareDatetime | None = None
    observed_at: AwareDatetime

    @field_validator("anchor_at", "observed_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("El instante debe ser UTC aware")
        return value

    @model_validator(mode="after")
    def valid_reference(self) -> "LiveClockResponse":
        reference = (self.segment_id, self.segment_number, self.elapsed_us)
        if self.state == "not_started":
            if any(value is not None for value in (*reference, self.anchor_at)):
                raise ValueError("El reloj sin iniciar no admite referencia")
        elif any(value is None for value in reference) or (self.state == "running") != (self.anchor_at is not None):
            raise ValueError("Referencia de reloj inválida")
        return self


class LiveSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initialized: bool = Field(strict=True)
    status: Literal["scheduled", "live", "suspended", "finished", "walkover", "abandoned", "cancelled", "postponed"]
    revision: Revision | None = None
    content_revision: Revision | None = None
    events: list[LiveEventPayload] = Field(default_factory=list, max_length=500)
    home_score: Revision | None = None
    away_score: Revision | None = None
    clock: LiveClockResponse | None = None

    @model_validator(mode="after")
    def coherent_snapshot(self) -> "LiveSnapshotResponse":
        state = (self.revision, self.content_revision, self.home_score, self.away_score, self.clock)
        if self.initialized:
            if any(value is None for value in state):
                raise ValueError("El estado inicializado requiere revisiones, marcador y reloj")
            if self.status != "live" and self.clock.state == "running":
                raise ValueError("Solo un partido live puede tener reloj en marcha")
        elif self.events or any(value is not None for value in state):
            raise ValueError("El estado sin inicializar no admite borrador")
        return self
