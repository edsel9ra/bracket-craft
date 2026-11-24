"""Entrega de avisos desde el worker (spec 046, RF-007, RF-011, RF-012)."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sqlalchemy import text

from app.modules.notifications.catalog import email_message


async def deliver_inbox(db, event: Mapping[str, Any]) -> None:
    """Revalida y entrega en la bandeja; sin derecho queda ``withheld`` sin reintento."""

    async with db.begin():
        await db.execute(
            text("SELECT deliver_notification_inbox(:id)"), {"id": str(event["id"])}
        )


async def deliver_email(
    db,
    event: Mapping[str, Any],
    *,
    base_url: str,
    send: Callable[[str, str, str], Awaitable[None]],
) -> bool:
    """Envía el correo de un destinatario; un fallo del SMTP se propaga para reintentar."""

    async with db.begin():
        payload = (
            await db.execute(
                text("SELECT notification_email_payload(:id)"), {"id": str(event["id"])}
            )
        ).scalar_one()
    if payload is None:
        return False
    subject, body = email_message(payload, base_url)
    await send(payload["recipient"], subject, body)
    async with db.begin():
        await db.execute(
            text("SELECT record_notification_email_delivery(:id)"),
            {"id": str(event["id"])},
        )
    return True
