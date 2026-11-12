"""036 clean chain and incremental upgrade, preserving membership and audit."""

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import SEED_SQL, ORG, MEMBER, MATCH, USER


@pytest.mark.parametrize("incremental", [False, True])
async def test_migration_036_clean_and_incremental(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=35 if incremental else 36) as db:
        await db.execute(SEED_SQL)
        audit = await db.fetchval("""INSERT INTO administrative_audit_logs
            (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
            VALUES ($1, 'matches', $2, 'HISTORICAL', '{}', $3) RETURNING id""", ORG, MATCH, MEMBER)
        old = dict(await db.fetchrow("SELECT * FROM administrative_audit_logs WHERE id = $1", audit))
        if incremental:
            await apply_migration(db, 36)
        row = dict(await db.fetchrow("SELECT * FROM administrative_audit_logs WHERE id = $1", audit))
        assert all(row[key] == value for key, value in old.items())
        assert row["performed_by_user_id"] is None
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute("""INSERT INTO administrative_audit_logs
                (organization_id, entity_type, entity_id, action, payload)
                VALUES ($1, 'matches', $2, 'NO_ACTOR', '{}')""", ORG, MATCH)
        function = await db.fetchrow("SELECT prosecdef, provolatile::text, proconfig FROM pg_proc WHERE oid = 'fn_verify_user_org_membership(uuid)'::regprocedure")
        assert function["prosecdef"] and function["provolatile"] == 's'
        assert function["proconfig"] == ['search_path=pg_catalog, public']
        assert await db.fetchval("SELECT has_function_privilege('bracket_app', 'rectification_platform_scopes()', 'EXECUTE')")
        assert not await db.fetchval("SELECT EXISTS (SELECT 1 FROM pg_proc p, LATERAL aclexplode(p.proacl) a WHERE p.oid = 'rectification_platform_scopes()'::regprocedure AND a.grantee = 0)")
        assert not await db.fetchval("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'bracket_app'")
        async with db.transaction():
            await db.execute("SET LOCAL ROLE bracket_app")
            await db.execute("SELECT set_config('app.current_user_id', $1, true)", USER)
            await db.execute("SELECT set_config('app.current_organization_id', $1, true)", ORG)
            assert await db.fetchval("SELECT fn_verify_user_org_membership($1::uuid)", ORG)
            assert await db.fetchval("SELECT count(*) FROM matches") == 1
            await db.execute("SELECT set_config('app.rectification_authorization_id', gen_random_uuid()::text, true)")
            assert await db.fetchval("SELECT fn_verify_user_org_membership($1::uuid)", ORG)
