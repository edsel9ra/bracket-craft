"""Lecturas de las exportaciones del Workspace (spec 048).

Cada exportación se lee en una transacción con ``set_rls_context`` y solo con
columnas explícitas: nunca documento, fecha de nacimiento, edad, correo ni claves
de foto o escudo (RF-004). Los datos salen de la versión publicada del torneo (D3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.exports import builders, catalog
from app.modules.exports.audit import record_roster_export_audit
from app.modules.exports.csv_format import render_csv
from app.modules.tournaments.public_stats import compute_player_stats, compute_team_stats


class ExportNotFound(Exception):
    """Torneo o partido inexistente o de otra organización (RF-005)."""


TOURNAMENT_SQL = text("""
    SELECT id, published_version_id
    FROM tournaments
    WHERE id = :tournament_id AND organization_id = :organization_id
""")

STANDINGS_SQL = text("""
    SELECT st.name AS stage_name, st.stage_order, g.name AS group_name, s.team_id,
           t.name AS team_name, s.played, s.won, s.drawn, s.lost, s.goals_for,
           s.goals_against, s.goal_difference, s.points, s.fair_play_points, s.rank
    FROM standings s
    JOIN stages st
      ON st.id = s.stage_id AND st.tournament_id = s.tournament_id
     AND st.organization_id = s.organization_id AND st.tournament_version_id = :version_id
    LEFT JOIN groups g
      ON g.id = s.group_id AND g.stage_id = s.stage_id AND g.organization_id = s.organization_id
    JOIN teams t ON t.id = s.team_id AND t.organization_id = s.organization_id
    WHERE s.organization_id = :organization_id AND s.tournament_id = :tournament_id
    ORDER BY st.stage_order, g.name NULLS FIRST, s.rank, s.team_id
    LIMIT :limit
""")

CALENDAR_SQL = text("""
    SELECT m.id, st.name AS stage_name, g.name AS group_name, m.bracket_code, m.matchday,
           m.match_date AS scheduled_at, home.name AS home_team_name, away.name AS away_team_name,
           m.status, m.result_confirmed, r.home_score, r.away_score, r.home_penalties, r.away_penalties
    FROM matches m
    JOIN v_match_current_report r ON r.match_id = m.id AND r.organization_id = m.organization_id
    JOIN stages st
      ON st.id = m.stage_id AND st.tournament_id = m.tournament_id AND st.organization_id = m.organization_id
    LEFT JOIN groups g
      ON g.id = m.group_id AND g.stage_id = m.stage_id AND g.organization_id = m.organization_id
    LEFT JOIN teams home ON home.id = m.home_team_id AND home.organization_id = m.organization_id
    LEFT JOIN teams away ON away.id = m.away_team_id AND away.organization_id = m.organization_id
    WHERE m.organization_id = :organization_id AND m.tournament_id = :tournament_id
      AND m.tournament_version_id = :version_id
    ORDER BY m.match_date NULLS LAST, m.matchday NULLS LAST, m.id
    LIMIT :limit
""")

# Mismos partidos que las estadísticas públicas (030), con el acta vigente (035).
STATS_MATCHES_SQL = text("""
    SELECT m.id, m.tournament_id, m.stage_id, m.group_id, m.home_team_id, m.away_team_id,
           r.home_score, r.away_score, r.home_score_regular, r.away_score_regular, m.status,
           m.result_confirmed, r.resolution_type, r.home_penalties, r.away_penalties, r.winner_team_id
    FROM matches m
    JOIN v_match_current_report r ON r.match_id = m.id AND r.organization_id = m.organization_id
    WHERE m.organization_id = :organization_id AND m.tournament_id = :tournament_id
      AND m.tournament_version_id = :version_id
      AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution')
""")

# Hechos de la versión vigente del acta, sin anulados (035).
STATS_EVENTS_SQL = text("""
    SELECT id, match_id, team_id, player_id, event_type, minute, added_minute,
           player_out_id, player_in_id, beneficiary_team_id, metadata
    FROM v_match_current_events
    WHERE organization_id = :organization_id AND match_id = ANY(CAST(:match_ids AS UUID[]))
""")

STATS_SEGMENTS_SQL = text("""
    SELECT id, match_id, segment_number, minute_start, minute_end, status
    FROM match_segments
    WHERE organization_id = :organization_id AND match_id = ANY(CAST(:match_ids AS UUID[]))
""")

# Solo formaciones publicadas, como la proyección pública de la 031.
STATS_FORMATIONS_SQL = text("""
    SELECT tl.match_id, tl.segment_id, ms.segment_number, tl.team_id, ls.player_id,
           ls.position_slot, ls.is_starter, tl.is_public, tl.formation_code
    FROM match_team_lineups tl
    JOIN match_segments ms
      ON ms.id = tl.segment_id AND ms.match_id = tl.match_id AND ms.organization_id = tl.organization_id
    JOIN match_lineup_snapshots ls
      ON ls.match_id = tl.match_id AND ls.segment_id = tl.segment_id
     AND ls.team_id = tl.team_id AND ls.organization_id = tl.organization_id
    WHERE tl.organization_id = :organization_id AND tl.match_id = ANY(CAST(:match_ids AS UUID[]))
      AND tl.is_public = TRUE AND tl.published_at IS NOT NULL
    ORDER BY tl.match_id, tl.team_id, ms.segment_number, ls.player_id
""")

# La inscripción vigente va primero: decide el equipo con el que cuenta el jugador.
STATS_ROSTERS_SQL = text("""
    SELECT r.team_id, r.player_id, r.dorsal_number, r.is_active, p.first_name, p.last_name,
           t.name AS team_name
    FROM rosters r
    JOIN players p ON p.id = r.player_id AND p.organization_id = r.organization_id
    JOIN teams t ON t.id = r.team_id AND t.organization_id = r.organization_id
    WHERE r.organization_id = :organization_id AND r.tournament_id = :tournament_id
    ORDER BY r.is_active DESC, r.valid_from DESC, r.id
""")

FAIR_PLAY_SQL = text("""
    SELECT s.team_id, COALESCE(SUM(s.fair_play_points), 0) AS fair_play_points
    FROM standings s
    JOIN stages st
      ON st.id = s.stage_id AND st.tournament_id = s.tournament_id
     AND st.organization_id = s.organization_id AND st.tournament_version_id = :version_id
    WHERE s.organization_id = :organization_id AND s.tournament_id = :tournament_id
    GROUP BY s.team_id
""")

# Plantillas (DA-3): sin edad, documento, fecha de nacimiento ni clave de la foto.
ROSTERS_SQL = text("""
    SELECT t.name AS team_name, r.dorsal_number, p.first_name, p.last_name, r.is_active, r.photo_consent
    FROM rosters r
    JOIN players p ON p.id = r.player_id AND p.organization_id = r.organization_id
    JOIN teams t ON t.id = r.team_id AND t.organization_id = r.organization_id
    WHERE r.organization_id = :organization_id AND r.tournament_id = :tournament_id
    ORDER BY t.name, r.dorsal_number, p.last_name, p.first_name, r.id
    LIMIT :limit
""")

TEAMS_SQL = text("""
    SELECT tt.team_id, t.name, t.short_code
    FROM tournament_teams tt
    JOIN teams t ON t.id = tt.team_id AND t.organization_id = tt.organization_id
    WHERE tt.organization_id = :organization_id AND tt.tournament_id = :tournament_id
""")


class ExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _rows(self, sql, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in (await self.db.execute(sql, params)).mappings().all()]

    async def export_tournament(self, context, tournament_id: UUID, kind: str, lang: str) -> bytes:
        header = catalog.header(kind, lang)
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            params = {"organization_id": str(context.organization_id), "tournament_id": str(tournament_id)}
            tournament = (await self.db.execute(TOURNAMENT_SQL, params)).mappings().one_or_none()
            if tournament is None:
                raise ExportNotFound
            if kind == "rosters":
                # Las plantillas no dependen de la versión publicada (D3).
                rows = await self._rosters(params, lang)
                data = render_csv(header, rows, max_rows=catalog.MAX_ROWS)
                await record_roster_export_audit(self.db, context, tournament_id, len(rows))
                return data
            version_id = tournament["published_version_id"]
            rows: list[list[Any]] = []
            if version_id is not None:
                params["version_id"] = str(version_id)
                rows = await self._READERS[kind](self, params, lang)
            return render_csv(header, rows, max_rows=catalog.MAX_ROWS)

    async def _rosters(self, params, lang) -> list[list[Any]]:
        data = await self._rows(ROSTERS_SQL, {**params, "limit": catalog.MAX_ROWS + 1})
        return builders.roster_rows(data, lang)

    async def _standings(self, params, lang):
        data = await self._rows(STANDINGS_SQL, {**params, "limit": catalog.MAX_ROWS + 1})
        return builders.standings_rows(data, lang)

    async def _calendar(self, params, lang):
        data = await self._rows(CALENDAR_SQL, {**params, "limit": catalog.MAX_ROWS + 1})
        return builders.calendar_rows(data, lang)

    async def _match_inputs(self, params, *, with_formations: bool):
        matches = await self._rows(STATS_MATCHES_SQL, params)
        events: list[dict] = []
        segments: list[dict] = []
        formations: list[dict] = []
        if matches:
            ids = {**params, "match_ids": [str(match["id"]) for match in matches]}
            events = await self._rows(STATS_EVENTS_SQL, ids)
            if with_formations:
                segments = await self._rows(STATS_SEGMENTS_SQL, ids)
                formations = await self._rows(STATS_FORMATIONS_SQL, ids)
        return matches, events, segments, formations

    async def _player_stats(self, params, lang):
        matches, events, segments, formations = await self._match_inputs(params, with_formations=True)
        rosters = await self._rows(STATS_ROSTERS_SQL, params)
        stats = compute_player_stats(matches, events, formations, segments, rosters)
        return builders.player_stats_rows(stats, lang)

    async def _team_stats(self, params, lang):
        matches, events, _segments, _formations = await self._match_inputs(params, with_formations=False)
        fair_play = await self._rows(FAIR_PLAY_SQL, params)
        teams = {row["team_id"]: row for row in await self._rows(TEAMS_SQL, params)}
        stats = compute_team_stats(matches, events, fair_play)
        for item in stats:
            info = teams.get(item["team_id"], {})
            item["team_name"] = info.get("name")
            item["short_code"] = info.get("short_code")
        return builders.team_stats_rows(stats, lang)

    _READERS: dict[str, Callable] = {
        "standings": _standings,
        "calendar": _calendar,
        "player-stats": _player_stats,
        "team-stats": _team_stats,
    }
