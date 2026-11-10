from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.locking import lock_stage_and_version, lock_version
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.tournaments.schemas import (
    AssignStageTeamsRequest,
    CreateStageRequest,
    StageSummaryResponse,
    StageTeamAssignmentResponse,
    StageTeamsResponse,
)
from app.modules.tournaments.roster_status import (
    RosterSizeOutOfRange,
    count_active_roster_players_by_team,
    describe_roster_violations,
)

from app.modules.tournaments.access import (
    _ensure_tournament,
    _require_tournament_management,
    _version_roster_limits,
)

router = APIRouter()


async def _enforce_roster_size(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    team_ids: Sequence[UUID],
) -> None:
    """Reject the whole batch when any team's active roster is out of range.

    Every team is counted before a single row is inserted, so the batch stays
    all-or-nothing (RF-045). Without configured limits no counting query runs
    and the previous behaviour is kept.
    """

    limits = await _version_roster_limits(
        db, organization_id, tournament_id, version_id
    )
    if not limits.has_limits:
        return
    rows = await count_active_roster_players_by_team(
        db, organization_id, tournament_id, team_ids
    )
    detail = describe_roster_violations(rows, limits)
    if detail:
        raise RosterSizeOutOfRange(detail)


@router.get("/{tournament_id}/stages")
async def list_stages(
    tournament_id: UUID,
    version_id: UUID | None = None,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[StageSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        result = await db.execute(
            text("""
                SELECT s.id, s.tournament_version_id, s.name, s.stage_type, s.stage_order,
                       tv.status AS version_status
                FROM stages s
                JOIN tournament_versions tv
                  ON tv.id = s.tournament_version_id
                 AND tv.tournament_id = s.tournament_id
                 AND tv.organization_id = s.organization_id
                WHERE s.tournament_id = :tournament_id
                  AND s.organization_id = :organization_id
                  AND (CAST(:version_id AS UUID) IS NULL OR s.tournament_version_id = CAST(:version_id AS UUID))
                ORDER BY s.tournament_version_id, s.stage_order, s.id
                LIMIT :limit OFFSET :offset
            """),
            {
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
                "version_id": str(version_id) if version_id else None,
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(row) for row in result.mappings().all()]


@router.post("/{tournament_id}/stages", response_model=StageSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_stage(
    tournament_id: UUID,
    payload: CreateStageRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> StageSummaryResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        # Version-only exception: lock the version and then insert the stage.
        # There is no pre-existing phase to lock first.
        try:
            version_status = await lock_version(
                db,
                context.organization_id,
                payload.version_id,
                tournament_id=tournament_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Versión no encontrada en el torneo") from exc
        if version_status != "draft":
            raise HTTPException(status_code=409, detail="La versión publicada es inmutable")
        try:
            result = await db.execute(
                text("""
                    INSERT INTO stages
                        (organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order)
                    VALUES (:organization_id, :tournament_id, :version_id, :name, :stage_type, :stage_order)
                    RETURNING id, tournament_version_id, name, stage_type, stage_order
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(payload.version_id),
                    "name": payload.name,
                    "stage_type": payload.stage_type,
                    "stage_order": payload.stage_order,
                },
            )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="No se pudo crear la fase") from exc
        return dict(result.mappings().one())


@router.get(
    "/{tournament_id}/stages/{stage_id}/teams",
    response_model=StageTeamsResponse,
)
async def list_stage_teams(
    tournament_id: UUID,
    stage_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Teams assigned to one stage/version plus the registered unassigned ones.

    Read-only and organization-scoped: the stage is resolved inside the
    tournament of the caller's organization and every query filters by the
    stage's own version, so assignments from other versions never leak in.
    """

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)

        stage_result = await db.execute(
            text("""
                SELECT s.id, s.tournament_version_id
                FROM stages s
                WHERE s.id = :stage_id
                  AND s.tournament_id = :tournament_id
                  AND s.organization_id = :organization_id
            """),
            {
                "stage_id": str(stage_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        stage = stage_result.mappings().one_or_none()
        if stage is None:
            raise HTTPException(
                status_code=404, detail="Fase no encontrada en el torneo"
            )
        version_id = stage["tournament_version_id"]

        scope = {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
        }
        assigned_result = await db.execute(
            text("""
                SELECT DISTINCT tt.team_id, t.name, t.short_code
                FROM stage_teams st
                JOIN tournament_teams tt
                  ON tt.team_id = st.team_id
                 AND tt.tournament_id = st.tournament_id
                 AND tt.organization_id = st.organization_id
                JOIN teams t
                  ON t.id = tt.team_id
                 AND t.organization_id = tt.organization_id
                WHERE st.organization_id = :organization_id
                  AND st.tournament_id = :tournament_id
                  AND st.tournament_version_id = :version_id
                  AND st.stage_id = :stage_id
                ORDER BY t.name, tt.team_id
            """),
            scope,
        )
        unassigned_result = await db.execute(
            text("""
                SELECT tt.team_id, t.name, t.short_code
                FROM tournament_teams tt
                JOIN teams t
                  ON t.id = tt.team_id
                 AND t.organization_id = tt.organization_id
                WHERE tt.organization_id = :organization_id
                  AND tt.tournament_id = :tournament_id
                  AND tt.status = 'registered'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM stage_teams st
                      WHERE st.organization_id = tt.organization_id
                        AND st.tournament_id = tt.tournament_id
                        AND st.tournament_version_id = :version_id
                        AND st.stage_id = :stage_id
                        AND st.team_id = tt.team_id
                  )
                ORDER BY t.name, tt.team_id
            """),
            scope,
        )

        return {
            "stage_id": stage_id,
            "version_id": version_id,
            "assigned": [
                dict(row) for row in assigned_result.mappings().all()
            ],
            "unassigned": [
                dict(row) for row in unassigned_result.mappings().all()
            ],
        }


def plan_stage_team_assignment(
    existing_ids: set[UUID],
    requested_ids: list[UUID],
) -> tuple[list[UUID], list[UUID]]:
    """Split a validated batch into new and already assigned teams.

    Preserves the request order and never introduces duplicates; the schema
    rejects duplicate ``team_ids`` before this function runs.
    """

    assigned = [team_id for team_id in requested_ids if team_id not in existing_ids]
    already_assigned = [
        team_id for team_id in requested_ids if team_id in existing_ids
    ]
    return assigned, already_assigned


@router.post(
    "/{tournament_id}/stages/{stage_id}/teams",
    response_model=StageTeamAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_stage_teams(
    tournament_id: UUID,
    stage_id: UUID,
    payload: AssignStageTeamsRequest,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Assign registered tournament teams to one stage in a draft version.

    The batch is atomic: either every new team is inserted or none is. The
    stage lock serializes concurrent assignments and publications, and the
    version state is re-read under that lock.
    """

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)

        stage_result = await db.execute(
            text("""
                SELECT s.id, s.tournament_version_id, tv.status AS version_status
                FROM stages s
                JOIN tournament_versions tv
                  ON tv.id = s.tournament_version_id
                 AND tv.tournament_id = s.tournament_id
                 AND tv.organization_id = s.organization_id
                WHERE s.id = :stage_id
                  AND s.tournament_id = :tournament_id
                  AND s.organization_id = :organization_id
            """),
            {
                "stage_id": str(stage_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        stage = stage_result.mappings().one_or_none()
        if stage is None:
            raise HTTPException(
                status_code=404, detail="Fase no encontrada en el torneo"
            )
        # The version check precedes the permission check and the idempotency.
        if stage["version_status"] != "draft":
            raise HTTPException(
                status_code=409, detail="La versión publicada es inmutable"
            )

        await _require_tournament_management(db, context)

        try:
            version_id, locked_status = await lock_stage_and_version(
                db, context.organization_id, tournament_id, stage_id
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="Fase no encontrada en el torneo"
            ) from exc
        if locked_status != "draft":
            raise HTTPException(
                status_code=409, detail="La versión publicada es inmutable"
            )

        team_ids = [str(team_id) for team_id in payload.team_ids]
        registered_result = await db.execute(
            text("""
                SELECT tt.team_id
                FROM tournament_teams tt
                WHERE tt.organization_id = :organization_id
                  AND tt.tournament_id = :tournament_id
                  AND tt.team_id = ANY(CAST(:team_ids AS uuid[]))
                  AND tt.status = 'registered'
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "team_ids": team_ids,
            },
        )
        registered_ids = {
            row["team_id"] for row in registered_result.mappings().all()
        }
        if len(registered_ids) != len(payload.team_ids):
            raise HTTPException(
                status_code=409,
                detail="Uno o más equipos no están registrados en el torneo",
            )

        existing_result = await db.execute(
            text("""
                SELECT DISTINCT team_id
                FROM stage_teams
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND team_id = ANY(CAST(:team_ids AS uuid[]))
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_ids": team_ids,
            },
        )
        existing_ids = {
            row["team_id"] for row in existing_result.mappings().all()
        }

        assigned, already_assigned = plan_stage_team_assignment(
            existing_ids, payload.team_ids
        )

        # The size check runs before any insert and covers every new team of the
        # batch: one team out of range rejects the whole lot (RF-045).
        if assigned:
            await _enforce_roster_size(
                db,
                context.organization_id,
                tournament_id,
                version_id,
                assigned,
            )

        if not assigned:
            response.status_code = status.HTTP_200_OK
        else:
            for team_id in assigned:
                await db.execute(
                    text("""
                        INSERT INTO stage_teams
                            (organization_id, tournament_id, tournament_version_id,
                             stage_id, group_id, team_id)
                        VALUES (:organization_id, :tournament_id, :version_id,
                                :stage_id, :group_id, :team_id)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "version_id": str(version_id),
                        "stage_id": str(stage_id),
                        "group_id": None,
                        "team_id": str(team_id),
                    },
                )
            response.status_code = status.HTTP_201_CREATED

        return {
            "stage_id": stage_id,
            "version_id": version_id,
            "team_ids": payload.team_ids,
            "assigned": assigned,
            "already_assigned": already_assigned,
        }


@router.delete(
    "/{tournament_id}/stages/{stage_id}/teams/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_stage_team(
    tournament_id: UUID,
    stage_id: UUID,
    team_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a registered team from one stage in a draft version.

    Precedence: tournament/stage 404 -> non-draft 409 (even when the team was
    not assigned) -> permission 403 -> non-registered 409 -> matches 409 ->
    standings 409 -> 204 idempotent. Every row of the team in that stage is
    removed; matches, groups, slots and standings are never deleted.
    """

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)

        stage_result = await db.execute(
            text("""
                SELECT s.id, s.tournament_version_id, tv.status AS version_status
                FROM stages s
                JOIN tournament_versions tv
                  ON tv.id = s.tournament_version_id
                 AND tv.tournament_id = s.tournament_id
                 AND tv.organization_id = s.organization_id
                WHERE s.id = :stage_id
                  AND s.tournament_id = :tournament_id
                  AND s.organization_id = :organization_id
            """),
            {
                "stage_id": str(stage_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        stage = stage_result.mappings().one_or_none()
        if stage is None:
            raise HTTPException(
                status_code=404, detail="Fase no encontrada en el torneo"
            )
        # Immutability precedes permission and idempotency: a published or
        # archived version answers 409 even if the team was not assigned.
        if stage["version_status"] != "draft":
            raise HTTPException(
                status_code=409, detail="La versión publicada es inmutable"
            )

        await _require_tournament_management(db, context)

        try:
            version_id, locked_status = await lock_stage_and_version(
                db, context.organization_id, tournament_id, stage_id
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="Fase no encontrada en el torneo"
            ) from exc
        if locked_status != "draft":
            raise HTTPException(
                status_code=409, detail="La versión publicada es inmutable"
            )

        registered_result = await db.execute(
            text("""
                SELECT 1
                FROM tournament_teams
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND team_id = :team_id
                  AND status = 'registered'
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
            },
        )
        if registered_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=409,
                detail="El equipo no está registrado en el torneo",
            )

        match_result = await db.execute(
            text("""
                SELECT 1
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND (
                      home_team_id = :team_id
                      OR away_team_id = :team_id
                  )
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
        if match_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="El equipo tiene partidos en la fase y no se puede retirar",
            )

        standings_result = await db.execute(
            text("""
                SELECT 1
                FROM standings
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND stage_id = :stage_id
                  AND team_id = :team_id
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
        if standings_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="El equipo tiene clasificación en la fase y no se puede retirar",
            )

        # No group filter: every row of the team in this stage/version goes.
        await db.execute(
            text("""
                DELETE FROM stage_teams
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND team_id = :team_id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
