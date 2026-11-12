"""Spec 033 T10: scoped platform authority, real RLS and atomic decisions."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.core.database import set_rls_context
from app.core.security import get_current_user_id
from app.core.tenancy import AuthContext
from app.main import api
from app.modules.rectifications.platform import RectificationPlatformService
from test_migration_031 import MEMBER, ORG, USER
from test_rectification_flow import add_approver, create, database_snapshot, proposal
from test_rectification_flow import flow as flow


@pytest.fixture
async def platform_flow(flow):
    flow.platform_user = uuid4()
    await flow.admin.execute("INSERT INTO users (id, email, full_name) VALUES ($1, 'platform@example.test', 'Platform')", flow.platform_user)
    await flow.admin.execute("INSERT INTO platform_admins (user_id, role_code) VALUES ($1, 'platform_admin')", flow.platform_user)

    async def current_user():
        return flow.platform_user

    api.dependency_overrides[get_current_user_id] = current_user
    yield flow
    api.dependency_overrides.pop(get_current_user_id, None)


async def grant(flow, request_id, **changes):
    return await flow.client.post(f"/api/v1/rectifications/{request_id}/platform-authorizations",
        json={"platform_admin_email": " PLATFORM@example.test ", "reason": " Revisión independiente ", **changes})


async def decision(flow, request_id, **changes):
    return await flow.client.post(f"/api/v1/platform/rectifications/{request_id}/decision",
        json={"decision": "approve", "reason": "Verificado", "expected_base_version": 1, **changes})


async def authorized(flow, body=None):
    request = (await create(flow, body)).json()
    authorization = await grant(flow, request["id"])
    assert authorization.status_code == 201, authorization.text
    return request, authorization.json()


@pytest.mark.parametrize("value", ["absent@example.test", "migration-031@example.test", "invalid"])
async def test_unknown_nonadmin_and_malformed_email_are_uniform_422(platform_flow, value):
    f = platform_flow
    request = (await create(f)).json()
    response = await grant(f, request["id"], platform_admin_email=value)
    assert response.status_code == 422
    assert response.json() == {"detail": "Administrador de plataforma no válido"}
    assert await f.admin.fetchval("SELECT count(*) FROM match_report_platform_authorizations") == 0


@pytest.mark.parametrize("change", ["support", "inactive_admin", "inactive_user"])
async def test_only_active_full_admin_may_be_designated(platform_flow, change):
    f = platform_flow
    request = (await create(f)).json()
    if change == "support":
        await f.admin.execute("UPDATE platform_admins SET role_code = 'platform_support'")
    elif change == "inactive_admin":
        await f.admin.execute("UPDATE platform_admins SET is_active = FALSE")
    else:
        await f.admin.execute("UPDATE users SET is_active = FALSE WHERE id = $1", f.platform_user)
    response = await grant(f, request["id"])
    assert response.status_code == 422 and response.json() == {"detail": "Administrador de plataforma no válido"}


async def test_owner_grants_revokes_and_audits(platform_flow):
    f = platform_flow
    request, authorization = await authorized(f)
    assert authorization["reason"] == "Revisión independiente"
    assert authorization["granted_by_member_id"] == MEMBER
    listed = await f.client.get("/api/v1/platform/rectifications")
    assert listed.status_code == 200 and [r["id"] for r in listed.json()] == [request["id"]]
    detail = await f.client.get(f"/api/v1/platform/rectifications/{request['id']}")
    assert detail.status_code == 200 and "diff" in detail.json()
    url = f"/api/v1/rectifications/{request['id']}/platform-authorizations/{authorization['id']}"
    revoked = await f.client.delete(url)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"]
    assert (await f.client.delete(url)).status_code == 409
    assert (await f.client.get("/api/v1/platform/rectifications")).json() == []
    assert (await decision(f, request["id"])).status_code == 404
    assert await f.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == 3


async def test_only_owner_pending_and_resource_isolation(platform_flow):
    f = platform_flow
    request = (await create(f)).json()
    owner = f.context
    f.context = await add_approver(f)
    assert (await grant(f, request["id"])).status_code == 403
    f.context = owner
    authorization = (await grant(f, request["id"])).json()
    f.context = AuthContext(UUID(USER.replace("31000000", "32000000")),
        UUID(ORG.replace("31000000", "32000000")), UUID(MEMBER.replace("31000000", "32000000")))
    hidden = await grant(f, request["id"])
    missing = await grant(f, str(uuid4()))
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert (await f.client.delete(f"/api/v1/rectifications/{request['id']}/platform-authorizations/{authorization['id']}")).status_code == 404
    f.context = owner
    assert (await grant(f, str(uuid4()))).status_code == 404
    await f.client.post(f"/api/v1/rectifications/{request['id']}/withdraw")
    assert (await grant(f, request["id"])).status_code == 409


@pytest.mark.parametrize("resolution", ["regular", "walkover", "administrative"])
async def test_platform_publication_consumes_and_records_both_real_actor_audits(platform_flow, resolution):
    f = platform_flow
    body = proposal() if resolution == "regular" else proposal(resolution_type=resolution,
        reason="no_show" if resolution == "walkover" else "Resolución", home_score_regular=3, home_score=3, events=[])
    request, authorization = await authorized(f, body)
    response = await decision(f, request["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published"
    row = await f.admin.fetchrow("SELECT * FROM match_report_rectification_decisions")
    assert row["decided_as"] == "platform_admin" and row["decided_by_member_id"] is None
    assert row["decided_by_user_id"] == f.platform_user and str(row["authorization_id"]) == authorization["id"]
    assert await f.admin.fetchval("SELECT consumed_at FROM match_report_platform_authorizations")
    tenant = await f.admin.fetchrow("SELECT * FROM administrative_audit_logs WHERE performed_by_user_id = $1", f.platform_user)
    assert tenant and tenant["performed_by_member_id"] is None
    audit = await f.admin.fetchrow("SELECT * FROM platform_audit_logs")
    assert audit["actor_user_id"] == f.platform_user and str(audit["organization_id"]) == ORG
    assert (await f.client.get("/api/v1/platform/rectifications")).json() == []
    assert (await decision(f, request["id"])).status_code == 404
    assert (await f.client.delete(f"/api/v1/rectifications/{request['id']}/platform-authorizations/{authorization['id']}")).status_code == 409


@pytest.mark.parametrize("invalidate", ["owner_role", "owner_inactive", "owner_user", "organization", "support", "admin_inactive", "revoked", "consumed"])
async def test_live_authority_is_rechecked(platform_flow, invalidate):
    f = platform_flow
    request, authorization = await authorized(f)
    statements = {
        "owner_role": "DELETE FROM organization_user_roles",
        "owner_inactive": f"UPDATE organization_users SET is_active = FALSE WHERE id = '{MEMBER}'",
        "owner_user": f"UPDATE users SET is_active = FALSE WHERE id = '{USER}'",
        "organization": f"UPDATE organizations SET is_active = FALSE WHERE id = '{ORG}'",
        "support": "UPDATE platform_admins SET role_code = 'platform_support'",
        "admin_inactive": "UPDATE platform_admins SET is_active = FALSE",
        "revoked": "UPDATE match_report_platform_authorizations SET revoked_at = now()",
        "consumed": "UPDATE match_report_platform_authorizations SET consumed_at = now()",
    }
    await f.admin.execute(statements[invalidate])
    before = await database_snapshot(f.admin)
    response = await decision(f, request["id"])
    assert response.status_code in (403, 404)
    assert await database_snapshot(f.admin) == before


async def test_missing_authority_and_other_admin_are_indistinguishable(platform_flow):
    f = platform_flow
    request = (await create(f)).json()
    hidden = await decision(f, request["id"])
    missing = await decision(f, str(uuid4()))
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    await authorized_after_create(f, request)
    other = uuid4()
    await f.admin.execute("INSERT INTO users (id, email, full_name) VALUES ($1, 'other-admin@test.dev', 'Other')", other)
    await f.admin.execute("INSERT INTO platform_admins (user_id, role_code) VALUES ($1, 'platform_admin')", other)
    f.platform_user = other
    assert (await f.client.get("/api/v1/platform/rectifications")).json() == []
    assert (await decision(f, request["id"])).status_code == 404


async def authorized_after_create(f, request):
    assert (await grant(f, request["id"])).status_code == 201


async def test_self_approval_and_failure_do_not_consume(platform_flow):
    f = platform_flow
    await f.admin.execute("INSERT INTO platform_admins (user_id, role_code) VALUES ($1, 'platform_admin')", USER)
    f.platform_user = UUID(USER)
    request = (await create(f)).json()
    email = await f.admin.fetchval("SELECT email FROM users WHERE id = $1", USER)
    assert (await grant(f, request["id"], platform_admin_email=email)).status_code == 201
    before = await database_snapshot(f.admin)
    response = await decision(f, request["id"])
    assert response.status_code == 403 and response.json()["code"] == "RECTIFICATION_SELF_APPROVAL"
    assert await database_snapshot(f.admin) == before


async def test_stale_rollback_and_concurrent_rejection_consumes_once(platform_flow):
    f = platform_flow
    request, _ = await authorized(f)
    before = await database_snapshot(f.admin)
    stale = await decision(f, request["id"], expected_base_version=2)
    assert stale.status_code == 409 and stale.json()["code"] == "RECTIFICATION_STALE"
    assert await database_snapshot(f.admin) == before
    responses = await asyncio.gather(decision(f, request["id"], decision="reject"), decision(f, request["id"], decision="reject"))
    assert sorted(r.status_code for r in responses) in ([200, 404], [200, 409])
    assert await f.admin.fetchval("SELECT count(*) FROM platform_audit_logs") == 1
    assert await f.admin.fetchval("SELECT count(*) FROM match_report_rectification_decisions") == 1


async def test_transaction_scope_and_no_forged_scope(platform_flow):
    f = platform_flow
    request, authorization = await authorized(f)
    async with f.engine.connect() as connection:
        await connection.execute(text("SET ROLE bracket_app"))
        await connection.commit()
        for auth, organization, user, visible in [
            (None, ORG, f.platform_user, 0), (str(uuid4()), ORG, f.platform_user, 0),
            (authorization["id"], ORG.replace("31000000", "32000000"), f.platform_user, 0),
            (authorization["id"], ORG, uuid4(), 0), (authorization["id"], ORG, f.platform_user, 2),
        ]:
            async with connection.begin():
                await set_rls_context(connection, UUID(organization), user)
                if auth:
                    await connection.execute(text("SELECT set_config('app.rectification_authorization_id', :id, true)"), {"id": auth})
                assert (await connection.execute(text("SELECT count(*) FROM matches"))).scalar_one() == visible
        async with connection.begin():
            await set_rls_context(connection, UUID(ORG), f.platform_user)
            assert (await connection.execute(text("SELECT count(*) FROM matches"))).scalar_one() == 0


@pytest.mark.parametrize("body", [{"reason": "  "}, {"extra": "forbidden"}])
async def test_authorization_body_is_strict(platform_flow, body):
    f = platform_flow
    request = (await create(f)).json()
    before = await database_snapshot(f.admin)
    assert (await grant(f, request["id"], **body)).status_code == 422
    assert await database_snapshot(f.admin) == before


async def test_failure_after_consumption_rolls_back_publication_and_both_audits(platform_flow, monkeypatch):
    f = platform_flow
    request, _ = await authorized(f)
    before = await database_snapshot(f.admin)
    decide_locked = RectificationPlatformService._decide_locked

    async def fail_after_decision(*args, **kwargs):
        await decide_locked(*args, **kwargs)
        raise ValueError("Interrupción antes del commit")

    monkeypatch.setattr(RectificationPlatformService, "_decide_locked", fail_after_decision)
    response = await decision(f, request["id"])
    assert response.status_code == 409
    assert await database_snapshot(f.admin) == before
