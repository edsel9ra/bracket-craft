"""«Equipo del torneo» (spec 049, plan §5): lectura para miembros, escritura con MANAGE_MEMBERS."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.tournament_roles.schemas import TournamentTeamMember
from app.modules.tournament_roles.service import (
    AssignmentNotFound,
    MemberNotFound,
    TournamentNotFound,
    TournamentRoleService,
)

router = APIRouter(tags=["tournament-roles"])

TOURNAMENT_NOT_FOUND = "Torneo no encontrado"
MEMBER_NOT_FOUND = "Miembro no encontrado"
ASSIGNMENT_NOT_FOUND = "Asignación no encontrada"


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    detail = {
        TournamentNotFound: TOURNAMENT_NOT_FOUND,
        MemberNotFound: MEMBER_NOT_FOUND,
        AssignmentNotFound: ASSIGNMENT_NOT_FOUND,
    }[type(exc)]
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


_ERRORS = (PermissionError, TournamentNotFound, MemberNotFound, AssignmentNotFound)


@router.get("/tournaments/{tournament_id}/team", response_model=list[TournamentTeamMember])
async def list_tournament_team(
    tournament_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    try:
        return await TournamentRoleService(db).list_team(context, tournament_id)
    except _ERRORS as exc:
        raise _http(exc) from exc


@router.put(
    "/tournaments/{tournament_id}/team/{organization_user_id}",
    response_model=TournamentTeamMember,
    status_code=status.HTTP_201_CREATED,
)
async def assign_tournament_operator(
    tournament_id: UUID,
    organization_user_id: UUID,
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        member, created = await TournamentRoleService(db).assign(context, tournament_id, organization_user_id)
    except _ERRORS as exc:
        raise _http(exc) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return member


@router.delete(
    "/tournaments/{tournament_id}/team/{organization_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_tournament_operator(
    tournament_id: UUID,
    organization_user_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        await TournamentRoleService(db).remove(context, tournament_id, organization_user_id)
    except _ERRORS as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
