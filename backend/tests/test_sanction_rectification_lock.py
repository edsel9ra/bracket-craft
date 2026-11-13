import pytest
from sqlalchemy import event

from test_migration_031 import ORG
from test_rectification_flow import add_approver, create
from test_rectification_platform import grant
from test_rectification_platform import platform_flow as platform_flow
from test_rectification_flow import flow as flow


@pytest.mark.parametrize("platform", [False, True])
@pytest.mark.parametrize("operation", ["preview", "decision"])
async def test_rectification_lock_preserves_minimum_permissions(platform_flow, platform, operation):
    f = platform_flow
    await f.admin.execute("UPDATE roles SET permissions='[\"REQUEST_MATCH_REPORT_RECTIFICATION\"]' WHERE organization_id=$1", ORG)
    statements = []
    event.listen(f.engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2].lower()))
    created = await create(f)
    assert created.status_code == 201, created.text
    assert next(i for i, sql in enumerate(statements) if "discipline:" in sql) < next(
        i for i, sql in enumerate(statements) if "from stages" in sql and "for update" in sql)
    request_id = created.json()["id"]
    if platform:
        authorized = await grant(f, request_id)
        assert authorized.status_code == 201, authorized.text
    else:
        f.context = await add_approver(f, permissions=["APPROVE_MATCH_REPORT_RECTIFICATION"])
    statements.clear()
    prefix = "/api/v1/platform" if platform else "/api/v1"
    path = f"{prefix}/rectifications/{request_id}/{operation}"
    response = await f.client.get(path) if operation == "preview" else await f.client.post(path,
        json={"decision": "approve", "reason": "Verificado", "expected_base_version": 1})
    assert response.status_code == 200, response.text
    coordinator = next(i for i, sql in enumerate(statements) if "discipline:" in sql)
    stage = next(i for i, sql in enumerate(statements) if "from stages" in sql and "for update" in sql)
    request = next(i for i, sql in enumerate(statements) if "from match_report_rectification_requests" in sql and "for update" in sql)
    assert coordinator < stage < request
