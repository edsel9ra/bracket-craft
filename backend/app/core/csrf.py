import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_HEADER_NAME = "X-CSRF-Token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def request_origin(headers) -> str | None:
    """Origen declarado explícitamente por ``Origin`` (``None`` si falta)."""

    return headers.get("origin")


def referer_origin(headers) -> str | None:
    """Origen derivado de ``Referer``.

    Devuelve ``None`` cuando la cabecera falta y la cadena vacía cuando existe
    pero no es una URL absoluta: un ``Referer`` no parseable nunca se admite.
    """

    referer = headers.get("referer")
    if referer is None:
        return None
    parsed = urlsplit(referer)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def is_allowed_origin(origin: str | None, allowed_origins: set[str] | frozenset[str]) -> bool:
    """Sin origen declarado la petición se admite; con origen, debe estar permitido."""

    return origin is None or origin in allowed_origins


def validate_request_origin(
    request: Request,
    allowed_origins: set[str] | frozenset[str],
) -> None:
    """Valida el origen de toda escritura, con o sin credenciales de sesión.

    Sin ``Origin`` ni ``Referer`` la petición se admite (renderizado en servidor
    y clientes externos). Si cualquiera de las dos cabeceras está presente debe
    identificar un origen permitido: un ``Referer`` no permitido rechaza aunque
    ``Origin`` lo esté, y un ``Referer`` no parseable se considera no permitido.
    """

    if request.method.upper() in SAFE_METHODS:
        return

    origin_allowed = is_allowed_origin(request_origin(request.headers), allowed_origins)
    referer_allowed = is_allowed_origin(referer_origin(request.headers), allowed_origins)
    if not (origin_allowed and referer_allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origen no permitido",
        )


def validate_csrf_token(request: Request, csrf_cookie_name: str) -> None:
    """Exige el token de doble envío en escrituras con credenciales."""

    if request.method.upper() in SAFE_METHODS:
        return

    header_token = request.headers.get(CSRF_HEADER_NAME)
    cookie_token = request.cookies.get(csrf_cookie_name)
    if not header_token or not cookie_token or not secrets.compare_digest(header_token, cookie_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF inválido",
        )


def validate_csrf_request(
    request: Request,
    allowed_origins: set[str] | frozenset[str],
    csrf_cookie_name: str,
) -> None:
    """Composición completa: origen permitido y token de doble envío."""

    validate_request_origin(request, allowed_origins)
    validate_csrf_token(request, csrf_cookie_name)
