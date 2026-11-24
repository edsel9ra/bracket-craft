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


async def send_rectification_decision_email(recipient: str, request_id: str, decision: str, reason: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP no configurado")
    decisions = {"approve": "aprobada", "reject": "rechazada"}
    verdict = decisions[decision]
    message = EmailMessage()
    message["Subject"] = f"Decisión de rectificación {request_id} — Bracket Craft"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(f"Tu solicitud de rectificación {request_id} ha sido {verdict}.\n\nMotivo: {reason}\n")
    await asyncio.to_thread(_send_message, message, settings.smtp_host, settings.smtp_port,
        settings.smtp_use_tls, settings.smtp_username, settings.smtp_password, settings.smtp_timeout_seconds)


async def send_sanction_notice_email(recipient: str, case_id: str, notification_type: str, decision: str | None, reason: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP no configurado")
    acts = {"withdrawn": "retirado", "closed_by_rectification": "cerrado por rectificación", "decision": "resuelto"}
    decisions = {"maintain": "mantener", "annul": "anular", "reduce": "reducir", "approve": "aprobar", "reject": "rechazar"}
    act = decisions[decision] if decision else acts[notification_type]
    message = EmailMessage()
    message["Subject"] = f"Aviso de expediente {case_id} — Bracket Craft"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(f"Expediente {case_id}: {act}.\n\nMotivo: {reason}\n")
    await asyncio.to_thread(_send_message, message, settings.smtp_host, settings.smtp_port,
        settings.smtp_use_tls, settings.smtp_username, settings.smtp_password, settings.smtp_timeout_seconds)


async def _send_account_email(recipient: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP no configurado")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(body)
    await asyncio.to_thread(_send_message, message, settings.smtp_host, settings.smtp_port,
        settings.smtp_use_tls, settings.smtp_username, settings.smtp_password, settings.smtp_timeout_seconds)


async def send_notification_email(recipient: str, subject: str, body: str) -> None:
    await _send_account_email(recipient, subject, body)


async def send_password_reset_email(recipient: str, reset_url: str, expires_at: datetime) -> None:
    await _send_account_email(
        recipient,
        "Recupera tu contraseña de Bracket Craft",
        "Alguien pidió recuperar la contraseña de tu cuenta de Bracket Craft.\n\n"
        f"Para elegir una contraseña nueva abre este enlace, válido durante 30 minutos "
        f"(hasta {expires_at.isoformat()}) y un solo uso:\n{reset_url}\n\n"
        "Si no lo pediste, ignora este mensaje: tu contraseña no cambia.",
    )


async def send_google_sign_in_reminder_email(recipient: str) -> None:
    await _send_account_email(
        recipient,
        "Tu cuenta de Bracket Craft entra con Google",
        "Alguien pidió recuperar la contraseña de tu cuenta de Bracket Craft.\n\n"
        "Tu cuenta no tiene contraseña: entra con el botón «Continuar con Google» "
        "de la pantalla de acceso.\n\n"
        "Si no lo pediste, ignora este mensaje.",
    )


async def send_password_changed_email(recipient: str, changed_at: datetime) -> None:
    await _send_account_email(
        recipient,
        "Tu contraseña de Bracket Craft ha cambiado",
        f"La contraseña de tu cuenta de Bracket Craft cambió el {changed_at.isoformat()}.\n\n"
        "Si no fuiste tú, recupera la contraseña desde la pantalla de acceso y avisa "
        "a la administración de tu organización.",
    )
