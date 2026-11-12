import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from app.core.database import set_rls_context
from app.core.locking import lock_matches
from app.core.permissions import require_permission
from app.modules.rectifications.advancement import AdvancementImpactCandidate


async def audit_impact(db, context, procedure, action):
    await db.execute(text("""INSERT INTO administrative_audit_logs
        (organization_id,entity_type,entity_id,action,payload,performed_by_member_id,performed_by_user_id)
        VALUES (:org,'competitive_impact_procedures',:id,:action,CAST(:payload AS jsonb),:member,:user)"""),
        {"org": context.organization_id, "id": procedure["id"], "action": action,
            "payload": json.dumps({"version_id": str(procedure["version_id"]), "resolution": procedure["resolution"]}),
            "member": getattr(context, "organization_user_id", None), "user": context.user_id})


async def open_impacts(db, context, version, candidates, now):
    if not candidates:
        return []
    matches, phases = {}, {}
    params = {"org": context.organization_id}
    for candidate in candidates:
        effect = {"kind": "advancement" if isinstance(candidate, AdvancementImpactCandidate) else "accumulation",
            **asdict(candidate)}
        if candidate.match_id is not None:
            matches.setdefault(candidate.match_id, []).append(effect)
        if isinstance(candidate, AdvancementImpactCandidate) and candidate.stage_id is not None:
            phases.setdefault(candidate.stage_id, []).append(effect)
    items = []
    for stage_id, effects in sorted(phases.items()):
        assignments = [dict(row) for row in (await db.execute(text("""SELECT * FROM stage_teams
            WHERE organization_id=:org AND stage_id=:stage ORDER BY id"""), {**params, "stage": stage_id})).mappings()]
        items.append({"stage_id": stage_id, "stage_assignments": assignments, "effects": effects})
        for match_id in (await db.execute(text("SELECT id FROM matches WHERE organization_id=:org AND stage_id=:stage ORDER BY id"),
                {**params, "stage": stage_id})).scalars():
            matches.setdefault(match_id, []).extend(effects)
    await lock_matches(db, context.organization_id, list(matches))
    for match_id, effects in sorted(matches.items()):
        match = (await db.execute(text("""SELECT id AS match_id,stage_id,home_team_id,away_team_id,status,result_confirmed
            FROM matches WHERE id=:id AND organization_id=:org"""), {**params, "id": match_id})).mappings().one()
        assignments = [dict(row) for row in (await db.execute(text("""SELECT * FROM match_slot_assignments
            WHERE organization_id=:org AND match_id=:id ORDER BY assigned_at,id"""), {**params, "id": match_id})).mappings()]
        items.append({**match, "slot_assignments": assignments, "effects": effects})
    procedure = (await db.execute(text("""INSERT INTO competitive_impact_procedures
        (organization_id,version_id,match_id,affected_items,created_at)
        VALUES (:org,:version,:match,CAST(:items AS jsonb),:now) RETURNING *"""),
        {**params, "version": version["id"], "match": version["match_id"],
            "items": json.dumps(items, default=str), "now": now})).mappings().one()
    await audit_impact(db, context, procedure, "OPEN_COMPETITIVE_IMPACT")
    return [{"effect_type": "impact_opened", "entity_type": "competitive_impact_procedure", "entity_id": str(procedure["id"]),
        "payload": {"procedure_id": str(procedure["id"]), "affected_items": json.loads(json.dumps(items, default=str))}}]


class CompetitiveImpactService:
    def __init__(self, db):
        self.db = db

    async def list_organization(self, context, filters):
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            params = {**filters.model_dump(), "org": context.organization_id}
            total = (await self.db.execute(text("""SELECT count(*) FROM competitive_impact_procedures q
                JOIN matches m ON m.id=q.match_id AND m.organization_id=q.organization_id
                WHERE q.organization_id=:org
                  AND (CAST(:status AS text) IS NULL OR q.status=:status)
                  AND (CAST(:tournament_id AS uuid) IS NULL OR m.tournament_id=:tournament_id)"""), params)).scalar_one()
            rows = (await self.db.execute(text("""SELECT q.* FROM competitive_impact_procedures q
                JOIN matches m ON m.id=q.match_id AND m.organization_id=q.organization_id
                WHERE q.organization_id=:org
                  AND (CAST(:status AS text) IS NULL OR q.status=:status)
                  AND (CAST(:tournament_id AS uuid) IS NULL OR m.tournament_id=:tournament_id)
                ORDER BY q.created_at DESC,q.id DESC LIMIT :limit OFFSET :offset"""), params)).mappings().all()
            return {"items": rows, "total": total, "limit": filters.limit, "offset": filters.offset}

    async def list(self, context, tournament_id: UUID):
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            exists = await self.db.execute(text("SELECT id FROM tournaments WHERE id=:id AND organization_id=:org"),
                {"id": tournament_id, "org": context.organization_id})
            if exists.scalar_one_or_none() is None:
                raise LookupError("Torneo no encontrado")
            return (await self.db.execute(text("""SELECT p.* FROM competitive_impact_procedures p
                JOIN matches m ON m.id=p.match_id AND m.organization_id=p.organization_id
                WHERE p.organization_id=:org AND m.tournament_id=:id ORDER BY p.created_at,p.id"""),
                {"org": context.organization_id, "id": tournament_id})).mappings().all()

    async def close(self, context, procedure_id: UUID, payload):
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            procedure = (await self.db.execute(text("""SELECT * FROM competitive_impact_procedures
                WHERE id=:id AND organization_id=:org FOR UPDATE"""),
                {"id": procedure_id, "org": context.organization_id})).mappings().one_or_none()
            if procedure is None:
                raise LookupError("Procedimiento no encontrado")
            await require_permission(self.db, context, "APPROVE_MATCH_REPORT_RECTIFICATION")
            if procedure["status"] != "open":
                raise ValueError("El procedimiento ya está cerrado")
            result = (await self.db.execute(text("""UPDATE competitive_impact_procedures SET status='closed',
                resolution='keep_as_played',reason=:reason,closed_by_user_id=:user,closed_at=:now
                WHERE id=:id AND organization_id=:org RETURNING *"""),
                {"id": procedure_id, "org": context.organization_id, "reason": payload.reason,
                    "user": context.user_id, "now": datetime.now(timezone.utc)})).mappings().one()
            await audit_impact(self.db, context, result, "CLOSE_COMPETITIVE_IMPACT")
            return result
