from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.locking import lock_stage_and_version
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.stage_advancement.origins import (
    MAX_SLOTS,
    MIN_SLOTS,
    SlotOrigin,
    TemplateError,
    classic_template,
    validate_origins,
)
from app.modules.stage_advancement.schemas import (
    ResolutionPreviewResponse,
    SlotOriginsResponse,
    SlotOriginsTemplateResponse,
    SlotOriginsUpdateRequest,
)
from app.modules.stage_advancement.service import (
    build_resolution_preview,
    preview_payload,
    load_declared_origins,
    load_destination_stage,
    load_source_stages,
    origin_payload,
    require_elimination,
    slot_errors_exception,
    stage_is_resolved,
)
from app.modules.tournaments.access import _ensure_tournament, _require_tournament_management
from app.modules.tournaments.routes.matches import _clear_stage_schedule, _persist_bracket_schedule
from app.modules.tournaments.scheduling import (
    build_seeded_double_elimination_bracket,
    build_seeded_single_elimination_bracket,
)

router = APIRouter(prefix="/tournaments", tags=["stage-advancement"])

SLOT_ORIGINS_PATH = "/{tournament_id}/stages/{stage_id}/slot-origins"
RESOLUTION_PATH = "/{tournament_id}/stages/{stage_id}/resolution"


async def _slot_origins_payload(db: AsyncSession, organization_id: UUID, stage) -> dict:
    _, source_stages = await load_source_stages(db, organization_id, stage)
    if stage["version_status"] == "draft":
        state = "editable"
    elif await stage_is_resolved(db, organization_id, stage["id"]):
        state = "resolved"
    else:
        state = "frozen"
    declared = await load_declared_origins(db, organization_id, stage["id"])
    return {
        "stage_id": stage["id"],
        "stage_type": stage["stage_type"],
        "status": state,
        "origins": [origin_payload(seed, origin) for seed, origin in declared],
        "source_stages": source_stages,
    }


async def _lock_draft_destination(db: AsyncSession, context: AuthContext, tournament_id: UUID, stage_id: UUID):
    await _ensure_tournament(db, context.organization_id, tournament_id)
    await _require_tournament_management(db, context)
    try:
        _, version_status = await lock_stage_and_version(db, context.organization_id, tournament_id, stage_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Fase no encontrada") from exc
    if version_status != "draft":
        raise HTTPException(status_code=409, detail="La versión publicada es inmutable")
    stage = await load_destination_stage(db, context.organization_id, tournament_id, stage_id)
    require_elimination(stage)
    return stage


async def _has_matches(db: AsyncSession, organization_id: UUID, stage_id: UUID) -> bool:
    result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM matches WHERE organization_id = :organization_id AND stage_id = :stage_id
            )
        """),
        {"organization_id": str(organization_id), "stage_id": str(stage_id)},
    )
    return bool(result.scalar_one())


@router.get(SLOT_ORIGINS_PATH, response_model=SlotOriginsResponse)
async def get_slot_origins(
    tournament_id: UUID,
    stage_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        stage = await load_destination_stage(db, context.organization_id, tournament_id, stage_id)
        require_elimination(stage)
        return await _slot_origins_payload(db, context.organization_id, stage)


@router.get(f"{SLOT_ORIGINS_PATH}/template", response_model=SlotOriginsTemplateResponse)
async def get_slot_origins_template(
    tournament_id: UUID,
    stage_id: UUID,
    source_stage_id: UUID,
    slots_count: int = Query(ge=MIN_SLOTS, le=MAX_SLOTS),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Plantilla clásica sugerida (RF-001b); no escribe nada."""

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        stage = await load_destination_stage(db, context.organization_id, tournament_id, stage_id)
        require_elimination(stage)
        sources, _ = await load_source_stages(db, context.organization_id, stage)
    source = sources.get(source_stage_id)
    if source is None:
        raise HTTPException(status_code=422, detail={"code": "invalid_source_stage"})
    try:
        origins = classic_template(source, slots_count)
    except TemplateError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code}) from exc
    return {
        "source_stage_id": source_stage_id,
        "slots_count": slots_count,
        "origins": [origin_payload(seed, origin) for seed, origin in enumerate(origins, start=1)],
    }


@router.put(SLOT_ORIGINS_PATH, response_model=SlotOriginsResponse)
async def put_slot_origins(
    tournament_id: UUID,
    stage_id: UUID,
    payload: SlotOriginsUpdateRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Declara los orígenes en el borrador y regenera la llave con plazas vacías (RF-001–RF-003, RF-011)."""

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        stage = await _lock_draft_destination(db, context, tournament_id, stage_id)
        sources, _ = await load_source_stages(db, context.organization_id, stage)
        origins = [SlotOrigin(**item.model_dump()) for item in payload.origins]
        errors = validate_origins(origins, sources)
        if errors:
            raise slot_errors_exception(errors)
        builder = (
            build_seeded_single_elimination_bracket
            if stage["stage_type"] == "single_elimination"
            else build_seeded_double_elimination_bracket
        )
        try:
            bracket = builder(
                len(origins),
                start_date=payload.start_date,
                round_interval_days=payload.round_interval_days,
                match_interval_hours=payload.match_interval_hours,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_slots_count", "message": str(exc)}) from exc
        teams = await db.execute(
            text("SELECT EXISTS (SELECT 1 FROM stage_teams WHERE organization_id = :organization_id AND stage_id = :stage_id)"),
            {"organization_id": str(context.organization_id), "stage_id": str(stage_id)},
        )
        if teams.scalar_one():
            raise HTTPException(
                status_code=409,
                detail="La llave tiene equipos asignados a mano; quítalos antes de declarar orígenes",
            )
        if await _has_matches(db, context.organization_id, stage_id):
            if not payload.replace_existing:
                raise HTTPException(
                    status_code=409,
                    detail="La fase ya tiene partidos; confirma el reemplazo para regenerar la llave",
                )
            await _clear_stage_schedule(
                db, context.organization_id, tournament_id, stage["tournament_version_id"], stage_id
            )
        await _persist_bracket_schedule(
            db, context, tournament_id, stage["tournament_version_id"], stage_id, bracket, slot_origins=origins
        )
        return await _slot_origins_payload(db, context.organization_id, stage)


@router.delete(SLOT_ORIGINS_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot_origins(
    tournament_id: UUID,
    stage_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Quita orígenes y llave del borrador para volver al avance manual (RF-011)."""

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        stage = await _lock_draft_destination(db, context, tournament_id, stage_id)
        if await _has_matches(db, context.organization_id, stage_id):
            await _clear_stage_schedule(
                db, context.organization_id, tournament_id, stage["tournament_version_id"], stage_id
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(f"{RESOLUTION_PATH}/preview", response_model=ResolutionPreviewResponse)
async def get_resolution_preview(
    tournament_id: UUID,
    stage_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Vista previa privada de la resolución en una transacción de solo lectura (RF-004–RF-006, RNF-001)."""

    async with db.begin():
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        stage = await load_destination_stage(db, context.organization_id, tournament_id, stage_id)
        require_elimination(stage)
        if await stage_is_resolved(db, context.organization_id, stage_id):
            raise HTTPException(status_code=409, detail={"code": "already_resolved"})
        preview = await build_resolution_preview(db, context.organization_id, tournament_id, stage)
        return await preview_payload(db, context.organization_id, stage, preview)
