from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db


password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def hash_password(value: str) -> str:
    return password_hash.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    return password_hash.verify(value, hashed)


def create_access_token(user_id: UUID, session_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "jti": str(session_id),
        "typ": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "exp": expires,
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token_claims(credentials_or_token: HTTPAuthorizationCredentials | str | None) -> dict[str, Any]:
    if not credentials_or_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticación requerida")

    settings = get_settings()
    token = (
        credentials_or_token.credentials
        if isinstance(credentials_or_token, HTTPAuthorizationCredentials)
        else credentials_or_token
    )
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        if payload.get("typ") != "access":
            raise ValueError("Tipo de token inválido")
        UUID(payload["sub"])
        UUID(payload["jti"])
        return payload
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido") from exc


def decode_access_token(credentials_or_token: HTTPAuthorizationCredentials | str | None) -> UUID:
    return UUID(decode_access_token_claims(credentials_or_token)["sub"])


async def create_user_session(db: AsyncSession, user_id: UUID) -> str:
    session_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=get_settings().jwt_expire_minutes)
    await db.execute(
        text("""
            INSERT INTO user_sessions (id, user_id, expires_at)
            VALUES (:id, :user_id, :expires_at)
        """),
        {"id": str(session_id), "user_id": str(user_id), "expires_at": expires_at},
    )
    return create_access_token(user_id, session_id)


def set_auth_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=get_settings().auth_cookie_name, path="/")


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    settings = get_settings()
    raw_token = credentials.credentials if credentials else request.cookies.get(settings.auth_cookie_name)
    claims = decode_access_token_claims(raw_token)
    user_id = UUID(claims["sub"])
    session_id = UUID(claims["jti"])

    async with db.begin():
        result = await db.execute(
            text("""
                SELECT u.is_active, s.revoked_at, s.expires_at
                FROM users u
                JOIN user_sessions s ON s.user_id = u.id
                WHERE u.id = :user_id
                  AND s.id = :session_id
                  AND s.expires_at > CURRENT_TIMESTAMP
            """),
            {"user_id": str(user_id), "session_id": str(session_id)},
        )
        session = result.mappings().one_or_none()

    if session is None or not session["is_active"] or session["revoked_at"] is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión no válida")
    return user_id
