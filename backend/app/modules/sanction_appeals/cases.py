import json
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import set_rls_context
from app.core.locking import lock_discipline, lock_matches, lock_stage_and_version, lock_version
from app.core.permissions import require_permission


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
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise SanctionConflict("SANCTION_CASE_CONFLICT") from exc
            if getattr(exc.orig, "sqlstate", None) == "23514":
                raise SanctionConflict("SANCTION_INVALID_STATE") from exc
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
