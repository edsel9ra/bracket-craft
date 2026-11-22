from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic import field_validator, model_validator

from app.modules.organization_audit.catalog import CATALOG


class OrganizationAuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    action: list[str] = Field(default_factory=list, max_length=len(CATALOG))
    actor_member_id: UUID | None = None
    date_from: AwareDatetime | None = Field(default=None, alias="from")
    date_to: AwareDatetime | None = Field(default=None, alias="to")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("action")
    @classmethod
    def cataloged_actions(cls, value: list[str]) -> list[str]:
        if any(action not in CATALOG for action in value):
            raise ValueError("Acción fuera del catálogo")
        return sorted(set(value))

    @model_validator(mode="after")
    def ordered_range(self) -> OrganizationAuditQuery:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("El rango de fechas está invertido")
        return self


class AuditActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["member", "platform"]
    member_id: UUID | None
    name: str | None


class AuditDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: StrictBool | StrictInt | StrictFloat | StrictStr


class OrganizationAuditItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    performed_at: AwareDatetime
    action: str
    cataloged: bool
    entity_type: str
    entity_id: UUID
    entity_available: bool
    actor: AuditActor
    details: list[AuditDetail] | None


class OrganizationAuditPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OrganizationAuditItem]
    total: int
    limit: int
    offset: int


class OrganizationAuditActor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: UUID
    name: str
