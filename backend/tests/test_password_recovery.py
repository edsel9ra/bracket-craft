"""Funciones puras, esquemas y correos de la recuperación de contraseña (spec 039, T2)."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
from pydantic import ValidationError

from app.core import email as email_module
from app.modules.identity import password_recovery as recovery
from app.modules.identity.schemas import ChangePasswordRequest, ForgotPasswordRequest, ResetPasswordRequest

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def test_token_has_256_bits_and_is_stored_as_sha256_hex():
    token = recovery.new_reset_token()
    assert len(token) >= 43 and token != recovery.new_reset_token()
    digest = recovery.token_hash(token)
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    assert recovery.token_hash(token) == digest


def test_link_expires_after_30_minutes():
    assert recovery.reset_expires_at(NOW) == NOW + timedelta(minutes=30)


def test_reset_url_keeps_the_token_in_the_fragment():
    url = recovery.reset_url("https://app.example/", "abc-_123")
    assert url == "https://app.example/password/reset#abc-_123"
    assert "?" not in url


@pytest.mark.parametrize(
    ("age", "expired"),
    [(timedelta(minutes=29), False), (timedelta(minutes=30), True), (timedelta(hours=2), True)],
)
def test_request_jobs_older_than_the_link_lifetime_are_discarded(age, expired):
    assert recovery.job_should_expire(NOW - age, NOW) is expired


@pytest.mark.parametrize("model", [ResetPasswordRequest, ChangePasswordRequest])
@pytest.mark.parametrize(("password", "valid"), [("x" * 7, False), ("x" * 8, True), ("x" * 128, True), ("x" * 129, False)])
def test_new_password_follows_the_registration_policy(model, password, valid):
    data = {"new_password": password}
    data.update({"token": "t" * 43} if model is ResetPasswordRequest else {"current_password": "old"})
    if valid:
        assert model(**data).new_password == password
    else:
        with pytest.raises(ValidationError):
            model(**data)


def test_schemas_reject_unknown_fields_and_hide_secrets_from_errors():
    with pytest.raises(ValidationError):
        ForgotPasswordRequest(email="a@example.test", extra=True)
    with pytest.raises(ValidationError) as error:
        ResetPasswordRequest(token="secret-token-value", new_password="Pw-9x")
    assert "secret-token-value" not in str(error.value) and "Pw-9x" not in str(error.value)


@pytest.fixture
def sent(monkeypatch):
    messages: list[EmailMessage] = []
    settings = email_module.get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(email_module, "_send_message", lambda message, *args: messages.append(message))
    return messages


async def test_reset_email_carries_the_link_and_expiry(sent):
    await email_module.send_password_reset_email("u@example.test", "https://app/password/reset#tok", NOW)
    body = sent[0].get_content()
    assert sent[0]["To"] == "u@example.test"
    assert "https://app/password/reset#tok" in body and "30 minutos" in body


async def test_google_reminder_and_change_notice_have_no_action_links(sent):
    await email_module.send_google_sign_in_reminder_email("g@example.test")
    await email_module.send_password_changed_email("u@example.test", NOW)
    reminder, notice = (message.get_content() for message in sent)
    assert "Google" in reminder
    assert NOW.isoformat() in notice
    for body in (reminder, notice):
        assert "http" not in body


async def test_account_emails_fail_without_smtp(monkeypatch):
    monkeypatch.setattr(email_module.get_settings(), "smtp_host", None)
    with pytest.raises(RuntimeError):
        await email_module.send_password_reset_email("u@example.test", "https://app/password/reset#tok", NOW)
