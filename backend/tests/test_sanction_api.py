from uuid import uuid4
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.platform import PlatformContext, get_platform_context
from app.core.tenancy import get_auth_context
from app.main import api
from test_sanction_cases import appeal, permissions, second_member
from test_sanction_cases import cases as cases
from test_sanction_readers import readers as readers
from test_sanction_platform import authorized_case


@pytest.fixture
async def client(cases):
    async def database():
        async with cases.service() as service:
            yield service.db
    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = lambda: cases.context
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        yield client
    api.dependency_overrides.clear()


async def test_member_contracts_and_private_evidence(cases, client):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    payload = appeal(f).model_dump(mode="json", exclude={"suspension_id"})
    response = await client.post(f"/api/v1/sanctions/{f.suspension}/appeals", json=payload)
    assert response.status_code == 201, response.text
    case = response.json()
    assert set(case) == {"id", "status"}
    path = f"/api/v1/sanction-cases/{case['id']}"
    assert (await client.get(path)).status_code == 403
    await permissions(f, "VIEW_SANCTION_CASES", "SUBMIT_SANCTION_APPEALS")
    assert (await client.get(path)).status_code == 200
    assert (await client.get(path + "/preview")).status_code == 403
    assert (await client.get(f"/api/v1/sanction-cases/{uuid4()}")).status_code == 404
    assert (await client.get("/api/v1/sanctions?limit=0")).status_code == 422
    assert (await client.get("/api/v1/sanction-cases?extra=true")).status_code == 422
    reviewer = await second_member(f, "RESOLVE_SANCTION_CASES", "VIEW_SANCTION_CASES")
    api.dependency_overrides[get_auth_context] = lambda: reviewer
    assert (await client.get(path + "/preview")).json()["can_decide"]
    decision = {"decision": "maintain", "expected_base_duration": 3, "reason": "Revisado"}
    assert (await client.post(path + "/decision", json=decision)).status_code == 200
    assert (await client.post(path + "/withdraw", json={"reason": "Tarde"})).status_code == 403


async def test_writing_unknown_fields_and_no_platform_submission(client, cases):
    await permissions(cases, "SUBMIT_SANCTION_APPEALS")
    payload = appeal(cases).model_dump(mode="json", exclude={"suspension_id"})
    response = await client.post(f"/api/v1/sanctions/{cases.suspension}/appeals", json={**payload, "status": "resolved"})
    assert response.status_code == 422
    assert (await client.post(f"/api/v1/platform/sanctions/{cases.suspension}/appeals", json=payload)).status_code == 404


async def test_platform_http_scope_preview_decision_and_support_denial(cases, client):
    case, platform, _ = await authorized_case(cases)
    api.dependency_overrides[get_platform_context] = lambda: platform
    path = f"/api/v1/platform/sanction-cases/{case['id']}"
    assert (await client.get("/api/v1/platform/sanction-cases")).json()["total"] == 1
    assert (await client.get(path)).status_code == 200
    assert (await client.get(path + "/preview")).json()["can_decide"]
    assert (await client.get(f"/api/v1/platform/sanction-cases/{uuid4()}")).status_code == 404
    payload = {"decision": "maintain", "expected_base_duration": 3, "reason": "Decisión"}
    assert (await client.post(path + "/decision", json={**payload,"expected_base_duration":2})).status_code == 409
    assert (await client.post(path + "/decision", json=payload)).status_code == 200
    assert (await client.get(path)).status_code == 404
    api.dependency_overrides[get_platform_context] = lambda: PlatformContext(platform.user_id, "platform_support")
    assert (await client.get("/api/v1/platform/sanction-cases")).status_code == 403


async def test_anonymous_requires_session(client):
    api.dependency_overrides.pop(get_auth_context)
    assert (await client.get("/api/v1/sanction-cases")).status_code == 401


async def test_domain_conflicts_expose_stable_codes_without_private_data(cases, client):
    f = cases
    await permissions(f,"SUBMIT_SANCTION_APPEALS","RESOLVE_SANCTION_CASES")
    payload = appeal(f).model_dump(mode="json",exclude={"suspension_id"})
    path = f"/api/v1/sanctions/{f.suspension}/appeals"
    submitted = await client.post(path,json=payload)
    case = submitted.json()
    duplicate = await client.post(path,json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail":"SANCTION_CASE_CONFLICT","code":"SANCTION_CASE_CONFLICT"}
    decision_path = f"/api/v1/sanction-cases/{case['id']}/decision"
    decision = {"decision":"maintain","expected_base_duration":3,"reason":"Revisado"}
    own = await client.post(decision_path,json=decision)
    assert own.status_code == 409
    assert own.json()["code"] == "SANCTION_SELF_DECISION"
    reviewer = await second_member(f,"RESOLVE_SANCTION_CASES")
    api.dependency_overrides[get_auth_context] = lambda:reviewer
    stale = await client.post(decision_path,json={**decision,"expected_base_duration":2})
    assert stale.status_code == 409
    assert stale.json()["code"] == "SANCTION_STALE_BASE"


async def test_withdrawal_evidence_is_optional_private_and_idempotent(cases, client):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f))
    path = f"/api/v1/sanction-cases/{case['id']}/withdraw"
    payload = {"reason": "Retiro", "evidence_text": "PRIVATE_WITHDRAWAL", "evidence_links": ["https://example.test/evidence"]}
    assert (await client.post(path, json=payload)).status_code == 200
    assert (await client.post(path, json=payload)).status_code == 200
    assert (await client.post(path, json={**payload,"evidence_text":"Otro"})).status_code == 409
    event = await f.admin.fetchrow("SELECT * FROM sanction_case_events WHERE event_type='withdrawn'")
    assert event["evidence_text"] == "PRIVATE_WITHDRAWAL"
    assert json.loads(event["evidence_links"]) == payload["evidence_links"]
    assert "PRIVATE_WITHDRAWAL" not in str(await f.admin.fetch("SELECT payload FROM outbox_events"))
