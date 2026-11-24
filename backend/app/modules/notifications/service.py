"""Bandeja y preferencias del miembro en su organización activa (spec 046, RF-005, RF-008–RF-010)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.notifications.catalog import effective_preferences
from app.modules.notifications.schemas import NotificationPreferences, NotificationQuery

# Solo los avisos propios entregados en la bandeja de la organización activa.
_COUNTS = """
    SELECT count(*) AS total, count(*) FILTER (WHERE r.read_at IS NULL) AS unread
    FROM notification_recipients r
    WHERE r.organization_id = :org AND r.user_id = :user AND r.channel = 'inbox' AND r.outcome = 'delivered'
"""

# El nombre del jugador sancionado se lee al listar; nunca se copia en el aviso (RF-009).
# Sin VIEW_SANCTION_CASES el aviso de sanción llega sin jugador ni suspensión (DA-5).
_PAGE = """
    SELECT n.id, n.notification_type, n.created_at, r.read_at, n.tournament_id,
           t.name AS tournament_name, n.match_id, home.name AS home_team_name,
           away.name AS away_team_name, n.match_count, ps.matches_suspended,
           p.first_name, p.last_name, sanctioned_team.name AS sanction_team_name
    FROM notification_recipients r
    JOIN notifications n ON n.id = r.notification_id AND n.organization_id = r.organization_id
    JOIN tournaments t ON t.id = n.tournament_id AND t.organization_id = n.organization_id
    LEFT JOIN matches m ON m.id = n.match_id AND m.organization_id = n.organization_id
    LEFT JOIN teams home ON home.id = m.home_team_id AND home.organization_id = n.organization_id
    LEFT JOIN teams away ON away.id = m.away_team_id AND away.organization_id = n.organization_id
    LEFT JOIN player_suspensions ps
      ON ps.id = n.suspension_id AND ps.organization_id = n.organization_id AND CAST(:sanction_detail AS boolean)
    LEFT JOIN players p ON p.id = ps.player_id AND p.organization_id = n.organization_id
    LEFT JOIN LATERAL (
        SELECT source.team_id FROM (
            SELECT mr.team_id, 0 AS priority, NULL::timestamptz AS since
            FROM match_rosters mr
            WHERE mr.match_id = ps.origin_match_id AND mr.player_id = ps.player_id
              AND mr.organization_id = n.organization_id
            UNION ALL
            SELECT ro.team_id, 1, ro.valid_from
            FROM rosters ro
            WHERE ro.tournament_id = ps.source_tournament_id AND ro.player_id = ps.player_id
              AND ro.organization_id = n.organization_id
        ) source
        ORDER BY source.priority, source.since DESC NULLS LAST
        LIMIT 1
    ) team_of_player ON TRUE
    LEFT JOIN teams sanctioned_team
      ON sanctioned_team.id = team_of_player.team_id AND sanctioned_team.organization_id = n.organization_id
    WHERE r.organization_id = :org AND r.user_id = :user AND r.channel = 'inbox' AND r.outcome = 'delivered'
    ORDER BY n.created_at DESC, n.id DESC
    LIMIT :limit OFFSET :offset
"""

_OWN_NOTICE = """
    SELECT EXISTS (
        SELECT 1 FROM notification_recipients r WHERE r.notification_id = :id AND r.organization_id = :org AND r.user_id = :user AND r.channel = 'inbox' AND r.outcome = 'delivered'
    )
"""

_PREFERENCES = """
    SELECT notification_type, channel, enabled
    FROM notification_preferences
    WHERE organization_id = :org AND user_id = :user
"""

_SAVE_PREFERENCE = """
    INSERT INTO notification_preferences (organization_id, user_id, notification_type, channel, enabled)
    VALUES (:org, :user, :type, :channel, :enabled)
    ON CONFLICT (organization_id, user_id, notification_type, channel)
    DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = CURRENT_TIMESTAMP
"""


def _item(row) -> dict:
    sanction = None
    if row["matches_suspended"] is not None:
        names = [part for part in (row["first_name"], row["last_name"]) if part]
        sanction = {
            "player_name": " ".join(names) or None,
            "team_name": row["sanction_team_name"],
            "matches_suspended": row["matches_suspended"],
        }
    return {
        "id": row["id"],
        "type": row["notification_type"],
        "created_at": row["created_at"],
        "read_at": row["read_at"],
        "tournament_id": row["tournament_id"],
        "tournament_name": row["tournament_name"],
        "match_id": row["match_id"],
        "home_team_name": row["home_team_name"],
        "away_team_name": row["away_team_name"],
        "match_count": row["match_count"],
        "sanction": sanction,
    }


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _scope(self, context) -> dict:
        return {"org": context.organization_id, "user": context.user_id}

    async def list(self, context, query: NotificationQuery) -> dict:
        scope = self._scope(context)
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            counts = (await self.db.execute(text(_COUNTS), scope)).mappings().one()
            sanction_detail = (await self.db.execute(
                text("SELECT sanction_member_has_permission(:org, 'VIEW_SANCTION_CASES')"), scope,
            )).scalar_one()
            rows = (await self.db.execute(text(_PAGE), {
                **scope, "limit": query.limit, "offset": query.offset, "sanction_detail": bool(sanction_detail),
            })).mappings().all()
        return {
            "items": [_item(row) for row in rows],
            "unread_count": counts["unread"],
            "total": counts["total"],
            "limit": query.limit,
            "offset": query.offset,
        }

    async def mark_read(self, context, notification_id: UUID | None) -> None:
        """Marca un aviso propio, o todos con ``None``; uno ajeno o inexistente da ``LookupError``."""

        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            if notification_id is not None:
                own = (await self.db.execute(
                    text(_OWN_NOTICE), {**self._scope(context), "id": notification_id},
                )).scalar_one()
                if not own:
                    raise LookupError("Aviso no encontrado")
            await self.db.execute(
                text("SELECT mark_notifications_read(CAST(:ids AS uuid[]))"),
                {"ids": None if notification_id is None else [notification_id]},
            )

    async def preferences(self, context) -> dict:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            return await self._read_preferences(context)

    async def save_preferences(self, context, body: NotificationPreferences) -> dict:
        scope = self._scope(context)
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await self.db.execute(text(_SAVE_PREFERENCE), [
                {**scope, "type": item.type, "channel": item.channel, "enabled": item.enabled}
                for item in body.items
            ])
            return await self._read_preferences(context)

    async def _read_preferences(self, context) -> dict:
        saved = (await self.db.execute(text(_PREFERENCES), self._scope(context))).mappings().all()
        return {"items": [
            {"type": item.notification_type, "channel": item.channel, "enabled": item.enabled}
            for item in effective_preferences(saved)
        ]}
