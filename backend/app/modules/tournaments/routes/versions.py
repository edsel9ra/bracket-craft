import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.permissions import require_permission
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.advancement.assignments import record_match_slot_assignments
from app.modules.rules_engine.engine import (
    normalize_rules_config,
    remap_stage_overrides,
    validate_rules_config,
    validate_walkover_score,
)
from app.modules.rules_engine.schemas import UpdateRulesConfigRequest
from app.modules.tournaments.schemas import (
    CreateDraftVersionRequest,
    PublishVersionResponse,
    VersionDetailResponse,
    VersionSummaryResponse,
)

from app.modules.tournaments.access import (
    _ensure_tournament,
    _require_tournament_management,
)

router = APIRouter()


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
    # Version-only exception (plus the tournament row): cloning never locks a
    # stage before the version because the new stages do not exist yet.
    await _ensure_tournament(db, context.organization_id, tournament_id)
    await _require_tournament_management(db, context)

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
            SELECT id, name, stage_type, stage_order, schedule_legs
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
                    (id, organization_id, tournament_id, tournament_version_id, name, stage_type,
                     stage_order, schedule_legs)
                VALUES (:id, :organization_id, :tournament_id, :version_id, :name, :stage_type,
                        :stage_order, :schedule_legs)
            """),
            {
                "id": str(new_stage_id),
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(new_version_id),
                "name": stage["name"],
                "stage_type": stage["stage_type"],
                "stage_order": stage["stage_order"],
                "schedule_legs": stage["schedule_legs"],
            },
        )

    source_rules_config = source["rules_config"]
    if isinstance(source_rules_config, str):
        source_rules_config = json.loads(source_rules_config)
    cloned_rules_config = normalize_rules_config(
        remap_stage_overrides(source_rules_config, stage_map)
    )
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
        await record_match_slot_assignments(db, context.organization_id, match_map[str(match["id"])])

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
    rules_config = normalize_rules_config(payload.rules_config.model_dump(mode="json"))
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        # Version-only exception: there is no phase to lock (see core.locking).
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
        # Spec 024: rechazar cambio a formato no 11v11 si hay formación táctica publicada.
        new_game_format = rules_config.get("game_format", "11v11")
        if new_game_format != "11v11":
            from app.modules.matches.errors import PublishedFormationMustBeUnpublished

            published = await db.execute(
                text("""
                    SELECT 1
                    FROM match_team_lineups mtl
                    JOIN matches m ON m.id = mtl.match_id
                    WHERE mtl.organization_id = :organization_id
                      AND m.tournament_version_id = :version_id
                      AND mtl.is_public = TRUE
                    LIMIT 1
                """),
                {
                    "organization_id": str(context.organization_id),
                    "version_id": str(version_id),
                },
            )
            if published.scalar_one_or_none() is not None:
                raise PublishedFormationMustBeUnpublished()

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


@router.post("/{version_id}/publish", response_model=PublishVersionResponse)
async def publish_version(
    version_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> PublishVersionResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        # Version-only exception: publication never takes a stage lock.
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
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if version["status"] != "draft":
            raise HTTPException(status_code=409, detail="Solo se pueden publicar versiones draft")
        if version["tournament_status"] in {"live", "finished", "archived"}:
            raise HTTPException(status_code=409, detail="No se puede publicar una nueva versión durante o después de la operación")
        try:
            validate_rules_config(version["rules_config"])
            # RF-011: publishing is the only path by which a historical pair
            # could come back; the pair is validated on the persisted draft.
            validate_walkover_score(version["rules_config"])
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
