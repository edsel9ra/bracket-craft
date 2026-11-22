"""064 concede el permiso de auditoría organizacional e indexa la consulta (spec 041, T1)."""

from uuid import uuid4

from migration_helpers import ORG, apply_migration, throwaway_database

PERMISSION = "VIEW_ORGANIZATION_AUDIT"
INDEX = "idx_administrative_audit_logs_org_performed"
ROLE_CODES = ("owner", "administrator", "operator", "referee", "viewer")
GRANTED = {"owner", "administrator"}


async def seed_roles(db, organization_id: str) -> None:
    await db.execute(
        "INSERT INTO public.organizations (id, name, slug) VALUES ($1, $2, $3)",
        organization_id, f"Org {organization_id[:8]}", f"org-{organization_id[:8]}",
    )
    await db.execute(
        """
        INSERT INTO public.roles (organization_id, role_definition_id, name, permissions)
        SELECT $1, rd.id, rd.name, rd.system_permissions FROM public.role_definitions rd
        """,
        organization_id,
    )


async def granted_definitions(db) -> set[str]:
    rows = await db.fetch(
        "SELECT code FROM public.role_definitions WHERE system_permissions @> $1::jsonb",
        f'["{PERMISSION}"]',
    )
    return {row["code"] for row in rows}


async def granted_roles(db, organization_id: str) -> set[str]:
    rows = await db.fetch(
        """
        SELECT rd.code FROM public.roles r JOIN public.role_definitions rd ON rd.id = r.role_definition_id
        WHERE r.organization_id = $1 AND r.permissions @> $2::jsonb
        """,
        organization_id, f'["{PERMISSION}"]',
    )
    return {row["code"] for row in rows}


async def permission_count(db, organization_id: str) -> int:
    return await db.fetchval(
        """
        SELECT count(*) FROM public.roles r, jsonb_array_elements_text(r.permissions) p
        WHERE r.organization_id = $1 AND p = $2
        """,
        organization_id, PERMISSION,
    )


async def test_064_clean_volume_grants_owner_and_administrator_only(database_admin_url):
    async with throwaway_database(database_admin_url, last=64) as db:
        assert await granted_definitions(db) == GRANTED
        assert {row["code"] for row in await db.fetch("SELECT code FROM public.role_definitions")} >= set(ROLE_CODES)
        new_org = str(uuid4())
        await seed_roles(db, new_org)
        assert await granted_roles(db, new_org) == GRANTED


async def test_064_index_orders_by_organization_date_and_id(database_admin_url):
    async with throwaway_database(database_admin_url, last=64) as db:
        definition = await db.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname = $1", INDEX)
        assert definition is not None
        assert "administrative_audit_logs" in definition
        assert "(organization_id, performed_at DESC, id DESC)" in definition


async def test_064_incremental_from_063_updates_existing_roles_and_is_idempotent(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as db:
        await seed_roles(db, ORG)
        assert await granted_roles(db, ORG) == set()
        for _ in range(2):
            await apply_migration(db, 64)
        assert await granted_definitions(db) == GRANTED
        assert await granted_roles(db, ORG) == GRANTED
        assert await permission_count(db, ORG) == len(GRANTED)
        assert await db.fetchval("SELECT count(*) FROM pg_indexes WHERE indexname = $1", INDEX) == 1


async def test_064_does_not_change_audit_table_security(database_admin_url):
    async with throwaway_database(database_admin_url, last=64) as db:
        table = "public.administrative_audit_logs"
        assert await db.fetchval(
            f"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid = '{table}'::regclass"
        )
        assert await db.fetchval(f"SELECT has_table_privilege('bracket_app', '{table}', 'SELECT')")
        assert not await db.fetchval("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'bracket_app'")
