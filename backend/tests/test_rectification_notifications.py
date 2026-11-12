import json
import smtplib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import main
from app.core import email
from app.core.database import set_rls_context
from app.modules.rectifications import notifications
from app.workers import outbox
from test_migration_031 import ORG, USER
from test_outbox_worker import FakeRedis
from test_rectification_flow import add_approver, create, database_snapshot, decide, proposal
from test_rectification_flow import flow as flow
from test_rectification_platform import authorized, decision, platform_flow as platform_flow


@pytest.mark.parametrize("actor", ["member", "platform"])
@pytest.mark.parametrize("verdict", ["approve", "reject"])
async def test_decision_records_private_outbox_and_requester_email(platform_flow, actor, verdict):
    f = platform_flow
    if actor == "platform":
        request, _ = await authorized(f)
    else:
        request = (await create(f)).json()
        f.context = await add_approver(f)
    before = await database_snapshot(f.admin)
    preview_ids = set()
    if actor == "member" and verdict == "approve":
        preview = await f.client.get(f"/api/v1/rectifications/{request['id']}/preview")
        assert preview.status_code == 200
        assert len([e for e in preview.json()["effects"] if e["effect_type"] == "outbox"]) == 3
        preview_ids = {e["entity_id"] for e in preview.json()["effects"] if e["effect_type"] == "outbox"}
        assert await database_snapshot(f.admin) == before
    response = await (decision(f, request["id"], decision=verdict) if actor == "platform"
        else decide(f, request["id"], decision=verdict))
    assert response.status_code == 200, response.text
    events = await f.admin.fetch("SELECT * FROM outbox_events ORDER BY event_type")
    expected = ["RECTIFICATION_DECISION_EMAIL"]
    if verdict == "approve":
        expected = ["MATCH_REPORT_RECTIFIED", "MATCH_UPDATED", *expected, "STANDINGS_UPDATED"]
    assert [row["event_type"] for row in events] == expected
    assert all(str(row["organization_id"]) == ORG for row in events)
    assert preview_ids.isdisjoint(str(row["id"]) for row in events)
    rows = await f.admin.fetch("SELECT * FROM match_report_rectification_notifications")
    assert {row["outbox_event_id"] for row in rows} == {row["id"] for row in events}
    assert all(str(row["request_id"]) == request["id"] for row in rows)
    mail = next(row for row in events if row["event_type"] == "RECTIFICATION_DECISION_EMAIL")
    payload = json.loads(mail["payload"])
    assert payload["decision"] == verdict and payload["reason"] == ("Verificado" if actor == "platform" else "Revisado con el vídeo")
    assert payload["recipient"] == await f.admin.fetchval("SELECT email FROM users WHERE id=$1", USER)
    assert "evidence" not in payload and "proposed_report" not in payload
    notification = next(row for row in rows if row["channel"] == "email")
    assert notification["recipient_user_id"] == UUID(USER)
    assert all(json.loads(row["payload"])["scope"] == "organization" for row in events if row != mail)
    assert await f.admin.fetchval("SELECT count(*) FROM match_report_rectification_effects WHERE effect_type='outbox'") == (3 if verdict == "approve" else 0)
    async with f.engine.connect() as conn:
        await conn.execute(text("SET ROLE bracket_app"))
        await conn.commit()
        async with AsyncSession(bind=conn) as session, session.begin():
            await set_rls_context(session, UUID(ORG.replace("31000000", "32000000")), UUID(USER.replace("31000000", "32000000")))
            assert (await session.execute(text("SELECT count(*) FROM match_report_rectification_notifications"))).scalar_one() == 0
            assert (await session.execute(text("SELECT count(*) FROM outbox_events"))).scalar_one() == 0


@pytest.mark.parametrize("event_type", ["MATCH_UPDATED", "STANDINGS_UPDATED", "MATCH_REPORT_RECTIFIED"])
async def test_rectification_realtime_never_reaches_public_rooms(monkeypatch, event_type):
    calls = []
    async def emit(*args, **kwargs):
        calls.append(kwargs["room"])
    monkeypatch.setattr(main.sio, "emit", emit)
    await main.emit_domain_event(main.ParsedEvent("event", ORG, event_type,
        {"match_id": "match", "tournament_id": "tournament", "scope": "organization"}))
    assert calls == [f"organization:{ORG}"]


@pytest.mark.parametrize("failure", ["smtp", "unconfigured"])
async def test_worker_email_retries_and_never_publishes_to_redis(flow, monkeypatch, failure):
    body = proposal()
    body["evidence"] = "SECRET EVIDENCE NOT FOR EMAIL"
    request = (await create(flow, body)).json()
    flow.context = await add_approver(flow)
    assert (await decide(flow, request["id"], decision="reject")).status_code == 200
    @asynccontextmanager
    async def factory():
        async with flow.engine.connect() as conn:
            await conn.execute(text("SET ROLE bracket_app"))
            await conn.commit()
            async with AsyncSession(bind=conn) as session:
                yield session
    monkeypatch.setattr(outbox, "SessionFactory", factory)
    settings = SimpleNamespace(smtp_host=None if failure == "unconfigured" else "smtp.test", smtp_from="sender@example.test",
        smtp_port=25, smtp_use_tls=False, smtp_username=None, smtp_password=None, smtp_timeout_seconds=5)
    monkeypatch.setattr(email, "get_settings", lambda: settings)
    def fail(*args):
        raise smtplib.SMTPException("smtp unavailable")
    monkeypatch.setattr(email, "_send_message", fail)
    redis = FakeRedis()
    assert await outbox.process_once(redis) == 1
    row = await flow.admin.fetchrow("SELECT * FROM outbox_events")
    assert row["status"] == "pending" and row["attempts"] == 1
    assert row["last_error"] and row["available_at"] > row["created_at"]
    assert redis.calls == []
    settings.smtp_host = "smtp.test"
    sent = []
    monkeypatch.setattr(email, "_send_message", lambda message, *args: sent.append(message))
    await flow.admin.execute("UPDATE outbox_events SET available_at=now()")
    assert await outbox.process_once(redis) == 1
    assert await flow.admin.fetchval("SELECT status FROM outbox_events") == "processed"
    assert len(sent) == 1 and "rechazada" in sent[0].get_content()
    assert "Revisado con el vídeo" in sent[0].get_content()
    assert body["evidence"] not in sent[0].as_string() and redis.calls == []
    assert await outbox.process_once(redis) == 0
    assert len(sent) == 1 and redis.calls == []


async def test_notification_failure_rolls_back_the_whole_publication(flow, monkeypatch):
    request = (await create(flow)).json()
    flow.context = await add_approver(flow)
    before = await database_snapshot(flow.admin)
    original = notifications.record_notification
    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise ValueError("injected notification failure")
    monkeypatch.setattr(notifications, "record_notification", fail)
    assert (await decide(flow, request["id"])).status_code == 409
    assert await database_snapshot(flow.admin) == before


@pytest.mark.parametrize("verdict,word", [("approve", "aprobada"), ("reject", "rechazada")])
async def test_email_renderer_uses_existing_smtp_sender(monkeypatch, verdict, word):
    settings = SimpleNamespace(smtp_host="smtp.test", smtp_from="sender@example.test", smtp_port=25,
        smtp_use_tls=True, smtp_username="sender", smtp_password="test-password", smtp_timeout_seconds=3)
    monkeypatch.setattr(email, "get_settings", lambda: settings)
    sent = []
    monkeypatch.setattr(email, "_send_message", lambda *args: sent.append(args))
    await email.send_rectification_decision_email("requester@example.test", "request-id", verdict, "Motivo de decisión")
    assert len(sent) == 1
    message, *connection = sent[0]
    assert message["To"] == "requester@example.test" and message["From"] == settings.smtp_from
    assert word in message.get_content() and "Motivo de decisión" in message.get_content()
    assert connection == [settings.smtp_host, 25, True, "sender", "test-password", 3]
