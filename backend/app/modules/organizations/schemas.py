from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrganizationSummaryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    organization_user_id: UUID


class OrganizationCreateRequest(BaseModel):
    """Alta explícita desde una sesión sin organización (RF-23, RF-24)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")


class CurrentOrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
