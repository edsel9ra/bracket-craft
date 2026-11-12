from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import set_rls_context
from app.core.platform import require_platform_write
from app.modules.matches.audit import record_match_audit
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.rectifications.diff import diff_reports
from app.modules.rectifications.service import (
    RectificationConflict, RectificationSelfApproval, RectificationService, _proposal_report, _self_approval_violation,
)


@dataclass(frozen=True)
class AuthorizedPlatformActor:
    user_id: UUID
    organization_id: UUID
    organization_user_id: None = None


class RectificationPlatformService(RectificationService):
    async def _owner(self, context):
        owner = (await self.db.execute(text("SELECT rectification_owner(:id)"),
            {"id": context.organization_id})).scalar_one()
        if owner != context.organization_user_id:
            raise PermissionError("Solo el dueño puede gestionar autorizaciones")

    async def grant(self, context, request_id, payload):
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            request = await self._request(context, request_id, lock=True)
            await self._owner(context)
            self._require_pending(request)
            admin = (await self.db.execute(text("SELECT rectification_platform_candidate(:email)"),
                {"email": payload.platform_admin_email})).scalar_one()
            if admin is None:
                raise HTTPException(status_code=422, detail="Administrador de plataforma no válido")
            row = (await self.db.execute(text("""
                INSERT INTO match_report_platform_authorizations (organization_id, request_id,
                    granted_by_member_id, platform_admin_user_id, reason)
                VALUES (:org, :request, :member, :admin, :reason) RETURNING *
            """), {"org": context.organization_id, "request": request_id, "member": context.organization_user_id,
                "admin": admin, "reason": payload.reason})).mappings().one()
            await self._authorization_audit(context, request, row, "GRANT_RECTIFICATION_AUTHORIZATION")
            return dict(row)

    async def revoke(self, context, request_id, authorization_id):
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            request = await self._request(context, request_id, lock=True)
            await self._owner(context)
            row = (await self.db.execute(text("""
                SELECT * FROM match_report_platform_authorizations
                WHERE id = :id AND request_id = :request AND organization_id = :org FOR UPDATE
            """), {"id": authorization_id, "request": request_id, "org": context.organization_id})).mappings().one_or_none()
            if row is None:
                raise LookupError("Autorización no encontrada")
            self._require_pending(request)
            if row["revoked_at"] or row["consumed_at"]:
                raise RectificationConflict("RECTIFICATION_NOT_PENDING", "La autorización no está vigente")
            valid = (await self.db.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM organization_users ou
                    JOIN users u ON u.id = ou.user_id AND u.is_active
                    JOIN organization_user_roles our ON our.organization_user_id = ou.id
                        AND our.organization_id = ou.organization_id
                    JOIN roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
                    JOIN role_definitions rd ON rd.id = r.role_definition_id AND rd.code = 'owner'
                    WHERE ou.id = :member AND ou.organization_id = :org AND ou.is_active
                ) AND EXISTS (
                    SELECT 1 FROM users u WHERE u.id = :admin
                        AND rectification_platform_candidate(u.email) = u.id
                )
            """), {"member": row["granted_by_member_id"], "org": context.organization_id,
                "admin": row["platform_admin_user_id"]})).scalar_one()
            if not valid:
                raise RectificationConflict("RECTIFICATION_NOT_PENDING", "La autorización no está vigente")
            row = (await self.db.execute(text("""
                UPDATE match_report_platform_authorizations SET revoked_at = :now
                WHERE id = :id AND organization_id = :org RETURNING *
            """), {"now": datetime.now(timezone.utc), "id": authorization_id,
                "org": context.organization_id})).mappings().one()
            await self._authorization_audit(context, request, row, "REVOKE_RECTIFICATION_AUTHORIZATION")
            return dict(row)

    async def _authorization_audit(self, context, request, authorization, action):
        await record_match_audit(self.db, organization_id=context.organization_id,
            member_id=context.organization_user_id, match_id=request["match_id"], action=action,
            payload={"request_id": request["id"], "authorization_id": authorization["id"],
                "platform_admin_user_id": authorization["platform_admin_user_id"]})

    async def _scopes(self):
        return (await self.db.execute(text("SELECT * FROM rectification_platform_scopes() ORDER BY id"))).mappings().all()

    async def _scope(self, platform, scope):
        await set_rls_context(self.db, scope["organization_id"], platform.user_id)
        await self.db.execute(text("SELECT set_config('app.rectification_authorization_id', :id, true)"),
            {"id": str(scope["id"])})
        return AuthorizedPlatformActor(platform.user_id, scope["organization_id"])

    async def list_authorized(self, platform):
        require_platform_write(platform)
        async with self.db.begin():
            await set_rls_context(self.db, None, platform.user_id)
            scopes = await self._scopes()
            requests = {}
            for scope in scopes:
                actor = await self._scope(platform, scope)
                row = (await self.db.execute(text("""
                    SELECT * FROM match_report_rectification_requests
                    WHERE id = :id AND organization_id = :org AND status = 'pending'
                """), {"id": scope["request_id"], "org": actor.organization_id})).mappings().one_or_none()
                if row:
                    requests[row["id"]] = self._request_response(row)
            return list(requests.values())

    async def _authorized_request(self, platform, request_id, *, lock=False):
        scopes = await self._scopes()
        scope = next((s for s in scopes if s["request_id"] == request_id), None)
        if scope is None:
            raise LookupError("Solicitud no encontrada")
        actor = await self._scope(platform, scope)
        request = await self._request(actor, request_id, lock=lock)
        match = await self._match(actor, request["match_id"], lock=lock)
        if lock:
            authorization = (await self.db.execute(text("""
                SELECT * FROM match_report_platform_authorizations
                WHERE id = :id AND request_id = :request AND organization_id = :org FOR UPDATE
            """), {"id": scope["id"], "request": request_id, "org": actor.organization_id})).mappings().one_or_none()
            if authorization is None:
                raise LookupError("Solicitud no encontrada")
        else:
            authorization = scope
        return actor, request, match, authorization

    async def detail(self, platform, request_id):
        require_platform_write(platform)
        async with self.db.begin():
            await set_rls_context(self.db, None, platform.user_id)
            actor, request, match, _ = await self._authorized_request(platform, request_id)
            current = await self._version(actor, request["match_id"], match["version_number"])
            proposal = _proposal_report(match, CloseMatchReportDTO.model_validate(request["proposed_report"]))
            return {**request, "diff": diff_reports(current["report"], proposal)}

    async def platform_decide(self, platform, request_id, payload):
        require_platform_write(platform)
        try:
            async with self.db.begin():
                await set_rls_context(self.db, None, platform.user_id)
                actor, request, match, authorization = await self._authorized_request(platform, request_id, lock=True)
                return await self._decide_locked(actor, request, match, payload, authorization)
        except DBAPIError as exc:
            if _self_approval_violation(exc):
                raise RectificationSelfApproval() from exc
            if getattr(exc.orig, "sqlstate", None) == "42501":
                raise PermissionError("Autorización de plataforma requerida") from exc
            raise
