"""Matriz de decisión de cuenta del flujo de Google (RF-11, RF-12, RF-14…RF-19).

Funciones puras y totales: reciben el estado ya leído de la base y devuelven un
desenlace del catálogo cerrado. No leen reloj, entorno, red ni base de datos y
no escriben nada; la resolución real (alta, sesión, vinculación) vive en
``google_accounts``.

El orden de las comprobaciones es parte del contrato:

* La cuenta desactivada se decide antes que su tipo (RF-16): el aviso es
  genérico y no revela si tiene contraseña ni si es solo-Google.
* Un correo repetido en más de una cuenta es un estado inconsistente y falla
  cerrado sin elegir cuenta (caso límite 4, RF-13/RNF-11).
* En la vinculación, la identidad propia gana a todo; después la cuenta ya
  vinculada, la identidad de otra cuenta y, por último, el correo.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID


class LoginOutcome(StrEnum):
    """Desenlace del inicio de sesión con una identidad ya verificada."""

    CREATE = "create"
    LINKED = "linked"
    DISABLED = "ACCOUNT_DISABLED"
    PASSWORD_ACCOUNT = "ACCOUNT_EXISTS_PASSWORD"
    GOOGLE_ONLY_ACCOUNT = "ACCOUNT_EXISTS_GOOGLE_ONLY"
    INCONSISTENT = "GOOGLE_IDENTITY_INVALID"


class LinkOutcome(StrEnum):
    """Desenlace de una vinculación desde una sesión ya iniciada."""

    LINK = "link"
    IDEMPOTENT = "idempotent"
    GOOGLE_ALREADY_LINKED = "GOOGLE_ALREADY_LINKED"
    LINK_IDENTITY_TAKEN = "LINK_IDENTITY_TAKEN"
    LINK_EMAIL_MISMATCH = "LINK_EMAIL_MISMATCH"


def decide_linked_account(*, is_active: bool) -> LoginOutcome:
    """Identidad ya vinculada: sesión si la cuenta está activa (RF-11/RF-16).

    Una cuenta desactivada no se reactiva ni se modifica; solo se rechaza con el
    aviso genérico ``ACCOUNT_DISABLED``.
    """

    return LoginOutcome.LINKED if is_active else LoginOutcome.DISABLED


def decide_existing_account(
    *, is_active: bool, has_password: bool, matches: int
) -> LoginOutcome:
    """Correo verificado sin identidad vinculada (RF-12, RF-15, RF-16, RF-17).

    ``matches`` es cuántas cuentas tienen ese correo, comparado sin distinguir
    mayúsculas. Orden de decisión:

    1. ``matches == 0`` → ``CREATE`` (no hay cuenta que pueda estar desactivada).
    2. ``matches > 1`` → ``INCONSISTENT`` (datos incoherentes: no se elige
       cuenta; el llamador responde ``GOOGLE_IDENTITY_INVALID``).
    3. ``is_active`` falso → ``DISABLED``, antes de mirar la contraseña: el
       motivo y el tipo de cuenta no se filtran (RF-16).
    4. Cuenta activa con contraseña → ``PASSWORD_ACCOUNT`` (RF-15: no se vincula
       automáticamente).
    5. Cuenta activa sin contraseña → ``GOOGLE_ONLY_ACCOUNT`` (RF-17: solo puede
       provenir de un estado inconsistente; no se elige ni se crea otra).

    Un recuento negativo es un error de programación y lanza ``ValueError``.
    """

    if matches < 0:
        raise ValueError("matches no puede ser negativo")
    if matches == 0:
        return LoginOutcome.CREATE
    if matches > 1:
        return LoginOutcome.INCONSISTENT
    if not is_active:
        return LoginOutcome.DISABLED
    if has_password:
        return LoginOutcome.PASSWORD_ACCOUNT
    return LoginOutcome.GOOGLE_ONLY_ACCOUNT


def decide_link(
    *,
    account_subject: str | None,
    presented_subject: str,
    identity_owner_id: UUID | None,
    account_id: UUID,
    email_matches: bool,
) -> LinkOutcome:
    """Vinculación de la identidad presentada a la cuenta de la sesión.

    ``account_subject`` es el sujeto de Google que ya tiene la cuenta (``None``
    si no tiene identidad); ``identity_owner_id`` es la cuenta dueña del sujeto
    presentado (``None`` si no está vinculado a ninguna); ``email_matches`` llega
    ya comparado sin distinguir mayúsculas (RF-18).

    Orden de precedencia (plan §5.2):

    1. La cuenta ya tiene el mismo sujeto → ``IDEMPOTENT``: no se escribe nada.
       Gana incluso si el correo del proveedor cambió (RF-14).
    2. La cuenta ya tiene otro sujeto → ``GOOGLE_ALREADY_LINKED``: no se
       sustituye la identidad existente (RF-14).
    3. El sujeto pertenece a otra cuenta → ``LINK_IDENTITY_TAKEN``: no se mueve
       ni se fusiona nada (RF-19).
    4. El correo verificado no coincide con el de la cuenta → 
       ``LINK_EMAIL_MISMATCH`` (RF-18).
    5. Todo coincide → ``LINK``.

    ``identity_owner_id == account_id`` sin sujeto en la cuenta es un estado
    incoherente: el plan solo considera ajena la identidad de **otra** cuenta,
    así que el correo sigue decidiendo y la restricción de unicidad de la 024 es
    la última garantía.
    """

    if account_subject is not None:
        if account_subject == presented_subject:
            return LinkOutcome.IDEMPOTENT
        return LinkOutcome.GOOGLE_ALREADY_LINKED

    if identity_owner_id is not None and identity_owner_id != account_id:
        return LinkOutcome.LINK_IDENTITY_TAKEN

    if not email_matches:
        return LinkOutcome.LINK_EMAIL_MISMATCH

    return LinkOutcome.LINK
