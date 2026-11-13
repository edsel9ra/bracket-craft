from uuid import uuid4
import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.locking import lock_discipline
from app.core.database import set_rls_context
from app.modules.sanction_appeals.application import record_opening
from test_migration_031 import ORG
from app.modules.matches import router as match_router, service as match_service
from test_rectification_flow import UNCONFIRMED, proposal
from test_rectification_flow import flow as flow
from app.modules.sanction_appeals.platform import SanctionPlatformService
from app.modules.sanction_appeals.schemas import DecisionRequest, ProposalRequest, WithdrawalRequest
from test_sanction_cases import appeal, permissions, second_member
from test_sanction_cases import cases as cases
from test_sanction_platform import authorized_case
from test_sanction_readers import readers as readers
from test_sanction_rectification import case_service
from test_rectification_flow import create, decide, proposal as rectification_proposal
from test_rectification_sanctions import card_report, submit
from migration_helpers import apply_migrations
from app.modules.sanction_appeals.schemas import AppealRequest
from test_migration_031 import PLAYER_HOME_FIRST
from test_migration_031 import SEED_SQL, TOURNAMENT, VERSION, STAGE, MATCH, SEGMENT_FIRST, SEGMENT_SECOND, TEAM_HOME
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG


async def overlap(f, *operations):
    async with f.admin.transaction():
        await f.admin.execute("SELECT pg_advisory_xact_lock(hashtextextended('discipline:'||$1,0))", str(f.context.organization_id))
        tasks = [asyncio.create_task(operation()) for operation in operations]
        try:
            async with asyncio.timeout(10):
                while True:
                    await f.admin.execute("SELECT pg_stat_clear_snapshot()")
                    if await f.admin.fetchval("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event='advisory'") >= len(tasks):
                        break
                    await asyncio.sleep(.01)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
    return await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=15)


async def test_appeal_proposal_race_has_one_pending(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS", "RESOLVE_SANCTION_CASES")
    async def appeal_operation():
        async with f.service() as service:
            return await service.submit_appeal(f.context, appeal(f))
    async def proposal_operation():
        async with f.service() as service:
            return await service.submit_proposal(f.context, ProposalRequest(suspension_id=f.suspension, proposed_action="annul", reason="Revisión"))
    results = await overlap(f, appeal_operation, proposal_operation)
    assert sum(isinstance(result, dict) for result in results) == 1, results
    assert any(isinstance(result, ValueError) for result in results), results
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_cases WHERE status='pending'") == 1


@pytest.mark.parametrize("other", ["decision", "withdrawal"])
async def test_terminal_races_are_serialized_without_duplicate_effects(cases, other):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS", "RESOLVE_SANCTION_CASES")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f))
    reviewer = await second_member(f, "RESOLVE_SANCTION_CASES")
    async def decision():
        async with f.service() as service:
            return await service.decide(reviewer, case["id"], DecisionRequest(decision="annul", expected_base_duration=3, reason="Revisado"))
    async def withdrawal():
        async with f.service() as service:
            return await service.withdraw(f.context, case["id"], WithdrawalRequest(reason="Retiro"))
    results = await overlap(f, decision, decision if other == "decision" else withdrawal)
    assert any(isinstance(result, dict) for result in results), results
    assert all(isinstance(result, (dict, ValueError)) for result in results), results
    status = await f.admin.fetchval("SELECT status FROM sanction_cases")
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_case_decisions") == (1 if status == "resolved" else 0)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_resolutions") == (1 if status == "resolved" else 0)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_effect_applications") == 0


async def test_revocation_decision_race_cannot_consume_revoked_grant(cases):
    f = cases
    case, platform, grant = await authorized_case(f)
    async def decision():
        async with f.service() as base:
            return await SanctionPlatformService(base.db).decide(platform, case["id"], DecisionRequest(
                decision="maintain", expected_base_duration=3, reason="Revisado"))
    async def revoke():
        async with f.service() as base:
            return await SanctionPlatformService(base.db).revoke(f.context, case["id"], grant["id"])
    results = await overlap(f, decision, revoke)
    assert any(isinstance(result, dict) for result in results), results
    assert all(isinstance(result, (dict, ValueError, PermissionError, LookupError)) for result in results), results
    row = await f.admin.fetchrow("SELECT * FROM sanction_platform_authorizations")
    assert (row["revoked_at"] is None) != (row["consumed_at"] is None)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_case_decisions") == (0 if row["revoked_at"] else 1)


async def test_opening_decision_race_preserves_committed_opening_snapshot(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS", "CLOSE_MATCH_REPORT")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f))
    reviewer = await second_member(f, "RESOLVE_SANCTION_CASES")
    async def decision():
        async with f.service() as service:
            return await service.decide(reviewer, case["id"], DecisionRequest(decision="annul", expected_base_duration=3, reason="Revisado"))
    async def opening():
        async with f.service() as service:
            async with service.db.begin():
                await set_rls_context(service.db, f.context.organization_id, f.context.user_id)
                await lock_discipline(service.db, f.context.organization_id)
                segment = (await service.db.execute(text("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start,created_at)
                    VALUES (:org,:match,1,0,:now) RETURNING id"""),
                    {"org": UUID(ORG), "match": f.future, "now": datetime.now(timezone.utc)})).scalar_one()
                await record_opening(service.db, f.future, segment)
                return {"segment": segment}
    results = await overlap(f, decision, opening)
    assert all(isinstance(result, dict) for result in results), results
    snapshot = dict(await f.admin.fetchrow("SELECT * FROM sanction_match_eligibility WHERE match_id=$1", f.future))
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_case_decisions") == 1
    assert snapshot["effective_duration"] in (0, 3)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_effect_applications") == (1 if snapshot["effective_duration"] == 0 else 0)


async def test_publication_decision_race_closes_or_marks_history_without_reopening(flow):
    f = flow
    await apply_migrations(f.admin, first=44)
    requester = f.context
    request = await submit(f, card_report())
    assert (await decide(f, request)).status_code == 200
    approver = f.context
    suspension = await f.admin.fetchval("SELECT id FROM player_suspensions")
    base_duration = await f.admin.fetchval("SELECT matches_suspended FROM player_suspensions WHERE id=$1", suspension)
    async with case_service(f) as service:
        case = await service.submit_appeal(requester, AppealRequest(suspension_id=suspension, represented_player_id=PLAYER_HOME_FIRST, reason="Recurso"))
    f.context = requester
    request = (await create(f, rectification_proposal())).json()["id"]
    f.context = approver
    async def publication():
        response = await decide(f, request, expected_base_version=2)
        assert response.status_code == 200, response.text
        return response.json()
    async def decision():
        async with case_service(f) as service:
            return await service.decide(approver, case["id"], DecisionRequest(decision="annul", expected_base_duration=base_duration, reason="Revisión"))
    results = await overlap(f, publication, decision)
    assert all(isinstance(result, dict) for result in results), results
    status = await f.admin.fetchval("SELECT status FROM sanction_cases")
    assert status in ("resolved", "closed_by_rectification")
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_case_decisions") == (1 if status == "resolved" else 0)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_case_events WHERE event_type IN ('affected_by_rectification','closed_by_rectification')") == 1


async def test_opening_and_walkover_in_different_tournaments_share_coordinator(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS", "CLOSE_MATCH_REPORT")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f))
    reviewer = await second_member(f, "RESOLVE_SANCTION_CASES")
    async with f.service() as service:
        await service.decide(reviewer, case["id"], DecisionRequest(decision="annul",expected_base_duration=3,reason="Anulada"))
    seed = SEED_SQL[SEED_SQL.index("INSERT INTO public.tournaments"):SEED_SQL.index("INSERT INTO public.match_segments")]
    seed = seed[:seed.index("INSERT INTO public.teams")] + seed[seed.index("INSERT INTO public.tournament_teams"):]
    mapping = {old:str(uuid4()) for old in (TOURNAMENT, VERSION, STAGE, MATCH, SEGMENT_FIRST, SEGMENT_SECOND)}
    for old, new in mapping.items():
        seed = seed.replace(old,new)
    seed = seed.replace("1, '{}'::jsonb, '{}'::jsonb,",f"1, '{json.dumps(DEFAULT_RULES_CONFIG)}'::jsonb, '{{}}'::jsonb,")
    await f.admin.execute(seed)
    other_match, other_tournament = UUID(mapping[MATCH]), UUID(mapping[TOURNAMENT])
    await f.admin.execute("""INSERT INTO rosters(organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
        SELECT organization_id,$1,team_id,player_id,dorsal_number,valid_from,eligible_from FROM rosters WHERE tournament_id=$2""", other_tournament,TOURNAMENT)
    await f.admin.execute("UPDATE tournament_versions SET status='published' WHERE id=$1",UUID(mapping[VERSION]))
    await f.admin.execute("UPDATE tournaments SET status='published',published_version_id=$2 WHERE id=$1",other_tournament,UUID(mapping[VERSION]))
    async def opening():
        async with f.service() as service:
            async with service.db.begin():
                await set_rls_context(service.db,f.context.organization_id,f.context.user_id)
                await lock_discipline(service.db,f.context.organization_id)
                segment = (await service.db.execute(text("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start,created_at)
                    VALUES (:org,:match,1,0,:now) RETURNING id"""),
                    {"org":f.context.organization_id,"match":other_match,"now":datetime.now(timezone.utc)})).scalar_one()
                await record_opening(service.db,other_match,segment)
                return {"id":segment}
    async def closing():
        async with f.service() as service:
            return await CloseMatchReportService(service.db).execute(f.context,UUID(MATCH),CloseMatchReportDTO(
                resolution_type="walkover",reason="no_show",winner_team_id=TEAM_HOME,
                home_score_regular=3,away_score_regular=0,home_score=3,away_score=0,events=[]))
    results = await overlap(f,opening,closing)
    assert all(isinstance(result,dict) for result in results),results
    assert await f.admin.fetchval("SELECT result_confirmed FROM matches WHERE id=$1",MATCH)
    assert await f.admin.fetchval("SELECT match_id FROM sanction_effect_applications") == other_match
    assert await f.admin.fetchval("SELECT count(*) FROM player_suspension_serves") == 0


async def test_coordinator_serializes_same_tenant_and_releases_on_rollback(database_admin_url):
    engine = create_async_engine(database_admin_url)
    org = uuid4()
    try:
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            async with first.begin():
                await lock_discipline(first, org)
                async with second.begin():
                    await second.execute(text("SET LOCAL lock_timeout='100ms'"))
                    await lock_discipline(second, uuid4())
                with pytest.raises(DBAPIError, match="lock timeout"):
                    async with second.begin():
                        await second.execute(text("SET LOCAL lock_timeout='100ms'"))
                        await lock_discipline(second, org)
            async with second.begin():
                await second.execute(text("SET LOCAL lock_timeout='100ms'"))
                await lock_discipline(second, org)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("opening", [True, False])
async def test_match_lock_takes_coordinator_before_row_locks(flow, monkeypatch, opening):
    order = []

    async def coordinator(*args, **kwargs):
        order.append("coordinator")
        await lock_discipline(*args, **kwargs)

    async def first_row_lock(*args, **kwargs):
        order.append("row")
        raise RuntimeError("stop after lock order probe")

    target = match_router if opening else match_service
    monkeypatch.setattr(target, "lock_discipline", coordinator, raising=False)
    monkeypatch.setattr(target, "_load_operation_match" if opening else "lock_stage_and_version", first_row_lock)
    path = f"/api/v1/matches/{UNCONFIRMED}/" + ("segments" if opening else "close")
    body = {"segment_number": 1, "minute_start": 0} if opening else proposal()["proposed_report"]
    with pytest.raises(RuntimeError, match="stop after lock order probe"):
        await flow.client.post(path, json=body)
    assert order == ["coordinator", "row"]
