"""Errores del flujo de identidad de Google con código estable (RF-31, RNF-9).

El cliente traduce ``code`` y no depende del texto; ``detail`` sigue siendo una
cadena para los clientes que solo leen el mensaje. El manejador único vive en
``app/main.py``: Starlette resuelve por MRO y respeta el estado HTTP de la
excepción, así que los endpoints solo lanzan ``GoogleAuthError``.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException

GOOGLE_UNAVAILABLE = "GOOGLE_UNAVAILABLE"
GOOGLE_CANCELLED = "GOOGLE_CANCELLED"
GOOGLE_STATE_INVALID = "GOOGLE_STATE_INVALID"
GOOGLE_IDENTITY_INVALID = "GOOGLE_IDENTITY_INVALID"
GOOGLE_ALREADY_LINKED = "GOOGLE_ALREADY_LINKED"
RATE_LIMITED = "RATE_LIMITED"

#: Mensajes por defecto: genéricos, sin datos de la cuenta ni del proveedor.
_DETAILS = {
    GOOGLE_UNAVAILABLE: "El acceso con Google no está disponible",
    GOOGLE_CANCELLED: "El acceso con Google se canceló",
    GOOGLE_STATE_INVALID: "El intento de acceso con Google no es válido o caducó",
    GOOGLE_IDENTITY_INVALID: "La prueba de identidad de Google no es válida",
    GOOGLE_ALREADY_LINKED: "La cuenta ya tiene una identidad de Google vinculada",
    RATE_LIMITED: "Demasiadas solicitudes. Inténtalo de nuevo más tarde.",
}

_FALLBACK_DETAIL = "No se pudo completar el acceso con Google"


class GoogleAuthError(HTTPException):
    """Error de dominio del flujo de Google con un ``code`` aditivo.

    ``status_code`` lo elige el punto que lanza la excepción (503, 409, 429…);
    el manejador global solo lo respeta. ``headers`` permite conservar, por
    ejemplo, ``Retry-After`` en el 429.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        super().__init__(
            status_code=status_code,
            detail=detail or _DETAILS.get(code, _FALLBACK_DETAIL),
            headers=dict(headers) if headers else None,
        )


def google_error_body(exc: GoogleAuthError) -> dict[str, str]:
    """Cuerpo del error: ``detail`` sigue siendo una cadena y ``code`` se añade."""

    return {"detail": str(exc.detail), "code": exc.code}
