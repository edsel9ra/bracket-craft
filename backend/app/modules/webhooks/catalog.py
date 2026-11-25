"""Catálogo puro de webhooks (spec 047): URL, secreto, cuerpo y firma."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from app.modules.notifications.catalog import NOTIFICATION_TYPES

EVENT_TYPES = tuple(NOTIFICATION_TYPES)
TEST_TYPE = "webhook_test"
MAX_WEBHOOKS = 10
MAX_URL_LENGTH = 2048
MAX_ATTEMPTS = 6
RETRY_DELAYS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=2),
)
REQUEST_TIMEOUT_SECONDS = 10.0
USER_AGENT = "BracketCraft-Webhooks/1"
SECRET_PREFIX = "whsec_"


def validate_url(url: str) -> str:
    """Devuelve la URL, con el esquema en minúsculas, si es HTTPS absoluta en ASCII, sin credenciales y acotada."""
    value = url.strip() if isinstance(url, str) else ""
    if not value or len(value) > MAX_URL_LENGTH:
        raise ValueError("WEBHOOK_URL_INVALID")
    if not value.isascii() or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value):
        raise ValueError("WEBHOOK_URL_INVALID")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError("WEBHOOK_URL_INVALID") from error
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("WEBHOOK_URL_INVALID")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("WEBHOOK_URL_INVALID")
    if port == 0:
        raise ValueError("WEBHOOK_URL_INVALID")
    return "https" + value[len(parts.scheme):]


def audit_host(url: str) -> str:
    """Dominio de la URL para auditoría: sin ruta, query, puerto ni credenciales."""
    return (urlsplit(url).hostname or "").lower()


def generate_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def serialize_body(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return "v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_headers(
    secret: str, *, event_type: str, delivery_id: str, timestamp: int, body: bytes
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-BracketCraft-Event": event_type,
        "X-BracketCraft-Delivery": delivery_id,
        "X-BracketCraft-Timestamp": str(timestamp),
        "X-BracketCraft-Signature": sign(secret, timestamp, body),
    }


def retry_delay(attempts: int) -> timedelta | None:
    """Espera antes del siguiente intento tras ``attempts`` fallidos; ``None`` si no queda ninguno."""
    if attempts < 1 or attempts >= MAX_ATTEMPTS:
        return None
    return RETRY_DELAYS[attempts - 1]
