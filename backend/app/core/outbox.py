import json

from sqlalchemy import text


OUTBOX_STREAM = "bracket_craft.events"
OUTBOX_STREAM_MAXLEN = 10_000


async def enqueue_outbox(session, organization_id, event_type, payload, *, return_id=True):
    statement = """INSERT INTO outbox_events (organization_id, event_type, payload)
        VALUES (:organization_id, :event_type, CAST(:payload AS jsonb))"""
    if return_id:
        statement += " RETURNING id"
    result = await session.execute(text(statement), {"organization_id": str(organization_id),
        "event_type": event_type, "payload": json.dumps(payload, default=str)})
    return result.scalar_one() if return_id else None
