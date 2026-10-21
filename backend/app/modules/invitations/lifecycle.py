"""Ciclo de vida efectivo de una invitación (R22/RF-005).

El estado almacenado no se reescribe al leer: el vencimiento se calcula con el
``now`` que recibe el llamador, de modo que la función es pura y determinista.
La materialización del vencimiento ocurre solo al **crear** y al **reenviar**;
**revocar** evalúa el estado efectivo sin escribir y la lectura nunca modifica
la fila ni su ``updated_at``.
"""

from datetime import datetime, timezone


PENDING_INVITATION_STATUS = "pending"
EXPIRED_INVITATION_STATUS = "expired"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def effective_invitation_status(
    stored_status: str,
    expires_at: datetime,
    now: datetime,
) -> str:
    """Return the effective status without touching the stored one.

    A ``pending`` invitation whose ``expires_at`` already passed is presented as
    ``expired``; every other state is returned unchanged.
    """

    if (
        stored_status == PENDING_INVITATION_STATUS
        and _as_utc(expires_at) <= _as_utc(now)
    ):
        return EXPIRED_INVITATION_STATUS
    return stored_status
