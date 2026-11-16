"""Funciones puras de la recuperación de contraseña (spec 039)."""

import hashlib
import secrets
from datetime import datetime, timedelta

RESET_LINK_LIFETIME = timedelta(minutes=30)


def new_reset_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reset_expires_at(now: datetime) -> datetime:
    return now + RESET_LINK_LIFETIME


def reset_url(frontend_base_url: str, token: str) -> str:
    return f"{frontend_base_url.rstrip('/')}/password/reset#{token}"


def job_should_expire(created_at: datetime, now: datetime) -> bool:
    return now - created_at >= RESET_LINK_LIFETIME
