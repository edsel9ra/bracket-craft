from uuid import uuid4

from app.modules.sanction_appeals.platform import SanctionPlatformService
from app.modules.sanction_appeals.schemas import AuthorizationRequest, CaseFilters
from test_sanction_cases import appeal, permissions
from test_sanction_cases import cases as cases
from test_sanction_platform import authorized_case
from test_sanction_readers import readers as readers


async def test_duplicate_live_grants_keep_unique_cases_totals_and_pages(cases):
    f = cases
    first, platform, grant = await authorized_case(f)
    email = await f.admin.fetchval("SELECT email FROM users WHERE id=$1",platform.user_id)
    payload = AuthorizationRequest(platform_admin_email=email,reason="Otra autorización puntual")
    async with f.service() as base:
        service = SanctionPlatformService(base.db)
        duplicate = await service.grant(f.context,first["id"],payload)
    assert duplicate["id"] != grant["id"]
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_platform_authorizations WHERE revoked_at IS NULL AND consumed_at IS NULL") == 2
    async with f.service() as base:
        service = SanctionPlatformService(base.db)
        listed = await service.list_authorized(platform,CaseFilters(limit=1))
        empty = await service.list_authorized(platform,CaseFilters(limit=1,offset=1))
    assert listed["total"] == 1
    assert [row["id"] for row in listed["items"]] == [first["id"]]
    assert listed["items"][0]["authorization_id"] == min(grant["id"],duplicate["id"])
    assert empty == {"items":[],"total":1}
    await permissions(f,"SUBMIT_SANCTION_APPEALS")
    f.suspension = await f.admin.fetchval("""INSERT INTO player_suspensions
        (organization_id,source_tournament_id,player_id,source_type,dedupe_key,scope_type,matches_suspended,reason,created_at)
        SELECT organization_id,source_tournament_id,player_id,source_type,$2,scope_type,matches_suspended,reason,created_at
        FROM player_suspensions WHERE id=$1 RETURNING id""",f.suspension,str(uuid4()))
    async with f.service() as base:
        second = await base.submit_appeal(f.context,appeal(f))
        await SanctionPlatformService(base.db).grant(f.context,second["id"],payload)
        service = SanctionPlatformService(base.db)
        page1 = await service.list_authorized(platform,CaseFilters(limit=1))
        page2 = await service.list_authorized(platform,CaseFilters(limit=1,offset=1))
        page3 = await service.list_authorized(platform,CaseFilters(limit=1,offset=2))
        filtered = await service.list_authorized(platform,CaseFilters(status="resolved"))
    assert page1["total"] == page2["total"] == page3["total"] == 2
    assert [page1["items"][0]["id"],page2["items"][0]["id"]] == [second["id"],first["id"]]
    assert page3["items"] == []
    assert filtered == {"items":[],"total":0}
    async with f.service() as base:
        service = SanctionPlatformService(base.db)
        await service.revoke(f.context,first["id"],grant["id"])
        assert (await service.list_authorized(platform))["total"] == 2
        await service.revoke(f.context,first["id"],duplicate["id"])
        remaining = await service.list_authorized(platform)
    assert remaining["total"] == 1
    assert remaining["items"][0]["id"] == second["id"]
