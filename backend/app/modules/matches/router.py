import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.permissions import require_permission
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.matches.schemas import (
    CloseMatchReportDTO,
    CreateMatchSegmentRequest,
    InterruptMatchSegmentRequest,
    MatchCloseResponse,
    MatchOperationResponse,
    MatchSegmentResponse,
    MatchSegmentInterruptionResponse,
    MatchOfficialResponse,
    MatchOfficialSummaryResponse,
    OfficialAssignmentRequest,
    OfficialRole,
    PublishMatchLineupRequest,
    SaveMatchLineupRequest,
)
from app.modules.matches.formations import FORMATION_SLOTS
from app.modules.matches.service import CloseMatchReportService


router = APIRouter(prefix="/matches", tags=["matches"])


async def _load_operation_match(
    db: AsyncSession,
    context: AuthContext,
    match_id: UUID,
    require_operation_permission: bool = True,
) -> dict[str, Any]:
    result = await db.execute(
        text("""
            SELECT m.id, m.tournament_id, m.tournament_version_id, m.stage_id, m.group_id,
                   m.matchday, m.match_date, m.status, m.result_confirmed,
                   m.home_team_id, ht.name AS home_team_name, ht.short_code AS home_team_short_code,
                   m.away_team_id, at.name AS away_team_name, at.short_code AS away_team_short_code,
                   m.home_score_regular, m.away_score_regular, m.home_score, m.away_score,
                   m.home_penalties, m.away_penalties, m.winner_team_id, m.resolution_type,
                   m.resolution_reason,
                   tv.status AS version_status, tv.rules_config, t.name AS tournament_name, s.name AS stage_name,
                   g.name AS group_name
            FROM matches m
            JOIN tournament_versions tv
              ON tv.id = m.tournament_version_id
             AND tv.tournament_id = m.tournament_id
             AND tv.organization_id = m.organization_id
            JOIN tournaments t
              ON t.id = m.tournament_id AND t.organization_id = m.organization_id
            JOIN stages s
              ON s.id = m.stage_id
             AND s.tournament_version_id = m.tournament_version_id
             AND s.tournament_id = m.tournament_id
             AND s.organization_id = m.organization_id
            LEFT JOIN groups g
              ON g.id = m.group_id
             AND g.stage_id = m.stage_id
             AND g.organization_id = m.organization_id
            LEFT JOIN teams ht
              ON ht.id = m.home_team_id AND ht.organization_id = m.organization_id
            LEFT JOIN teams at
              ON at.id = m.away_team_id AND at.organization_id = m.organization_id
             WHERE m.id = :match_id AND m.organization_id = :organization_id
             FOR UPDATE OF m
         """),
        {"match_id": str(match_id), "organization_id": str(context.organization_id)},
    )
    match = result.mappings().one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    if require_operation_permission:
        try:
            await require_permission(
                db,
                context,
                "CLOSE_MATCH_REPORT",
                tournament_id=match["tournament_id"],
                match_id=match_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    return dict(match)


async def _load_match_lineup(
    db: AsyncSession,
    organization_id: UUID,
    match_id: UUID,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text("""
            SELECT mr.id AS match_roster_id, mr.roster_id, mr.player_id, mr.team_id,
                   mr.role, mr.entered_minute, mr.left_minute, mr.is_valid,
                   p.first_name, p.last_name, r.dorsal_number, latest_snapshot.position_slot
            FROM match_rosters mr
            JOIN rosters r
              ON r.id = mr.roster_id AND r.organization_id = mr.organization_id
            JOIN players p ON p.id = mr.player_id
            LEFT JOIN LATERAL (
                SELECT ls.position_slot
                FROM match_lineup_snapshots ls
                JOIN match_segments ms
                  ON ms.id = ls.segment_id
                 AND ms.match_id = ls.match_id
                 AND ms.organization_id = ls.organization_id
                WHERE ls.match_id = mr.match_id
                  AND ls.team_id = mr.team_id
                  AND ls.player_id = mr.player_id
                  AND ls.organization_id = mr.organization_id
                ORDER BY ms.segment_number DESC
                LIMIT 1
            ) latest_snapshot ON TRUE
            WHERE mr.match_id = :match_id AND mr.organization_id = :organization_id
            ORDER BY mr.team_id, mr.role, r.dorsal_number, p.last_name, p.first_name
        """),
        {"match_id": str(match_id), "organization_id": str(organization_id)},
    )
    return [dict(row) for row in result.mappings().all()]


async def _load_match_tactical_lineups(
    db: AsyncSession,
    organization_id: UUID,
    match_id: UUID,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text("""
            SELECT tl.segment_id, ms.segment_number, tl.team_id, tl.formation_code,
                   tl.is_public, tl.published_at, ls.player_id, ls.is_starter,
                   ls.position_slot, p.first_name, p.last_name
            FROM match_team_lineups tl
            JOIN match_segments ms
              ON ms.id = tl.segment_id
             AND ms.match_id = tl.match_id
             AND ms.organization_id = tl.organization_id
            LEFT JOIN match_lineup_snapshots ls
              ON ls.match_id = tl.match_id
             AND ls.segment_id = tl.segment_id
             AND ls.team_id = tl.team_id
             AND ls.organization_id = tl.organization_id
            LEFT JOIN players p ON p.id = ls.player_id
            WHERE tl.match_id = :match_id AND tl.organization_id = :organization_id
            ORDER BY ms.segment_number, tl.team_id, ls.is_starter DESC,
                     ls.position_slot NULLS LAST, p.last_name, p.first_name
        """),
        {"match_id": str(match_id), "organization_id": str(organization_id)},
    )
    return [dict(row) for row in result.mappings().all()]


@router.post("/{match_id}/close", response_model=MatchCloseResponse)
async def close_match(
    match_id: UUID,
    payload: CloseMatchReportDTO,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MatchCloseResponse:
    try:
        return await CloseMatchReportService(db).execute(context, match_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="El acta no cumple las reglas de integridad del partido") from exc


@router.get("/{match_id}/operation", response_model=MatchOperationResponse)
async def get_match_operation(
    match_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MatchOperationResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match = await _load_operation_match(db, context, match_id, require_operation_permission=False)
        segment_result = await db.execute(
            text("""
                SELECT id, segment_number, minute_start, minute_end, status
                FROM match_segments
                WHERE match_id = :match_id AND organization_id = :organization_id
                ORDER BY segment_number
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        officials_result = await db.execute(
            text("""
                SELECT mo.id, mo.match_id, mo.organization_user_id, mo.official_role,
                       u.full_name, u.email
                FROM match_officials mo
                JOIN organization_users ou
                  ON ou.id = mo.organization_user_id AND ou.organization_id = mo.organization_id
                JOIN users u ON u.id = ou.user_id
                WHERE mo.match_id = :match_id AND mo.organization_id = :organization_id
                ORDER BY mo.official_role, mo.id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        eligible_result = await db.execute(
            text("""
                SELECT DISTINCT ou.id AS organization_user_id, u.full_name, u.email
                FROM organization_users ou
                JOIN users u ON u.id = ou.user_id
                JOIN organization_user_roles our
                  ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
                JOIN roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
                WHERE ou.organization_id = :organization_id
                  AND ou.is_active = TRUE
                   AND r.permissions @> CAST(:permission AS jsonb)
                   AND NOT EXISTS (
                       SELECT 1
                       FROM match_officials assigned
                       WHERE assigned.match_id = :match_id
                         AND assigned.organization_id = ou.organization_id
                         AND assigned.organization_user_id = ou.id
                   )
                ORDER BY u.full_name, u.email
            """),
            {
                "organization_id": str(context.organization_id),
                "match_id": str(match_id),
                "permission": '["CLOSE_MATCH_REPORT"]',
            },
        )
        interruption_result = await db.execute(
            text("""
                SELECT id, match_id, segment_id, reason, minute, notes, created_at
                FROM match_segment_interruptions
                WHERE match_id = :match_id AND organization_id = :organization_id
                ORDER BY minute, created_at, id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        roster_result = await db.execute(
            text("""
                SELECT r.id AS roster_id, r.player_id, r.team_id, t.name AS team_name,
                       p.first_name, p.last_name, r.dorsal_number, r.is_active,
                       mr.id AS match_roster_id, mr.role, mr.entered_minute, mr.left_minute,
                       mr.is_valid
                FROM rosters r
                JOIN players p ON p.id = r.player_id
                JOIN teams t ON t.id = r.team_id AND t.organization_id = r.organization_id
                LEFT JOIN match_rosters mr
                  ON mr.roster_id = r.id
                 AND mr.match_id = :match_id
                 AND mr.organization_id = r.organization_id
                WHERE r.tournament_id = :tournament_id
                  AND r.organization_id = :organization_id
                  AND r.team_id IN (CAST(:home_team_id AS UUID), CAST(:away_team_id AS UUID))
                ORDER BY r.team_id, r.dorsal_number, p.last_name, p.first_name
            """),
            {
                "match_id": str(match_id),
                "tournament_id": str(match["tournament_id"]),
                "organization_id": str(context.organization_id),
                "home_team_id": str(match["home_team_id"]) if match["home_team_id"] else None,
                "away_team_id": str(match["away_team_id"]) if match["away_team_id"] else None,
            },
        )
        event_result = await db.execute(
            text("""
                SELECT me.id, me.client_event_id, me.event_type, me.team_id,
                       t.name AS team_name, me.beneficiary_team_id, me.player_id,
                       p.first_name, p.last_name, me.minute, me.added_minute,
                       me.segment_id, me.metadata, me.is_voided, me.created_at
                FROM match_events me
                JOIN players p ON p.id = me.player_id
                JOIN teams t ON t.id = me.team_id AND t.organization_id = me.organization_id
                WHERE me.match_id = :match_id AND me.organization_id = :organization_id
                ORDER BY me.minute, me.added_minute, me.created_at, me.id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        lineup = await _load_match_lineup(db, context.organization_id, match_id)
        tactical_lineups = await _load_match_tactical_lineups(db, context.organization_id, match_id)

    return {
        "match": match,
        "segments": [dict(row) for row in segment_result.mappings().all()],
        "interruptions": [dict(row) for row in interruption_result.mappings().all()],
        "officials": [dict(row) for row in officials_result.mappings().all()],
        "eligible_officials": [dict(row) for row in eligible_result.mappings().all()],
        "rosters": [dict(row) for row in roster_result.mappings().all()],
        "lineup": lineup,
        "tactical_lineups": tactical_lineups,
        "events": [dict(row) for row in event_result.mappings().all()],
    }


@router.post("/{match_id}/segments", response_model=MatchSegmentResponse, status_code=status.HTTP_201_CREATED)
async def create_match_segment(
    match_id: UUID,
    payload: CreateMatchSegmentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MatchSegmentResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match = await _load_operation_match(db, context, match_id)
        if match["status"] in {"finished", "cancelled", "administrative_resolution"}:
            raise HTTPException(status_code=409, detail="El partido terminado no admite nuevos segmentos")
        try:
            latest_result = await db.execute(
                text("""
                    SELECT segment_number, minute_start, minute_end
                    FROM match_segments
                    WHERE match_id = :match_id AND organization_id = :organization_id
                    ORDER BY segment_number DESC
                    LIMIT 1
                    FOR UPDATE
                """),
                {"match_id": str(match_id), "organization_id": str(context.organization_id)},
            )
            latest_segment = latest_result.mappings().one_or_none()
            if latest_segment is not None:
                if payload.segment_number != latest_segment["segment_number"] + 1:
                    raise HTTPException(status_code=422, detail="El número de segmento debe ser consecutivo")
                required_start = latest_segment["minute_end"]
                if required_start is not None and payload.minute_start < required_start:
                    raise HTTPException(status_code=422, detail="El nuevo segmento no puede comenzar antes del segmento anterior")

            active_result = await db.execute(
                text("""
                    SELECT id, minute_start
                    FROM match_segments
                    WHERE match_id = :match_id
                      AND organization_id = :organization_id
                      AND status = 'active'
                    FOR UPDATE
                """),
                {"match_id": str(match_id), "organization_id": str(context.organization_id)},
            )
            active_segment = active_result.mappings().one_or_none()
            if active_segment is not None:
                if payload.minute_start < active_segment["minute_start"]:
                    raise HTTPException(status_code=422, detail="El nuevo segmento no puede comenzar antes del segmento activo")
                await db.execute(
                    text("""
                        UPDATE match_segments
                        SET status = 'completed', minute_end = :minute_end
                        WHERE id = :segment_id AND organization_id = :organization_id
                    """),
                    {
                        "segment_id": str(active_segment["id"]),
                        "organization_id": str(context.organization_id),
                        "minute_end": payload.minute_start,
                    },
                )
            result = await db.execute(
                text("""
                    INSERT INTO match_segments (organization_id, match_id, segment_number, minute_start)
                    VALUES (:organization_id, :match_id, :segment_number, :minute_start)
                    RETURNING id, segment_number, minute_start, minute_end, status
                """),
                {
                    "organization_id": str(context.organization_id),
                    "match_id": str(match_id),
                    "segment_number": payload.segment_number,
                    "minute_start": payload.minute_start,
                },
            )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="El número de segmento ya existe para este partido") from exc
        return dict(result.mappings().one())


@router.post("/{match_id}/segments/{segment_id}/interrupt", response_model=MatchSegmentInterruptionResponse, status_code=status.HTTP_201_CREATED)
async def interrupt_match_segment(
    match_id: UUID,
    segment_id: UUID,
    payload: InterruptMatchSegmentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MatchSegmentInterruptionResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match = await _load_operation_match(db, context, match_id)
        if match["status"] in {"finished", "cancelled", "administrative_resolution"}:
            raise HTTPException(status_code=409, detail="El partido terminado no admite interrupciones")
        segment_result = await db.execute(
            text("""
                SELECT id, minute_start, status
                FROM match_segments
                WHERE id = :segment_id AND match_id = :match_id AND organization_id = :organization_id
                FOR UPDATE
            """),
            {
                "segment_id": str(segment_id),
                "match_id": str(match_id),
                "organization_id": str(context.organization_id),
            },
        )
        segment = segment_result.mappings().one_or_none()
        if segment is None:
            raise HTTPException(status_code=404, detail="Segmento no encontrado en el partido")
        if segment["status"] != "active":
            raise HTTPException(status_code=409, detail="Solo se puede interrumpir el segmento activo")
        if payload.minute < segment["minute_start"]:
            raise HTTPException(status_code=422, detail="La interrupción no puede ocurrir antes del inicio del segmento")
        interruption_result = await db.execute(
            text("""
                INSERT INTO match_segment_interruptions
                    (organization_id, match_id, segment_id, reason, minute, notes, created_by_member_id)
                VALUES (:organization_id, :match_id, :segment_id, :reason, :minute, :notes, :member_id)
                RETURNING id, match_id, segment_id, reason, minute, notes, created_at
            """),
            {
                "organization_id": str(context.organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "reason": payload.reason,
                "minute": payload.minute,
                "notes": payload.notes,
                "member_id": str(context.organization_user_id),
            },
        )
        await db.execute(
            text("""
                UPDATE match_segments
                SET status = 'interrupted', minute_end = :minute
                WHERE id = :segment_id AND organization_id = :organization_id
            """),
            {
                "minute": payload.minute,
                "segment_id": str(segment_id),
                "organization_id": str(context.organization_id),
            },
        )
        interruption = dict(interruption_result.mappings().one())
        await db.execute(
            text("""
                INSERT INTO administrative_audit_logs
                    (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
                VALUES (
                    :organization_id,
                    'matches',
                    :match_id,
                    'INTERRUPT_MATCH_SEGMENT',
                    CAST(:payload AS jsonb),
                    :member_id
                )
            """),
            {
                "organization_id": str(context.organization_id),
                "match_id": str(match_id),
                "payload": json.dumps({
                    "segment_id": str(segment_id),
                    "reason": payload.reason,
                    "minute": payload.minute,
                    "notes": payload.notes,
                }),
                "member_id": str(context.organization_user_id),
            },
        )
        return interruption


@router.put("/{match_id}/lineup", response_model=list[dict[str, Any]])
async def save_match_lineup(
    match_id: UUID,
    payload: SaveMatchLineupRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match = await _load_operation_match(db, context, match_id)
        if match["status"] in {"finished", "cancelled", "administrative_resolution"}:
            raise HTTPException(status_code=409, detail="El partido terminado no admite cambios de planilla")

        segment_result = await db.execute(
            text("""
                SELECT status
                FROM match_segments
                WHERE id = :segment_id AND match_id = :match_id AND organization_id = :organization_id
            """),
            {
                "segment_id": str(payload.segment_id),
                "match_id": str(match_id),
                "organization_id": str(context.organization_id),
            },
        )
        segment_status = segment_result.scalar_one_or_none()
        if segment_status is None:
            raise HTTPException(status_code=404, detail="Segmento no encontrado en el partido")
        if segment_status != "active":
            raise HTTPException(status_code=409, detail="La planilla solo puede modificarse en el segmento activo")

        events_result = await db.execute(
            text("""
                SELECT 1
                FROM match_events
                WHERE match_id = :match_id AND organization_id = :organization_id
                LIMIT 1
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        if events_result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="La planilla no puede cambiar después de registrar eventos")
        if not payload.entries:
            raise HTTPException(status_code=422, detail="La planilla debe tener al menos un jugador por equipo")

        roster_ids = [str(entry.roster_id) for entry in payload.entries]
        roster_result = await db.execute(
            text("""
                SELECT r.id AS roster_id, r.player_id, r.team_id, r.is_active,
                       r.valid_from, r.valid_to, r.eligible_from
                FROM rosters r
                WHERE r.id = ANY(CAST(:roster_ids AS uuid[]))
                  AND r.tournament_id = :tournament_id
                  AND r.organization_id = :organization_id
            """),
            {
                "roster_ids": roster_ids,
                "tournament_id": str(match["tournament_id"]),
                "organization_id": str(context.organization_id),
            },
        )
        roster_by_id = {str(row["roster_id"]): dict(row) for row in roster_result.mappings().all()}
        if len(roster_by_id) != len(payload.entries):
            raise HTTPException(status_code=422, detail="Una o más inscripciones no pertenecen al torneo")

        participants = {str(match["home_team_id"]), str(match["away_team_id"])}
        participants.discard("None")
        selected_teams: set[str] = set()
        entries_by_team: dict[str, list[Any]] = {}
        for entry in payload.entries:
            roster = roster_by_id[str(entry.roster_id)]
            team_id = str(roster["team_id"])
            if team_id not in participants:
                raise HTTPException(status_code=422, detail="La planilla solo puede incluir jugadores de los dos equipos")
            if not roster["is_active"]:
                raise HTTPException(status_code=422, detail="La planilla incluye una inscripción inactiva")
            if match["match_date"] and roster["eligible_from"] > match["match_date"]:
                raise HTTPException(status_code=422, detail="La planilla incluye un jugador aún no elegible")
            if match["match_date"] and roster["valid_to"] and roster["valid_to"] < match["match_date"]:
                raise HTTPException(status_code=422, detail="La planilla incluye una inscripción vencida")
            selected_teams.add(team_id)
            entries_by_team.setdefault(team_id, []).append(entry)
        if selected_teams != participants:
            raise HTTPException(status_code=422, detail="La planilla debe incluir jugadores de ambos equipos")

        formation_by_team = {str(config.team_id): config.formation_code for config in payload.team_lineups}
        if payload.team_lineups and set(formation_by_team) != participants:
            raise HTTPException(status_code=422, detail="La formación debe configurarse para los dos equipos")
        if not payload.team_lineups and any(entry.position_slot for entry in payload.entries):
            raise HTTPException(status_code=422, detail="Las posiciones requieren una formación por equipo")
        for team_id, formation_code in formation_by_team.items():
            expected_slots = set(FORMATION_SLOTS[formation_code])
            team_entries = entries_by_team.get(team_id, [])
            starters = [entry for entry in team_entries if entry.role == "starter"]
            positions = [entry.position_slot for entry in starters]
            if len(starters) != len(expected_slots) or any(position is None for position in positions):
                raise HTTPException(status_code=422, detail="Cada formación debe tener once titulares con posición")
            if len(set(positions)) != len(positions) or set(positions) != expected_slots:
                raise HTTPException(status_code=422, detail="Las posiciones no corresponden con la formación seleccionada")

        await db.execute(
            text("""
                DELETE FROM match_team_lineups
                WHERE match_id = :match_id
                  AND segment_id = :segment_id
                  AND organization_id = :organization_id
            """),
            {
                "match_id": str(match_id),
                "segment_id": str(payload.segment_id),
                "organization_id": str(context.organization_id),
            },
        )
        await db.execute(
            text("""
                DELETE FROM match_lineup_snapshots
                WHERE match_id = :match_id
                  AND segment_id = :segment_id
                  AND organization_id = :organization_id
            """),
            {
                "match_id": str(match_id),
                "segment_id": str(payload.segment_id),
                "organization_id": str(context.organization_id),
            },
        )
        await db.execute(
            text("DELETE FROM match_rosters WHERE match_id = :match_id AND organization_id = :organization_id"),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        try:
            for config in payload.team_lineups:
                await db.execute(
                    text("""
                        INSERT INTO match_team_lineups
                            (organization_id, match_id, segment_id, team_id, formation_code)
                        VALUES (:organization_id, :match_id, :segment_id, :team_id, :formation_code)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "match_id": str(match_id),
                        "segment_id": str(payload.segment_id),
                        "team_id": str(config.team_id),
                        "formation_code": config.formation_code,
                    },
                )
            for entry in payload.entries:
                roster = roster_by_id[str(entry.roster_id)]
                await db.execute(
                    text("""
                        INSERT INTO match_rosters
                            (organization_id, match_id, roster_id, player_id, team_id, tournament_id,
                             role, entered_minute, left_minute)
                        VALUES
                            (:organization_id, :match_id, :roster_id, :player_id, :team_id, :tournament_id,
                             :role, :entered_minute, :left_minute)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "match_id": str(match_id),
                        "roster_id": str(entry.roster_id),
                        "player_id": str(roster["player_id"]),
                        "team_id": str(roster["team_id"]),
                        "tournament_id": str(match["tournament_id"]),
                        "role": entry.role,
                        "entered_minute": entry.entered_minute,
                        "left_minute": entry.left_minute,
                    },
                )
                await db.execute(
                    text("""
                        INSERT INTO match_lineup_snapshots
                            (organization_id, match_id, segment_id, team_id, player_id, is_starter, position_slot)
                        VALUES (:organization_id, :match_id, :segment_id, :team_id, :player_id, :is_starter, :position_slot)
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "match_id": str(match_id),
                        "segment_id": str(payload.segment_id),
                        "team_id": str(roster["team_id"]),
                        "player_id": str(roster["player_id"]),
                        "is_starter": entry.role == "starter",
                        "position_slot": entry.position_slot,
                    },
                )
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="La planilla contiene jugadores o dorsales incompatibles") from exc
        return await _load_match_lineup(db, context.organization_id, match_id)


@router.patch("/{match_id}/lineup/publication", response_model=dict[str, Any])
async def publish_match_lineup(
    match_id: UUID,
    payload: PublishMatchLineupRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match = await _load_operation_match(db, context, match_id)
        if payload.team_id not in {match["home_team_id"], match["away_team_id"]}:
            raise HTTPException(status_code=422, detail="El equipo no participa en el partido")

        lineup_result = await db.execute(
            text("""
                SELECT id, segment_id, team_id, formation_code
                FROM match_team_lineups
                WHERE match_id = :match_id
                  AND segment_id = :segment_id
                  AND team_id = :team_id
                  AND organization_id = :organization_id
            """),
            {
                "match_id": str(match_id),
                "segment_id": str(payload.segment_id),
                "team_id": str(payload.team_id),
                "organization_id": str(context.organization_id),
            },
        )
        lineup = lineup_result.mappings().one_or_none()
        if lineup is None:
            raise HTTPException(status_code=409, detail="Guarda la formación antes de publicarla")

        snapshot_result = await db.execute(
            text("""
                SELECT COUNT(*) FILTER (WHERE is_starter) AS starters,
                       COUNT(*) AS players,
                       ARRAY_AGG(position_slot) FILTER (WHERE is_starter) AS positions
                FROM match_lineup_snapshots
                WHERE match_id = :match_id
                  AND segment_id = :segment_id
                  AND team_id = :team_id
                  AND organization_id = :organization_id
            """),
            {
                "match_id": str(match_id),
                "segment_id": str(payload.segment_id),
                "team_id": str(payload.team_id),
                "organization_id": str(context.organization_id),
            },
        )
        snapshot = snapshot_result.mappings().one()
        if payload.is_public and (snapshot["starters"] != 11 or snapshot["players"] < 11):
            raise HTTPException(status_code=409, detail="La formación debe tener once titulares antes de publicarse")
        if payload.is_public:
            expected_positions = set(FORMATION_SLOTS[str(lineup["formation_code"])])
            actual_positions = set(snapshot["positions"] or [])
            if actual_positions != expected_positions:
                raise HTTPException(status_code=409, detail="La formación tiene posiciones incompletas o incompatibles")

        result = await db.execute(
            text("""
                UPDATE match_team_lineups
                SET is_public = :is_public,
                    published_at = CASE WHEN :is_public THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :lineup_id AND organization_id = :organization_id
                RETURNING id, segment_id, team_id, formation_code, is_public, published_at
            """),
            {
                "lineup_id": str(lineup["id"]),
                "organization_id": str(context.organization_id),
                "is_public": payload.is_public,
            },
        )
        return dict(result.mappings().one())


@router.get("/{match_id}/officials", response_model=list[MatchOfficialSummaryResponse])
async def list_match_officials(
    match_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[MatchOfficialSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match_result = await db.execute(
            text("""
                SELECT 1
                FROM matches
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        if match_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Partido no encontrado")
        result = await db.execute(
            text("""
                SELECT mo.id, mo.organization_user_id, mo.official_role,
                       u.full_name, u.email
                FROM match_officials mo
                JOIN organization_users ou
                  ON ou.id = mo.organization_user_id
                 AND ou.organization_id = mo.organization_id
                JOIN users u ON u.id = ou.user_id
                WHERE mo.match_id = :match_id
                  AND mo.organization_id = :organization_id
                ORDER BY mo.official_role, mo.id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        return [dict(row) for row in result.mappings().all()]


@router.post("/{match_id}/officials", response_model=MatchOfficialResponse, status_code=status.HTTP_201_CREATED)
async def assign_match_official(
    match_id: UUID,
    payload: OfficialAssignmentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> MatchOfficialResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match_result = await db.execute(
            text("""
                SELECT tournament_id
                FROM matches
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        tournament_id = match_result.scalar_one_or_none()
        if tournament_id is None:
            raise HTTPException(status_code=404, detail="Partido no encontrado")

        try:
            await require_permission(
                db,
                context,
                "MANAGE_TOURNAMENTS",
                tournament_id=tournament_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        member_result = await db.execute(
            text("""
                SELECT id
                FROM organization_users
                WHERE id = :organization_user_id
                  AND organization_id = :organization_id
                  AND is_active = TRUE
            """),
            {
                "organization_user_id": str(payload.organization_user_id),
                "organization_id": str(context.organization_id),
            },
        )
        if member_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="El miembro no pertenece a la organización activa")

        existing_assignment_result = await db.execute(
            text("""
                SELECT official_role
                FROM match_officials
                WHERE match_id = :match_id
                  AND organization_id = :organization_id
                  AND organization_user_id = :organization_user_id
            """),
            {
                "match_id": str(match_id),
                "organization_id": str(context.organization_id),
                "organization_user_id": str(payload.organization_user_id),
            },
        )
        existing_role = existing_assignment_result.scalar_one_or_none()
        if existing_role is not None and existing_role != payload.official_role:
            raise HTTPException(status_code=409, detail="El usuario ya tiene otro rol asignado en este partido")

        assignment_result = await db.execute(
            text("""
                INSERT INTO match_officials
                    (organization_id, match_id, organization_user_id, official_role)
                VALUES (:organization_id, :match_id, :organization_user_id, :official_role)
                ON CONFLICT (match_id, organization_user_id) DO NOTHING
                RETURNING id
            """),
            {
                "organization_id": str(context.organization_id),
                "match_id": str(match_id),
                "organization_user_id": str(payload.organization_user_id),
                "official_role": payload.official_role,
            },
        )
        assignment_id = assignment_result.scalar_one_or_none()
        if assignment_id is None:
            assignment_id = (await db.execute(
                text("""
                    SELECT id
                    FROM match_officials
                    WHERE match_id = :match_id
                      AND organization_id = :organization_id
                      AND organization_user_id = :organization_user_id
                      AND official_role = :official_role
                """),
                {
                    "match_id": str(match_id),
                    "organization_id": str(context.organization_id),
                    "organization_user_id": str(payload.organization_user_id),
                    "official_role": payload.official_role,
                },
            )).scalar_one()

    return {
        "id": str(assignment_id),
        "match_id": str(match_id),
        "organization_user_id": str(payload.organization_user_id),
        "official_role": payload.official_role,
    }


@router.delete("/{match_id}/officials/{organization_user_id}/{official_role}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_match_official(
    match_id: UUID,
    organization_user_id: UUID,
    official_role: OfficialRole,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        match_result = await db.execute(
            text("""
                SELECT tournament_id
                FROM matches
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        tournament_id = match_result.scalar_one_or_none()
        if tournament_id is None:
            raise HTTPException(status_code=404, detail="Partido no encontrado")
        try:
            await require_permission(
                db,
                context,
                "MANAGE_TOURNAMENTS",
                tournament_id=tournament_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        result = await db.execute(
            text("""
                DELETE FROM match_officials
                WHERE match_id = :match_id
                  AND organization_id = :organization_id
                  AND organization_user_id = :organization_user_id
                  AND official_role = :official_role
            """),
            {
                "match_id": str(match_id),
                "organization_id": str(context.organization_id),
                "organization_user_id": str(organization_user_id),
                "official_role": official_role,
            },
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="Asignación de oficial no encontrada")
