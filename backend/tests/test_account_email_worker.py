"""Worker de correos de cuenta de la spec 039 (T3).

Opt-in con ``RUN_DATABASE_TESTS=1``; reutiliza la API, el SMTP simulado y la
fábrica de sesiones de ``test_password_recovery_endpoints``.
"""

from __future__ import annotations

import logging
import smtplib

from sqlalchemy import text

from app.modules.identity.password_recovery import token_hash
from app.workers import account_email
from tests import test_password_recovery_endpoints as shared

client = shared.client
sent = shared.sent
create_user = shared.create_user
run_worker = shared.run_worker


async def pending_targets(db, token: str) -> int:
    return (await db.execute(
        text("SELECT count(*) FROM password_reset_target(:h)"), {"h": token_hash(token)},
    )).scalar_one()


async def test_forgot_worker_smtp_failure_invalidates_the_link_and_hides_the_email(
    client, db_session, monkeypatch, caplog,
):
    _, email = await create_user(db_session)
    urls: list[str] = []

    async def failing(recipient, url, _expires_at):
        urls.append(url)
        raise smtplib.SMTPRecipientsRefused({recipient: (550, b"rejected")})

    monkeypatch.setattr(account_email, "send_password_reset_email", failing)
    caplog.set_level(logging.DEBUG)
    await client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert await run_worker(db_session) == 1
    token = urls[0].split("#", 1)[1]
    assert await pending_targets(db_session, token) == 0
    assert await run_worker(db_session) == 0, "el reintento espera su turno"
    assert "SMTPRecipientsRefused" in caplog.text
    assert email not in caplog.text and token not in caplog.text and urls[0] not in caplog.text


async def test_forgot_worker_discards_requests_older_than_the_link_lifetime(client, db_session, sent, monkeypatch):
    _, email = await create_user(db_session)
    monkeypatch.setattr(account_email, "job_should_expire", lambda _created_at, _now: True)
    await client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert await run_worker(db_session) == 1
    assert sent == []
    assert await run_worker(db_session) == 0, "el trabajo caducado queda procesado, sin reintento"


async def test_forgot_worker_emits_a_distinct_token_per_request(client, db_session, sent):
    _, email = await create_user(db_session)
    for _ in range(2):
        await client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert await run_worker(db_session) == 2
    tokens = [message[2].split("#", 1)[1] for message in sent]
    assert len(set(tokens)) == 2 and all(len(token) >= 43 for token in tokens)
    assert [await pending_targets(db_session, token) for token in tokens] == [0, 1]
