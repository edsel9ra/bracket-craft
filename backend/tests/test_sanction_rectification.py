from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sanction_appeals.cases import SanctionCaseService
from app.modules.sanction_appeals.schemas import AppealRequest
from app.modules.rectifications import effects
from migration_helpers import apply_migrations
from test_migration_031 import ORG, PLAYER_HOME_FIRST
from test_rectification_flow import create, decide, proposal
from test_rectification_flow import flow as flow
from test_rectification_sanctions import card_report, submit


@asynccontextmanager
async def case_service(flow):
    async with flow.engine.connect() as connection:
        await connection.execute(text("SET ROLE bracket_app"))
        await connection.commit()
        async with AsyncSession(bind=connection) as db:
            yield SanctionCaseService(db)


@pytest.mark.parametrize("changed", [False, True])
async def test_closure_from_publication_without_case_view(flow, changed):
    await apply_migrations(flow.admin, first=44)
    requester = flow.context
    body = card_report()
    request = await submit(flow, body)
    assert (await decide(flow, request)).status_code == 200
    approver = flow.context
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
