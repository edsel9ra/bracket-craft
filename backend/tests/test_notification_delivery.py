"""Entrega de avisos en el worker (spec 046, T4: RF-007, RF-011, RF-012, RNF-002).

Opt-in con ``RUN_DATABASE_TESTS=1``: el aviso nace de un cierre real con el rol
de la aplicación y el worker lo entrega con sesiones de ese mismo rol.
"""

from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email as email_module
from app.workers import outbox
from migration_helpers import connect
from test_match_assists_db import close, committed_application, report_of, seeded_match
from test_outbox_worker import FakeRedis

PLAYER_NAMES = "SELECT string_agg(first_name || '|' || last_name, '|') FROM players"


@dataclass
class World:
    admin: object
    engine: object
    organization_id: object
    user_id: object
    match_id: object


@pytest.fixture
async def world(database_admin_url, monkeypatch):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        admin = await connect(database_admin_url, engine.url.database)
        try:
            await admin.execute(
                """INSERT INTO notification_preferences (organization_id, user_id, notification_type, channel, enabled)
                VALUES ($1, $2, 'result_confirmed', 'email', TRUE)""",
                context.organization_id,
                context.user_id,
            )
            await close(
                engine, context, match.match_id, report_of(home_score_regular=0)
            )

            @asynccontextmanager
            async def factory():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    yield session

            monkeypatch.setattr(outbox, "SessionFactory", factory)
            yield World(
                admin, engine, context.organization_id, context.user_id, match.match_id
            )
        finally:
            await admin.close()


async def outcome(world, channel):
    return await world.admin.fetchval(
        "SELECT outcome FROM notification_recipients WHERE channel = $1", channel
    )


async def event(world, event_type):
    return await world.admin.fetchrow(
        "SELECT status, attempts, last_error FROM outbox_events WHERE event_type = $1",
        event_type,
    )


async def make_available(world):
    await world.admin.execute(
        "UPDATE outbox_events SET available_at = CURRENT_TIMESTAMP WHERE status = 'pending'"
    )


def smtp_recorder(monkeypatch, *, error=None):
    calls = []

    async def send(recipient, subject, body):
        calls.append({"recipient": recipient, "subject": subject, "body": body})
        if error is not None:
            raise error

    monkeypatch.setattr(outbox, "send_notification_email", send)
    return calls


async def test_the_outbox_loop_delivers_the_inbox_without_redis_nor_email(
    world, monkeypatch
):
    calls = smtp_recorder(monkeypatch)
    redis = FakeRedis()
    await outbox.process_once(redis)
    assert await outcome(world, "inbox") == "delivered"
    assert (await event(world, "NOTIFICATION_INBOX"))["status"] == "processed"
    assert "NOTIFICATION" not in str(redis.calls)
    assert calls == []
    assert (await event(world, "NOTIFICATION_EMAIL"))["status"] == "pending"
    assert await outcome(world, "email") == "pending"


@pytest.mark.parametrize("change", ["membership", "channel"])
async def test_the_inbox_is_withheld_without_retry_after_losing_the_right(
    world, change
):
    if change == "membership":
        await world.admin.execute(
            "UPDATE organization_users SET is_active = FALSE WHERE user_id = $1",
            world.user_id,
        )
    else:
        await world.admin.execute(
            """INSERT INTO notification_preferences (organization_id, user_id, notification_type, channel, enabled)
            VALUES ($1, $2, 'result_confirmed', 'inbox', FALSE)""",
            world.organization_id,
            world.user_id,
        )
    await outbox.process_once(FakeRedis())
    assert await outcome(world, "inbox") == "withheld"
    assert (await event(world, "NOTIFICATION_INBOX"))["status"] == "processed"


async def test_the_email_loop_sends_once_without_player_names(world, monkeypatch):
    calls = smtp_recorder(monkeypatch)
    assert await outbox.process_notification_emails() == 1
    email = await world.admin.fetchval(
        "SELECT email FROM users WHERE id = $1", world.user_id
    )
    assert [call["recipient"] for call in calls] == [email]
    assert "/workspace/notifications" in calls[0]["body"]
    for name in (await world.admin.fetchval(PLAYER_NAMES) or "").split("|"):
        assert not name or name not in calls[0]["subject"] + calls[0]["body"]
    assert await outcome(world, "email") == "delivered"
    assert (await event(world, "NOTIFICATION_EMAIL"))["status"] == "processed"
    # Un evento reclamado de nuevo tras enviar (p. ej. al perder la confirmación)
    # no duplica el correo.
    await world.admin.execute(
        "UPDATE outbox_events SET status = 'pending' WHERE event_type = 'NOTIFICATION_EMAIL'"
    )
    assert await outbox.process_notification_emails() == 1
    assert len(calls) == 1
    assert (await event(world, "NOTIFICATION_EMAIL"))["status"] == "processed"


async def test_an_smtp_failure_is_retried_without_duplicating(
    world, monkeypatch, caplog
):
    email = await world.admin.fetchval(
        "SELECT email FROM users WHERE id = $1", world.user_id
    )
    calls = smtp_recorder(monkeypatch, error=RuntimeError(f"rejected {email}"))
    await outbox.process_notification_emails()
    row = await event(world, "NOTIFICATION_EMAIL")
    assert (row["status"], row["attempts"], row["last_error"]) == (
        "pending",
        1,
        "RuntimeError",
    )
    assert await outcome(world, "email") == "pending"
    assert email not in caplog.text
    assert await outbox.process_notification_emails() == 0, (
        "el reintento espera su turno"
    )
    calls = smtp_recorder(monkeypatch)
    await make_available(world)
    assert await outbox.process_notification_emails() == 1
    assert len(calls) == 1
    assert await outcome(world, "email") == "delivered"
    assert await world.admin.fetchval("SELECT count(*) FROM notifications") == 1


async def test_without_smtp_the_email_stays_failed_and_retriable(world, monkeypatch):
    monkeypatch.setattr(
        email_module, "get_settings", lambda: SimpleNamespace(smtp_host=None)
    )
    await outbox.process_notification_emails()
    row = await event(world, "NOTIFICATION_EMAIL")
    assert (row["status"], row["last_error"]) == ("pending", "RuntimeError")
    assert await outcome(world, "email") == "pending"


@pytest.mark.parametrize("change", ["membership", "channel"])
async def test_the_email_is_withheld_without_retry_after_losing_the_right(
    world, monkeypatch, change
):
    calls = smtp_recorder(monkeypatch)
    if change == "membership":
        await world.admin.execute(
            "UPDATE organization_users SET is_active = FALSE WHERE user_id = $1",
            world.user_id,
        )
    else:
        await world.admin.execute(
            "UPDATE notification_preferences SET enabled = FALSE WHERE channel = 'email'"
        )
    await outbox.process_notification_emails()
    assert calls == []
    assert await outcome(world, "email") == "withheld"
    assert (await event(world, "NOTIFICATION_EMAIL"))["status"] == "processed"


async def test_a_blocked_smtp_does_not_stop_the_outbox_loop(world, monkeypatch):
    release = asyncio.Event()

    async def blocked(recipient, subject, body):
        await release.wait()

    monkeypatch.setattr(outbox, "send_notification_email", blocked)
    emails = asyncio.create_task(outbox.process_notification_emails())
    try:
        await asyncio.sleep(0.2)
        await asyncio.wait_for(outbox.process_once(FakeRedis()), timeout=10)
        assert await outcome(world, "inbox") == "delivered"
        assert await outcome(world, "email") == "pending"
    finally:
        release.set()
        await asyncio.wait_for(emails, timeout=10)
    assert await outcome(world, "email") == "delivered"


async def test_main_runs_the_email_loop_beside_the_others(monkeypatch):
    started = []

    def loop(name):
        async def run(*_args):
            started.append(name)

        return run

    monkeypatch.setattr(outbox, "_run_loop", loop("outbox"))
    monkeypatch.setattr(outbox, "_run_account_email_loop", loop("account"))
    monkeypatch.setattr(
        outbox, "_run_notification_email_loop", loop("notifications"), raising=False
    )
    monkeypatch.setattr(outbox, "_run_webhook_loop", loop("webhooks"), raising=False)
    monkeypatch.setattr(outbox, "validate_application_role", loop("role"))
    await outbox.main()
    assert {"outbox", "account", "notifications"} <= set(started)
    assert inspect.iscoroutinefunction(outbox.process_notification_emails)
