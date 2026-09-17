from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


InvitationRole = Literal["administrator", "operator", "referee", "viewer"]


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role_code: InvitationRole


class InvitationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    email: EmailStr
    role_code: InvitationRole
    expires_at: datetime
    status: Literal["pending", "accepted", "expired", "revoked"]
    invited_by_member_id: UUID
    accepted_by_user_id: UUID | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    invite_url: str | None = None


class InvitationPreviewResponse(BaseModel):
    invitation_id: UUID
    organization_id: UUID
    organization_name: str
    email: EmailStr
    role_code: InvitationRole
    expires_at: datetime
    status: Literal["pending", "accepted", "expired", "revoked"]
    requires_login: bool


class AcceptInvitationRequest(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    full_name: str | None = Field(default=None, min_length=2, max_length=100)


class AcceptInvitationResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    user_id: UUID
    organization_id: UUID
    organization_user_id: UUID
    role_code: InvitationRole
    created_user: bool


class OrganizationAccessResponse(BaseModel):
    organization_id: UUID
    organization_user_id: UUID
    user_id: UUID
    role_code: str
    permissions: list[str]


class MemberResponse(BaseModel):
    organization_user_id: UUID
    user_id: UUID
    email: EmailStr
    full_name: str
    is_active: bool
    role_code: str
    created_at: datetime


class UpdateMemberRoleRequest(BaseModel):
    role_code: InvitationRole


class UpdateMemberActiveRequest(BaseModel):
    is_active: bool
