from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.notifications.schemas import NotificationPage, NotificationPreferences, NotificationQuery
from app.modules.notifications.service import NotificationService

router = APIRouter(tags=["notifications"])

# El mismo 404 para un aviso inexistente y para uno ajeno (RF-013).
NOT_FOUND = "Aviso no encontrado"


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    query: NotificationQuery = Query(),
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).list(context, query)


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    await NotificationService(db).mark_read(context, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: UUID,
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    try:
        await NotificationService(db).mark_read(context, notification_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notification-preferences", response_model=NotificationPreferences)
async def get_notification_preferences(
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).preferences(context)


@router.put("/notification-preferences", response_model=NotificationPreferences)
async def save_notification_preferences(
    body: NotificationPreferences,
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await NotificationService(db).save_preferences(context, body)
