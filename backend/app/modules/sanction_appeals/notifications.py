from sqlalchemy import text

from app.modules.sanction_appeals.cases import SanctionCaseService


async def deliver_internal(db, event):
    async with db.begin():
        allowed = (await db.execute(text("SELECT deliver_sanction_notice(:id)"), {"id": event["id"]})).scalar_one()
    if not allowed:
        raise PermissionError("SANCTION_RECIPIENT_NOT_AUTHORIZED")


class SanctionNotificationService(SanctionCaseService):
    async def list(self, context, *, limit=50, offset=0):
        async with self.transaction(context):
            rows = (await self.db.execute(text("""SELECT sanction_internal_notice_payload(n.id) AS notice
                FROM sanction_notifications n
                JOIN sanction_notification_deliveries delivery ON delivery.notification_id=n.id
                    AND delivery.organization_id=n.organization_id AND delivery.outcome='delivered'
                WHERE n.organization_id=:org AND n.recipient_user_id=:user AND n.channel='internal'
                ORDER BY n.created_at DESC,n.id DESC LIMIT :limit OFFSET :offset"""),
                {"org": context.organization_id, "user": context.user_id, "limit": limit, "offset": offset})).mappings().all()
            return {"items": [row["notice"] for row in rows]}
