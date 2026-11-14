"""Transaction-local integration of reviewed live content with classic closure."""

import json

from fastapi import HTTPException
from sqlalchemy import text

from app.modules.matches.live_policy import review_fingerprint
from app.modules.matches.live_schemas import LiveEventPayload, LiveResultDTO
from app.modules.matches.schemas import CloseMatchReportDTO


async def read_live_events(db, context, match_id):
    rows = (
        (
            await db.execute(
                text("""
        SELECT client_event_id,event_type,team_id,beneficiary_team_id,player_id,
            player_out_id,player_in_id,assist_player_id,minute,added_minute,segment_id,metadata
        FROM match_live_events WHERE organization_id=:org AND match_id=:id AND removed_at IS NULL
        ORDER BY event_order,id
    """),
                {"org": context.organization_id, "id": match_id},
            )
        )
        .mappings()
        .all()
    )
    return [
        LiveEventPayload.model_validate(
            {**row, "client_event_id": str(row["client_event_id"])}
        )
        for row in rows
    ]


async def prepare_live_report(db, context, match, dto, session_id):
    if not match.get("live_schema_available"):
        raise HTTPException(409, "LIVE_REVIEW_STALE")
    state = (
        (
            await db.execute(
                text("""SELECT * FROM match_live_state
        WHERE organization_id=:org AND match_id=:match FOR UPDATE"""),
                {"org": context.organization_id, "match": match["id"]},
            )
        )
        .mappings()
        .one_or_none()
    )
    if state is None:
        if dto.live_review_id is not None:
            raise HTTPException(409, "LIVE_REVIEW_STALE")
        return None
    allowed = await db.scalar(
        text("SELECT match_live_has_permission(:org,:match,'VIEW_MATCH_LIVE_DRAFT')"),
        {"org": context.organization_id, "match": match["id"]},
    )
    if not allowed:
        raise PermissionError("Permiso requerido: VIEW_MATCH_LIVE_DRAFT")
    if dto.live_review_id is None:
        raise HTTPException(409, "LIVE_REVIEW_REQUIRED")
    active_session = await db.scalar(
        text("""SELECT 1 FROM user_sessions us
        JOIN users u ON u.id=us.user_id AND u.is_active
        WHERE us.id=:session AND us.user_id=:user AND us.revoked_at IS NULL
          AND us.expires_at > clock_timestamp()
          AND EXISTS (SELECT 1 FROM organization_users ou WHERE ou.organization_id=:org
            AND ou.id=:member AND ou.user_id=us.user_id AND ou.is_active)"""),
        {
            "session": session_id,
            "user": context.user_id,
            "org": context.organization_id,
            "member": context.organization_user_id,
        },
    )
    if not active_session:
        raise HTTPException(401, "Sesión no válida")
    review = (
        (
            await db.execute(
                text("""SELECT * FROM match_live_reviews
        WHERE id=:id AND organization_id=:org AND match_id=:match
          AND actor_user_id=:user AND session_id=:session"""),
                {
                    "id": dto.live_review_id,
                    "org": context.organization_id,
                    "match": match["id"],
                    "user": context.user_id,
                    "session": session_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    events = await read_live_events(db, context, match["id"])
    result = LiveResultDTO.model_validate(
        dto.model_dump(exclude={"events", "live_review_id"})
    )
    reviewed_result = review["result"] if review else None
    if isinstance(reviewed_result, str):
        reviewed_result = json.loads(reviewed_result)
    if (
        review is None
        or state["frozen_at"] is not None
        or review["content_revision"] != state["content_revision"]
        or reviewed_result != result.model_dump(mode="json", exclude={"events"})
        or review["fingerprint"]
        != review_fingerprint(tuple(events), result, state["content_revision"])
    ):
        raise HTTPException(409, "LIVE_REVIEW_STALE")
    return CloseMatchReportDTO.model_validate(
        {**result.model_dump(), "events": [event.model_dump() for event in events]}
    )


async def freeze_live_report(db, context, match_id):
    now = await db.scalar(text("SELECT clock_timestamp()"))
    await db.execute(
        text("""UPDATE match_live_state SET frozen_at=:now,updated_at=:now,
        updated_by_member_id=:member,
        clock_elapsed_us=clock_elapsed_us+CASE WHEN clock_state='running'
            THEN (GREATEST(0,EXTRACT(EPOCH FROM (CAST(:now AS timestamptz)-clock_anchor_at)))*1000000)::BIGINT
            ELSE 0 END,
        clock_anchor_at=NULL,clock_state=CASE WHEN clock_state='not_started' THEN 'not_started' ELSE 'paused' END
        WHERE match_id=:match AND organization_id=:org"""),
        {
            "now": now,
            "member": context.organization_user_id,
            "match": match_id,
            "org": context.organization_id,
        },
    )
