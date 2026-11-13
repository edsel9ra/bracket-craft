import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from app.core.database import set_rls_context
from app.core.platform import require_platform_write
from app.modules.sanction_appeals.cases import SanctionCaseService, SanctionConflict
from app.modules.sanction_appeals.repository import project_fact
from app.modules.sanction_appeals.schemas import CaseFilters


@dataclass(frozen=True)
class PlatformCaseActor:
    user_id: UUID
    organization_id: UUID | None = None
    organization_user_id: None = None
    case_id: UUID | None = None


class SanctionPlatformService(SanctionCaseService):
    async def _scopes(self):
        return (await self.db.execute(text("SELECT * FROM sanction_platform_scopes() ORDER BY id"))).mappings().all()

    async def _scope(self, platform, scope):
        await set_rls_context(self.db, scope["organization_id"], platform.user_id)
        await self.db.execute(text("SELECT set_config('app.sanction_authorization_id',:id,true)"), {"id": str(scope["id"])})
        return PlatformCaseActor(platform.user_id, scope["organization_id"], case_id=scope["case_id"])

    async def _authorized(self, platform, case_id):
        scope = next((row for row in await self._scopes() if row["case_id"] == case_id), None)
        if scope is None:
            raise LookupError("Expediente no encontrado")
        return await self._scope(platform, scope)

    async def list_authorized(self, platform, filters=None):
        require_platform_write(platform)
        filters = filters or CaseFilters()
        async with self.transaction(PlatformCaseActor(platform.user_id)):
            items = []
            for scope in await self._scopes():
                actor = await self._scope(platform, scope)
                row = (await self.db.execute(text("""SELECT id,suspension_id,case_type,status,submitted_at
                    FROM sanction_cases WHERE id=:id AND organization_id=:org"""),
                    {"id": scope["case_id"], "org": actor.organization_id})).mappings().one_or_none()
                if row and (filters.status is None or row["status"] == filters.status) and (
                    filters.case_type is None or row["case_type"] == filters.case_type):
                    items.append({**dict(row), "authorization_id": scope["id"], "organization_id": actor.organization_id})
            items.sort(key=lambda item: (item["submitted_at"], str(item["id"])), reverse=True)
            return {"items": items[filters.offset:filters.offset + filters.limit], "total": len(items)}

    async def detail(self, platform, case_id):
        require_platform_write(platform)
        async with self.transaction(PlatformCaseActor(platform.user_id)):
            actor = await self._authorized(platform, case_id)
            return await self._detail(actor, case_id)

    async def preview(self, platform, case_id):
        require_platform_write(platform)
        async with self.transaction(PlatformCaseActor(platform.user_id)):
            actor = await self._authorized(platform, case_id)
            return self._preview(await self._detail(actor, case_id), platform.user_id)

    async def decide(self, platform, case_id, payload):
        require_platform_write(platform)
        async with self.transaction(PlatformCaseActor(platform.user_id)):
            await self._authorized(platform, case_id)
            result = (await self.db.execute(text("SELECT decide_sanction_case(:id,CAST(:payload AS jsonb))"),
                {"id": case_id, "payload": payload.model_dump_json()})).scalar_one()
            return {"id": case_id, "status": result["status"]}

    async def source(self, context, suspension_id, *, lock=False):
        history = (await self.db.execute(text("SELECT sanction_platform_history(:case)"), {"case": context.case_id})).scalar_one()
        source = history["source"]
        for key in ("id", "player_id", "source_tournament_id", "origin_match_id", "source_event_id", "source_version_event_id",
                    "stage_id", "tournament_version_id"):
            source[key] = UUID(source[key]) if source[key] else None
        source["created_at"] = datetime.fromisoformat(source["created_at"])
        if source["id"] != suspension_id:
            raise LookupError("Sanción no encontrada")
        return source

    async def _projections(self, context, sources, as_of):
        history = (await self.db.execute(text("SELECT sanction_platform_history(:case)"), {"case": context.case_id})).scalar_one()
        fact = {"original_duration": history["source"]["matches_suspended"], "status": history["source"]["status"],
            "resolutions": history["resolutions"], "applications": history["applications"],
            "serves": [row for row in history["serves"] if not row["is_voided"]], "snapshot": None}
        projection, _, _ = project_fact(fact, as_of=as_of, started_at=None, current=True)
        return {sources[0]["id"]: {"projection": asdict(projection), "resolutions": history["resolutions"],
            "applications": history["applications"], "serves": history["serves"]}}

    async def _owner(self, context):
        owner = (await self.db.execute(text("SELECT sanction_owner(:org)"),
            {"org": context.organization_id})).scalar_one()
        if owner is None or owner != context.organization_user_id:
            raise PermissionError("Solo el dueño puede gestionar autorizaciones F9")

    async def list_authorizations(self, context, case_id):
        async with self.transaction(context):
            await self._owner(context)
            return [dict(row) for row in (await self.db.execute(text("""SELECT * FROM sanction_platform_authorizations
                WHERE organization_id=:org AND case_id=:case ORDER BY granted_at,id"""),
                {"org": context.organization_id, "case": case_id})).mappings().all()]

    async def grant(self, context, case_id, payload):
        async with self.transaction(context):
            await self._owner(context)
            await self.db.execute(text("SELECT sanction_lock_authorization_case(:case)"), {"case": case_id})
            admin = (await self.db.execute(text("SELECT sanction_platform_candidate(:email)"),
                {"email": payload.platform_admin_email})).scalar_one()
            if admin is None:
                raise ValueError("Administrador de plataforma no válido")
            row = (await self.db.execute(text("""INSERT INTO sanction_platform_authorizations
                (organization_id,case_id,granted_by_member_id,platform_admin_user_id,reason)
                VALUES (:org,:case,:member,:admin,:reason) RETURNING *"""),
                {"org": context.organization_id, "case": case_id, "member": context.organization_user_id,
                    "admin": admin, "reason": payload.reason})).mappings().one()
            await self._audit(context, case_id, row, "GRANT_SANCTION_AUTHORIZATION")
            return dict(row)

    async def revoke(self, context, case_id, authorization_id):
        async with self.transaction(context):
            await self._owner(context)
            await self.db.execute(text("SELECT sanction_lock_authorization_case(:case)"), {"case": case_id})
            row = (await self.db.execute(text("""SELECT * FROM sanction_platform_authorizations
                WHERE id=:id AND organization_id=:org AND case_id=:case"""),
                {"id": authorization_id, "org": context.organization_id, "case": case_id})).mappings().one_or_none()
            if row is None:
                raise LookupError("Autorización no encontrada")
            if row["revoked_at"] is not None or row["consumed_at"] is not None:
                raise SanctionConflict("SANCTION_AUTHORIZATION_REQUIRED")
            await self.db.execute(text("SELECT sanction_revoke_authorization(:id)"), {"id": authorization_id})
            await self._audit(context, case_id, row, "REVOKE_SANCTION_AUTHORIZATION")
            return {**dict(row), "revoked_at": (await self.db.execute(text("SELECT revoked_at FROM sanction_platform_authorizations WHERE id=:id"),
                {"id": authorization_id})).scalar_one()}

    async def _audit(self, context, case_id, authorization, action):
        await self.db.execute(text("""INSERT INTO administrative_audit_logs
            (organization_id,entity_type,entity_id,action,payload,performed_by_user_id)
            VALUES (:org,'sanction_cases',:case,:action,CAST(:payload AS jsonb),:actor)"""),
            {"org": context.organization_id, "case": case_id, "action": action, "actor": context.user_id,
                "payload": json.dumps({"authorization_id": str(authorization["id"]),
                    "platform_admin_user_id": str(authorization["platform_admin_user_id"])})})
