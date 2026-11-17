from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.modules.crests.resolver import (
    MediaGroup,
    sign_crest_rows,
    sign_media_rows,
)
from app.modules.matches.live_public import (
    PublicMatchStateResponse,
    SuspendedPublicMatchResponse,
)
from app.modules.tournaments.public_player_profile import (
    authorized_tournaments,
    build_player_profile,
    profile_available_ids,
    profile_photo_candidate,
    representative_first,
)
from app.modules.tournaments.public_timeline import (
    build_public_timeline,
    public_player_names,
    timeline_availability,
)
from app.modules.tournaments.schemas import (
    PublicMatchTimelineResponse,
    PublicPlayerProfileResponse,
    PublicPlayerStatsResponse,
    PublicStandingResponse,
    PublicTeamStatsResponse,
    PublicTournamentResponse,
    PublicTournamentSummaryResponse,
)

from app.modules.tournaments.access import (
    _ensure_public_tournament,
)

router = APIRouter()


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


async def _profile_rows(
    db: AsyncSession, tournament_id: UUID, player_ids: list[str] | None = None
) -> list:
    """Spec 038 RF-009: inscripciones públicas de **este** torneo, nunca de otros,
    para calcular `profile_available` y la inscripción representativa."""

    query = """
        SELECT tournament_id, team_id, player_id, is_active, valid_from, photo_consent
        FROM v_public_player_profile_rosters
        WHERE tournament_id = :tournament_id
    """
    params: dict[str, object] = {"tournament_id": str(tournament_id)}
    if player_ids is not None:
        if not player_ids:
            return []
        query += " AND player_id = ANY(CAST(:player_ids AS UUID[]))"
        params["player_ids"] = player_ids
    return list((await db.execute(text(query), params)).mappings().all())


@router.get("/public/players/{player_id}", response_model=PublicPlayerProfileResponse)
async def public_player_profile(
    player_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PublicPlayerProfileResponse:
    """Ficha pública del jugador (spec 038).

    Solo torneos visibles de su organización cuya inscripción representativa
    tiene consentimiento de imagen (DA-1, CL-11); sin ninguno, el mismo 404
    que el resto de lecturas públicas (RF-002). Número de consultas fijo
    (RNF-001) y cifras de ``compute_player_stats`` torneo a torneo (RF-006).
    """

    from app.modules.tournaments.public_stats import compute_player_stats

    params = {"player_id": str(player_id)}
    async with db.begin():
        org_id = (
            await db.execute(
                text("""
                    SELECT organization_id FROM v_public_player_profile_rosters
                    WHERE player_id = :player_id AND photo_consent
                    LIMIT 1
                """),
                params,
            )
        ).scalar_one_or_none()
        if org_id is None:
            raise HTTPException(status_code=404, detail="Torneo público no encontrado")
        await set_rls_context(db, org_id, None)

        inscriptions = [
            dict(row)
            for row in (
                await db.execute(
                    text("""
                        SELECT tournament_id, tournament_name, start_date, team_id, team_name,
                               player_id, first_name, last_name, is_active, valid_from,
                               photo_consent, photo_object_key
                        FROM v_public_player_profile_rosters
                        WHERE organization_id = :organization_id AND player_id = :player_id
                    """),
                    {**params, "organization_id": str(org_id)},
                )
            ).mappings().all()
        ]
        tournaments = authorized_tournaments(inscriptions)
        if not tournaments:
            raise HTTPException(status_code=404, detail="Torneo público no encontrado")

        tournament_ids = [str(row["tournament_id"]) for row in tournaments]
        team_ids = sorted({
            str(row["team_id"]) for row in inscriptions if str(row["tournament_id"]) in tournament_ids
        })
        scope = {"tournament_ids": tournament_ids, "team_ids": team_ids, **params}
        matches = [
            dict(row)
            for row in (
                await db.execute(
                    text("""
                        SELECT id, tournament_id, stage_id, stage_name, stage_order, group_id, group_name,
                               home_team_id, away_team_id, home_score, away_score, home_score_regular,
                               away_score_regular, status, resolution_type, home_penalties, away_penalties,
                               winner_team_id
                        FROM v_public_matches
                        WHERE tournament_id = ANY(CAST(:tournament_ids AS UUID[]))
                          AND (home_team_id = ANY(CAST(:team_ids AS UUID[]))
                               OR away_team_id = ANY(CAST(:team_ids AS UUID[])))
                    """),
                    scope,
                )
            ).mappings().all()
        ]
        # La inscripción del jugador en cada torneo, como en `player-stats`,
        # sin columnas de foto ni dorsal.
        rosters = [
            dict(row)
            for row in (
                await db.execute(
                    text("""
                        SELECT tournament_id, team_id, player_id, is_active, first_name, last_name, team_name
                        FROM v_public_tournament_rosters
                        WHERE tournament_id = ANY(CAST(:tournament_ids AS UUID[]))
                          AND player_id = :player_id
                        ORDER BY tournament_id, is_active DESC
                    """),
                    scope,
                )
            ).mappings().all()
        ]
        match_ids = [str(match["id"]) for match in matches]
        events: list[dict] = []
        segments: list[dict] = []
        formations: list[dict] = []
        if match_ids:
            ids = {"match_ids": match_ids}
            events = [
                dict(row)
                for row in (
                    await db.execute(
                        text("""
                            SELECT id, match_id, team_id, player_id, event_type, minute, added_minute,
                                   player_out_id, player_in_id, beneficiary_team_id, metadata
                            FROM v_public_match_events
                            WHERE match_id = ANY(CAST(:match_ids AS UUID[]))
                              AND (is_voided IS FALSE OR is_voided IS NULL)
                        """),
                        ids,
                    )
                ).mappings().all()
            ]
            segments = [
                dict(row)
                for row in (
                    await db.execute(
                        text("""
                            SELECT id, match_id, segment_number, minute_start, minute_end, status
                            FROM v_public_match_segments
                            WHERE match_id = ANY(CAST(:match_ids AS UUID[]))
                        """),
                        ids,
                    )
                ).mappings().all()
            ]
            formations = [
                dict(row)
                for row in (
                    await db.execute(
                        text("""
                            SELECT match_id, tournament_id, segment_id, segment_number, team_id,
                                   player_id, position_slot, is_starter, is_public, formation_code
                            FROM v_public_match_formations
                            WHERE match_id = ANY(CAST(:match_ids AS UUID[]))
                            ORDER BY match_id, team_id, segment_number, player_id
                        """),
                        ids,
                    )
                ).mappings().all()
            ]

    match_tournament = {str(match["id"]): str(match["tournament_id"]) for match in matches}
    stats_by_tournament: dict[str, dict] = {}
    for tournament_id in tournament_ids:
        own = {match_id for match_id, owner in match_tournament.items() if owner == tournament_id}
        rows = compute_player_stats(
            [m for m in matches if str(m["id"]) in own],
            [e for e in events if str(e["match_id"]) in own],
            [f for f in formations if str(f["match_id"]) in own],
            [s for s in segments if str(s["match_id"]) in own],
            representative_first([r for r in rosters if str(r["tournament_id"]) == tournament_id], tournaments),
        )
        mine = next((row for row in rows if str(row["player_id"]) == str(player_id)), None)
        if mine is not None:
            stats_by_tournament[tournament_id] = mine

    profile = build_player_profile(tournaments, stats_by_tournament)
    candidate = profile_photo_candidate(tournaments)
    photo = [{
        "photo_url": candidate["photo_object_key"] if candidate else None,
        "photo_consent": bool(candidate),
    }]
    # N-2: una sola firma, con la transacción de lectura ya cerrada (RNF-001).
    await sign_media_rows(
        [MediaGroup(rows=photo, key_field="photo_url", value_field="photo_url", consent_field="photo_consent")],
        policy="null",
    )
    return PublicPlayerProfileResponse(**profile, photo_url=photo[0]["photo_url"])


@router.get("/public/{tournament_id}", response_model=PublicTournamentResponse)
async def public_tournament(tournament_id: UUID, db: AsyncSession = Depends(get_db)) -> PublicTournamentResponse:
    async with db.begin():
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
        stages = [dict(stage) for stage in stages_result.mappings().all()]
        teams_result = await db.execute(
            text("""
                SELECT team_id, name, short_code, crest_object_key
                FROM v_public_tournament_teams
                WHERE tournament_id = :tournament_id
                ORDER BY name, team_id
            """),
            {"tournament_id": str(tournament_id)},
        )
        teams = [dict(team) for team in teams_result.mappings().all()]

    # N-2: the read transaction is closed before signing; one batch per answer.
    await sign_crest_rows(teams, policy="null")
    return {**dict(tournament), "stages": stages, "teams": teams}


@router.get("/public/{tournament_id}/standings")
async def public_standings(
    tournament_id: UUID,
    stage_id: UUID | None = None,
    group_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PublicStandingResponse]:
    async with db.begin():
        await _ensure_public_tournament(db, tournament_id)
        result = await db.execute(
            text("""
                SELECT s.tournament_id, s.stage_id, s.stage_name, s.stage_order,
                       s.group_id, s.group_name, s.team_id, s.team_name, s.short_code,
                       s.played, s.won, s.drawn, s.lost, s.goals_for,
                       s.goals_against, s.goal_difference, s.points,
                       s.fair_play_points, s.rank, s.calculated_at,
                       pt.crest_object_key
                FROM v_public_standings s
                LEFT JOIN v_public_tournament_teams pt
                  ON pt.tournament_id = s.tournament_id
                 AND pt.team_id = s.team_id
                WHERE s.tournament_id = :tournament_id
                  AND (CAST(:stage_id AS UUID) IS NULL
                       OR s.stage_id = CAST(:stage_id AS UUID))
                  AND (CAST(:group_id AS UUID) IS NULL
                       OR s.group_id = CAST(:group_id AS UUID))
                 ORDER BY s.stage_order, s.group_name NULLS FIRST, s.rank, s.team_id
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
        rows = [dict(row) for row in result.mappings().all()]

    # N-2: sign the whole table after the read transaction closed.
    await sign_crest_rows(rows, policy="null")
    return rows


SUSPENDED_PUBLIC_KEYS = tuple(SuspendedPublicMatchResponse.model_fields)


@router.get("/public/{tournament_id}/matches")
async def public_matches(
    tournament_id: UUID,
    stage_id: UUID | None = None,
    group_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PublicMatchStateResponse]:
    # N-2: every query lives inside this read transaction; the photos are
    # signed after it closes, never while the connection is idle in transaction.
    async with db.begin():
        await _ensure_public_tournament(db, tournament_id)
        result = await db.execute(
            text("""
                -- F1 (spec 036): la página se calcula sobre la unión completa:
                -- la proyección clásica aporta scheduled/finished/live (los live
                -- reciben los campos de reloj de la selección interna) y la
                -- selección interna aporta los suspendidos. El orden y los
                -- filtros usan metadatos internos antes de serializar; la salida
                -- del suspendido se recorta a sus 14 claves exactas.
                SELECT u.id, u.tournament_id, u.stage_id, u.stage_name, u.stage_order,
                       u.group_id, u.group_name, u.bracket_code, u.matchday, u.match_date,
                       u.home_team_id, u.home_team_name, u.home_team_short_code,
                       u.away_team_id, u.away_team_name, u.away_team_short_code,
                       u.home_score_regular, u.away_score_regular, u.home_score,
                       u.away_score, u.home_penalties, u.away_penalties,
                       u.winner_team_id, u.status, u.resolution_type, u.rectified_at,
                       u.is_provisional, u.clock_segment_number,
                       u.clock_elapsed_seconds, u.clock_state, u.clock_observed_at,
                       ht.crest_object_key AS home_team_crest_object_key,
                       at.crest_object_key AS away_team_crest_object_key
                FROM (
                    SELECT m.id, m.tournament_id, m.stage_id, m.stage_name,
                           m.stage_order, m.group_id, m.group_name, m.bracket_code,
                           m.matchday, m.match_date, m.home_team_id, m.home_team_name,
                           m.home_team_short_code, m.away_team_id, m.away_team_name,
                           m.away_team_short_code, m.home_score_regular,
                           m.away_score_regular,
                           COALESCE(lv.home_score, m.home_score) AS home_score,
                           COALESCE(lv.away_score, m.away_score) AS away_score,
                           m.home_penalties, m.away_penalties, m.winner_team_id,
                           m.status, m.resolution_type, m.rectified_at,
                           lv.is_provisional, lv.clock_segment_number,
                           lv.clock_elapsed_seconds, lv.clock_state,
                           lv.clock_observed_at
                    FROM v_public_matches m
                    LEFT JOIN v_match_live_public_selection lv
                      ON lv.id = m.id
                    WHERE m.tournament_id = :tournament_id
                    UNION ALL
                    SELECT s.id, s.tournament_id, s.stage_id, st.name, st.stage_order,
                           s.group_id, NULL, s.bracket_code, s.matchday, s.match_date,
                           s.home_team_id, s.home_team_name, NULL,
                           s.away_team_id, s.away_team_name, NULL,
                           NULL, NULL, s.home_score, s.away_score,
                           NULL, NULL, NULL, s.status, NULL, NULL,
                           s.is_provisional, s.clock_segment_number,
                           s.clock_elapsed_seconds, s.clock_state,
                           s.clock_observed_at
                    FROM v_match_live_public_selection s
                    JOIN v_public_stages st
                      ON st.tournament_id = s.tournament_id
                     AND st.id = s.stage_id
                    WHERE s.tournament_id = :tournament_id
                      AND s.status = 'suspended'
                ) u
                LEFT JOIN v_public_tournament_teams ht
                  ON ht.tournament_id = u.tournament_id
                 AND ht.team_id = u.home_team_id
                 AND u.status <> 'suspended'
                LEFT JOIN v_public_tournament_teams at
                  ON at.tournament_id = u.tournament_id
                 AND at.team_id = u.away_team_id
                 AND u.status <> 'suspended'
                WHERE (CAST(:stage_id AS UUID) IS NULL
                       OR u.stage_id = CAST(:stage_id AS UUID))
                  AND (CAST(:group_id AS UUID) IS NULL
                       OR u.group_id = CAST(:group_id AS UUID))
                  ORDER BY u.stage_order, u.stage_id, u.matchday NULLS LAST,
                           u.bracket_code NULLS LAST, u.match_date NULLS LAST, u.id
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
        lineup_rows: list[dict] = []
        origin_rows: list[dict] = []
        if matches:
            match_ids = [
                str(match["id"])
                for match in matches
                if match["status"] != "suspended"
            ]
            if match_ids:
                lineup_result = await db.execute(
                    text("""
                        SELECT match_id, team_id, team_name, side, formation_code, segment_number, player_id,
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
                lineup_rows = [dict(row) for row in lineup_result.mappings().all()]
                # Spec 040 §8: etiqueta de origen solo en plazas de la llave sin resolver.
                origin_result = await db.execute(
                    text("""
                        SELECT match_id, side, origin_kind, group_name, position, ordinal
                        FROM v_public_match_slot_origins
                        WHERE tournament_id = :tournament_id
                          AND match_id = ANY(CAST(:match_ids AS UUID[]))
                    """),
                    {"tournament_id": str(tournament_id), "match_ids": match_ids},
                )
                origin_rows = [dict(row) for row in origin_result.mappings().all()]

    if not matches:
        return []

    lineups_by_match: dict[str, dict[str, dict[str, object]]] = {}
    players: list[dict] = []
    for row in lineup_rows:
        match_key = str(row["match_id"])
        side = str(row["side"])
        match_lineups = lineups_by_match.setdefault(match_key, {})
        team_lineup = match_lineups.setdefault(
            side,
            {
                "team_id": row["team_id"],
                "team_name": row["team_name"],
                "formation_code": row["formation_code"],
                "segment_number": row.get("segment_number"),
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
            # The public view already nulls this without consent; the batch
            # resolver replaces the object key with a signed URL (or null).
            "photo_url": row["photo_url"],
        }
        players.append(player)
        bucket = "starters" if row["role"] == "starter" else "substitutes"
        team_lineup[bucket].append(player)  # type: ignore[union-attr]

    origins = {
        (str(row["match_id"]), row["side"]): {
            "kind": row["origin_kind"],
            "group_name": row["group_name"],
            "position": row["position"],
            "ordinal": row["ordinal"],
        }
        for row in origin_rows
    }
    for match in matches:
        if match["status"] == "suspended":
            continue
        match["home_origin"] = origins.get((str(match["id"]), "home"))
        match["away_origin"] = origins.get((str(match["id"]), "away"))
        match_lineups = lineups_by_match.get(str(match["id"]))
        if match_lineups:
            match["lineup"] = {
                "home": match_lineups.get("home"),
                "away": match_lineups.get("away"),
            }

    # N-2: the read transaction is closed. Photos and both crests of every match
    # go in the same single batch; a failure degrades to null (public policy).
    await sign_media_rows(
        [
            MediaGroup(
                rows=[match],
                key_field="home_team_crest_object_key",
                value_field="home_team_crest_url",
            )
            for match in matches
        ]
        + [
            MediaGroup(
                rows=[match],
                key_field="away_team_crest_object_key",
                value_field="away_team_crest_url",
            )
            for match in matches
        ]
        + [MediaGroup(rows=players, key_field="photo_url", value_field="photo_url")],
        policy="null",
    )

    # The published lineup of each side carries the crest of that same team.
    for match in matches:
        lineup = match.get("lineup") or {}
        if lineup.get("home") is not None:
            lineup["home"]["crest_url"] = match["home_team_crest_url"]
        if lineup.get("away") is not None:
            lineup["away"]["crest_url"] = match["away_team_crest_url"]

    # El suspendido responde con sus 14 claves exactas (extra="forbid"): nada de
    # alineaciones, escudos, metadatos de fase/grupo ni campos nulos añadidos.
    return [
        {key: match[key] for key in SUSPENDED_PUBLIC_KEYS}
        if match["status"] == "suspended"
        else match
        for match in matches
    ]


@router.get("/public/{tournament_id}/player-stats", response_model=list[PublicPlayerStatsResponse])
async def public_player_stats(
    tournament_id: UUID,
    stage_id: UUID | None = None,
    group_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PublicPlayerStatsResponse]:
    async with db.begin():
        org_result = await db.execute(
            text("SELECT organization_id FROM v_public_tournaments WHERE id = :tournament_id"),
            {"tournament_id": str(tournament_id)},
        )
        org_id = org_result.scalar_one_or_none()
        if org_id is None:
            raise HTTPException(status_code=404, detail="Torneo público no encontrado")
        await set_rls_context(db, org_id, None)
        await _ensure_public_tournament(db, tournament_id)

        matches_result = await db.execute(
            text("""
                SELECT id, tournament_id, stage_id, stage_name, stage_order, group_id, group_name,
                       home_team_id, away_team_id, home_score, away_score, home_score_regular,
                       away_score_regular, status, resolution_type, home_penalties, away_penalties,
                       winner_team_id
                FROM v_public_matches
                WHERE tournament_id = :tournament_id
                  AND (CAST(:stage_id AS UUID) IS NULL OR stage_id = CAST(:stage_id AS UUID))
                  AND (CAST(:group_id AS UUID) IS NULL OR group_id = CAST(:group_id AS UUID))
            """),
            {
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id) if stage_id else None,
                "group_id": str(group_id) if group_id else None,
            },
        )
        matches = [dict(row) for row in matches_result.mappings().all()]

        match_ids = [str(match["id"]) for match in matches]
        if match_ids:
            events_result = await db.execute(
                text("""
                    SELECT id, match_id, team_id, player_id, event_type, minute, added_minute,
                           player_out_id, player_in_id, beneficiary_team_id, metadata
                    FROM v_public_match_events
                    WHERE match_id = ANY(CAST(:match_ids AS UUID[]))
                      AND (is_voided IS FALSE OR is_voided IS NULL)
                """),
                {"match_ids": match_ids},
            )
            events = [dict(row) for row in events_result.mappings().all()]
            segments_result = await db.execute(
                text("""
                    SELECT id, match_id, segment_number, minute_start, minute_end, status
                    FROM v_public_match_segments
                    WHERE match_id = ANY(CAST(:match_ids AS UUID[]))
                """),
                {"match_ids": match_ids},
            )
            segments = [dict(row) for row in segments_result.mappings().all()]
            # Formaciones de la regla del portero (spec 022, T12). La
            # proyección interna de la 031 devuelve **todas** las formaciones
            # publicadas por partido, segmento y equipo; `v_public_match_lineups`
            # solo devuelve la última por equipo (`DISTINCT ON (match_id,
            # team_id)`), así que con ella el titular del primer segmento y el
            # portero entrante de una formación posterior (caso 16b) son
            # inalcanzables. El ámbito por fase ya viene resuelto en
            # `match_ids`: se acota a esos partidos (no se amplía), y solo al
            # torneo pedido. La 031 es requisito previo: sin la vista esta
            # lectura falla en vez de degradar el cálculo en silencio.
            formations_result = await db.execute(
                text("""
                    SELECT match_id, tournament_id, segment_id, segment_number, team_id,
                           player_id, position_slot, is_starter, is_public, formation_code
                    FROM v_public_match_formations
                    WHERE tournament_id = :tournament_id
                      AND match_id = ANY(CAST(:match_ids AS UUID[]))
                    ORDER BY match_id, team_id, segment_number, player_id
                """),
                {"tournament_id": str(tournament_id), "match_ids": match_ids},
            )
            formations = [dict(row) for row in formations_result.mappings().all()]
        else:
            events = []
            segments = []
            formations = []

        rosters_result = await db.execute(
            text("""
                -- RF-034: una inscripción retirada (is_active = FALSE) nunca
                -- publica foto, aunque su consentimiento y su clave de objeto
                -- estén guardados: la clave se anula aquí, en la lectura, para
                -- que no llegue a la firma en lote. El consentimiento se lee
                -- también de la inscripción vigente, de modo que un jugador con
                -- varias inscripciones firma la pareja (foto + consentimiento)
                -- de la vigente y no mezcla campos de una retirada.
                SELECT tournament_id, team_id, player_id, dorsal_number, is_active,
                       first_name, last_name, team_name,
                       CASE WHEN is_active AND photo_consent THEN photo_url
                            ELSE NULL END AS photo_url,
                       CASE WHEN is_active THEN photo_consent ELSE NULL END AS photo_consent
                FROM v_public_tournament_rosters
                WHERE tournament_id = :tournament_id
            """),
            {"tournament_id": str(tournament_id)},
        )
        rosters = []
        for row in rosters_result.mappings().all():
            item = dict(row)
            rosters.append(item)
        profile_rows = await _profile_rows(db, tournament_id)
        profiles = profile_available_ids(profile_rows)
        rosters = representative_first(rosters, profile_rows)

    from app.modules.tournaments.public_stats import (
        assign_ranks,
        compute_player_stats,
        player_stats_rank_key,
    )

    stats = compute_player_stats(matches, events, formations, segments, rosters)
    # Orden y `rank` se calculan una sola vez sobre el conjunto completo, antes
    # de paginar: la página 2 continúa la numeración de la 1 (RF-006, RF-022).
    ranked = assign_ranks(stats, player_stats_rank_key, "player_id")
    page = [dict(row) for row in ranked[offset: offset + limit]]

    # N-2: sign photos after the read transaction closed.
    await sign_media_rows(
        [MediaGroup(rows=page, key_field="photo_url", value_field="photo_url", consent_field="photo_consent")],
        policy="null",
    )
    for row in page:
        row.pop("photo_consent", None)
        row["profile_available"] = str(row["player_id"]) in profiles
    return page


@router.get("/public/{tournament_id}/team-stats", response_model=list[PublicTeamStatsResponse])
async def public_team_stats(
    tournament_id: UUID,
    stage_id: UUID | None = None,
    group_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PublicTeamStatsResponse]:
    async with db.begin():
        org_result = await db.execute(
            text("SELECT organization_id FROM v_public_tournaments WHERE id = :tournament_id"),
            {"tournament_id": str(tournament_id)},
        )
        org_id = org_result.scalar_one_or_none()
        if org_id is None:
            raise HTTPException(status_code=404, detail="Torneo público no encontrado")
        await set_rls_context(db, org_id, None)
        await _ensure_public_tournament(db, tournament_id)

        matches_result = await db.execute(
            text("""
                SELECT id, tournament_id, stage_id, stage_name, stage_order, group_id, group_name,
                       home_team_id, away_team_id, home_score, away_score, home_score_regular,
                       away_score_regular, status, resolution_type, home_penalties, away_penalties,
                       winner_team_id
                FROM v_public_matches
                WHERE tournament_id = :tournament_id
                  AND (CAST(:stage_id AS UUID) IS NULL OR stage_id = CAST(:stage_id AS UUID))
                  AND (CAST(:group_id AS UUID) IS NULL OR group_id = CAST(:group_id AS UUID))
            """),
            {
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id) if stage_id else None,
                "group_id": str(group_id) if group_id else None,
            },
        )
        matches = [dict(row) for row in matches_result.mappings().all()]

        match_ids = [str(match["id"]) for match in matches]
        if match_ids:
            events_result = await db.execute(
                text("""
                    SELECT id, match_id, team_id, player_id, event_type, minute, added_minute,
                           player_out_id, player_in_id, beneficiary_team_id, metadata
                    FROM v_public_match_events
                    WHERE match_id = ANY(CAST(:match_ids AS UUID[]))
                      AND (is_voided IS FALSE OR is_voided IS NULL)
                """),
                {"match_ids": match_ids},
            )
            events = [dict(row) for row in events_result.mappings().all()]
        else:
            events = []

        fair_play_result = await db.execute(
            text("""
                SELECT team_id, COALESCE(SUM(fair_play_points), 0) AS fair_play_points
                FROM v_public_standings
                WHERE tournament_id = :tournament_id
                  AND (CAST(:stage_id AS UUID) IS NULL OR stage_id = CAST(:stage_id AS UUID))
                  AND (CAST(:group_id AS UUID) IS NULL OR group_id = CAST(:group_id AS UUID))
                GROUP BY team_id
            """),
            {
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id) if stage_id else None,
                "group_id": str(group_id) if group_id else None,
            },
        )
        fair_play = [
            {"team_id": row["team_id"], "fair_play_points": row["fair_play_points"]}
            for row in fair_play_result.mappings().all()
        ]

        teams_result = await db.execute(
            text("""
                SELECT team_id, name, short_code, crest_object_key
                FROM v_public_tournament_teams
                WHERE tournament_id = :tournament_id
            """),
            {"tournament_id": str(tournament_id)},
        )
        team_info = {row["team_id"]: dict(row) for row in teams_result.mappings().all()}

    from app.modules.tournaments.public_stats import (
        assign_ranks,
        compute_team_stats,
        team_stats_rank_key,
    )

    stats = compute_team_stats(matches, events, fair_play)
    for item in stats:
        info = team_info.get(item["team_id"], {})
        item["team_name"] = info.get("name")
        item["short_code"] = info.get("short_code")
        item["crest_object_key"] = info.get("crest_object_key")

    # Igual que en jugadores: un único orden con la posición compartida en los
    # empates, calculado antes de paginar (RF-006, RF-022).
    ranked = assign_ranks(stats, team_stats_rank_key, "team_id")
    page = [dict(row) for row in ranked[offset: offset + limit]]

    await sign_crest_rows(page, policy="null")
    return page


@router.get(
    "/public/{tournament_id}/matches/{match_id}/timeline",
    response_model=PublicMatchTimelineResponse,
)
async def public_match_timeline(
    tournament_id: UUID,
    match_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PublicMatchTimelineResponse:
    """Cronología pública de un partido confirmado (spec 037).

    Torneo no visible, partido cancelado, inexistente o de otro torneo devuelven
    el mismo 404 que el resto de lecturas públicas (RF-004). Un partido en
    curso, suspendido o sin juego no lee eventos (RF-002, RF-003).
    """

    params = {"tournament_id": str(tournament_id), "match_id": str(match_id)}
    async with db.begin():
        org_id = (
            await db.execute(
                text("SELECT organization_id FROM v_public_tournaments WHERE id = :tournament_id"),
                params,
            )
        ).scalar_one_or_none()
        if org_id is None:
            raise HTTPException(status_code=404, detail="Torneo público no encontrado")
        await set_rls_context(db, org_id, None)

        match = (
            await db.execute(
                text("""
                    SELECT id, status, resolution_type, home_team_id, away_team_id,
                           home_score, away_score, home_score_regular, away_score_regular
                    FROM v_public_matches
                    WHERE tournament_id = :tournament_id AND id = :match_id
                """),
                params,
            )
        ).mappings().one_or_none()
        if match is None:
            suspended = (
                await db.execute(
                    text("""
                        SELECT id, status FROM v_match_live_public_selection
                        WHERE tournament_id = :tournament_id AND id = :match_id
                          AND status = 'suspended'
                    """),
                    params,
                )
            ).mappings().one_or_none()
            if suspended is None:
                raise HTTPException(status_code=404, detail="Torneo público no encontrado")
            match = {"id": suspended["id"], "status": "suspended", "resolution_type": None}
        match = dict(match)

        events: list[dict] = []
        segments: list[dict] = []
        names: dict[str, tuple[str, str]] = {}
        profiles: set[str] = set()
        if timeline_availability(match["status"], match["resolution_type"]) == "available":
            events = [
                dict(row)
                for row in (
                    await db.execute(
                        text("""
                            SELECT id, match_id, segment_id, team_id, player_id, event_type,
                                   minute, added_minute, player_out_id, player_in_id,
                                   beneficiary_team_id, metadata, is_voided
                            FROM v_public_match_events
                            WHERE tournament_id = :tournament_id AND match_id = :match_id
                              AND (is_voided IS FALSE OR is_voided IS NULL)
                        """),
                        params,
                    )
                ).mappings().all()
            ]
            segments = [
                dict(row)
                for row in (
                    await db.execute(
                        text("""
                            SELECT id, match_id, segment_number
                            FROM v_public_match_segments
                            WHERE match_id = :match_id
                        """),
                        params,
                    )
                ).mappings().all()
            ]
            player_ids = sorted(
                {
                    str(value)
                    for event in events
                    for value in (event["player_id"], event["player_out_id"], event["player_in_id"])
                    if value is not None
                }
            )
            if player_ids:
                # Solo nombre y apellido (DA-2 a): ni dorsal, ni foto, ni plantilla.
                rosters = (
                    await db.execute(
                        text("""
                            SELECT player_id, first_name, last_name
                            FROM v_public_tournament_rosters
                            WHERE tournament_id = :tournament_id
                              AND player_id = ANY(CAST(:player_ids AS UUID[]))
                            ORDER BY player_id, is_active DESC
                        """),
                        {**params, "player_ids": player_ids},
                    )
                ).mappings().all()
                names = public_player_names(rosters)
                profiles = profile_available_ids(await _profile_rows(db, tournament_id, player_ids))

    return PublicMatchTimelineResponse(**build_public_timeline(match, events, segments, names, profiles))
