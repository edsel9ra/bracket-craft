import json
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.permissions import require_administrative_resolution, require_permission
from app.core.tenancy import AuthContext
from app.modules.matches.audit import record_match_audit
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.matches.service import load_report_payload_snapshot, validate_report_payload
from app.modules.rectifications.schemas import (
    CreateRectificationRequest,
    RectificationResponse,
    ReportContentResponse,
    ReportEventResponse,
    ReportVersionResponse,
)


class RectificationConflict(HTTPException):
    def __init__(self, code: str, detail: str):
        super().__init__(status_code=409, detail=detail)
        self.code = code


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
                snapshot = await load_report_payload_snapshot(self.db, context, match, payload.proposed_report)
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
            return await self._request(context, request_id)

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
