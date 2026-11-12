import json
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.permissions import require_administrative_resolution, require_permission
from app.core.tenancy import AuthContext
from app.modules.matches.audit import record_match_audit
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import derive_walkover_score, load_report_payload_snapshot, validate_report_payload
from app.modules.rectifications.diff import diff_reports
from app.modules.rectifications.schemas import (
    CreateRectificationRequest,
    RectificationDecisionRequest,
    RectificationResponse,
    ReportContentResponse,
    ReportEventResponse,
    ReportVersionResponse,
)


class RectificationConflict(HTTPException):
    def __init__(self, code: str, detail: str):
        super().__init__(status_code=409, detail=detail)
        self.code = code


class RectificationSelfApproval(HTTPException):
    def __init__(self):
        super().__init__(status_code=403, detail="El solicitante no puede decidir su propia solicitud")
        self.code = "RECTIFICATION_SELF_APPROVAL"


def _self_approval_violation(exc: DBAPIError) -> bool:
    error = exc.orig
    while error is not None:
        if (getattr(error, "sqlstate", None) == "42501"
                and getattr(error, "message", None) == "RECTIFICATION_SELF_APPROVAL"):
            return True
        error = error.__cause__
    return False


def _already_open() -> RectificationConflict:
    return RectificationConflict("RECTIFICATION_ALREADY_OPEN", "El partido ya tiene una solicitud pendiente")


def _pending_collision(exc: IntegrityError) -> bool:
    error = exc.orig
    while error is not None:
        if (getattr(error, "sqlstate", None) == "23505"
                and getattr(error, "constraint_name", None) == "uq_match_report_pending_request"):
            return True
        error = error.__cause__
    return False


def _canonical_events(events) -> list[str]:
    fields = MatchEventPayload.model_fields
    normalized = []
    for event in events:
        value = {key: event.get(key) for key in fields}
        value["client_event_id"] = value["client_event_id"].lower()
        value["metadata"] = value["metadata"] or {}
        value["added_minute"] = value["added_minute"] or 0
        normalized.append(json.dumps(value, sort_keys=True, default=str))
    return sorted(normalized)


def _same_report(current: Mapping[str, Any], events, payload: CloseMatchReportDTO, outcome) -> bool:
    proposed = {
        "resolution_type": payload.resolution_type,
        "resolution_reason": payload.reason,
        "home_score_regular": payload.home_score_regular if payload.home_score_regular is not None else outcome.home_score,
        "away_score_regular": payload.away_score_regular if payload.away_score_regular is not None else outcome.away_score,
        "home_score": outcome.home_score,
        "away_score": outcome.away_score,
        "home_penalties": outcome.home_penalties,
        "away_penalties": outcome.away_penalties,
        "winner_team_id": outcome.winner_team_id,
    }
    return (all(current[key] == value for key, value in proposed.items())
            and _canonical_events(events) == _canonical_events(payload.model_dump()["events"]))


async def apply_effects(db: AsyncSession, context: AuthContext, version: Mapping[str, Any], now: datetime) -> list[dict]:
    return []


def _proposal_report(match, payload):
    report = payload.model_dump()
    report["resolution_reason"] = report.pop("reason")
    if payload.resolution_type == "walkover":
        pair = derive_walkover_score(match["rules_config"], match["stage_id"],
            match["home_team_id"], match["away_team_id"], payload.winner_team_id)
        if pair is not None:
            for field, value in (("home_score_regular", pair.home_score), ("away_score_regular", pair.away_score),
                                 ("home_score", pair.home_score), ("away_score", pair.away_score)):
                if report[field] is None:
                    report[field] = value
    for side in ("home", "away"):
        if report[f"{side}_score"] is None:
            report[f"{side}_score"] = report[f"{side}_score_regular"]
    if payload.resolution_type == "regular" and report["winner_team_id"] is None:
        home, away = report["home_score"], report["away_score"]
        if home is not None and away is not None and home != away:
            report["winner_team_id"] = match["home_team_id"] if home > away else match["away_team_id"]
    return report


class RectificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _match(self, context: AuthContext, match_id: UUID, *, lock: bool = False) -> dict:
        query = """
            SELECT m.id, m.tournament_id, m.tournament_version_id, m.stage_id,
                m.home_team_id, m.away_team_id, m.match_date, m.matchday, m.bracket_code,
                m.status, m.result_confirmed, tv.status AS version_status, tv.rules_config
            FROM matches m
            JOIN tournament_versions tv ON tv.id = m.tournament_version_id
                AND tv.organization_id = m.organization_id
            WHERE m.id = :match_id AND m.organization_id = :organization_id
        """
        if lock:
            query += " FOR UPDATE OF m"
        row = (await self.db.execute(text(query), {
            "match_id": match_id, "organization_id": context.organization_id,
        })).mappings().one_or_none()
        if row is None:
            raise LookupError("Partido no encontrado")
        match = dict(row)
        current = (await self.db.execute(text("""
            SELECT * FROM v_match_current_report
            WHERE match_id = :match_id AND organization_id = :organization_id
        """), {"match_id": match_id, "organization_id": context.organization_id})).mappings().one()
        match.update(current)
        rules = dict(match["rules_config"])
        override = rules.get("stage_overrides", {}).get(str(match["stage_id"]), {})
        if override:
            rules["stage_defaults"] = {**rules["stage_defaults"], **override}
        match["rules_config"] = rules
        return match

    async def create(self, context: AuthContext, match_id: UUID, payload: CreateRectificationRequest) -> dict:
        try:
            async with self.db.begin():
                await set_rls_context(self.db, context.organization_id, context.user_id)
                match = await self._match(context, match_id, lock=True)
                await require_permission(self.db, context, "REQUEST_MATCH_REPORT_RECTIFICATION")
                if payload.proposed_report.resolution_type in {"walkover", "administrative"}:
                    await require_administrative_resolution(self.db, context, match_id)
                self._require_confirmed(match)
                if match["version_status"] == "archived":
                    raise RectificationConflict("TOURNAMENT_ARCHIVED", "El torneo está archivado")
                pending = (await self.db.execute(text("""
                    SELECT id FROM match_report_rectification_requests
                    WHERE match_id = :match_id AND organization_id = :organization_id AND status = 'pending'
                """), {"match_id": match_id, "organization_id": context.organization_id})).scalar_one_or_none()
                if pending is not None:
                    raise _already_open()
                snapshot = await load_report_payload_snapshot(self.db, context, match, payload.proposed_report,
                    exclude_suspensions_from_match_id=match["id"])
                outcome = validate_report_payload(snapshot, payload.proposed_report, datetime.now(timezone.utc))
                events = (await self.db.execute(text("""
                    SELECT * FROM v_match_current_events
                    WHERE match_id = :match_id AND organization_id = :organization_id
                """), {"match_id": match_id, "organization_id": context.organization_id})).mappings().all()
                if _same_report(match, events, payload.proposed_report, outcome):
                    raise RectificationConflict("RECTIFICATION_NO_CHANGES", "La propuesta no cambia el acta vigente")
                request = await self._insert_request(context, match_id, match["version_number"], payload)
                await record_match_audit(self.db, organization_id=context.organization_id,
                    member_id=context.organization_user_id, match_id=match_id,
                    action="REQUEST_MATCH_REPORT_RECTIFICATION", payload={
                        "request_id": request["id"], "base_version_number": match["version_number"],
                    })
                return request
        except IntegrityError as exc:
            if _pending_collision(exc):
                raise _already_open() from exc
            raise

    async def _insert_request(self, context, match_id, base_version_number, payload) -> dict:
        row = (await self.db.execute(text("""
            INSERT INTO match_report_rectification_requests (organization_id, match_id,
                base_version_number, proposed_report, reason, evidence,
                requested_by_user_id, requested_by_member_id)
            VALUES (:organization_id, :match_id, :base_version_number, CAST(:report AS jsonb),
                :reason, :evidence, :user_id, :member_id) RETURNING *
        """), {"organization_id": context.organization_id, "match_id": match_id,
            "base_version_number": base_version_number,
            "report": payload.proposed_report.model_dump_json(), "reason": payload.reason,
            "evidence": payload.evidence, "user_id": context.user_id,
            "member_id": context.organization_user_id})).mappings().one()
        return self._request_response(row)

    @staticmethod
    def _request_response(row) -> dict:
        return {key: row[key] for key in RectificationResponse.model_fields}

    async def list_requests(self, context: AuthContext, match_id: UUID) -> list[dict]:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            await self._match(context, match_id)
            rows = (await self.db.execute(text("""
                SELECT * FROM match_report_rectification_requests
                WHERE match_id = :match_id AND organization_id = :organization_id
                ORDER BY requested_at, id
            """), {"match_id": match_id, "organization_id": context.organization_id})).mappings().all()
            return [self._request_response(row) for row in rows]

    async def _request(self, context: AuthContext, request_id: UUID, *, lock: bool = False) -> dict:
        query = """
            SELECT * FROM match_report_rectification_requests
            WHERE id = :request_id AND organization_id = :organization_id
        """
        if lock:
            query += " FOR UPDATE"
        row = (await self.db.execute(text(query), {
            "request_id": request_id, "organization_id": context.organization_id,
        })).mappings().one_or_none()
        if row is None:
            raise LookupError("Solicitud no encontrada")
        return self._request_response(row)

    async def get_request(self, context: AuthContext, request_id: UUID) -> dict:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            request = await self._request(context, request_id)
            match = await self._match(context, request["match_id"])
            current = await self._version(context, request["match_id"], match["version_number"])
            proposal = _proposal_report(match, CloseMatchReportDTO.model_validate(request["proposed_report"]))
            return {**request, "diff": diff_reports(current["report"], proposal)}

    @staticmethod
    def _require_pending(request):
        if request["status"] != "pending":
            raise RectificationConflict("RECTIFICATION_NOT_PENDING", "La solicitud no está pendiente")

    async def _approval_permission(self, context, request):
        await require_permission(self.db, context, "APPROVE_MATCH_REPORT_RECTIFICATION")
        if request["proposed_report"]["resolution_type"] in {"walkover", "administrative"}:
            await require_administrative_resolution(self.db, context, request["match_id"])

    async def preview(self, context: AuthContext, request_id: UUID) -> dict:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            savepoint = await self.db.begin_nested()
            try:
                request = await self._request(context, request_id, lock=True)
                match = await self._match(context, request["match_id"], lock=True)
                self._require_pending(request)
                await self._approval_permission(context, request)
                result = await self._publish(context, request, match, datetime.now(timezone.utc))
                return {key: result[key] for key in ("version", "effects")}
            finally:
                await savepoint.rollback()

    @staticmethod
    def _require_distinct_actor(request, context):
        if request["requested_by_user_id"] == context.user_id:
            raise RectificationSelfApproval()

    async def decide(self, context: AuthContext, request_id: UUID, payload: RectificationDecisionRequest) -> dict:
        try:
            async with self.db.begin():
                await set_rls_context(self.db, context.organization_id, context.user_id)
                request = await self._request(context, request_id, lock=True)
                match = await self._match(context, request["match_id"], lock=True)
                return await self._decide_locked(context, request, match, payload)
        except DBAPIError as exc:
            if _self_approval_violation(exc):
                raise RectificationSelfApproval() from exc
            raise

    async def _decide_locked(self, context, request, match, payload, authorization=None):
        self._require_pending(request)
        self._require_distinct_actor(request, context)
        if authorization is None:
            await self._approval_permission(context, request)
        else:
            valid = (await self.db.execute(text("SELECT EXISTS (SELECT 1 FROM rectification_platform_scopes() WHERE id = :id)"),
                {"id": authorization["id"]})).scalar_one()
            if not valid:
                raise PermissionError("Autorización de plataforma requerida")
        now = datetime.now(timezone.utc)
        request_id = request["id"]
        decision_id = (await self.db.execute(text("""
                    INSERT INTO match_report_rectification_decisions (organization_id, request_id,
                        decision, reason, decided_by_user_id, decided_by_member_id, decided_as, decided_at, authorization_id)
                    VALUES (:organization_id, :request_id, :decision, :reason,
                        :user_id, :member_id, :decided_as, :now, :authorization_id) RETURNING id
                """), {"organization_id": context.organization_id, "request_id": request_id,
                    "decision": payload.decision, "reason": payload.reason, "user_id": context.user_id,
                    "member_id": context.organization_user_id, "now": now,
                    "decided_as": "member" if authorization is None else "platform_admin",
                    "authorization_id": authorization["id"] if authorization else None})).scalar_one()
        version_id, status = None, "rejected"
        if payload.decision == "approve":
            if match["version_number"] != payload.expected_base_version:
                raise RectificationConflict("RECTIFICATION_STALE", "La versión vigente ha cambiado")
            result = await self._publish(context, request, match, now)
            version_id, status = result["version_id"], "published"
        params = {"status": status, "version_id": version_id, "request_id": request_id,
            "organization_id": context.organization_id}
        audit = {"request_id": request_id, "decision_id": decision_id,
            "decision": payload.decision, "version_id": version_id}
        if authorization is not None:
            await self.db.execute(text("""
                INSERT INTO administrative_audit_logs (organization_id, entity_type, entity_id,
                    action, payload, performed_by_user_id)
                VALUES (:organization_id, 'matches', :match_id, 'DECIDE_MATCH_REPORT_RECTIFICATION',
                    CAST(:payload AS jsonb), :user_id)
            """), {"organization_id": context.organization_id, "match_id": request["match_id"],
                "user_id": context.user_id, "payload": json.dumps(audit, default=str)})
            await self.db.execute(text("SELECT record_rectification_platform_audit(:id)"), {"id": decision_id})
            row = (await self.db.execute(text("""
                WITH consumed AS (
                    UPDATE match_report_platform_authorizations SET consumed_at = :now
                    WHERE id = :authorization_id AND organization_id = :organization_id RETURNING id
                )
                UPDATE match_report_rectification_requests q
                SET status = :status, resulting_version_id = :version_id FROM consumed
                WHERE q.id = :request_id AND q.organization_id = :organization_id RETURNING q.*
            """), {**params, "now": now, "authorization_id": authorization["id"]})).mappings().one()
        else:
            row = (await self.db.execute(text("""
                    UPDATE match_report_rectification_requests
                    SET status = :status, resulting_version_id = :version_id
                    WHERE id = :request_id AND organization_id = :organization_id RETURNING *
                """), params)).mappings().one()
            await record_match_audit(self.db, organization_id=context.organization_id,
                member_id=context.organization_user_id, match_id=request["match_id"],
                action="DECIDE_MATCH_REPORT_RECTIFICATION", payload=audit)
        return self._request_response(row)

    async def _publish(self, context, request, match, now) -> dict:
        if match["version_number"] != request["base_version_number"]:
            raise RectificationConflict("RECTIFICATION_STALE", "La versión vigente ha cambiado")
        if match["version_status"] == "archived":
            raise RectificationConflict("TOURNAMENT_ARCHIVED", "El torneo está archivado")
        payload = CloseMatchReportDTO.model_validate(request["proposed_report"])
        snapshot = await load_report_payload_snapshot(self.db, context, match, payload,
            exclude_suspensions_from_match_id=match["id"])
        outcome = validate_report_payload(snapshot, payload, now)
        report = _proposal_report(match, payload)
        report.update(home_score=outcome.home_score, away_score=outcome.away_score,
            home_penalties=outcome.home_penalties, away_penalties=outcome.away_penalties,
            winner_team_id=outcome.winner_team_id)
        version = (await self.db.execute(text("""
            INSERT INTO match_report_versions (organization_id, match_id, version_number,
                supersedes_version_number, resolution_type, resolution_reason,
                home_score_regular, away_score_regular, home_score, away_score,
                home_penalties, away_penalties, winner_team_id, request_id,
                published_at, published_by_user_id)
            VALUES (:organization_id, :match_id, :number, :base, :resolution_type, :resolution_reason,
                :home_score_regular, :away_score_regular, :home_score, :away_score,
                :home_penalties, :away_penalties, :winner_team_id, :request_id, :now, :user_id)
            RETURNING *
        """), {**{key: value for key, value in report.items() if key != "events"},
            "organization_id": context.organization_id, "match_id": request["match_id"],
            "number": match["version_number"] + 1, "base": match["version_number"],
            "request_id": request["id"], "now": now, "user_id": context.user_id})).mappings().one()
        for event in payload.events:
            values = event.model_dump()
            values["client_event_id"] = values["client_event_id"].lower()
            values["metadata"] = json.dumps(event.metadata or {}, default=str)
            await self.db.execute(text("""
                INSERT INTO match_report_version_events (organization_id, version_id, match_id,
                    segment_id, team_id, beneficiary_team_id, player_id, event_type, minute,
                    added_minute, client_event_id, assist_player_id, player_out_id, player_in_id, metadata)
                VALUES (:organization_id, :version_id, :match_id, :segment_id, :team_id,
                    :beneficiary_team_id, :player_id, :event_type, :minute, :added_minute,
                    :client_event_id, :assist_player_id, :player_out_id, :player_in_id, CAST(:metadata AS jsonb))
            """), {**values, "organization_id": context.organization_id,
                "version_id": version["id"], "match_id": request["match_id"]})
        await self.db.execute(text("SELECT set_config('app.rectification_version_id', :version_id, true)"),
            {"version_id": str(version["id"])})
        effects = await apply_effects(self.db, context, version, now)
        return {"version_id": version["id"],
            "version": await self._version(context, request["match_id"], version["version_number"]),
            "effects": effects}

    async def withdraw(self, context: AuthContext, request_id: UUID) -> dict:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            request = await self._request(context, request_id, lock=True)
            if request["requested_by_user_id"] != context.user_id:
                raise PermissionError("Solo el solicitante puede retirar la solicitud")
            if request["status"] != "pending":
                raise RectificationConflict("RECTIFICATION_NOT_PENDING", "La solicitud no está pendiente")
            row = (await self.db.execute(text("""
                UPDATE match_report_rectification_requests SET status = 'withdrawn', withdrawn_at = :now
                WHERE id = :request_id AND organization_id = :organization_id RETURNING *
            """), {"now": datetime.now(timezone.utc), "request_id": request_id,
                "organization_id": context.organization_id})).mappings().one()
            return self._request_response(row)

    @staticmethod
    def _require_confirmed(match):
        if not match["result_confirmed"]:
            raise RectificationConflict("MATCH_NOT_CONFIRMED", "El acta no está confirmada")

    async def list_versions(self, context: AuthContext, match_id: UUID) -> list[dict]:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            match = await self._match(context, match_id)
            self._require_confirmed(match)
            return [await self._version(context, match_id, number)
                    for number in range(1, match["version_number"] + 1)]

    async def get_version(self, context: AuthContext, match_id: UUID, number: int) -> dict:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            match = await self._match(context, match_id)
            self._require_confirmed(match)
            return await self._version(context, match_id, number)

    async def _original_report(self, context: AuthContext, match_id: UUID) -> dict:
        row = (await self.db.execute(text("""
            SELECT m.resolution_type, m.resolution_reason, m.home_score_regular, m.away_score_regular,
                m.home_score, m.away_score, m.home_penalties, m.away_penalties, m.winner_team_id,
                a.performed_at AS published_at, ou.user_id AS published_by_user_id
            FROM matches m
            LEFT JOIN LATERAL (
                SELECT performed_at, performed_by_member_id FROM administrative_audit_logs
                WHERE organization_id = m.organization_id AND entity_type = 'matches'
                    AND entity_id = m.id AND action IN ('CLOSE_MATCH_REPORT', 'ADMINISTRATIVE_MATCH_RESOLUTION')
                ORDER BY performed_at, id LIMIT 1
            ) a ON TRUE
            LEFT JOIN organization_users ou ON ou.id = a.performed_by_member_id
                AND ou.organization_id = m.organization_id
            WHERE m.id = :match_id AND m.organization_id = :organization_id
        """), {"match_id": match_id, "organization_id": context.organization_id})).mappings().one()
        events = (await self.db.execute(text("""
            SELECT * FROM match_events WHERE match_id = :match_id AND organization_id = :organization_id
            ORDER BY minute, added_minute, created_at, id
        """), {"match_id": match_id, "organization_id": context.organization_id})).mappings().all()
        return self._version_response(match_id, 1, row, events)

    async def _version(self, context: AuthContext, match_id: UUID, number: int) -> dict:
        if number == 1:
            return await self._original_report(context, match_id)
        row = (await self.db.execute(text("""
            SELECT v.*, r.reason, r.evidence
            FROM match_report_versions v JOIN match_report_rectification_requests r
                ON r.id = v.request_id AND r.organization_id = v.organization_id AND r.match_id = v.match_id
            WHERE v.match_id = :match_id AND v.organization_id = :organization_id AND v.version_number = :number
        """), {"match_id": match_id, "organization_id": context.organization_id, "number": number})).mappings().one_or_none()
        if row is None:
            raise LookupError("Versión de acta no encontrada")
        events = (await self.db.execute(text("""
            SELECT * FROM match_report_version_events
            WHERE version_id = :version_id AND match_id = :match_id AND organization_id = :organization_id
            ORDER BY minute, added_minute, created_at, id
        """), {"version_id": row["id"], "match_id": match_id,
            "organization_id": context.organization_id})).mappings().all()
        return self._version_response(match_id, number, row, events)

    @staticmethod
    def _version_response(match_id, number, row, events) -> dict:
        report = {key: row[key] for key in ReportContentResponse.model_fields if key != "events"}
        report["events"] = [{key: event[key] for key in ReportEventResponse.model_fields} for event in events]
        return {"match_id": match_id, "version_number": number,
            **{key: row.get(key) for key in ReportVersionResponse.model_fields
               if key not in {"match_id", "version_number", "report"}}, "report": report}
