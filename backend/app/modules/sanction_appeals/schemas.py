from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El motivo no puede estar vacío")
        return value.strip()


class EvidenceRequest(ReasonRequest):
    evidence_text: str | None = None
    evidence_links: list[HttpUrl] = Field(default_factory=list)


class AppealRequest(EvidenceRequest):
    suspension_id: UUID
    represented_player_id: UUID | None = None
    represented_team_id: UUID | None = None
    prior_case_id: UUID | None = None

    @model_validator(mode="after")
    def representation(self):
        if (self.represented_player_id is None) == (self.represented_team_id is None):
            raise ValueError("Debe representar a un jugador o a un equipo")
        return self


class ProposalRequest(EvidenceRequest):
    suspension_id: UUID
    proposed_action: Literal["annul", "reduce"]
    proposed_duration: int | None = Field(default=None, ge=0, strict=True)
    prior_case_id: UUID | None = None

    @model_validator(mode="after")
    def measure(self):
        if (self.proposed_action == "reduce") != (self.proposed_duration is not None):
            raise ValueError("Solo una reducción exige duración")
        return self


class DecisionRequest(EvidenceRequest):
    decision: Literal["maintain", "annul", "reduce", "approve", "reject"]
    expected_base_duration: int = Field(gt=0, strict=True)
    after_duration: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def measure(self):
        if self.decision == "reduce" and self.after_duration is None:
            raise ValueError("La reducción exige duración")
        if self.decision not in {"reduce", "approve"} and self.after_duration is not None:
            raise ValueError("La decisión no admite duración")
        if self.after_duration is not None and self.after_duration >= self.expected_base_duration:
            raise ValueError("La reducción debe disminuir la duración vigente")
        return self


class WithdrawalRequest(ReasonRequest):
    pass


class SuspensionWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_id: UUID
    remaining: int = Field(gt=0)


class CaseFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "resolved", "withdrawn", "closed_by_rectification"] | None = None
    case_type: Literal["appeal", "administrative_proposal"] | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
