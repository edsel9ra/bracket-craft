from sqlalchemy import text

from app.core.outbox import enqueue_outbox


async def record_notification(db, context, request_id, version_id, channel, event_type, event_id, recipient=None):
    await db.execute(text("""INSERT INTO match_report_rectification_notifications
        (organization_id,request_id,version_id,channel,notification_type,recipient_user_id,outbox_event_id)
        VALUES (:org,:request,:version,:channel,:type,:recipient,:event)"""),
        {"org": context.organization_id, "request": request_id, "version": version_id,
            "channel": channel, "type": event_type, "recipient": recipient, "event": event_id})


async def enqueue_publication(db, context, version, now):
    payload = {"match_id": str(version["match_id"]), "tournament_id": str(version["tournament_id"]),
        "version_id": str(version["id"]), "scope": "organization"}
    effects = []
    for event_type in ("MATCH_UPDATED", "STANDINGS_UPDATED", "MATCH_REPORT_RECTIFIED"):
        event_id = await enqueue_outbox(db, context.organization_id, event_type, payload)
        await record_notification(db, context, version["request_id"], version["id"], "realtime", event_type, event_id)
        effects.append({"effect_type": "outbox", "entity_type": "outbox_event", "entity_id": str(event_id),
            "payload": {"event_type": event_type, **payload}})
    return effects


async def enqueue_decision_email(db, context, request, decision, reason, version_id):
    recipient = (await db.execute(text("SELECT email FROM users WHERE id=:id"),
        {"id": request["requested_by_user_id"]})).scalar_one()
    event_type = "RECTIFICATION_DECISION_EMAIL"
    event_id = await enqueue_outbox(db, context.organization_id, event_type,
        {"request_id": str(request["id"]), "recipient": recipient, "decision": decision, "reason": reason})
    await record_notification(db, context, request["id"], version_id, "email", event_type,
        event_id, request["requested_by_user_id"])
