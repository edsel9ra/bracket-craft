"""Stable error catalog of team crests (RF-57).

The eight codes of the specification are closed. Each one keeps a string
``detail`` —the Spanish fallback a client shows when it ignores ``code``— and
adds the stable ``code`` the frontend translates to the active language. No
detail, no code and no log line ever carries the internal object reference, the
file name chosen by the person, the size or any personal data.

The single handler lives in ``app/main.py`` (task T10): Starlette resolves the
exception by MRO, so the routes only raise ``CrestError``.
"""

from fastapi import HTTPException, status

CREST_FILE_EMPTY = "CREST_FILE_EMPTY"
CREST_FORMAT_UNSUPPORTED = "CREST_FORMAT_UNSUPPORTED"
CREST_ANIMATION_UNSUPPORTED = "CREST_ANIMATION_UNSUPPORTED"
CREST_TOO_LARGE = "CREST_TOO_LARGE"
CREST_NOT_FOUND = "CREST_NOT_FOUND"
CREST_FORBIDDEN = "CREST_FORBIDDEN"
CREST_STORAGE_UNAVAILABLE = "CREST_STORAGE_UNAVAILABLE"
CREST_UPLOAD_FAILED = "CREST_UPLOAD_FAILED"

#: HTTP status of every catalog code. The constructor reads it from here so the
#: catalog cannot drift between the constant and the exception.
CREST_ERROR_STATUS: dict[str, int] = {
    CREST_FILE_EMPTY: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CREST_FORMAT_UNSUPPORTED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CREST_ANIMATION_UNSUPPORTED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CREST_TOO_LARGE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    CREST_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    CREST_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    CREST_STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    CREST_UPLOAD_FAILED: status.HTTP_500_INTERNAL_SERVER_ERROR,
}

#: ``detail`` of every code: a string, never a translated message. The client
#: uses ``code`` for the active language.
CREST_ERROR_DETAILS: dict[str, str] = {
    CREST_FILE_EMPTY: "El archivo está vacío",
    CREST_FORMAT_UNSUPPORTED: "El escudo debe ser una imagen JPG, PNG o WEBP",
    CREST_ANIMATION_UNSUPPORTED: "El escudo no puede ser una imagen animada",
    CREST_TOO_LARGE: "El escudo supera el tamaño máximo permitido",
    CREST_NOT_FOUND: "El equipo no fue encontrado",
    CREST_FORBIDDEN: "No tienes permiso para gestionar el escudo de este equipo",
    CREST_STORAGE_UNAVAILABLE: "El almacenamiento de imágenes no está disponible",
    CREST_UPLOAD_FAILED: "No se pudo completar la operación del escudo",
}

#: Status and text of an unclassified failure: the operation answers 500 with
#: ``CREST_UPLOAD_FAILED`` and never leaks the internal cause.
_FALLBACK_DETAIL = CREST_ERROR_DETAILS[CREST_UPLOAD_FAILED]


class CrestError(HTTPException):
    """Domain error with a stable ``code`` next to a string ``detail``."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        status_code = CREST_ERROR_STATUS.get(
            code, status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        if detail is None:
            detail = CREST_ERROR_DETAILS.get(code, _FALLBACK_DETAIL)
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def crest_error_body(exc: CrestError) -> dict[str, str]:
    """Response body: ``detail`` stays a string and ``code`` is additive."""

    return {"detail": str(exc.detail), "code": exc.code}
