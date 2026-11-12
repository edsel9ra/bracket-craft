"""Scoped GET preview simulates publication without durable effects."""

from uuid import UUID, uuid4

import pytest

from app.modules.rectifications.platform import RectificationPlatformService
from test_migration_031 import MATCH
from test_rectification_flow import create, database_snapshot
from test_rectification_platform import authorized, decision
from test_rectification_platform import platform_flow as platform_flow
from test_rectification_flow import flow as flow


async def test_platform_preview_and_detail_have_current_version_and_rollback_everything(platform_flow):
    f = platform_flow
    request, authorization = await authorized(f)
    before = await database_snapshot(f.admin)
    detail = await f.client.get(f"/api/v1/platform/rectifications/{request['id']}")
    assert detail.status_code == 200
    assert detail.json()["current_version"]["version_number"] == 1
    for _ in range(2):
        response = await f.client.get(f"/api/v1/platform/rectifications/{request['id']}/preview")
        assert response.status_code == 200, response.text
        assert response.json()["expected_base_version"] == 1
        assert response.json()["version"]["version_number"] == 2
        assert response.json()["effects"]
        assert await database_snapshot(f.admin) == before
    assert await f.admin.fetchval("SELECT consumed_at FROM match_report_platform_authorizations WHERE id=$1", UUID(authorization['id'])) is None
    assert (await decision(f, request["id"])).status_code == 200


@pytest.mark.parametrize("invalidate", ["missing", "revoked", "consumed"])
async def test_inaccessible_preview_and_detail_are_indistinguishable_404(platform_flow, invalidate):
    f = platform_flow
    request = (await create(f)).json() if invalidate == "missing" else (await authorized(f))[0]
    if invalidate == "revoked":
        await f.admin.execute("UPDATE match_report_platform_authorizations SET revoked_at=now()")
    if invalidate == "consumed":
        await f.admin.execute("UPDATE match_report_platform_authorizations SET consumed_at=now()")
    before = await database_snapshot(f.admin)
    for suffix in ["", "/preview"]:
        response = await f.client.get(f"/api/v1/platform/rectifications/{request['id']}{suffix}")
        absent = await f.client.get(f"/api/v1/platform/rectifications/{uuid4()}{suffix}")
        assert response.status_code == absent.status_code == 404 and response.json() == absent.json()
    assert await database_snapshot(f.admin) == before


async def test_preview_failure_after_publication_rolls_back_all_tables(platform_flow, monkeypatch):
    f = platform_flow
    request, _ = await authorized(f)
    before = await database_snapshot(f.admin)
    publish = RectificationPlatformService._publish

    async def fail(self, *args, **kwargs):
        await publish(self, *args, **kwargs)
        raise ValueError("simulation failed")

    monkeypatch.setattr(RectificationPlatformService, "_publish", fail)
    response = await f.client.get(f"/api/v1/platform/rectifications/{request['id']}/preview")
    assert response.status_code == 409 and response.json()["detail"] == "simulation failed"
    assert await database_snapshot(f.admin) == before


async def test_member_preview_also_exposes_its_base_version(flow):
    request = (await create(flow)).json()
    response = await flow.client.get(f"/api/v1/rectifications/{request['id']}/preview")
    assert response.status_code == 200
    assert response.json()["expected_base_version"] == 1
    assert str(response.json()["version"]["match_id"]) == MATCH
