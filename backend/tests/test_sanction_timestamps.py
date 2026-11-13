import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text

from app.core.database import set_rls_context
from app.core.locking import lock_discipline
from app.modules.sanction_appeals.application import record_opening
from app.modules.sanction_appeals.platform import SanctionPlatformService
from app.modules.sanction_appeals.schemas import AppealRequest, DecisionRequest, WithdrawalRequest
from migration_helpers import apply_migrations
from test_migration_031 import ORG, PLAYER_HOME_FIRST
from test_rectification_flow import create, decide, proposal
from test_rectification_flow import flow as flow
from test_rectification_sanctions import card_report, submit
from test_sanction_cases import appeal, permissions, second_member
from test_sanction_cases import cases as cases
from test_sanction_platform import authorized_case
from test_sanction_rectification import case_service
from test_sanction_readers import readers as readers


async def after_lock_wait(f, operation, while_blocked=None):
    async with f.admin.transaction():
        await f.admin.execute("SELECT pg_advisory_xact_lock(hashtextextended('discipline:'||$1,0))",str(f.context.organization_id))
        task = asyncio.create_task(operation())
        try:
            async with asyncio.timeout(10):
                while True:
                    await f.admin.execute("SELECT pg_stat_clear_snapshot()")
                    if await f.admin.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event='advisory'"):
                        break
                    await asyncio.sleep(.01)
            if while_blocked:
                await while_blocked()
            boundary = await f.admin.fetchval("SELECT clock_timestamp()")
        except BaseException:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            raise
    result = await asyncio.wait_for(task,15)
    return boundary,result


@pytest.mark.parametrize("platform_mode", [False, True])
async def test_decision_resolution_follow_lock_wait_and_prior_opening(cases, platform_mode):
    f = cases
    if platform_mode:
        case, actor, _ = await authorized_case(f)
        await permissions(f,"CLOSE_MATCH_REPORT")
    else:
        await permissions(f,"SUBMIT_SANCTION_APPEALS","CLOSE_MATCH_REPORT")
        async with f.service() as service:
            case = await service.submit_appeal(f.context,appeal(f))
        actor = await second_member(f,"RESOLVE_SANCTION_CASES")
    async def decision():
        async with f.service() as service:
            service = SanctionPlatformService(service.db) if platform_mode else service
            return await service.decide(actor,case["id"],DecisionRequest(
                decision="annul",expected_base_duration=3,reason="Posterior al inicio"))
    async def opening():
        await f.admin.execute("SELECT set_config('app.current_organization_id',$1,true),set_config('app.current_user_id',$2,true)",
            str(f.context.organization_id),str(f.context.user_id))
        segment = await f.admin.fetchval("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start,created_at)
            VALUES ($1,$2,1,0,clock_timestamp()) RETURNING id""", UUID(ORG),f.future)
        await f.admin.execute("SELECT record_sanction_opening($1,$2)",f.future,segment)
    boundary,result = await after_lock_wait(f,decision,opening)
    assert result["status"] == "resolved"
    row = await f.admin.fetchrow("""SELECT d.created_at AS decided_at,r.created_at AS resolved_at
        FROM sanction_case_decisions d JOIN sanction_resolutions r ON r.decision_id=d.id WHERE d.case_id=$1""",case["id"])
    assert row["decided_at"] >= boundary
    assert row["decided_at"] == row["resolved_at"]
    snapshot = await f.admin.fetchrow("SELECT * FROM sanction_match_eligibility WHERE match_id=$1",f.future)
    assert snapshot["started_at"] < row["decided_at"]
    assert snapshot["effective_duration"] == 3
    assert not await f.admin.fetchval("SELECT count(*) FROM sanction_effect_applications")


async def test_withdrawal_event_follows_lock_wait(cases):
    f = cases
    await permissions(f,"SUBMIT_SANCTION_APPEALS")
    async with f.service() as service:
        case = await service.submit_appeal(f.context,appeal(f))
    async def withdrawal():
        async with f.service() as service:
            return await service.withdraw(f.context,case["id"],WithdrawalRequest(reason="Retirada posterior"))
    boundary,_ = await after_lock_wait(f,withdrawal)
    assert await f.admin.fetchval("SELECT created_at FROM sanction_case_events WHERE event_type='withdrawn'") >= boundary


async def test_application_keeps_real_opening_boundary_after_wait(cases):
    f = cases
    await permissions(f,"SUBMIT_SANCTION_APPEALS","CLOSE_MATCH_REPORT")
    async with f.service() as service:
        case = await service.submit_appeal(f.context,appeal(f))
    reviewer = await second_member(f,"RESOLVE_SANCTION_CASES")
    async with f.service() as service:
        await service.decide(reviewer,case["id"],DecisionRequest(decision="annul",expected_base_duration=3,reason="Anular"))
    async def opening():
        async with f.service() as service:
            async with service.db.begin():
                await set_rls_context(service.db,f.context.organization_id,f.context.user_id)
                await lock_discipline(service.db,f.context.organization_id)
                segment = (await service.db.execute(text("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start,created_at)
                    VALUES (:org,:match,1,0,clock_timestamp()) RETURNING id"""),
                    {"org":f.context.organization_id,"match":f.future})).scalar_one()
                await record_opening(service.db,f.future,segment)
    boundary,_ = await after_lock_wait(f,opening)
    application = await f.admin.fetchrow("SELECT * FROM sanction_effect_applications")
    assert application["effective_at"] >= boundary
    assert application["created_at"] >= application["effective_at"]
    assert await f.admin.fetchval("SELECT started_at FROM sanction_match_eligibility WHERE match_id=$1",f.future) == application["effective_at"]


async def test_rectification_closure_follows_publication_after_lock_wait(flow):
    f = flow
    await apply_migrations(f.admin,first=44)
    requester = f.context
    request = await submit(f,card_report())
    assert (await decide(f,request)).status_code == 200
    approver = f.context
    suspension = await f.admin.fetchval("SELECT id FROM player_suspensions")
    async with case_service(f) as service:
        await service.submit_appeal(requester,AppealRequest(
            suspension_id=suspension,represented_player_id=PLAYER_HOME_FIRST,reason="Pendiente"))
    f.context = requester
    request = (await create(f,proposal())).json()["id"]
    f.context = approver
    async def publication():
        return await decide(f,request,expected_base_version=2)
    boundary,response = await after_lock_wait(f,publication)
    assert response.status_code == 200,response.text
    event = await f.admin.fetchrow("""SELECT e.created_at,v.published_at FROM sanction_case_events e
        JOIN match_report_versions v ON v.id=e.rectification_version_id WHERE e.event_type='closed_by_rectification'""")
    assert event["created_at"] >= event["published_at"] >= boundary
