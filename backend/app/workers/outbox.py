import asyncio
import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.database import SessionFactory, validate_application_role
from app.core.config import get_settings
from app.core.outbox import OUTBOX_STREAM, OUTBOX_STREAM_MAXLEN
from app.workers.heartbeat import (
    HEARTBEAT_INTERVAL_SECONDS,
    heartbeat_is_due,
    heartbeat_is_fresh,
    publish_heartbeat,
)

# ``heartbeat_is_fresh`` se reexporta desde aquí porque el plan de la spec lo
# documenta en este módulo; el healthcheck importa ``app.workers.heartbeat``
# para no cargar la base de datos ni Redis.
__all__ = [
    "build_stream_message",
    "heartbeat_is_fresh",
    "main",
    "process_once",
    "publish_stream_event",
]


logger = logging.getLogger(__name__)


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


async def process_once() -> int:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    async with SessionFactory() as db:
        try:
            async with db.begin():
                result = await db.execute(text("""
                    SELECT id, organization_id, event_type, payload
                    FROM claim_outbox_events(20)
                """))
                events = result.mappings().all()

            for event in events:
                try:
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
        finally:
            await redis.aclose()


async def main():
    if get_settings().app_env.lower().strip() not in {"development", "dev", "local"}:
        await validate_application_role()
    last_heartbeat: float | None = None
    while True:
        # El latido mide que el bucle avanza: se publica también cuando la base
        # de datos falla y ``process_once`` reintenta.
        now = time.monotonic()
        if heartbeat_is_due(last_heartbeat, now, HEARTBEAT_INTERVAL_SECONDS):
            try:
                publish_heartbeat()
                last_heartbeat = now
            except OSError:
                logger.exception("No se pudo publicar el latido del worker")
        try:
            await process_once()
        except Exception:
            logger.exception("Error procesando outbox")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
