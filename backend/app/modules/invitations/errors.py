"""Contrato de error estable del ciclo de vida de invitaciones (RF-002/RF-003).

Los 409 de invitación conservan el ``detail`` de siempre —una cadena que el
cliente ya muestra como respaldo— y añaden un ``code`` estable y aditivo que el
frontend traduce al idioma activo. El manejador único vive en ``app/main.py``:
Starlette resuelve por MRO, así que las rutas solo lanzan la excepción.
"""

from fastapi import HTTPException, status

INVITATION_NOT_REVOKED = "INVITATION_NOT_REVOKED"
INVITATION_OTHER_PENDING = "INVITATION_OTHER_PENDING"
INVITATION_ALREADY_ACCEPTED = "INVITATION_ALREADY_ACCEPTED"
INVITATION_REVOKED_RESEND = "INVITATION_REVOKED_RESEND"

# Texto por defecto de cada motivo. Es el ``detail`` de siempre y no se traduce
# en el servidor: el cliente usa ``code`` para mostrar el mensaje del idioma.
INVITATION_CONFLICT_DETAILS: dict[str, str] = {
    INVITATION_NOT_REVOKED: "Solo se puede reabrir una invitación revocada",
    INVITATION_OTHER_PENDING: "Ya existe una invitación pendiente para ese correo",
    INVITATION_ALREADY_ACCEPTED: "Una invitación aceptada no se puede reenviar",
    INVITATION_REVOKED_RESEND: "La invitación está revocada y debe reabrirse",
}

_FALLBACK_DETAIL = "Conflicto de invitación"


class InvitationConflict(HTTPException):
    """409 de dominio con un motivo estable en ``code``."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        if detail is None:
            detail = INVITATION_CONFLICT_DETAILS.get(code, _FALLBACK_DETAIL)
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
        self.code = code


def conflict_body(exc: InvitationConflict) -> dict[str, str]:
    """Cuerpo del 409: ``detail`` sigue siendo una cadena y ``code`` se añade."""

    return {"detail": str(exc.detail), "code": exc.code}
