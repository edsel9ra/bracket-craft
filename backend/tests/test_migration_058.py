"""058 exposes only live eligibility, not the F9 operational ledger."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.modules.sanction_appeals.repository import load_effective_sanctions
from migration_helpers import apply_migration, throwaway_database
from test_match_live_db import live_service_db as live_service_db, command, goal
from test_migration_031 import (
    MATCH,
    ORG,
    PLAYER_HOME_FIRST,
    TOURNAMENT,
    USER,
    MEMBER,
)
from test_migration_040 import insert_case, insert_decision
from test_migration_056 import app
from test_sanction_readers import readers as readers


QUERY = "SELECT player_id FROM match_live_ineligible_players($1,$2,$3)"


async def suspend(db, status="active"):
    return await db.fetchval(
        """INSERT INTO player_suspensions
        (organization_id,source_tournament_id,player_id,source_type,dedupe_key,scope_type,matches_suspended,reason,status)
        VALUES ($1,$2,$3,'competition_rule',$4,'organization',3,'private reason',$5) RETURNING id""",
        ORG,
        TOURNAMENT,
        PLAYER_HOME_FIRST,
        str(uuid4()),
        status,
    )


async def test_operate_only_rejects_suspended_player_atomically(live_service_db):
    f = live_service_db
    await suspend(f.admin)
    await f.permissions(["OPERATE_MATCH_LIVE"])
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("add_event", event=goal()))
    assert error.value.status_code == 422
    assert error.value.detail == "Contenido live no válido"
    assert str(error.value.__cause__) == "La planilla contiene un jugador suspendido"
    for table in (
        "match_live_events",
        "match_live_commands",
        "match_live_state",
        "match_events",
    ):
        assert await f.admin.fetchval(f"SELECT count(*) FROM {table}") == 0


@pytest.mark.parametrize("role", ["owner", "administrator", "operator"])
async def test_eligibility_minimal_empty_and_deduplicated(live_service_db, role):
    f = live_service_db
    await f.permissions(["OPERATE_MATCH_LIVE"])
    await f.admin.execute(
        "UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code=$1) WHERE organization_id=$2",
        role,
        ORG,
    )
    now = datetime.now(timezone.utc)
    async with app(f.admin):
        assert await f.admin.fetch(QUERY, MATCH, [], now) == []
        assert await f.admin.fetch(QUERY, MATCH, [UUID(PLAYER_HOME_FIRST)], now) == []
    await suspend(f.admin)
    await suspend(f.admin)
    async with app(f.admin):
        rows = await f.admin.fetch(QUERY, MATCH, [UUID(PLAYER_HOME_FIRST)] * 2, now)
        assert len(rows) == 1 and dict(rows[0]) == {
            "player_id": UUID(PLAYER_HOME_FIRST)
        }
        assert not await f.admin.fetchval(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="SANCTION_OPERATION_DENIED"
    ):
        async with app(f.admin):
            await f.admin.fetch("SELECT * FROM sanction_operational_facts($1)", MATCH)


@pytest.mark.parametrize("permissions", [[], ["VIEW_MATCH_LIVE_DRAFT"]])
async def test_eligibility_requires_operate(live_service_db, permissions):
    f = live_service_db
    await f.permissions(permissions)
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="LIVE_ELIGIBILITY_NOT_AUTHORIZED"
    ):
        async with app(f.admin):
            await f.admin.fetch(QUERY, MATCH, [], datetime.now(timezone.utc))


async def test_eligibility_official_scope_and_foreign_tenant(live_service_db):
    f = live_service_db
    await f.permissions(["OPERATE_MATCH_LIVE"])
    await f.admin.execute(
        "UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='referee') WHERE organization_id=$1",
        ORG,
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(f.admin):
            await f.admin.fetch(
                QUERY, MATCH, [UUID(PLAYER_HOME_FIRST)], datetime.now(timezone.utc)
            )
    await f.admin.execute(
        "INSERT INTO match_officials(organization_id,match_id,organization_user_id,official_role) VALUES ($1,$2,$3,'main_referee')",
        ORG,
        MATCH,
        MEMBER,
    )
    async with app(f.admin):
        assert (
            await f.admin.fetch(
                QUERY, MATCH, [UUID(PLAYER_HOME_FIRST)], datetime.now(timezone.utc)
            )
            == []
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(f.admin):
            await f.admin.fetch(
                QUERY,
                MATCH.replace("31000000", "32000000"),
                [UUID(PLAYER_HOME_FIRST)],
                datetime.now(timezone.utc),
            )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(f.admin, org=ORG.replace("31000000", "32000000")):
            await f.admin.fetch(
                QUERY, MATCH, [UUID(PLAYER_HOME_FIRST)], datetime.now(timezone.utc)
            )


@pytest.mark.parametrize("readers", [{"last": 58}], indirect=True)
@pytest.mark.parametrize("action", [None, "reduce", "annul"])
@pytest.mark.parametrize("target", ["started", "future", "opened"])
async def test_eligibility_equivalent_to_existing_projection(readers, action, target):
    f = readers
    await f.admin.execute(
        "UPDATE roles SET permissions=permissions || '[\"OPERATE_MATCH_LIVE\"]'::jsonb"
    )
    if action:
        case = await insert_case(f.admin, f.suspension)
        await insert_decision(f.admin, case, action=action)
    match = UUID(MATCH) if target == "started" else f.future
    if target == "opened":
        from app.modules.sanction_appeals.application import record_opening

        async with f.session() as db:
            segment = (
                await db.execute(
                    text(
                        "INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start) VALUES (:org,:match,1,0) RETURNING id"
                    ),
                    {"org": UUID(ORG), "match": match},
                )
            ).scalar_one()
            await record_opening(db, match, segment)
    now = datetime.now(timezone.utc)
    for scoped_match in {match, UUID(MATCH), f.future}:
        await assert_equivalent(f, scoped_match, now)


async def assert_equivalent(f, match, now):
    async with f.session() as db:
        facts = await load_effective_sanctions(db, match, as_of=now)
        expected = {fact.player_id for fact in facts if fact.projection.blocking}
        actual = set(
            (
                await db.execute(
                    text(
                        "SELECT player_id FROM match_live_ineligible_players(:match,:players,:now)"
                    ),
                    {"match": match, "players": [UUID(PLAYER_HOME_FIRST)], "now": now},
                )
            ).scalars()
        )
        assert actual == expected


@pytest.mark.parametrize("readers", [{"last": 58}], indirect=True)
@pytest.mark.parametrize("status", ["active", "served", "cancelled", "appealed"])
@pytest.mark.parametrize("voided", [True, False])
async def test_eligibility_equivalent_with_status_and_serves(readers, status, voided):
    f = readers
    await f.admin.execute(
        "UPDATE roles SET permissions=permissions || '[\"OPERATE_MATCH_LIVE\"]'::jsonb"
    )
    await f.admin.execute(
        "UPDATE player_suspensions SET status=$1 WHERE id=$2", status, f.suspension
    )
    await f.admin.execute(
        "INSERT INTO player_suspension_serves(organization_id,suspension_id,match_id,is_voided) VALUES ($1,$2,$3,$4)",
        ORG,
        f.suspension,
        MATCH,
        voided,
    )
    await assert_equivalent(f, UUID(MATCH), datetime.now(timezone.utc))


@pytest.mark.parametrize("readers", [{"last": 58}], indirect=True)
async def test_eligibility_excludes_rectified_resolution(readers):
    f = readers
    await f.admin.execute(
        "UPDATE roles SET permissions=permissions || '[\"OPERATE_MATCH_LIVE\"]'::jsonb"
    )
    case = await insert_case(f.admin, f.suspension)
    await insert_decision(f.admin, case, action="annul")
    request = await f.admin.fetchval(
        """INSERT INTO match_report_rectification_requests
        (organization_id,match_id,base_version_number,proposed_report,reason,requested_by_user_id,requested_by_member_id)
        VALUES ($1,$2,1,'{}','Correct report',$3,$4) RETURNING id""",
        ORG,
        MATCH,
        USER,
        MEMBER,
    )
    version = await f.admin.fetchval(
        """INSERT INTO match_report_versions(organization_id,match_id,version_number,
        supersedes_version_number,resolution_type,home_score,away_score,request_id,published_by_user_id)
        VALUES ($1,$2,2,1,'regular',0,0,$3,current_setting('app.current_user_id')::uuid) RETURNING id""",
        ORG,
        MATCH,
        request,
    )
    await f.admin.execute(
        """INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason,rectification_version_id)
        SELECT organization_id,id,'affected_by_rectification',current_setting('app.current_user_id')::uuid,'Corrected',$2 FROM sanction_cases WHERE id=$1""",
        case,
        version,
    )
    await assert_equivalent(f, UUID(MATCH), datetime.now(timezone.utc))


async def test_058_clean_incremental_idempotent_and_privileges(database_admin_url):
    async with throwaway_database(database_admin_url, last=58) as db:
        row = await db.fetchrow(
            "SELECT prosecdef,proconfig FROM pg_proc WHERE proname='match_live_ineligible_players'"
        )
        assert row["prosecdef"] and "search_path=pg_catalog, public" in row["proconfig"]
        assert await db.fetchval(
            "SELECT has_function_privilege('bracket_app','match_live_ineligible_players(uuid,uuid[],timestamptz)','EXECUTE')"
        )
        assert not await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.proname='match_live_ineligible_players' AND a.grantee=0)"
        )
    async with throwaway_database(database_admin_url, last=57) as db:
        for _ in range(2):
            await apply_migration(db, 58)
        assert (
            await db.fetchval(
                "SELECT count(*) FROM pg_proc WHERE proname='match_live_ineligible_players'"
            )
            == 1
        )
