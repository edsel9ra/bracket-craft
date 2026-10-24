"""Error del alta de organización con código estable (RF-24).

Un identificador ocupado responde **409** con ``detail`` de cadena y el código
aditivo ``ORGANIZATION_SLUG_TAKEN``; el mensaje no revela la organización
existente. El manejador único vive en ``app/main.py`` (Starlette resuelve por
MRO); el router solo lanza la excepción.
"""

from __future__ import annotations

from fastapi import HTTPException, status

ORGANIZATION_SLUG_TAKEN = "ORGANIZATION_SLUG_TAKEN"

ORGANIZATION_SLUG_TAKEN_DETAIL = "El identificador de la organización ya está en uso"


class OrganizationSlugTaken(HTTPException):
    """409 de dominio con un motivo estable en ``code``."""

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or ORGANIZATION_SLUG_TAKEN_DETAIL,
        )
        self.code = ORGANIZATION_SLUG_TAKEN


def slug_taken_body(exc: OrganizationSlugTaken) -> dict[str, str]:
    """Cuerpo del 409: ``detail`` sigue siendo una cadena y ``code`` se añade."""

    return {"detail": str(exc.detail), "code": exc.code}
