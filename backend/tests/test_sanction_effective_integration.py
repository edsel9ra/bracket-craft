from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.sanction_appeals.application import record_opening
from app.modules.sanction_appeals.repository import load_effective_sanctions
from test_migration_031 import MATCH, MEMBER, ORG, USER
from test_migration_040 import f9_db as f9_db, insert_case, insert_decision
from migration_helpers import apply_migration
from test_sanction_readers import readers as readers


@pytest.mark.parametrize("action", ["reduce", "annul", None])
async def test_opening_applies_pending_measure_without_convocation_and_preserves_started(readers, action):
    if action:
        case = await insert_case(readers.admin, readers.suspension)
        await insert_decision(readers.admin, case, action=action)
    async with readers.session() as db:
        now = datetime.now(timezone.utc)
        segment = (await db.execute(text("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start,created_at)
            VALUES (:org,:match,1,0,:now) RETURNING id"""), {"org": UUID(ORG), "match": readers.future, "now": now})).scalar_one()
        await record_opening(db, readers.future, segment)
        await record_opening(db, readers.future, segment)
        current = await load_effective_sanctions(db, readers.future, as_of=now)
        old = await load_effective_sanctions(db, UUID(MATCH), as_of=now)
        assert current[0].projection.effective_duration == {"reduce": 1, "annul": 0, None: 3}[action]
        assert old[0].projection.effective_duration == 3
        assert old[0].projection.blocking
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_effect_applications") == int(action is not None)
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_match_eligibility") == 1
    assert await readers.admin.fetchval("SELECT matches_suspended FROM player_suspensions WHERE id=$1", readers.suspension) == 3
    with pytest.raises(DBAPIError, match="SANCTION_OPENING_REQUIRED"):
        async with readers.session() as db:
            await record_opening(db, readers.future, segment)


async def test_opening_rollback_and_unauthorized_actor_leave_no_effects(readers):
    case = await insert_case(readers.admin, readers.suspension)
    await insert_decision(readers.admin, case)
    with pytest.raises(RuntimeError, match="rollback"):
        async with readers.session() as db:
            segment = (await db.execute(text("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start,created_at)
                VALUES (:org,:match,1,0,:now) RETURNING id"""),
                {"org": UUID(ORG), "match": readers.future, "now": datetime.now(timezone.utc)})).scalar_one()
            await record_opening(db, readers.future, segment)
            raise RuntimeError("rollback")
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_effect_applications") == 0
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_match_eligibility") == 0
    assert await readers.admin.fetchval("SELECT status FROM player_suspensions WHERE id=$1", readers.suspension) == "active"


@pytest.mark.parametrize("excluded", [True, False])
async def test_opening_excludes_rectified_resolution_and_rejects_unprivileged_writer(readers, excluded):
    case = await insert_case(readers.admin, readers.suspension)
    await insert_decision(readers.admin, case)
    if excluded:
        request = await readers.admin.fetchval("""INSERT INTO match_report_rectification_requests
            (organization_id,match_id,base_version_number,proposed_report,reason,requested_by_user_id,requested_by_member_id)
            VALUES ($1,$2,1,'{}','Correct report',$3,$4) RETURNING id""", ORG, MATCH, USER, MEMBER)
        version = await readers.admin.fetchval("""INSERT INTO match_report_versions(organization_id,match_id,version_number,
            supersedes_version_number,resolution_type,home_score,away_score,request_id,published_by_user_id)
            VALUES ($1,$2,2,1,'regular',0,0,$3,current_setting('app.current_user_id')::uuid) RETURNING id""", ORG, MATCH, request)
        await readers.admin.execute("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason,rectification_version_id)
            SELECT organization_id,id,'affected_by_rectification',current_setting('app.current_user_id')::uuid,'Corrected',$2 FROM sanction_cases WHERE id=$1""", case, version)
    else:
        await readers.admin.execute("UPDATE roles SET permissions=permissions-'CLOSE_MATCH_REPORT'")
    try:
        async with readers.session() as db:
            segment = (await db.execute(text("""INSERT INTO match_segments(organization_id,match_id,segment_number,minute_start)
                VALUES (:org,:match,1,0) RETURNING id"""), {"org": UUID(ORG), "match": readers.future})).scalar_one()
            await record_opening(db, readers.future, segment)
    except DBAPIError as exc:
        assert not excluded and "SANCTION_OPERATION_DENIED" in str(exc)
    else:
        assert excluded
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_effect_applications") == 0


async def test_opening_migration_041_preserves_040_provenance(f9_db):
    db, suspension = f9_db
    await insert_case(db, suspension)
    before = [dict(row) for row in await db.fetch("SELECT * FROM sanction_transaction_provenance")]
    await apply_migration(db, 41)
    after = [{key: row[key] for key in before[0]} for row in await db.fetch("SELECT * FROM sanction_transaction_provenance")]
    assert before == after
    assert not await db.fetchval("SELECT has_table_privilege('bracket_app','sanction_match_eligibility','INSERT')")
    assert not await db.fetchval("SELECT has_table_privilege('bracket_app','sanction_effect_applications','INSERT')")
    assert not await db.fetchval("SELECT has_function_privilege('public','record_sanction_opening(uuid,uuid)','EXECUTE')")
