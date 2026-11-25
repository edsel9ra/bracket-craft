import asyncio
import json
import logging
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.database import SessionFactory, validate_application_role
from app.core.email import (
    send_notification_email,
    send_rectification_decision_email,
    send_sanction_notice_email,
)
from app.core.config import get_settings
from app.core.outbox import OUTBOX_STREAM, OUTBOX_STREAM_MAXLEN
from app.modules.notifications.delivery import deliver_email, deliver_inbox
from app.modules.sanction_appeals.notifications import deliver_internal
from app.modules.webhooks.catalog import REQUEST_TIMEOUT_SECONDS
from app.modules.webhooks.delivery import build_client, deliver_webhook
from app.modules.webhooks.network import resolve_target
from app.workers.heartbeat import (
    HEARTBEAT_INTERVAL_SECONDS,
    heartbeat_is_due,
    heartbeat_is_fresh,
    publish_heartbeat,
)
from app.workers.account_email import process_account_email_jobs
from app.workers.retention import (
    purge_account_recovery_once,
    purge_is_due,
    purge_once,
    purge_webhook_deliveries_once,
)

# ``heartbeat_is_fresh`` se reexporta desde aquí porque el plan de la spec lo
# documenta en este módulo; el healthcheck importa ``app.workers.heartbeat``
# para no cargar la base de datos ni Redis.
__all__ = [
    "build_stream_message",
    "dispatch_webhook_deliveries",
    "heartbeat_is_fresh",
    "main",
    "process_notification_emails",
    "process_once",
    "publish_stream_event",
]


logger = logging.getLogger(__name__)

WEBHOOK_CONCURRENCY = 10


def build_stream_message(event: Mapping[str, Any]) -> str:
    """Construye el sobre JSON que se publica en el stream del outbox.

    ``event_id`` es aditivo y duplica ``id`` durante la transición; el payload
    de dominio se conserva tal cual.
    """

    event_id = str(event["id"])
    return json.dumps(
        {
            "event_id": event_id,
            "id": event_id,
            "organization_id": str(event["organization_id"]),
            "event_type": event["event_type"],
            "payload": event["payload"],
        },
        default=str,
    )


async def publish_stream_event(redis: Redis, event: Mapping[str, Any]) -> None:
    """Publica un evento con ``MAXLEN`` aproximado fijo.

    La excepción de ``xadd`` se propaga a ``process_once`` para que marque el
    evento como fallido.
    """

    await redis.xadd(
        OUTBOX_STREAM,
        {"event": build_stream_message(event)},
        maxlen=OUTBOX_STREAM_MAXLEN,
        approximate=True,
    )


async def process_once(redis: Redis | None = None) -> int:
    """Procese un lote de eventos; sin ``redis`` abre y cierra su propio cliente."""

    if redis is None:
        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        try:
            return await process_once(redis)
        finally:
            await redis.aclose()

    async with SessionFactory() as db:
        async with db.begin():
            result = await db.execute(text("""
                SELECT id, organization_id, event_type, payload
                FROM claim_outbox_events(20)
            """))
            events = result.mappings().all()

        for event in events:
            try:
                if event["event_type"] == "NOTIFICATION_INBOX":
                    await deliver_inbox(db, event)
                elif event["event_type"] == "SANCTION_CASE_NOTICE_INTERNAL":
                    await deliver_internal(db, event)
                elif event["event_type"] == "SANCTION_CASE_NOTICE_EMAIL":
                    async with db.begin():
                        payload = (await db.execute(text("SELECT sanction_notice_email_payload(:id)"),
                            {"id": event["id"]})).scalar_one()
                    if payload is None:
                        raise PermissionError("SANCTION_RECIPIENT_NOT_AUTHORIZED")
                    await send_sanction_notice_email(recipient=payload["recipient"], case_id=payload["case_id"],
                        notification_type=payload["type"], decision=payload["decision"], reason=payload["reason"])
                    async with db.begin():
                        await db.execute(text("SELECT record_sanction_email_delivery(:id)"), {"id": event["id"]})
                elif event["event_type"] == "RECTIFICATION_DECISION_EMAIL":
                    payload = event["payload"]
                    await send_rectification_decision_email(payload["recipient"], payload["request_id"],
                        payload["decision"], payload["reason"])
                else:
                    await publish_stream_event(redis, event)
            except Exception as exc:
                async with db.begin():
                    await db.execute(
                        text("SELECT fail_outbox_event(:id, :error)"),
                        {"id": str(event["id"]), "error": str(exc)},
                    )
                continue

            try:
                async with db.begin():
                    await db.execute(
                        text("SELECT complete_outbox_event(:id)"),
                        {"id": str(event["id"])},
                    )
            except Exception as exc:
                logger.exception("No se pudo completar el evento outbox %s", event["id"])
                async with db.begin():
                    await db.execute(
                        text("SELECT fail_outbox_event(:id, :error)"),
                        {"id": str(event["id"]), "error": str(exc)},
                    )
        return len(events)


async def process_notification_emails() -> int:
    """Procesa un lote de correos de aviso (spec 046), fuera del bucle del outbox."""

    async with SessionFactory() as db:
        async with db.begin():
            result = await db.execute(text("""
                SELECT id, organization_id, event_type, payload
                FROM claim_notification_email_events(20)
            """))
            events = result.mappings().all()

        for event in events:
            try:
                await deliver_email(
                    db, event, base_url=get_settings().frontend_base_url, send=send_notification_email
                )
            except Exception as exc:
                # Solo el id y el tipo de error: el mensaje del SMTP puede llevar el correo.
                logger.warning("No se pudo enviar el correo del aviso %s: %s", event["id"], type(exc).__name__)
                async with db.begin():
                    await db.execute(
                        text("SELECT fail_outbox_event(:id, :error)"),
                        {"id": str(event["id"]), "error": type(exc).__name__},
                    )
                continue
            async with db.begin():
                await db.execute(text("SELECT complete_outbox_event(:id)"), {"id": str(event["id"])})
        return len(events)


async def _deliver_webhook_event(client, event, *, resolve, timeout) -> None:
    # Cada entrega usa su propia sesión: un destino lento no retiene a las demás (RNF-001).
    async with SessionFactory() as db:
        try:
            await deliver_webhook(
                db, event, key=get_settings().webhook_secret_key, client=client, resolve=resolve, timeout=timeout
            )
        except Exception as exc:
            # Solo el id y el tipo de error: nunca la URL ni el secreto (RNF-002).
            logger.warning("No se pudo procesar la entrega de webhook %s: %s", event["id"], type(exc).__name__)
            async with db.begin():
                await db.execute(
                    text("SELECT fail_outbox_event(:id, :error)"),
                    {"id": str(event["id"]), "error": type(exc).__name__},
                )


async def dispatch_webhook_deliveries(
    client,
    in_flight: set[asyncio.Task],
    *,
    limit: int = WEBHOOK_CONCURRENCY,
    resolve=resolve_target,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> int:
    """Reclama tantas entregas como huecos libres y lanza cada una en su propia tarea."""

    free = limit - len(in_flight)
    if free <= 0:
        return 0
    async with SessionFactory() as db:
        async with db.begin():
            result = await db.execute(
                text("SELECT id, organization_id, event_type, payload FROM claim_webhook_delivery_events(:limit)"),
                {"limit": free},
            )
            events = result.mappings().all()
    for event in events:
        task = asyncio.create_task(_deliver_webhook_event(client, event, resolve=resolve, timeout=timeout))
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)
    return len(events)


async def main():
    if get_settings().app_env.lower().strip() not in {"development", "dev", "local"}:
        await validate_application_role()
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await asyncio.gather(
            _run_loop(redis), _run_account_email_loop(), _run_notification_email_loop(), _run_webhook_loop()
        )
    finally:
        await redis.aclose()


async def _run_account_email_loop() -> None:
    # Bucle aparte: un SMTP lento o caído no retrasa la publicación de eventos
    # en tiempo real ni el latido del bucle del outbox (spec 039).
    while True:
        try:
            await process_account_email_jobs()
        except Exception:
            logger.exception("Error procesando correos de cuenta")
        await asyncio.sleep(1)


async def _run_notification_email_loop() -> None:
    # Bucle aparte: un SMTP lento no frena el tiempo real ni la bandeja (RNF-002).
    while True:
        try:
            await process_notification_emails()
        except Exception:
            logger.exception("Error procesando correos de avisos")
        await asyncio.sleep(1)


async def _run_webhook_loop() -> None:
    # Bucle aparte con hasta 10 entregas a la vez: un destino lento no frena el
    # tiempo real, la bandeja, el correo ni los demás webhooks (spec 047, RNF-001).
    in_flight: set[asyncio.Task] = set()
    client = build_client()
    try:
        while True:
            try:
                await dispatch_webhook_deliveries(client, in_flight)
            except Exception:
                logger.exception("Error procesando entregas de webhooks")
            await asyncio.sleep(1)
    finally:
        for task in in_flight:
            task.cancel()
        await asyncio.gather(*in_flight, return_exceptions=True)
        await client.aclose()


async def _run_loop(redis: Redis) -> None:
    last_heartbeat: float | None = None
    last_purge: float | None = None
    while True:
        # El bucle se considera detenido cuando no completa una vuelta en 90 s,
        # haya o no eventos; un fallo de dependencia con el bucle girando no
        # cuenta como detenido. Por eso el latido se publica al principio de
        # cada vuelta, también cuando ``process_once`` falla y reintenta.
        now = time.monotonic()
        if heartbeat_is_due(last_heartbeat, now, HEARTBEAT_INTERVAL_SECONDS):
            try:
                publish_heartbeat()
                last_heartbeat = now
            except OSError:
                logger.exception("No se pudo publicar el latido del worker")
        try:
            await process_once(redis)
        except Exception:
            logger.exception("Error procesando outbox")
        if purge_is_due(last_purge, now):
            last_purge = now
            try:
                await purge_once(datetime.now(timezone.utc))
            except Exception:
                logger.exception("No se pudo completar la purga periódica")
            try:
                await purge_account_recovery_once(datetime.now(timezone.utc))
            except Exception:
                logger.exception("No se pudo completar la purga de recuperación de contraseña")
            try:
                await purge_webhook_deliveries_once(datetime.now(timezone.utc))
            except Exception:
                logger.exception("No se pudo completar la purga de entregas de webhooks")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
