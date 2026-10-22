"""Ciclo de vida efectivo de una invitación (R22/RF-005).

El estado almacenado no se reescribe al leer: el vencimiento se calcula con el
``now`` que recibe el llamador, de modo que la función es pura y determinista.
La materialización del vencimiento ocurre solo al **crear**, al **reenviar** y
al **reabrir**; **revocar** evalúa el estado efectivo sin escribir y la lectura
nunca modifica la fila ni su ``updated_at``.

Las guardas ``reopen_conflict`` y ``resend_conflict`` deciden el 409 antes de
cualquier escritura. No leen el reloj ni la base de datos: reciben el estado
almacenado y, en la reapertura, si el correo tiene otra pendiente vigente.
"""

from datetime import datetime, timezone

from app.modules.invitations.errors import (
    INVITATION_ALREADY_ACCEPTED,
    INVITATION_NOT_REVOKED,
    INVITATION_OTHER_PENDING,
    INVITATION_REVOKED_RESEND,
)


PENDING_INVITATION_STATUS = "pending"
EXPIRED_INVITATION_STATUS = "expired"
REVOKED_INVITATION_STATUS = "revoked"
ACCEPTED_INVITATION_STATUS = "accepted"


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


def reopen_conflict(stored_status: str, has_live_pending: bool) -> str | None:
    """Reason to reject reopening, or ``None`` when the operation may proceed.

    Only a stored ``revoked`` invitation is reopened. Another *live* pending
    invitation for the same e-mail blocks the operation; an expired stored
    pending does not, because it is materialised first in the same transaction.
    """

    if stored_status != REVOKED_INVITATION_STATUS:
        return INVITATION_NOT_REVOKED
    if has_live_pending:
        return INVITATION_OTHER_PENDING
    return None


def resend_conflict(stored_status: str) -> str | None:
    """Reason to reject a resend, or ``None`` when it is allowed.

    An accepted invitation cannot be resent and a revoked one must be reopened;
    pending and stored ``expired`` invitations keep the resend contract.
    """

    if stored_status == ACCEPTED_INVITATION_STATUS:
        return INVITATION_ALREADY_ACCEPTED
    if stored_status == REVOKED_INVITATION_STATUS:
        return INVITATION_REVOKED_RESEND
    return None
