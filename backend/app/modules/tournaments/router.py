import json
import logging
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.config import get_settings
from app.core.permissions import require_permission
from app.core.storage import StorageError, get_object_storage
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.rules_engine.engine import remap_stage_overrides, validate_rules_config
from app.modules.rules_engine.schemas import CreateTournamentRequest, UpdateRulesConfigRequest
from app.modules.tournaments.schemas import (
    CreateDraftVersionRequest,
    CreateMatchRequest,
    CreateStageRequest,
    CreateTournamentTeamRequest,
    GenerateSingleEliminationRequest,
    GenerateSingleEliminationResponse,
    BulkTournamentTeamRequest,
    BulkTournamentTeamResponse,
    BulkRosterPlayerResponse,
    CreateRosterPlayerRequest,
    PublicMatchResponse,
    PublicStandingResponse,
    PublicTournamentResponse,
    PublicTournamentSummaryResponse,
    PublishVersionResponse,
    StageSummaryResponse,
    TournamentCreateResponse,
    TournamentMatchSummaryResponse,
    TournamentSummaryResponse,
    TournamentTeamCreateResponse,
    RosterPlayerResponse,
    TournamentTeamSummaryResponse,
    UpdatePhotoConsentRequest,
    VersionDetailResponse,
    VersionSummaryResponse,
)
from app.modules.tournaments.scheduling import (
    build_double_elimination_bracket,
    build_round_robin_schedule,
    build_single_elimination_bracket,
    build_swiss_pairings,
    distribute_groups,
)
from app.modules.tournaments.roster_import import (
    RosterImportError,
    extract_zip_photos,
    parse_roster_csv,
    validate_photo_content,
)


router = APIRouter(prefix="/tournaments", tags=["tournaments"])
logger = logging.getLogger(__name__)


async def _ensure_public_tournament(db: AsyncSession, tournament_id: UUID) -> None:
    result = await db.execute(
        text("SELECT 1 FROM v_public_tournaments WHERE id = :tournament_id"),
        {"tournament_id": str(tournament_id)},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Torneo público no encontrado")


async def _require_tournament_management(db: AsyncSession, context: AuthContext, tournament_id: UUID) -> None:
    try:
        await require_permission(db, context, "MANAGE_TOURNAMENTS", tournament_id=tournament_id)
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


async def _load_draft_stage_context(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    allow_published: bool = False,
):
    result = await db.execute(
        text("""
            SELECT tv.status AS version_status, s.tournament_version_id, s.stage_type
            FROM stages s
            JOIN tournament_versions tv
              ON tv.id = s.tournament_version_id
             AND tv.tournament_id = s.tournament_id
             AND tv.organization_id = s.organization_id
            WHERE s.id = :stage_id
              AND s.tournament_id = :tournament_id
              AND s.organization_id = :organization_id
              AND s.tournament_version_id = :version_id
        """),
        {
            "stage_id": str(stage_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(organization_id),
            "version_id": str(version_id),
        },
    )
    stage = result.mappings().one_or_none()
    if stage is None:
        raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada")
    if stage["version_status"] != "draft" and not (
        allow_published and stage["version_status"] == "published"
    ):
        raise HTTPException(status_code=409, detail="La versión publicada es inmutable")
    return stage


@router.post("", response_model=TournamentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tournament(
    payload: CreateTournamentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TournamentCreateResponse:
    rules_config = payload.rules_config.model_dump(mode="json")
    try:
        validate_rules_config(rules_config)
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


@router.get("/{tournament_id}/versions")
async def list_versions(
    tournament_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[VersionSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        result = await db.execute(
            text("""
                SELECT id, version_number, status, published_at, created_at, rules_config
                FROM tournament_versions
                WHERE tournament_id = :tournament_id
                  AND organization_id = :organization_id
                ORDER BY version_number DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(row) for row in result.mappings().all()]


async def _create_draft_version_record(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: CreateDraftVersionRequest | None,
) -> dict:
    await _ensure_tournament(db, context.organization_id, tournament_id)
    await _require_tournament_management(db, context, tournament_id)

    tournament_result = await db.execute(
        text("""
            SELECT published_version_id, status
            FROM tournaments
            WHERE id = :tournament_id AND organization_id = :organization_id
            FOR UPDATE
        """),
        {
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    tournament = tournament_result.mappings().one_or_none()
    if tournament is None:
        raise HTTPException(status_code=404, detail="Torneo no encontrado")
    if tournament["status"] in {"live", "finished", "archived"}:
        raise HTTPException(status_code=409, detail="No se puede crear una versión sobre un torneo que ya está en operación")
    source_version_id = (payload.source_version_id if payload else None) or tournament["published_version_id"]
    if source_version_id is None:
        raise HTTPException(status_code=409, detail="El torneo no tiene una versión publicada para clonar")

    source_result = await db.execute(
        text("""
            SELECT id, rules_config, phase_config, status
            FROM tournament_versions
            WHERE id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
            FOR SHARE
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    source = source_result.mappings().one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Versión origen no encontrada")
    if source["status"] != "published":
        raise HTTPException(status_code=409, detail="Solo se puede clonar una versión publicada")

    draft_result = await db.execute(
        text("""
            SELECT id
            FROM tournament_versions
            WHERE tournament_id = :tournament_id
              AND organization_id = :organization_id
              AND status = 'draft'
            LIMIT 1
        """),
        {
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    if draft_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="El torneo ya tiene una versión draft")

    number_result = await db.execute(
        text("""
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM tournament_versions
            WHERE tournament_id = :tournament_id
        """),
        {"tournament_id": str(tournament_id)},
    )
    version_number = number_result.scalar_one()
    new_version_id = uuid4()
    await db.execute(
        text("""
            INSERT INTO tournament_versions
                (id, organization_id, tournament_id, version_number, rules_config,
                 phase_config, status, created_by_member_id)
            VALUES (:id, :organization_id, :tournament_id, :version_number, CAST(:rules AS jsonb),
                    CAST(:phase AS jsonb), 'draft', :member_id)
        """),
        {
            "id": str(new_version_id),
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "version_number": version_number,
            "rules": json.dumps(source["rules_config"]),
            "phase": json.dumps(source["phase_config"]),
            "member_id": str(context.organization_user_id),
        },
    )

    stage_result = await db.execute(
        text("""
            SELECT id, name, stage_type, stage_order
            FROM stages
            WHERE tournament_version_id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
            ORDER BY stage_order, id
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    stage_map: dict[str, UUID] = {}
    for stage in stage_result.mappings().all():
        new_stage_id = uuid4()
        stage_map[str(stage["id"])] = new_stage_id
        await db.execute(
            text("""
                INSERT INTO stages
                    (id, organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order)
                VALUES (:id, :organization_id, :tournament_id, :version_id, :name, :stage_type, :stage_order)
            """),
            {
                "id": str(new_stage_id),
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "name": stage["name"],
                "stage_type": stage["stage_type"],
                "stage_order": stage["stage_order"],
            },
        )

    cloned_rules_config = remap_stage_overrides(source["rules_config"], stage_map)
    await db.execute(
        text("""
            UPDATE tournament_versions
            SET rules_config = CAST(:rules AS jsonb)
            WHERE id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "rules": json.dumps(cloned_rules_config),
            "version_id": str(new_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )

    group_result = await db.execute(
        text("""
            SELECT id, stage_id, name
            FROM groups
            WHERE tournament_version_id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    group_map: dict[str, UUID] = {}
    for group in group_result.mappings().all():
        new_group_id = uuid4()
        group_map[str(group["id"])] = new_group_id
        await db.execute(
            text("""
                INSERT INTO groups
                    (id, organization_id, tournament_id, tournament_version_id, stage_id, name)
                VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id, :name)
            """),
            {
                "id": str(new_group_id),
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "stage_id": str(stage_map[str(group["stage_id"])]),
                "name": group["name"],
            },
        )

    slot_result = await db.execute(
        text("""
            SELECT id, stage_id, slot_code, source_type, source_reference
            FROM phase_slots
            WHERE tournament_version_id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    slot_map: dict[str, UUID] = {}
    for slot in slot_result.mappings().all():
        new_slot_id = uuid4()
        slot_map[str(slot["id"])] = new_slot_id
        await db.execute(
            text("""
                INSERT INTO phase_slots
                    (id, organization_id, tournament_id, tournament_version_id, stage_id,
                     slot_code, source_type, source_reference)
                VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                        :slot_code, :source_type, CAST(:source_reference AS jsonb))
            """),
            {
                "id": str(new_slot_id),
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "stage_id": str(stage_map[str(slot["stage_id"])]),
                "slot_code": slot["slot_code"],
                "source_type": slot["source_type"],
                "source_reference": json.dumps(slot["source_reference"]),
            },
        )

    edge_result = await db.execute(
        text("""
            SELECT source_stage_id, target_stage_id, selector_type, selector_config
            FROM stage_edges
            WHERE tournament_version_id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    for edge in edge_result.mappings().all():
        await db.execute(
            text("""
                INSERT INTO stage_edges
                    (organization_id, tournament_id, tournament_version_id,
                     source_stage_id, target_stage_id, selector_type, selector_config)
                VALUES (:organization_id, :tournament_id, :version_id, :source_stage_id,
                        :target_stage_id, :selector_type, CAST(:selector_config AS jsonb))
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "source_stage_id": str(stage_map[str(edge["source_stage_id"])]),
                "target_stage_id": str(stage_map[str(edge["target_stage_id"])]),
                "selector_type": edge["selector_type"],
                "selector_config": json.dumps(edge["selector_config"]),
            },
        )

    stage_team_result = await db.execute(
        text("""
            SELECT stage_id, group_id, team_id
            FROM stage_teams
            WHERE tournament_version_id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    for stage_team in stage_team_result.mappings().all():
        await db.execute(
            text("""
                INSERT INTO stage_teams
                    (organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id)
                VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :group_id, :team_id)
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "stage_id": str(stage_map[str(stage_team["stage_id"])]),
                "group_id": str(group_map[str(stage_team["group_id"])]) if stage_team["group_id"] else None,
                "team_id": str(stage_team["team_id"]),
            },
        )

    match_result = await db.execute(
        text("""
            SELECT id, stage_id, group_id, venue_id, replacement_match_id, matchday,
                   bracket_code, home_slot_id, away_slot_id, home_team_id, away_team_id, match_date
            FROM matches
            WHERE tournament_version_id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
            ORDER BY matchday NULLS LAST, id
        """),
        {
            "version_id": str(source_version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    source_matches = match_result.mappings().all()
    match_map: dict[str, UUID] = {str(row["id"]): uuid4() for row in source_matches}
    for match in source_matches:
        await db.execute(
            text("""
                INSERT INTO matches
                    (id, organization_id, tournament_id, tournament_version_id, stage_id, group_id,
                     venue_id, matchday, bracket_code, home_slot_id, away_slot_id, home_team_id,
                     away_team_id, match_date, status, result_confirmed)
                VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id, :group_id,
                        :venue_id, :matchday, :bracket_code, :home_slot_id, :away_slot_id, :home_team_id,
                        :away_team_id, :match_date, 'scheduled', FALSE)
            """),
            {
                "id": str(match_map[str(match["id"])]),
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "stage_id": str(stage_map[str(match["stage_id"])]),
                "group_id": str(group_map[str(match["group_id"])]) if match["group_id"] else None,
                "venue_id": str(match["venue_id"]) if match["venue_id"] else None,
                "matchday": match["matchday"],
                "bracket_code": match["bracket_code"],
                "home_slot_id": str(slot_map[str(match["home_slot_id"])]) if match["home_slot_id"] else None,
                "away_slot_id": str(slot_map[str(match["away_slot_id"])]) if match["away_slot_id"] else None,
                "home_team_id": str(match["home_team_id"]) if match["home_team_id"] else None,
                "away_team_id": str(match["away_team_id"]) if match["away_team_id"] else None,
                "match_date": match["match_date"],
            },
        )

    for match in source_matches:
        if match["replacement_match_id"] is not None:
            await db.execute(
                text("""
                    UPDATE matches
                    SET replacement_match_id = :replacement_match_id
                    WHERE id = :match_id AND organization_id = :organization_id
                """),
                {
                    "replacement_match_id": str(match_map[str(match["replacement_match_id"])]),
                    "match_id": str(match_map[str(match["id"])]),
                    "organization_id": str(context.organization_id),
                },
            )

    advancement_result = await db.execute(
        text("""
            SELECT source_match_id, target_match_id, outcome, target_side
            FROM advancement_links
            WHERE organization_id = :organization_id
              AND source_match_id IN (
                  SELECT id FROM matches WHERE tournament_version_id = :version_id
              )
        """),
        {
            "organization_id": str(context.organization_id),
            "version_id": str(source_version_id),
        },
    )
    for link in advancement_result.mappings().all():
        await db.execute(
            text("""
                INSERT INTO advancement_links
                    (organization_id, source_match_id, target_match_id, outcome, target_side)
                VALUES (:organization_id, :source_match_id, :target_match_id, :outcome, :target_side)
            """),
            {
                "organization_id": str(context.organization_id),
                "source_match_id": str(match_map[str(link["source_match_id"])]),
                "target_match_id": str(match_map[str(link["target_match_id"])]),
                "outcome": link["outcome"],
                "target_side": link["target_side"],
            },
        )

    await db.execute(
        text("""
            UPDATE tournaments
            SET current_draft_config = CAST(:rules AS jsonb)
            WHERE id = :tournament_id AND organization_id = :organization_id
        """),
        {
            "rules": json.dumps(cloned_rules_config),
            "tournament_id": str(tournament_id),
            "organization_id": str(context.organization_id),
        },
    )
    result = await db.execute(
        text("""
            SELECT id, version_number, status, published_at, created_at, rules_config
            FROM tournament_versions
            WHERE id = :version_id AND organization_id = :organization_id
        """),
        {"version_id": str(new_version_id), "organization_id": str(context.organization_id)},
    )
    return dict(result.mappings().one())


@router.post("/{tournament_id}/versions", response_model=VersionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_draft_version(
    tournament_id: UUID,
    payload: CreateDraftVersionRequest | None = None,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> VersionDetailResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        return await _create_draft_version_record(db, context, tournament_id, payload)


async def _update_version_rules_record(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    version_id: UUID,
    payload: UpdateRulesConfigRequest,
) -> dict:
    rules_config = payload.rules_config.model_dump(mode="json")
    validate_rules_config(rules_config)
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context, tournament_id)
        version_result = await db.execute(
            text("""
                SELECT status
                FROM tournament_versions
                WHERE id = :version_id
                  AND tournament_id = :tournament_id
                  AND organization_id = :organization_id
                FOR UPDATE
            """),
            {
                "version_id": str(version_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        version = version_result.mappings().one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Versión no encontrada")
        if version["status"] != "draft":
            raise HTTPException(status_code=409, detail="La versión publicada es inmutable")
        await db.execute(
            text("""
                UPDATE tournament_versions
                SET rules_config = CAST(:rules AS jsonb)
                WHERE id = :version_id AND organization_id = :organization_id
            """),
            {
                "rules": json.dumps(rules_config),
                "version_id": str(version_id),
                "organization_id": str(context.organization_id),
            },
        )
        await db.execute(
            text("""
                UPDATE tournaments
                SET current_draft_config = CAST(:rules AS jsonb)
                WHERE id = :tournament_id AND organization_id = :organization_id
            """),
            {
                "rules": json.dumps(rules_config),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        result = await db.execute(
            text("""
                SELECT id, version_number, status, published_at, created_at, rules_config
                FROM tournament_versions
                WHERE id = :version_id AND organization_id = :organization_id
            """),
            {"version_id": str(version_id), "organization_id": str(context.organization_id)},
        )
        return dict(result.mappings().one())


@router.patch(
    "/{tournament_id}/versions/{version_id}/rules",
    response_model=VersionDetailResponse,
)
@router.patch(
    "/{tournament_id}/versions/{version_id}",
    response_model=VersionDetailResponse,
)
async def update_version_rules(
    tournament_id: UUID,
    version_id: UUID,
    payload: UpdateRulesConfigRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> VersionDetailResponse:
    return await _update_version_rules_record(db, context, tournament_id, version_id, payload)


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
        await _require_tournament_management(db, context, tournament_id)
        version_result = await db.execute(
            text("""
                SELECT status
                FROM tournament_versions
                WHERE id = :version_id
                  AND tournament_id = :tournament_id
                  AND organization_id = :organization_id
            """),
            {
                "version_id": str(payload.version_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        version_status = version_result.scalar_one_or_none()
        if version_status is None:
            raise HTTPException(status_code=404, detail="Versión no encontrada en el torneo")
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
                SELECT tt.team_id, t.name, t.short_code, t.logo_url, tt.status, tt.registered_at,
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
                GROUP BY tt.team_id, t.name, t.short_code, t.logo_url, tt.status, tt.registered_at
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
        return [dict(row) for row in result.mappings().all()]


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
        await _require_tournament_management(db, context, tournament_id)

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

        try:
            team_result = await db.execute(
                text("""
                    INSERT INTO teams (organization_id, name, short_code, logo_url)
                    VALUES (:organization_id, :name, :short_code, :logo_url)
                    RETURNING id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "name": payload.name,
                    "short_code": payload.short_code,
                    "logo_url": payload.logo_url,
                },
            )
            team_id = team_result.scalar_one()
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
        await _require_tournament_management(db, context, tournament_id)

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

        created: list[dict[str, str]] = []
        try:
            for team in payload.teams:
                team_result = await db.execute(
                    text("""
                        INSERT INTO teams (organization_id, name, short_code, logo_url)
                        VALUES (:organization_id, :name, :short_code, :logo_url)
                        RETURNING id
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "name": team.name,
                        "short_code": team.short_code,
                        "logo_url": team.logo_url,
                    },
                )
                team_id = team_result.scalar_one()
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


async def _create_roster_player_record(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: CreateRosterPlayerRequest,
    settings,
) -> tuple[UUID, UUID]:
    team_result = await db.execute(
        text("""
            SELECT 1
            FROM tournament_teams
            WHERE tournament_id = :tournament_id
              AND team_id = :team_id
              AND organization_id = :organization_id
        """),
        {
            "tournament_id": str(tournament_id),
            "team_id": str(payload.team_id),
            "organization_id": str(context.organization_id),
        },
    )
    if team_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="El equipo no está registrado en el torneo")

    existing_player_result = await db.execute(
        text("""
            SELECT id
            FROM players
            WHERE document_type = :document_type
              AND issuing_country = :issuing_country
              AND national_id_hmac = encode(
                  hmac(CAST(:national_id AS TEXT), CAST(:player_data_key AS TEXT), 'sha256'),
                  'hex'
              )
        """),
        {
            "document_type": payload.document_type,
            "issuing_country": payload.issuing_country,
            "national_id": payload.national_id,
            "player_data_key": settings.player_data_key,
        },
    )
    player_id = existing_player_result.scalar_one_or_none()
    if player_id is None:
        player_result = await db.execute(
            text("""
                INSERT INTO players
                    (first_name, last_name, document_type, national_id_encrypted, national_id_hmac,
                     issuing_country, birth_date)
                VALUES (
                    :first_name,
                    :last_name,
                    :document_type,
                    pgp_sym_encrypt(CAST(:national_id AS TEXT), :player_data_key),
                    encode(hmac(CAST(:national_id AS TEXT), CAST(:player_data_key AS TEXT), 'sha256'), 'hex'),
                    :issuing_country,
                    :birth_date
                )
                RETURNING id
            """),
            {
                "first_name": payload.first_name,
                "last_name": payload.last_name,
                "document_type": payload.document_type,
                "national_id": payload.national_id,
                "player_data_key": settings.player_data_key,
                "issuing_country": payload.issuing_country,
                "birth_date": payload.birth_date,
            },
        )
        player_id = player_result.scalar_one()

    roster_result = await db.execute(
        text("""
            INSERT INTO rosters
                (organization_id, tournament_id, team_id, player_id, dorsal_number, photo_consent,
                 valid_from, eligible_from)
            VALUES (
                :organization_id, :tournament_id, :team_id, :player_id, :dorsal_number, :photo_consent,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id
        """),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(payload.team_id),
            "player_id": str(player_id),
            "dorsal_number": payload.dorsal_number,
            "photo_consent": payload.photo_consent,
        },
    )
    return roster_result.scalar_one(), player_id


async def _resolve_photo_url(photo_object_key: str | None, photo_consent: bool) -> str | None:
    if not photo_consent or not photo_object_key:
        return None
    try:
        return await get_object_storage().signed_url(photo_object_key)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="El almacenamiento de fotos no está disponible") from exc


async def _resolve_roster_photo_urls(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["photo_url"] = await _resolve_photo_url(
            row.pop("photo_object_key", None),
            bool(row["photo_consent"]),
        )
    return rows


async def _load_roster_player(db: AsyncSession, organization_id: UUID, roster_id: UUID) -> dict:
    result = await db.execute(
        text("""
            SELECT r.id AS roster_id, r.player_id, r.team_id, p.first_name, p.last_name,
                   r.dorsal_number, r.photo_object_key, r.photo_consent, r.is_active
            FROM rosters r
            JOIN players p ON p.id = r.player_id
            WHERE r.id = :roster_id AND r.organization_id = :organization_id
        """),
        {"roster_id": str(roster_id), "organization_id": str(organization_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
    return (await _resolve_roster_photo_urls([dict(row)]))[0]


@router.get("/{tournament_id}/rosters", response_model=list[RosterPlayerResponse])
async def list_tournament_rosters(
    tournament_id: UUID,
    team_id: UUID | None = None,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[RosterPlayerResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        result = await db.execute(
            text("""
                SELECT r.id AS roster_id, r.player_id, r.team_id, p.first_name, p.last_name,
                       r.dorsal_number, r.photo_object_key, r.photo_consent, r.is_active
                FROM rosters r
                JOIN players p ON p.id = r.player_id
                WHERE r.tournament_id = :tournament_id
                  AND r.organization_id = :organization_id
                  AND (CAST(:team_id AS UUID) IS NULL OR r.team_id = CAST(:team_id AS UUID))
                ORDER BY r.team_id, r.dorsal_number, p.last_name, p.first_name
                LIMIT :limit OFFSET :offset
            """),
            {
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
                "team_id": str(team_id) if team_id else None,
                "limit": limit,
                "offset": offset,
            },
        )
        players = [dict(row) for row in result.mappings().all()]
    return await _resolve_roster_photo_urls(players)


@router.post("/{tournament_id}/rosters", response_model=RosterPlayerResponse, status_code=status.HTTP_201_CREATED)
async def create_roster_player(
    tournament_id: UUID,
    payload: CreateRosterPlayerRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerResponse:
    settings = get_settings()
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context, tournament_id)
        try:
            roster_id, _ = await _create_roster_player_record(db, context, tournament_id, payload, settings)
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="El documento, dorsal o jugador ya está registrado en el torneo") from exc
        return await _load_roster_player(db, context.organization_id, roster_id)


@router.post("/{tournament_id}/rosters/bulk", response_model=BulkRosterPlayerResponse, status_code=status.HTTP_201_CREATED)
async def create_roster_players_bulk(
    tournament_id: UUID,
    team_id: UUID = Form(...),
    csv_file: UploadFile = File(...),
    photos_zip: UploadFile | None = File(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BulkRosterPlayerResponse:
    settings = get_settings()
    filename = (csv_file.filename or "").lower()
    if not filename.endswith((".csv", ".txt")):
        raise HTTPException(status_code=422, detail="El archivo de plantilla debe ser CSV o TXT")
    csv_raw = await csv_file.read(settings.storage_max_archive_bytes + 1)
    if len(csv_raw) > settings.storage_max_archive_bytes:
        raise HTTPException(status_code=413, detail="El archivo de plantilla supera el tamaño máximo permitido")
    try:
        rows = parse_roster_csv(csv_raw, team_id)
        photos: dict = {}
        if photos_zip is not None:
            zip_raw = await photos_zip.read(settings.storage_max_archive_bytes + 1)
            if len(zip_raw) > settings.storage_max_archive_bytes:
                raise RosterImportError("El archivo ZIP supera el tamaño máximo permitido")
            photos = extract_zip_photos(zip_raw)
    except RosterImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    warnings: list[str] = []
    uploaded_keys: list[str] = []
    created_roster_ids: list[UUID] = []
    players: list[dict] = []
    storage = get_object_storage()
    try:
        async with db.begin():
            await set_rls_context(db, context.organization_id, context.user_id)
            await _ensure_tournament(db, context.organization_id, tournament_id)
            await _require_tournament_management(db, context, tournament_id)
            for row in rows:
                try:
                    roster_id, player_id = await _create_roster_player_record(
                        db, context, tournament_id, row.payload, settings
                    )
                except IntegrityError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Fila {row.line_number}: el documento, dorsal o jugador ya está registrado en el torneo",
                    ) from exc
                if row.photo_filename:
                    photo = photos.get(row.photo_filename.casefold())
                    if photo is None:
                        warnings.append(f"Fila {row.line_number}: no se encontró {row.photo_filename} en el ZIP")
                    else:
                        key = (
                            "private/organizations/"
                            f"{context.organization_id}/tournaments/{tournament_id}/rosters/"
                            f"{roster_id}/{uuid4()}{photo.extension}"
                        )
                        try:
                            await storage.put_bytes(key, photo.content, photo.content_type)
                        except StorageError as exc:
                            raise HTTPException(status_code=503, detail="El almacenamiento de fotos no está disponible") from exc
                        uploaded_keys.append(key)
                        await db.execute(
                            text("SELECT set_roster_photo_object(:roster_id, :photo_object_key)"),
                            {"roster_id": str(roster_id), "photo_object_key": key},
                        )
                created_roster_ids.append(roster_id)
            players = [await _load_roster_player(db, context.organization_id, roster_id) for roster_id in created_roster_ids]
    except Exception:
        for key in uploaded_keys:
            try:
                await storage.delete_key(key)
            except Exception:
                pass
        raise

    return {"count": len(players), "players": players, "warnings": warnings}


@router.post("/{tournament_id}/rosters/{roster_id}/photo", response_model=RosterPlayerResponse)
async def upload_roster_player_photo(
    tournament_id: UUID,
    roster_id: UUID,
    photo: UploadFile = File(...),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerResponse:
    settings = get_settings()
    raw = await photo.read(settings.storage_max_image_bytes + 1)
    try:
        image = validate_photo_content(raw, photo.filename or "player.jpg")
    except RosterImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    storage = get_object_storage()
    key: str | None = None
    old_key: str | None = None
    try:
        async with db.begin():
            await set_rls_context(db, context.organization_id, context.user_id)
            await _ensure_tournament(db, context.organization_id, tournament_id)
            await _require_tournament_management(db, context, tournament_id)
            roster_result = await db.execute(
                text("""
                    SELECT r.id, r.photo_consent, r.photo_object_key
                    FROM rosters r
                    WHERE r.id = :roster_id
                      AND r.tournament_id = :tournament_id
                      AND r.organization_id = :organization_id
                """),
                {
                    "roster_id": str(roster_id),
                    "tournament_id": str(tournament_id),
                    "organization_id": str(context.organization_id),
                },
            )
            roster = roster_result.mappings().one_or_none()
            if roster is None:
                raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
            if not roster["photo_consent"]:
                raise HTTPException(status_code=409, detail="No existe consentimiento para cargar la foto")
            old_key = roster["photo_object_key"]
            key = (
                "private/organizations/"
                f"{context.organization_id}/tournaments/{tournament_id}/rosters/"
                f"{roster_id}/{uuid4()}{image.extension}"
            )
            try:
                await storage.put_bytes(key, image.content, image.content_type)
            except StorageError as exc:
                raise HTTPException(status_code=503, detail="El almacenamiento de fotos no está disponible") from exc
            replacement_result = await db.execute(
                text("SELECT set_roster_photo_object(:roster_id, :photo_object_key)"),
                {"roster_id": str(roster_id), "photo_object_key": key},
            )
            old_key = replacement_result.scalar_one_or_none()
            result = await _load_roster_player(db, context.organization_id, roster_id)
    except Exception:
        if key:
            try:
                await storage.delete_key(key)
            except Exception:
                pass
        raise
    if old_key and old_key != key:
        try:
            await storage.delete_key(old_key)
        except StorageError:
            logger.warning("No se pudo eliminar la foto anterior del roster %s", roster_id, exc_info=True)
    return result


@router.patch("/{tournament_id}/rosters/{roster_id}/photo-consent", response_model=RosterPlayerResponse)
async def update_roster_photo_consent(
    tournament_id: UUID,
    roster_id: UUID,
    payload: UpdatePhotoConsentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerResponse:
    storage = get_object_storage()
    old_key: str | None = None
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context, tournament_id)
        roster_result = await db.execute(
            text("""
                SELECT id
                FROM rosters
                WHERE id = :roster_id
                  AND tournament_id = :tournament_id
                  AND organization_id = :organization_id
            """),
            {
                "roster_id": str(roster_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        if roster_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
        old_key = (await db.execute(
            text("SELECT set_roster_photo_consent(:roster_id, :photo_consent)"),
            {"roster_id": str(roster_id), "photo_consent": payload.photo_consent},
        )).scalar_one_or_none()
        result = await _load_roster_player(db, context.organization_id, roster_id)

    if not payload.photo_consent and old_key:
        try:
            await storage.delete_key(old_key)
        except StorageError:
            logger.warning("No se pudo eliminar la foto sin consentimiento del roster %s", roster_id, exc_info=True)
    return result


async def _clear_stage_schedule(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
) -> None:
    scope = {
        "organization_id": str(organization_id),
        "tournament_id": str(tournament_id),
        "version_id": str(version_id),
        "stage_id": str(stage_id),
    }
    match_result = await db.execute(
        text("""
            SELECT id, status
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
            FOR UPDATE
        """),
        scope,
    )
    matches = match_result.mappings().all()
    if any(match["status"] not in {"scheduled", "cancelled"} for match in matches):
        raise HTTPException(
            status_code=409,
            detail="No se puede regenerar una fase que ya contiene partidos operados",
        )

    external_links_result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM advancement_links al
                WHERE al.organization_id = :organization_id
                  AND al.target_match_id IN (
                      SELECT id
                      FROM matches
                      WHERE organization_id = :organization_id
                        AND tournament_id = :tournament_id
                        AND tournament_version_id = :version_id
                        AND stage_id = :stage_id
                  )
                  AND al.source_match_id NOT IN (
                      SELECT id
                      FROM matches
                      WHERE organization_id = :organization_id
                        AND tournament_id = :tournament_id
                        AND tournament_version_id = :version_id
                        AND stage_id = :stage_id
                  )
            ) AS has_external_links
        """),
        scope,
    )
    if external_links_result.scalar_one():
        raise HTTPException(
            status_code=409,
            detail="La fase tiene avances provenientes de otra fase y no se puede regenerar",
        )

    external_replacements_result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM matches external_match
                WHERE external_match.organization_id = :organization_id
                  AND external_match.replacement_match_id IN (
                      SELECT id
                      FROM matches
                      WHERE organization_id = :organization_id
                        AND tournament_id = :tournament_id
                        AND tournament_version_id = :version_id
                        AND stage_id = :stage_id
                  )
                  AND external_match.id NOT IN (
                      SELECT id
                      FROM matches
                      WHERE organization_id = :organization_id
                        AND tournament_id = :tournament_id
                        AND tournament_version_id = :version_id
                        AND stage_id = :stage_id
                  )
            ) AS has_external_replacements
        """),
        scope,
    )
    if external_replacements_result.scalar_one():
        raise HTTPException(
            status_code=409,
            detail="La fase tiene partidos de reemplazo externos y no se puede regenerar",
        )

    dependencies_result = await db.execute(
        text("""
            SELECT (
                EXISTS (
                    SELECT 1 FROM match_officials
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM match_segments
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM match_rosters
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM match_lineup_snapshots
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM match_segment_team_state
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM match_events
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM player_suspension_serves
                    WHERE organization_id = :organization_id
                      AND match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM player_suspensions
                    WHERE organization_id = :organization_id
                      AND origin_match_id IN (
                          SELECT id FROM matches
                          WHERE organization_id = :organization_id
                            AND tournament_id = :tournament_id
                            AND tournament_version_id = :version_id
                            AND stage_id = :stage_id
                      )
                )
            ) AS has_dependencies
        """),
        scope,
    )
    if dependencies_result.scalar_one():
        raise HTTPException(
            status_code=409,
            detail="No se puede regenerar una fase que ya tiene datos operativos asociados",
        )

    await db.execute(
        text("""
            DELETE FROM advancement_links
            WHERE organization_id = :organization_id
              AND (
                  source_match_id IN (
                      SELECT id FROM matches
                      WHERE organization_id = :organization_id
                        AND tournament_id = :tournament_id
                        AND tournament_version_id = :version_id
                        AND stage_id = :stage_id
                  )
                  OR target_match_id IN (
                      SELECT id FROM matches
                      WHERE organization_id = :organization_id
                        AND tournament_id = :tournament_id
                        AND tournament_version_id = :version_id
                        AND stage_id = :stage_id
                  )
              )
        """),
        scope,
    )
    await db.execute(
        text("""
            UPDATE matches
            SET home_slot_id = NULL,
                away_slot_id = NULL,
                replacement_match_id = NULL
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
        """),
        scope,
    )
    await db.execute(
        text("""
            DELETE FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
        """),
        scope,
    )
    await db.execute(
        text("""
            DELETE FROM phase_slots
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
        """),
        scope,
    )


@router.post(
    "/{tournament_id}/matches/generate",
    response_model=GenerateSingleEliminationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_single_elimination_matches(
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> GenerateSingleEliminationResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context, tournament_id)
        stage = await _load_draft_stage_context(
            db,
            context.organization_id,
            tournament_id,
            payload.version_id,
            payload.stage_id,
        )
        if stage["stage_type"] != "single_elimination":
            raise HTTPException(
                status_code=422,
                detail="La generación automática solo está disponible para fases de eliminación directa",
            )

        team_result = await db.execute(
            text("""
                SELECT st.team_id, st.group_id
                FROM stage_teams st
                JOIN tournament_teams tt
                  ON tt.tournament_id = st.tournament_id
                 AND tt.team_id = st.team_id
                 AND tt.organization_id = st.organization_id
                WHERE st.organization_id = :organization_id
                  AND st.tournament_id = :tournament_id
                  AND st.tournament_version_id = :version_id
                  AND st.stage_id = :stage_id
                  AND tt.status = 'registered'
                ORDER BY st.team_id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
            },
        )
        team_rows = team_result.mappings().all()
        if any(row["group_id"] is not None for row in team_rows):
            raise HTTPException(
                status_code=409,
                detail="Una fase de eliminación directa no puede usar equipos asignados a grupos",
            )
        team_ids = [row["team_id"] for row in team_rows]
        if len(team_ids) < 2:
            raise HTTPException(
                status_code=422,
                detail="Asigna al menos dos equipos registrados a la fase antes de generar la llave",
            )

        existing_result = await db.execute(
            text("""
                SELECT 1
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
            },
        )
        has_existing_matches = existing_result.scalar_one_or_none() is not None
        if has_existing_matches and not payload.replace_existing:
            raise HTTPException(
                status_code=409,
                detail="La fase ya tiene partidos; confirma la regeneración para reemplazar la llave",
            )
        if payload.replace_existing:
            await _clear_stage_schedule(
                db,
                context.organization_id,
                tournament_id,
                payload.version_id,
                payload.stage_id,
            )

        seed = payload.seed if payload.seed is not None else secrets.randbits(63)
        try:
            bracket = build_single_elimination_bracket(
                team_ids,
                seed=seed,
                start_date=payload.start_date,
                round_interval_days=payload.round_interval_days,
                match_interval_hours=payload.match_interval_hours,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        match_ids = {match.code: uuid4() for match in bracket.matches}
        slot_ids: dict[tuple[str, str], UUID] = {}
        try:
            for match in bracket.matches:
                for side, entrant in (("home", match.home), ("away", match.away)):
                    slot_id = uuid4()
                    slot_ids[(match.code, side)] = slot_id
                    if entrant.team_id is not None:
                        source_type = "direct_team"
                        source_reference = {"team_id": str(entrant.team_id)}
                    else:
                        if entrant.source_match_code is None:
                            raise ValueError(f"El slot {match.code}_{side.upper()} no tiene origen")
                        source_type = "match_result"
                        source_reference = {
                            "source_match_id": str(match_ids[entrant.source_match_code]),
                            "outcome": entrant.source_outcome,
                        }
                    await db.execute(
                        text("""
                            INSERT INTO phase_slots
                                (id, organization_id, tournament_id, tournament_version_id, stage_id,
                                 slot_code, source_type, source_reference)
                            VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                                    :slot_code, :source_type, CAST(:source_reference AS jsonb))
                        """),
                        {
                            "id": str(slot_id),
                            "organization_id": str(context.organization_id),
                            "tournament_id": str(tournament_id),
                            "version_id": str(payload.version_id),
                            "stage_id": str(payload.stage_id),
                            "slot_code": f"{match.code}_{side.upper()}",
                            "source_type": source_type,
                            "source_reference": json.dumps(source_reference),
                        },
                    )

            for match in bracket.matches:
                await db.execute(
                    text("""
                        INSERT INTO matches
                            (id, organization_id, tournament_id, tournament_version_id, stage_id,
                             bracket_code, home_slot_id, away_slot_id, home_team_id, away_team_id,
                             matchday, match_date)
                        VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                                :bracket_code, :home_slot_id, :away_slot_id, :home_team_id,
                                :away_team_id, :matchday, :match_date)
                    """),
                    {
                        "id": str(match_ids[match.code]),
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "version_id": str(payload.version_id),
                        "stage_id": str(payload.stage_id),
                        "bracket_code": match.code,
                        "home_slot_id": str(slot_ids[(match.code, "home")]),
                        "away_slot_id": str(slot_ids[(match.code, "away")]),
                        "home_team_id": str(match.home.team_id) if match.home.team_id else None,
                        "away_team_id": str(match.away.team_id) if match.away.team_id else None,
                        "matchday": match.round_number,
                        "match_date": match.match_date,
                    },
                )

            for link in bracket.advancement_links:
                await db.execute(
                    text("""
                        INSERT INTO advancement_links
                            (organization_id, source_match_id, target_match_id, outcome, target_side)
                        VALUES (:organization_id, :source_match_id, :target_match_id, 'winner', :target_side)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "source_match_id": str(match_ids[link.source_match_code]),
                        "target_match_id": str(match_ids[link.target_match_code]),
                        "target_side": link.target_side,
                    },
                )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="No se pudo guardar la llave eliminatoria") from exc

    return GenerateSingleEliminationResponse(
        version_id=payload.version_id,
        stage_id=payload.stage_id,
        stage_type="single_elimination",
        seed=bracket.seed,
        bracket_size=bracket.bracket_size,
        round_count=bracket.round_count,
        match_count=len(bracket.matches),
        bye_count=bracket.bracket_size - len(team_ids),
    )


async def _load_registered_stage_teams(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT st.team_id, st.group_id
            FROM stage_teams st
            JOIN tournament_teams tt
              ON tt.tournament_id = st.tournament_id
             AND tt.team_id = st.team_id
             AND tt.organization_id = st.organization_id
            WHERE st.organization_id = :organization_id
              AND st.tournament_id = :tournament_id
              AND st.tournament_version_id = :version_id
              AND st.stage_id = :stage_id
              AND tt.status = 'registered'
            ORDER BY st.team_id
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _persist_direct_schedule(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    schedules: list[tuple[UUID | None, object]],
) -> int:
    count = 0
    for group_id, schedule in schedules:
        for match in schedule.matches:
            await db.execute(
                text("""
                    INSERT INTO matches
                        (id, organization_id, tournament_id, tournament_version_id, stage_id,
                         group_id, bracket_code, home_team_id, away_team_id, matchday, match_date)
                    VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                            :group_id, :bracket_code, :home_team_id, :away_team_id, :matchday, :match_date)
                """),
                {
                    "id": str(uuid4()),
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                    "stage_id": str(stage_id),
                    "group_id": str(group_id) if group_id else None,
                    "bracket_code": match.code,
                    "home_team_id": str(match.home_team_id),
                    "away_team_id": str(match.away_team_id),
                    "matchday": match.round_number,
                    "match_date": match.match_date,
                },
            )
            count += 1
    return count


async def _persist_bracket_schedule(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    bracket,
) -> int:
    match_ids = {match.code: uuid4() for match in bracket.matches}
    slot_ids: dict[tuple[str, str], UUID] = {}
    try:
        for match in bracket.matches:
            for side, entrant in (("home", match.home), ("away", match.away)):
                slot_id = uuid4()
                slot_ids[(match.code, side)] = slot_id
                if entrant.team_id is not None:
                    source_type = "direct_team"
                    source_reference = {"team_id": str(entrant.team_id)}
                else:
                    if entrant.source_match_code is None:
                        raise ValueError(f"El slot {match.code}_{side.upper()} no tiene origen")
                    source_type = "match_result"
                    source_reference = {
                        "source_match_id": str(match_ids[entrant.source_match_code]),
                        "outcome": entrant.source_outcome,
                        "lane": match.lane,
                    }
                await db.execute(
                    text("""
                        INSERT INTO phase_slots
                            (id, organization_id, tournament_id, tournament_version_id, stage_id,
                             slot_code, source_type, source_reference)
                        VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                                :slot_code, :source_type, CAST(:source_reference AS jsonb))
                    """),
                    {
                        "id": str(slot_id),
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "version_id": str(version_id),
                        "stage_id": str(stage_id),
                        "slot_code": f"{match.code}_{side.upper()}",
                        "source_type": source_type,
                        "source_reference": json.dumps(source_reference),
                    },
                )

        for match in bracket.matches:
            await db.execute(
                text("""
                    INSERT INTO matches
                        (id, organization_id, tournament_id, tournament_version_id, stage_id,
                         bracket_code, home_slot_id, away_slot_id, home_team_id, away_team_id,
                         matchday, match_date)
                    VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                            :bracket_code, :home_slot_id, :away_slot_id, :home_team_id,
                            :away_team_id, :matchday, :match_date)
                """),
                {
                    "id": str(match_ids[match.code]),
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                    "stage_id": str(stage_id),
                    "bracket_code": match.code,
                    "home_slot_id": str(slot_ids[(match.code, "home")]),
                    "away_slot_id": str(slot_ids[(match.code, "away")]),
                    "home_team_id": str(match.home.team_id) if match.home.team_id else None,
                    "away_team_id": str(match.away.team_id) if match.away.team_id else None,
                    "matchday": match.round_number,
                    "match_date": match.match_date,
                },
            )

        if bracket.reset_code:
            await db.execute(
                text("""
                    INSERT INTO matches
                        (id, organization_id, tournament_id, tournament_version_id, stage_id,
                         bracket_code, matchday, match_date, status)
                    VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                            :bracket_code, :matchday, :match_date, 'cancelled')
                """),
                {
                    "id": str(uuid4()),
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(version_id),
                    "stage_id": str(stage_id),
                    "bracket_code": bracket.reset_code,
                    "matchday": bracket.round_count,
                    "match_date": bracket.reset_date,
                },
            )

        for link in bracket.advancement_links:
            await db.execute(
                text("""
                    INSERT INTO advancement_links
                        (organization_id, source_match_id, target_match_id, outcome, target_side)
                    VALUES (:organization_id, :source_match_id, :target_match_id, :outcome, :target_side)
                """),
                {
                    "organization_id": str(context.organization_id),
                    "source_match_id": str(match_ids[link.source_match_code]),
                    "target_match_id": str(match_ids[link.target_match_code]),
                    "outcome": link.outcome,
                    "target_side": link.target_side,
                },
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="No se pudo guardar la llave generada") from exc
    return len(bracket.matches) + (1 if bracket.reset_code else 0)


async def _draw_swiss_schedule(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    team_ids: list[UUID],
    seed: int,
) -> GenerateSingleEliminationResponse:
    if payload.swiss_round > payload.swiss_rounds:
        raise HTTPException(status_code=422, detail="La ronda Swiss no puede superar la cantidad de rondas configurada")
    if payload.swiss_home_target is not None and payload.swiss_away_target is not None:
        if payload.swiss_home_target + payload.swiss_away_target != payload.swiss_rounds:
            raise HTTPException(status_code=422, detail="Los objetivos de local y visitante deben sumar las rondas Swiss")

    match_count_per_round = len(team_ids) // 2
    if payload.swiss_round == 1:
        placeholder_ids: list[UUID] = []
        for round_number in range(1, payload.swiss_rounds + 1):
            for match_number in range(1, match_count_per_round + 1):
                match_id = uuid4()
                if round_number == 1:
                    placeholder_ids.append(match_id)
                await db.execute(
                    text("""
                        INSERT INTO matches
                            (id, organization_id, tournament_id, tournament_version_id, stage_id,
                             bracket_code, matchday, match_date, status)
                        VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                                :bracket_code, :matchday, :match_date, 'cancelled')
                    """),
                    {
                        "id": str(match_id),
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "version_id": str(payload.version_id),
                        "stage_id": str(payload.stage_id),
                        "bracket_code": f"SW{round_number}-{match_number}",
                        "matchday": round_number,
                        "match_date": payload.start_date + timedelta(
                            days=(round_number - 1) * payload.round_interval_days,
                            hours=(match_number - 1) * payload.match_interval_hours,
                        ),
                    },
                )
    else:
        configured_rounds_result = await db.execute(
            text("""
                SELECT MAX(matchday)
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND bracket_code LIKE 'SW%'
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
            },
        )
        configured_rounds = configured_rounds_result.scalar_one_or_none()
        if configured_rounds != payload.swiss_rounds:
            raise HTTPException(status_code=409, detail="La cantidad de rondas Swiss no puede cambiar después de iniciar la fase")
        previous_result = await db.execute(
            text("""
                SELECT status
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND bracket_code LIKE 'SW%'
                  AND matchday < :round_number
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
                "round_number": payload.swiss_round,
            },
        )
        previous_rows = previous_result.mappings().all()
        if not previous_rows or any(row["status"] not in {"finished", "administrative_resolution"} for row in previous_rows):
            raise HTTPException(status_code=409, detail="Completa las rondas Swiss anteriores antes de generar la siguiente")
        placeholder_result = await db.execute(
            text("""
                SELECT id
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND matchday = :round_number
                  AND status = 'cancelled'
                  AND bracket_code LIKE 'SW%'
                ORDER BY bracket_code
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
                "round_number": payload.swiss_round,
            },
        )
        placeholder_ids = [row["id"] for row in placeholder_result.mappings().all()]
        if len(placeholder_ids) != match_count_per_round:
            raise HTTPException(status_code=409, detail="No existen suficientes espacios para la ronda Swiss solicitada")

    history_result = await db.execute(
        text("""
            SELECT home_team_id, away_team_id
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
              AND home_team_id IS NOT NULL
              AND away_team_id IS NOT NULL
              AND status <> 'cancelled'
        """),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(payload.version_id),
            "stage_id": str(payload.stage_id),
        },
    )
    prior_pairs = {
        frozenset((row["home_team_id"], row["away_team_id"]))
        for row in history_result.mappings().all()
    }
    counts_result = await db.execute(
        text("""
            SELECT home_team_id, away_team_id
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
              AND home_team_id IS NOT NULL
              AND away_team_id IS NOT NULL
              AND status <> 'cancelled'
        """),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(payload.version_id),
            "stage_id": str(payload.stage_id),
        },
    )
    home_counts: dict[UUID, int] = {}
    away_counts: dict[UUID, int] = {}
    for row in counts_result.mappings().all():
        home_counts[row["home_team_id"]] = home_counts.get(row["home_team_id"], 0) + 1
        away_counts[row["away_team_id"]] = away_counts.get(row["away_team_id"], 0) + 1

    standings_result = await db.execute(
        text("""
            SELECT team_id, points, won, rank
            FROM standings
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND stage_id = :stage_id
              AND group_id IS NULL
            ORDER BY rank, team_id
        """),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "stage_id": str(payload.stage_id),
        },
    )
    pairings = build_swiss_pairings(
        team_ids,
        standings=[dict(row) for row in standings_result.mappings().all()],
        prior_pairs=prior_pairs,
        seed=seed,
        round_number=payload.swiss_round,
        home_counts=home_counts,
        away_counts=away_counts,
        home_target=payload.swiss_home_target,
        away_target=payload.swiss_away_target,
    )
    active_pairings = [pairing for pairing in pairings if pairing.home_team_id and pairing.away_team_id]
    if len(active_pairings) != len(placeholder_ids):
        raise HTTPException(status_code=409, detail="El sorteo Swiss no coincide con los espacios disponibles")
    for match_id, pairing in zip(placeholder_ids, active_pairings):
        await db.execute(
            text("""
                UPDATE matches
                SET home_team_id = :home_team_id,
                    away_team_id = :away_team_id,
                    status = 'scheduled',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {
                "home_team_id": str(pairing.home_team_id),
                "away_team_id": str(pairing.away_team_id),
                "match_id": str(match_id),
                "organization_id": str(context.organization_id),
            },
        )
    return GenerateSingleEliminationResponse(
        version_id=payload.version_id,
        stage_id=payload.stage_id,
        stage_type="swiss",
        seed=seed,
        round_count=payload.swiss_rounds,
        match_count=len(active_pairings),
        bye_count=sum(1 for pairing in pairings if pairing.bye_team_id),
        round_number=payload.swiss_round,
    )


@router.post(
    "/{tournament_id}/matches/draw",
    response_model=GenerateSingleEliminationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def draw_stage_schedule(
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> GenerateSingleEliminationResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context, tournament_id)
        stage = await _load_draft_stage_context(
            db,
            context.organization_id,
            tournament_id,
            payload.version_id,
            payload.stage_id,
            allow_published=payload.swiss_round > 1,
        )
        team_rows = await _load_registered_stage_teams(
            db,
            context.organization_id,
            tournament_id,
            payload.version_id,
            payload.stage_id,
        )
        team_ids = [row["team_id"] for row in team_rows]
        if len(team_ids) < 2:
            raise HTTPException(status_code=422, detail="Asigna al menos dos equipos registrados a la fase antes del sorteo")
        stage_type = stage["stage_type"]
        if stage["version_status"] != "draft" and stage_type != "swiss":
            raise HTTPException(status_code=409, detail="Solo se pueden generar rondas Swiss en una versión publicada")
        if stage_type != "custom_group" and any(row["group_id"] is not None for row in team_rows):
            raise HTTPException(status_code=409, detail="Esta fase no puede usar equipos asignados a grupos")
        if stage_type == "swiss":
            existing_result = await db.execute(
                text("""
                    SELECT 1 FROM matches
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND tournament_version_id = :version_id
                      AND stage_id = :stage_id
                    LIMIT 1
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(payload.version_id),
                    "stage_id": str(payload.stage_id),
                },
            )
            has_existing_matches = existing_result.scalar_one_or_none() is not None
            if payload.swiss_round > 1:
                if payload.replace_existing:
                    raise HTTPException(status_code=409, detail="No se puede reemplazar una ronda Swiss ya iniciada")
            elif has_existing_matches and not payload.replace_existing:
                raise HTTPException(status_code=409, detail="La fase ya tiene un sorteo; confirma el reemplazo para reiniciarlo")
            if payload.replace_existing:
                await _clear_stage_schedule(
                    db,
                    context.organization_id,
                    tournament_id,
                    payload.version_id,
                    payload.stage_id,
                )
            seed = payload.seed if payload.seed is not None else secrets.randbits(63)
            return await _draw_swiss_schedule(db, context, tournament_id, payload, team_ids, seed)

        existing_result = await db.execute(
            text("""
                SELECT 1 FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                LIMIT 1
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
            },
        )
        if existing_result.scalar_one_or_none() is not None and not payload.replace_existing:
            raise HTTPException(status_code=409, detail="La fase ya tiene partidos; confirma el reemplazo para volver a sortear")
        if payload.replace_existing:
            await _clear_stage_schedule(
                db,
                context.organization_id,
                tournament_id,
                payload.version_id,
                payload.stage_id,
            )

        seed = payload.seed if payload.seed is not None else secrets.randbits(63)
        group_count = 0
        schedules: list[tuple[UUID | None, object]] = []
        if stage_type == "round_robin":
            if any(row["group_id"] is not None for row in team_rows):
                raise HTTPException(status_code=409, detail="Una liga única no puede tener grupos asignados")
            try:
                schedules.append((None, build_round_robin_schedule(
                    team_ids,
                    seed=seed,
                    start_date=payload.start_date,
                    round_interval_days=payload.round_interval_days,
                    match_interval_hours=payload.match_interval_hours,
                    legs=payload.legs,
                )))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif stage_type == "custom_group":
            if payload.group_count is None:
                raise HTTPException(status_code=422, detail="Indica la cantidad de grupos para la fase")
            if not payload.use_group_heads and payload.head_team_ids:
                raise HTTPException(status_code=422, detail="Activa cabezas de grupo antes de seleccionarlas")
            try:
                draw = distribute_groups(
                    team_ids,
                    group_count=payload.group_count,
                    seed=seed,
                    head_team_ids=payload.head_team_ids if payload.use_group_heads else None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            await db.execute(
                text("""
                    UPDATE stage_teams SET group_id = NULL
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND tournament_version_id = :version_id
                      AND stage_id = :stage_id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(payload.version_id),
                    "stage_id": str(payload.stage_id),
                },
            )
            await db.execute(
                text("""
                    DELETE FROM groups
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND tournament_version_id = :version_id
                      AND stage_id = :stage_id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(payload.version_id),
                    "stage_id": str(payload.stage_id),
                },
            )
            group_count = len(draw.groups)
            for group_number, group_team_ids in enumerate(draw.groups, start=1):
                group_id = uuid4()
                await db.execute(
                    text("""
                        INSERT INTO groups
                            (id, organization_id, tournament_id, tournament_version_id, stage_id, name)
                        VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id, :name)
                    """),
                    {
                        "id": str(group_id),
                        "organization_id": str(context.organization_id),
                        "tournament_id": str(tournament_id),
                        "version_id": str(payload.version_id),
                        "stage_id": str(payload.stage_id),
                        "name": f"Grupo {chr(64 + group_number)}" if group_number <= 26 else f"Grupo {group_number}",
                    },
                )
                for team_id in group_team_ids:
                    await db.execute(
                        text("""
                            UPDATE stage_teams SET group_id = :group_id
                            WHERE organization_id = :organization_id
                              AND tournament_id = :tournament_id
                              AND tournament_version_id = :version_id
                              AND stage_id = :stage_id
                              AND team_id = :team_id
                        """),
                        {
                            "group_id": str(group_id),
                            "organization_id": str(context.organization_id),
                            "tournament_id": str(tournament_id),
                            "version_id": str(payload.version_id),
                            "stage_id": str(payload.stage_id),
                            "team_id": str(team_id),
                        },
                    )
                try:
                    schedules.append((group_id, build_round_robin_schedule(
                        list(group_team_ids),
                        seed=seed + group_number,
                        start_date=payload.start_date,
                        round_interval_days=payload.round_interval_days,
                        match_interval_hours=payload.match_interval_hours,
                        legs=payload.legs,
                        code_prefix=f"G{group_number}",
                    )))
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif stage_type in {"single_elimination", "double_elimination"}:
            if any(row["group_id"] is not None for row in team_rows):
                raise HTTPException(status_code=409, detail="Una llave eliminatoria no puede usar equipos asignados a grupos")
            builder = build_single_elimination_bracket if stage_type == "single_elimination" else build_double_elimination_bracket
            try:
                bracket = builder(
                    team_ids,
                    seed=seed,
                    start_date=payload.start_date,
                    round_interval_days=payload.round_interval_days,
                    match_interval_hours=payload.match_interval_hours,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            match_count = await _persist_bracket_schedule(
                db,
                context,
                tournament_id,
                payload.version_id,
                payload.stage_id,
                bracket,
            )
            return GenerateSingleEliminationResponse(
                version_id=payload.version_id,
                stage_id=payload.stage_id,
                stage_type=stage_type,
                seed=seed,
                bracket_size=bracket.bracket_size,
                round_count=bracket.round_count,
                match_count=match_count,
                bye_count=bracket.bracket_size - len(team_ids),
            )
        else:
            raise HTTPException(status_code=422, detail=f"El formato de fase {stage_type} no admite sorteo automático")

        try:
            match_count = await _persist_direct_schedule(
                db,
                context,
                tournament_id,
                payload.version_id,
                payload.stage_id,
                schedules,
            )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="No se pudo guardar el calendario sorteado") from exc
        return GenerateSingleEliminationResponse(
            version_id=payload.version_id,
            stage_id=payload.stage_id,
            stage_type=stage_type,
            seed=seed,
            round_count=max((schedule.round_count for _, schedule in schedules), default=0),
            match_count=match_count,
            bye_count=sum(schedule.bye_count for _, schedule in schedules),
            group_count=group_count,
        )


@router.get("/{tournament_id}/matches")
async def list_tournament_matches(
    tournament_id: UUID,
    version_id: UUID | None = None,
    stage_id: UUID | None = None,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TournamentMatchSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        result = await db.execute(
            text("""
                SELECT m.id, m.tournament_version_id, m.stage_id, m.group_id, m.bracket_code, m.matchday,
                       m.match_date, m.home_team_id, home_team.name AS home_team_name,
                       m.away_team_id, away_team.name AS away_team_name, m.status,
                       m.home_score, m.away_score, m.winner_team_id
                FROM matches m
                LEFT JOIN teams home_team
                  ON home_team.id = m.home_team_id AND home_team.organization_id = m.organization_id
                LEFT JOIN teams away_team
                  ON away_team.id = m.away_team_id AND away_team.organization_id = m.organization_id
                WHERE m.tournament_id = :tournament_id
                  AND m.organization_id = :organization_id
                  AND (CAST(:version_id AS UUID) IS NULL OR m.tournament_version_id = CAST(:version_id AS UUID))
                  AND (CAST(:stage_id AS UUID) IS NULL OR m.stage_id = CAST(:stage_id AS UUID))
                ORDER BY m.match_date NULLS LAST, m.matchday NULLS LAST, m.id
                LIMIT :limit OFFSET :offset
            """),
            {
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
                "version_id": str(version_id) if version_id else None,
                "stage_id": str(stage_id) if stage_id else None,
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(row) for row in result.mappings().all()]


@router.post("/{tournament_id}/matches", response_model=TournamentMatchSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_match(
    tournament_id: UUID,
    payload: CreateMatchRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TournamentMatchSummaryResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context, tournament_id)
        await _load_draft_stage_context(
            db,
            context.organization_id,
            tournament_id,
            payload.version_id,
            payload.stage_id,
        )
        if payload.home_team_id is not None and payload.home_team_id == payload.away_team_id:
            raise HTTPException(status_code=422, detail="Un partido no puede enfrentar al mismo equipo")
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

        for team_id in (payload.home_team_id, payload.away_team_id):
            if team_id is None:
                continue
            team_result = await db.execute(
                text("""
                    SELECT 1
                    FROM tournament_teams
                    WHERE tournament_id = :tournament_id
                      AND team_id = :team_id
                      AND organization_id = :organization_id
                """),
                {
                    "tournament_id": str(tournament_id),
                    "team_id": str(team_id),
                    "organization_id": str(context.organization_id),
                },
            )
            if team_result.scalar_one_or_none() is None:
                raise HTTPException(status_code=409, detail="El equipo no está registrado en el torneo")
            stage_team_result = await db.execute(
                text("""
                    SELECT 1
                    FROM stage_teams
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND tournament_version_id = :version_id
                      AND stage_id = :stage_id
                      AND team_id = :team_id
                      AND group_id IS NOT DISTINCT FROM CAST(:group_id AS UUID)
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(payload.version_id),
                    "stage_id": str(payload.stage_id),
                    "team_id": str(team_id),
                    "group_id": str(payload.group_id) if payload.group_id else None,
                },
            )
            if stage_team_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=409,
                    detail="El equipo no está asignado a la fase y grupo indicados",
                )

        result = await db.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id, group_id,
                     home_team_id, away_team_id, matchday, match_date)
                VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :group_id,
                        :home_team_id, :away_team_id, :matchday, :match_date)
                RETURNING id, tournament_version_id, stage_id, group_id, bracket_code, home_team_id, away_team_id,
                          matchday, match_date, status
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
                "group_id": str(payload.group_id) if payload.group_id else None,
                "home_team_id": str(payload.home_team_id) if payload.home_team_id else None,
                "away_team_id": str(payload.away_team_id) if payload.away_team_id else None,
                "matchday": payload.matchday,
                "match_date": payload.match_date,
            },
        )
    return dict(result.mappings().one())


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


@router.post("/{version_id}/publish", response_model=PublishVersionResponse)
async def publish_version(
    version_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> PublishVersionResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        result = await db.execute(
            text("""
            SELECT tv.id, tv.tournament_id, tv.status, tv.rules_config,
                   t.status AS tournament_status, t.published_version_id
            FROM tournament_versions tv
            JOIN tournaments t
              ON t.id = tv.tournament_id
             AND t.organization_id = tv.organization_id
            WHERE tv.id = :version_id AND tv.organization_id = :organization_id
            FOR UPDATE
            """),
            {"version_id": str(version_id), "organization_id": str(context.organization_id)},
        )
        version = result.mappings().one_or_none()
        if version is None:
            raise HTTPException(status_code=404, detail="Versión no encontrada")
        try:
            await require_permission(
                db,
                context,
                "MANAGE_TOURNAMENTS",
                tournament_id=version["tournament_id"],
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if version["status"] != "draft":
            raise HTTPException(status_code=409, detail="Solo se pueden publicar versiones draft")
        if version["tournament_status"] in {"live", "finished", "archived"}:
            raise HTTPException(status_code=409, detail="No se puede publicar una nueva versión durante o después de la operación")
        try:
            validate_rules_config(version["rules_config"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        readiness_result = await db.execute(
            text("""
                SELECT
                    (SELECT COUNT(*) FROM stages
                     WHERE tournament_version_id = :version_id
                       AND tournament_id = :tournament_id
                       AND organization_id = :organization_id) AS stage_count,
                    (SELECT COUNT(*) FROM tournament_teams
                     WHERE tournament_id = :tournament_id
                       AND organization_id = :organization_id
                       AND status = 'registered') AS team_count,
                    (SELECT COUNT(*) FROM stage_teams
                     WHERE tournament_version_id = :version_id
                       AND tournament_id = :tournament_id
                       AND organization_id = :organization_id) AS stage_team_count,
                    (SELECT COUNT(*) FROM matches
                     WHERE tournament_version_id = :version_id
                       AND tournament_id = :tournament_id
                       AND organization_id = :organization_id) AS match_count
            """),
            {
                "version_id": str(version_id),
                "tournament_id": str(version["tournament_id"]),
                "organization_id": str(context.organization_id),
            },
        )
        readiness = readiness_result.mappings().one()
        if readiness["stage_count"] < 1:
            raise HTTPException(status_code=422, detail="La versión necesita al menos una fase")
        if readiness["team_count"] < 2:
            raise HTTPException(status_code=422, detail="La versión necesita al menos dos equipos registrados")
        if readiness["stage_team_count"] < 2:
            raise HTTPException(status_code=422, detail="Asigna al menos dos equipos a una fase antes de publicar")
        if readiness["match_count"] < 1:
            raise HTTPException(status_code=422, detail="La versión necesita al menos un partido programado")

        if version["published_version_id"] is not None:
            await db.execute(
                text("""
                    UPDATE tournament_versions
                    SET status = 'archived'
                    WHERE id = :published_version_id
                      AND tournament_id = :tournament_id
                      AND organization_id = :organization_id
                      AND status = 'published'
                """),
                {
                    "published_version_id": str(version["published_version_id"]),
                    "tournament_id": str(version["tournament_id"]),
                    "organization_id": str(context.organization_id),
                },
            )

        await db.execute(
            text("""
                UPDATE tournament_versions
                SET status = 'published', published_at = CURRENT_TIMESTAMP
                WHERE id = :version_id
            """),
            {"version_id": str(version_id)},
        )
        await db.execute(
            text("""
                UPDATE tournaments
                SET status = 'published', published_version_id = :version_id
                WHERE id = :tournament_id AND organization_id = :organization_id
            """),
            {
                "version_id": str(version_id),
                "tournament_id": str(version["tournament_id"]),
                "organization_id": str(context.organization_id),
            },
        )

    return {"version_id": str(version_id), "status": "published"}


@router.get("/public", response_model=list[PublicTournamentSummaryResponse])
async def list_public_tournaments(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[PublicTournamentSummaryResponse]:
    result = await db.execute(
        text("""
            SELECT id, name, season, start_date, status
            FROM v_public_tournaments
            ORDER BY start_date DESC, id
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    )
    return [dict(row) for row in result.mappings().all()]


@router.get("/public/{tournament_id}", response_model=PublicTournamentResponse)
async def public_tournament(tournament_id: UUID, db: AsyncSession = Depends(get_db)) -> PublicTournamentResponse:
    result = await db.execute(
        text("""
            SELECT id, name, season, start_date, status
            FROM v_public_tournaments
            WHERE id = :tournament_id
        """),
        {"tournament_id": str(tournament_id)},
    )
    tournament = result.mappings().one_or_none()
    if tournament is None:
        raise HTTPException(status_code=404, detail="Torneo público no encontrado")
    stages_result = await db.execute(
        text("""
            SELECT id, name, stage_type, stage_order
            FROM v_public_stages
            WHERE tournament_id = :tournament_id
            ORDER BY stage_order, id
        """),
        {"tournament_id": str(tournament_id)},
    )
    return {
        **dict(tournament),
        "stages": [dict(stage) for stage in stages_result.mappings().all()],
    }


@router.get("/public/{tournament_id}/standings")
async def public_standings(
    tournament_id: UUID,
    stage_id: UUID | None = None,
    group_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PublicStandingResponse]:
    await _ensure_public_tournament(db, tournament_id)
    result = await db.execute(
        text("""
            SELECT tournament_id, stage_id, stage_name, stage_order, group_id, group_name,
                   team_id, team_name, short_code, played, won, drawn, lost,
                   goals_for, goals_against, goal_difference, points, fair_play_points,
                   rank, calculated_at
            FROM v_public_standings
            WHERE tournament_id = :tournament_id
              AND (CAST(:stage_id AS UUID) IS NULL OR stage_id = CAST(:stage_id AS UUID))
              AND (CAST(:group_id AS UUID) IS NULL OR group_id = CAST(:group_id AS UUID))
             ORDER BY stage_order, group_name NULLS FIRST, rank, team_id
             LIMIT :limit OFFSET :offset
        """),
        {
            "tournament_id": str(tournament_id),
            "stage_id": str(stage_id) if stage_id else None,
            "group_id": str(group_id) if group_id else None,
            "limit": limit,
            "offset": offset,
        },
    )
    return [dict(row) for row in result.mappings().all()]


@router.get("/public/{tournament_id}/matches")
async def public_matches(
    tournament_id: UUID,
    stage_id: UUID | None = None,
    group_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PublicMatchResponse]:
    await _ensure_public_tournament(db, tournament_id)
    result = await db.execute(
        text("""
            SELECT id, tournament_id, stage_id, stage_name, stage_order, group_id, group_name,
                   bracket_code, matchday, match_date, home_team_id, home_team_name, home_team_short_code,
                   away_team_id, away_team_name, away_team_short_code, home_score_regular,
                   away_score_regular, home_score, away_score, home_penalties, away_penalties,
                   winner_team_id, status, resolution_type
            FROM v_public_matches
            WHERE tournament_id = :tournament_id
              AND (CAST(:stage_id AS UUID) IS NULL OR stage_id = CAST(:stage_id AS UUID))
              AND (CAST(:group_id AS UUID) IS NULL OR group_id = CAST(:group_id AS UUID))
              ORDER BY stage_order, stage_id, matchday NULLS LAST, bracket_code NULLS LAST,
                       match_date NULLS LAST, id
             LIMIT :limit OFFSET :offset
        """),
        {
            "tournament_id": str(tournament_id),
            "stage_id": str(stage_id) if stage_id else None,
            "group_id": str(group_id) if group_id else None,
            "limit": limit,
            "offset": offset,
        },
    )
    matches = [dict(row) for row in result.mappings().all()]
    if not matches:
        return []

    match_ids = [str(match["id"]) for match in matches]
    lineup_result = await db.execute(
        text("""
            SELECT match_id, team_id, team_name, side, formation_code, player_id,
                   first_name, last_name, dorsal_number, role, position_slot, photo_url
            FROM v_public_match_lineups
            WHERE tournament_id = :tournament_id
              AND match_id = ANY(CAST(:match_ids AS UUID[]))
            ORDER BY match_id, side,
                     CASE WHEN role = 'starter' THEN 0 ELSE 1 END,
                     dorsal_number NULLS LAST, last_name, first_name
        """),
        {"tournament_id": str(tournament_id), "match_ids": match_ids},
    )

    lineups_by_match: dict[str, dict[str, dict[str, object]]] = {}
    for row in lineup_result.mappings().all():
        match_key = str(row["match_id"])
        side = str(row["side"])
        match_lineups = lineups_by_match.setdefault(match_key, {})
        team_lineup = match_lineups.setdefault(
            side,
            {
                "team_id": row["team_id"],
                "team_name": row["team_name"],
                "formation_code": row["formation_code"],
                "starters": [],
                "substitutes": [],
            },
        )
        player = {
            "player_id": row["player_id"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "dorsal_number": row["dorsal_number"],
            "role": row["role"],
            "position_slot": row["position_slot"],
            "photo_url": await _resolve_photo_url(row["photo_url"], bool(row["photo_url"])),
        }
        bucket = "starters" if row["role"] == "starter" else "substitutes"
        team_lineup[bucket].append(player)  # type: ignore[union-attr]

    for match in matches:
        match_lineups = lineups_by_match.get(str(match["id"]))
        if match_lineups:
            match["lineup"] = {
                "home": match_lineups.get("home"),
                "away": match_lineups.get("away"),
            }

    return matches
