"""Auditoría organizacional de la descarga de plantillas (spec 048, RF-007).

El ``payload`` guarda solo el número de filas, nunca nombres de jugadores. Se
escribe en la transacción de la lectura y solo si el archivo se genera.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EXPORT_ENTITY_TYPE = "tournaments"
EXPORT_TOURNAMENT_ROSTERS = "EXPORT_TOURNAMENT_ROSTERS"


async def record_roster_export_audit(db: AsyncSession, context, tournament_id: UUID, row_count: int) -> None:
    await db.execute(
        text("""
            INSERT INTO administrative_audit_logs
                (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
            VALUES (:organization_id, :entity_type, :entity_id, :action, CAST(:payload AS jsonb), :member_id)
        """),
        {
            "organization_id": str(context.organization_id),
            "entity_type": EXPORT_ENTITY_TYPE,
            "entity_id": str(tournament_id),
            "action": EXPORT_TOURNAMENT_ROSTERS,
            "payload": json.dumps({"row_count": row_count}),
            "member_id": str(context.organization_user_id),
        },
    )
