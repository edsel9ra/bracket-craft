from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_match_slot_assignments(
    db: AsyncSession,
    organization_id: UUID,
    match_id: UUID,
    *,
    origin: str = "manual",
    side: str | None = None,
    advancement_link_id: UUID | None = None,
) -> None:
    await db.execute(
        text("""
            INSERT INTO match_slot_assignments
                (organization_id, tournament_id, match_id, side, team_id,
                 origin, advancement_link_id)
            SELECT m.organization_id, m.tournament_id, m.id, slot.side, slot.team_id,
                   :origin, :advancement_link_id
            FROM matches m
            CROSS JOIN LATERAL (
                VALUES ('home', m.home_team_id), ('away', m.away_team_id)
            ) slot(side, team_id)
            WHERE m.id = :match_id AND m.organization_id = :organization_id
              AND slot.team_id IS NOT NULL
              AND (CAST(:side AS text) IS NULL OR slot.side = :side)
        """),
        {
            "organization_id": str(organization_id),
            "match_id": str(match_id),
            "origin": origin,
            "side": side,
            "advancement_link_id": str(advancement_link_id) if advancement_link_id else None,
        },
    )
