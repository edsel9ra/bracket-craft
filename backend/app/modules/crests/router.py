"""Workspace endpoints for the crest of a team enrolled in a tournament (RF-2, RF-10).

The three operations live under the tournament that gives the screen its
context; the permission is always the organization one (there is no tournament
scope). The service enforces the documented order — session and organization,
tournament (404), ``MANAGE_TOURNAMENTS`` (403), enrolled team (404) — and the
router only reads the upload, calls the service and signs the answer.

``GET`` only requires an active membership with a role (already checked by
``get_auth_context``) and answers the current signed link. ``POST`` and
``DELETE`` require the management permission, revalidated inside the service.
The ``CrestError`` handler registered in ``app/main.py`` adds the stable
``code`` next to the string ``detail`` for any status.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.storage import get_object_storage
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.crests.errors import CREST_UPLOAD_FAILED, CrestError
from app.modules.crests.resolver import sign_crest_rows
from app.modules.crests.service import (
    delete_crest,
    load_crest,
    resolve_enrolled_team,
)
from app.modules.crests.validation import validate_crest_content
from app.modules.tournaments.schemas import TeamCrestResponse

router = APIRouter(prefix="/tournaments", tags=["crests"])


@router.get(
    "/{tournament_id}/teams/{team_id}/crest",
    response_model=TeamCrestResponse,
)
async def get_team_crest(
    tournament_id: UUID,
    team_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TeamCrestResponse:
    """Return the current crest of the team as a temporary signed link."""

    enrolled = await resolve_enrolled_team(
        db,
        context,
        tournament_id,
        team_id,
        require_management=False,
    )
    row = {
        "team_id": enrolled.team_id,
        "crest_object_key": enrolled.crest_object_key,
        "logo_url": enrolled.logo_url,
    }
    # Signed after the read transaction closed (N-2); a storage failure is a 503.
    await sign_crest_rows([row], policy="error")
    return TeamCrestResponse(
        team_id=row["team_id"],
        crest_url=row["crest_url"],
        logo_url=row["logo_url"],
    )


@router.post(
    "/{tournament_id}/teams/{team_id}/crest",
    response_model=TeamCrestResponse,
)
async def upload_team_crest(
    tournament_id: UUID,
    team_id: UUID,
    file: UploadFile = File(...),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> TeamCrestResponse:
    """Upload or replace the crest; the detected content type decides."""

    # Guard order (plan §7.1): context, tournament (404), permission (403) and
    # enrollment (404) decide before the file is read or validated (422). The
    # service revalidates everything inside the write transaction.
    enrolled = await resolve_enrolled_team(db, context, tournament_id, team_id)

    settings = get_settings()
    # One byte past the limit detects the excess even when the body fits the
    # global request limit; the original file name is never used.
    raw = await file.read(settings.storage_max_image_bytes + 1)
    crest = validate_crest_content(raw, max_bytes=settings.storage_max_image_bytes)
    try:
        return await load_crest(
            db,
            context,
            tournament_id,
            team_id,
            crest,
            storage=get_object_storage(),
            enrolled=enrolled,
        )
    except HTTPException:
        # Coded and plain HTTP errors keep their status, detail and code.
        raise
    except Exception as exc:
        # The service compensates before propagating (T7/T9); an unclassified
        # failure answers the catalog's 500 without leaking the internal cause.
        raise CrestError(CREST_UPLOAD_FAILED) from exc


@router.delete(
    "/{tournament_id}/teams/{team_id}/crest",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_team_crest(
    tournament_id: UUID,
    team_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove the crest; the answer is the same with and without an image."""

    await delete_crest(
        db,
        context,
        tournament_id,
        team_id,
        get_object_storage(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
