"""Publication locks precede origin and impact match locks, including previews."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import locking
from app.main import api
from app.modules.rectifications import advancement, impacts, service
from test_migration_031 import MATCH, ORG, SEGMENT_FIRST, TEAM_AWAY
from test_rectification_effects import TARGET, pending, reversed_report
from test_rectification_flow import UNCONFIRMED, proposal
from test_rectification_flow import flow as flow


@pytest.mark.parametrize("flow,other_match,lock_module", [
    ({"advancement": {"origin": "manual"}}, TARGET, advancement),
    ({"advancement": {"no_link": True, "later_phase": True, "target_in_later": True}}, UNCONFIRMED, impacts),
], indirect=["flow"])
@pytest.mark.parametrize("first_operation,second_operation", [
    ("preview", "preview"), ("preview", "decision"),
    ("decision", "preview"), ("decision", "decision"),
])
async def test_concurrent_rectifications_do_not_deadlock(flow, monkeypatch, other_match, lock_module,
                                                      first_operation, second_operation):
    await flow.admin.execute("UPDATE matches SET away_team_id=$2 WHERE id=$1", other_match, TEAM_AWAY)
    segment = await flow.admin.fetchval("""INSERT INTO match_segments
        (organization_id,match_id,segment_number,minute_start,minute_end,status)
        VALUES ($1,$2,1,0,45,'completed') RETURNING id""", ORG, other_match)
    await flow.admin.execute("""INSERT INTO match_lineup_snapshots
        (organization_id,match_id,segment_id,team_id,player_id,is_starter,position_slot)
        SELECT organization_id,$1,$2,team_id,player_id,is_starter,position_slot
        FROM match_lineup_snapshots WHERE match_id=$3 AND segment_id=$4""",
        other_match, segment, MATCH, SEGMENT_FIRST)
    await flow.admin.execute("""UPDATE matches SET status='finished',result_confirmed=TRUE,
        resolution_type='regular',home_score_regular=0,away_score_regular=0,home_score=0,away_score=0
        WHERE id=$1""", other_match)
    body = proposal()
    body["proposed_report"]["events"][0]["segment_id"] = str(segment)
    second = await flow.client.post(f"/api/v1/matches/{other_match}/rectifications", json=body)
    assert second.status_code == 201, second.text
    first = await pending(flow, reversed_report())
    second_id = second.json()["id"]
    second_at_coordinator, first_at_target = asyncio.Event(), asyncio.Event()
    load_match = service.RectificationService._match
    lock_discipline = locking.lock_discipline
    lock_matches = locking.lock_matches

    async def identify(instance, context, match_id, **kwargs):
        if kwargs.get("lock"):
            instance.db.info["rectification_match"] = str(match_id)
        return await load_match(instance, context, match_id, **kwargs)

    async def coordinator_gate(db, *args, **kwargs):
        if db.info.get("rectification_match") == other_match:
            second_at_coordinator.set()
            await asyncio.wait_for(first_at_target.wait(), timeout=10)
        return await lock_discipline(db, *args, **kwargs)

    async def target_gate(db, organization_id, match_ids):
        ids = list(match_ids)
        if db.info.get("rectification_match") == MATCH and str(other_match) in map(str, ids):
            first_at_target.set()
        return await lock_matches(db, organization_id, ids)

    monkeypatch.setattr(service.RectificationService, "_match", identify)
    monkeypatch.setattr(service, "lock_discipline", coordinator_gate)
    monkeypatch.setattr(lock_module, "lock_matches", target_gate)

    async with AsyncClient(transport=ASGITransport(app=api, raise_app_exceptions=False),
                           base_url="http://test", headers={"Origin": "http://localhost:3000"}) as client:
        async def perform(request_id, operation):
            path = f"/api/v1/rectifications/{request_id}/{operation}"
            if operation == "preview":
                return await client.get(path)
            return await client.post(path, json={"decision": "approve", "reason": "Revisado",
                                                 "expected_base_version": 1})

        second_task = asyncio.create_task(perform(second_id, second_operation))
        try:
            await asyncio.wait_for(second_at_coordinator.wait(), timeout=10)
            first_task = asyncio.create_task(perform(first, first_operation))
            responses = await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=20)
        finally:
            first_at_target.set()
            if not second_task.done():
                second_task.cancel()
                await asyncio.gather(second_task, return_exceptions=True)
        assert [response.status_code for response in responses] == [200, 200], [
            (response.status_code, response.text) for response in responses]
