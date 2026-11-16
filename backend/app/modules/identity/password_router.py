"""Recuperación y cambio de contraseña (spec 039).

La petición de recuperación solo encola el correo normalizado y responde 202
siempre igual (RF-001, RNF-001); el worker resuelve la cuenta. El token viaja
solo como SHA-256 y nunca aparece en logs, errores ni respuestas (RF-011).
"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import enforce_rate_limit
from app.core.security import (
    clear_auth_cookie,
    get_current_user_id,
    get_session_id,
    hash_password,
    verify_password,
)
from app.modules.identity.password_recovery import token_hash
from app.modules.identity.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    PasswordStatusResponse,
    ResetPasswordRequest,
)

PASSWORD_RESET_INVALID = "PASSWORD_RESET_INVALID"
PASSWORD_REUSED = "PASSWORD_REUSED"
CURRENT_PASSWORD_INVALID = "CURRENT_PASSWORD_INVALID"
PASSWORD_NOT_SET = "PASSWORD_NOT_SET"

router = APIRouter(prefix="/auth/password", tags=["identity"])


@router.post("/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    await enforce_rate_limit(
        request,
        "password-forgot",
        settings.auth_password_reset_rate_limit,
        3600,
        account_identifier=str(payload.email),
        max_body_bytes=settings.max_request_body_bytes,
    )
    async with db.begin():
        await db.execute(text("SELECT enqueue_password_reset_request(:email)"), {"email": str(payload.email)})
    return {}


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = get_settings()
    digest = token_hash(payload.token)
    await enforce_rate_limit(
        request,
        "password-reset",
        settings.auth_login_rate_limit,
        60,
        connection_identifier=digest,
        max_body_bytes=settings.max_request_body_bytes,
    )
    async with db.begin():
        target = (await db.execute(
            text("SELECT user_id, password_hash FROM password_reset_target(:token_hash)"),
            {"token_hash": digest},
        )).mappings().one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PASSWORD_RESET_INVALID)
    current_hash = target["password_hash"]
    if await asyncio.to_thread(verify_password, payload.new_password, current_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PASSWORD_REUSED)
    new_hash = await asyncio.to_thread(hash_password, payload.new_password)
    async with db.begin():
        user_id = (await db.execute(
            text("SELECT complete_password_reset(:token_hash, :current_hash, :new_hash)"),
            {"token_hash": digest, "current_hash": current_hash, "new_hash": new_hash},
        )).scalar_one()
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PASSWORD_RESET_INVALID)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookie(response)
    return response


async def _stored_password_hash(db: AsyncSession, user_id: UUID) -> str | None:
    async with db.begin():
        return (await db.execute(
            text("SELECT password_hash FROM users WHERE id = :id AND is_active = TRUE"),
            {"id": str(user_id)},
        )).scalar_one_or_none()


@router.get("", response_model=PasswordStatusResponse)
async def password_status(
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PasswordStatusResponse:
    return PasswordStatusResponse(has_password=bool(await _stored_password_hash(db, user_id)))


@router.post("/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user_id: UUID = Depends(get_current_user_id),
    session_id: UUID = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    settings = get_settings()
    await enforce_rate_limit(
        request,
        "password-change",
        settings.auth_login_rate_limit,
        60,
        account_identifier=str(user_id),
        max_body_bytes=settings.max_request_body_bytes,
    )
    current_hash = await _stored_password_hash(db, user_id)
    if not current_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PASSWORD_NOT_SET)
    if not await asyncio.to_thread(verify_password, payload.current_password, current_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CURRENT_PASSWORD_INVALID)
    if await asyncio.to_thread(verify_password, payload.new_password, current_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PASSWORD_REUSED)
    new_hash = await asyncio.to_thread(hash_password, payload.new_password)
    async with db.begin():
        changed = (await db.execute(
            text("SELECT change_account_password(:user_id, :session_id, :current_hash, :new_hash)"),
            {"user_id": str(user_id), "session_id": str(session_id),
             "current_hash": current_hash, "new_hash": new_hash},
        )).scalar_one()
    if not changed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=CURRENT_PASSWORD_INVALID)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
