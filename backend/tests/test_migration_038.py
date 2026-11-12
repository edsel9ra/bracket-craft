"""D4 is the only difference from the original published-structure protection."""

from pathlib import Path
import re

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MATCH, SEED_SQL


async def prohibited_operations(db):
    failures = []
    assignments = ["home_team_id=NULL", "away_team_id=NULL", "organization_id=gen_random_uuid()",
        "tournament_id=gen_random_uuid()", "tournament_version_id=gen_random_uuid()",
        "stage_id=gen_random_uuid()", "group_id=gen_random_uuid()", "home_slot_id=gen_random_uuid()",
        "away_slot_id=gen_random_uuid()", "replacement_match_id=gen_random_uuid()", "matchday=2", "bracket_code='other'"]
    statements = [f"UPDATE matches SET {assignment} WHERE id=$1" for assignment in assignments]
    statements.extend(["DELETE FROM matches WHERE id=$1", """INSERT INTO matches
        (organization_id,tournament_id,tournament_version_id,stage_id)
        SELECT organization_id,tournament_id,tournament_version_id,stage_id FROM matches WHERE id=$1"""])
    for statement in statements:
        with pytest.raises(asyncpg.PostgresError) as rejected:
            async with db.transaction():
                await db.execute(statement, MATCH)
        failures.append((rejected.value.sqlstate, str(rejected.value)))
    return failures


@pytest.mark.parametrize("incremental", [False, True])
async def test_038_preserves_literal_guard_and_all_nonexception_prohibitions(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=37) as db:
        await db.execute(SEED_SQL)
        old = await db.fetchval("SELECT prosrc FROM pg_proc WHERE oid='prevent_published_match_structure_mutation()'::regprocedure")
        before = await prohibited_operations(db)
        await apply_migration(db, 38)
        new = await db.fetchval("SELECT prosrc FROM pg_proc WHERE oid='prevent_published_match_structure_mutation()'::regprocedure")
        for side in ["home", "away"]:
            new = new.replace(f"\n                     AND NOT public.apply_rectification_slot(OLD, NEW, '{side}')", "")
        assert new == old
        assert await prohibited_operations(db) == before
        if not incremental:
            async with throwaway_database(database_admin_url, last=38) as clean:
                actual = await clean.fetchval("SELECT prosrc FROM pg_proc WHERE oid='prevent_published_match_structure_mutation()'::regprocedure")
                assert actual == await db.fetchval("SELECT prosrc FROM pg_proc WHERE oid='prevent_published_match_structure_mutation()'::regprocedure")
        source = (Path(__file__).parents[2] / "infra/postgres/init/03_hardening.sql").read_text()
        body = re.search(r"CREATE OR REPLACE FUNCTION prevent_published_match_structure_mutation\(\)[\s\S]*?AS \$\$([\s\S]*?)\$\$;", source)
        assert body and body.group(1) == old
