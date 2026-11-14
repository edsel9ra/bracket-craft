"""Minimal transactional notices, used only by unmounted live commands."""

from app.core.outbox import enqueue_outbox
from app.modules.matches.live_policy import observe_clock


def public_live_key(status, state, clock, observed_at):
    observation = observe_clock(clock, observed_at)
    return (
        status,
        state["home_score"] if state else None,
        state["away_score"] if state else None,
        observation.segment_number,
        observation.elapsed_seconds,
        observation.state,
    )


async def enqueue_live_notices(db, context, match, *, public_changed):
    payload = {
        "match_id": str(match["id"]),
        "tournament_id": str(match["tournament_id"]),
    }
    await enqueue_outbox(
        db,
        context.organization_id,
        "MATCH_LIVE_UPDATED",
        {"scope": "organization", **payload},
    )
    if public_changed:
        await enqueue_outbox(
            db, context.organization_id, "MATCH_LIVE_PUBLIC_UPDATED", payload
        )
