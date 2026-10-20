import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.database import SessionFactory, validate_application_role
from app.core.config import get_settings
from app.core.outbox import OUTBOX_STREAM, OUTBOX_STREAM_MAXLEN


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
    while True:
        try:
            await process_once()
        except Exception:
            logger.exception("Error procesando outbox")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
