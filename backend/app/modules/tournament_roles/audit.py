"""Auditoría organizacional del operador del torneo (spec 049, D10, RF-013).

Se escribe en la transacción del cambio; el ``payload`` guarda solo el miembro y el rol.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tournament_roles.catalog import audit_payload

AUDIT_ENTITY_TYPE = "tournaments"
ASSIGN_TOURNAMENT_OPERATOR = "ASSIGN_TOURNAMENT_OPERATOR"
REMOVE_TOURNAMENT_OPERATOR = "REMOVE_TOURNAMENT_OPERATOR"


async def record_tournament_role_audit(
    db: AsyncSession, context, tournament_id: UUID, organization_user_id: UUID, action: str
) -> None:
    await db.execute(
        text("""
            INSERT INTO administrative_audit_logs
                (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
            VALUES (:organization_id, :entity_type, :entity_id, :action, CAST(:payload AS jsonb), :member_id)
        """),
        {
            "organization_id": str(context.organization_id),
            "entity_type": AUDIT_ENTITY_TYPE,
            "entity_id": str(tournament_id),
            "action": action,
            "payload": json.dumps(audit_payload(organization_user_id)),
            "member_id": str(context.organization_user_id),
        },
    )
