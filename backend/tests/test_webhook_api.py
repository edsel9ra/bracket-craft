"""API de gestión de webhooks contra PostgreSQL (spec 047, T3; opt-in ``RUN_DATABASE_TESTS=1``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from db_helpers import create_tenant_owner
from migration_helpers import connect
from test_match_assists_db import committed_application, seeded_match
from test_notification_api import add_member
from test_request_schema_strictness import walk_routes

URL = "/api/v1/webhooks"
HOOK = "https://hooks.example.com/bc/secret-path?token=abc"
TYPES = ["result_confirmed", "match_scheduled"]
PUBLIC_KEYS = {"id", "url", "event_types", "is_active", "created_at", "updated_at"}
DELIVERY_KEYS = {"id", "event_type", "created_at", "attempts", "last_status_code", "status"}
NOT_FOUND = {"detail": "Webhook no encontrado"}


@dataclass
class Hooks:
    client: AsyncClient
    admin: object
    owner: AuthContext
    operator: AuthContext
    stranger: AuthContext
    context: AuthContext | None = None


@pytest.fixture
async def hooks(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        owner, _match = await seeded_match(engine)
        admin = await connect(database_admin_url, engine.url.database)
        try:
            user = await admin.fetchval("""INSERT INTO users (email,password_hash,full_name)
                VALUES ('operador-047@example.test','hash','Olga Operadora') RETURNING id""")
            operator = await add_member(admin, owner.organization_id, user, "operator")
            async with AsyncSession(engine, expire_on_commit=False) as session:
                tenant = await create_tenant_owner(session, full_name="Otra organización 047")
                await session.commit()
            stranger = AuthContext(tenant.user_id, tenant.organization_id, tenant.member_id)

            async def database():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    yield session

            state = Hooks(None, admin, owner, operator, stranger, owner)

            async def auth_context():
                return state.context

            api.dependency_overrides[get_db] = database
            api.dependency_overrides[get_auth_context] = auth_context
            try:
                async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
                    state.client = client
                    yield state
            finally:
                api.dependency_overrides.clear()
        finally:
            await admin.close()


async def create(hooks, url=HOOK, types=TYPES):
    response = await hooks.client.post(URL, json={"url": url, "event_types": types})
    assert response.status_code == 201, response.text
    return response.json()


async def stored_secret(admin, webhook_id):
    return await admin.fetchval(
        "SELECT pgp_sym_decrypt(secret_encrypted, $2) FROM organization_webhooks WHERE id=$1",
        webhook_id, get_settings().webhook_secret_key)


async def audits(admin, action=None):
    rows = await admin.fetch(
        """SELECT action, entity_type, entity_id, payload, performed_by_member_id
           FROM administrative_audit_logs WHERE entity_type='organization_webhooks'
             AND ($1::text IS NULL OR action=$1) ORDER BY performed_at, id""", action)
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]


async def test_routes_are_registered():
    methods = {(path, method) for path, route in walk_routes(api.routes)
               if path.startswith(URL) for method in route.methods}
    item = f"{URL}/{{webhook_id}}"
    assert methods == {
        (URL, "GET"), (URL, "POST"), (item, "PATCH"), (item, "DELETE"),
        (f"{item}/rotate-secret", "POST"), (f"{item}/test", "POST"), (f"{item}/deliveries", "GET"),
    }


async def test_create_shows_the_secret_once_and_stores_it_encrypted(hooks):
    body = await create(hooks)
    assert set(body) == PUBLIC_KEYS | {"secret"}
    assert body["secret"].startswith("whsec_")
    assert (body["url"], body["event_types"], body["is_active"]) == (HOOK, sorted(TYPES), True)
    assert await stored_secret(hooks.admin, body["id"]) == body["secret"]
    listed = await hooks.client.get(URL)
    assert listed.status_code == 200
    assert [set(item) for item in listed.json()] == [PUBLIC_KEYS]
    assert body["secret"] not in listed.text
    [entry] = await audits(hooks.admin)
    assert (entry["action"], str(entry["entity_id"]), entry["performed_by_member_id"]) == (
        "CREATE_WEBHOOK", body["id"], hooks.owner.organization_user_id)
    assert entry["payload"] == {"host": "hooks.example.com", "event_types": sorted(TYPES), "is_active": True}


@pytest.mark.parametrize("payload", [
    {"url": "http://hooks.example.com/", "event_types": TYPES},
    {"url": "https://user:pw@hooks.example.com/", "event_types": TYPES},
    {"url": "https://hooks.example.com/" + "a" * 2048, "event_types": TYPES},
    {"url": HOOK, "event_types": []},
    {"url": HOOK, "event_types": ["webhook_test"]},
    {"url": HOOK, "event_types": ["unknown"]},
    {"url": HOOK, "event_types": TYPES, "secret": "mine"},
    {"url": HOOK},
])
async def test_invalid_creation_is_rejected_without_saving(hooks, payload):
    response = await hooks.client.post(URL, json=payload)
    assert response.status_code == 422
    assert await hooks.admin.fetchval("SELECT count(*) FROM organization_webhooks") == 0
    assert await audits(hooks.admin) == []


async def test_an_organization_has_at_most_ten_webhooks(hooks):
    for number in range(10):
        await create(hooks, url=f"https://hooks.example.com/{number}")
    response = await hooks.client.post(URL, json={"url": HOOK, "event_types": TYPES})
    assert (response.status_code, response.json()) == (409, {"detail": "WEBHOOK_LIMIT_REACHED"})
    hooks.context = hooks.stranger
    await create(hooks)


async def test_management_requires_manage_webhooks(hooks):
    webhook = await create(hooks)
    hooks.context = hooks.operator
    item = f"{URL}/{webhook['id']}"
    for method, path, payload in [
        ("GET", URL, None), ("POST", URL, {"url": HOOK, "event_types": TYPES}),
        ("PATCH", item, {"is_active": False}), ("DELETE", item, None),
        ("POST", f"{item}/rotate-secret", None), ("POST", f"{item}/test", None), ("GET", f"{item}/deliveries", None),
    ]:
        response = await hooks.client.request(method, path, json=payload)
        assert response.status_code == 403, (method, path, response.text)
    assert await hooks.admin.fetchval("SELECT count(*) FROM organization_webhooks") == 1
    assert len(await audits(hooks.admin)) == 1


async def test_other_organizations_get_the_same_404_as_a_missing_webhook(hooks):
    webhook = await create(hooks)
    hooks.context = hooks.stranger
    assert (await hooks.client.get(URL)).json() == []
    for webhook_id in (webhook["id"], str(uuid4())):
        item = f"{URL}/{webhook_id}"
        for method, path, payload in [
            ("PATCH", item, {"is_active": False}), ("DELETE", item, None),
            ("POST", f"{item}/rotate-secret", None), ("POST", f"{item}/test", None),
            ("GET", f"{item}/deliveries", None),
        ]:
            response = await hooks.client.request(method, path, json=payload)
            assert (response.status_code, response.json()) == (404, NOT_FOUND), (method, path)
    row = await hooks.admin.fetchrow("SELECT is_active, url FROM organization_webhooks WHERE id=$1", webhook["id"])
    assert (row["is_active"], row["url"]) == (True, HOOK)
    assert len(await audits(hooks.admin)) == 1


async def test_edit_url_and_types_is_audited_with_the_domain_only(hooks):
    webhook = await create(hooks)
    response = await hooks.client.patch(
        f"{URL}/{webhook['id']}",
        json={"url": "https://other.example.org/x?y=1", "event_types": ["sanction_generated"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == PUBLIC_KEYS
    assert (body["url"], body["event_types"]) == ("https://other.example.org/x?y=1", ["sanction_generated"])
    [entry] = await audits(hooks.admin, "UPDATE_WEBHOOK")
    assert entry["payload"] == {"host": "other.example.org", "event_types": ["sanction_generated"], "is_active": True}
    assert "/x" not in json.dumps(entry["payload"]) and "y=1" not in json.dumps(entry["payload"])


@pytest.mark.parametrize("payload", [
    {}, {"url": None}, {"event_types": None}, {"is_active": None}, {"url": "http://x.example/"},
    {"event_types": []}, {"is_active": "no"}, {"secret": "x"},
])
async def test_invalid_edits_are_rejected(hooks, payload):
    webhook = await create(hooks)
    response = await hooks.client.patch(f"{URL}/{webhook['id']}", json=payload)
    assert response.status_code == 422
    assert len(await audits(hooks.admin)) == 1


async def test_deactivation_discards_pending_and_blocks_tests(hooks):
    webhook = await create(hooks)
    item = f"{URL}/{webhook['id']}"
    sent = await hooks.client.post(f"{item}/test")
    assert sent.status_code == 202, sent.text
    off = await hooks.client.patch(item, json={"is_active": False})
    assert (off.status_code, off.json()["is_active"]) == (200, False)
    row = await hooks.admin.fetchrow(
        """SELECT d.status, e.status AS event_status FROM webhook_deliveries d
           JOIN outbox_events e ON e.id = d.outbox_event_id WHERE d.id=$1""", sent.json()["delivery_id"])
    assert (row["status"], row["event_status"]) == ("discarded", "processed")
    blocked = await hooks.client.post(f"{item}/test")
    assert (blocked.status_code, blocked.json()) == (409, {"detail": "WEBHOOK_INACTIVE"})
    on = await hooks.client.patch(item, json={"is_active": True})
    assert on.json()["is_active"] is True
    assert [entry["payload"]["is_active"] for entry in await audits(hooks.admin, "SET_WEBHOOK_ACTIVE")] == [False, True]
    assert await audits(hooks.admin, "UPDATE_WEBHOOK") == []
    same = await hooks.client.patch(item, json={"is_active": True})
    assert same.status_code == 200
    assert len(await audits(hooks.admin, "SET_WEBHOOK_ACTIVE")) == 2


async def test_rotation_shows_the_new_secret_once(hooks):
    webhook = await create(hooks)
    response = await hooks.client.post(f"{URL}/{webhook['id']}/rotate-secret")
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"secret"}
    secret = response.json()["secret"]
    assert secret != webhook["secret"] and secret.startswith("whsec_")
    assert await stored_secret(hooks.admin, webhook["id"]) == secret
    [entry] = await audits(hooks.admin, "ROTATE_WEBHOOK_SECRET")
    assert entry["payload"] == {"host": "hooks.example.com"}
    assert secret not in (await hooks.client.get(URL)).text


async def test_deliveries_list_the_latest_fifty_of_thirty_days(hooks):
    webhook = await create(hooks)
    sent = await hooks.client.post(f"{URL}/{webhook['id']}/test")
    assert set(sent.json()) == {"delivery_id"}
    await hooks.admin.execute(
        """INSERT INTO webhook_deliveries (id, organization_id, webhook_id, event_type, body, status, attempts, created_at)
           SELECT gen_random_uuid(), $1, $2, 'webhook_test', '{}'::jsonb, 'delivered', 1,
                  CURRENT_TIMESTAMP - make_interval(hours => n)
           FROM generate_series(1, 60) AS n""", hooks.owner.organization_id, webhook["id"])
    await hooks.admin.execute(
        """INSERT INTO webhook_deliveries (id, organization_id, webhook_id, event_type, body, status, created_at)
           VALUES (gen_random_uuid(), $1, $2, 'webhook_test', '{}'::jsonb, 'failed',
                   CURRENT_TIMESTAMP - interval '31 days')""", hooks.owner.organization_id, webhook["id"])
    response = await hooks.client.get(f"{URL}/{webhook['id']}/deliveries")
    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) == 50
    assert all(set(item) == DELIVERY_KEYS for item in items)
    assert items[0]["id"] == sent.json()["delivery_id"]
    assert (items[0]["event_type"], items[0]["status"], items[0]["attempts"]) == ("webhook_test", "pending", 0)
    assert [item["created_at"] for item in items] == sorted((item["created_at"] for item in items), reverse=True)
    assert "failed" not in {item["status"] for item in items}


async def test_delete_removes_the_webhook_and_its_deliveries(hooks):
    webhook = await create(hooks)
    item = f"{URL}/{webhook['id']}"
    sent = await hooks.client.post(f"{item}/test")
    event = await hooks.admin.fetchval(
        "SELECT outbox_event_id FROM webhook_deliveries WHERE id=$1", sent.json()["delivery_id"])
    response = await hooks.client.delete(item)
    assert response.status_code == 204
    assert await hooks.admin.fetchval("SELECT count(*) FROM organization_webhooks") == 0
    assert await hooks.admin.fetchval("SELECT count(*) FROM webhook_deliveries") == 0
    assert await hooks.admin.fetchval("SELECT status FROM outbox_events WHERE id=$1", event) == "processed"
    [entry] = await audits(hooks.admin, "DELETE_WEBHOOK")
    assert (str(entry["entity_id"]), entry["payload"]) == (webhook["id"], {"host": "hooks.example.com"})
    again = await hooks.client.delete(item)
    assert (again.status_code, again.json()) == (404, NOT_FOUND)
