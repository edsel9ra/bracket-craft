from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AdvancementService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def advance_from_match(self, context, match_id: UUID, match, outcome) -> None:
        links_result = await self.db.execute(
            text("""
                SELECT target_match_id, target_side, outcome
                FROM advancement_links
                WHERE organization_id = :organization_id
                  AND source_match_id = :source_match_id
            """),
            {"organization_id": str(context.organization_id), "source_match_id": str(match_id)},
        )
        links = links_result.mappings().all()
        if not links:
            return

        winner = outcome.winner_team_id
        if winner is None:
            raise ValueError("No se puede avanzar una llave sin ganador")
        loser = match["away_team_id"] if winner == match["home_team_id"] else match["home_team_id"]

        for link in links:
            team_id = winner if link["outcome"] == "winner" else loser
            column = "home_team_id" if link["target_side"] == "home" else "away_team_id"
            update_result = await self.db.execute(
                text(f"""
                    UPDATE matches
                    SET {column} = :team_id, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :target_match_id
                      AND organization_id = :organization_id
                      AND status = 'scheduled'
                      AND {column} IS NULL
                """),
                {
                    "team_id": str(team_id),
                    "target_match_id": str(link["target_match_id"]),
                    "organization_id": str(context.organization_id),
                },
            )
            if update_result.rowcount != 1:
                raise ValueError("El partido destino del advancement no está disponible")
