import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.permissions import require_permission
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.rules_engine.engine import (
    normalize_rules_config,
)
from app.modules.rules_engine.schemas import CreateTournamentRequest
from app.modules.tournaments.schemas import (
    TournamentCreateResponse,
    TournamentSummaryResponse,
)


router = APIRouter()


@router.post("", response_model=TournamentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tournament(
    payload: CreateTournamentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TournamentCreateResponse:
    try:
        rules_config = normalize_rules_config(payload.rules_config.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        try:
            await require_permission(db, context, "MANAGE_TOURNAMENTS")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        tournament_result = await db.execute(
        text("""
            INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES (:organization_id, :name, :season, :start_date, 'draft', CAST(:config AS jsonb))
                RETURNING id
            """),
            {
                "organization_id": str(context.organization_id),
                "name": payload.name,
                "season": payload.season,
                "start_date": payload.start_date,
                "config": json.dumps(rules_config),
            },
        )
        tournament_id = tournament_result.scalar_one()
        version_result = await db.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config, phase_config, status, created_by_member_id)
                VALUES (:organization_id, :tournament_id, 1, CAST(:rules AS jsonb), '{}'::jsonb, 'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "rules": json.dumps(rules_config),
                "member_id": str(context.organization_user_id),
            },
        )
        version_id = version_result.scalar_one()

    return {"id": str(tournament_id), "version_id": str(version_id), "status": "draft"}


@router.get("")
async def list_tournaments(
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TournamentSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        result = await db.execute(
            text("""
                SELECT t.id, t.name, t.season, t.start_date, t.status, t.created_at,
                       (
                           SELECT tv.id
                           FROM tournament_versions tv
                           WHERE tv.tournament_id = t.id
                             AND tv.organization_id = t.organization_id
                             AND tv.status = 'draft'
                           ORDER BY tv.version_number DESC
                           LIMIT 1
                       ) AS draft_version_id
                FROM tournaments t
                WHERE t.organization_id = :organization_id
                ORDER BY t.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"organization_id": str(context.organization_id), "limit": limit, "offset": offset},
        )
        tournaments = [dict(row) for row in result.mappings().all()]
    return tournaments
