from types import SimpleNamespace

import pytest

from app.core import email


@pytest.mark.parametrize("kind,decision", [("decision","annul"),("withdrawn",None),("closed_by_rectification",None)])
async def test_sanction_email_contains_only_authorized_act_and_reason(monkeypatch, kind, decision):
    settings = SimpleNamespace(smtp_host="localhost",smtp_port=25,smtp_use_tls=False,smtp_username=None,
        smtp_password=None,smtp_timeout_seconds=10,smtp_from="sender@example.test")
    monkeypatch.setattr(email,"get_settings",lambda:settings)
    messages = []
    monkeypatch.setattr(email,"_send_message",lambda message,*args:messages.append(message))
    await email.send_sanction_notice_email("recipient@example.test","case-id",kind,decision,"Motivo autorizado")
    assert len(messages) == 1
    assert messages[0]["To"] == "recipient@example.test"
    assert "Motivo autorizado" in messages[0].get_content()
    assert "case-id" in messages[0].get_content()


async def test_missing_smtp_is_retriable_not_silent_delivery(monkeypatch):
    monkeypatch.setattr(email,"get_settings",lambda:SimpleNamespace(smtp_host=None))
    with pytest.raises(RuntimeError,match="SMTP no configurado"):
        await email.send_sanction_notice_email("recipient@example.test","case-id","withdrawn",None,"Motivo")
