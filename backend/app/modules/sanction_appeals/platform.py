import json

from sqlalchemy import text

from app.modules.sanction_appeals.cases import SanctionCaseService, SanctionConflict


class SanctionPlatformService(SanctionCaseService):
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
