"""Organisational audit for team crest changes (RF-45, RF-46, RNF-7).

Two operations leave one entry in ``administrative_audit_logs``: an upload or a
replacement (``SET_TEAM_CREST``) and a deletion that effectively removes an
existing image (``REMOVE_TEAM_CREST``). The entry depends on the **state
transition** —the object key before and after—, so a deletion without an image
or a repeated deletion writes nothing: ``crest_audit_action`` returns ``None``
and ``record_crest_audit`` refuses to write a non-effective action.

The payload keeps the tournament identifier only: never the object key, the file
name, the content type, the size, the content or any personal data. The actor is
the organisation member (``AuthContext.organization_user_id``), because
``performed_by_member_id`` references ``organization_users``; the auth
``user_id`` is not stored here. ``record_crest_audit`` only executes the
``INSERT``; the caller runs it inside its own transaction, so a failed or
reverted operation leaves no entry.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TEAM_ENTITY_TYPE = "teams"
SET_TEAM_CREST = "SET_TEAM_CREST"
REMOVE_TEAM_CREST = "REMOVE_TEAM_CREST"

_CREST_AUDIT_ACTIONS = (SET_TEAM_CREST, REMOVE_TEAM_CREST)


def crest_audit_action(before: str | None, after: str | None) -> str | None:
    """Action to record for a crest transition, ``None`` when nothing changed.

    A non-null ``after`` is a load or a replacement (``SET_TEAM_CREST``); a null
    ``after`` with an image before is the effective deletion
    (``REMOVE_TEAM_CREST``). Both null is a deletion without an image: the
    operation succeeds but leaves no audit entry.
    """

    if after is not None:
        return SET_TEAM_CREST
    if before is not None:
        return REMOVE_TEAM_CREST
    return None


def _crest_audit_payload(tournament_id: UUID | str) -> dict[str, str]:
    """Payload with the tournament identifier only, as strings."""

    return {"tournament_id": str(tournament_id)}


async def record_crest_audit(
    db: AsyncSession,
    *,
    organization_id: UUID | str,
    member_id: UUID | str,
    tournament_id: UUID | str,
    team_id: UUID | str,
    action: str,
) -> None:
    """Insert one crest audit entry inside the caller's transaction.

    ``member_id`` is the organisation member (``organization_users.id``) that
    performs the action. Only the two catalog actions are accepted: a non
    effective operation must not reach this function, and passing ``None``
    raises instead of writing a misleading entry.
    """

    if action not in _CREST_AUDIT_ACTIONS:
        raise ValueError(f"Acción de auditoría de escudo no admitida: {action!r}")

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
            "entity_type": TEAM_ENTITY_TYPE,
            "entity_id": str(team_id),
            "action": action,
            "payload": json.dumps(_crest_audit_payload(tournament_id)),
            "member_id": str(member_id),
        },
    )
