import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import set_rls_context
from app.core.tenancy import AuthContext
from app.modules.sanction_appeals.repository import load_effective_sanctions
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from migration_helpers import throwaway_database
from test_migration_031 import MATCH, MEMBER, ORG, PLAYER_HOME_FIRST, SEED_SQL, TEAM_HOME, TOURNAMENT, USER
from test_migration_040 import insert_case, insert_decision

FUTURE = "31000000-0000-4000-8000-000000000053"


@pytest.fixture
async def readers(database_admin_url, request):
    options = request.param if isinstance(getattr(request, "param", None), dict) else {}
    async with throwaway_database(database_admin_url, last=options.get("last", 41)) as admin:
        seed = SEED_SQL.replace("1, '{}'::jsonb, '{}'::jsonb,", f"1, '{json.dumps(DEFAULT_RULES_CONFIG)}'::jsonb, '{{}}'::jsonb,")
        seed = seed.replace("UPDATE public.tournament_versions", f"""
            INSERT INTO matches(id,organization_id,tournament_id,tournament_version_id,stage_id,home_team_id,away_team_id,status)
            SELECT '{FUTURE}',organization_id,tournament_id,tournament_version_id,stage_id,home_team_id,away_team_id,'scheduled'
            FROM matches WHERE id='{MATCH}';
            UPDATE public.tournament_versions""")
        await admin.execute(seed)
        role = await admin.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
            SELECT $1,id,'F9 writer','["CLOSE_MATCH_REPORT","SUBMIT_SANCTION_APPEALS","RESOLVE_SANCTION_CASES"]'
            FROM role_definitions WHERE code='operator' RETURNING id""", ORG)
        await admin.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
        await admin.execute("""INSERT INTO rosters(organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
            VALUES ($1,$2,$3,$4,1,'2026-01-01','2026-01-01')""", ORG, TOURNAMENT, TEAM_HOME, PLAYER_HOME_FIRST)
        suspension = await admin.fetchval("""INSERT INTO player_suspensions(organization_id,source_tournament_id,player_id,
            source_type,dedupe_key,scope_type,matches_suspended,reason) VALUES ($1,$2,$3,'competition_rule','original','organization',3,'test')
            RETURNING id""", ORG, TOURNAMENT, PLAYER_HOME_FIRST)
        await admin.execute("SELECT set_config('app.current_organization_id',$1,false),set_config('app.current_user_id',$2,false)", ORG, USER)
        database = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(make_url(database_admin_url).set(database=database))
        context = AuthContext(UUID(USER), UUID(ORG), UUID(MEMBER))

        @asynccontextmanager
        async def session(org=ORG):
            async with engine.connect() as connection:
                await connection.execute(text("SET ROLE bracket_app"))
                await connection.commit()
                async with AsyncSession(bind=connection) as db, db.begin():
                    await set_rls_context(db, UUID(org), UUID(USER))
                    yield db

        try:
            yield SimpleNamespace(admin=admin, engine=engine, context=context, session=session, suspension=suspension, future=UUID(FUTURE))
        finally:
            await engine.dispose()


async def test_repository_batches_operational_facts_without_case_access(readers):
    await insert_case(readers.admin, readers.suspension, evidence="Private evidence")
    statements = []
    event.listen(readers.engine.sync_engine, "before_cursor_execute", lambda *args: statements.append(args[2]))
    async with readers.session() as db:
        statements.clear()
        facts = await load_effective_sanctions(db, UUID(MATCH), as_of=datetime.now(timezone.utc))
        assert len(statements) == 2
        assert len(facts) == 1
        assert facts[0].projection.effective_duration == 3
        assert facts[0].projection.blocking
        assert not hasattr(facts[0], "reason") and not hasattr(facts[0], "case_id")
        assert (await db.execute(text("SELECT count(*) FROM sanction_cases"))).scalar_one() == 0
    with pytest.raises(DBAPIError, match="SANCTION_OPERATION_DENIED"):
        async with readers.session(org=str(uuid4())) as db:
            await load_effective_sanctions(db, UUID(MATCH), as_of=datetime.now(timezone.utc))


@pytest.mark.parametrize("readers", [{"last": 40}], indirect=True)
async def test_requester_already_reads_original_suspensions_under_040_rls(readers):
    await readers.admin.execute("UPDATE roles SET permissions='[\"REQUEST_MATCH_REPORT_RECTIFICATION\"]'")
    async with readers.session() as db:
        assert (await db.execute(text("SELECT current_user"))).scalar_one() == "bracket_app"
        rows = (await db.execute(text("SELECT id, organization_id, matches_suspended, status FROM player_suspensions"))).mappings().all()
        assert len(rows) == 1
        assert rows[0]["id"] == readers.suspension
        assert rows[0]["organization_id"] == UUID(ORG)
        assert rows[0]["matches_suspended"] == 3 and rows[0]["status"] == "active"


async def test_repository_pending_preview_empty_and_applied_resolution(readers):
    case = await insert_case(readers.admin, readers.suspension)
    await insert_decision(readers.admin, case, action="reduce")
    async with readers.session() as db:
        current = await load_effective_sanctions(db, UUID(MATCH), as_of=datetime.now(timezone.utc))
        preview = await load_effective_sanctions(db, readers.future, as_of=datetime.now(timezone.utc), preview=True)
        assert current[0].projection.effective_duration == 3
        assert preview[0].projection.effective_duration == 1
        assert preview[0].projection.pending_effect
    await readers.admin.execute("DELETE FROM rosters")
    async with readers.session() as db:
        assert await load_effective_sanctions(db, UUID(MATCH), as_of=datetime.now(timezone.utc)) == []
