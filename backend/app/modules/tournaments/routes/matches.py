import json
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.locking import lock_stage_and_version
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.advancement.assignments import record_match_slot_assignments
from app.modules.tournaments.pairings import (
    count_pair_meetings,
    max_meetings_per_pair,
    pair_limit_detail,
)
from app.modules.tournaments.schemas import (
    CreateMatchRequest,
    GenerateSingleEliminationRequest,
    GenerateSingleEliminationResponse,
    TournamentMatchSummaryResponse,
)
from app.modules.tournaments.scheduling import (
    MAX_SWISS_TEAMS,
    SwissPairing,
    SwissPairingFailure,
    SwissPairingTimeout,
    build_double_elimination_bracket,
    build_round_robin_schedule,
    build_single_elimination_bracket,
    distribute_groups,
    run_swiss_pairing,
)

from app.modules.tournaments.access import (
    _ensure_tournament,
    _require_tournament_management,
)

router = APIRouter()

# Conserva el nombre del logger tras dividir el router.
logger = logging.getLogger("app.modules.tournaments.router")

SWISS_STATE_CHANGED_DETAIL = "el estado de la fase cambió durante el sorteo; vuelve a intentarlo"


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
            SELECT tv.status AS version_status, s.tournament_version_id, s.stage_type,
                   s.name AS stage_name, s.schedule_legs
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
            ORDER BY id
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
        await _require_tournament_management(db, context)
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
        # phase -> version before reading stage_teams or locking matches.
        try:
            locked_version_id, locked_status = await lock_stage_and_version(
                db, context.organization_id, tournament_id, payload.stage_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada") from exc
        if locked_version_id != payload.version_id:
            raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada")
        if locked_status != "draft":
            raise HTTPException(status_code=409, detail="La versión publicada es inmutable")

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
                await record_match_slot_assignments(db, context.organization_id, match_ids[match.code])

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
            match_id = uuid4()
            await db.execute(
                text("""
                    INSERT INTO matches
                        (id, organization_id, tournament_id, tournament_version_id, stage_id,
                         group_id, bracket_code, home_team_id, away_team_id, matchday, match_date)
                    VALUES (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                            :group_id, :bracket_code, :home_team_id, :away_team_id, :matchday, :match_date)
                """),
                {
                    "id": str(match_id),
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
            await record_match_slot_assignments(db, context.organization_id, match_id)
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
            await record_match_slot_assignments(db, context.organization_id, match_ids[match.code])

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


@dataclass(frozen=True)
class SwissDrawData:
    """Inputs of the Swiss draw, loaded entirely inside the read transaction."""

    seed: int
    match_count_per_round: int
    placeholder_ids: tuple[UUID, ...]
    standings: tuple[dict, ...]
    prior_pairs: frozenset[frozenset[UUID]]
    home_counts: dict[UUID, int]
    away_counts: dict[UUID, int]
    replace_existing: bool
    existing_match_ids: tuple[UUID, ...] = ()
    previous_match_ids: tuple[UUID, ...] = ()


async def _load_swiss_draw_data(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    team_ids: list[UUID],
    seed: int,
    *,
    replace_existing: bool,
    existing_match_ids: tuple[UUID, ...],
) -> SwissDrawData:
    """Read every input of a Swiss round; this function never writes."""

    if payload.swiss_round > payload.swiss_rounds:
        raise HTTPException(status_code=422, detail="La ronda Swiss no puede superar la cantidad de rondas configurada")
    if payload.swiss_home_target is not None and payload.swiss_away_target is not None:
        if payload.swiss_home_target + payload.swiss_away_target != payload.swiss_rounds:
            raise HTTPException(status_code=422, detail="Los objetivos de local y visitante deben sumar las rondas Swiss")

    match_count_per_round = len(team_ids) // 2
    placeholder_ids: tuple[UUID, ...] = ()
    previous_match_ids: tuple[UUID, ...] = ()
    if payload.swiss_round == 1:
        # Placeholders are only materialised by the write transaction.
        placeholder_ids = tuple(uuid4() for _ in range(match_count_per_round))
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
                SELECT id, status
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                  AND bracket_code LIKE 'SW%'
                  AND matchday < :round_number
                ORDER BY id
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
        previous_match_ids = tuple(row["id"] for row in previous_rows)
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
                ORDER BY id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
                "round_number": payload.swiss_round,
            },
        )
        placeholder_ids = tuple(row["id"] for row in placeholder_result.mappings().all())
        if len(placeholder_ids) != match_count_per_round:
            raise HTTPException(status_code=409, detail="No existen suficientes espacios para la ronda Swiss solicitada")

    if replace_existing:
        # The write transaction clears the stage before inserting the new
        # schedule, so the calculation must see the same (empty) history it saw
        # before T005, when the clear happened before the reads.
        prior_pairs: frozenset[frozenset[UUID]] = frozenset()
        home_counts: dict[UUID, int] = {}
        away_counts: dict[UUID, int] = {}
    else:
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
        prior_pairs = frozenset(
            frozenset((row["home_team_id"], row["away_team_id"]))
            for row in history_result.mappings().all()
        )
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
        home_counts = {}
        away_counts = {}
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
    return SwissDrawData(
        seed=seed,
        match_count_per_round=match_count_per_round,
        placeholder_ids=placeholder_ids,
        standings=tuple(dict(row) for row in standings_result.mappings().all()),
        prior_pairs=prior_pairs,
        home_counts=home_counts,
        away_counts=away_counts,
        replace_existing=replace_existing,
        existing_match_ids=existing_match_ids,
        previous_match_ids=previous_match_ids,
    )


async def _revalidate_swiss_draw_state(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    swiss_draw: SwissDrawData,
) -> None:
    """Lock and re-check the stage state inside the write transaction (T006).

    Runs after ``set_rls_context`` and before any write: if the stage changed
    between the read and the calculation, nothing is written and the operator
    gets a 409 that can be retried.
    """

    scope = {
        "organization_id": str(context.organization_id),
        "tournament_id": str(tournament_id),
        "version_id": str(payload.version_id),
        "stage_id": str(payload.stage_id),
    }
    if payload.swiss_round == 1:
        existing_result = await db.execute(
            text("""
                SELECT id
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                ORDER BY id
                FOR UPDATE
            """),
            scope,
        )
        current_ids = tuple(row["id"] for row in existing_result.mappings().all())
        if current_ids != swiss_draw.existing_match_ids:
            raise HTTPException(status_code=409, detail=SWISS_STATE_CHANGED_DETAIL)
        return

    scope_with_round = {**scope, "round_number": payload.swiss_round}
    previous_result = await db.execute(
        text("""
            SELECT id, status
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
              AND bracket_code LIKE 'SW%'
              AND matchday < :round_number
            ORDER BY id
            FOR UPDATE
        """),
        scope_with_round,
    )
    previous_rows = previous_result.mappings().all()
    previous_ids = tuple(row["id"] for row in previous_rows)
    previous_finished = all(
        row["status"] in {"finished", "administrative_resolution"}
        for row in previous_rows
    )
    if previous_ids != swiss_draw.previous_match_ids or not previous_finished:
        raise HTTPException(status_code=409, detail=SWISS_STATE_CHANGED_DETAIL)

    placeholder_result = await db.execute(
        text("""
            SELECT id, status
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
              AND matchday = :round_number
              AND bracket_code LIKE 'SW%'
            ORDER BY id
            FOR UPDATE
        """),
        scope_with_round,
    )
    placeholder_rows = placeholder_result.mappings().all()
    placeholder_ids = tuple(row["id"] for row in placeholder_rows)
    placeholders_cancelled = all(row["status"] == "cancelled" for row in placeholder_rows)
    if placeholder_ids != swiss_draw.placeholder_ids or not placeholders_cancelled:
        raise HTTPException(status_code=409, detail=SWISS_STATE_CHANGED_DETAIL)


async def _calculate_swiss_pairings(
    swiss_draw: SwissDrawData,
    team_ids: list[UUID],
    payload: GenerateSingleEliminationRequest,
) -> tuple[SwissPairing, ...]:
    """Run the pure calculation off-thread and map its failures to 409."""

    try:
        return await run_swiss_pairing(
            team_ids,
            standings=list(swiss_draw.standings),
            prior_pairs=set(swiss_draw.prior_pairs),
            seed=swiss_draw.seed,
            round_number=payload.swiss_round,
            home_counts=swiss_draw.home_counts,
            away_counts=swiss_draw.away_counts,
            home_target=payload.swiss_home_target,
            away_target=payload.swiss_away_target,
        )
    except SwissPairingTimeout as exc:
        logger.error("Sorteo Swiss: tiempo máximo de cálculo excedido")
        raise HTTPException(status_code=409, detail="tiempo máximo de cálculo del sorteo excedido") from exc
    except SwissPairingFailure as exc:
        if exc.reason == "budget_exhausted":
            logger.warning("Sorteo Swiss: presupuesto de emparejamiento agotado (%s evaluaciones)", exc.evaluations)
            raise HTTPException(status_code=409, detail="presupuesto de emparejamiento agotado") from exc
        logger.warning("Sorteo Swiss: no existe un sorteo válido sin repetir rivales (%s evaluaciones)", exc.evaluations)
        raise HTTPException(status_code=409, detail="no existe un sorteo válido sin repetir rivales") from exc


async def _write_swiss_schedule(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    swiss_draw: SwissDrawData,
    active_pairings: list[SwissPairing],
) -> None:
    """Materialise the round placeholders and its pairings in one transaction."""

    if payload.swiss_round == 1:
        for round_number in range(1, payload.swiss_rounds + 1):
            for match_number in range(1, swiss_draw.match_count_per_round + 1):
                if round_number == 1:
                    match_id = swiss_draw.placeholder_ids[match_number - 1]
                else:
                    match_id = uuid4()
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
    for match_id, pairing in zip(swiss_draw.placeholder_ids, active_pairings, strict=True):
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
        await record_match_slot_assignments(db, context.organization_id, match_id)


async def _draw_non_swiss_schedule(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: GenerateSingleEliminationRequest,
    stage_type: str,
    team_rows: list[dict],
    team_ids: list[UUID],
) -> GenerateSingleEliminationResponse:
    """Existing draw flow for round robin, groups and elimination brackets."""

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

    # The league format is persisted with the generated calendar so the manual
    # pairing limit can read it later. Elimination brackets keep the default
    # (one leg) and Swiss has no legs at all (RF-009).
    if stage_type in {"round_robin", "custom_group"}:
        await db.execute(
            text("""
                UPDATE stages
                SET schedule_legs = :schedule_legs
                WHERE id = :stage_id
                  AND organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
            """),
            {
                "schedule_legs": payload.legs,
                "stage_id": str(payload.stage_id),
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
            },
        )
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
    swiss_draw: SwissDrawData | None = None
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        stage = await _load_draft_stage_context(
            db,
            context.organization_id,
            tournament_id,
            payload.version_id,
            payload.stage_id,
            allow_published=payload.swiss_round > 1,
        )
        # phase -> version before reading stage_teams and locking matches. Swiss
        # keeps its read transaction lock-free and re-locks in the write
        # transaction, after the calculation.
        stage_type = stage["stage_type"]
        if stage_type != "swiss":
            try:
                locked_version_id, locked_status = await lock_stage_and_version(
                    db, context.organization_id, tournament_id, payload.stage_id
                )
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada") from exc
            if locked_version_id != payload.version_id:
                raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada")
            if locked_status != "draft":
                raise HTTPException(status_code=409, detail="La versión publicada es inmutable")
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
        if stage["version_status"] != "draft" and stage_type != "swiss":
            raise HTTPException(status_code=409, detail="Solo se pueden generar rondas Swiss en una versión publicada")
        if stage_type != "custom_group" and any(row["group_id"] is not None for row in team_rows):
            raise HTTPException(status_code=409, detail="Esta fase no puede usar equipos asignados a grupos")
        if stage_type != "swiss":
            return await _draw_non_swiss_schedule(
                db, context, tournament_id, payload, stage_type, team_rows, team_ids
            )

        # The cap uses the stage team set loaded above and runs before any write
        # and before any work is sent to the dedicated executor.
        if len(team_ids) > MAX_SWISS_TEAMS:
            raise HTTPException(
                status_code=422,
                detail=f"La fase Swiss admite como máximo {MAX_SWISS_TEAMS} equipos",
            )
        existing_result = await db.execute(
            text("""
                SELECT id
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND tournament_version_id = :version_id
                  AND stage_id = :stage_id
                ORDER BY id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(payload.version_id),
                "stage_id": str(payload.stage_id),
            },
        )
        existing_match_ids = tuple(
            row["id"] for row in existing_result.mappings().all()
        )
        has_existing_matches = bool(existing_match_ids)
        if payload.swiss_round > 1:
            if payload.replace_existing:
                raise HTTPException(status_code=409, detail="No se puede reemplazar una ronda Swiss ya iniciada")
        elif has_existing_matches and not payload.replace_existing:
            raise HTTPException(status_code=409, detail="La fase ya tiene un sorteo; confirma el reemplazo para reiniciarlo")
        seed = payload.seed if payload.seed is not None else secrets.randbits(63)
        swiss_draw = await _load_swiss_draw_data(
            db,
            context,
            tournament_id,
            payload,
            team_ids,
            seed,
            replace_existing=payload.replace_existing,
            existing_match_ids=existing_match_ids,
        )

    # N-2: the read transaction is closed. The pure calculation runs in the
    # dedicated executor, so no connection stays idle in transaction while it
    # works and a failure never leaves partial writes behind.
    if swiss_draw is None:
        raise HTTPException(status_code=422, detail="El formato de fase indicado no admite sorteo automático")
    pairings = await _calculate_swiss_pairings(swiss_draw, team_ids, payload)
    active_pairings = [
        pairing
        for pairing in pairings
        if pairing.home_team_id and pairing.away_team_id
    ]
    if len(active_pairings) != len(swiss_draw.placeholder_ids):
        raise HTTPException(status_code=409, detail="El sorteo Swiss no coincide con los espacios disponibles")

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _require_tournament_management(db, context)
        try:
            _, locked_status = await lock_stage_and_version(
                db, context.organization_id, tournament_id, payload.stage_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada") from exc
        if locked_status != "draft" and not (
            locked_status == "published" and payload.swiss_round > 1
        ):
            raise HTTPException(status_code=409, detail="Solo se pueden generar rondas Swiss en una versión publicada")
        await _revalidate_swiss_draw_state(
            db, context, tournament_id, payload, swiss_draw
        )
        if swiss_draw.replace_existing:
            await _clear_stage_schedule(
                db,
                context.organization_id,
                tournament_id,
                payload.version_id,
                payload.stage_id,
            )
        await _write_swiss_schedule(
            db, context, tournament_id, payload, swiss_draw, active_pairings
        )

    return GenerateSingleEliminationResponse(
        version_id=payload.version_id,
        stage_id=payload.stage_id,
        stage_type="swiss",
        seed=swiss_draw.seed,
        round_count=payload.swiss_rounds,
        match_count=len(active_pairings),
        bye_count=sum(1 for pairing in pairings if pairing.bye_team_id),
        round_number=payload.swiss_round,
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
                       r.home_score, r.away_score, r.winner_team_id
                FROM matches m
                JOIN v_match_current_report r
                  ON r.match_id = m.id AND r.organization_id = m.organization_id
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


async def _team_display_names(
    db: AsyncSession, organization_id: UUID, team_ids: tuple[UUID, UUID]
) -> tuple[str, str]:
    """Return the team names used in the pairing-limit message."""

    result = await db.execute(
        text("""
            SELECT id, name
            FROM teams
            WHERE organization_id = :organization_id
              AND id = ANY(CAST(:team_ids AS uuid[]))
        """),
        {
            "organization_id": str(organization_id),
            "team_ids": [str(team_id) for team_id in team_ids],
        },
    )
    names = {str(row["id"]): row["name"] for row in result.mappings().all()}
    return tuple(names.get(str(team_id), str(team_id)) for team_id in team_ids)


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
        await _require_tournament_management(db, context)
        stage = await _load_draft_stage_context(
            db,
            context.organization_id,
            tournament_id,
            payload.version_id,
            payload.stage_id,
        )
        # phase -> version before reading stage_teams and inserting the match.
        try:
            _, locked_status = await lock_stage_and_version(
                db, context.organization_id, tournament_id, payload.stage_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Fase no encontrada en la versión indicada") from exc
        if locked_status != "draft":
            raise HTTPException(status_code=409, detail="La versión publicada es inmutable")
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

        # Manual pairings are limited by the persisted stage format (RF-009),
        # inside the phase -> version lock and before any INSERT. Generated
        # calendars are never validated with this rule. A pair needs both sides
        # to be a meeting, and cancelled matches do not count.
        max_meetings = max_meetings_per_pair(
            stage["stage_type"], stage["schedule_legs"]
        )
        if (
            max_meetings is not None
            and payload.home_team_id is not None
            and payload.away_team_id is not None
        ):
            existing_meetings = await count_pair_meetings(
                db,
                organization_id=context.organization_id,
                tournament_id=tournament_id,
                version_id=payload.version_id,
                stage_id=payload.stage_id,
                group_id=payload.group_id,
                home_team_id=payload.home_team_id,
                away_team_id=payload.away_team_id,
            )
            if existing_meetings >= max_meetings:
                home_name, away_name = await _team_display_names(
                    db,
                    context.organization_id,
                    (payload.home_team_id, payload.away_team_id),
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=pair_limit_detail(
                        stage_name=stage["stage_name"],
                        home_team_name=home_name,
                        away_team_name=away_name,
                        max_meetings=max_meetings,
                    ),
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
        match = dict(result.mappings().one())
        await record_match_slot_assignments(db, context.organization_id, match["id"])
    return match
