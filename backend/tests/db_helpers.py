"""Reusable helpers for PostgreSQL-backed tests (RF-018).

The helpers assume the connection uses the application role (``bracket_app``):
it is not a superuser, does not have ``BYPASSRLS`` and cannot insert into
``organizations`` directly. Organizations and their owner are therefore created
through the ``SECURITY DEFINER`` function ``create_organization_with_owner``.

Every helper works inside the transaction owned by the ``db_session`` fixture,
so the fixture rolls the whole tenant back when the test finishes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import set_rls_context

RUN_DATABASE_TESTS = "RUN_DATABASE_TESTS"
DATABASE_ADMIN_URL = "DATABASE_ADMIN_URL"


def database_tests_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the opt-in PostgreSQL suite is enabled."""

    source = os.environ if environ is None else environ
    return source.get(RUN_DATABASE_TESTS, "").strip() == "1"


def application_database_url() -> str:
    """Return the URL used by the tests; it must point at the application role."""

    return get_settings().database_url


def admin_database_url(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the administrator URL used to apply migrations, when configured.

    Migration tests create a throwaway database and apply the real migration
    files with a role that owns the schema. The application role cannot do that,
    so the harness needs a second, explicit URL.
    """

    source = os.environ if environ is None else environ
    value = source.get(DATABASE_ADMIN_URL, "").strip()
    return value or None


@dataclass(frozen=True)
class TenantContext:
    organization_id: UUID
    user_id: UUID
    member_id: UUID


async def create_test_user(session: AsyncSession, *, full_name: str = "Harness Owner") -> UUID:
    """Create a throwaway user with a unique email."""

    result = await session.execute(
        text("""
            INSERT INTO users (email, password_hash, full_name)
            VALUES (:email, :password_hash, :full_name)
            RETURNING id
        """),
        {
            "email": f"harness-{uuid4().hex}@example.test",
            "password_hash": "integration-test-hash",
            "full_name": full_name,
        },
    )
    return result.scalar_one()


async def create_test_organization(
    session: AsyncSession,
    owner_user_id: UUID,
    *,
    name: str | None = None,
) -> UUID:
    """Create an organization plus its owner membership and role."""

    slug = f"harness-{uuid4().hex[:16]}"
    result = await session.execute(
        text("SELECT create_organization_with_owner(:name, :slug, :owner_id)"),
        {
            "name": name or f"Harness {slug}",
            "slug": slug,
            "owner_id": str(owner_user_id),
        },
    )
    return result.scalar_one()


async def set_tenant_context(session: AsyncSession, tenant: TenantContext) -> None:
    """Set both RLS session variables for the given tenant."""

    await set_rls_context(session, tenant.organization_id, tenant.user_id)


async def clear_rls_context(session: AsyncSession) -> None:
    """Remove the tenant context so tenant-owned tables return no rows."""

    await set_rls_context(session, None, None)


async def create_tenant_owner(
    session: AsyncSession,
    *,
    full_name: str = "Harness Owner",
) -> TenantContext:
    """Create an isolated organization and leave its RLS context active."""

    user_id = await create_test_user(session, full_name=full_name)
    organization_id = await create_test_organization(session, user_id)
    await set_rls_context(session, organization_id, user_id)
    member_id = (
        await session.execute(
            text("""
                SELECT id
                FROM organization_users
                WHERE organization_id = :organization_id
                  AND user_id = :user_id
            """),
            {"organization_id": str(organization_id), "user_id": str(user_id)},
        )
    ).scalar_one()
    return TenantContext(
        organization_id=organization_id,
        user_id=user_id,
        member_id=member_id,
    )


async def insert_player(
    session: AsyncSession,
    organization_id: UUID,
    *,
    first_name: str = "Harness",
    last_name: str = "Player",
    document_type: str = "DNI",
    issuing_country: str = "ARG",
    national_id_hmac: str | None = None,
    birth_date: date | str = "2000-01-01",
    reference_year: int | None = None,
) -> UUID:
    """Insert a minimal tenant-owned player and return its id.

    The birth date is write-only: it is stored encrypted with
    ``PLAYER_DATA_KEY`` and never written in clear text. The materialized age
    uses the explicit ``reference_year`` or, when omitted, the current year.
    Tests that assert a concrete age pass it explicitly to stay deterministic.
    """

    if isinstance(birth_date, str):
        birth_date = date.fromisoformat(birth_date)

    reference_year = reference_year if reference_year is not None else date.today().year
    age_at_reference = reference_year - birth_date.year

    result = await session.execute(
        text("""
            INSERT INTO players (
                organization_id, first_name, last_name, document_type,
                national_id_encrypted, national_id_hmac, issuing_country,
                birth_date_encrypted, age_at_reference, age_reference_year
            )
            VALUES (
                :organization_id, :first_name, :last_name, :document_type,
                decode('00', 'hex'), :national_id_hmac, :issuing_country,
                pgp_sym_encrypt(CAST(:birth_date AS TEXT), :player_data_key),
                :age_at_reference, :reference_year
            )
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "first_name": first_name,
            "last_name": last_name,
            "document_type": document_type,
            "national_id_hmac": national_id_hmac or uuid4().hex * 2,
            "issuing_country": issuing_country,
            "birth_date": birth_date.isoformat(),
            "player_data_key": get_settings().player_data_key,
            "age_at_reference": age_at_reference,
            "reference_year": reference_year,
        },
    )
    return result.scalar_one()


async def insert_venue(
    session: AsyncSession,
    organization_id: UUID,
    *,
    name: str = "Harness Venue",
) -> UUID:
    """Insert a tenant-owned row using the active RLS context."""

    result = await session.execute(
        text("""
            INSERT INTO venues (organization_id, name)
            VALUES (:organization_id, :name)
            RETURNING id
        """),
        {"organization_id": str(organization_id), "name": name},
    )
    return result.scalar_one()


async def count_venues(session: AsyncSession) -> int:
    """Count the tenant rows visible under the active RLS context."""

    return (await session.execute(text("SELECT count(*) FROM venues"))).scalar_one()
