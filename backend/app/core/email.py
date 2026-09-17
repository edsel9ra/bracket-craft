import asyncio
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from app.core.config import get_settings


logger = logging.getLogger(__name__)


def _send_message(message: EmailMessage, host: str, port: int, use_tls: bool, username: str | None, password: str | None, timeout: int) -> None:
    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        if use_tls:
            smtp.starttls()
        if username:
            smtp.login(username, password or "")
        smtp.send_message(message)


async def send_invitation_email(
    recipient: str,
    organization_name: str,
    role_code: str,
    invite_url: str,
    expires_at: datetime,
) -> None:
    """Send an invitation through SMTP, or keep local development link-only."""

    settings = get_settings()
    if not settings.smtp_host:
        logger.warning("SMTP no configurado; se generó el enlace de invitación sin enviarlo")
        return

    message = EmailMessage()
    message["Subject"] = f"Invitación a {organization_name} en Bracket Craft"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(
        "Has recibido una invitación para colaborar en "
        f"{organization_name} con el rol {role_code}.\n\n"
        f"Acepta la invitación antes de {expires_at.isoformat()}:\n{invite_url}\n\n"
        "Si no esperabas este mensaje, puedes ignorarlo."
    )

    await asyncio.to_thread(
        _send_message,
        message,
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_use_tls,
        settings.smtp_username,
        settings.smtp_password,
        settings.smtp_timeout_seconds,
    )
