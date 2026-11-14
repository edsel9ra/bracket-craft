"""F1 foundation: real migrations, application-role SQL and inert projections."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import (
    MATCH, MEMBER, ORG, PLAYER_HOME_FIRST, PLAYER_HOME_SECOND, SEGMENT_FIRST, SEED_SQL,
    TEAM_AWAY, TEAM_HOME, TOURNAMENT, USER,
)
from test_rectification_flow import flow as flow
from test_realtime_delivery_db import test_resources_rectification_requires_readable_concrete_version as legacy_version_read

TABLES = ("match_live_state", "match_live_events", "match_live_commands", "match_live_reviews")
PERMISSIONS = ["VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE"]
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


async def seed(db):
    await db.execute(SEED_SQL)
    await db.execute(SEED_SQL.replace("31000000", "32000000").replace("migration-031", "migration-056-other"))
    role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'Live owner',system_permissions FROM role_definitions WHERE code='owner' RETURNING id""", ORG)
    await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
    session = uuid4()
    await db.execute("INSERT INTO user_sessions(id,user_id,expires_at) VALUES ($1,$2,'2099-01-01')", session, USER)
    await db.execute("UPDATE matches SET status='live' WHERE id=$1", MATCH)
    return session


@pytest.fixture
async def live_db(database_admin_url):
    async with throwaway_database(database_admin_url, last=55) as db:
        session = await seed(db)
        matches = await db.fetch("SELECT to_jsonb(m) FROM matches m ORDER BY id")
        projections = await db.fetch("SELECT viewname,definition FROM pg_views WHERE schemaname='public' ORDER BY viewname")
        await apply_migration(db, 56)
        assert await db.fetch("SELECT to_jsonb(m) FROM matches m ORDER BY id") == matches
        assert [row for row in await db.fetch("SELECT viewname,definition FROM pg_views WHERE schemaname='public' ORDER BY viewname")
                if row['viewname'] not in ('v_match_live_public_selection', 'v_public_match_live')] == projections
        yield db, session


@asynccontextmanager
async def app(db, org=ORG, user=USER):
    async with db.transaction():
        await db.execute("SET LOCAL ROLE bracket_app")
        await db.execute("SELECT set_config('app.current_organization_id',$1,true),set_config('app.current_user_id',$2,true)", org, user)
        yield


async def state(db):
    await db.execute("INSERT INTO match_live_state(organization_id,match_id,updated_by_member_id) VALUES ($1,$2,$3)", ORG, MATCH, MEMBER)


async def event(db, **changes):
    data = dict(organization_id=ORG, match_id=MATCH, segment_id=SEGMENT_FIRST, team_id=TEAM_HOME,
                player_id=PLAYER_HOME_FIRST, event_type="goal", minute=1, client_event_id=uuid4())
    data.update(changes)
    columns = ",".join(data)
    placeholders = ",".join(f"${i}" for i in range(1, len(data) + 1))
    await db.execute(f"INSERT INTO match_live_events({columns}) VALUES ({placeholders})", *data.values())


async def command(db, session, command_id=None, **changes):
    data = dict(organization_id=ORG, match_id=MATCH, command_id=command_id or uuid4(), actor_user_id=USER,
                session_id=session, request_hash="a" * 64, command_type="add_event", revision=1)
    data.update(changes)
    await db.execute(f"INSERT INTO match_live_commands({','.join(data)}) VALUES ({','.join(f'${i}' for i in range(1,len(data)+1))})", *data.values())


async def review(db, session, **changes):
    data = dict(organization_id=ORG, match_id=MATCH, actor_user_id=USER, session_id=session,
                content_revision=0, fingerprint="a" * 64, result='{"resolution_type":"regular","home_score":0,"away_score":0}')
    data.update(changes)
    return await db.fetchval(f"INSERT INTO match_live_reviews({','.join(data)}) VALUES ({','.join(f'${i}' for i in range(1,len(data)+1))}) RETURNING id", *data.values())


async def test_baseline_055(database_admin_url):
    async with throwaway_database(database_admin_url, last=55) as db:
        await seed(db)
        assert await db.fetchval("SELECT to_regclass('match_live_state')") is None
        assert await db.fetchval("SELECT count(*) FROM matches") == 2


@pytest.mark.parametrize("table", TABLES)
async def test_new_schema_rls(live_db, table):
    db, _ = live_db
    row = await db.fetchrow("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=$1::regclass", table)
    assert all(row)
    async with app(db):
        assert not await db.fetchval("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        assert not await db.fetchval("SELECT has_table_privilege('bracket_app',$1,'DELETE')", table)


async def test_state_table_valid_clock_and_foreign_context(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
        assert await db.fetchval("SELECT clock_state FROM match_live_state") == "not_started"
    for assignment in ["clock_elapsed_us=-1", "clock_state='running'", "clock_anchor_at=now()",
                       "segment_id='32000000-0000-4000-8000-000000000051',clock_state='paused'"]:
        with pytest.raises(asyncpg.PostgresError):
            async with app(db):
                await db.execute(f"UPDATE match_live_state SET {assignment}")
    async with app(db):
        await db.execute("UPDATE match_segments SET status='active',minute_end=NULL WHERE id=$1", SEGMENT_FIRST)
        await db.execute("UPDATE match_live_state SET segment_id=$1,clock_state='running',clock_anchor_at=$2,clock_elapsed_us=1234567", SEGMENT_FIRST, NOW)
        assert await db.fetchval("SELECT clock_elapsed_us FROM match_live_state") == 1234567


@pytest.mark.parametrize("changes", [
    {"team_id": TEAM_HOME.replace("31000000", "32000000")},
    {"segment_id": SEGMENT_FIRST.replace("31000000", "32000000")},
    {"player_id": PLAYER_HOME_FIRST.replace("31000000", "32000000")},
    {"event_type": "unknown"}, {"minute": 181}, {"metadata": '{"private":"no"}'},
    {"event_type": "substitution"}, {"event_type": "own_goal"},
])
async def test_events_table_rejects_invalid_structure(live_db, changes):
    db, _ = live_db
    async with app(db):
        await state(db)
    with pytest.raises(asyncpg.PostgresError):
        async with app(db):
            await event(db, **changes)


async def test_events_table_identity_withdrawal_and_confirmed_untouched(live_db):
    db, _ = live_db
    identity = uuid4()
    async with app(db):
        await state(db)
        await event(db, client_event_id=identity)
        await db.execute("UPDATE match_live_events SET removed_at=now()")
        assert await db.fetchval("SELECT count(*) FROM match_events") == 0
    with pytest.raises(asyncpg.UniqueViolationError):
        async with app(db):
            await event(db, client_event_id=identity)


async def test_commands_table_idempotent_immutable_actor(live_db):
    db, session = live_db
    identity = uuid4()
    async with app(db):
        await state(db)
        await command(db, session, identity)
    for changes in [{}, {"request_hash": "b" * 64}]:
        with pytest.raises(asyncpg.UniqueViolationError):
            async with app(db):
                await command(db, session, identity, **changes)
    with pytest.raises(asyncpg.PostgresError):
        async with app(db):
            await command(db, session, actor_user_id=USER.replace("31000000", "32000000"))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(db):
            await db.execute("UPDATE match_live_commands SET revision=2")


async def test_reviews_table_actor_session_immutable(live_db):
    db, session = live_db
    async with app(db):
        await state(db)
        await review(db, session)
    for changes in [{"actor_user_id": USER.replace("31000000", "32000000")},
                    {"session_id": uuid4()}, {"result": '{"events":[]}'}]:
        with pytest.raises(asyncpg.PostgresError):
            async with app(db):
                await review(db, session, **changes)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(db):
            await db.execute("UPDATE match_live_reviews SET content_revision=1")
    async with app(db, user=USER.replace("31000000", "32000000")):
        assert await db.fetchval("SELECT count(*) FROM match_live_reviews") == 0


@pytest.mark.parametrize("table", TABLES)
async def test_rls_foreign_and_missing_context(live_db, table):
    db, session = live_db
    async with app(db):
        await state(db)
        await event(db)
        await command(db, session)
        await review(db, session)
    for org, user in [("", ""), (ORG.replace("31000000", "32000000"), USER.replace("31000000", "32000000")), (ORG, USER.replace("31000000", "32000000"))]:
        async with app(db, org, user):
            assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0
    async with app(db):
        assert await db.fetchval(f"SELECT count(*) FROM {table}") == 1


async def test_permissions_additive_existing_new_and_reexecution(live_db):
    db, _ = live_db
    before = await db.fetchval("SELECT permissions FROM roles WHERE name='Live owner'")
    for code in ["owner", "administrator", "operator", "referee", "viewer"]:
        permissions = json.loads(await db.fetchval("SELECT system_permissions FROM role_definitions WHERE code=$1", code))
        assert all((permission in permissions) == (code != "viewer") for permission in PERMISSIONS)
    await apply_migration(db, 56)
    assert await db.fetchval("SELECT permissions FROM roles WHERE name='Live owner'") == before
    assert len(json.loads(before)) == len(set(json.loads(before)))
    assert "CLOSE_MATCH_REPORT" in json.loads(before)


async def test_live_integrity_suspend_terminal_and_freeze_rollback(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
        await db.execute("UPDATE matches SET status='suspended' WHERE id=$1", MATCH)
    with pytest.raises(asyncpg.PostgresError):
        async with app(db):
            await event(db)
    async with app(db):
        await db.execute("UPDATE matches SET status='live' WHERE id=$1", MATCH)
    with pytest.raises(asyncpg.PostgresError):
        async with app(db):
            await db.execute("UPDATE matches SET status='scheduled' WHERE id=$1", MATCH)
    with pytest.raises(RuntimeError):
        async with app(db):
            await db.execute("UPDATE match_live_state SET frozen_at=now()")
            raise RuntimeError("rollback")
    async with app(db):
        assert await db.fetchval("SELECT frozen_at FROM match_live_state") is None
        await db.execute("UPDATE match_live_state SET frozen_at=now()")
    with pytest.raises(asyncpg.PostgresError):
        async with app(db):
            await event(db)


async def decisions(db, session, event_type="MATCH_LIVE_UPDATED", **changes):
    envelope = dict(event_type=event_type, scope="organization", match_id=MATCH, tournament_id=TOURNAMENT)
    envelope.update(changes)
    return await db.fetch("SELECT * FROM authorize_realtime_recipients($1,$2::jsonb,$3::jsonb,$4)",
                          ORG, json.dumps([dict(user_id=USER, session_id=str(session))]), json.dumps(envelope), NOW)


async def test_realtime_live_authorization_and_context(live_db):
    db, session = live_db
    async with app(db):
        before = await db.fetchval("SELECT current_setting('app.current_user_id')")
        assert (await decisions(db, session))[0]["decision"] == "ALLOW"
        assert (await decisions(db, session, version_id=str(uuid4())))[0]["decision"] == "DENY"
        assert (await decisions(db, session, match_id=str(uuid4())))[0]["decision"] == "DENY"
        assert (await decisions(db, session, "SANCTION_CASE_NOTICE_INTERNAL"))[0]["decision"] == "DENY"
        assert await db.fetchval("SELECT current_setting('app.current_user_id')") == before
        assert not await db.fetchval("SELECT prosecdef FROM pg_proc WHERE proname='authorize_realtime_recipients'")
    await db.execute("UPDATE roles SET permissions='[\"OPERATE_MATCH_LIVE\"]' WHERE name='Live owner'")
    async with app(db):
        assert (await decisions(db, session))[0]["decision"] == "DENY"


@pytest.mark.parametrize("count", [256, 257])
async def test_realtime_live_batch_limit(live_db, count):
    db, session = live_db
    candidates = json.dumps([dict(user_id=USER, session_id=str(session))] * count)
    async with app(db):
        if count == 257:
            with pytest.raises(asyncpg.InvalidParameterValueError):
                await db.fetch("SELECT * FROM authorize_realtime_recipients($1,$2::jsonb,'{}',$3)", ORG, candidates, NOW)
        else:
            assert len(await db.fetch("SELECT * FROM authorize_realtime_recipients($1,$2::jsonb,'{}',$3)", ORG, candidates, NOW)) == 256


async def test_public_projection_exact_inert_and_visibility(live_db):
    db, _ = live_db
    old = await db.fetchval("SELECT pg_get_viewdef('v_public_matches'::regclass)")
    async with app(db):
        await state(db)
        rows = await db.fetch("SELECT * FROM v_public_match_live")
        assert len(rows) == 1
        assert set(rows[0].keys()) == {"id", "tournament_id", "home_team_id", "home_team_name", "away_team_id", "away_team_name", "status", "home_score", "away_score", "is_provisional", "clock_segment_number", "clock_elapsed_seconds", "clock_state", "clock_observed_at"}
        assert rows[0]["clock_elapsed_seconds"] is None
        await db.execute("UPDATE matches SET status='suspended' WHERE id=$1", MATCH)
        assert (await db.fetchrow("SELECT * FROM v_public_match_live"))["status"] == "suspended"
    await db.execute("UPDATE organizations SET is_active=false WHERE id=$1", ORG)
    async with app(db):
        assert await db.fetchval("SELECT count(*) FROM v_public_match_live") == 0
    assert await db.fetchval("SELECT pg_get_viewdef('v_public_matches'::regclass)") == old


@pytest.mark.parametrize("incremental", [False, True])
async def test_clean_incremental_idempotent(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=55 if incremental else 56) as db:
        if incremental:
            await seed(db)
            await apply_migration(db, 56)
        await apply_migration(db, 56)
        assert await db.fetchval("SELECT count(*) FROM pg_class WHERE relname=ANY($1::text[])", list(TABLES)) == 4


@pytest.mark.parametrize('flow', [{'schema': 56}], indirect=True)
@pytest.mark.parametrize('name', ['MATCH_UPDATED', 'STANDINGS_UPDATED', 'MATCH_REPORT_RECTIFIED'])
async def test_legacy_authorization_concrete_versions(flow, name):
    await legacy_version_read(flow, name)


@pytest.mark.parametrize('name', ['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'])
async def test_legacy_authorization_operation(live_db, name):
    db, session = live_db
    async with app(db):
        event_data = json.dumps(dict(event_type=name, match_id=MATCH, tournament_id=TOURNAMENT))
        candidates = json.dumps([dict(user_id=USER, session_id=str(session))])
        rows = await db.fetch("SELECT * FROM authorize_realtime_recipients($1,$2::jsonb,$3::jsonb,$4)", ORG, candidates, event_data, NOW)
        assert rows[0]['decision'] == 'ALLOW'


@pytest.mark.parametrize('assigned', [False, True])
async def test_realtime_live_referee_and_multi_role(live_db, assigned):
    db, session = live_db
    await db.execute("UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='referee') WHERE name='Live owner'")
    if assigned:
        await db.execute("INSERT INTO match_officials(organization_id,match_id,organization_user_id,official_role) VALUES ($1,$2,$3,'main_referee')", ORG, MATCH, MEMBER)
    async with app(db):
        assert (await decisions(db, session))[0]['decision'] == ('ALLOW' if assigned else 'DENY')
    role = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'Organizational reader','["VIEW_MATCH_LIVE_DRAFT"]' FROM role_definitions WHERE code='operator' RETURNING id""", ORG)
    await db.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
    async with app(db):
        assert (await decisions(db, session))[0]['decision'] == 'ALLOW'


async def test_permissions_new_custom_and_view_operate_independent(live_db):
    db, session = live_db
    await db.execute("UPDATE roles SET permissions='[\"VIEW_MATCH_LIVE_DRAFT\"]' WHERE name='Live owner'")
    async with app(db):
        assert (await decisions(db, session))[0]['decision'] == 'ALLOW'
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(db):
            await state(db)
    await db.execute("UPDATE roles SET permissions='[\"OPERATE_MATCH_LIVE\"]' WHERE name='Live owner'")
    async with app(db):
        await state(db)
        assert (await decisions(db, session))[0]['decision'] == 'DENY'
    await db.execute("INSERT INTO roles(organization_id,name,permissions) VALUES ($1,'Custom','[\"CLOSE_MATCH_REPORT\"]')", ORG)
    await apply_migration(db, 56)
    assert json.loads(await db.fetchval("SELECT permissions FROM roles WHERE name='Custom'")) == ['CLOSE_MATCH_REPORT']
    permissions = await db.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'New referee',system_permissions FROM role_definitions WHERE code='referee' RETURNING permissions""", ORG)
    assert set(PERMISSIONS) <= set(json.loads(permissions))


async def test_live_integrity_closer_can_only_freeze(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
    await db.execute("UPDATE roles SET permissions='[\"VIEW_MATCH_LIVE_DRAFT\",\"CLOSE_MATCH_REPORT\"]' WHERE name='Live owner'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(db):
            await db.execute("UPDATE match_live_state SET home_score=10")
    async with app(db):
        await db.execute("UPDATE match_live_state SET frozen_at=now()")
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await db.execute("UPDATE match_live_state SET frozen_at=NULL")


async def test_live_integrity_running_closed_segment_and_suspended_state(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await db.execute("UPDATE match_live_state SET clock_state='running',segment_id=$1,clock_anchor_at=now()", SEGMENT_FIRST)
    async with app(db):
        await db.execute("UPDATE matches SET status='suspended' WHERE id=$1", MATCH)
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await db.execute("UPDATE match_live_state SET home_score=1")


@pytest.mark.parametrize('status', ['finished','cancelled','administrative_resolution'])
async def test_live_integrity_terminal_cannot_initialize(live_db, status):
    db, _ = live_db
    # A cancelled match exercises the real transition; confirmed fixtures cover the other terminals.
    if status != 'cancelled':
        await db.execute("ALTER TABLE matches DISABLE TRIGGER USER")
    try:
        await db.execute("UPDATE matches SET status=$1,result_confirmed=$2,resolution_type='regular',home_score_regular=0,away_score_regular=0,home_score=0,away_score=0 WHERE id=$3", status, status != 'cancelled', MATCH)
    finally:
        if status != 'cancelled':
            await db.execute("ALTER TABLE matches ENABLE TRIGGER USER")
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await state(db)


@pytest.mark.parametrize('table', TABLES)
async def test_rls_cross_tenant_insert_and_public_privileges(live_db, table):
    db, session = live_db
    async with app(db):
        await state(db)
    writers = {'match_live_state': lambda: state(db), 'match_live_events': lambda: event(db),
               'match_live_commands': lambda: command(db, session), 'match_live_reviews': lambda: review(db, session)}
    with pytest.raises(asyncpg.PostgresError):
        async with app(db, ORG.replace('31000000','32000000'), USER.replace('31000000','32000000')):
            await writers[table]()
    assert not await db.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_class c, LATERAL aclexplode(c.relacl) acl
        WHERE c.oid=$1::regclass AND acl.grantee=0)""", table)


async def test_events_table_limit_and_valid_catalog(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
        for event_type in ['goal','penalty_goal','yellow_card','red_card','foul']:
            await event(db, event_type=event_type)
        for _ in range(495):
            await event(db)
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await event(db)
    async with app(db):
        await db.execute("UPDATE match_live_events SET removed_at=now() WHERE id=(SELECT id FROM match_live_events LIMIT 1)")
        await event(db)
        assert await db.fetchval("SELECT count(*) FROM match_live_events WHERE removed_at IS NULL") == 500


@pytest.mark.parametrize('change', ['session','membership','user'])
async def test_realtime_live_revoked_current_identity(live_db, change):
    db, session = live_db
    if change == 'session':
        await db.execute("UPDATE user_sessions SET revoked_at=now() WHERE id=$1", session)
    elif change == 'membership':
        await db.execute("UPDATE organization_users SET is_active=false WHERE id=$1", MEMBER)
    else:
        await db.execute("UPDATE users SET is_active=false WHERE id=$1", USER)
    async with app(db):
        assert (await decisions(db, session))[0]['decision'] == 'DENY'


@pytest.mark.parametrize('change', ['hidden','version','cancelled'])
async def test_public_projection_excludes_invisible(live_db, change):
    db, _ = live_db
    async with app(db):
        await state(db)
        if change == 'cancelled':
            await db.execute("UPDATE match_live_state SET frozen_at=now()")
            await db.execute("UPDATE matches SET status='cancelled' WHERE id=$1", MATCH)
    if change == 'hidden':
        await db.execute("UPDATE tournaments SET status='archived' WHERE id=$1", TOURNAMENT)
    elif change == 'version':
        version = await db.fetchval("""INSERT INTO tournament_versions(organization_id,tournament_id,version_number,
            rules_config,phase_config,status,created_by_member_id)
            SELECT organization_id,tournament_id,2,rules_config,phase_config,'draft',created_by_member_id
            FROM tournament_versions WHERE id=(SELECT tournament_version_id FROM matches WHERE id=$1) RETURNING id""", MATCH)
        await db.execute("UPDATE tournament_versions SET status='archived' WHERE id=(SELECT tournament_version_id FROM matches WHERE id=$1)", MATCH)
        await db.execute("UPDATE tournament_versions SET status='published' WHERE id=$1", version)
        await db.execute("UPDATE tournaments SET published_version_id=$1 WHERE id=$2", version, TOURNAMENT)
    async with app(db):
        assert await db.fetchval("SELECT count(*) FROM v_public_match_live") == 0
    for view in ['v_match_live_public_selection','v_public_match_live']:
        assert 'security_barrier=true' in await db.fetchval("SELECT reloptions FROM pg_class WHERE oid=$1::regclass", view)


async def test_live_integrity_cannot_close_running_segment(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
        await db.execute("UPDATE match_segments SET status='active',minute_end=NULL WHERE id=$1", SEGMENT_FIRST)
        await db.execute("UPDATE match_live_state SET segment_id=$1,clock_state='running',clock_anchor_at=now()", SEGMENT_FIRST)
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await db.execute("UPDATE match_segments SET status='completed',minute_end=45 WHERE id=$1", SEGMENT_FIRST)


async def test_permissions_new_organization_uses_updated_definitions(live_db):
    db, _ = live_db
    org = await db.fetchval("SELECT create_organization_with_owner('New live tenant',$1,$2)", uuid4().hex, USER)
    rows = await db.fetch("""SELECT rd.code,r.permissions FROM roles r JOIN role_definitions rd ON rd.id=r.role_definition_id
        WHERE r.organization_id=$1""", org)
    assert len(rows) == 1
    for row in rows:
        for permission in PERMISSIONS:
            assert (permission in json.loads(row['permissions'])) == (row['code'] != 'viewer')


async def test_live_integrity_different_closer_can_freeze_with_own_identity(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
    other_user = USER.replace('31000000', '32000000')
    member = await db.fetchval("INSERT INTO organization_users(organization_id,user_id) VALUES ($1,$2) RETURNING id", ORG, other_user)
    await db.execute("""INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id)
        SELECT $1,$2,id FROM roles WHERE name='Live owner'""", ORG, member)
    await db.execute("UPDATE roles SET permissions='[\"VIEW_MATCH_LIVE_DRAFT\",\"CLOSE_MATCH_REPORT\"]' WHERE name='Live owner'")
    async with app(db, user=other_user):
        await db.execute("UPDATE match_live_state SET frozen_at=now(),updated_by_member_id=$1", member)
        assert await db.fetchval("SELECT updated_by_member_id FROM match_live_state") == member


async def test_events_table_rejects_null_red_card_type(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
    with pytest.raises(asyncpg.CheckViolationError):
        async with app(db):
            await event(db, event_type='red_card', metadata='{"red_card_type":null}')


async def test_events_table_accepts_substitution_and_own_goal(live_db):
    db, _ = live_db
    async with app(db):
        await state(db)
        await event(db, event_type='own_goal', beneficiary_team_id=TEAM_AWAY)
        await event(db, event_type='substitution', player_out_id=PLAYER_HOME_FIRST,
                    player_in_id=PLAYER_HOME_SECOND)
        assert await db.fetchval('SELECT count(*) FROM match_live_events') == 2


async def test_realtime_live_invalid_candidate_and_full_context_restoration(live_db):
    db, session = live_db
    async with app(db):
        keys = ['app.current_organization_id','app.current_user_id','app.rectification_authorization_id','app.sanction_authorization_id']
        before = {key: str(uuid4()) for key in keys}
        for key, value in before.items():
            await db.execute("SELECT set_config($1,$2,true)", key, value)
        candidates = json.dumps([dict(user_id=USER, session_id=str(session)), dict(user_id=USER, session_id='invalid'),
                                 dict(user_id='invalid', session_id=str(session))])
        rows = await db.fetch("SELECT * FROM authorize_realtime_recipients($1,$2::jsonb,$3::jsonb,$4)", ORG, candidates,
                              json.dumps(dict(event_type='MATCH_LIVE_UPDATED', scope='organization', match_id=MATCH, tournament_id=TOURNAMENT)), NOW)
        assert sorted(row['decision'] for row in rows) == ['ALLOW', 'INDETERMINATE']
        assert {key: await db.fetchval("SELECT current_setting($1,true)", key) for key in keys} == before


async def test_commands_reviews_compatible_with_existing_session_retention(live_db):
    db, session = live_db
    async with app(db):
        await state(db)
        await command(db, session)
        await review(db, session)
    await db.execute("UPDATE user_sessions SET expires_at='2025-01-01' WHERE id=$1", session)
    async with app(db):
        result = await db.fetchrow("SELECT * FROM purge_retained_records($1,$1,500)", NOW)
        assert result['sessions_deleted'] == 1
        assert await db.fetchval('SELECT session_id FROM match_live_commands') == session
        assert await db.fetchval('SELECT session_id FROM match_live_reviews') == session
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app(db):
            await review(db, session)
