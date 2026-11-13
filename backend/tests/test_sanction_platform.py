from uuid import uuid4

import pytest

from app.core.platform import PlatformContext
from app.modules.sanction_appeals.platform import SanctionPlatformService
from app.modules.sanction_appeals.schemas import AuthorizationRequest
from test_sanction_cases import appeal, permissions, second_member
from test_sanction_cases import cases as cases
from test_sanction_readers import readers as readers


async def platform_user(f):
    user = await f.admin.fetchval("INSERT INTO users(email,full_name) VALUES ($1,'Platform') RETURNING id", f"{uuid4()}@example.test")
    await f.admin.execute("INSERT INTO platform_admins(user_id,role_code,is_active) VALUES ($1,'platform_admin',TRUE)", user)
    return PlatformContext(user, "platform_admin")


async def authorized_case(f):
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f))
    await f.admin.execute("""UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='owner'),
        permissions='[]' WHERE organization_id=$1""", f.context.organization_id)
    platform = await platform_user(f)
    email = await f.admin.fetchval("SELECT email FROM users WHERE id=$1", platform.user_id)
    async with f.service() as base:
        grant = await SanctionPlatformService(base.db).grant(f.context, case["id"],
            AuthorizationRequest(platform_admin_email=email, reason="Intervención puntual"))
    return case, platform, grant


@pytest.mark.parametrize("invalid", ["platform_support", "inactive_platform", "inactive_owner", "owner_role_lost"])
async def test_authorization_revalidates_current_owner_and_platform(cases, invalid):
    f = cases
    case, platform, _ = await authorized_case(f)
    if invalid == "platform_support":
        await f.admin.execute("UPDATE platform_admins SET role_code='platform_support' WHERE user_id=$1", platform.user_id)
    elif invalid == "inactive_platform":
        await f.admin.execute("UPDATE platform_admins SET is_active=FALSE WHERE user_id=$1", platform.user_id)
    elif invalid == "inactive_owner":
        await f.admin.execute("UPDATE organization_users SET is_active=FALSE WHERE id=$1", f.context.organization_user_id)
    else:
        await f.admin.execute("UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='operator')")
    email = await f.admin.fetchval("SELECT email FROM users WHERE id=$1", platform.user_id)
    async with f.service() as base:
        with pytest.raises((ValueError, PermissionError)):
            await SanctionPlatformService(base.db).grant(f.context, case["id"],
                AuthorizationRequest(platform_admin_email=email, reason="Ya no vigente"))
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_platform_authorizations") == 1


async def test_authorization_owner_without_view_can_grant_and_revoke(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f))
    await f.admin.execute("""UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='owner'),
        permissions='[]' WHERE organization_id=$1""", f.context.organization_id)
    platform = await platform_user(f)
    email = await f.admin.fetchval("SELECT email FROM users WHERE id=$1", platform.user_id)
    payload = AuthorizationRequest(platform_admin_email=email, reason="Intervención puntual F9")
    async with f.service() as base:
        service = SanctionPlatformService(base.db)
        grant = await service.grant(f.context, case["id"], payload)
    assert grant["case_id"] == case["id"]
    assert grant["revoked_at"] is None and grant["consumed_at"] is None
    other = await second_member(f, "VIEW_SANCTION_CASES", "RESOLVE_SANCTION_CASES")
    async with f.service() as base:
        with pytest.raises(PermissionError):
            await SanctionPlatformService(base.db).grant(other, case["id"], payload)
    async with f.service() as base:
        await SanctionPlatformService(base.db).revoke(f.context, case["id"], grant["id"])
    assert await f.admin.fetchval("SELECT revoked_at IS NOT NULL FROM sanction_platform_authorizations")
    assert await f.admin.fetchval("SELECT count(*) FROM administrative_audit_logs WHERE action LIKE '%SANCTION_AUTHORIZATION'") == 2
