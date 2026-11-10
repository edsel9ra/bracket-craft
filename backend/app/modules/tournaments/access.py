import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import require_permission
from app.core.tenancy import AuthContext
from app.modules.tournaments.roster_status import (
    RosterLimits,
    effective_roster_limits,
)



async def _ensure_public_tournament(db: AsyncSession, tournament_id: UUID) -> None:
    result = await db.execute(
        text("SELECT 1 FROM v_public_tournaments WHERE id = :tournament_id"),
        {"tournament_id": str(tournament_id)},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Torneo público no encontrado")


async def _require_tournament_management(db: AsyncSession, context: AuthContext) -> None:
    try:
        await require_permission(db, context, "MANAGE_TOURNAMENTS")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _ensure_tournament(db: AsyncSession, organization_id: UUID, tournament_id: UUID) -> None:
    result = await db.execute(
        text("""
            SELECT 1
            FROM tournaments
            WHERE id = :tournament_id AND organization_id = :organization_id
        """),
        {"tournament_id": str(tournament_id), "organization_id": str(organization_id)},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Torneo no encontrado")


async def _version_roster_limits(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
) -> RosterLimits:
    """Read the effective roster limits of the stage's version (RF-045).

    The limits are a top-level key of ``rules_config``, so the version of the
    stage —the published one when it applies— is the only source. A stored
    configuration written before the keys existed resolves to "no limit".
    """

    result = await db.execute(
        text("""
            SELECT rules_config
            FROM tournament_versions
            WHERE id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(organization_id),
        },
    )
    row = result.mappings().one_or_none()
    config = row["rules_config"] if row is not None else None
    if isinstance(config, str):
        config = json.loads(config)
    return effective_roster_limits(config or {})
