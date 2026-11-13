from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_opening(db: AsyncSession, match_id: UUID, segment_id: UUID) -> None:
    await db.execute(text("SELECT record_sanction_opening(:match_id,:segment_id)"),
        {"match_id": match_id, "segment_id": segment_id})
