import json
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

from app.modules.sanction_appeals.schemas import DecisionRequest, WithdrawalRequest
from test_sanction_cases import appeal, permissions, second_member
from test_sanction_cases import cases as cases
from test_sanction_readers import readers as readers
from test_outbox_worker import FakeRedis


async def notice_act(f, act="decision"):
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f, evidence_text="EVIDENCE_PRIVATE"))
    reviewer = await second_member(f, "RESOLVE_SANCTION_CASES")
    await second_member(f, "VIEW_SANCTION_CASES")
    async with f.service() as service:
        if act == "decision":
            await service.decide(reviewer, case["id"], DecisionRequest(decision="maintain", expected_base_duration=3,
                reason="ACT_REASON", evidence_text="EVIDENCE_PRIVATE"))
        else:
            await service.withdraw(f.context, case["id"], WithdrawalRequest(reason="ACT_REASON"))
    return case, reviewer


@pytest.mark.parametrize("act", ["decision", "withdrawn"])
async def test_enqueue_private_minimum_deduplicated_recipient_channels(cases, act):
    f = cases
    case, reviewer = await notice_act(f, act)
    notices = await f.admin.fetch("SELECT * FROM sanction_notifications")
    assert len(notices) == 4
    assert {row["recipient_user_id"] for row in notices} == {f.context.user_id, reviewer.user_id}
    assert {row["channel"] for row in notices} == {"internal", "email"}
    assert all(row["reason"] == "ACT_REASON" and row["case_id"] == case["id"] for row in notices)
    events = await f.admin.fetch("SELECT * FROM outbox_events")
    assert len(events) == 4
    assert {row["event_type"] for row in events} == {"SANCTION_CASE_NOTICE_EMAIL", "SANCTION_CASE_NOTICE_INTERNAL"}
    for row in events:
        payload = json.loads(row["payload"])
        assert set(payload) == {"notification_id"}
        assert "EVIDENCE_PRIVATE" not in row["payload"]


async def test_internal_revalidates_withholds_recovers_and_is_idempotent(cases):
    from app.modules.sanction_appeals.notifications import SanctionNotificationService, deliver_internal

    f = cases
    _, reviewer = await notice_act(f)
    async with f.service() as base:
        async with base.db.begin():
            events = (await base.db.execute(text("SELECT * FROM claim_outbox_events(20)"))).mappings().all()
    event_id = await f.admin.fetchval("""SELECT outbox_event_id FROM sanction_notifications
        WHERE recipient_user_id=$1 AND channel='internal'""", f.context.user_id)
    event = next(row for row in events if row["id"] == event_id)
    await permissions(f)
    async with f.service() as base:
        with pytest.raises(PermissionError):
            await deliver_internal(base.db, event)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_notification_deliveries WHERE outcome='withheld'") == 1
    async with f.service() as base:
        assert (await SanctionNotificationService(base.db).list(f.context))["items"] == []
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    async with f.service() as base:
        await deliver_internal(base.db, event)
        await deliver_internal(base.db, event)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_notification_deliveries WHERE outcome='delivered'") == 1
    async with f.service() as base:
        items = (await SanctionNotificationService(base.db).list(f.context))["items"]
    assert len(items) == 1 and items[0]["reason"] == "ACT_REASON"
    assert items[0]["decision"] == "maintain"
    assert "EVIDENCE_PRIVATE" not in str(items)
    async with f.service() as base:
        assert (await SanctionNotificationService(base.db).list(reviewer))["items"] == []


@pytest.mark.parametrize("mode", ["normal", "smtp_fails", "revoked"])
async def test_worker_email_is_private_revalidated_and_retriable(cases, monkeypatch, mode):
    from app.workers import outbox

    f = cases
    await notice_act(f)
    calls = []
    if mode == "revoked":
        await permissions(f)

    @asynccontextmanager
    async def factory():
        async with f.service() as base:
            yield base.db

    async def smtp(**payload):
        calls.append(payload)
        if mode == "smtp_fails":
            raise RuntimeError("SMTP_UNAVAILABLE")

    monkeypatch.setattr(outbox, "SessionFactory", factory)
    monkeypatch.setattr(outbox, "send_sanction_notice_email", smtp, raising=False)
    redis = FakeRedis()
    await outbox.process_once(redis)
    assert redis.calls == []
    assert len(calls) == (0 if mode == "revoked" else 2)
    assert "EVIDENCE_PRIVATE" not in str(calls)
    assert all(call["reason"] == "ACT_REASON" for call in calls)
    delivered = {"normal": 4, "smtp_fails": 2, "revoked": 0}[mode]
    assert await f.admin.fetchval("SELECT count(*) FROM outbox_events WHERE status='processed'") == delivered
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_notification_deliveries WHERE outcome='delivered'") == delivered
    if mode == "revoked":
        assert await f.admin.fetchval("SELECT count(*) FROM sanction_notification_deliveries WHERE outcome='withheld'") == 4
        await permissions(f, "SUBMIT_SANCTION_APPEALS", "RESOLVE_SANCTION_CASES")
        await f.admin.execute("UPDATE outbox_events SET available_at=CURRENT_TIMESTAMP WHERE status='pending'")
        await outbox.process_once(redis)
        assert len(calls) == 2
        assert await f.admin.fetchval("SELECT count(*) FROM outbox_events WHERE status='processed'") == 4
        assert await f.admin.fetchval("SELECT count(*) FROM sanction_notifications") == 4
        assert redis.calls == []
