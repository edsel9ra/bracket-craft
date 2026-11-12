import pytest

from migration_helpers import apply_migration, throwaway_database


@pytest.mark.parametrize("incremental", [False, True])
async def test_039_preserves_existing_guards_and_rls(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=38) as db:
        guards = await db.fetch("""SELECT p.oid,p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' ORDER BY p.oid""")
        await apply_migration(db, 39)
        for guard in guards:
            assert await db.fetchval("SELECT prosrc FROM pg_proc WHERE oid=$1", guard["oid"]) == guard["prosrc"]
        assert await db.fetchval("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='competitive_impact_procedures'::regclass")
        assert await db.fetchval("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_competitive_impact_%'") == 3
        assert await db.fetchval("SELECT indisunique FROM pg_index WHERE indexrelid='uq_competitive_impact_version'::regclass")
        if not incremental:
            async with throwaway_database(database_admin_url, last=39) as clean:
                assert await clean.fetchval("SELECT prosrc FROM pg_proc WHERE oid='assert_no_open_competitive_impact(uuid,uuid)'::regprocedure") == await db.fetchval("SELECT prosrc FROM pg_proc WHERE oid='assert_no_open_competitive_impact(uuid,uuid)'::regprocedure")
