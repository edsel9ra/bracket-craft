"""Cliente del proveedor de Google: URL de autorización y canje (RF-2, RF-5, RNF-2, RNF-4).

Este es el borde de red del flujo de identidad. La URL de autorización es lo
único que llega al navegador y no lleva secretos ni tokens; el código se canjea
en el servidor con un timeout de 5 s por llamada, el presupuesto de 10 s del
intento y un tope de 8 KiB, sin reintentos (D-12). El cuerpo devuelto se entrega
tal cual a ``google_claims.parse_identity_claims``, que es quien valida la
prueba de identidad.

La firma del ``id_token`` no se verifica aquí (D-9): llega del endpoint de token
por TLS, autenticado con el secreto del cliente.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx

from app.modules.identity.google_claims import (
    MAX_IDENTITY_RESPONSE_BYTES,
    GoogleIdentityInvalid,
)

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones
    from app.core.config import Settings

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# RF-2: solo los datos mínimos de identidad.
SCOPE = "openid email profile"

# RNF-2: 5 s por llamada y 10 s para todo el intento.
PROVIDER_TIMEOUT_SECONDS = 5.0
ATTEMPT_BUDGET_SECONDS = 10.0

# Se pide un byte de más para detectar el exceso antes de entregar el cuerpo al
# analizador (RNF-4).
MAX_READ_BYTES = MAX_IDENTITY_RESPONSE_BYTES + 1

__all__ = [
    "ATTEMPT_BUDGET_SECONDS",
    "AUTHORIZATION_ENDPOINT",
    "GoogleIdentityInvalid",
    "GoogleUnavailable",
    "MAX_IDENTITY_RESPONSE_BYTES",
    "PROVIDER_TIMEOUT_SECONDS",
    "SCOPE",
    "TOKEN_ENDPOINT",
    "authorization_url",
    "exchange_code",
    "remaining_seconds",
]


class GoogleUnavailable(RuntimeError):
    """El proveedor no está configurado, no responde o responde con un fallo."""


def _configuration(
    settings: Settings, *, require_secret: bool
) -> tuple[str, str | None, str]:
    """Devuelve ``(client_id, client_secret, redirect_uri)`` o falla cerrado.

    La validación definitiva vive en la configuración (T6: ``GOOGLE_REDIRECT_URI``
    obligatoria cuando Google está habilitado); aquí solo se evita construir una
    dirección o un canje incompletos.
    """

    client_id = getattr(settings, "google_client_id", None)
    redirect_uri = getattr(settings, "google_redirect_uri", None)
    client_secret = getattr(settings, "google_client_secret", None)

    if not isinstance(client_id, str) or not client_id.strip():
        raise GoogleUnavailable("El proveedor de identidad no está configurado.")
    if not isinstance(redirect_uri, str) or not redirect_uri.strip():
        raise GoogleUnavailable("El proveedor de identidad no está configurado.")
    if require_secret and (not isinstance(client_secret, str) or not client_secret):
        raise GoogleUnavailable("El proveedor de identidad no está configurado.")

    return client_id, client_secret if isinstance(client_secret, str) else None, redirect_uri


def authorization_url(settings: Settings, *, state: str) -> str:
    """Dirección de autorización del proveedor para el estado indicado.

    Lleva exactamente ``client_id``, ``redirect_uri`` (la configurada, sin
    derivarla de la petición: D-14), ``response_type=code``, ``scope``
    (``openid email profile``) y ``state``. Nunca incluye el secreto del cliente,
    un token ni el destino de retorno (ese vive solo en Redis, RF-9).
    """

    client_id, _client_secret, redirect_uri = _configuration(
        settings, require_secret=False
    )

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
        }
    )
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


def remaining_seconds(deadline: float, now: float) -> float:
    """Segundos que quedan hasta ``deadline``; nunca negativo. No lee el reloj."""

    return max(0.0, deadline - now)


async def exchange_code(
    settings: Settings,
    *,
    code: str,
    deadline: float,
    client: httpx.AsyncClient,
) -> bytes:
    """Canjea el código en el servidor y devuelve el cuerpo crudo del proveedor.

    * ``timeout`` = mínimo entre 5 s y el presupuesto restante del intento; sin
      presupuesto no se llama al proveedor.
    * Lee como máximo 8193 bytes con ``client.stream(...).aiter_bytes()`` y
      aborta en cuanto se supera el tope: el exceso es ``GoogleIdentityInvalid``
      (RNF-4, la misma clasificación que aplica el analizador).
    * ``5xx``, un estado inesperado (por ejemplo un redirect), un timeout o un
      error de red son ``GoogleUnavailable``; ``4xx`` (incluido ``invalid_grant``
      por un código reutilizado) es ``GoogleIdentityInvalid``.
    * No hay reintentos (D-12): el código de autorización es de un solo uso y un
      reintento solo añadiría latencia.
    * Los mensajes son genéricos: ni el código, ni el secreto, ni el cuerpo del
      proveedor aparecen en ellos (RNF-5).
    """

    client_id, client_secret, redirect_uri = _configuration(
        settings, require_secret=True
    )

    timeout = min(
        PROVIDER_TIMEOUT_SECONDS, remaining_seconds(deadline, time.monotonic())
    )
    if timeout <= 0:
        raise GoogleUnavailable("El proveedor de identidad no está disponible.")

    try:
        async with client.stream(
            "POST",
            TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            timeout=timeout,
        ) as response:
            if response.status_code >= 500:
                raise GoogleUnavailable(
                    "El proveedor de identidad no está disponible."
                )
            if response.status_code >= 400:
                raise GoogleIdentityInvalid(
                    "La prueba de identidad del proveedor no es válida."
                )
            if not 200 <= response.status_code < 300:
                raise GoogleUnavailable(
                    "El proveedor de identidad no está disponible."
                )

            buffer = bytearray()
            budget = MAX_READ_BYTES
            async for chunk in response.aiter_bytes():
                if len(chunk) >= budget:
                    buffer.extend(chunk[:budget])
                    raise GoogleIdentityInvalid(
                        "La prueba de identidad del proveedor no es válida."
                    )
                buffer.extend(chunk)
                budget -= len(chunk)

            return bytes(buffer)
    except httpx.HTTPError as exc:
        raise GoogleUnavailable(
            "El proveedor de identidad no está disponible."
        ) from exc
