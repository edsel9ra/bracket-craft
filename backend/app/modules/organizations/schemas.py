from uuid import UUID

from pydantic import BaseModel


class OrganizationSummaryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    organization_user_id: UUID


class CurrentOrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
