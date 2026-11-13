"""F9 schema tested with the application role on disposable PostgreSQL databases."""

import json
from uuid import uuid4

import asyncpg
import pytest

from app.core.roles import SANCTION_CASE_PERMISSIONS

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MATCH, MEMBER, ORG, PLAYER_HOME_FIRST, SEGMENT_FIRST, TEAM_HOME, TOURNAMENT, USER, SEED_SQL


@pytest.fixture
async def f9_db(database_admin_url):
    async with throwaway_database(database_admin_url, last=39) as db:
        await db.execute(SEED_SQL)
        await apply_migration(db, 40)
        role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
            SELECT $1,id,'F9 writer','["SUBMIT_SANCTION_APPEALS","RESOLVE_SANCTION_CASES"]'
            FROM role_definitions WHERE code='viewer' RETURNING id""", ORG)
        await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
        await db.execute("SELECT set_config('app.current_organization_id',$1,false), set_config('app.current_user_id',$2,false)", ORG, USER)
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


async def insert_case(db, suspension, *, case_id=None, kind="appeal", evidence=None):
    case_id = case_id or uuid4()
    await db.execute("SELECT set_config('app.current_user_id',$1,false)", USER)
    async with db.transaction():
        await db.execute("""INSERT INTO sanction_cases
            (id,organization_id,suspension_id,case_type,submitted_by_user_id,submitted_by_member_id,
             represented_player_id,reason,base_fingerprint,base_duration,proposed_action,evidence_text)
            VALUES ($1,$2,$3,$4,$5,$6,$7,'Review','{}',3,$8,$9)""",
            case_id, ORG, suspension, kind, USER, MEMBER, PLAYER_HOME_FIRST,
            "annul" if kind == "administrative_proposal" else None, evidence)
        await db.execute("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
            VALUES ($1,$2,'submitted',$3,'Review')""", ORG, case_id, USER)
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
    with pytest.raises((asyncpg.ForeignKeyViolationError, asyncpg.InsufficientPrivilegeError)):
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


@pytest.mark.parametrize("kind,permission", [("appeal", "SUBMIT_SANCTION_APPEALS"), ("administrative_proposal", "RESOLVE_SANCTION_CASES")])
@pytest.mark.parametrize("revoke_before_event", [True, False])
async def test_withdrawal_requires_current_permission_at_event_and_finalization(f9_db, kind, permission, revoke_before_event):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension, kind=kind)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="SANCTION_EVENT_DENIED"):
        async with db.transaction():
            if not revoke_before_event:
                await db.execute("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
                    VALUES ($1,$2,'withdrawn',$3,'Withdraw')""", ORG, case_id, USER)
            await db.execute("UPDATE roles SET permissions=permissions-$1 WHERE organization_id=$2 AND name='F9 writer'", permission, ORG)
            await app_context(db)
            if revoke_before_event:
                await db.execute("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
                    VALUES ($1,$2,'withdrawn',$3,'Withdraw')""", ORG, case_id, USER)
            else:
                await db.execute("SELECT sanction_finalize_case($1)", case_id)
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "pending"


async def test_auxiliary_private_authorizations_prejudice_notifications(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    admin = await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-platform@test.invalid','Platform') RETURNING id")
    authorization = await authorize_platform(db, case_id, admin)
    assert authorization
    await db.execute("""INSERT INTO sanction_prejudice_records
        (organization_id,case_id,match_id,recorded_by_user_id,reason)
        VALUES ($1,$2,$3,$4,'Played match remains unchanged')""", ORG, case_id, MATCH, USER)
    async with db.transaction():
        event = await db.fetchval("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
            VALUES ($1,$2,'withdrawn',$3,'Withdrawn by applicant') RETURNING id""", ORG, case_id, USER)
        await record_notice(db, case_id, event)
        await db.execute("SELECT sanction_finalize_case($1)", case_id)
    for table in ("sanction_prejudice_records", "sanction_notifications", "sanction_platform_authorizations"):
        assert await db.fetchval("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass", table)
        async with db.transaction():
            await app_context(db, user=str(admin))
            assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(f"DELETE FROM {table}")
    columns = await db.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='sanction_notifications'")
    assert not {"evidence_text", "evidence_links", "attachments"} & {r[0] for r in columns}


async def test_transitions_direct_self_decision_and_deferred_completeness(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_SELF_DECISION"):
        await insert_decision(db, case_id, actor=USER)
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "pending"
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_MISSING_ACT"):
        await db.execute("UPDATE sanction_cases SET status='resolved' WHERE id=$1", case_id)
    async with db.transaction():
        await db.execute("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
            VALUES ($1,$2,'withdrawn',$3,'Withdraw')""", ORG, case_id, USER)
        await db.execute("SELECT sanction_finalize_case($1)", case_id)
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "withdrawn"
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute("UPDATE sanction_cases SET status='pending' WHERE id=$1", case_id)
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_MISSING_ACT"):
        await db.execute("""INSERT INTO sanction_cases
            (organization_id,suspension_id,case_type,submitted_by_user_id,submitted_by_member_id,
             represented_player_id,reason,base_fingerprint,base_duration)
            VALUES ($1,$2,'appeal',$3,$4,$5,'Missing event','{}',3)""", ORG, suspension, USER, MEMBER, PLAYER_HOME_FIRST)
    proposal = await insert_case(db, suspension, kind="administrative_proposal")
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_DECISION_CATALOG"):
        await insert_decision(db, proposal, action="maintain")
    await insert_decision(db, proposal, action="reject")
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", proposal) == "resolved"
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_FINAL_CASE"):
        await insert_case(db, suspension)
    assert await db.fetchval("SELECT status FROM player_suspensions WHERE id=$1", suspension) == "active"


@pytest.mark.parametrize("kind,action", [("appeal", "maintain"), ("appeal", "annul"),
    ("appeal", "reduce"), ("administrative_proposal", "approve"), ("administrative_proposal", "reject")])
async def test_transitions_catalog_normal(f9_db, kind, action):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension, kind=kind)
    await insert_decision(db, case_id, action=action)
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "resolved"
    assert await db.fetchval("SELECT status FROM player_suspensions WHERE id=$1", suspension) == "active"


async def test_transitions_app_role_and_missing_resolution_at_commit(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_SELF_DECISION"):
        async with db.transaction():
            await app_context(db)
            await db.execute("""INSERT INTO sanction_case_decisions
                (organization_id,case_id,decided_by_user_id,decided_by_member_id,decided_as,decision,reason,before_duration)
                VALUES ($1,$2,$3,$4,'member','maintain','Self',3)""", ORG, case_id, USER, MEMBER)
    actor = await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-deferred@test.invalid','Other') RETURNING id")
    member = await db.fetchval("INSERT INTO organization_users(organization_id,user_id) VALUES ($1,$2) RETURNING id", ORG, actor)
    await db.execute("""INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id)
        SELECT $1,$2,id FROM roles WHERE organization_id=$1 AND name='F9 writer'""", ORG, member)
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_MISSING_RESOLUTION"):
        async with db.transaction():
            await app_context(db, user=str(actor))
            await db.execute("""INSERT INTO sanction_case_decisions
                (organization_id,case_id,decided_by_user_id,decided_by_member_id,decided_as,decision,reason,before_duration,after_duration)
                VALUES ($1,$2,$3,$4,'member','reduce','No resolution',3,1)""", ORG, case_id, actor, member)
            await db.execute("SELECT sanction_finalize_case($1)", case_id)
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "pending"
    assert await db.fetchval("SELECT count(*) FROM sanction_case_decisions") == 0


async def test_applications_and_match_snapshots(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    decision = await insert_decision(db, case_id)
    resolution = await db.fetchval("SELECT id FROM sanction_resolutions WHERE decision_id=$1", decision)
    assert await db.fetchval("SELECT count(*) FROM sanction_effect_applications") == 0
    await db.execute("""INSERT INTO sanction_effect_applications
        (organization_id,resolution_id,suspension_id,match_id,effective_at,before_status,after_status)
        VALUES ($1,$2,$3,$4,'2026-11-12','active','active')""", ORG, resolution, suspension, MATCH)
    await db.execute("""INSERT INTO sanction_match_eligibility
        (organization_id,suspension_id,match_id,effective_duration,applicable_status,started_at)
        VALUES ($1,$2,$3,1,'active','2026-11-12')""", ORG, suspension, MATCH)
    for table in ("sanction_effect_applications", "sanction_match_eligibility"):
        assert await db.fetchval("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass", table)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(f"DELETE FROM {table}")
        async with db.transaction():
            await app_context(db)
            assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0
    assert not await db.fetchval("SELECT rolbypassrls FROM pg_roles WHERE rolname='bracket_app'")


async def test_permissions_defaults_and_minimal_operational_facts(f9_db):
    db, suspension = f9_db
    for code in ("owner", "administrator", "operator", "referee", "viewer"):
        permissions = json.loads(await db.fetchval("SELECT system_permissions FROM role_definitions WHERE code=$1", code))
        assert set(SANCTION_CASE_PERMISSIONS).issubset(permissions) == (code in ("owner", "administrator"))
    await insert_case(db, suspension)
    role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'Operation only','["CLOSE_MATCH_REPORT"]' FROM role_definitions WHERE code='operator' RETURNING id""", ORG)
    await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
    await db.execute("""INSERT INTO rosters(organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
        SELECT $1,$2,home_team_id,$3,5,now(),now() FROM matches WHERE id=$4""", ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH)
    async with db.transaction():
        await app_context(db)
        rows = await db.fetch("SELECT * FROM sanction_operational_facts($1)", MATCH)
        assert len(rows) == 1
        assert rows[0]["suspension_id"] == suspension
        assert rows[0]["original_duration"] == 3
        assert not {"reason", "evidence_text", "evidence_links", "case_id"} & set(rows[0].keys())
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0
        assert not await db.fetchval("SELECT sanction_member_has_permission($1,'VIEW_SANCTION_CASES')", ORG)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with db.transaction():
            await app_context(db, org=str(uuid4()))
            await db.fetch("SELECT * FROM sanction_operational_facts($1)", MATCH)


async def authorize_platform(db, case_id, admin):
    await db.execute("INSERT INTO platform_admins(user_id,role_code) VALUES ($1,'platform_admin')", admin)
    role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'F9 owner',system_permissions FROM role_definitions WHERE code='owner' RETURNING id""", ORG)
    await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
    await db.execute("SELECT set_config('app.current_user_id',$1,false)", USER)
    return await db.fetchval("""INSERT INTO sanction_platform_authorizations
        (organization_id,case_id,granted_by_member_id,platform_admin_user_id,reason)
        VALUES ($1,$2,$3,$4,'Exceptional decision') RETURNING id""", ORG, case_id, MEMBER, admin)


async def test_platform_scopes_are_case_local_and_not_membership(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension, kind="administrative_proposal")
    admin = await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-scoped@test.invalid','Admin') RETURNING id")
    authorization = await authorize_platform(db, case_id, admin)
    async with db.transaction():
        await app_context(db, user=str(admin))
        await db.execute("SELECT set_config('app.rectification_authorization_id',$1,true)", str(authorization))
        assert not await db.fetchval("SELECT sanction_platform_scope($1)", case_id)
        await db.execute("SELECT set_config('app.sanction_authorization_id',$1,true)", str(authorization))
        assert await db.fetchval("SELECT sanction_platform_scope($1)", case_id)
        assert not await db.fetchval("SELECT sanction_platform_scope($1)", uuid4())
        assert not await db.fetchval("SELECT fn_verify_user_org_membership($1)", ORG)
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 1
        assert await db.fetchval("SELECT count(*) FROM player_suspensions") == 0
        source = json.loads(await db.fetchval("SELECT sanction_platform_source($1)", case_id))
        assert source["id"] == str(suspension)
        assert "reason" not in source
        decision = uuid4()
        await db.execute("""INSERT INTO sanction_case_decisions
            (id,organization_id,case_id,decided_by_user_id,decided_as,authorization_id,decision,reason,before_duration)
            VALUES ($1,$2,$3,$4,'platform_admin',$5,'reject','Verified',3)""", decision, ORG, case_id, admin, authorization)
        await db.execute("SELECT sanction_finalize_case($1)", case_id)
        assert not await db.fetchval("SELECT sanction_platform_scope($1)", case_id)
    assert await db.fetchval("SELECT consumed_at IS NOT NULL FROM sanction_platform_authorizations WHERE id=$1", authorization)
    assert await db.fetchval("SELECT count(*) FROM platform_audit_logs WHERE action='DECIDE_SANCTION_CASE'") == 1
    assert await db.fetchval("SELECT count(*) FROM administrative_audit_logs WHERE action='DECIDE_SANCTION_CASE'") == 1
    async with db.transaction():
        await app_context(db, user=str(admin))
        assert not await db.fetchval("SELECT sanction_platform_scope($1)", case_id)


@pytest.mark.parametrize("invalidated", ["owner", "admin", "support", "organization", "revoked"])
async def test_platform_authority_revalidated(f9_db, invalidated):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    admin = await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-invalid@test.invalid','Admin') RETURNING id")
    authorization = await authorize_platform(db, case_id, admin)
    if invalidated == "owner":
        await db.execute("UPDATE organization_users SET is_active=FALSE WHERE id=$1", MEMBER)
    elif invalidated == "admin":
        await db.execute("UPDATE users SET is_active=FALSE WHERE id=$1", admin)
    elif invalidated == "support":
        await db.execute("UPDATE platform_admins SET role_code='platform_support' WHERE user_id=$1", admin)
    elif invalidated == "organization":
        await db.execute("UPDATE organizations SET is_active=FALSE WHERE id=$1", ORG)
    else:
        await db.execute("SELECT sanction_revoke_authorization($1)", authorization)
    async with db.transaction():
        await app_context(db, user=str(admin))
        await db.execute("SELECT set_config('app.sanction_authorization_id',$1,true)", str(authorization))
        assert not await db.fetchval("SELECT sanction_platform_scope($1)", case_id)
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0


async def test_platform_self_decision_even_with_authorization(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension, kind="administrative_proposal")
    authorization = await authorize_platform(db, case_id, USER)
    with pytest.raises(asyncpg.CheckViolationError, match="SANCTION_SELF_DECISION"):
        async with db.transaction():
            await app_context(db)
            await db.execute("SELECT set_config('app.sanction_authorization_id',$1,true)", str(authorization))
            await db.execute("""INSERT INTO sanction_case_decisions
                (organization_id,case_id,decided_by_user_id,decided_as,authorization_id,decision,reason,before_duration)
                VALUES ($1,$2,$3,'platform_admin',$4,'approve','Own proposal',3)""", ORG, case_id, USER, authorization)
    assert await db.fetchval("SELECT consumed_at FROM sanction_platform_authorizations WHERE id=$1", authorization) is None


async def record_notice(db, case_id, event, channel="internal"):
    notice = uuid4()
    outbox = await db.fetchval("""INSERT INTO outbox_events(organization_id,event_type,payload)
        VALUES ($1,$2,jsonb_build_object('notification_id',$3::TEXT)) RETURNING id""", ORG,
        "SANCTION_CASE_NOTICE_EMAIL" if channel == "email" else "SANCTION_CASE_NOTICE_INTERNAL", str(notice))
    await db.execute("""INSERT INTO sanction_notifications
        (id,organization_id,case_id,recipient_user_id,channel,notification_type,reason,outbox_event_id,case_event_id)
        VALUES ($1,$2,$3,$4,$5,'withdrawn','Withdrawn by applicant',$6,$7)""", notice, ORG, case_id, USER, channel, outbox, event)
    return notice, outbox


async def test_delivery_claimed_event_without_impersonation_and_private_reads(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    async with db.transaction():
        event = await db.fetchval("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
            VALUES ($1,$2,'withdrawn',$3,'Withdrawn by applicant') RETURNING id""", ORG, case_id, USER)
        notice, outbox = await record_notice(db, case_id, event)
        await db.execute("SELECT sanction_finalize_case($1)", case_id)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await db.fetchval("SELECT deliver_sanction_notice($1)", outbox)
    async with db.transaction():
        await db.execute("SET LOCAL ROLE bracket_app")
        await db.execute("SELECT set_config('app.current_user_id','',true), set_config('app.current_organization_id','',true)")
        assert len(await db.fetch("SELECT * FROM claim_outbox_events(20)")) == 1
        assert await db.fetchval("SELECT deliver_sanction_notice($1)", outbox)
        assert await db.fetchval("SELECT deliver_sanction_notice($1)", outbox)
        assert await db.fetchval("SELECT count(*) FROM sanction_notifications") == 0
        assert await db.fetchval("SELECT count(*) FROM sanction_notification_deliveries") == 0
    assert await db.fetchval("SELECT count(*) FROM sanction_notification_deliveries WHERE notification_id=$1 AND outcome='delivered'", notice) == 1
    async with db.transaction():
        await app_context(db)
        assert await db.fetchval("SELECT count(*) FROM sanction_notifications") == 1
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0
    await db.execute("UPDATE organization_users SET is_active=FALSE WHERE id=$1", MEMBER)
    assert not await db.fetchval("SELECT deliver_sanction_notice($1)", outbox)
    assert await db.fetchval("SELECT count(*) FROM sanction_notification_deliveries WHERE outcome='withheld'") == 1
    async with db.transaction():
        await app_context(db)
        assert await db.fetchval("SELECT count(*) FROM sanction_notifications") == 0


async def test_bridge_requires_new_publication_and_accredited_sanction_change(f9_db):
    db, _ = f9_db
    await db.execute("""INSERT INTO rosters(organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
        VALUES ($1,$2,$3,$4,1,now(),now())""", ORG, TOURNAMENT, TEAM_HOME, PLAYER_HOME_FIRST)
    await db.execute("""INSERT INTO match_rosters(organization_id,match_id,roster_id,player_id,team_id,tournament_id,role)
        SELECT organization_id,$1,id,player_id,team_id,tournament_id,'starter' FROM rosters""", MATCH)
    source = await db.fetchval("""INSERT INTO match_events(organization_id,match_id,segment_id,team_id,player_id,event_type,minute,client_event_id)
        VALUES ($1,$2,$3,$4,$5,'red_card',30,'f9-bridge-red') RETURNING id""", ORG, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST)
    suspension = await db.fetchval("""INSERT INTO player_suspensions(organization_id,source_tournament_id,player_id,
        origin_match_id,source_event_id,source_type,dedupe_key,scope_type,matches_suspended,reason)
        VALUES ($1,$2,$3,$4,$5,'match_event','f9-bridge','organization',3,'red') RETURNING id""", ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH, source)
    case_id = await insert_case(db, suspension)
    publisher = await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-bridge@test.invalid','Rectifier') RETURNING id")
    member = await db.fetchval("INSERT INTO organization_users(organization_id,user_id) VALUES ($1,$2) RETURNING id", ORG, publisher)
    role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'Rectify only','["APPROVE_MATCH_REPORT_RECTIFICATION"]' FROM role_definitions WHERE code='viewer' RETURNING id""", ORG)
    await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, member, role)
    request = await db.fetchval("""INSERT INTO match_report_rectification_requests
        (organization_id,match_id,base_version_number,proposed_report,reason,requested_by_user_id,requested_by_member_id)
        VALUES ($1,$2,1,'{}','Correct report',$3,$4) RETURNING id""", ORG, MATCH, USER, MEMBER)
    async with db.transaction():
        version = await db.fetchval("""INSERT INTO match_report_versions(organization_id,match_id,version_number,
            supersedes_version_number,resolution_type,home_score,away_score,request_id,published_by_user_id)
            VALUES ($1,$2,2,1,'regular',0,0,$3,$4) RETURNING id""", ORG, MATCH, request, publisher)
        async with db.transaction():
            await app_context(db, user=str(publisher))
            assert await db.fetchval("SELECT close_sanction_cases_for_rectification($1)", version) == 0
        await db.execute("UPDATE player_suspensions SET status='cancelled' WHERE id=$1", suspension)
        await db.execute("INSERT INTO player_suspension_annulments(organization_id,suspension_id,version_id,reason) VALUES ($1,$2,$3,'Corrected card')", ORG, suspension, version)
        await app_context(db, user=str(publisher))
        assert await db.fetchval("SELECT close_sanction_cases_for_rectification($1)", version) == 1
        assert await db.fetchval("SELECT count(*) FROM sanction_cases") == 0
        assert not await db.fetchval("SELECT has_column_privilege('bracket_app','sanction_cases','status','UPDATE')")
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "closed_by_rectification"
    assert await db.fetchval("SELECT count(*) FROM sanction_case_decisions") == 0


@pytest.mark.parametrize("incremental", [False, True])
async def test_migration_040_clean_and_incremental_guards_and_grants(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=39 if incremental else 40) as db:
        before = {row["name"]: row["definition"] for row in await db.fetch("""SELECT p.oid::regprocedure::TEXT AS name,
            pg_get_functiondef(p.oid) AS definition FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prokind='f'""")}
        await db.execute(SEED_SQL)
        role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
            SELECT $1,id,'Owner',system_permissions FROM role_definitions WHERE code='owner' RETURNING id""", ORG)
        if incremental:
            await apply_migration(db, 40)
        for name, definition in before.items():
            assert await db.fetchval("SELECT pg_get_functiondef($1::regprocedure)", name) == definition
        permissions = json.loads(await db.fetchval("SELECT permissions FROM roles WHERE id=$1", role))
        assert set(SANCTION_CASE_PERMISSIONS).issubset(permissions)
        assert len(permissions) == len(set(permissions))
        functions = await db.fetch("""SELECT p.oid::regprocedure::TEXT AS name,p.proconfig,p.prosecdef,
            EXISTS (SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0) AS public_execute
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'
            AND (p.proname LIKE 'sanction_%' OR p.proname LIKE 'protect_sanction_%'
                OR p.proname IN ('record_sanction_platform_audit','deliver_sanction_notice','close_sanction_cases_for_rectification'))""")
        for function in functions:
            assert not function["public_execute"], function["name"]
            assert function["proconfig"] == ['search_path=pg_catalog, public']
        assert not await db.fetchval("SELECT has_function_privilege('bracket_app','sanction_claimed_notice(uuid)','EXECUTE')")
        assert not await db.fetchval("SELECT has_table_privilege('bracket_app','sanction_notification_deliveries','INSERT')")
        assert not await db.fetchval("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname='bracket_app'")


async def test_delivery_email_minimal_payload_and_reauthorization(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension, evidence="Private supporting report")
    async with db.transaction():
        event = await db.fetchval("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
            VALUES ($1,$2,'withdrawn',$3,'Withdrawn by applicant') RETURNING id""", ORG, case_id, USER)
        _, outbox = await record_notice(db, case_id, event, channel="email")
        await db.execute("SELECT sanction_finalize_case($1)", case_id)
    async with db.transaction():
        await db.execute("SET LOCAL ROLE bracket_app")
        await db.fetch("SELECT * FROM claim_outbox_events(20)")
        payload = json.loads(await db.fetchval("SELECT sanction_notice_email_payload($1)", outbox))
        assert set(payload) == {"recipient", "case_id", "type", "decision", "reason"}
        assert payload["reason"] == "Withdrawn by applicant"
        assert "Private supporting report" not in json.dumps(payload)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await db.execute("SELECT deliver_sanction_notice($1)", outbox)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await db.execute("SELECT sanction_notice_email_payload($1)", uuid4())
    await db.execute("UPDATE organization_users SET is_active=FALSE WHERE id=$1", MEMBER)
    assert await db.fetchval("SELECT sanction_notice_email_payload($1)", outbox) is None


async def test_platform_rollback_restores_authorization_and_both_audits(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension, kind="administrative_proposal")
    admin = await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-rollback@test.invalid','Admin') RETURNING id")
    authorization = await authorize_platform(db, case_id, admin)
    with pytest.raises(RuntimeError, match="rollback"):
        async with db.transaction():
            await app_context(db, user=str(admin))
            await db.execute("SELECT set_config('app.sanction_authorization_id',$1,true)", str(authorization))
            await db.execute("""INSERT INTO sanction_case_decisions
                (organization_id,case_id,decided_by_user_id,decided_as,authorization_id,decision,reason,before_duration)
                VALUES ($1,$2,$3,'platform_admin',$4,'reject','Verified',3)""", ORG, case_id, admin, authorization)
            await db.execute("SELECT sanction_finalize_case($1)", case_id)
            raise RuntimeError("rollback")
    assert await db.fetchval("SELECT status FROM sanction_cases WHERE id=$1", case_id) == "pending"
    assert await db.fetchval("SELECT consumed_at FROM sanction_platform_authorizations WHERE id=$1", authorization) is None
    assert await db.fetchval("SELECT count(*) FROM platform_audit_logs WHERE action='DECIDE_SANCTION_CASE'") == 0
    assert await db.fetchval("SELECT count(*) FROM administrative_audit_logs WHERE action='DECIDE_SANCTION_CASE'") == 0


async def insert_decision(db, case_id, actor=None, action="reduce"):
    actor = actor or await db.fetchval("SELECT id FROM users WHERE email='f9-decider@test.invalid'") or await db.fetchval("INSERT INTO users(email,full_name) VALUES ('f9-decider@test.invalid','Decider') RETURNING id")
    member = await db.fetchval("SELECT id FROM organization_users WHERE organization_id=$1 AND user_id=$2", ORG, actor)
    if member is None:
        member = await db.fetchval("INSERT INTO organization_users(organization_id,user_id) VALUES ($1,$2) RETURNING id", ORG, actor)
        await db.execute("""INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id)
            SELECT $1,$2,id FROM roles WHERE organization_id=$1 AND name='F9 writer'""", ORG, member)
    await db.execute("SELECT set_config('app.current_user_id',$1,false)", str(actor))
    async with db.transaction():
        decision = await db.fetchval("""INSERT INTO sanction_case_decisions
            (organization_id,case_id,decided_by_user_id,decided_by_member_id,decided_as,decision,reason,before_duration,after_duration)
            VALUES ($1,$2,$3,$4,'member',$5,'Verified',3,$6) RETURNING id""", ORG, case_id, actor, member, action,
            1 if action == "reduce" else None)
        if action in ("reduce", "annul", "approve"):
            await db.execute("""INSERT INTO sanction_resolutions
                (organization_id,case_id,decision_id,suspension_id,action,original_duration,
                 before_duration,new_duration,served_count,is_declarative)
                SELECT $1,$2,$3,suspension_id,$4,3,3,$5,0,FALSE FROM sanction_cases WHERE id=$2""",
                ORG, case_id, decision, "annul" if action == "approve" else action, 1 if action == "reduce" else None)
        await db.execute("SELECT sanction_finalize_case($1)", case_id)
    return decision


async def test_decisions_append_only_and_duration_original(f9_db):
    db, suspension = f9_db
    case_id = await insert_case(db, suspension)
    decision = await insert_decision(db, case_id)
    resolution = await db.fetchval("SELECT id FROM sanction_resolutions WHERE decision_id=$1", decision)
    assert resolution
    for table in ("sanction_case_decisions", "sanction_resolutions"):
        assert await db.fetchval("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass", table)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(f"UPDATE {table} SET created_at=created_at + interval '1 second'")
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(f"DELETE FROM {table}")
    with pytest.raises(asyncpg.UndefinedColumnError):
        await db.execute("UPDATE sanction_case_decisions SET attachments='[]'")
    async with db.transaction():
        await app_context(db)
        assert await db.fetchval("SELECT count(*) FROM sanction_resolutions") == 0
    assert await db.fetchval("SELECT matches_suspended FROM player_suspensions WHERE id=$1", suspension) == 3
