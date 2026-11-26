"""Descargas CSV del Workspace (spec 048): cualquier miembro, sin permiso adicional (DA-3)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.exports.csv_format import ExportTooLarge
from app.modules.exports.service import ExportNotFound, ExportService, MatchNotClosed

router = APIRouter(tags=["exports"])

TOURNAMENT_NOT_FOUND = "Torneo no encontrado"
MATCH_NOT_FOUND = "Partido no encontrado"
MATCH_NOT_CLOSED = "MATCH_NOT_CLOSED"
EXPORT_TOO_LARGE = "EXPORT_TOO_LARGE"

TournamentExportKind = Literal["standings", "calendar", "player-stats", "team-stats", "rosters"]
ExportLang = Literal["es", "en"]


def _csv(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/tournaments/{tournament_id}/exports/{kind}")
async def export_tournament(
    tournament_id: UUID,
    kind: TournamentExportKind,
    lang: ExportLang = "es",
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        data = await ExportService(db).export_tournament(context, tournament_id, kind, lang)
    except ExportNotFound as exc:
        raise HTTPException(status_code=404, detail=TOURNAMENT_NOT_FOUND) from exc
    except ExportTooLarge as exc:
        raise HTTPException(status_code=422, detail=EXPORT_TOO_LARGE) from exc
    return _csv(data, f"{kind}-{str(tournament_id)[:8]}.csv")


@router.get("/matches/{match_id}/export")
async def export_match_report(
    match_id: UUID,
    lang: ExportLang = "es",
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        data = await ExportService(db).export_match_report(context, match_id, lang)
    except ExportNotFound as exc:
        raise HTTPException(status_code=404, detail=MATCH_NOT_FOUND) from exc
    except MatchNotClosed as exc:
        raise HTTPException(status_code=409, detail=MATCH_NOT_CLOSED) from exc
    except ExportTooLarge as exc:
        raise HTTPException(status_code=422, detail=EXPORT_TOO_LARGE) from exc
    return _csv(data, f"match-report-{str(match_id)[:8]}.csv")
