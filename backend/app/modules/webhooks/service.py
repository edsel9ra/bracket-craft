"""Gestión de webhooks de la organización activa (spec 047, RF-001–RF-004, RF-008, RF-012, RF-013)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import set_rls_context
from app.core.permissions import require_permission
from app.modules.webhooks import audit
from app.modules.webhooks.catalog import MAX_WEBHOOKS, audit_host, generate_secret
from app.modules.webhooks.schemas import CreateWebhookRequest, UpdateWebhookRequest

PERMISSION = "MANAGE_WEBHOOKS"
DELIVERY_PAGE = 50
DELIVERY_DAYS = 30



class WebhookNotFound(LookupError):
    pass


class WebhookConflict(Exception):
    """``WEBHOOK_LIMIT_REACHED`` o ``WEBHOOK_INACTIVE``."""


def _database_code(error: DBAPIError) -> str | None:
    message = str(error.orig)
    for code in ("WEBHOOK_NOT_FOUND", "WEBHOOK_INACTIVE", "WEBHOOK_MANAGER_REQUIRED"):
        if code in message:
            return code
    return None


def _raise_domain(error: DBAPIError) -> None:
    code = _database_code(error)
    if code == "WEBHOOK_NOT_FOUND":
        raise WebhookNotFound from error
    if code == "WEBHOOK_INACTIVE":
        raise WebhookConflict(code) from error
    if code == "WEBHOOK_MANAGER_REQUIRED":
        raise PermissionError(code) from error
    raise error


def _payload(row, *, full: bool) -> dict:
    payload = {"host": audit_host(row["url"])}
    if full:
        payload |= {"event_types": list(row["event_types"]), "is_active": row["is_active"]}
    return payload


class WebhookService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _enter(self, context) -> None:
        await set_rls_context(self.db, context.organization_id, context.user_id)
        await require_permission(self.db, context, PERMISSION)

    async def _managed(self, context, webhook_id: UUID):
        """Bloquea el webhook de la organización activa; uno ajeno o inexistente da ``WebhookNotFound``."""
        row = (await self.db.execute(
            text("SELECT id, url, event_types, is_active, created_at, updated_at FROM organization_webhooks WHERE id = :id AND organization_id = :org FOR UPDATE"),
            {"id": webhook_id, "org": context.organization_id},
        )).mappings().one_or_none()
        if row is None:
            raise WebhookNotFound
        return row

    async def list(self, context) -> list[dict]:
        async with self.db.begin():
            await self._enter(context)
            rows = (await self.db.execute(
                text("SELECT id, url, event_types, is_active, created_at, updated_at FROM organization_webhooks WHERE organization_id = :org "
                     "ORDER BY created_at, id"),
                {"org": context.organization_id},
            )).mappings().all()
        return [dict(row) for row in rows]

    async def create(self, context, body: CreateWebhookRequest) -> dict:
        secret = generate_secret()
        async with self.db.begin():
            await self._enter(context)
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('organization_webhooks:' || :org, 0))"),
                {"org": str(context.organization_id)},
            )
            count = (await self.db.execute(
                text("SELECT count(*) FROM organization_webhooks WHERE organization_id = :org"),
                {"org": context.organization_id},
            )).scalar_one()
            if count >= MAX_WEBHOOKS:
                raise WebhookConflict("WEBHOOK_LIMIT_REACHED")
            row = (await self.db.execute(
                text("""INSERT INTO organization_webhooks
                        (organization_id, url, event_types, secret_encrypted, created_by_member_id)
                    VALUES (:org, :url, CAST(:types AS text[]), pgp_sym_encrypt(:secret, :key), :member)
                    RETURNING id, url, event_types, is_active, created_at, updated_at"""),
                {"org": context.organization_id, "url": body.url, "types": body.event_types,
                 "secret": secret, "key": get_settings().webhook_secret_key,
                 "member": context.organization_user_id},
            )).mappings().one()
            await audit.record_webhook_audit(
                self.db, context, webhook_id=row["id"], action=audit.CREATE_WEBHOOK, payload=_payload(row, full=True))
        return {**dict(row), "secret": secret}

    async def update(self, context, webhook_id: UUID, body: UpdateWebhookRequest) -> dict:
        async with self.db.begin():
            await self._enter(context)
            current = await self._managed(context, webhook_id)
            url = body.url if body.url is not None else current["url"]
            types = body.event_types if body.event_types is not None else sorted(current["event_types"])
            active = body.is_active if body.is_active is not None else current["is_active"]
            row = (await self.db.execute(
                text("""UPDATE organization_webhooks
                    SET url = :url, event_types = CAST(:types AS text[]), is_active = :active,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND organization_id = :org RETURNING id, url, event_types, is_active, created_at, updated_at"""),
                {"id": webhook_id, "org": context.organization_id, "url": url, "types": types, "active": active},
            )).mappings().one()
            if not active and current["is_active"]:
                await self.db.execute(text("SELECT discard_webhook_deliveries(:id)"), {"id": webhook_id})
            changed = url != current["url"] or types != sorted(current["event_types"])
            if changed:
                await audit.record_webhook_audit(
                    self.db, context, webhook_id=webhook_id, action=audit.UPDATE_WEBHOOK,
                    payload=_payload(row, full=True))
            if active != current["is_active"]:
                await audit.record_webhook_audit(
                    self.db, context, webhook_id=webhook_id, action=audit.SET_WEBHOOK_ACTIVE,
                    payload=_payload(row, full=True))
        return dict(row)

    async def delete(self, context, webhook_id: UUID) -> None:
        async with self.db.begin():
            await self._enter(context)
            current = await self._managed(context, webhook_id)
            await self.db.execute(text("SELECT discard_webhook_deliveries(:id)"), {"id": webhook_id})
            await self.db.execute(
                text("DELETE FROM organization_webhooks WHERE id = :id AND organization_id = :org"),
                {"id": webhook_id, "org": context.organization_id},
            )
            await audit.record_webhook_audit(
                self.db, context, webhook_id=webhook_id, action=audit.DELETE_WEBHOOK,
                payload=_payload(current, full=False))

    async def rotate(self, context, webhook_id: UUID) -> dict:
        secret = generate_secret()
        async with self.db.begin():
            await self._enter(context)
            current = await self._managed(context, webhook_id)
            await self.db.execute(
                text("""UPDATE organization_webhooks
                    SET secret_encrypted = pgp_sym_encrypt(:secret, :key), updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND organization_id = :org"""),
                {"id": webhook_id, "org": context.organization_id, "secret": secret,
                 "key": get_settings().webhook_secret_key},
            )
            await audit.record_webhook_audit(
                self.db, context, webhook_id=webhook_id, action=audit.ROTATE_WEBHOOK_SECRET,
                payload=_payload(current, full=False))
        return {"secret": secret}

    async def send_test(self, context, webhook_id: UUID) -> dict:
        async with self.db.begin():
            await self._enter(context)
            try:
                delivery = (await self.db.execute(
                    text("SELECT enqueue_webhook_test(:id)"), {"id": webhook_id},
                )).scalar_one()
            except DBAPIError as error:
                _raise_domain(error)
        return {"delivery_id": delivery}

    async def deliveries(self, context, webhook_id: UUID) -> list[dict]:
        async with self.db.begin():
            await self._enter(context)
            exists = (await self.db.execute(
                text("SELECT EXISTS (SELECT 1 FROM organization_webhooks WHERE id = :id AND organization_id = :org)"),
                {"id": webhook_id, "org": context.organization_id},
            )).scalar_one()
            if not exists:
                raise WebhookNotFound
            rows = (await self.db.execute(
                text("""SELECT id, event_type, created_at, attempts, last_status_code, status
                    FROM webhook_deliveries
                    WHERE webhook_id = :id AND organization_id = :org
                      AND created_at >= CURRENT_TIMESTAMP - make_interval(days => :days)
                    ORDER BY created_at DESC, id DESC LIMIT :limit"""),
                {"id": webhook_id, "org": context.organization_id, "days": DELIVERY_DAYS, "limit": DELIVERY_PAGE},
            )).mappings().all()
        return [dict(row) for row in rows]
