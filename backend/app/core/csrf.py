import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_HEADER_NAME = "X-CSRF-Token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _origin_from_referer(referer: str | None) -> str | None:
    if not referer:
        return None
    parsed = urlsplit(referer)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_csrf_request(
    request: Request,
    allowed_origins: set[str] | frozenset[str],
    csrf_cookie_name: str,
) -> None:
    """Validate browser origins and the double-submit token.

    Same-origin server-side requests do not always carry Origin or Referer. They
    remain supported, while browser requests with either header must identify a
    configured frontend origin. Unsafe requests must carry matching token copies.
    """

    if request.method.upper() in SAFE_METHODS:
        return

    origin = request.headers.get("origin") or _origin_from_referer(request.headers.get("referer"))
    if origin is not None and origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origen no permitido",
        )

    header_token = request.headers.get(CSRF_HEADER_NAME)
    cookie_token = request.cookies.get(csrf_cookie_name)
    if not header_token or not cookie_token or not secrets.compare_digest(header_token, cookie_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF inválido",
        )
