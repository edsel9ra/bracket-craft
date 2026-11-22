"""Lectura de ``administrative_audit_logs`` de la organización activa (spec 041)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.permissions import require_permission
from app.modules.organization_audit.catalog import project_details, referenced_member_ids
from app.modules.organization_audit.schemas import OrganizationAuditQuery

PERMISSION = "VIEW_ORGANIZATION_AUDIT"

_COUNT = """
    SELECT count(*)
    FROM administrative_audit_logs l
    LEFT JOIN organization_users ou
      ON ou.id = l.performed_by_member_id AND ou.organization_id = l.organization_id
    LEFT JOIN organization_users ou_user
      ON ou.id IS NULL AND ou_user.user_id = l.performed_by_user_id AND ou_user.organization_id = l.organization_id
    WHERE l.organization_id = :org
      AND (CAST(:actions AS text[]) IS NULL OR l.action = ANY(CAST(:actions AS text[])))
      AND (CAST(:actor AS uuid) IS NULL OR COALESCE(ou.id, ou_user.id) = CAST(:actor AS uuid))
      AND (CAST(:date_from AS timestamptz) IS NULL OR l.performed_at >= CAST(:date_from AS timestamptz))
      AND (CAST(:date_to AS timestamptz) IS NULL OR l.performed_at <= CAST(:date_to AS timestamptz))
"""

_PAGE = """
    SELECT l.id, l.performed_at, l.action, l.entity_type, l.entity_id, l.payload,
           COALESCE(ou.id, ou_user.id) AS actor_member_id, u.full_name AS actor_name,
           CASE l.entity_type
               WHEN 'matches' THEN EXISTS (
                   SELECT 1 FROM matches m WHERE m.id = l.entity_id AND m.organization_id = l.organization_id)
               WHEN 'sanction_cases' THEN EXISTS (
                   SELECT 1 FROM sanction_cases s WHERE s.id = l.entity_id AND s.organization_id = l.organization_id)
               ELSE FALSE
           END AS entity_available
    FROM administrative_audit_logs l
    LEFT JOIN organization_users ou
      ON ou.id = l.performed_by_member_id AND ou.organization_id = l.organization_id
    LEFT JOIN organization_users ou_user
      ON ou.id IS NULL AND ou_user.user_id = l.performed_by_user_id AND ou_user.organization_id = l.organization_id
    LEFT JOIN users u ON u.id = COALESCE(ou.user_id, ou_user.user_id)
    WHERE l.organization_id = :org
      AND (CAST(:actions AS text[]) IS NULL OR l.action = ANY(CAST(:actions AS text[])))
      AND (CAST(:actor AS uuid) IS NULL OR COALESCE(ou.id, ou_user.id) = CAST(:actor AS uuid))
      AND (CAST(:date_from AS timestamptz) IS NULL OR l.performed_at >= CAST(:date_from AS timestamptz))
      AND (CAST(:date_to AS timestamptz) IS NULL OR l.performed_at <= CAST(:date_to AS timestamptz))
    ORDER BY l.performed_at DESC, l.id DESC
    LIMIT :limit OFFSET :offset
"""

_MEMBER_NAMES = """
    SELECT ou.id, u.full_name FROM organization_users ou JOIN users u ON u.id = ou.user_id
    WHERE ou.organization_id = :org AND ou.id = ANY(CAST(:ids AS uuid[]))
"""


class OrganizationAuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, context, filters: OrganizationAuditQuery) -> dict:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await require_permission(self.db, context, PERMISSION)
            params = {
                "org": context.organization_id,
                "actions": filters.action or None,
                "actor": filters.actor_member_id,
                "date_from": filters.date_from,
                "date_to": filters.date_to,
            }
            total = (await self.db.execute(text(_COUNT), params)).scalar_one()
            rows = (await self.db.execute(
                text(_PAGE), {**params, "limit": filters.limit, "offset": filters.offset},
            )).mappings().all()
            member_ids = sorted(set().union(*(referenced_member_ids(row["action"], row["payload"]) for row in rows)))
            names = {
                str(row["id"]): row["full_name"]
                for row in (await self.db.execute(
                    text(_MEMBER_NAMES), {"org": context.organization_id, "ids": member_ids},
                )).mappings()
            }
        return {
            "items": [self._item(row, names) for row in rows],
            "total": total,
            "limit": filters.limit,
            "offset": filters.offset,
        }

    async def actors(self, context) -> list[dict]:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await require_permission(self.db, context, PERMISSION)
            rows = (await self.db.execute(text("""
                SELECT ou.id AS member_id, u.full_name AS name
                FROM organization_users ou JOIN users u ON u.id = ou.user_id
                WHERE ou.organization_id = :org
                ORDER BY u.full_name, ou.id
            """), {"org": context.organization_id})).mappings().all()
        return [dict(row) for row in rows]

    @staticmethod
    def _item(row, names: dict[str, str]) -> dict:
        details = project_details(row["action"], row["payload"], names)
        member_id = row["actor_member_id"]
        return {
            "id": row["id"],
            "performed_at": row["performed_at"],
            "action": row["action"],
            "cataloged": details is not None,
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "entity_available": row["entity_available"],
            "actor": {"kind": "member", "member_id": member_id, "name": row["actor_name"]}
            if member_id is not None else {"kind": "platform", "member_id": None, "name": None},
            "details": details,
        }
