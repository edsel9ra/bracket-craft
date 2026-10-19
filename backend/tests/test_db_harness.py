"""Tests for the PostgreSQL test harness (RF-018).

The database-backed tests are opt-in: they only run with
``RUN_DATABASE_TESTS=1`` and a ``DATABASE_URL`` that points at the
``bracket_app`` role. The pure gating test always runs, so the unit suite
stays green without a database.
"""

import pytest
from sqlalchemy import text

from db_helpers import (
    clear_rls_context,
    count_venues,
    database_tests_enabled,
    insert_venue,
    set_tenant_context,
)


def test_database_suite_is_opt_in():
    assert database_tests_enabled({}) is False
    assert database_tests_enabled({"RUN_DATABASE_TESTS": ""}) is False
    assert database_tests_enabled({"RUN_DATABASE_TESTS": "0"}) is False
    assert database_tests_enabled({"RUN_DATABASE_TESTS": " 1 "}) is True


@pytest.mark.asyncio
async def test_application_role_is_not_superuser_and_cannot_bypass_rls(db_session):
    role = (
        await db_session.execute(
            text("""
                SELECT current_user AS role_name, rolsuper, rolbypassrls, rolcanlogin
                FROM pg_roles
                WHERE rolname = current_user
            """)
        )
    ).mappings().one()

    assert role["role_name"] == "bracket_app"
    assert role["rolcanlogin"] is True
    assert role["rolsuper"] is False
    assert role["rolbypassrls"] is False


@pytest.mark.asyncio
async def test_fixture_creates_organization_and_sets_the_rls_context(db_session, tenant_context):
    session_settings = (
        await db_session.execute(
            text("""
                SELECT current_setting('app.current_organization_id', true) AS organization_id,
                       current_setting('app.current_user_id', true) AS user_id
            """)
        )
    ).mappings().one()
    current_organization = (
        await db_session.execute(text("SELECT id FROM get_current_organization()"))
    ).scalar_one()
    organizations = (
        await db_session.execute(text("SELECT id FROM list_user_organizations()"))
    ).scalars().all()
    member = (
        await db_session.execute(
            text("SELECT id FROM organization_users WHERE id = :member_id"),
            {"member_id": str(tenant_context.member_id)},
        )
    ).scalar_one()

    assert session_settings["organization_id"] == str(tenant_context.organization_id)
    assert session_settings["user_id"] == str(tenant_context.user_id)
    assert current_organization == tenant_context.organization_id
    assert tenant_context.organization_id in organizations
    assert member == tenant_context.member_id


@pytest.mark.asyncio
async def test_tenant_query_returns_rows_with_context_and_none_without(db_session, tenant_context):
    venue_id = await insert_venue(db_session, tenant_context.organization_id)

    assert await count_venues(db_session) == 1

    await clear_rls_context(db_session)

    assert await count_venues(db_session) == 0

    # Restore the context so the fixture's rollback happens in a clean state.
    await set_tenant_context(db_session, tenant_context)
    assert (
        await db_session.execute(
            text("SELECT id FROM venues WHERE id = :venue_id"),
            {"venue_id": str(venue_id)},
        )
    ).scalar_one() == venue_id


@pytest.mark.asyncio
async def test_tenant_rows_are_invisible_to_another_organization(db_session, tenant_factory):
    first = await tenant_factory()
    second = await tenant_factory()

    await set_tenant_context(db_session, first)
    await insert_venue(db_session, first.organization_id)

    assert await count_venues(db_session) == 1

    await set_tenant_context(db_session, second)
    assert await count_venues(db_session) == 0
