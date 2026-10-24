"""Contrato de error estable de la operación del partido (P5, RF-032).

La resolución no habilitada por la configuración efectiva de la fase se rechaza
igual al crear un segmento, al interrumpirlo y al cerrar el acta: **409** con
un ``detail`` común —una cadena que el cliente ya muestra como respaldo— y un
``code`` estable y aditivo. El manejador único vive en ``app/main.py``:
Starlette resuelve por MRO, así que las rutas solo lanzan la excepción.
"""

from fastapi import HTTPException, status

RESOLUTION_NOT_ENABLED = "RESOLUTION_NOT_ENABLED"

# Texto único de los tres puntos. No nombra la resolución para que el mensaje
# sea el mismo en todos los casos ni se traduce en el servidor: el cliente usa
# ``code`` para mostrar el mensaje del idioma activo.
RESOLUTION_NOT_ENABLED_DETAIL = (
    "La resolución no está habilitada por la configuración de la fase"
)


class ResolutionNotEnabled(HTTPException):
    """409 de dominio con un motivo estable en ``code``."""

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or RESOLUTION_NOT_ENABLED_DETAIL,
        )
        self.code = RESOLUTION_NOT_ENABLED


def resolution_not_enabled_body(exc: ResolutionNotEnabled) -> dict[str, str]:
    """Cuerpo del 409: ``detail`` sigue siendo una cadena y ``code`` se añade."""

    return {"detail": str(exc.detail), "code": exc.code}
