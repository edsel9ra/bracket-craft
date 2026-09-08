import asyncio
import json
import logging

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.database import SessionFactory
from app.core.config import get_settings


OUTBOX_CHANNEL = "bracket_craft.events"
logger = logging.getLogger(__name__)


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
                message = json.dumps({
                    "id": str(event["id"]),
                    "organization_id": str(event["organization_id"]),
                    "event_type": event["event_type"],
                    "payload": event["payload"],
                }, default=str)
                try:
                    subscribers = await redis.publish(OUTBOX_CHANNEL, message)
                    if subscribers < 1:
                        raise RuntimeError("No hay consumidores del canal de eventos")
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
    while True:
        try:
            await process_once()
        except Exception:
            logger.exception("Error procesando outbox")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
