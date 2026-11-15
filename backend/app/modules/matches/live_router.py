"""Rutas HTTP del partido en vivo (F1, spec 036).

Montaje productivo único bajo `/api/v1/matches`: sin router paralelo de
pruebas ni flag oculto. Cada ruta comparte el middleware de origen/CSRF, la
sesión vigente (`get_session_id`) y el contexto organizativo del resto del
módulo; los permisos VIEW/OPERATE/CLOSE se exigen dentro del servicio.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_session_id
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.matches.live_schemas import (
    LiveAccessResponse,
    LiveCommandAck,
    LiveCommandRequest,
    LiveReviewRequest,
    LiveReviewResponse,
    LiveSnapshotResponse,
)
from app.modules.matches.live_service import LiveMatchService

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("/{match_id}/live", response_model=LiveSnapshotResponse)
async def get_match_live(
    match_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    session_id: UUID = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
) -> LiveSnapshotResponse:
    return await LiveMatchService(db).snapshot(context, match_id, session_id)


@router.get("/{match_id}/live/access", response_model=LiveAccessResponse)
async def get_match_live_access(
    match_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    session_id: UUID = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
) -> LiveAccessResponse:
    return await LiveMatchService(db).access(context, match_id, session_id)


@router.post("/{match_id}/live/commands", response_model=LiveCommandAck)
async def post_match_live_command(
    match_id: UUID,
    command: LiveCommandRequest,
    context: AuthContext = Depends(get_auth_context),
    session_id: UUID = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
) -> LiveCommandAck:
    return await LiveMatchService(db).execute(context, match_id, session_id, command.root)


@router.post(
    "/{match_id}/live/reviews",
    response_model=LiveReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_match_live_review(
    match_id: UUID,
    request: LiveReviewRequest,
    context: AuthContext = Depends(get_auth_context),
    session_id: UUID = Depends(get_session_id),
    db: AsyncSession = Depends(get_db),
) -> LiveReviewResponse:
    return LiveReviewResponse.model_validate(
        await LiveMatchService(db).create_review(
            context, match_id, session_id, request
        )
    )
