"""Registro de avisos en la transacción del hecho (spec 046, RF-002)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from app.modules.notifications.catalog import NOTIFICATION_TYPES

_RECORD = text(
    "SELECT record_notification(:notification_type, CAST(:tournament_id AS uuid), "
    "CAST(:match_id AS uuid), CAST(:suspension_id AS uuid), CAST(:match_count AS integer))"
)


def _optional(value: UUID | str | None) -> str | None:
    return None if value is None else str(value)


async def record_notification(
    db,
    notification_type: str,
    *,
    tournament_id: UUID | str,
    match_id: UUID | str | None = None,
    suspension_id: UUID | str | None = None,
    match_count: int | None = None,
) -> UUID | None:
    if notification_type not in NOTIFICATION_TYPES:
        raise ValueError("NOTIFICATION_TYPE_UNKNOWN")
    if notification_type == "match_scheduled" and not match_count:
        return None
    result = await db.execute(
        _RECORD,
        {
            "notification_type": notification_type,
            "tournament_id": str(tournament_id),
            "match_id": _optional(match_id),
            "suspension_id": _optional(suspension_id),
            "match_count": match_count,
        },
    )
    return result.scalar_one()
