"""Entrega de webhooks en el worker (spec 047, T4: RF-006–RF-011, RNF-001, RNF-002).

Opt-in con ``RUN_DATABASE_TESTS=1``. La entrega nace de un cierre real con el rol
de la aplicación y el worker la envía a un servidor HTTPS local con certificado
propio para ``hooks.test``: el cliente se conecta a la IP comprobada y verifica
el certificado contra el dominio (SNI).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import ssl
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.webhooks import delivery as delivery_module
from app.modules.webhooks.network import resolve_target
from app.workers import outbox
from migration_helpers import connect
from test_match_assists_db import close, committed_application, report_of, seeded_match

HOST = "hooks.test"
SECRET = "whsec_first-secret"
PLAYERS = "SELECT array_agg(first_name || ' ' || last_name) || array_agg(id::text) FROM players"


@pytest.fixture(scope="module")
def certificate(tmp_path_factory) -> tuple[Path, Path]:
    folder = tmp_path_factory.mktemp("tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-keyout", str(key),
         "-out", str(cert), "-subj", f"/CN={HOST}", "-addext", f"subjectAltName=DNS:{HOST}",
         "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,digitalSignature,keyCertSign"],
        check=True, capture_output=True,
    )
    return cert, key


@dataclass
class Receiver:
    """Servidor HTTPS mínimo: registra cada petición y responde según la ruta."""

    port: int = 0
    requests: list[dict] = field(default_factory=list)
    responses: dict[str, tuple[int, float, dict[str, str]]] = field(default_factory=dict)

    async def handle(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {k.strip().lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:] if line)}
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            path = target.split("?", 1)[0]
            self.requests.append({"method": method, "target": target, "path": path, "headers": headers, "body": body})
            status, delay, extra = self.responses.get(path, (200, 0.0, {}))
            if delay:
                await asyncio.sleep(delay)
            response = f"HTTP/1.1 {status} X\r\nContent-Length: 0\r\nConnection: close\r\n"
            response += "".join(f"{k}: {v}\r\n" for k, v in extra.items()) + "\r\n"
            writer.write(response.encode())
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()


@pytest.fixture
async def receiver(certificate):
    cert, key = certificate
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert, key)
    server_receiver = Receiver()
    server = await asyncio.start_server(server_receiver.handle, "127.0.0.1", 0, ssl=context)
    server_receiver.port = server.sockets[0].getsockname()[1]
    try:
        yield server_receiver
    finally:
        server.close()


@pytest.fixture
async def client(certificate):
    verify = ssl.create_default_context(cafile=str(certificate[0]))
    async with delivery_module.build_client(verify=verify) as http:
        yield http


async def loopback(host, port):
    return ["127.0.0.1"]


@dataclass
class World:
    admin: object
    organization_id: object
    match_id: object
    receiver: Receiver
    client: httpx.AsyncClient

    def url(self, path="/bc"):
        return f"https://{HOST}:{self.receiver.port}{path}?token=abc"


async def add_webhook(admin, organization_id, url, *, types=("result_confirmed",), active=True, secret=SECRET):
    member = await admin.fetchval(
        "SELECT id FROM organization_users WHERE organization_id = $1 ORDER BY created_at LIMIT 1", organization_id
    )
    return await admin.fetchval(
        """INSERT INTO organization_webhooks
               (organization_id, url, event_types, is_active, secret_encrypted, created_by_member_id)
           VALUES ($1, $2, $3, $4, pgp_sym_encrypt($5, $6), $7) RETURNING id""",
        organization_id, url, list(types), active, secret, get_settings().webhook_secret_key, member,
    )


@pytest.fixture
async def setup(database_admin_url, monkeypatch, receiver, client):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        admin = await connect(database_admin_url, engine.url.database)

        @asynccontextmanager
        async def factory():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        monkeypatch.setattr(outbox, "SessionFactory", factory)
        world = World(admin, context.organization_id, match.match_id, receiver, client)

        async def produce(*urls, **options):
            hooks = [await add_webhook(admin, context.organization_id, world.url(url), **options) for url in urls]
            await close(engine, context, match.match_id, report_of(home_score_regular=0))
            return hooks

        try:
            yield world, produce
        finally:
            await admin.close()


async def deliver(world, **options):
    in_flight: set[asyncio.Task] = set()
    options.setdefault("resolve", loopback)
    claimed = await outbox.dispatch_webhook_deliveries(world.client, in_flight, **options)
    if in_flight:
        await asyncio.gather(*in_flight)
    return claimed


async def deliveries(world):
    return [dict(row) for row in await world.admin.fetch(
        """SELECT d.id::text, d.webhook_id, d.status, d.attempts, d.last_status_code, d.body,
                  e.status AS event_status, e.attempts AS event_attempts, e.last_error,
                  e.available_at - CURRENT_TIMESTAMP AS wait
           FROM webhook_deliveries d LEFT JOIN outbox_events e ON e.id = d.outbox_event_id
           ORDER BY d.created_at, d.id""")]


async def make_available(world):
    await world.admin.execute(
        "UPDATE outbox_events SET available_at = CURRENT_TIMESTAMP WHERE event_type = 'WEBHOOK_DELIVERY'"
    )


def verify(request, secret):
    headers = request["headers"]
    message = headers["x-bracketcraft-timestamp"].encode() + b"." + request["body"]
    expected = "v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["x-bracketcraft-signature"])


async def test_delivery_is_signed_sent_to_the_checked_ip_and_recorded(setup):
    world, produce = setup
    await produce("/bc")
    assert await deliver(world) == 1
    [request] = world.receiver.requests
    [row] = await deliveries(world)
    headers = request["headers"]
    assert (request["method"], request["target"]) == ("POST", "/bc?token=abc")
    assert headers["host"] == f"{HOST}:{world.receiver.port}"
    assert headers["content-type"] == "application/json"
    assert headers["user-agent"] == "BracketCraft-Webhooks/1"
    assert headers["x-bracketcraft-event"] == "result_confirmed"
    assert headers["x-bracketcraft-delivery"] == row["id"]
    assert verify(request, SECRET)
    assert json.loads(request["body"]) == json.loads(row["body"])
    names = await world.admin.fetchval(PLAYERS)
    payload = request["body"].decode()
    assert names and [name for name in names if name in payload] == []
    assert "player" not in payload
    assert (row["status"], row["attempts"], row["last_status_code"]) == ("delivered", 1, 200)
    assert (row["event_status"], row["last_error"]) == ("processed", None)


async def test_retries_keep_the_delivery_id_and_sign_with_the_rotated_secret(setup):
    world, produce = setup
    [hook] = await produce("/bc")
    world.receiver.responses["/bc"] = (500, 0.0, {})
    await deliver(world)
    [row] = await deliveries(world)
    assert (row["status"], row["attempts"], row["last_status_code"], row["event_status"]) == ("pending", 1, 500, "pending")
    assert 50 <= row["wait"].total_seconds() <= 60
    await world.admin.execute(
        "UPDATE organization_webhooks SET secret_encrypted = pgp_sym_encrypt('whsec_rotated', $2) WHERE id = $1",
        hook, get_settings().webhook_secret_key,
    )
    assert await deliver(world) == 0
    await make_available(world)
    world.receiver.responses["/bc"] = (204, 0.0, {})
    await deliver(world)
    first, second = world.receiver.requests
    assert first["headers"]["x-bracketcraft-delivery"] == second["headers"]["x-bracketcraft-delivery"] == row["id"]
    assert first["body"] == second["body"]
    assert verify(first, SECRET) and verify(second, "whsec_rotated") and not verify(second, SECRET)
    [row] = await deliveries(world)
    assert (row["status"], row["attempts"], row["last_status_code"]) == ("delivered", 2, 204)


async def test_redirects_are_not_followed(setup):
    world, produce = setup
    await produce("/bc")
    world.receiver.responses["/bc"] = (302, 0.0, {"Location": world.url("/elsewhere")})
    await deliver(world)
    assert [request["path"] for request in world.receiver.requests] == ["/bc"]
    [row] = await deliveries(world)
    assert (row["status"], row["last_status_code"], row["event_status"]) == ("pending", 302, "pending")


@pytest.mark.parametrize("status", [400, 404, 410, 500, 503])
async def test_client_and_server_errors_are_retried(setup, status):
    world, produce = setup
    await produce("/bc")
    world.receiver.responses["/bc"] = (status, 0.0, {})
    await deliver(world)
    [row] = await deliveries(world)
    assert (row["status"], row["last_status_code"], row["event_status"], row["last_error"]) == (
        "pending", status, "pending", "WEBHOOK_FAILED")


async def test_a_timeout_is_a_failed_attempt_without_status(setup):
    world, produce = setup
    await produce("/bc")
    world.receiver.responses["/bc"] = (200, 2.0, {})
    await deliver(world, timeout=0.3)
    [row] = await deliveries(world)
    assert (row["status"], row["attempts"], row["last_status_code"], row["event_status"]) == ("pending", 1, None, "pending")


async def test_a_certificate_for_another_domain_fails_the_attempt(setup):
    world, produce = setup
    await produce("/bc")
    await world.admin.execute("UPDATE organization_webhooks SET url = replace(url, 'hooks.test', 'other.test')")
    await deliver(world)
    assert world.receiver.requests == []
    [row] = await deliveries(world)
    assert (row["status"], row["last_status_code"], row["event_status"]) == ("pending", None, "pending")


async def test_the_sixth_failed_attempt_is_final(setup):
    world, produce = setup
    await produce("/bc")
    await world.admin.execute("UPDATE outbox_events SET attempts = 5 WHERE event_type = 'WEBHOOK_DELIVERY'")
    world.receiver.responses["/bc"] = (500, 0.0, {})
    await deliver(world)
    [row] = await deliveries(world)
    assert (row["status"], row["attempts"], row["event_status"], row["last_error"]) == (
        "failed", 6, "processed", "WEBHOOK_FAILED")
    assert await world.admin.fetchval("SELECT is_active FROM organization_webhooks") is True


async def private_dns(host, port):
    return ["93.184.216.34", "10.0.0.7"]


async def broken_dns(host, port):
    raise OSError("dns down")


@pytest.mark.parametrize("dns", [private_dns, broken_dns])
async def test_a_rejected_destination_is_final_without_a_request(setup, dns):
    world, produce = setup
    await produce("/bc")
    await deliver(world, resolve=partial(resolve_target, resolver=dns))
    assert world.receiver.requests == []
    [row] = await deliveries(world)
    assert (row["status"], row["attempts"], row["last_status_code"], row["event_status"], row["last_error"]) == (
        "rejected", 1, None, "processed", "WEBHOOK_REJECTED")


async def test_the_default_resolution_rejects_loopback(setup):
    world, produce = setup
    await produce("/bc")
    await world.admin.execute("UPDATE organization_webhooks SET url = replace(url, 'hooks.test', '127.0.0.1')")
    await deliver(world, resolve=resolve_target)
    assert world.receiver.requests == []
    assert (await deliveries(world))[0]["status"] == "rejected"


@pytest.mark.parametrize("change", ["deactivate", "unsubscribe", "delete"])
async def test_a_deactivated_unsubscribed_or_deleted_webhook_is_not_sent(setup, change):
    world, produce = setup
    await produce("/bc")
    event_id = await world.admin.fetchval("SELECT id FROM outbox_events WHERE event_type = 'WEBHOOK_DELIVERY'")
    statement = {
        "deactivate": "UPDATE organization_webhooks SET is_active = FALSE",
        "unsubscribe": "UPDATE organization_webhooks SET event_types = ARRAY['match_scheduled']",
        "delete": "DELETE FROM organization_webhooks",
    }[change]
    await world.admin.execute(statement)
    assert await deliver(world) == 1
    assert world.receiver.requests == []
    assert await world.admin.fetchval("SELECT status FROM outbox_events WHERE id = $1", event_id) == "processed"
    rows = await deliveries(world)
    assert [row["status"] for row in rows] == ([] if change == "delete" else ["discarded"])


async def test_a_slow_destination_does_not_hold_back_another(setup):
    world, produce = setup
    await produce("/slow", "/fast")
    world.receiver.responses["/slow"] = (200, 1.5, {})
    in_flight: set[asyncio.Task] = set()
    assert await outbox.dispatch_webhook_deliveries(world.client, in_flight, resolve=loopback) == 2
    statuses = {}
    for _ in range(50):
        statuses = {row["webhook_id"]: row["status"] for row in await deliveries(world)}
        if "delivered" in statuses.values():
            break
        await asyncio.sleep(0.05)
    assert sorted(statuses.values()) == ["delivered", "pending"]
    assert len(in_flight) == 1
    assert await outbox.dispatch_webhook_deliveries(world.client, in_flight, resolve=loopback, limit=1) == 0
    await asyncio.gather(*in_flight)
    assert sorted(row["status"] for row in await deliveries(world)) == ["delivered", "delivered"]


async def test_logs_carry_only_the_event_and_the_error_type(setup, caplog):
    world, produce = setup
    await produce("/bc")
    caplog.set_level(logging.DEBUG, logger="app")
    world.receiver.responses["/bc"] = (200, 2.0, {})
    await deliver(world, timeout=0.2)
    await make_available(world)
    await deliver(world, resolve=partial(resolve_target, resolver=private_dns))
    text = caplog.text
    assert "TimeoutError" in text and "TargetRejected" in text
    for secret_part in (HOST, "token=abc", "/bc", SECRET, "10.0.0.7", "127.0.0.1"):
        assert secret_part not in text


def test_the_production_client_neither_follows_redirects_nor_uses_proxies():
    http = delivery_module.build_client()
    assert http.follow_redirects is False
    assert http.trust_env is False


def test_rectifications_do_not_record_notifications_nor_deliveries():
    source = "\n".join(path.read_text() for path in (Path(__file__).parents[1] / "app/modules/rectifications").rglob("*.py"))
    assert "SELECT record_notification(" not in source
    assert "notifications.recorder" not in source
