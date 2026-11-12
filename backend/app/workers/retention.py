import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.database import SessionFactory

SESSION_RETENTION = timedelta(days=30)
OUTBOX_RETENTION = timedelta(days=7)
PURGE_INTERVAL_SECONDS = 3600
PURGE_BATCH_LIMIT = 500

logger = logging.getLogger(__name__)


def retention_cutoffs(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("La fecha de purga debe incluir zona horaria")
    return now - SESSION_RETENTION, now - OUTBOX_RETENTION


def purge_is_due(last: float | None, now: float) -> bool:
    return last is None or now < last or now - last >= PURGE_INTERVAL_SECONDS


async def purge_once(now: datetime) -> tuple[int, int]:
    session_cutoff, outbox_cutoff = retention_cutoffs(now)
    async with SessionFactory() as db:
        async with db.begin():
            result = await db.execute(
                text("SELECT * FROM public.purge_retained_records(:sessions, :outbox, :batch_limit)"),
                {"sessions": session_cutoff, "outbox": outbox_cutoff, "batch_limit": PURGE_BATCH_LIMIT},
            )
            counts = result.one()
    logger.info("Purga completada: sesiones=%d, eventos outbox=%d", counts[0], counts[1])
    return counts[0], counts[1]
