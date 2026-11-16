"""Endpoints y worker de la recuperación y el cambio de contraseña (spec 039, T3–T5).

Opt-in con ``RUN_DATABASE_TESTS=1``: cada prueba corre en la transacción del
``db_session`` que se revierte al final, con la API real sobre
``httpx.ASGITransport`` y el worker con SMTP simulado.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import text

from app.core import rate_limit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_user_session, hash_password, verify_password
from app.main import api
from app.modules.identity import password_router
from app.modules.identity.password_recovery import token_hash
from app.workers import account_email
from tests.migration_helpers import connect

OLD_PASSWORD = "contraseña-antigua"
NEW_PASSWORD = "contraseña-nueva-1"
OLD_HASH = hash_password(OLD_PASSWORD)


class SavepointAdapter:
    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


class SessionFactory:
    def __init__(self, session) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return SavepointAdapter(self._session)

    async def __aexit__(self, *_exc_info):
        return False


@pytest.fixture
async def client(db_session, monkeypatch):
    async def _db():
        yield SavepointAdapter(db_session)

    async def no_rate_limit(*_args, **_kwargs):
        return None

    api.dependency_overrides[get_db] = _db
    monkeypatch.setattr(password_router, "enforce_rate_limit", no_rate_limit)
    try:
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as http:
            csrf = await http.get("/api/v1/auth/csrf")
            http.headers["X-CSRF-Token"] = csrf.headers["X-CSRF-Token"]
            yield http
    finally:
        api.dependency_overrides.clear()


@pytest.fixture
def sent(monkeypatch):
    messages: list[tuple[str, ...]] = []

    async def reset(recipient, url, _expires_at):
        messages.append(("reset", recipient, url))

    async def reminder(recipient):
        messages.append(("google", recipient))

    async def changed(recipient, _changed_at):
        messages.append(("changed", recipient))

    monkeypatch.setattr(account_email, "send_password_reset_email", reset)
    monkeypatch.setattr(account_email, "send_google_sign_in_reminder_email", reminder)
    monkeypatch.setattr(account_email, "send_password_changed_email", changed)
    return messages


async def create_user(db, *, password_hash: str | None = OLD_HASH) -> tuple[UUID, str]:
    email = f"pw-{uuid4().hex[:10]}@example.com"
    user_id = (await db.execute(
        text("""
            INSERT INTO users (email, password_hash, full_name)
            VALUES (:email, :hash, 'Password User') RETURNING id
        """),
        {"email": email, "hash": password_hash},
    )).scalar_one()
    return user_id, email


@pytest.fixture
async def inactive_email(database_admin_url):
    """A committed deactivated account: ``bracket_app`` cannot write ``is_active``."""

    email = f"pw-off-{uuid4().hex[:10]}@example.com"
    admin = await connect(database_admin_url)
    try:
        await admin.execute(
            "INSERT INTO users (email, password_hash, full_name, is_active) VALUES ($1, $2, 'Off', FALSE)",
            email, OLD_HASH,
        )
        yield email
    finally:
        await admin.execute("DELETE FROM users WHERE email = $1", email)
        await admin.close()


async def run_worker(db_session) -> int:
    return await account_email.process_account_email_jobs(SessionFactory(db_session))


async def request_reset_token(client, db_session, sent, email: str) -> str:
    assert (await client.post("/api/v1/auth/password/forgot", json={"email": email})).status_code == 202
    await run_worker(db_session)
    return sent[-1][2].split("#", 1)[1]


async def active_sessions(db, user_id: UUID) -> int:
    return (await db.execute(
        text("SELECT count(*) FROM user_sessions WHERE user_id = :id AND revoked_at IS NULL"), {"id": user_id},
    )).scalar_one()


async def stored_hash(db, user_id: UUID) -> str:
    return (await db.execute(text("SELECT password_hash FROM users WHERE id = :id"), {"id": user_id})).scalar_one()


# --- forgot -----------------------------------------------------------------


async def test_forgot_answers_the_same_for_every_kind_of_email(client, db_session, sent, caplog, inactive_email):
    _, local = await create_user(db_session)
    _, google = await create_user(db_session, password_hash=None)
    inactive = inactive_email
    missing = f"missing-{uuid4().hex[:8]}@example.com"

    responses = [
        await client.post("/api/v1/auth/password/forgot", json={"email": email})
        for email in (f"  {local.upper()}", google, inactive, missing)
    ]
    assert {(r.status_code, r.text, r.headers.get("set-cookie")) for r in responses} == {(202, "{}", None)}
    assert sent == []

    caplog.set_level(logging.DEBUG)
    assert await run_worker(db_session) == 4
    kinds = sorted((message[0], message[1]) for message in sent)
    assert kinds == sorted([("reset", local), ("google", google)])
    reset_url = next(message[2] for message in sent if message[0] == "reset")
    assert reset_url.startswith(get_settings().frontend_base_url.rstrip("/") + "/password/reset#")
    for secret in (local, google, inactive, missing, reset_url.split("#", 1)[1]):
        assert secret not in caplog.text


async def test_forgot_new_link_invalidates_the_previous_one(client, db_session, sent):
    _, email = await create_user(db_session)
    first = await request_reset_token(client, db_session, sent, email)
    second = await request_reset_token(client, db_session, sent, email)
    targets = [
        (await db_session.execute(text("SELECT count(*) FROM password_reset_target(:h)"), {"h": token_hash(t)})).scalar_one()
        for t in (first, second)
    ]
    assert targets == [0, 1]


async def test_forgot_rejects_malformed_email_without_echoing_it(client):
    response = await client.post("/api/v1/auth/password/forgot", json={"email": "not-an-email-xyz"})
    assert response.status_code == 422 and "not-an-email-xyz" not in response.text


@pytest.mark.parametrize("endpoint", ["forgot", "reset"])
async def test_forgot_and_reset_rate_limit_429_and_503(endpoint, monkeypatch):
    class Redis:
        def __init__(self, outcome):
            self.outcome = outcome

        async def eval(self, *_args):
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

    body = {"email": "a@example.com"} if endpoint == "forgot" else {"token": "t" * 43, "new_password": NEW_PASSWORD}
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as http:
        csrf = (await http.get("/api/v1/auth/csrf")).headers["X-CSRF-Token"]
        monkeypatch.setattr(rate_limit, "get_redis_client", lambda: Redis(1))
        limited = await http.post(f"/api/v1/auth/password/{endpoint}", json=body, headers={"X-CSRF-Token": csrf})
        monkeypatch.setattr(rate_limit, "get_redis_client", lambda: Redis(RedisError("down")))
        unavailable = await http.post(f"/api/v1/auth/password/{endpoint}", json=body, headers={"X-CSRF-Token": csrf})
    assert limited.status_code == 429 and limited.headers["Retry-After"]
    assert unavailable.status_code == 503


# --- reset ------------------------------------------------------------------


async def test_reset_changes_the_password_once_and_revokes_every_session(client, db_session, sent):
    user_id, email = await create_user(db_session)
    await create_user_session(db_session, user_id)
    await create_user_session(db_session, user_id)
    token = await request_reset_token(client, db_session, sent, email)

    response = await client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD})
    assert response.status_code == 204
    assert verify_password(NEW_PASSWORD, await stored_hash(db_session, user_id))
    assert await active_sessions(db_session, user_id) == 0

    again = await client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": "otra-distinta-2"})
    assert again.status_code == 400 and again.json() == {"detail": "PASSWORD_RESET_INVALID"}

    await run_worker(db_session)
    assert sent[-1] == ("changed", email)


async def test_reset_rejects_unknown_used_and_superseded_links_alike(client, db_session, sent):
    user_id, email = await create_user(db_session)
    superseded = await request_reset_token(client, db_session, sent, email)
    await request_reset_token(client, db_session, sent, email)
    unknown = await client.post("/api/v1/auth/password/reset", json={"token": "x" * 43, "new_password": NEW_PASSWORD})
    replaced = await client.post("/api/v1/auth/password/reset", json={"token": superseded, "new_password": NEW_PASSWORD})
    assert {(r.status_code, r.text) for r in (unknown, replaced)} == {(400, '{"detail":"PASSWORD_RESET_INVALID"}')}
    assert await stored_hash(db_session, user_id) == OLD_HASH


async def test_reset_rejects_the_current_password(client, db_session, sent):
    user_id, email = await create_user(db_session)
    token = await request_reset_token(client, db_session, sent, email)
    response = await client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": OLD_PASSWORD})
    assert response.status_code == 400 and response.json() == {"detail": "PASSWORD_REUSED"}
    assert (await db_session.execute(text("SELECT count(*) FROM password_reset_target(:h)"), {"h": token_hash(token)})).scalar_one() == 1


async def test_reset_acts_on_the_link_account_not_the_open_session(client, db_session, sent):
    other_id, _ = await create_user(db_session)
    user_id, email = await create_user(db_session)
    token = await request_reset_token(client, db_session, sent, email)
    other_session = await create_user_session(db_session, other_id)
    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "new_password": NEW_PASSWORD},
        headers={"Authorization": f"Bearer {other_session}"},
    )
    assert response.status_code == 204
    assert verify_password(NEW_PASSWORD, await stored_hash(db_session, user_id))
    assert await stored_hash(db_session, other_id) == OLD_HASH
    assert await active_sessions(db_session, other_id) == 1


# --- change -----------------------------------------------------------------


async def authenticate(client, db_session, user_id: UUID) -> None:
    client.headers["Authorization"] = f"Bearer {await create_user_session(db_session, user_id)}"


async def test_change_status_and_password_keep_only_the_current_session(client, db_session, sent):
    user_id, email = await create_user(db_session)
    await create_user_session(db_session, user_id)
    pending = await request_reset_token(client, db_session, sent, email)
    await authenticate(client, db_session, user_id)

    assert (await client.get("/api/v1/auth/password")).json() == {"has_password": True}
    response = await client.post(
        "/api/v1/auth/password/change", json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    assert verify_password(NEW_PASSWORD, await stored_hash(db_session, user_id))
    assert await active_sessions(db_session, user_id) == 1
    assert (await client.get("/api/v1/auth/password")).status_code == 200
    assert (await db_session.execute(text("SELECT count(*) FROM password_reset_target(:h)"), {"h": token_hash(pending)})).scalar_one() == 0
    await run_worker(db_session)
    assert sent[-1] == ("changed", email)


async def test_change_rejects_wrong_current_and_reused_password(client, db_session):
    user_id, _ = await create_user(db_session)
    await create_user_session(db_session, user_id)
    await authenticate(client, db_session, user_id)
    wrong = await client.post(
        "/api/v1/auth/password/change", json={"current_password": "incorrecta", "new_password": NEW_PASSWORD},
    )
    reused = await client.post(
        "/api/v1/auth/password/change", json={"current_password": OLD_PASSWORD, "new_password": OLD_PASSWORD},
    )
    assert (wrong.status_code, wrong.json()) == (400, {"detail": "CURRENT_PASSWORD_INVALID"})
    assert (reused.status_code, reused.json()) == (400, {"detail": "PASSWORD_REUSED"})
    assert await stored_hash(db_session, user_id) == OLD_HASH
    assert await active_sessions(db_session, user_id) == 2


async def test_change_google_only_account_has_no_password(client, db_session):
    user_id, _ = await create_user(db_session, password_hash=None)
    await authenticate(client, db_session, user_id)
    assert (await client.get("/api/v1/auth/password")).json() == {"has_password": False}
    response = await client.post(
        "/api/v1/auth/password/change", json={"current_password": "cualquiera", "new_password": NEW_PASSWORD},
    )
    assert (response.status_code, response.json()) == (409, {"detail": "PASSWORD_NOT_SET"})


async def test_change_requires_a_session(client):
    assert (await client.get("/api/v1/auth/password")).status_code == 401
    response = await client.post(
        "/api/v1/auth/password/change", json={"current_password": OLD_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401


async def test_change_uses_the_login_rate_limit_per_account(client, db_session, monkeypatch):
    user_id, _ = await create_user(db_session)
    await authenticate(client, db_session, user_id)
    calls = []

    async def record(_request, bucket, limit, window, **kwargs):
        calls.append((bucket, limit, window, kwargs["account_identifier"]))

    monkeypatch.setattr(password_router, "enforce_rate_limit", record)
    await client.post("/api/v1/auth/password/change", json={"current_password": "x", "new_password": NEW_PASSWORD})
    assert calls == [("password-change", get_settings().auth_login_rate_limit, 60, str(user_id))]
