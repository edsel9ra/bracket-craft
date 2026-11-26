"""Asignación y retirada del operador del torneo (spec 049, RF-003–RF-007, RF-011, RF-013).

Cada operación abre su transacción con ``set_rls_context()``. Un torneo o un
miembro ajenos dan el mismo error que uno inexistente, y la auditoría se
escribe en la misma transacción que el cambio.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.permissions import require_permission
from app.core.roles import ROLE_PRECEDENCE_SQL
from app.modules.tournament_roles.audit import (
    ASSIGN_TOURNAMENT_OPERATOR,
    REMOVE_TOURNAMENT_OPERATOR,
    record_tournament_role_audit,
)
from app.modules.tournament_roles.catalog import TOURNAMENT_OPERATOR, adds_permissions


class TournamentNotFound(LookupError):
    pass


class MemberNotFound(LookupError):
    pass


class AssignmentNotFound(LookupError):
    pass


_TEAM_SQL = """
    SELECT t.organization_user_id,
           u.full_name,
           COALESCE(
               (ARRAY_AGG(rd.code ORDER BY {role_precedence}) FILTER (WHERE rd.code IS NOT NULL))[1],
               'viewer'
           ) AS organization_role_code,
           t.role_code,
           ou.is_active,
           t.created_at AS assigned_at
    FROM tournament_member_roles t
    JOIN organization_users ou
      ON ou.id = t.organization_user_id
     AND ou.organization_id = t.organization_id
    JOIN users u ON u.id = ou.user_id
    LEFT JOIN organization_user_roles our
      ON our.organization_user_id = ou.id
     AND our.organization_id = ou.organization_id
    LEFT JOIN roles r
      ON r.id = our.role_id
     AND r.organization_id = ou.organization_id
    LEFT JOIN role_definitions rd ON rd.id = r.role_definition_id
    WHERE t.organization_id = :organization_id
      AND t.tournament_id = :tournament_id
      AND (CAST(:organization_user_id AS UUID) IS NULL OR t.organization_user_id = :organization_user_id)
    GROUP BY t.id, u.id, ou.id
    ORDER BY u.full_name, t.organization_user_id
"""
TEAM_SQL = text(_TEAM_SQL.format(role_precedence=ROLE_PRECEDENCE_SQL.format(column="rd.code")))


def _member(row) -> dict:
    data = dict(row)
    data["adds_permissions"] = adds_permissions(data["organization_role_code"])
    return data


class TournamentRoleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_team(self, context, tournament_id: UUID) -> list[dict]:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await self._tournament(context, tournament_id)
            return await self._team(context, tournament_id)

    async def assign(self, context, tournament_id: UUID, organization_user_id: UUID) -> tuple[dict, bool]:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await self._tournament(context, tournament_id)
            await require_permission(self.db, context, "MANAGE_MEMBERS")
            active = await self.db.scalar(
                text("""
                    SELECT TRUE FROM organization_users ou
                    JOIN users u ON u.id = ou.user_id
                    WHERE ou.id = :member AND ou.organization_id = :organization_id
                      AND ou.is_active AND u.is_active
                """),
                {"member": str(organization_user_id), "organization_id": str(context.organization_id)},
            )
            if not active:
                raise MemberNotFound
            created = await self.db.scalar(
                text("""
                    INSERT INTO tournament_member_roles
                        (organization_id, tournament_id, organization_user_id, role_code, created_by_member_id)
                    VALUES (:organization_id, :tournament_id, :member, :role_code, :creator)
                    ON CONFLICT (tournament_id, organization_user_id, role_code) DO NOTHING
                    RETURNING id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "member": str(organization_user_id),
                    "role_code": TOURNAMENT_OPERATOR,
                    "creator": str(context.organization_user_id),
                },
            )
            if created is not None:
                await record_tournament_role_audit(
                    self.db, context, tournament_id, organization_user_id, ASSIGN_TOURNAMENT_OPERATOR
                )
            [member] = await self._team(context, tournament_id, organization_user_id)
            return member, created is not None

    async def remove(self, context, tournament_id: UUID, organization_user_id: UUID) -> None:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await self._tournament(context, tournament_id)
            await require_permission(self.db, context, "MANAGE_MEMBERS")
            removed = await self.db.scalar(
                text("""
                    DELETE FROM tournament_member_roles
                    WHERE organization_id = :organization_id AND tournament_id = :tournament_id
                      AND organization_user_id = :member AND role_code = :role_code
                    RETURNING id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "member": str(organization_user_id),
                    "role_code": TOURNAMENT_OPERATOR,
                },
            )
            if removed is None:
                raise AssignmentNotFound
            await record_tournament_role_audit(
                self.db, context, tournament_id, organization_user_id, REMOVE_TOURNAMENT_OPERATOR
            )

    async def _tournament(self, context, tournament_id: UUID) -> None:
        found = await self.db.scalar(
            text("SELECT TRUE FROM tournaments WHERE id = :id AND organization_id = :organization_id"),
            {"id": str(tournament_id), "organization_id": str(context.organization_id)},
        )
        if not found:
            raise TournamentNotFound

    async def _team(self, context, tournament_id: UUID, organization_user_id: UUID | None = None) -> list[dict]:
        result = await self.db.execute(TEAM_SQL, {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "organization_user_id": str(organization_user_id) if organization_user_id else None,
        })
        return [_member(row) for row in result.mappings().all()]
