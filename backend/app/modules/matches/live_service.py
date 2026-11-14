"""Internal F1 services. No router or production event producer mounts these."""

from contextlib import asynccontextmanager
from dataclasses import replace
from hashlib import sha256
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.locking import lock_discipline, lock_stage_and_version
from app.core.permissions import require_administrative_resolution
from app.modules.matches.live_policy import (
    ClockReference,
    LiveState,
    SegmentFacts,
    TransitionFacts,
    decide_live_transition,
    derive_provisional_score,
    reduce_clock,
    review_fingerprint,
)
from app.modules.matches.live_schemas import (
    LiveAccessResponse,
    LiveClockResponse,
    LiveCommandAck,
    LiveReportDTO,
    LiveResultDTO,
    LiveSnapshotResponse,
)
from app.modules.matches.live_close import read_live_events
from app.modules.matches.live_notices import enqueue_live_notices, public_live_key
from app.modules.matches.router import _load_operation_match
from app.modules.matches.service import (
    CloseMatchReportService,
    effective_match_minutes,
    effective_report_match,
    load_report_payload_snapshot,
    validate_event_minute,
    validate_report_payload,
)
from app.modules.rules_engine.engine import effective_substitutions
from app.modules.rules_engine.substitutions import SubstitutionLimits


def conflict(code):
    return HTTPException(status_code=409, detail=code)


class LiveMatchService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @asynccontextmanager
    async def _scope(self, context, match_id, session_id, *, write=False):
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            match = await _load_operation_match(
                self.db, context, match_id, False, False
            )
            if write:
                await lock_discipline(self.db, context.organization_id)
                await lock_stage_and_version(
                    self.db,
                    context.organization_id,
                    match["tournament_id"],
                    match["stage_id"],
                )
                match = await _load_operation_match(
                    self.db, context, match_id, False, True
                )
            else:
                await self.db.execute(
                    text(
                        "SELECT id FROM matches WHERE id=:id AND organization_id=:org FOR SHARE"
                    ),
                    {"id": match_id, "org": context.organization_id},
                )
                match = await _load_operation_match(
                    self.db, context, match_id, False, False
                )
            membership = await self.db.scalar(
                text("""
                SELECT 1 FROM organization_users ou
                WHERE ou.organization_id=:org AND ou.user_id=:user AND ou.id=:member
                    AND ou.is_active AND fn_verify_user_org_membership(:org)
            """),
                {
                    "org": context.organization_id,
                    "user": context.user_id,
                    "member": context.organization_user_id,
                },
            )
            if not membership:
                raise HTTPException(403, "Membresía no válida")
            session = await self.db.scalar(
                text("""
                SELECT 1 FROM user_sessions us
                WHERE us.id=:session AND us.user_id=:user AND us.revoked_at IS NULL
                    AND us.expires_at > clock_timestamp()
            """),
                {"session": session_id, "user": context.user_id},
            )
            if not session:
                raise HTTPException(401, "Sesión no válida")
            now = await self.db.scalar(text("SELECT clock_timestamp()"))
            yield match, now

    async def _allowed(self, context, match_id, permission):
        return bool(
            await self.db.scalar(
                text("SELECT match_live_has_permission(:org,:match,:permission)"),
                {
                    "org": context.organization_id,
                    "match": match_id,
                    "permission": permission,
                },
            )
        )

    async def _require(self, context, match_id, permission):
        if not await self._allowed(context, match_id, permission):
            raise HTTPException(403, "Permiso requerido")

    async def _available(self, match):
        published = await self.db.scalar(
            text("SELECT published_version_id FROM tournaments WHERE id=:id"),
            {"id": match["tournament_id"]},
        )
        return bool(
            match["version_status"] == "published"
            and published == match["tournament_version_id"]
            and not match["result_confirmed"]
            and match["status"] in {"scheduled", "live", "suspended"}
            and match["home_team_id"]
            and match["away_team_id"]
            and match["home_team_id"] != match["away_team_id"]
        )

    async def access(self, context, match_id, session_id):
        async with self._scope(context, match_id, session_id) as (match, _):
            return LiveAccessResponse(
                can_view=await self._allowed(
                    context, match_id, "VIEW_MATCH_LIVE_DRAFT"
                ),
                can_operate=await self._allowed(
                    context, match_id, "OPERATE_MATCH_LIVE"
                ),
                can_close=await self._allowed(context, match_id, "CLOSE_MATCH_REPORT"),
                available=await self._available(match),
            )

    async def _state(self, context, match_id):
        row = (
            (
                await self.db.execute(
                    text(
                        "SELECT * FROM match_live_state WHERE match_id=:id AND organization_id=:org"
                    ),
                    {"id": match_id, "org": context.organization_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def _events(self, context, match_id):
        return await read_live_events(self.db, context, match_id)

    async def _clock(self, state):
        if state is None or state["clock_state"] == "not_started":
            return None
        number = await self.db.scalar(
            text("SELECT segment_number FROM match_segments WHERE id=:id"),
            {"id": state["segment_id"]},
        )
        return ClockReference(
            state["segment_id"],
            number,
            state["clock_elapsed_us"],
            state["clock_state"],
            state["clock_anchor_at"],
        )

    async def snapshot(self, context, match_id, session_id):
        async with self._scope(context, match_id, session_id) as (match, now):
            await self._require(context, match_id, "VIEW_MATCH_LIVE_DRAFT")
            state = await self._state(context, match_id)
            if state is None:
                return LiveSnapshotResponse(initialized=False, status=match["status"])
            clock = await self._clock(state)
            reference = (
                LiveClockResponse(state="not_started", observed_at=now)
                if clock is None
                else LiveClockResponse(
                    state=clock.state,
                    segment_id=clock.segment_id,
                    segment_number=clock.segment_number,
                    elapsed_us=clock.elapsed_us,
                    anchor_at=clock.anchor_at,
                    observed_at=now,
                )
            )
            return LiveSnapshotResponse(
                initialized=True,
                status=match["status"],
                revision=state["revision"],
                content_revision=state["content_revision"],
                home_score=state["home_score"],
                away_score=state["away_score"],
                events=await self._events(context, match_id),
                clock=reference,
            )

    async def _save_state(self, context, match_id, state, clock, now):
        await self.db.execute(
            text("""
            UPDATE match_live_state SET revision=:revision,content_revision=:content_revision,
                home_score=:home_score,away_score=:away_score,segment_id=:segment_id,
                clock_state=:clock_state,clock_elapsed_us=:elapsed,clock_anchor_at=:anchor,
                updated_at=:now,updated_by_member_id=:member
            WHERE organization_id=:org AND match_id=:id
        """),
            {
                **state,
                "org": context.organization_id,
                "id": match_id,
                "member": context.organization_user_id,
                "now": now,
                "segment_id": clock.segment_id if clock else None,
                "clock_state": clock.state if clock else "not_started",
                "elapsed": clock.elapsed_us if clock else 0,
                "anchor": clock.anchor_at if clock else None,
            },
        )

    async def _set_status(self, context, match_id, status):
        await self.db.execute(
            text(
                "UPDATE matches SET status=:status WHERE id=:id AND organization_id=:org"
            ),
            {"status": status, "id": match_id, "org": context.organization_id},
        )

    async def execute(self, context, match_id, session_id, command):
        try:
            async with self._scope(context, match_id, session_id, write=True) as (
                match,
                now,
            ):
                await self._require(context, match_id, "OPERATE_MATCH_LIVE")
                body = command.model_dump(mode="json")
                digest = sha256(
                    json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                accepted = (
                    (
                        await self.db.execute(
                            text("""
                    SELECT request_hash,revision,session_id FROM match_live_commands
                    WHERE organization_id=:org AND match_id=:id AND command_id=:command
                """),
                            {
                                "org": context.organization_id,
                                "id": match_id,
                                "command": command.command_id,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if accepted:
                    if (
                        accepted["request_hash"] != digest
                        or accepted["session_id"] != session_id
                    ):
                        raise conflict("LIVE_COMMAND_IDENTITY_CONFLICT")
                    return LiveCommandAck(
                        command_id=command.command_id, revision=accepted["revision"]
                    )
                if not await self._available(match):
                    raise conflict("LIVE_MATCH_NOT_AVAILABLE")
                state = await self._state(context, match_id)
                if state and state["frozen_at"]:
                    raise conflict("LIVE_DRAFT_FROZEN")
                if command.expected_revision != (state["revision"] if state else 0):
                    raise conflict("LIVE_REVISION_CONFLICT")
                clock = await self._clock(state)
                previous_public = public_live_key(match["status"], state, clock, now)
                target = match["status"]
                if command.type in {"start", "suspend", "resume"}:
                    try:
                        transition = decide_live_transition(
                            LiveState(match["status"], clock),
                            command.type,
                            TransitionFacts(
                                True, match["home_team_id"], match["away_team_id"]
                            ),
                            now,
                        )
                    except ValueError as exc:
                        raise conflict("LIVE_INVALID_TRANSITION") from exc
                    target, clock = transition.status, transition.clock
                    if target == "live":
                        await self._set_status(context, match_id, target)
                elif match["status"] != "live":
                    raise conflict("LIVE_MATCH_NOT_EDITABLE")
                if state is None:
                    await self.db.execute(
                        text("""INSERT INTO match_live_state(organization_id,match_id,updated_by_member_id)
                        VALUES (:org,:id,:member)"""),
                        {
                            "org": context.organization_id,
                            "id": match_id,
                            "member": context.organization_user_id,
                        },
                    )
                    state = await self._state(context, match_id)
                if command.type in {
                    "start_clock",
                    "pause_clock",
                    "resume_clock",
                    "correct_clock",
                }:
                    segment_id = getattr(command, "segment_id", None) or (
                        clock.segment_id if clock else None
                    )
                    segment = (
                        (
                            await self.db.execute(
                                text("""SELECT id,segment_number,status FROM match_segments
                        WHERE organization_id=:org AND match_id=:match AND id=:id FOR UPDATE"""),
                                {
                                    "org": context.organization_id,
                                    "match": match_id,
                                    "id": segment_id,
                                },
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if not segment:
                        raise conflict("LIVE_CLOCK_SEGMENT_NOT_ACTIVE")
                    clock = reduce_clock(
                        clock,
                        command,
                        now,
                        SegmentFacts(
                            match["status"],
                            segment_id,
                            segment["segment_number"],
                            segment["status"] == "active",
                        ),
                    )
                if command.type in {"add_event", "correct_event", "remove_event"}:
                    await self._change_event(
                        context, match_id, match, command, now, state
                    )
                    state["content_revision"] += 1
                state["revision"] += 1
                await self._save_state(context, match_id, state, clock, now)
                if target == "suspended":
                    await self._set_status(context, match_id, target)
                await self._record_command(
                    context, match_id, session_id, command, digest, state["revision"]
                )
                await enqueue_live_notices(
                    self.db, context, match,
                    public_changed=previous_public != public_live_key(target, state, clock, now),
                )
                return LiveCommandAck(
                    command_id=command.command_id, revision=state["revision"]
                )
        except (ValueError, LookupError) as exc:
            raise HTTPException(422, "Contenido live no válido") from exc
        except IntegrityError as exc:
            raise conflict("LIVE_COMMAND_CONFLICT") from exc

    async def _record_command(
        self, context, match_id, session_id, command, digest, revision
    ):
        await self.db.execute(
            text("""INSERT INTO match_live_commands
            (organization_id,match_id,command_id,actor_user_id,session_id,request_hash,command_type,revision)
            VALUES (:org,:match,:command,:user,:session,:hash,:type,:revision)"""),
            {
                "org": context.organization_id,
                "match": match_id,
                "command": command.command_id,
                "user": context.user_id,
                "session": session_id,
                "hash": digest,
                "type": command.type,
                "revision": revision,
            },
        )
        await self.db.execute(
            text("""INSERT INTO administrative_audit_logs
            (organization_id,entity_type,entity_id,action,payload,performed_by_member_id)
            VALUES (:org,'matches',:match,'MATCH_LIVE_COMMAND',CAST(:payload AS jsonb),:member)"""),
            {
                "org": context.organization_id,
                "match": match_id,
                "member": context.organization_user_id,
                "payload": json.dumps(
                    {
                        "command_id": str(command.command_id),
                        "type": command.type,
                        "revision": revision,
                    }
                ),
            },
        )

    async def _validated_report(self, context, match, events, result, now):
        match = effective_report_match(match)
        report = LiveReportDTO.model_validate(
            {**result.model_dump(mode="python", exclude={"events"}), "events": events}
        )
        snapshot = await load_report_payload_snapshot(
            self.db, context, match, report, require_active_segment=True
        )
        snapshot = replace(
            snapshot,
            active_segment_id=next(
                (
                    segment["id"]
                    for segment in snapshot.segments
                    if segment["status"] == "active"
                ),
                None,
            ),
            segments=tuple(
                {
                    **segment,
                    "status": "completed"
                    if segment["status"] == "interrupted"
                    else segment["status"],
                }
                for segment in snapshot.segments
            ),
        )
        validate_report_payload(snapshot, report, now)
        return report

    async def _change_event(self, context, match_id, match, command, now, state):
        events = await self._events(context, match_id)
        position = len(events)
        if command.type != "add_event":
            old = next(
                (
                    event
                    for event in events
                    if UUID(event.client_event_id) == command.event_id
                ),
                None,
            )
            if old is None:
                raise conflict("LIVE_EVENT_NOT_FOUND")
            segment_id = old.segment_id
            position = events.index(old)
            events.remove(old)
            if (
                command.type == "correct_event"
                and command.event.client_event_id != old.client_event_id
            ):
                raise conflict("LIVE_EVENT_IDENTITY_CONFLICT")
        else:
            segment_id = command.event.segment_id
        ids = {segment_id}
        if command.type != "remove_event":
            ids.add(command.event.segment_id)
            events.insert(position, command.event)
        for segment_id in sorted(ids, key=str):
            segment_status = await self.db.scalar(
                text("""SELECT status FROM match_segments WHERE id=:id
                AND match_id=:match AND organization_id=:org FOR UPDATE"""),
                {"id": segment_id, "match": match_id, "org": context.organization_id},
            )
            requires_active = (
                command.type == "add_event" or segment_id != old.segment_id
            )
            if not segment_status or (requires_active and segment_status != "active"):
                raise conflict("LIVE_EVENT_SEGMENT_NOT_ACTIVE")
        if len(events) > 500:
            raise conflict("LIVE_EVENT_LIMIT")
        home, away = derive_provisional_score(
            tuple(events),
            match["rules_config"],
            (match["home_team_id"], match["away_team_id"]),
        )
        result = LiveResultDTO(
            resolution_type="regular", home_score_regular=home, away_score_regular=away
        )
        report = LiveReportDTO(**result.model_dump(exclude={"events"}), events=events)
        rosters = await CloseMatchReportService(self.db)._load_match_rosters(
            context, match_id
        )
        ineligible = await self.db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM match_live_ineligible_players(:match,:players,:now))"
            ),
            {
                "match": match_id,
                "players": sorted({row["player_id"] for row in rosters}, key=str),
                "now": now,
            },
        )
        snapshot = await load_report_payload_snapshot(
            self.db,
            context,
            match,
            report,
            rosters=rosters,
            has_suspended_players=ineligible,
        )
        minutes = effective_match_minutes(match["rules_config"], match["stage_id"])
        segments = {segment["id"]: segment for segment in snapshot.segments}
        for event in events:
            segment = segments.get(event.segment_id)
            if (
                segment is None
                or event.minute < segment["minute_start"]
                or (
                    segment["minute_end"] is not None
                    and event.minute > segment["minute_end"]
                )
            ):
                raise ValueError("Minuto fuera del segmento")
            validate_event_minute(
                event.minute, event.added_minute, maximum=minutes["max_minute"]
            )
        validators = CloseMatchReportService
        validators._validate_event_participants(report, match, snapshot.rosters)
        validators._validate_rosters(match, snapshot.rosters)
        validators._validate_substitutions(
            report,
            match,
            snapshot.rosters,
            SubstitutionLimits.from_config(
                effective_substitutions(match["rules_config"])
            ),
        )
        validators._validate_double_yellow(report)
        if snapshot.has_suspended_players:
            raise ValueError("La planilla contiene un jugador suspendido")
        if command.type == "remove_event":
            await self.db.execute(
                text("""UPDATE match_live_events SET removed_at=:now WHERE organization_id=:org
                AND match_id=:match AND client_event_id=:event AND removed_at IS NULL"""),
                {
                    "now": now,
                    "org": context.organization_id,
                    "match": match_id,
                    "event": command.event_id,
                },
            )
        else:
            event = command.event.model_dump(mode="python")
            values = {
                **event,
                "metadata": json.dumps(event["metadata"] or {}),
                "client_event_id": UUID(event["client_event_id"]),
                "org": context.organization_id,
                "match": match_id,
            }
            if command.type == "add_event":
                await self.db.execute(
                    text("""INSERT INTO match_live_events
                    (organization_id,match_id,client_event_id,event_type,team_id,beneficiary_team_id,player_id,
                     player_out_id,player_in_id,assist_player_id,minute,added_minute,segment_id,metadata)
                    VALUES (:org,:match,:client_event_id,:event_type,:team_id,:beneficiary_team_id,:player_id,
                     :player_out_id,:player_in_id,:assist_player_id,:minute,:added_minute,:segment_id,CAST(:metadata AS jsonb))"""),
                    values,
                )
            else:
                await self.db.execute(
                    text("""UPDATE match_live_events SET event_type=:event_type,team_id=:team_id,
                    beneficiary_team_id=:beneficiary_team_id,player_id=:player_id,player_out_id=:player_out_id,
                    player_in_id=:player_in_id,assist_player_id=:assist_player_id,minute=:minute,added_minute=:added_minute,
                    segment_id=:segment_id,metadata=CAST(:metadata AS jsonb)
                    WHERE organization_id=:org AND match_id=:match AND client_event_id=:client_event_id AND removed_at IS NULL"""),
                    values,
                )
        state["home_score"], state["away_score"] = home, away

    async def create_review(self, context, match_id, session_id, request):
        try:
            async with self._scope(context, match_id, session_id, write=True) as (
                match,
                now,
            ):
                await self._require(context, match_id, "VIEW_MATCH_LIVE_DRAFT")
                await self._require(context, match_id, "CLOSE_MATCH_REPORT")
                if request.result.resolution_type == "administrative":
                    await require_administrative_resolution(self.db, context, match_id)
                state = await self._state(context, match_id)
                if (
                    not state
                    or state["frozen_at"]
                    or match["status"] != "live"
                    or not await self._available(match)
                ):
                    raise conflict("LIVE_MATCH_NOT_EDITABLE")
                if request.expected_content_revision != state["content_revision"]:
                    raise conflict("LIVE_CONTENT_REVISION_CONFLICT")
                events = await self._events(context, match_id)
                report = await self._validated_report(
                    context, match, events, request.result, now
                )
                review_id = uuid4()
                result = request.result.model_dump(mode="json", exclude={"events"})
                fingerprint = review_fingerprint(
                    tuple(events), request.result, state["content_revision"]
                )
                await self.db.execute(
                    text("""INSERT INTO match_live_reviews
                    (id,organization_id,match_id,actor_user_id,session_id,content_revision,fingerprint,result)
                    VALUES (:id,:org,:match,:user,:session,:revision,:fingerprint,CAST(:result AS jsonb))"""),
                    {
                        "id": review_id,
                        "org": context.organization_id,
                        "match": match_id,
                        "user": context.user_id,
                        "session": session_id,
                        "revision": state["content_revision"],
                        "fingerprint": fingerprint,
                        "result": json.dumps(result),
                    },
                )
                return {
                    "live_review_id": review_id,
                    "content_revision": state["content_revision"],
                    "report": report,
                    "fingerprint": fingerprint,
                }
        except PermissionError as exc:
            raise HTTPException(403, "Permiso requerido") from exc
        except (ValueError, LookupError) as exc:
            raise HTTPException(422, "Resultado de revisión no válido") from exc
