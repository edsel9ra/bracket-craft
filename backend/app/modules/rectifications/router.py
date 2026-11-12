from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.rectifications.schemas import (
    CreateRectificationRequest,
    RectificationResponse,
    ReportVersionResponse,
)
from app.modules.rectifications.service import RectificationService

router = APIRouter(tags=["rectifications"])


async def _execute(operation):
    try:
        return await operation
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/matches/{match_id}/rectifications", response_model=RectificationResponse, status_code=201)
async def create_rectification(
    match_id: UUID, payload: CreateRectificationRequest,
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _execute(RectificationService(db).create(context, match_id, payload))


@router.get("/matches/{match_id}/rectifications", response_model=list[RectificationResponse])
async def list_rectifications(
    match_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _execute(RectificationService(db).list_requests(context, match_id))


@router.get("/rectifications/{request_id}", response_model=RectificationResponse)
async def get_rectification(
    request_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _execute(RectificationService(db).get_request(context, request_id))


@router.post("/rectifications/{request_id}/withdraw", response_model=RectificationResponse)
async def withdraw_rectification(
    request_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _execute(RectificationService(db).withdraw(context, request_id))


@router.get("/matches/{match_id}/report-versions", response_model=list[ReportVersionResponse])
async def list_report_versions(
    match_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _execute(RectificationService(db).list_versions(context, match_id))


@router.get("/matches/{match_id}/report-versions/{number}", response_model=ReportVersionResponse)
async def get_report_version(
    match_id: UUID, number: int = Path(ge=1),
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _execute(RectificationService(db).get_version(context, match_id, number))
