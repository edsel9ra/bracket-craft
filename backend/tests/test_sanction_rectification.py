from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sanction_appeals.cases import SanctionCaseService
from app.modules.sanction_appeals.schemas import AppealRequest, DecisionRequest
from app.modules.rectifications import effects
from migration_helpers import apply_migrations
from test_migration_031 import ORG, PLAYER_HOME_FIRST
from test_rectification_flow import create, decide, proposal, database_snapshot
from test_rectification_flow import flow as flow
from test_rectification_sanctions import card_report, submit


@asynccontextmanager
async def case_service(flow):
    async with flow.engine.connect() as connection:
        await connection.execute(text("SET ROLE bracket_app"))
        await connection.commit()
        async with AsyncSession(bind=connection) as db:
            yield SanctionCaseService(db)


async def publication_only(flow, context):
    await flow.admin.execute("""UPDATE roles SET permissions='["APPROVE_MATCH_REPORT_RECTIFICATION"]'
        WHERE organization_id=$1 AND id IN (SELECT role_id FROM organization_user_roles
            WHERE organization_id=$1 AND organization_user_id=$2)""", ORG, context.organization_user_id)


@pytest.mark.parametrize("changed", [False, True])
async def test_closure_from_publication_without_case_view(flow, changed):
    await apply_migrations(flow.admin, first=44)
    requester = flow.context
    body = card_report()
    request = await submit(flow, body)
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
    await publication_only(flow, approver)
    suspension = await flow.admin.fetchval("SELECT id FROM player_suspensions")
    async with case_service(flow) as service:
        case = await service.submit_appeal(requester, AppealRequest(
            suspension_id=suspension, represented_player_id=PLAYER_HOME_FIRST, reason="Recurso", evidence_text="Privada"))
    report = proposal() if changed else deepcopy(body)
    if not changed:
        report["proposed_report"]["events"][0]["minute"] = 12
    flow.context = requester
    response = await create(flow, report)
    assert response.status_code == 201, response.text
    flow.context = approver
    response = await decide(flow, response.json()["id"], expected_base_version=2)
    assert response.status_code == 200, response.text
    status = await flow.admin.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case["id"])
    assert status == ("closed_by_rectification" if changed else "pending")
    assert await flow.admin.fetchval("SELECT count(*) FROM sanction_case_decisions") == 0
    if changed:
        event = await flow.admin.fetchrow("SELECT * FROM sanction_case_events WHERE event_type='closed_by_rectification'")
        assert event["rectification_version_id"] is not None and event["reason"]
        assert await flow.admin.fetchval("SELECT count(*) FROM sanction_cases WHERE organization_id<>$1", ORG) == 0


async def test_closure_failure_rolls_back_publication(flow, monkeypatch):
    await apply_migrations(flow.admin, first=44)
    requester = flow.context
    request = await submit(flow, card_report())
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
    suspension = await flow.admin.fetchval("SELECT id FROM player_suspensions")
    async with case_service(flow) as service:
        case = await service.submit_appeal(requester, AppealRequest(
            suspension_id=suspension, represented_player_id=PLAYER_HOME_FIRST, reason="Recurso"))
    flow.context = requester
    response = await create(flow, proposal())
    flow.context = approver
    before = await flow.admin.fetchval("SELECT count(*) FROM outbox_events")
    close = effects.close_for_rectification
    async def fail_after_closure(db, version_id):
        await close(db, version_id)
        raise RuntimeError("closure rollback")
    monkeypatch.setattr(effects, "close_for_rectification", fail_after_closure)
    with pytest.raises(RuntimeError, match="closure rollback"):
        await decide(flow, response.json()["id"], expected_base_version=2)
    assert await flow.admin.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case["id"]) == "pending"
    assert await flow.admin.fetchval("SELECT count(*) FROM sanction_case_events") == 1
    assert await flow.admin.fetchval("SELECT count(*) FROM match_report_versions") == 1
    assert await flow.admin.fetchval("SELECT count(*) FROM outbox_events") == before


@pytest.mark.parametrize("preview_as_author", [True, False])
async def test_rectification_preview_with_pending_case_is_read_only_for_author_and_approver(flow, preview_as_author):
    await apply_migrations(flow.admin, first=44)
    requester = flow.context
    request = await submit(flow, card_report())
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
    suspension = await flow.admin.fetchval("SELECT id FROM player_suspensions")
    async with case_service(flow) as service:
        await service.submit_appeal(requester, AppealRequest(
            suspension_id=suspension,represented_player_id=PLAYER_HOME_FIRST,reason="Pendiente"))
    flow.context = requester
    response = await create(flow, proposal())
    assert response.status_code == 201,response.text
    flow.context = requester if preview_as_author else approver
    before = await database_snapshot(flow.admin)
    response = await flow.client.get(f"/api/v1/rectifications/{response.json()['id']}/preview")
    assert response.status_code == 200,response.text
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("action", ["annul", "reduce"])
async def test_reconcile_does_not_recreate_or_erase_f9_resolution(flow, action):
    await apply_migrations(flow.admin, first=44)
    requester = flow.context
    body = card_report()
    request = await submit(flow, body)
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
    source = dict(await flow.admin.fetchrow("SELECT * FROM player_suspensions"))
    if action == "annul":
        await flow.admin.execute("UPDATE player_suspensions SET status='served' WHERE id=$1", source["id"])
    async with case_service(flow) as service:
        case = await service.submit_appeal(requester, AppealRequest(suspension_id=source["id"],
            represented_player_id=PLAYER_HOME_FIRST, reason="Recurso"))
    async with case_service(flow) as service:
        await service.decide(approver, case["id"], DecisionRequest(decision=action, expected_base_duration=source["matches_suspended"],
            after_duration=0 if action == "reduce" else None, reason="Resolución F9"))
    resolution = dict(await flow.admin.fetchrow("SELECT * FROM sanction_resolutions"))
    unchanged = deepcopy(body)
    unchanged["proposed_report"]["events"][-1]["minute"] = 25
    await publication_only(flow, approver)
    flow.context = requester
    response = await create(flow, unchanged)
    flow.context = approver
    response = await decide(flow, response.json()["id"], expected_base_version=2)
    assert response.status_code == 200, response.text
    assert await flow.admin.fetchval("SELECT count(*) FROM player_suspensions") == 1
    assert dict(await flow.admin.fetchrow("SELECT * FROM sanction_resolutions")) == resolution
    assert await flow.admin.fetchval("SELECT count(*) FROM sanction_case_events WHERE event_type='affected_by_rectification'") == 0
    flow.context = requester
    response = await create(flow, proposal())
    flow.context = approver
    response = await decide(flow, response.json()["id"], expected_base_version=3)
    assert response.status_code == 200, response.text
    assert await flow.admin.fetchval("SELECT count(*) FROM sanction_case_events WHERE event_type='affected_by_rectification'") == 1
    assert dict(await flow.admin.fetchrow("SELECT * FROM sanction_resolutions")) == resolution
    flow.context = requester
    response = await create(flow, body)
    flow.context = approver
    response = await decide(flow, response.json()["id"], expected_base_version=4)
    assert response.status_code == 200, response.text
    successor = await flow.admin.fetchval("SELECT id FROM player_suspensions WHERE status='active'")
    assert successor != source["id"]
    assert await flow.admin.fetchval("SELECT count(*) FROM sanction_resolutions WHERE suspension_id=$1", successor) == 0
    async with case_service(flow) as service:
        new_case = await service.submit_appeal(requester, AppealRequest(suspension_id=successor,
            represented_player_id=PLAYER_HOME_FIRST, reason="Revisión expresa", prior_case_id=case["id"]))
    assert new_case["id"] != case["id"]
