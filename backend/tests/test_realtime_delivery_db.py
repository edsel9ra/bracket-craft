"""D1: HTTP read parity for the inert 035 authorization kernel."""

import asyncio
import json
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from migration_helpers import apply_migration, throwaway_database

from app.core.security import get_current_user_id
from app.core.realtime_authorization import RealtimeAuthorizer
from app.core import realtime_policy as policy
from app.core.tenancy import get_auth_context
from app.main import api
from test_migration_031 import MATCH, MEMBER, ORG, TOURNAMENT, USER
from test_rectification_effects import pending
from test_rectification_flow import decide
from test_rectification_flow import UNCONFIRMED
from test_rectification_flow import flow as flow
from test_realtime_policy import envelope, socket_metadata


EVALUATION_TIME = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


async def candidate(f, user=USER):
    session = uuid4()
    await f.admin.execute('INSERT INTO user_sessions (id,user_id,expires_at) VALUES ($1,$2,$3)',
        session, UUID(user), EVALUATION_TIME + timedelta(hours=1))
    return {'user_id': str(user), 'session_id': str(session)}


async def authorize(f, candidates, event=None, evaluation_time=EVALUATION_TIME, settings=None):
    event = event or {'event_type': 'MATCH_UPDATED', 'match_id': MATCH,
                      'tournament_id': MATCH.replace('000000000050', '000000000010')}
    async with f.engine.connect() as connection:
        await connection.execute(text('SET ROLE bracket_app'))
        await connection.commit()
        async with AsyncSession(bind=connection) as session:
            async with session.begin():
                for key, value in (settings or {}).items():
                    await session.execute(text('SELECT set_config(:key,:value,true)'), {'key': key, 'value': value})
                result = await session.execute(text('''SELECT * FROM public.authorize_realtime_recipients(
                    :org,CAST(:candidates AS JSONB),CAST(:event AS JSONB),:now)'''),
                    {'org': UUID(ORG), 'candidates': json.dumps(candidates), 'event': json.dumps(event),
                     'now': evaluation_time})
                decisions = {(str(row.user_id), str(row.session_id)): row.decision for row in result}
                for key, value in (settings or {}).items():
                    assert (await session.execute(text('SELECT current_setting(:key,true)'), {'key': key})).scalar_one() == value
                return decisions


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
@pytest.mark.parametrize('invalid', [None, 'revoked', 'expired', 'session_owner', 'user', 'organization', 'membership', 'roles'])
async def test_identity_fresh_real_membership_and_session(flow, invalid):
    f = flow
    principal = await candidate(f)
    if invalid == 'revoked':
        await f.admin.execute('UPDATE user_sessions SET revoked_at=$1 WHERE id=$2', EVALUATION_TIME, UUID(principal['session_id']))
    elif invalid == 'expired':
        await f.admin.execute('UPDATE user_sessions SET expires_at=$1 WHERE id=$2', EVALUATION_TIME, UUID(principal['session_id']))
    elif invalid == 'session_owner':
        principal['session_id'] = (await candidate(f, USER.replace('31000000', '32000000')))['session_id']
    elif invalid == 'user':
        await f.admin.execute('UPDATE users SET is_active=FALSE WHERE id=$1', USER)
    elif invalid == 'organization':
        await f.admin.execute('UPDATE organizations SET is_active=FALSE WHERE id=$1', ORG)
    elif invalid == 'membership':
        await f.admin.execute('UPDATE organization_users SET is_active=FALSE WHERE organization_id=$1', ORG)
    elif invalid == 'roles':
        await f.admin.execute('DELETE FROM organization_user_roles WHERE organization_id=$1', ORG)
    result = await authorize(f, [principal])
    assert result[(principal['user_id'], principal['session_id'])] == ('ALLOW' if invalid is None else 'DENY')


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
async def test_identity_ignores_exceptional_context_and_requires_real_membership(flow):
    principal = await candidate(flow)
    settings = {key: str(uuid4()) for key in ['app.current_user_id', 'app.current_organization_id',
                 'app.rectification_authorization_id', 'app.sanction_authorization_id']}
    result = await authorize(flow, [principal], settings=settings)
    assert result[(principal['user_id'], principal['session_id'])] == 'ALLOW'
    platform = str(uuid4())
    await flow.admin.execute("INSERT INTO users (id,email,full_name) VALUES ($1,'rt-gate-platform@example.test','Platform')", UUID(platform))
    await flow.admin.execute("INSERT INTO platform_admins (user_id,role_code) VALUES ($1,'platform_admin')", UUID(platform))
    principal = await candidate(flow, platform)
    result = await authorize(flow, [principal], settings=settings)
    assert result[(platform, principal['session_id'])] == 'DENY'


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
@pytest.mark.parametrize('change', [None, 'foreign_match', 'foreign_tournament', 'absent_match',
    'unknown', 'scope', 'field', 'missing', 'bad_uuid'])
async def test_resources_operation_and_closed_catalog(flow, change):
    event = {'event_type': 'MATCH_UPDATED', 'match_id': MATCH, 'tournament_id': TOURNAMENT}
    if change == 'foreign_match':
        event['match_id'] = MATCH.replace('31000000', '32000000')
    elif change == 'foreign_tournament':
        event['tournament_id'] = TOURNAMENT.replace('31000000', '32000000')
    elif change == 'absent_match':
        event['match_id'] = str(uuid4())
    elif change == 'unknown':
        event['event_type'] = 'VERIFICATION_OUTBOX_PROBE'
    elif change == 'scope':
        event['scope'] = 'public'
    elif change == 'field':
        event['evidence'] = 'excluded'
    elif change == 'missing':
        del event['match_id']
    elif change == 'bad_uuid':
        event['match_id'] = 'bad'
    principal = await candidate(flow)
    assert list((await authorize(flow, [principal], event)).values()) == ['ALLOW' if change is None else 'DENY']


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
@pytest.mark.parametrize('name', ['MATCH_UPDATED', 'STANDINGS_UPDATED', 'MATCH_REPORT_RECTIFIED'])
async def test_resources_rectification_requires_readable_concrete_version(flow, name):
    request = await pending(flow)
    response = await decide(flow, request)
    assert response.status_code == 200
    version = str(await flow.admin.fetchval('SELECT id FROM match_report_versions WHERE match_id=$1', MATCH))
    event = {'event_type': name, 'scope': 'organization', 'match_id': MATCH,
             'tournament_id': TOURNAMENT, 'version_id': version}
    principal = await candidate(flow)
    assert list((await authorize(flow, [principal], event)).values()) == ['ALLOW']
    for patch in [{'version_id': str(uuid4())}, {'match_id': UNCONFIRMED},
                  {'match_id': MATCH.replace('31000000', '32000000')},
                  {'tournament_id': str(uuid4())}, {'version_id': None}, {'scope': None}]:
        assert list((await authorize(flow, [principal], {**event, **patch})).values()) == ['DENY']
    await flow.admin.execute('ALTER TABLE matches DISABLE TRIGGER ALL')
    try:
        await flow.admin.execute("UPDATE matches SET result_confirmed=FALSE,status='scheduled' WHERE id=$1", MATCH)
        assert list((await authorize(flow, [principal], event)).values()) == ['DENY']
    finally:
        await flow.admin.execute('ALTER TABLE matches ENABLE TRIGGER ALL')


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
@pytest.mark.parametrize('name,private', [
    ('MATCH_CLOSED', False), ('MATCH_UPDATED', False), ('STANDINGS_UPDATED', False),
    ('MATCH_UPDATED', True), ('STANDINGS_UPDATED', True), ('MATCH_REPORT_RECTIFIED', True),
])
async def test_parity_http_and_gate_preserve_effective_roles_and_irrelevant_officials(http_reader, name, private):
    f = http_reader
    event = {'event_type': name, 'match_id': MATCH, 'tournament_id': TOURNAMENT}
    if private:
        request = await pending(f)
        f.reader_id = f.context.user_id
        assert (await decide(f, request)).status_code == 200
        event.update(scope='organization', version_id=str(await f.admin.fetchval(
            'SELECT id FROM match_report_versions WHERE match_id=$1', MATCH)))
        f.reader_id = UUID(USER)
    principal = await candidate(f)
    await f.admin.execute("UPDATE roles SET permissions='[]'::jsonb WHERE organization_id=$1", ORG)

    async def parity(allowed):
        path = 'report-versions/2' if private else 'operation'
        response = await f.client.get(f'/api/v1/matches/{MATCH}/{path}')
        assert response.status_code == (200 if allowed else 403)
        assert list((await authorize(f, [principal], event)).values()) == ['ALLOW' if allowed else 'DENY']

    await parity(True)
    await f.admin.execute("""INSERT INTO match_officials
        (organization_id,match_id,organization_user_id,official_role)
        VALUES ($1,$2,$3,'main_referee')""", ORG, MATCH, MEMBER)
    await parity(True)
    await f.admin.execute('DELETE FROM match_officials WHERE organization_id=$1', ORG)
    await parity(True)
    role = await f.admin.fetchval("""INSERT INTO roles (organization_id,role_definition_id,name,permissions)
        SELECT $1,id,'Second reader','[]'::jsonb FROM role_definitions WHERE code='operator' RETURNING id""", ORG)
    await f.admin.execute('INSERT INTO organization_user_roles (organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)', ORG, MEMBER, role)
    await parity(True)
    await f.admin.execute('DELETE FROM organization_user_roles WHERE organization_user_id=$1 AND role_id<>$2', MEMBER, role)
    await parity(True)
    await f.admin.execute('DELETE FROM organization_user_roles WHERE organization_user_id=$1', MEMBER)
    await parity(False)
    await f.admin.execute('INSERT INTO organization_user_roles (organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)', ORG, MEMBER, role)
    await parity(True)


def real_authorizer(f, snapshot_hook=None):
    class SnapshotSession:
        def __init__(self, session):
            self.session = session

        def begin(self):
            return self.session.begin()

        async def execute(self, statement, *args, **kwargs):
            result = await self.session.execute(statement, *args, **kwargs)
            if str(statement) == 'SELECT statement_timestamp()' and snapshot_hook is not None:
                isolation = (await self.session.execute(text('SHOW transaction_isolation'))).scalar_one()
                assert isolation == 'repeatable read'
                await snapshot_hook()
            return result

    @asynccontextmanager
    async def factory():
        async with f.engine.connect() as connection:
            await connection.execute(text('SET ROLE bracket_app'))
            await connection.commit()
            async with AsyncSession(bind=connection) as session:
                yield SnapshotSession(session)
    return RealtimeAuthorizer(factory, lambda: datetime.now(timezone.utc))


async def delivery_inputs(f):
    principal = await candidate(f)
    await f.admin.execute("UPDATE user_sessions SET expires_at=CURRENT_TIMESTAMP + INTERVAL '1 hour' WHERE id=$1", UUID(principal['session_id']))
    data = envelope()
    data.update(organization_id=ORG)
    data['payload'].update(match_id=MATCH, tournament_id=TOURNAMENT)
    event = policy.classify_organization_event(data)
    metadata = socket_metadata(ORG, USER, principal['session_id'], jwt_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    return event, policy.group_recipients({'sid': metadata}, UUID(ORG))[0]


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
@pytest.mark.parametrize('withdrawal', ['session', 'expiry', 'membership', 'roles', 'user', 'organization', 'irrelevant_permission', 'irrelevant_official'])
async def test_cutoff_committed_before_next_batch_and_preapproved_transit(flow, withdrawal):
    event, principals = await delivery_inputs(flow)
    started, proceed = asyncio.Event(), asyncio.Event()

    async def snapshot_barrier():
        started.set()
        await asyncio.wait_for(proceed.wait(), timeout=10)

    old_evaluation = asyncio.create_task(real_authorizer(flow, snapshot_barrier).evaluate_batch(event, principals))
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        async with flow.admin.transaction():
            if withdrawal == 'session':
                await flow.admin.execute('UPDATE user_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE id=$1', principals[0].session_id)
            elif withdrawal == 'expiry':
                await flow.admin.execute("UPDATE user_sessions SET expires_at=CURRENT_TIMESTAMP - INTERVAL '1 second' WHERE id=$1", principals[0].session_id)
            elif withdrawal == 'membership':
                await flow.admin.execute('UPDATE organization_users SET is_active=FALSE WHERE id=$1', MEMBER)
            elif withdrawal == 'roles':
                await flow.admin.execute('DELETE FROM organization_user_roles WHERE organization_user_id=$1', MEMBER)
            elif withdrawal == 'user':
                await flow.admin.execute('UPDATE users SET is_active=FALSE WHERE id=$1', USER)
            elif withdrawal == 'organization':
                await flow.admin.execute('UPDATE organizations SET is_active=FALSE WHERE id=$1', ORG)
            elif withdrawal == 'irrelevant_permission':
                await flow.admin.execute("UPDATE roles SET permissions='[]'::jsonb WHERE organization_id=$1", ORG)
            elif withdrawal == 'irrelevant_official':
                await flow.admin.execute('DELETE FROM match_officials WHERE organization_id=$1', ORG)
        proceed.set()
        approved_before_commit = await asyncio.wait_for(old_evaluation, timeout=10)
    finally:
        proceed.set()
        if not old_evaluation.done():
            old_evaluation.cancel()
            await asyncio.gather(old_evaluation, return_exceptions=True)
    assert approved_before_commit[0].decision == policy.Decision.ALLOW
    current = await real_authorizer(flow).evaluate_batch(event, principals)
    expected = 'ALLOW' if withdrawal.startswith('irrelevant_') else 'DENY'
    assert current[0].decision == expected
    assert current[0].evaluation_time > approved_before_commit[0].evaluation_time
    if withdrawal == 'membership':
        await flow.admin.execute('UPDATE organization_users SET is_active=TRUE WHERE id=$1', MEMBER)
        assert (await real_authorizer(flow).evaluate_batch(event, principals))[0].decision == 'ALLOW'


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
async def test_migration_partial_malformed_candidate_does_not_reuse_previous_key(flow):
    first, second = await candidate(flow), await candidate(flow)
    result = await authorize(flow, [first, {**first, 'session_id': 'bad'}, second])
    assert result[(first['user_id'], first['session_id'])] == 'ALLOW'
    assert result[(second['user_id'], second['session_id'])] == 'ALLOW'


@pytest.mark.parametrize('incremental', [False, True])
async def test_migration_invoker_grants_and_unchanged_policies(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=54 if incremental else 55) as db:
        before = await db.fetch('SELECT schemaname,tablename,policyname,qual,with_check FROM pg_policies ORDER BY 1,2,3')
        force_before = await db.fetch("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY relname")
        if incremental:
            await apply_migration(db, 55)
        function = 'authorize_realtime_recipients(uuid,jsonb,jsonb,timestamp with time zone)'
        assert not await db.fetchval('SELECT prosecdef FROM pg_proc WHERE oid=$1::regprocedure', function)
        assert await db.fetchval("SELECT has_function_privilege('bracket_app',$1,'EXECUTE')", function)
        assert not await db.fetchval('''SELECT EXISTS (SELECT 1 FROM pg_proc p,
            LATERAL aclexplode(p.proacl) a WHERE p.oid=$1::regprocedure AND a.grantee=0)''', function)
        assert not await db.fetchval("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname='bracket_app'")
        assert before == await db.fetch('SELECT schemaname,tablename,policyname,qual,with_check FROM pg_policies ORDER BY 1,2,3')
        assert force_before == await db.fetch("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace ORDER BY relname")
        async with db.transaction():
            await db.execute('SET LOCAL ROLE bracket_app')
            assert await db.fetch('SELECT * FROM authorize_realtime_recipients($1,\'[]\',\'{}\',$2)', UUID(ORG), EVALUATION_TIME) == []
        async with db.transaction():
            await db.execute('SET LOCAL ROLE bracket_app')
            assert all([await db.fetchval('SELECT current_setting($1,true)', name) in (None, '') for name in
                ['app.current_user_id', 'app.current_organization_id', 'app.rectification_authorization_id', 'app.sanction_authorization_id']])


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
@pytest.mark.parametrize('principals,users', [(100, 100), (100, 1), (257, 1)])
async def test_batching_sql_work_is_per_user_not_tab_or_session(flow, principals, users):
    f = flow
    function = 'authorize_realtime_recipients(uuid,jsonb,jsonb,timestamp with time zone)'
    definition = await f.admin.fetchval('SELECT pg_get_functiondef($1::regprocedure)', function)
    for query, label in [
        ('SELECT public.fn_verify_user_org_membership', 'member'),
        ('SELECT EXISTS (\n                    SELECT 1 FROM public.matches', 'resource'),
        ('SELECT CASE WHEN member_valid', 'sessions'),
        ('SELECT COALESCE(array_agg', 'sessions'),
    ]:
        definition = definition.replace(query, f"RAISE NOTICE 'F8_PROFILE {label}';\n                " + query)
    await f.admin.execute(definition)
    counts = Counter()

    def notice(connection, message):
        if message.message.startswith('F8_PROFILE '):
            counts[message.message.split()[-1]] += 1

    f.admin.add_log_listener(notice)
    identities = [USER] + [str(uuid4()) for _ in range(users - 1)]
    await f.admin.execute('''WITH added_users AS (
        INSERT INTO users (id,email,password_hash,full_name)
        SELECT id,id::text||'@example.test','hash','Reader' FROM unnest($1::uuid[]) id RETURNING id
    ), added_members AS (
        INSERT INTO organization_users (organization_id,user_id)
        SELECT $2,id FROM added_users RETURNING id
    ) INSERT INTO organization_user_roles (organization_id,organization_user_id,role_id)
        SELECT $2,id,(SELECT id FROM roles WHERE organization_id=$2 LIMIT 1) FROM added_members''',
        [UUID(value) for value in identities[1:]], UUID(ORG))
    candidates = [await candidate(f, identities[i % users]) for i in range(principals)]
    event = {'event_type': 'MATCH_UPDATED', 'match_id': MATCH, 'tournament_id': TOURNAMENT}
    started = perf_counter()
    try:
        for start in range(0, principals, 256):
            async with f.admin.transaction():
                await f.admin.execute('SET LOCAL ROLE bracket_app')
                result = await f.admin.fetch('SELECT * FROM authorize_realtime_recipients($1,$2::jsonb,$3::jsonb,$4)',
                    UUID(ORG), json.dumps(candidates[start:start + 256]), json.dumps(event), EVALUATION_TIME)
                assert len(result) == min(256, principals - start)
                assert all(row['decision'] == 'ALLOW' for row in result)
        await f.admin.execute('SELECT 1')
    finally:
        f.admin.remove_log_listener(notice)
    expected_work = sum(len({row['user_id'] for row in candidates[start:start + 256]})
                        for start in range(0, principals, 256))
    print(f'L1 principals={principals} users={users} calls={(principals + 255)//256} blocks={dict(counts)} seconds={perf_counter()-started:.4f}')
    assert counts == {'member': expected_work, 'resource': expected_work, 'sessions': expected_work}


@pytest.mark.parametrize('flow', [{'schema': 55}], indirect=True)
async def test_snapshot_adapter_reads_primary_with_real_application_role(flow):
    principal = await candidate(flow)
    await flow.admin.execute("UPDATE user_sessions SET expires_at=CURRENT_TIMESTAMP + INTERVAL '1 hour' WHERE id=$1", UUID(principal['session_id']))
    data = envelope()
    data.update(organization_id=ORG)
    data['payload'].update(match_id=MATCH, tournament_id=TOURNAMENT)
    event = policy.classify_organization_event(data)
    metadata = socket_metadata(ORG, USER, principal['session_id'], jwt_expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    batch = policy.group_recipients({'sid': metadata}, UUID(ORG))[0]
    result = await real_authorizer(flow).evaluate_batch(event, batch)
    assert len(result) == 1 and result[0].decision == policy.Decision.ALLOW


@pytest.fixture
async def http_reader(flow):
    api.dependency_overrides.pop(get_auth_context)

    async def identity():
        return flow.reader_id

    flow.reader_id = UUID(USER)
    api.dependency_overrides[get_current_user_id] = identity
    flow.client.headers['X-Organization-ID'] = ORG
    yield flow


@pytest.mark.parametrize('flow', [{'schema': 54}], indirect=True)
@pytest.mark.parametrize('roles', ['reader', 'multirole'])
async def test_http_baseline_member_reads_without_write_permission_or_assignment(http_reader, roles):
    f = http_reader
    await f.admin.execute("UPDATE roles SET permissions='[]'::jsonb WHERE organization_id=$1", ORG)
    await f.admin.execute('DELETE FROM match_officials WHERE organization_id=$1', ORG)
    if roles == 'multirole':
        await f.admin.execute("""WITH added AS (
            INSERT INTO roles (organization_id, role_definition_id, name, permissions)
            SELECT $1, id, 'Second reader', '[]'::jsonb FROM role_definitions WHERE code='operator'
            RETURNING id,organization_id
        ) INSERT INTO organization_user_roles (organization_id,organization_user_id,role_id)
          SELECT a.organization_id,ou.id,a.id FROM added a JOIN organization_users ou
          ON ou.organization_id=a.organization_id WHERE ou.user_id=$2""", ORG, USER)
    for suffix in ['operation', 'report-versions', 'report-versions/1']:
        response = await f.client.get(f'/api/v1/matches/{MATCH}/{suffix}')
        assert response.status_code == 200
    versions = await f.client.get(f'/api/v1/matches/{MATCH}/report-versions')
    assert len(versions.json()) == 1


@pytest.mark.parametrize('flow', [{'schema': 54}], indirect=True)
async def test_http_baseline_foreign_absent_and_unconfirmed_resources(http_reader):
    f = http_reader
    for suffix in ['operation', 'report-versions', 'report-versions/1']:
        foreign = await f.client.get(f"/api/v1/matches/{MATCH.replace('31000000', '32000000')}/{suffix}")
        absent = await f.client.get(f'/api/v1/matches/{uuid4()}/{suffix}')
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()
    assert (await f.client.get(f'/api/v1/matches/{UNCONFIRMED}/report-versions')).status_code == 409
    assert (await f.client.get(f'/api/v1/matches/{UNCONFIRMED}/operation')).status_code == 200
    assert (await f.client.get(f'/api/v1/matches/{MATCH}/report-versions/99')).status_code == 404


@pytest.mark.parametrize('flow', [{'schema': 54}], indirect=True)
async def test_http_baseline_platform_without_membership_and_member_without_roles(http_reader):
    f = http_reader
    platform = uuid4()
    await f.admin.execute("INSERT INTO users (id,email,full_name) VALUES ($1,'rt-platform@example.test','Platform')", platform)
    await f.admin.execute("INSERT INTO platform_admins (user_id,role_code) VALUES ($1,'platform_admin')", platform)
    f.reader_id = platform
    for suffix in ['operation', 'report-versions', 'report-versions/1']:
        assert (await f.client.get(f'/api/v1/matches/{MATCH}/{suffix}')).status_code == 403
    f.reader_id = UUID(USER)
    await f.admin.execute('DELETE FROM organization_user_roles WHERE organization_id=$1', ORG)
    for suffix in ['operation', 'report-versions']:
        assert (await f.client.get(f'/api/v1/matches/{MATCH}/{suffix}')).status_code == 403
