from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.webhooks.schemas import (
    CreatedWebhook,
    CreateWebhookRequest,
    UpdateWebhookRequest,
    WebhookDelivery,
    WebhookItem,
    WebhookSecret,
    WebhookTestDelivery,
)
from app.modules.webhooks.service import WebhookConflict, WebhookNotFound, WebhookService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# El mismo 404 para un webhook inexistente y para uno de otra organización (RF-013).
NOT_FOUND = "Webhook no encontrado"
FORBIDDEN = "Permiso requerido: MANAGE_WEBHOOKS"


async def _run(call):
    try:
        return await call
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=FORBIDDEN) from exc
    except WebhookNotFound as exc:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from exc
    except WebhookConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", response_model=list[WebhookItem])
async def list_webhooks(context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)):
    return await _run(WebhookService(db).list(context))


@router.post("", response_model=CreatedWebhook, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: CreateWebhookRequest,
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _run(WebhookService(db).create(context, body))


@router.patch("/{webhook_id}", response_model=WebhookItem)
async def update_webhook(
    webhook_id: UUID, body: UpdateWebhookRequest,
    context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _run(WebhookService(db).update(context, webhook_id, body))


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    await _run(WebhookService(db).delete(context, webhook_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookSecret)
async def rotate_webhook_secret(
    webhook_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _run(WebhookService(db).rotate(context, webhook_id))


@router.post("/{webhook_id}/test", response_model=WebhookTestDelivery, status_code=status.HTTP_202_ACCEPTED)
async def test_webhook(
    webhook_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _run(WebhookService(db).send_test(context, webhook_id))


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDelivery])
async def list_webhook_deliveries(
    webhook_id: UUID, context: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db),
):
    return await _run(WebhookService(db).deliveries(context, webhook_id))
