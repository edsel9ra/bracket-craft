"""F9 schema tested with the application role on disposable PostgreSQL databases."""

from uuid import uuid4

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MEMBER, ORG, PLAYER_HOME_FIRST, TOURNAMENT, USER, SEED_SQL


@pytest.fixture
async def f9_db(database_admin_url):
    async with throwaway_database(database_admin_url, last=39) as db:
        await db.execute(SEED_SQL)
        await apply_migration(db, 40)
        suspension = await db.fetchval("""INSERT INTO player_suspensions
            (organization_id,source_tournament_id,player_id,source_type,dedupe_key,
             scope_type,matches_suspended,reason)
            VALUES ($1,$2,$3,'competition_rule','f9-original','organization',3,'test') RETURNING id""",
            ORG, TOURNAMENT, PLAYER_HOME_FIRST)
        yield db, suspension


async def app_context(db, org=ORG, user=USER):
    await db.execute("SET LOCAL ROLE bracket_app")
    await db.execute("SELECT set_config('app.current_organization_id',$1,true)", org)
    await db.execute("SELECT set_config('app.current_user_id',$1,true)", user)


async def insert_case(db, suspension, *, case_id=None, kind="appeal"):
    case_id = case_id or uuid4()
    await db.execute("""INSERT INTO sanction_cases
        (id,organization_id,suspension_id,case_type,submitted_by_user_id,submitted_by_member_id,
         represented_player_id,reason,base_fingerprint,base_duration,proposed_action)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'Review','{}',3,$8)""",
        case_id, ORG, suspension, kind, USER, MEMBER, PLAYER_HOME_FIRST,
        "annul" if kind == "administrative_proposal" else None)
    return case_id


async def test_cases_rls_pending_and_history(f9_db):
    db, suspension = f9_db
    for table in ("sanction_cases", "sanction_case_events"):
        assert await db.fetchval("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass", table)
    await insert_case(db, suspension)
    with pytest.raises(asyncpg.UniqueViolationError):
        await insert_case(db, suspension, kind="administrative_proposal")
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute("UPDATE sanction_cases SET reason='overwrite'")
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute("DELETE FROM sanction_cases")
    async with db.transaction():
        await app_context(db)
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0
        await db.execute("SELECT set_config('app.rectification_authorization_id',gen_random_uuid()::text,true)")
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0
    assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 1
    other_org = await db.fetchval("INSERT INTO organizations(name,slug) VALUES ('Other','f9-other') RETURNING id")
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await db.execute("""INSERT INTO sanction_cases
            (organization_id,suspension_id,case_type,submitted_by_user_id,submitted_by_member_id,
             represented_player_id,reason,base_fingerprint,base_duration)
            VALUES ($1,$2,'appeal',$3,$4,$5,'Review','{}',3)""", other_org, suspension, USER, MEMBER, PLAYER_HOME_FIRST)
    role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'F9 viewer','["VIEW_SANCTION_CASES"]' FROM role_definitions WHERE code='viewer' RETURNING id""", ORG)
    await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
    async with db.transaction():
        await app_context(db)
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 1
        await db.execute("SELECT set_config('app.current_organization_id',$1,true)", str(other_org))
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0
    assert await db.fetchval("SELECT matches_suspended FROM player_suspensions WHERE id=$1", suspension) == 3
    assert not await db.fetchval("SELECT rolbypassrls FROM pg_roles WHERE rolname='bracket_app'")
