"""Organizational inbox, owner authorizations and member-visible impacts."""

import pytest
from copy import deepcopy
import json
from uuid import UUID, uuid4

from app.core.tenancy import AuthContext
from test_migration_031 import MATCH, MEMBER, ORG, TOURNAMENT, USER
from test_rectification_effects import pending, reversed_report
from test_rectification_flow import add_approver, create, decide, proposal
from test_rectification_flow import flow as flow
from test_rectification_platform import authorized
from test_rectification_platform import platform_flow as platform_flow


async def test_request_inbox_pagination_filters_and_isolation(flow):
    first = (await create(flow)).json()
    assert (await flow.client.post(f"/api/v1/rectifications/{first['id']}/withdraw")).status_code == 200
    second = (await create(flow)).json()
    response = await flow.client.get("/api/v1/rectifications?limit=1")
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"items", "total", "limit", "offset"}
    assert response.json()["total"] == 2 and len(response.json()["items"]) == 1
    following = await flow.client.get("/api/v1/rectifications?limit=1&offset=1")
    assert following.json()["items"][0]["id"] != response.json()["items"][0]["id"]
    selected = await flow.client.get(f"/api/v1/rectifications?status=pending&tournament_id={TOURNAMENT}")
    assert [row["id"] for row in selected.json()["items"]] == [second["id"]]
    for tournament in [TOURNAMENT.replace("31000000", "32000000"), "ffffffff-ffff-4fff-8fff-ffffffffffff"]:
        empty = await flow.client.get(f"/api/v1/rectifications?tournament_id={tournament}")
        assert empty.json() == {"items": [], "total": 0, "limit": 25, "offset": 0}
    beyond = await flow.client.get("/api/v1/rectifications?offset=100")
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 2
    await flow.admin.execute("UPDATE roles SET permissions='[]'::jsonb WHERE organization_id=$1", ORG)
    assert (await flow.client.get("/api/v1/rectifications")).status_code == 200
    flow.context = AuthContext(UUID(USER.replace("31000000", "32000000")),
        UUID(ORG.replace("31000000", "32000000")), UUID(MEMBER.replace("31000000", "32000000")))
    foreign = await flow.client.get("/api/v1/rectifications")
    assert foreign.json()["items"] == [] and foreign.json()["total"] == 0


async def test_editor_reads_published_events_in_report_order(flow):
    body = proposal()
    first = body["proposed_report"]["events"][0]
    second = {**deepcopy(first), "minute": 5, "client_event_id": str(uuid4())}
    body["proposed_report"].update(events=[first, second], home_score_regular=2, home_score=2)
    request = await pending(flow, body)
    assert (await decide(flow, request)).status_code == 200
    versions = await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/2")
    assert [event["client_event_id"] for event in versions.json()["report"]["events"]] == [first["client_event_id"], second["client_event_id"]]


@pytest.mark.parametrize("flow", [{"events": [
    {"client_event_id": "ffffffff-ffff-4fff-8fff-ffffffffffff", "minute": 15},
    {"client_event_id": "00000000-0000-4000-8000-000000000001", "minute": 15},
]}], indirect=True)
async def test_editor_reads_original_audit_event_order(flow):
    rows = await flow.admin.fetch("""SELECT id,client_event_id FROM match_events WHERE match_id=$1
        ORDER BY minute DESC,added_minute DESC,created_at DESC,id DESC""", MATCH)
    await flow.admin.execute("""INSERT INTO administrative_audit_logs
        (organization_id,entity_type,entity_id,action,payload,performed_by_member_id)
        VALUES ($1,'matches',$2,'CLOSE_MATCH_REPORT',$3::jsonb,$4)""", ORG, MATCH,
        json.dumps({"event_ids": [str(row["id"]) for row in rows]}), flow.context.organization_user_id)
    response = await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/1")
    assert response.status_code == 200
    assert [event["client_event_id"] for event in response.json()["report"]["events"]] == [row["client_event_id"] for row in rows]


@pytest.mark.parametrize("path", ["rectifications", "competitive-impacts"])
@pytest.mark.parametrize("query", ["extra=true", "limit=0", "limit=101", "offset=-1", "status=invalid", "tournament_id=bad"])
async def test_inbox_query_contract_is_strict(flow, path, query):
    response = await flow.client.get(f"/api/v1/{path}?{query}")
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("flow", [{"advancement": {"origin": "manual"}}], indirect=True)
async def test_members_read_impacts_but_only_approvers_close(flow):
    request = await pending(flow, reversed_report())
    assert (await decide(flow, request)).status_code == 200
    await flow.admin.execute("UPDATE roles SET permissions='[]'::jsonb WHERE organization_id=$1", ORG)
    response = await flow.client.get(f"/api/v1/competitive-impacts?status=open&tournament_id={TOURNAMENT}")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    procedure = response.json()["items"][0]
    beyond = await flow.client.get("/api/v1/competitive-impacts?limit=1&offset=1")
    assert beyond.json() == {"items": [], "total": 1, "limit": 1, "offset": 1}
    by_tournament = await flow.client.get(f"/api/v1/tournaments/{TOURNAMENT}/competitive-impacts")
    assert by_tournament.status_code == 200 and by_tournament.json()[0]["id"] == procedure["id"]
    denied = await flow.client.post(f"/api/v1/competitive-impacts/{procedure['id']}/close", json={"reason": "Conservar"})
    assert denied.status_code == 403
    for tournament in [TOURNAMENT.replace("31000000", "32000000"), "ffffffff-ffff-4fff-8fff-ffffffffffff"]:
        empty = await flow.client.get(f"/api/v1/competitive-impacts?tournament_id={tournament}")
        assert empty.json()["items"] == [] and empty.json()["total"] == 0
    await flow.admin.execute("""UPDATE roles r SET permissions=d.system_permissions
        FROM role_definitions d WHERE r.role_definition_id=d.id AND r.organization_id=$1""", ORG)
    closed = await flow.client.post(f"/api/v1/competitive-impacts/{procedure['id']}/close", json={"reason": "Conservar"})
    assert closed.status_code == 200
    assert (await flow.client.get("/api/v1/competitive-impacts?status=open")).json()["total"] == 0
    assert (await flow.client.get("/api/v1/competitive-impacts?status=closed")).json()["total"] == 1


async def test_only_owner_can_read_platform_authorizations_with_uniform_404(platform_flow):
    f = platform_flow
    request, authorization = await authorized(f)
    path = f"/api/v1/rectifications/{request['id']}/platform-authorizations"
    listing = await f.client.get(path)
    assert listing.status_code == 200, listing.text
    assert listing.json() == [authorization]
    await f.client.delete(f"{path}/{authorization['id']}")
    assert (await f.client.get(path)).json()[0]["revoked_at"] is not None
    owner = f.context
    f.context = await add_approver(f)
    denied = await f.client.get(path)
    absent = await f.client.get("/api/v1/rectifications/ffffffff-ffff-4fff-8fff-ffffffffffff/platform-authorizations")
    assert denied.status_code == absent.status_code == 404 and denied.json() == absent.json()
    f.context = owner
    assert (await f.client.get(f"/api/v1/rectifications/{MATCH}/platform-authorizations")).status_code == 404
