"""Contrato de error y guardas puras del ciclo de vida de invitaciones (T1).

Spec 009: RF-002 (409 de la reapertura), RF-003 (409 al reenviar una revocada)
y RF-004 (forma del payload de auditoría). Nada de esto toca la base de datos:
la decisión se prueba como función pura y el cuerpo del 409 se comprueba sobre
el manejador registrado en la aplicación.
"""

from __future__ import annotations

import inspect
import json

import pytest
from fastapi import HTTPException

from app.main import _invitation_conflict_exception_handler, api
from app.modules.invitations.audit import (
    INVITATION_ENTITY_TYPE,
    REOPEN_INVITATION,
    record_invitation_audit,
    reopen_audit_payload,
)
from app.modules.invitations.errors import (
    INVITATION_ALREADY_ACCEPTED,
    INVITATION_NOT_REVOKED,
    INVITATION_OTHER_PENDING,
    INVITATION_REVOKED_RESEND,
    InvitationConflict,
    conflict_body,
)
from app.modules.invitations.lifecycle import resend_conflict, reopen_conflict


# --- RF-002: cuándo procede reabrir -----------------------------------------


def test_reopening_a_revoked_invitation_without_another_live_pending_is_allowed():
    assert reopen_conflict("revoked", False) is None


@pytest.mark.parametrize("stored_status", ["pending", "expired", "accepted"])
def test_reopening_an_invitation_that_is_not_revoked_is_rejected(stored_status):
    assert reopen_conflict(stored_status, False) == INVITATION_NOT_REVOKED
    assert reopen_conflict(stored_status, True) == INVITATION_NOT_REVOKED


def test_reopening_a_revoked_invitation_with_another_live_pending_is_rejected():
    assert reopen_conflict("revoked", True) == INVITATION_OTHER_PENDING


# --- RF-003: cuándo procede reenviar ----------------------------------------


def test_resending_an_accepted_invitation_is_rejected():
    assert resend_conflict("accepted") == INVITATION_ALREADY_ACCEPTED


def test_resending_a_revoked_invitation_is_rejected():
    assert resend_conflict("revoked") == INVITATION_REVOKED_RESEND


@pytest.mark.parametrize("stored_status", ["pending", "expired"])
def test_resending_a_pending_or_expired_invitation_is_allowed(stored_status):
    assert resend_conflict(stored_status) is None


def test_the_four_conflict_codes_are_distinct_and_stable():
    assert {
        INVITATION_NOT_REVOKED,
        INVITATION_OTHER_PENDING,
        INVITATION_ALREADY_ACCEPTED,
        INVITATION_REVOKED_RESEND,
    } == {
        "INVITATION_NOT_REVOKED",
        "INVITATION_OTHER_PENDING",
        "INVITATION_ALREADY_ACCEPTED",
        "INVITATION_REVOKED_RESEND",
    }


# --- Contrato del 409: detail (cadena) + code (aditivo) ---------------------


def test_invitation_conflict_is_a_409_http_exception_with_a_code():
    exc = InvitationConflict(INVITATION_NOT_REVOKED)
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 409
    assert exc.code == INVITATION_NOT_REVOKED
    assert isinstance(exc.detail, str) and exc.detail


def test_conflict_body_keeps_detail_as_a_string_and_adds_the_code():
    detail = "Ya existe una invitación pendiente para ese correo"
    body = conflict_body(InvitationConflict(INVITATION_OTHER_PENDING, detail))
    assert body == {"detail": detail, "code": INVITATION_OTHER_PENDING}
    assert isinstance(body["detail"], str)


def test_conflict_body_defaults_detail_to_a_non_empty_string():
    body = conflict_body(InvitationConflict(INVITATION_REVOKED_RESEND))
    assert body["code"] == INVITATION_REVOKED_RESEND
    assert isinstance(body["detail"], str) and body["detail"]


async def test_the_conflict_handler_is_registered_once_and_returns_the_additive_body():
    handler = api.exception_handlers.get(InvitationConflict)
    assert handler is _invitation_conflict_exception_handler

    response = await handler(None, InvitationConflict(INVITATION_NOT_REVOKED))
    assert response.status_code == 409
    assert json.loads(response.body) == {
        "detail": InvitationConflict(INVITATION_NOT_REVOKED).detail,
        "code": INVITATION_NOT_REVOKED,
    }


# --- RF-004: forma del payload de auditoría ---------------------------------


def test_reopen_audit_payload_only_contains_previous_status_and_role_code():
    assert reopen_audit_payload(role_code="operator") == {
        "previous_status": "revoked",
        "role_code": "operator",
    }
    assert set(reopen_audit_payload(role_code="admin", previous_status="revoked")) == {
        "previous_status",
        "role_code",
    }


def test_reopen_audit_payload_never_carries_contact_or_secret_fields():
    serialized = json.dumps(reopen_audit_payload(role_code="viewer")).lower()
    for forbidden in ("email", "token", "invite_url", "full_name", "@"):
        assert forbidden not in serialized


def test_invitation_audit_constants_are_stable():
    assert INVITATION_ENTITY_TYPE == "organization_invitations"
    assert REOPEN_INVITATION == "REOPEN_INVITATION"


def test_record_invitation_audit_inserts_without_committing_or_sending_mail():
    source = inspect.getsource(record_invitation_audit)
    assert "INSERT INTO administrative_audit_logs" in source
    assert "commit" not in source.lower()
    assert "send" not in source.lower()
