from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.platform import PlatformContext, get_platform_context
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.sanction_appeals.cases import SanctionCaseService
from app.modules.sanction_appeals.notifications import SanctionNotificationService
from app.modules.sanction_appeals.platform import SanctionPlatformService
from app.modules.sanction_appeals.schemas import (
    AppealBody, AppealRequest, AuthorizationRequest, CaseFilters, DecisionRequest,
    ProposalBody, ProposalRequest, SanctionFilters, WithdrawalRequest,
)

router = APIRouter(tags=["sanction-appeals"])


async def _execute(operation):
    try:
        return await operation
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sanctions")
async def list_sanctions(filters: SanctionFilters = Query(), context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).list_sanctions(context, filters))


@router.get("/sanction-cases")
async def list_cases(filters: CaseFilters = Query(), context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).list_cases(context, filters))


@router.post("/sanctions/{suspension_id}/appeals", status_code=201)
async def appeal(suspension_id: UUID, payload: AppealBody, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).submit_appeal(context, AppealRequest(suspension_id=suspension_id, **payload.model_dump())))


@router.post("/sanctions/{suspension_id}/administrative-proposals", status_code=201)
async def propose(suspension_id: UUID, payload: ProposalBody, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).submit_proposal(context, ProposalRequest(suspension_id=suspension_id, **payload.model_dump())))


@router.get("/sanction-cases/{case_id}")
async def detail(case_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).detail(context, case_id))


@router.get("/sanction-cases/{case_id}/preview")
async def preview(case_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).preview(context, case_id))


@router.post("/sanction-cases/{case_id}/decision")
async def decide(case_id: UUID, payload: DecisionRequest, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).decide(context, case_id, payload))


@router.post("/sanction-cases/{case_id}/withdraw")
async def withdraw(case_id: UUID, payload: WithdrawalRequest, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionCaseService(db).withdraw(context, case_id, payload))


@router.get("/sanction-cases/{case_id}/platform-authorizations")
async def authorizations(case_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).list_authorizations(context, case_id))


@router.post("/sanction-cases/{case_id}/platform-authorizations", status_code=201)
async def grant(case_id: UUID, payload: AuthorizationRequest, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).grant(context, case_id, payload))


@router.delete("/sanction-cases/{case_id}/platform-authorizations/{authorization_id}")
async def revoke(case_id: UUID, authorization_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).revoke(context, case_id, authorization_id))


@router.get("/platform/sanction-cases")
async def platform_list(filters: CaseFilters = Query(), context: PlatformContext = Depends(get_platform_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).list_authorized(context, filters))


@router.get("/platform/sanction-cases/{case_id}")
async def platform_detail(case_id: UUID, context: PlatformContext = Depends(get_platform_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).detail(context, case_id))


@router.get("/platform/sanction-cases/{case_id}/preview")
async def platform_preview(case_id: UUID, context: PlatformContext = Depends(get_platform_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).preview(context, case_id))


@router.post("/platform/sanction-cases/{case_id}/decision")
async def platform_decide(case_id: UUID, payload: DecisionRequest, context: PlatformContext = Depends(get_platform_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionPlatformService(db).decide(context, case_id, payload))


@router.get("/sanction-notifications")
async def notifications(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                        context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _execute(SanctionNotificationService(db).list(context, limit=limit, offset=offset))
