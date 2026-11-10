from collections.abc import Sequence
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.locking import lock_stage_and_version
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.crests.resolver import (
    sign_crest_rows,
)
from app.modules.tournaments.schemas import (
    CreateTournamentTeamRequest,
    BulkTournamentTeamRequest,
    BulkTournamentTeamResponse,
    TournamentTeamCreateResponse,
    TournamentTeamSummaryResponse,
)
from app.modules.tournaments.roster_status import (
    RosterSizeOutOfRange,
    describe_roster_violations,
    roster_rows_for_new_teams,
)

from app.modules.tournaments.access import (
    _ensure_tournament,
    _require_tournament_management,
    _version_roster_limits,
)

router = APIRouter()


async def _enforce_new_team_roster_size(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    teams: Sequence[tuple[UUID, str]],
) -> None:
    """Reject creating teams with a target stage when their roster is out of range.

    A new team has an empty roster, so a minimum above zero rejects the create
    before the first insert: no team, no tournament team and no stage
    assignment is written (RF-045, BX-1). A maximum alone can never be
    exceeded, and without limits no check runs, keeping the current
    behaviour.
    """

    limits = await _version_roster_limits(
        db, organization_id, tournament_id, version_id
    )
    if not limits.has_limits:
        return
    detail = describe_roster_violations(
        roster_rows_for_new_teams(teams), limits
    )
    if detail:
        raise RosterSizeOutOfRange(detail)


@router.get("/{tournament_id}/teams")
async def list_tournament_teams(
    tournament_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TournamentTeamSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        result = await db.execute(
            text("""
                SELECT tt.team_id, t.name, t.short_code, t.logo_url,
                       t.crest_object_key, tt.status, tt.registered_at,
                       COALESCE(
                           ARRAY_AGG(DISTINCT st.stage_id) FILTER (WHERE st.stage_id IS NOT NULL),
                           ARRAY[]::UUID[]
                       ) AS stage_ids
                FROM tournament_teams tt
                JOIN teams t
                  ON t.id = tt.team_id AND t.organization_id = tt.organization_id
                LEFT JOIN stage_teams st
                  ON st.team_id = tt.team_id
                 AND st.tournament_id = tt.tournament_id
                 AND st.organization_id = tt.organization_id
                WHERE tt.tournament_id = :tournament_id
                  AND tt.organization_id = :organization_id
                GROUP BY tt.team_id, t.name, t.short_code, t.logo_url,
                         t.crest_object_key, tt.status, tt.registered_at
                ORDER BY t.name, tt.team_id
                LIMIT :limit OFFSET :offset
            """),
            {
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
                "limit": limit,
                "offset": offset,
            },
        )
        rows = [dict(row) for row in result.mappings().all()]

    # N-2: the read transaction is closed before signing. One batch for the
    # whole listing; a storage failure is the Workspace 503.
    await sign_crest_rows(rows, policy="error")
    return rows


@router.post("/{tournament_id}/teams", response_model=TournamentTeamCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tournament_team(
    tournament_id: UUID,
    payload: CreateTournamentTeamRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TournamentTeamCreateResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)

        stage = None
        if payload.stage_id is not None:
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
                    "stage_id": str(payload.stage_id),
                    "tournament_id": str(tournament_id),
                    "organization_id": str(context.organization_id),
                },
            )
            stage = stage_result.mappings().one_or_none()
            if stage is None:
                raise HTTPException(status_code=404, detail="Fase no encontrada en el torneo")
            if stage["version_status"] != "draft":
                raise HTTPException(status_code=409, detail="La fase publicada es inmutable")
            # phase -> version before reading teams or writing stage_teams.
            try:
                _, locked_status = await lock_stage_and_version(
                    db, context.organization_id, tournament_id, payload.stage_id
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="Fase no encontrada en el torneo") from exc
            if locked_status != "draft":
                raise HTTPException(status_code=409, detail="La fase publicada es inmutable")
        elif payload.group_id is not None:
            raise HTTPException(status_code=422, detail="group_id requiere stage_id")

        existing_code_result = await db.execute(
            text("""
                SELECT 1
                FROM teams
                WHERE organization_id = :organization_id
                  AND LOWER(short_code) = LOWER(:short_code)
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "short_code": payload.short_code,
            },
        )
        if existing_code_result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="El código de equipo ya existe en la organización")

        if payload.group_id is not None:
            group_result = await db.execute(
                text("""
                    SELECT 1
                    FROM groups
                    WHERE id = :group_id
                      AND stage_id = :stage_id
                      AND tournament_id = :tournament_id
                      AND organization_id = :organization_id
                """),
                {
                    "group_id": str(payload.group_id),
                    "stage_id": str(payload.stage_id),
                    "tournament_id": str(tournament_id),
                    "organization_id": str(context.organization_id),
                },
            )
            if group_result.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Grupo no encontrado en la fase")

        team_id = uuid4()
        if stage is not None:
            # Phase -> version -> limits -> insert: the team is enrolled in the
            # target stage, so the same size block applies (RF-045, BX-1).
            await _enforce_new_team_roster_size(
                db,
                context.organization_id,
                tournament_id,
                stage["tournament_version_id"],
                [(team_id, payload.name)],
            )

        try:
            await db.execute(
                text("""
                    INSERT INTO teams (id, organization_id, name, short_code, logo_url)
                    VALUES (:team_id, :organization_id, :name, :short_code, :logo_url)
                """),
                {
                    "team_id": str(team_id),
                    "organization_id": str(context.organization_id),
                    "name": payload.name,
                    "short_code": payload.short_code,
                    "logo_url": payload.logo_url,
                },
            )
            await db.execute(
                text("""
                    INSERT INTO tournament_teams (organization_id, tournament_id, team_id)
                    VALUES (:organization_id, :tournament_id, :team_id)
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "team_id": str(team_id),
                },
            )
            if stage is not None:
                await db.execute(
                    text("""
                        INSERT INTO stage_teams
                            (organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id)
                        VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :group_id, :team_id)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "version_id": str(stage["tournament_version_id"]),
                        "stage_id": str(payload.stage_id),
                        "group_id": str(payload.group_id) if payload.group_id else None,
                        "team_id": str(team_id),
                    },
                )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="El código de equipo ya existe o el registro es inválido") from exc
    return {"team_id": str(team_id), "tournament_id": str(tournament_id)}


@router.post("/{tournament_id}/teams/bulk", response_model=BulkTournamentTeamResponse, status_code=status.HTTP_201_CREATED)
async def create_tournament_teams_bulk(
    tournament_id: UUID,
    payload: BulkTournamentTeamRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BulkTournamentTeamResponse:
    codes = [team.short_code.casefold() for team in payload.teams]
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=422, detail="No se permiten códigos de equipo duplicados en la carga")

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)

        existing_codes_result = await db.execute(
            text("""
                SELECT LOWER(short_code)
                FROM teams
                WHERE organization_id = :organization_id
                  AND LOWER(short_code) = ANY(CAST(:short_codes AS TEXT[]))
            """),
            {
                "organization_id": str(context.organization_id),
                "short_codes": codes,
            },
        )
        existing_codes = {row[0] for row in existing_codes_result.all()}
        if existing_codes:
            raise HTTPException(status_code=409, detail="Uno o más códigos de equipo ya existen en la organización")

        stage = None
        if payload.stage_id is not None:
            stage_result = await db.execute(
                text("""
                    SELECT s.tournament_version_id, tv.status AS version_status
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
                    "stage_id": str(payload.stage_id),
                    "tournament_id": str(tournament_id),
                    "organization_id": str(context.organization_id),
                },
            )
            stage = stage_result.mappings().one_or_none()
            if stage is None:
                raise HTTPException(status_code=404, detail="Fase no encontrada en el torneo")
            if stage["version_status"] != "draft":
                raise HTTPException(status_code=409, detail="La fase publicada es inmutable")
            # phase -> version before reading groups or writing stage_teams.
            try:
                _, locked_status = await lock_stage_and_version(
                    db, context.organization_id, tournament_id, payload.stage_id
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="Fase no encontrada en el torneo") from exc
            if locked_status != "draft":
                raise HTTPException(status_code=409, detail="La fase publicada es inmutable")
            if payload.group_id is not None:
                group_result = await db.execute(
                    text("""
                        SELECT 1
                        FROM groups
                        WHERE id = :group_id
                          AND stage_id = :stage_id
                          AND tournament_id = :tournament_id
                          AND organization_id = :organization_id
                    """),
                    {
                        "group_id": str(payload.group_id),
                        "stage_id": str(payload.stage_id),
                        "tournament_id": str(tournament_id),
                        "organization_id": str(context.organization_id),
                    },
                )
                if group_result.scalar_one_or_none() is None:
                    raise HTTPException(status_code=404, detail="Grupo no encontrado en la fase")
        elif payload.group_id is not None:
            raise HTTPException(status_code=422, detail="group_id requiere stage_id")

        planned = [(uuid4(), team.name) for team in payload.teams]
        if stage is not None:
            # All-or-nothing: every new team is checked before the first insert
            # (RF-045, BX-1).
            await _enforce_new_team_roster_size(
                db,
                context.organization_id,
                tournament_id,
                stage["tournament_version_id"],
                planned,
            )

        created: list[dict[str, str]] = []
        try:
            for (team_id, _), team in zip(planned, payload.teams):
                await db.execute(
                    text("""
                        INSERT INTO teams (id, organization_id, name, short_code, logo_url)
                        VALUES (:team_id, :organization_id, :name, :short_code, :logo_url)
                    """),
                    {
                        "team_id": str(team_id),
                        "organization_id": str(context.organization_id),
                        "name": team.name,
                        "short_code": team.short_code,
                        "logo_url": team.logo_url,
                    },
                )
                await db.execute(
                    text("""
                        INSERT INTO tournament_teams (organization_id, tournament_id, team_id)
                        VALUES (:organization_id, :tournament_id, :team_id)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "team_id": str(team_id),
                    },
                )
                if stage is not None:
                    await db.execute(
                        text("""
                            INSERT INTO stage_teams
                                (organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id)
                            VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :group_id, :team_id)
                        """),
                        {
                            "organization_id": str(context.organization_id),
                            "tournament_id": str(tournament_id),
                            "version_id": str(stage["tournament_version_id"]),
                            "stage_id": str(payload.stage_id),
                            "group_id": str(payload.group_id) if payload.group_id else None,
                            "team_id": str(team_id),
                        },
                    )
                created.append({"team_id": str(team_id), "tournament_id": str(tournament_id)})
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Uno de los códigos de equipo ya existe o el registro es inválido") from exc

    return {"count": len(created), "teams": created}
