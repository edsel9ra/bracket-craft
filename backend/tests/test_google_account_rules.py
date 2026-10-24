"""Matriz de decisión de cuenta del flujo de Google (RF-11, RF-12, RF-14…RF-19).

Funciones puras: reciben el estado ya leído (identidad vinculada, cuenta
desactivada, contraseña, número de coincidencias de correo, sujeto y correo de
la cuenta) y devuelven un desenlace del catálogo cerrado. No hay reloj, red ni
base de datos, y la desactivación se decide antes que el tipo de cuenta para no
filtrar el motivo (RF-16).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.modules.identity.account_rules import (
    LinkOutcome,
    LoginOutcome,
    decide_existing_account,
    decide_linked_account,
    decide_link,
)

ACCOUNT_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_ACCOUNT_ID = UUID("00000000-0000-4000-8000-000000000002")


# ---------------------------------------------------------------------------
# Catálogo cerrado
# ---------------------------------------------------------------------------


def test_login_outcome_values_are_the_documented_codes():
    assert {outcome.value for outcome in LoginOutcome} == {
        "create",
        "linked",
        "ACCOUNT_DISABLED",
        "ACCOUNT_EXISTS_PASSWORD",
        "ACCOUNT_EXISTS_GOOGLE_ONLY",
        "GOOGLE_IDENTITY_INVALID",
    }
    assert LoginOutcome.CREATE == "create"
    assert LoginOutcome.LINKED == "linked"


def test_link_outcome_values_are_the_documented_codes():
    assert {outcome.value for outcome in LinkOutcome} == {
        "link",
        "idempotent",
        "GOOGLE_ALREADY_LINKED",
        "LINK_IDENTITY_TAKEN",
        "LINK_EMAIL_MISMATCH",
    }


def test_outcomes_are_strings():
    assert isinstance(LoginOutcome.CREATE, str)
    assert isinstance(LinkOutcome.LINK, str)


# ---------------------------------------------------------------------------
# Identidad ya vinculada (RF-11)
# ---------------------------------------------------------------------------


def test_decide_linked_account_accepts_an_active_account():
    assert decide_linked_account(is_active=True) is LoginOutcome.LINKED


def test_decide_linked_account_rejects_a_disabled_account_generically():
    assert decide_linked_account(is_active=False) is LoginOutcome.DISABLED


# ---------------------------------------------------------------------------
# Correo sin identidad vinculada: 6 salidas (RF-12, RF-15, RF-16, RF-17)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("is_active", [True, False])
@pytest.mark.parametrize("has_password", [True, False])
def test_decide_existing_account_creates_when_no_account_matches(
    is_active, has_password
):
    # Sin coincidencias no hay cuenta que pueda estar desactivada.
    assert (
        decide_existing_account(is_active=is_active, has_password=has_password, matches=0)
        is LoginOutcome.CREATE
    )


@pytest.mark.parametrize("has_password", [True, False])
def test_decide_existing_account_disabled_wins_over_the_account_type(has_password):
    # RF-16: el aviso es genérico y la desactivación precede a saber si tiene
    # contraseña o es solo-Google.
    assert (
        decide_existing_account(
            is_active=False, has_password=has_password, matches=1
        )
        is LoginOutcome.DISABLED
    )


def test_decide_existing_account_reports_a_local_password_account():
    assert (
        decide_existing_account(is_active=True, has_password=True, matches=1)
        is LoginOutcome.PASSWORD_ACCOUNT
    )


def test_decide_existing_account_reports_a_google_only_account():
    assert (
        decide_existing_account(is_active=True, has_password=False, matches=1)
        is LoginOutcome.GOOGLE_ONLY_ACCOUNT
    )


@pytest.mark.parametrize("is_active", [True, False])
@pytest.mark.parametrize("has_password", [True, False])
@pytest.mark.parametrize("matches", [2, 3, 10])
def test_decide_existing_account_fails_closed_on_duplicated_emails(
    is_active, has_password, matches
):
    # Caso límite 4: datos inconsistentes; no se elige cuenta ni se revela el
    # estado de ninguna.
    assert (
        decide_existing_account(
            is_active=is_active, has_password=has_password, matches=matches
        )
        is LoginOutcome.INCONSISTENT
    )
    assert LoginOutcome.INCONSISTENT.value == "GOOGLE_IDENTITY_INVALID"


def test_decide_existing_account_rejects_a_negative_match_count():
    with pytest.raises(ValueError):
        decide_existing_account(is_active=True, has_password=True, matches=-1)


# ---------------------------------------------------------------------------
# Vinculación desde una sesión iniciada: 5 salidas (RF-14, RF-18, RF-19)
# ---------------------------------------------------------------------------


def link(
    *,
    account_subject: str | None = None,
    presented_subject: str = "google-subject",
    identity_owner_id: UUID | None = None,
    account_id: UUID = ACCOUNT_ID,
    email_matches: bool = True,
) -> LinkOutcome:
    return decide_link(
        account_subject=account_subject,
        presented_subject=presented_subject,
        identity_owner_id=identity_owner_id,
        account_id=account_id,
        email_matches=email_matches,
    )


def test_decide_link_links_when_everything_matches():
    assert link() is LinkOutcome.LINK


def test_decide_link_is_idempotent_for_the_same_subject():
    assert (
        link(account_subject="google-subject", presented_subject="google-subject")
        is LinkOutcome.IDEMPOTENT
    )


def test_decide_link_idempotent_wins_over_every_other_condition():
    assert (
        link(
            account_subject="google-subject",
            presented_subject="google-subject",
            identity_owner_id=OTHER_ACCOUNT_ID,
            email_matches=False,
        )
        is LinkOutcome.IDEMPOTENT
    )


def test_decide_link_rejects_an_account_with_another_identity():
    assert (
        link(account_subject="another-google-subject")
        is LinkOutcome.GOOGLE_ALREADY_LINKED
    )


def test_decide_link_already_linked_wins_over_a_foreign_identity_and_email():
    assert (
        link(
            account_subject="another-google-subject",
            identity_owner_id=OTHER_ACCOUNT_ID,
            email_matches=False,
        )
        is LinkOutcome.GOOGLE_ALREADY_LINKED
    )


def test_decide_link_rejects_an_identity_owned_by_another_account():
    assert (
        link(identity_owner_id=OTHER_ACCOUNT_ID)
        is LinkOutcome.LINK_IDENTITY_TAKEN
    )


def test_decide_link_identity_taken_wins_over_the_email_mismatch():
    assert (
        link(identity_owner_id=OTHER_ACCOUNT_ID, email_matches=False)
        is LinkOutcome.LINK_IDENTITY_TAKEN
    )


def test_decide_link_rejects_a_different_email():
    assert link(email_matches=False) is LinkOutcome.LINK_EMAIL_MISMATCH


def test_decide_link_accepts_the_identity_owned_by_the_same_account():
    # ``identity_owner_id == account_id`` sin sujeto en la cuenta es un estado
    # incoherente que no debe alcanzar el INSERT; el plan solo marca como ajena
    # la identidad de otra cuenta, así que el correo sigue decidiendo.
    assert (
        link(identity_owner_id=ACCOUNT_ID, email_matches=True) is LinkOutcome.LINK
    )
    assert (
        link(identity_owner_id=ACCOUNT_ID, email_matches=False)
        is LinkOutcome.LINK_EMAIL_MISMATCH
    )
