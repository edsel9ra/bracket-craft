"""Auditoría organizacional de las operaciones de invitación (RF-004).

Solo la reapertura de una invitación revocada deja una entrada nueva; crear,
reenviar y revocar no añaden ninguna y la aceptación conserva su
``ACCEPT_INVITATION`` (migración 014). El payload guarda solo identificadores y
códigos de rol y estado: nunca correo, token, enlace ni nombre.
``record_invitation_audit`` ejecuta el ``INSERT`` y lo hace dentro de la
transacción del llamador, de modo que una operación revertida no deja entrada.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INVITATION_ENTITY_TYPE = "organization_invitations"
REOPEN_INVITATION = "REOPEN_INVITATION"


def reopen_audit_payload(
    role_code: str,
    previous_status: str = "revoked",
) -> dict[str, str]:
    """Payload puro de la reapertura: solo códigos, sin datos de la persona."""

    return {"previous_status": previous_status, "role_code": role_code}


async def record_invitation_audit(
    db: AsyncSession,
    *,
    organization_id: UUID,
    member_id: UUID,
    invitation_id: UUID,
    action: str,
    payload: dict[str, Any],
) -> None:
    """Insert one invitation audit entry inside the caller's transaction."""

    await db.execute(
        text("""
            INSERT INTO administrative_audit_logs
                (organization_id, entity_type, entity_id, action, payload,
                 performed_by_member_id)
            VALUES (
                :organization_id,
                :entity_type,
                :entity_id,
                :action,
                CAST(:payload AS jsonb),
                :member_id
            )
        """),
        {
            "organization_id": str(organization_id),
            "entity_type": INVITATION_ENTITY_TYPE,
            "entity_id": str(invitation_id),
            "action": action,
            "payload": json.dumps(payload, default=str),
            "member_id": str(member_id),
        },
    )
