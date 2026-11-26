"""Contratos de «Equipo del torneo» (spec 049, D11): sin correo ni datos del usuario."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TournamentTeamMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_user_id: UUID
    full_name: str
    organization_role_code: str
    role_code: Literal["tournament_operator"]
    is_active: bool
    adds_permissions: bool
    assigned_at: datetime
