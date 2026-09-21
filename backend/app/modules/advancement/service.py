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

    async def activate_double_elimination_reset(self, context, match, outcome) -> None:
        """Activate GF2 only when the losers-bracket finalist wins GF1."""
        if match.get("bracket_code") != "GF1" or outcome.winner_team_id != match.get("away_team_id"):
            return

        reset_result = await self.db.execute(
            text("""
                SELECT id
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND bracket_code = 'GF2'
                  AND status = 'cancelled'
                FOR UPDATE
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(match["tournament_id"]),
                "version_id": str(match["tournament_version_id"]),
                "stage_id": str(match["stage_id"]),
            },
        )
        reset = reset_result.mappings().one_or_none()
        if reset is None:
            raise ValueError("La gran final no tiene configurado el bracket reset")

        update_result = await self.db.execute(
            text("""
                UPDATE matches
                SET home_team_id = :home_team_id,
                    away_team_id = :away_team_id,
                    status = 'scheduled',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :match_id
                  AND organization_id = :organization_id
                  AND status = 'cancelled'
                  AND home_team_id IS NULL
                  AND away_team_id IS NULL
            """),
            {
                "home_team_id": str(match["home_team_id"]),
                "away_team_id": str(match["away_team_id"]),
                "match_id": str(reset["id"]),
                "organization_id": str(context.organization_id),
            },
        )
        if update_result.rowcount != 1:
            raise ValueError("El bracket reset ya fue activado o no está disponible")
        await self.db.execute(
            text("""
                INSERT INTO outbox_events (organization_id, event_type, payload)
                VALUES (:organization_id, 'MATCH_UPDATED', CAST(:payload AS jsonb))
            """),
            {
                "organization_id": str(context.organization_id),
                "payload": f'{{"match_id":"{reset["id"]}","tournament_id":"{match["tournament_id"]}"}}',
            },
        )
