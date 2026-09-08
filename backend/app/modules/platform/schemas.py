from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PlatformUserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
    organization_count: int


class PlatformOrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    member_count: int


class PlatformAuditResponse(BaseModel):
    id: UUID
    actor_user_id: UUID
    actor_email: str
    action: str
    target_type: str
    target_id: UUID | None = None
    organization_id: UUID | None = None
    payload: dict
    created_at: datetime


class PlatformMembershipResponse(BaseModel):
    organization_user_id: UUID
    user_id: UUID
    email: str
    full_name: str
    is_active: bool
    role_codes: list[str]


class CreateMembershipRequest(BaseModel):
    user_id: UUID
    role_code: str = Field(pattern=r"^(owner|administrator|operator|referee|viewer)$")


class SetActiveRequest(BaseModel):
    is_active: bool


class OutboxReprocessRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)


class PlatformListResponse(BaseModel):
    items: list[dict[str, Any]]
    limit: int
    offset: int
