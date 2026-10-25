"""Resolución del inicio de sesión con Google sobre la base de datos (RF-10, RF-12, RF-26, RF-27).

Una sola transacción resuelve la identidad, la cuenta, la organización inicial y
la sesión:

1. Identidad ``(google, provider_subject)`` ya vinculada → su cuenta
   (``decide_linked_account``; una cuenta desactivada se rechaza sin
   reactivarla).
2. Sin identidad → se decide por el correo verificado
   (``decide_existing_account``): alta, cuenta con contraseña, cuenta solo-Google
   o datos inconsistentes.
3. Alta: ``users`` sin contraseña, correo en minúsculas y nombre saneado, y
   después la identidad. La transacción garantiza que no quede nada a medias.
4. ``set_rls_context(db, None, user_id)`` antes de ``list_user_organizations()``;
   la organización inicial es la primera del orden estable.
5. ``create_user_session`` emite la sesión existente de la aplicación.

El camino de Google nunca escribe membresías ni roles (RF-26) y no abre una
segunda transacción. La concurrencia y la vinculación desde una sesión iniciada
son tareas posteriores (T9/T10).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.security import create_user_session
from app.modules.identity.account_rules import (
    LinkOutcome,
    LoginOutcome,
    decide_existing_account,
    decide_link,
    decide_linked_account,
)
from app.modules.identity.google_claims import GoogleIdentity, sanitize_display_name
from app.modules.organizations.ordering import ordered_organizations

GOOGLE_PROVIDER = "google"

# D-10: sin `ON CONFLICT`. Un conflicto de unicidad se resuelve releyendo una
# sola vez lo que ya confirmó otra transacción; un segundo conflicto falla
# cerrado.
MAX_LOGIN_ATTEMPTS = 2


class LoginRejected(Exception):
    """Inicio rechazado: ``code`` es el valor del catálogo que usa el router.

    No lleva correo, nombre, sujeto ni identificadores; el router traduce el
    código a su mensaje y estado HTTP. ``outcome`` conserva el desenlace para
    decidir el flujo.
    """

    def __init__(self, outcome: LoginOutcome) -> None:
        self.outcome = outcome
        self.code = outcome.value
        super().__init__(outcome.value)


class LinkRejected(Exception):
    """Vinculación rechazada con un código del catálogo (sin datos personales).

    ``outcome`` es el desenlace de ``decide_link`` cuando lo hay; un conflicto de
    unicidad que no se puede atribuir a una rama conocida se cierra con el código
    ``GOOGLE_IDENTITY_INVALID`` y ``outcome`` nulo.
    """

    def __init__(self, outcome: LinkOutcome | str) -> None:
        if isinstance(outcome, LinkOutcome):
            self.outcome: LinkOutcome | None = outcome
            self.code = outcome.value
        else:
            self.outcome = None
            self.code = str(outcome)
        super().__init__(self.code)


class SessionAccountInvalid(Exception):
    """La cuenta de la sesión ya no existe o está desactivada (sesión inválida).

    El módulo no responde HTTP: el router lo traduce a ``401`` sin escribir nada.
    """


@dataclass(frozen=True)
class LoginResult:
    """Sesión resuelta: cuenta, organización inicial y token existente."""

    outcome: LoginOutcome
    user_id: UUID
    organization_id: UUID | None
    session_token: str


async def resolve_login(db: AsyncSession, identity: GoogleIdentity) -> LoginResult:
    """Resuelve la cuenta y la sesión de una identidad ya verificada.

    ``identity`` viene de ``google_claims.parse_identity_claims``: sujeto y
    correo presentes, correo verificado. El correo se normaliza una vez
    (``strip`` y minúsculas) para buscar y, si hay alta, para guardar; el correo
    almacenado de una cuenta existente nunca se reescribe.

    Lanza ``LoginRejected`` con el desenlace del catálogo cuando no hay sesión
    (``ACCOUNT_DISABLED``, ``ACCOUNT_EXISTS_PASSWORD``,
    ``ACCOUNT_EXISTS_GOOGLE_ONLY`` o ``GOOGLE_IDENTITY_INVALID``) sin escribir
    nada. Devuelve ``LoginResult`` con ``CREATE`` o ``LINKED``.

    **Segundo pase (RF-13, RF-22, RNF-11).** Si el ``INSERT`` del alta choca con
    una garantía de unicidad (correo, identidad o una identidad por cuenta), otra
    transacción ganó la carrera: se revierte el intento y se repite **una sola
    vez** con exactamente la misma consulta, que ahora ve lo ya confirmado
    (identidad creada → sesión para esa cuenta; correo ya creado sin contraseña
    → ``ACCOUNT_EXISTS_GOOGLE_ONLY``; con contraseña →
    ``ACCOUNT_EXISTS_PASSWORD``). No hay ``ON CONFLICT`` (D-10), no hay bucles ni
    reintentos arbitrarios: un segundo conflicto falla cerrado con
    ``GOOGLE_IDENTITY_INVALID`` (nunca un 500).
    """

    email = identity.email.strip().lower()
    attempts_left = MAX_LOGIN_ATTEMPTS - 1

    while True:
        try:
            return await _resolve_login_once(db, identity, email)
        except IntegrityError:
            if attempts_left == 0:
                raise LoginRejected(LoginOutcome.INCONSISTENT) from None
            attempts_left -= 1


async def _resolve_login_once(
    db: AsyncSession, identity: GoogleIdentity, email: str
) -> LoginResult:
    """Un intento completo en una sola transacción (se revierte si choca)."""

    async with db.begin():
        linked = (
            await db.execute(
                text("""
                    SELECT ai.user_id, u.is_active
                    FROM public.auth_identities ai
                    JOIN public.users u ON u.id = ai.user_id
                    WHERE ai.provider = :provider
                      AND ai.provider_subject = :subject
                """),
                {"provider": GOOGLE_PROVIDER, "subject": identity.subject},
            )
        ).mappings().one_or_none()

        if linked is not None:
            outcome = decide_linked_account(is_active=linked["is_active"])
            if outcome is not LoginOutcome.LINKED:
                raise LoginRejected(outcome)
            user_id = linked["user_id"]
        else:
            accounts = (
                await db.execute(
                    text("""
                        SELECT id, is_active, password_hash
                        FROM public.users
                        WHERE LOWER(email) = LOWER(:email)
                        ORDER BY id
                    """),
                    {"email": email},
                )
            ).mappings().all()
            account = accounts[0] if accounts else None

            outcome = decide_existing_account(
                is_active=account["is_active"] if account is not None else True,
                has_password=(
                    account["password_hash"] is not None
                    if account is not None
                    else False
                ),
                matches=len(accounts),
            )
            if outcome is not LoginOutcome.CREATE:
                raise LoginRejected(outcome)

            full_name = sanitize_display_name(identity.name, identity.email)
            user_id = (
                await db.execute(
                    text("""
                        INSERT INTO public.users (email, password_hash, full_name)
                        VALUES (:email, NULL, :full_name)
                        RETURNING id
                    """),
                    {"email": email, "full_name": full_name},
                )
            ).scalar_one()
            await db.execute(
                text("""
                    INSERT INTO public.auth_identities
                        (user_id, provider, provider_subject)
                    VALUES (:user_id, :provider, :subject)
                """),
                {
                    "user_id": user_id,
                    "provider": GOOGLE_PROVIDER,
                    "subject": identity.subject,
                },
            )

        await set_rls_context(db, None, user_id)
        organizations = (
            await db.execute(text("SELECT id, name FROM list_user_organizations()"))
        ).mappings().all()
        ordered = ordered_organizations(organizations)
        organization_id = ordered[0]["id"] if ordered else None

        session_token = await create_user_session(db, user_id)

    return LoginResult(
        outcome=outcome,
        user_id=user_id,
        organization_id=organization_id,
        session_token=session_token,
    )


async def link_identity(
    db: AsyncSession, *, user_id: UUID, identity: GoogleIdentity
) -> LinkOutcome:
    """Vincula la identidad presentada a la cuenta de la sesión (RF-14, RF-18…RF-21).

    Una sola transacción: lee la cuenta activa, la identidad que ya tiene la
    cuenta y la cuenta dueña del sujeto presentado, aplica ``decide_link`` y solo
    inserta cuando el desenlace es ``LINK``.

    * ``IDEMPOTENT`` devuelve éxito sin escribir (mismo sujeto ya vinculado).
    * ``GOOGLE_ALREADY_LINKED``, ``LINK_IDENTITY_TAKEN`` y
      ``LINK_EMAIL_MISMATCH`` lanzan ``LinkRejected`` sin cambios.
    * La cuenta de la sesión inexistente o desactivada lanza
      ``SessionAccountInvalid`` (el router responde 401) sin escribir.

    No actualiza ``users.email`` (el correo almacenado manda: RF-20), no borra
    filas, no toca ``user_sessions`` ni escribe membresías o roles (RF-21). La
    restricción ``uq_auth_identity_user_provider`` de la 024 es la última
    garantía: si el ``INSERT`` choca con una carrera, el conflicto se clasifica y
    se responde con un código del catálogo, nunca con un 500.
    """

    email = identity.email.strip().lower()

    try:
        async with db.begin():
            account = (
                await db.execute(
                    text("""
                        SELECT id, email
                        FROM public.users
                        WHERE id = :user_id AND is_active = TRUE
                    """),
                    {"user_id": user_id},
                )
            ).mappings().one_or_none()
            if account is None:
                raise SessionAccountInvalid(
                    "La sesión no corresponde a una cuenta activa."
                )

            account_subject = (
                await db.execute(
                    text("""
                        SELECT provider_subject
                        FROM public.auth_identities
                        WHERE user_id = :user_id AND provider = :provider
                    """),
                    {"user_id": user_id, "provider": GOOGLE_PROVIDER},
                )
            ).scalars().first()

            identity_owner_id = (
                await db.execute(
                    text("""
                        SELECT user_id
                        FROM public.auth_identities
                        WHERE provider = :provider AND provider_subject = :subject
                    """),
                    {"provider": GOOGLE_PROVIDER, "subject": identity.subject},
                )
            ).scalars().first()

            outcome = decide_link(
                account_subject=account_subject,
                presented_subject=identity.subject,
                identity_owner_id=identity_owner_id,
                account_id=user_id,
                email_matches=account["email"].strip().lower() == email,
            )

            if outcome is LinkOutcome.IDEMPOTENT:
                return LinkOutcome.IDEMPOTENT
            if outcome is not LinkOutcome.LINK:
                raise LinkRejected(outcome)

            await db.execute(
                text("""
                    INSERT INTO public.auth_identities
                        (user_id, provider, provider_subject)
                    VALUES (:user_id, :provider, :subject)
                """),
                {
                    "user_id": user_id,
                    "provider": GOOGLE_PROVIDER,
                    "subject": identity.subject,
                },
            )
    except IntegrityError:
        # Otra transacción ganó la carrera: el intento se revirtió y se clasifica
        # en una lectura nueva (sin escrituras).
        await _classify_link_conflict(db, user_id=user_id, subject=identity.subject)
        raise LinkRejected("GOOGLE_IDENTITY_INVALID")

    return LinkOutcome.LINK


async def _classify_link_conflict(
    db: AsyncSession, *, user_id: UUID, subject: str
) -> None:
    """Traduce un choque de unicidad de la vinculación a un código del catálogo.

    Se ejecuta después de revertir el intento: si la cuenta ya tiene una
    identidad, el choque fue por ``uq_auth_identity_user_provider``; si el sujeto
    pertenece a otra cuenta, por ``uq_auth_provider_subject``. Si no queda
    rastro de ninguno de los dos, falla cerrado con ``GOOGLE_IDENTITY_INVALID``.
    """

    async with db.begin():
        account_subject = (
            await db.execute(
                text("""
                    SELECT provider_subject
                    FROM public.auth_identities
                    WHERE user_id = :user_id AND provider = :provider
                """),
                {"user_id": user_id, "provider": GOOGLE_PROVIDER},
            )
        ).scalars().first()

        identity_owner_id = (
            await db.execute(
                text("""
                    SELECT user_id
                    FROM public.auth_identities
                    WHERE provider = :provider AND provider_subject = :subject
                """),
                {"provider": GOOGLE_PROVIDER, "subject": subject},
            )
        ).scalars().first()

    if account_subject is not None:
        raise LinkRejected(LinkOutcome.GOOGLE_ALREADY_LINKED)
    if identity_owner_id is not None and identity_owner_id != user_id:
        raise LinkRejected(LinkOutcome.LINK_IDENTITY_TAKEN)
    raise LinkRejected("GOOGLE_IDENTITY_INVALID")
