"""Restoring an outcome already assigned to a destination is not an impact."""

import pytest

from test_migration_031 import MATCH, ORG
from test_rectification_effects import TARGET, fail_d4, pending, reversed_report
from test_rectification_flow import create, database_snapshot, decide, proposal
from test_rectification_flow import flow as flow


@pytest.mark.parametrize("flow", [
    {"advancement": {"origin": "manual", "outcome": outcome, "side": side}}
    for outcome in ["winner", "loser"] for side in ["home", "away"]
], indirect=True)
@pytest.mark.parametrize("condition", ["manual", "segments", "confirmed"])
async def test_restoring_original_outcome_does_not_reopen_unchanged_destination(flow, condition):
    if condition != "manual":
        await fail_d4(flow, condition)
    requester = flow.context
    first = await pending(flow, reversed_report())
    assert (await decide(flow, first)).status_code == 200
    approver = flow.context
    assert await flow.admin.fetchval("SELECT count(*) FROM competitive_impact_procedures") == 1
    assignments = await flow.admin.fetch("SELECT * FROM match_slot_assignments ORDER BY id")
    matches = await flow.admin.fetch("SELECT * FROM matches WHERE id IN ($1,$2) ORDER BY id", MATCH, TARGET)
    flow.context = requester
    second = await create(flow, proposal())
    assert second.status_code == 201, second.text
    assert second.json()["base_version_number"] == 2
    flow.context = approver
    before = await database_snapshot(flow.admin)
    preview = await flow.client.get(f"/api/v1/rectifications/{second.json()['id']}/preview")
    assert preview.status_code == 200, preview.text
    assert not any(effect["effect_type"] in {"advancement", "impact_opened"}
                   for effect in preview.json()["effects"])
    assert await database_snapshot(flow.admin) == before
    response = await decide(flow, second.json()["id"], expected_base_version=2)
    assert response.status_code == 200, response.text
    assert await flow.admin.fetchval("SELECT count(*) FROM competitive_impact_procedures") == 1
    assert await flow.admin.fetchval("""SELECT count(*) FROM match_report_rectification_effects e
        JOIN match_report_versions v ON v.id=e.version_id
        WHERE v.organization_id=$1 AND v.version_number=3
          AND e.effect_type IN ('advancement','impact_opened')""", ORG) == 0
    assert await flow.admin.fetch("SELECT * FROM match_slot_assignments ORDER BY id") == assignments
    assert await flow.admin.fetch("SELECT * FROM matches WHERE id IN ($1,$2) ORDER BY id", MATCH, TARGET) == matches
