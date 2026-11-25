"""Auditoría organizacional de webhooks (spec 047, RF-004).

El ``payload`` guarda solo el dominio de la URL (``host``), los tipos suscritos y
el estado: nunca la ruta, la consulta ni el secreto. El responsable es el
miembro (``organization_users.id``). Se escribe dentro de la transacción de la
operación, así una operación revertida no deja entrada.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WEBHOOK_ENTITY_TYPE = "organization_webhooks"
CREATE_WEBHOOK = "CREATE_WEBHOOK"
UPDATE_WEBHOOK = "UPDATE_WEBHOOK"
ROTATE_WEBHOOK_SECRET = "ROTATE_WEBHOOK_SECRET"
SET_WEBHOOK_ACTIVE = "SET_WEBHOOK_ACTIVE"
DELETE_WEBHOOK = "DELETE_WEBHOOK"

_ACTIONS = (CREATE_WEBHOOK, UPDATE_WEBHOOK, ROTATE_WEBHOOK_SECRET, SET_WEBHOOK_ACTIVE, DELETE_WEBHOOK)


async def record_webhook_audit(
    db: AsyncSession, context, *, webhook_id: UUID | str, action: str, payload: dict[str, Any]
) -> None:
    if action not in _ACTIONS:
        raise ValueError(f"Acción de auditoría de webhook no admitida: {action!r}")
    await db.execute(
        text("""
            INSERT INTO administrative_audit_logs
                (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
            VALUES (:organization_id, :entity_type, :entity_id, :action, CAST(:payload AS jsonb), :member_id)
        """),
        {
            "organization_id": str(context.organization_id),
            "entity_type": WEBHOOK_ENTITY_TYPE,
            "entity_id": str(webhook_id),
            "action": action,
            "payload": json.dumps(payload),
            "member_id": str(context.organization_user_id),
        },
    )
