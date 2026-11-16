import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.database import SessionFactory

SESSION_RETENTION = timedelta(days=30)
OUTBOX_RETENTION = timedelta(days=7)
ACCOUNT_RECOVERY_RETENTION = timedelta(days=7)
PURGE_INTERVAL_SECONDS = 3600
PURGE_BATCH_LIMIT = 500
PURGE_MAX_BATCHES = 20

logger = logging.getLogger(__name__)


def retention_cutoffs(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("La fecha de purga debe incluir zona horaria")
    return now - SESSION_RETENTION, now - OUTBOX_RETENTION


def purge_is_due(last: float | None, now: float) -> bool:
    return last is None or now < last or now - last >= PURGE_INTERVAL_SECONDS


async def purge_once(now: datetime) -> tuple[int, int]:
    session_cutoff, outbox_cutoff = retention_cutoffs(now)
    sessions_deleted = 0
    outbox_deleted = 0
    async with SessionFactory() as db:
        for _ in range(PURGE_MAX_BATCHES):
            async with db.begin():
                result = await db.execute(
                    text("SELECT * FROM public.purge_retained_records(:sessions, :outbox, :batch_limit)"),
                    {"sessions": session_cutoff, "outbox": outbox_cutoff, "batch_limit": PURGE_BATCH_LIMIT},
                )
                counts = result.one()
            sessions_deleted += counts[0]
            outbox_deleted += counts[1]
            if counts[0] < PURGE_BATCH_LIMIT and counts[1] < PURGE_BATCH_LIMIT:
                break
    logger.info("Purga completada: sesiones=%d, eventos outbox=%d", sessions_deleted, outbox_deleted)
    return sessions_deleted, outbox_deleted


async def purge_account_recovery_once(now: datetime) -> tuple[int, int]:
    """Purge used/expired reset links and finished account email jobs (spec 039).

    Security events are kept: only the queue and the links are purged.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("La fecha de purga debe incluir zona horaria")
    cutoff = now - ACCOUNT_RECOVERY_RETENTION
    tokens_deleted = 0
    jobs_deleted = 0
    async with SessionFactory() as db:
        for _ in range(PURGE_MAX_BATCHES):
            async with db.begin():
                result = await db.execute(
                    text("SELECT * FROM public.purge_account_recovery_records(:cutoff, :batch_limit)"),
                    {"cutoff": cutoff, "batch_limit": PURGE_BATCH_LIMIT},
                )
                counts = result.one()
            tokens_deleted += counts[0]
            jobs_deleted += counts[1]
            if counts[0] < PURGE_BATCH_LIMIT and counts[1] < PURGE_BATCH_LIMIT:
                break
    logger.info("Purga de recuperación completada: enlaces=%d, correos de cuenta=%d", tokens_deleted, jobs_deleted)
    return tokens_deleted, jobs_deleted
