import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import set_rls_context
from app.core.locking import lock_discipline, lock_matches, lock_stage_and_version, lock_version
from app.core.permissions import require_permission
from app.modules.sanction_appeals.repository import project_fact


class SanctionConflict(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def disciplinary_fingerprint(source):
    return {key: str(source[key]) if source[key] is not None else None for key in (
        "id", "player_id", "source_tournament_id", "scope_type", "matches_suspended",
        "source_type", "origin_match_id", "source_event_id", "source_version_event_id")}


class SanctionCaseService:
    def __init__(self, db):
        self.db = db

    @asynccontextmanager
    async def transaction(self, context, permission=None):
        try:
            async with self.db.begin():
                await set_rls_context(self.db, context.organization_id, context.user_id)
                if permission:
                    await require_permission(self.db, context, permission)
                yield
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "P0002":
                raise LookupError("Expediente no encontrado") from exc
            if getattr(exc.orig, "sqlstate", None) == "42501":
                raise PermissionError("Operación no autorizada") from exc
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise SanctionConflict("SANCTION_CASE_CONFLICT") from exc
            if getattr(exc.orig, "sqlstate", None) == "23514":
                error, code = exc.orig, "SANCTION_INVALID_STATE"
                while error is not None:
                    message = getattr(error, "message", "")
                    if message.startswith("SANCTION_") and message.replace("_", "").isalnum():
                        code = message
                        break
                    error = error.__cause__
                raise SanctionConflict(code) from exc
            raise

    async def source(self, context, suspension_id, *, lock=False):
        if lock:
            await lock_discipline(self.db, context.organization_id)
        source = (await self.db.execute(text("""SELECT ps.*, m.stage_id, m.tournament_version_id
            FROM player_suspensions ps LEFT JOIN matches m ON m.id=ps.origin_match_id
                AND m.organization_id=ps.organization_id
            WHERE ps.id=:id AND ps.organization_id=:org"""),
            {"id": suspension_id, "org": context.organization_id})).mappings().one_or_none()
        if source is None:
            raise LookupError("Sanción no encontrada")
        if lock:
            if source["origin_match_id"]:
                await lock_stage_and_version(self.db, context.organization_id,
                    source["source_tournament_id"], source["stage_id"])
            else:
                versions = (await self.db.execute(text("""SELECT id FROM tournament_versions
                    WHERE organization_id=:org AND tournament_id=:tournament ORDER BY id"""),
                    {"org": context.organization_id, "tournament": source["source_tournament_id"]})).scalars().all()
                for version in versions:
                    await lock_version(self.db, context.organization_id, version)
            matches = (await self.db.execute(text("""SELECT id FROM matches
                WHERE organization_id=:org AND tournament_id=:tournament ORDER BY id"""),
                {"org": context.organization_id, "tournament": source["source_tournament_id"]})).scalars().all()
            await lock_matches(self.db, context.organization_id, matches)
            source = (await self.db.execute(text("""SELECT * FROM player_suspensions
                WHERE id=:id AND organization_id=:org FOR UPDATE"""),
                {"id": suspension_id, "org": context.organization_id})).mappings().one()
        return dict(source)

    async def submit_appeal(self, context, payload):
        async with self.transaction(context, "SUBMIT_SANCTION_APPEALS"):
            source = await self.source(context, payload.suspension_id, lock=True)
            if payload.represented_player_id and payload.represented_player_id != source["player_id"]:
                raise ValueError("Representación no válida")
            if payload.represented_team_id:
                represented = (await self.db.execute(text("""SELECT 1 FROM rosters
                    WHERE organization_id=:org AND tournament_id=:tournament
                        AND player_id=:player AND team_id=:team LIMIT 1"""),
                    {"org": context.organization_id, "tournament": source["source_tournament_id"],
                        "player": source["player_id"], "team": payload.represented_team_id})).scalar_one_or_none()
                if represented is None:
                    raise ValueError("Representación no válida")
            return await self._submit(context, payload, source, "appeal")

    async def _submit(self, context, payload, source, kind):
        if source["status"] == "cancelled":
            raise SanctionConflict("SANCTION_CANCELLED")
        case_id = uuid4()
        values = {"id": case_id, "org": context.organization_id, "suspension": source["id"],
            "kind": kind, "user": context.user_id, "member": context.organization_user_id,
            "player": getattr(payload, "represented_player_id", None),
            "team": getattr(payload, "represented_team_id", None), "reason": payload.reason,
            "evidence": payload.evidence_text, "links": json.dumps([str(link) for link in payload.evidence_links]),
            "base": json.dumps(disciplinary_fingerprint(source)), "duration": source["matches_suspended"],
            "prior": payload.prior_case_id, "action": getattr(payload, "proposed_action", None),
            "proposed_duration": getattr(payload, "proposed_duration", None)}
        await self.db.execute(text("""INSERT INTO sanction_cases
            (id,organization_id,suspension_id,case_type,submitted_by_user_id,submitted_by_member_id,
             represented_player_id,represented_team_id,reason,evidence_text,evidence_links,
             base_fingerprint,base_duration,prior_case_id,proposed_action,proposed_duration)
            VALUES (:id,:org,:suspension,:kind,:user,:member,:player,:team,:reason,:evidence,
                CAST(:links AS jsonb),CAST(:base AS jsonb),:duration,:prior,:action,:proposed_duration)"""), values)
        await self.db.execute(text("""INSERT INTO sanction_case_events
            (organization_id,case_id,event_type,actor_user_id,reason)
            VALUES (:org,:id,'submitted',:user,:reason)"""), values)
        return {"id": case_id, "status": "pending"}

    async def submit_proposal(self, context, payload):
        async with self.transaction(context, "RESOLVE_SANCTION_CASES"):
            source = await self.source(context, payload.suspension_id, lock=True)
            if payload.proposed_action == "reduce" and payload.proposed_duration >= source["matches_suspended"]:
                raise ValueError("La propuesta debe reducir la duración")
            return await self._submit(context, payload, source, "administrative_proposal")

    async def withdraw(self, context, case_id, payload):
        async with self.transaction(context):
            result = (await self.db.execute(text("SELECT withdraw_sanction_case(:id,:reason,CAST(:evidence AS jsonb))"),
                {"id": case_id, "reason": payload.reason,
                 "evidence": payload.model_dump_json(exclude={"reason"})})).scalar_one()
            return {"id": case_id, "status": result["status"]}

    async def decide(self, context, case_id, payload):
        async with self.transaction(context, "RESOLVE_SANCTION_CASES"):
            result = (await self.db.execute(text("SELECT decide_sanction_case(:id,CAST(:payload AS jsonb))"),
                {"id": case_id, "payload": payload.model_dump_json()})).scalar_one()
            return {"id": case_id, "status": result["status"]}

    async def list_cases(self, context, filters):
        async with self.transaction(context, "VIEW_SANCTION_CASES"):
            params = {"org": context.organization_id, **filters.model_dump()}
            items = (await self.db.execute(text("""SELECT id,suspension_id,case_type,status,
                submitted_by_user_id,submitted_at FROM sanction_cases WHERE organization_id=:org
                AND (CAST(:status AS text) IS NULL OR status=:status)
                AND (CAST(:case_type AS text) IS NULL OR case_type=:case_type)
                ORDER BY submitted_at DESC,id DESC LIMIT :limit OFFSET :offset"""), params)).mappings().all()
            total = (await self.db.execute(text("""SELECT count(*) FROM sanction_cases WHERE organization_id=:org
                AND (CAST(:status AS text) IS NULL OR status=:status)
                AND (CAST(:case_type AS text) IS NULL OR case_type=:case_type)"""), params)).scalar_one()
            return {"items": [dict(row) for row in items], "total": total}

    async def list_sanctions(self, context, filters):
        async with self.transaction(context, "VIEW_SANCTION_CASES"):
            params = {"org": context.organization_id, **filters.model_dump()}
            sources = (await self.db.execute(text("""SELECT * FROM player_suspensions
                WHERE organization_id=:org
                AND (CAST(:status AS text) IS NULL OR status=:status)
                AND (CAST(:scope_type AS text) IS NULL OR scope_type=:scope_type)
                AND (CAST(:player_id AS uuid) IS NULL OR player_id=:player_id)
                AND (CAST(:source_tournament_id AS uuid) IS NULL OR source_tournament_id=:source_tournament_id)
                ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"""), params)).mappings().all()
            total = (await self.db.execute(text("""SELECT count(*) FROM player_suspensions WHERE organization_id=:org
                AND (CAST(:status AS text) IS NULL OR status=:status)
                AND (CAST(:scope_type AS text) IS NULL OR scope_type=:scope_type)
                AND (CAST(:player_id AS uuid) IS NULL OR player_id=:player_id)
                AND (CAST(:source_tournament_id AS uuid) IS NULL OR source_tournament_id=:source_tournament_id)"""), params)).scalar_one()
            projections = await self._projections(context, sources, datetime.now(timezone.utc))
            return {"items": [{"source": dict(source), "projection": projections[source["id"]]["projection"]}
                for source in sources], "total": total}

    async def case(self, context, case_id):
        row = (await self.db.execute(text("SELECT * FROM sanction_cases WHERE id=:id AND organization_id=:org"),
            {"id": case_id, "org": context.organization_id})).mappings().one_or_none()
        if row is None:
            raise LookupError("Expediente no encontrado")
        return dict(row)

    async def detail(self, context, case_id):
        async with self.transaction(context, "VIEW_SANCTION_CASES"):
            return await self._detail(context, case_id)

    async def preview(self, context, case_id):
        async with self.transaction(context, "VIEW_SANCTION_CASES"):
            await require_permission(self.db, context, "RESOLVE_SANCTION_CASES")
            detail = await self._detail(context, case_id)
            return self._preview(detail, context.user_id)

    @staticmethod
    def _preview(detail, actor_id):
        case = detail["case"]
        return {"id": case["id"], "status": case["status"], "projection": detail["projection"],
            "expected_base_duration": case["base_duration"],
            "allowed_decisions": ["maintain", "annul", "reduce"] if case["case_type"] == "appeal" else ["approve", "reject"],
            "can_decide": case["status"] == "pending" and case["submitted_by_user_id"] != actor_id}

    async def _detail(self, context, case_id):
        case = await self.case(context, case_id)
        source = await self.source(context, case["suspension_id"])
        values = {"id": case_id, "org": context.organization_id}
        events = (await self.db.execute(text("""SELECT * FROM sanction_case_events
            WHERE case_id=:id AND organization_id=:org ORDER BY created_at,id"""), values)).mappings().all()
        decisions = (await self.db.execute(text("""SELECT * FROM sanction_case_decisions
            WHERE case_id=:id AND organization_id=:org ORDER BY created_at,id"""), values)).mappings().all()
        prejudice = (await self.db.execute(text("""SELECT * FROM sanction_prejudice_records
            WHERE case_id=:id AND organization_id=:org ORDER BY created_at,id"""), values)).mappings().all()
        projection = (await self._projections(context, [source], datetime.now(timezone.utc)))[source["id"]]
        return {"case": case, "source": source, "events": [dict(row) for row in events],
            "decisions": [dict(row) for row in decisions], "prejudice": [dict(row) for row in prejudice], **projection}

    async def _projections(self, context, sources, as_of):
        if not sources:
            return {}
        params = {"org": context.organization_id, "ids": [source["id"] for source in sources]}
        resolutions = (await self.db.execute(text("""SELECT r.*, EXISTS (SELECT 1 FROM sanction_case_events e
            WHERE e.case_id=r.case_id AND e.organization_id=r.organization_id
                AND e.event_type='affected_by_rectification') AS excluded
            FROM sanction_resolutions r WHERE r.organization_id=:org
                AND r.suspension_id=ANY(CAST(:ids AS uuid[])) ORDER BY r.created_at,r.id"""), params)).mappings().all()
        applications = (await self.db.execute(text("""SELECT * FROM sanction_effect_applications
            WHERE organization_id=:org AND suspension_id=ANY(CAST(:ids AS uuid[])) ORDER BY effective_at,id"""), params)).mappings().all()
        serves = (await self.db.execute(text("""SELECT * FROM player_suspension_serves
            WHERE organization_id=:org AND suspension_id=ANY(CAST(:ids AS uuid[])) ORDER BY served_at,match_id"""), params)).mappings().all()
        result = {}
        for source in sources:
            relevant = [dict(row) for row in resolutions if row["suspension_id"] == source["id"]]
            applied = [dict(row) for row in applications if row["suspension_id"] == source["id"]]
            served = [dict(row) for row in serves if row["suspension_id"] == source["id"]]
            fact = {"original_duration": source["matches_suspended"], "status": source["status"],
                "resolutions": [{**row, "id": str(row["id"])} for row in relevant],
                "applications": applied, "serves": [row for row in served if not row["is_voided"]], "snapshot": None}
            projection, _, _ = project_fact(fact, as_of=as_of, started_at=None, current=True)
            result[source["id"]] = {"projection": asdict(projection), "resolutions": relevant,
                "applications": applied, "serves": served}
        return result
