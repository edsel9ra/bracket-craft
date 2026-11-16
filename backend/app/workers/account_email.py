"""Correos de cuenta de la recuperación de contraseña (spec 039).

El worker resuelve la cuenta, emite el token y envía el correo fuera de la
petición (RNF-001). Si el envío falla, invalida el token emitido antes de
reintentar (CL-7). Los logs solo llevan el id del trabajo y el tipo de error:
nunca el correo, el token ni el enlace (RF-011).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.email import (
    send_google_sign_in_reminder_email,
    send_password_changed_email,
    send_password_reset_email,
)
from app.modules.identity.password_recovery import (
    job_should_expire,
    new_reset_token,
    reset_expires_at,
    reset_url,
    token_hash,
)

ACCOUNT_EMAIL_BATCH_LIMIT = 20
ACCOUNT_EMAIL_MAX_ATTEMPTS = 5

logger = logging.getLogger(__name__)


async def _send_reset_request(db, job) -> None:
    now = datetime.now(UTC)
    if job_should_expire(job["created_at"], now):
        return
    token = new_reset_token()
    digest = token_hash(token)
    expires_at = reset_expires_at(now)
    async with db.begin():
        issued = (await db.execute(
            text("SELECT outcome, recipient FROM issue_password_reset(:id, :token_hash, :expires_at)"),
            {"id": str(job["id"]), "token_hash": digest, "expires_at": expires_at},
        )).mappings().one()
    if issued["outcome"] == "reset":
        try:
            await send_password_reset_email(issued["recipient"], reset_url(get_settings().frontend_base_url, token), expires_at)
        except Exception:
            async with db.begin():
                await db.execute(text("SELECT invalidate_password_reset_token(:token_hash)"), {"token_hash": digest})
            raise
    elif issued["outcome"] == "google_reminder":
        await send_google_sign_in_reminder_email(issued["recipient"])


async def _send_changed_notice(db, job) -> None:
    async with db.begin():
        recipient = (await db.execute(
            text("SELECT recipient FROM account_email_notice_target(:id)"), {"id": str(job["id"])},
        )).scalar_one_or_none()
    if recipient:
        await send_password_changed_email(recipient, job["created_at"])


async def process_account_email_jobs(session_factory: Callable[[], Any] = SessionFactory) -> int:
    async with session_factory() as db:
        async with db.begin():
            jobs = (await db.execute(
                text("SELECT id, kind, created_at FROM claim_account_email_jobs(:limit)"),
                {"limit": ACCOUNT_EMAIL_BATCH_LIMIT},
            )).mappings().all()
        for job in jobs:
            try:
                if job["kind"] == "password_reset_request":
                    await _send_reset_request(db, job)
                else:
                    await _send_changed_notice(db, job)
            except Exception as exc:
                logger.warning("No se pudo enviar el correo de cuenta %s (%s)", job["id"], type(exc).__name__)
                async with db.begin():
                    await db.execute(
                        text("SELECT fail_account_email_job(:id, :max_attempts)"),
                        {"id": str(job["id"]), "max_attempts": ACCOUNT_EMAIL_MAX_ATTEMPTS},
                    )
                continue
            async with db.begin():
                await db.execute(text("SELECT complete_account_email_job(:id)"), {"id": str(job["id"])})
        return len(jobs)
