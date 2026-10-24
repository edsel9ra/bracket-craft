"""Piezas puras de la identidad de Google: destino, nombre y prueba de identidad.

El módulo aplica RF-5/RF-8/RNF-4 (``parse_identity_claims``), RF-9
(``validate_return_destination``) y RF-12 (``sanitize_display_name``). No lee
reloj, entorno, red ni base de datos, no escribe estado global mutable y
``validate_return_destination``/``sanitize_display_name`` no lanzan: cada una
devuelve un valor seguro y el llamador aplica su política (destino por defecto,
nombre de reserva) cuando recibe ``None`` o una cadena vacía.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote

import jwt

# Límites del plan §5.1. ``users.full_name`` es VARCHAR(100) y RF-9 fija 512
# caracteres para el destino de retorno.
MAX_DISPLAY_NAME_LENGTH = 100
MAX_RETURN_DESTINATION_LENGTH = 512

# RNF-4: como máximo 8 KiB de respuesta del proveedor.
MAX_IDENTITY_RESPONSE_BYTES = 8 * 1024

# Columnas del esquema: ``auth_identities.provider_subject`` y ``users.email``.
MAX_SUBJECT_LENGTH = 255
MAX_EMAIL_LENGTH = 255

# RF-12: nombre neutro estable cuando ni el proveedor ni el correo aportan uno.
DEFAULT_DISPLAY_NAME = "Cuenta de Bracket Craft"

# Emisores admitidos de Google (RF-5, plan §5.1). El valor sin esquema aparece
# en tokens antiguos.
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})

# Esquema absoluto al inicio de la ruta (tras las barras iniciales): «http:»,
# «javascript:», «data:», etc.
_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# D-9: la firma del ``id_token`` no se verifica porque el token llega del
# endpoint de token de Google por TLS, autenticado con el secreto del cliente.
# Las comprobaciones temporales de PyJWT se desactivan en la llamada para que la
# vigencia la decida solo el ``now`` inyectado (RF-5); así no queda ningún
# estado global mutable en el módulo.


class GoogleIdentityInvalid(ValueError):
    """La respuesta del canje no contiene una prueba de identidad válida."""


@dataclass(frozen=True)
class GoogleIdentity:
    """Solo los campos admitidos (RNF-4); el resto se descarta."""

    subject: str
    email: str
    email_verified: bool
    name: str | None



def _contains_control_characters(value: str) -> bool:
    """Indica si ``value`` incluye algún carácter de la categoría Unicode Cc."""

    return any(unicodedata.category(character) == "Cc" for character in value)


def _is_safe_internal_path(value: str) -> bool:
    """Comprueba la forma de una ruta relativa interna, sin decodificar."""

    if not value.startswith("/"):
        return False
    if value.startswith("//"):
        return False
    if "\\" in value:
        return False
    if _contains_control_characters(value):
        return False

    path = value.split("?", 1)[0].split("#", 1)[0]
    if _SCHEME_PATTERN.match(path.lstrip("/")):
        return False

    return True


def validate_return_destination(
    value: object,
    *,
    max_length: int = MAX_RETURN_DESTINATION_LENGTH,
) -> str | None:
    """Devuelve ``value`` si es una ruta interna segura; si no, ``None``.

    Normalización (RF-9): no se recorta, no se decodifica y no se reescribe
    nada; una ruta válida se devuelve exactamente como llegó, porque el
    llamador la guarda y la usa como ruta del frontend. Solo se valida.

    Se rechaza (``None``) cuando el valor:

    * no es ``str`` (``None``, números, bytes, objetos…) o es demasiado largo
      (``len(value) > max_length``, 512 por defecto);
    * no empieza por ``/`` (una ruta relativa sin barra inicial no se puede
      distinguir de un host relativo al esquema);
    * empieza por ``//`` (host absoluto);
    * contiene ``\\`` (algunos navegadores lo tratan como ``/``);
    * contiene caracteres de control (categoría Unicode Cc, incluidos los
      saltos de línea que permitirían inyectar cabeceras);
    * tras las barras iniciales empieza por un esquema (``http:``,
      ``javascript:``, ``data:``…);
    * al decodificar **una sola vez** el porcentaje deja de cumplir cualquiera
      de las reglas anteriores (``/%2F%2Fhost``, ``/%5C…``, ``%0A`` o un
      esquema codificado).

    Un valor vacío o solo con espacios no empieza por ``/`` y también se
    rechaza. No se lanza ninguna excepción: el llamador aplica el destino por
    defecto cuando recibe ``None``.
    """

    if not isinstance(value, str):
        return None
    if len(value) > max_length:
        return None
    if not _is_safe_internal_path(value):
        return None

    decoded = unquote(value)
    if decoded != value and not _is_safe_internal_path(decoded):
        return None

    return value


def sanitize_display_name(name: object, email: object) -> str:
    """Devuelve un nombre para mostrar no vacío y de hasta 100 caracteres.

    Regla de RF-12, aplicada en este orden:

    1. Si ``name`` es una cadena, se recorta (``strip``) y se limita a
       ``MAX_DISPLAY_NAME_LENGTH`` (100) caracteres. Primero se recorta y
       después se acota, para que los espacios de los extremos no consuman el
       límite.
    2. Si el resultado queda vacío (``None``, cadena vacía, solo espacios o un
       valor que no es ``str``), se usa la parte del correo anterior a ``@``,
       también recortada y limitada a 100 caracteres. Sin ``@`` se usa el correo
       completo como parte local.
    3. Si tampoco queda nada (correo vacío, sin parte local o que no es
       ``str``), se devuelve ``DEFAULT_DISPLAY_NAME``.

    Nunca lanza: el alta de una cuenta no puede fallar por el nombre.
    """

    candidate = name.strip() if isinstance(name, str) else ""
    candidate = candidate[:MAX_DISPLAY_NAME_LENGTH]
    if candidate:
        return candidate

    local_part = email.partition("@")[0].strip() if isinstance(email, str) else ""
    local_part = local_part[:MAX_DISPLAY_NAME_LENGTH]
    if local_part:
        return local_part

    return DEFAULT_DISPLAY_NAME


def _now_timestamp(now: datetime) -> float:
    """Convierte el instante inyectado en segundos; un ``datetime`` sin zona es UTC."""

    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.timestamp()


def _response_body(raw: object, *, max_bytes: int) -> dict:
    """Valida tamaño, codificación y JSON de la respuesta del canje."""

    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > max_bytes:
            raise GoogleIdentityInvalid(
                "La respuesta del proveedor supera el tamaño máximo permitido."
            )
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GoogleIdentityInvalid(
                "La respuesta del proveedor no tiene una codificación válida."
            ) from exc
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > max_bytes:
            raise GoogleIdentityInvalid(
                "La respuesta del proveedor supera el tamaño máximo permitido."
            )
        text = raw
    else:
        raise GoogleIdentityInvalid(
            "La respuesta del proveedor no tiene un tipo válido."
        )

    try:
        body = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GoogleIdentityInvalid(
            "La respuesta del proveedor no es un JSON válido."
        ) from exc

    if not isinstance(body, dict):
        raise GoogleIdentityInvalid(
            "La respuesta del proveedor no es un objeto JSON."
        )

    return body


def parse_identity_claims(
    raw: object,
    *,
    client_id: str,
    now: datetime,
    issuers: frozenset[str] = GOOGLE_ISSUERS,
    max_bytes: int = MAX_IDENTITY_RESPONSE_BYTES,
) -> GoogleIdentity:
    """Extrae la prueba de identidad de la respuesta del canje (RF-5/RF-8/RNF-4).

    ``raw`` es el cuerpo devuelto por el endpoint de token (``bytes`` o ``str``)
    y ``now`` el instante del intento, inyectado: la función no lee el reloj.
    Orden de las comprobaciones:

    1. Tamaño: se mide **antes** de decodificar; más de ``max_bytes`` (8 KiB)
       se rechaza.
    2. Codificación UTF-8 y JSON: la respuesta debe ser un objeto JSON.
    3. ``id_token``: cadena no vacía. Su firma **no** se verifica (D-9: llega
       del endpoint de token por TLS, autenticado con el secreto del cliente);
       solo se lee el segmento central.
    4. ``iss`` debe ser una cadena y pertenecer a ``issuers`` (por defecto
       ``GOOGLE_ISSUERS``: ``https://accounts.google.com`` y
       ``accounts.google.com``).
    5. ``aud`` debe ser exactamente ``client_id``. Un arreglo de audiencias se
       rechaza en vez de interpretarse.
    6. ``exp`` debe ser numérico, finito y estrictamente futuro respecto de
       ``now``. Un booleano, una cadena o un valor ausente no valen; ``exp``
       igual a ``now`` ya está caducado.
    7. ``sub`` debe ser una cadena no vacía de hasta 255 caracteres.
    8. ``email`` debe ser una cadena no vacía de hasta 255 caracteres y
       ``email_verified`` debe ser exactamente ``True`` (RF-8); ``"true"`` o
       ``1`` no cuentan.
    9. ``name`` es opcional: se conserva solo si es una cadena; cualquier otro
       tipo se descarta.

    Cualquier otro campo se descarta y nunca se copia al resultado ni al
    mensaje de error. Cualquier incumplimiento lanza ``GoogleIdentityInvalid``
    sin incluir valores del proveedor (RNF-5).
    """

    body = _response_body(raw, max_bytes=max_bytes)

    token = body.get("id_token")
    if not isinstance(token, str) or not token:
        raise GoogleIdentityInvalid(
            "La respuesta del proveedor no contiene un id_token válido."
        )

    try:
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_aud": False,
                "verify_iss": False,
            },
            algorithms=["RS256"],
        )
    except jwt.InvalidTokenError as exc:
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        ) from exc

    if not isinstance(claims, dict):
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )

    issuer = claims.get("iss")
    if not isinstance(issuer, str) or issuer not in issuers:
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )

    if not isinstance(client_id, str) or not client_id or claims.get("aud") != client_id:
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )

    expiry = claims.get("exp")
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )
    if not math.isfinite(expiry) or expiry <= _now_timestamp(now):
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )

    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or len(subject) > MAX_SUBJECT_LENGTH
    ):
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )

    email = claims.get("email")
    if (
        not isinstance(email, str)
        or not email.strip()
        or len(email) > MAX_EMAIL_LENGTH
        or claims.get("email_verified") is not True
    ):
        raise GoogleIdentityInvalid(
            "La prueba de identidad del proveedor no es válida."
        )

    name = claims.get("name")
    if not isinstance(name, str):
        name = None

    return GoogleIdentity(
        subject=subject,
        email=email,
        email_verified=True,
        name=name,
    )
