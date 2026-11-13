"""Development-only ASGI fixture; never imported by the application entrypoint."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from sqlalchemy import text

from app.core.config import DEVELOPMENT_ENVS, get_settings


if get_settings().app_env.lower().strip() not in DEVELOPMENT_ENVS:
    raise RuntimeError('El arnés E2E no se puede ejecutar fuera de desarrollo')

from app import main  # noqa: E402
from app.core.database import SessionFactory, set_rls_context  # noqa: E402
from app.core.outbox import enqueue_outbox  # noqa: E402
from app.core.security import create_access_token, decode_access_token_claims  # noqa: E402
from scripts import seed_demo as seed  # noqa: E402


DIRECTORY = Path('/harness')
tenants = {}
tenant_states = {}
mode = {'authorization_failure': False, 'revalidation_failure': False, 'pause_maintenance': False}
barrier = None
paused = None
release = asyncio.Event()
allow_connect = asyncio.Event()
allow_connect.set()
connect_socket = main.connect
authorizer = main.private_delivery.authorizer
validate_context = main.private_delivery.validate_context
maintenance = main.revalidate_socket_sessions_cycle
emit_domain_event = main.emit_domain_event
delivered = []


async def deliver(event):
    await emit_domain_event(event)
    delivered.append(str(event.event_id))
    del delivered[:-256]


async def pause_evaluation(event, phase):
    global paused
    if barrier == (str(event.event_id), phase):
        paused = str(event.event_id)
        await release.wait()
        paused = None


class AuthorizationFixture:
    async def evaluate_batch(self, event, principals):
        await pause_evaluation(event, 'before')
        if mode['authorization_failure']:
            raise RuntimeError('E2E private authorization unavailable')
        results = await authorizer.evaluate_batch(event, principals)
        await pause_evaluation(event, 'after')
        return results


async def revalidate(sessions):
    if mode['revalidation_failure']:
        raise RuntimeError('E2E private revalidation unavailable')
    return await validate_context(sessions)


async def cycle():
    if not mode['pause_maintenance']:
        await maintenance()


async def connect_socket_after_barrier(sid, environ, auth):
    await allow_connect.wait()
    return await connect_socket(sid, environ, auth)


async def create_tenant():
    identity = uuid4().hex
    email = f'f8-owner-{identity}@bracketcraft.dev'
    reader_email = f'f8-reader-{identity}@bracketcraft.dev'
    async with SessionFactory() as db:
        async with db.begin():
            owner = await seed._ensure_demo_user(db, email=email)
            reader = await seed._ensure_demo_user(db, email=reader_email)
            await set_rls_context(db, None, owner)
            org = (await db.execute(text('SELECT create_organization_with_owner(:name,:slug,:user)'),
                {'name': f'F8 {identity}', 'slug': f'f8-{identity}', 'user': str(owner)})).scalar_one()
            await set_rls_context(db, org, owner)
            member = (await db.execute(text('''INSERT INTO organization_users (organization_id,user_id)
                VALUES (:org,:user) RETURNING id'''), {'org': org, 'user': reader})).scalar_one()
            role = (await db.execute(text('''INSERT INTO roles (organization_id,role_definition_id,name,permissions)
                SELECT :org,id,'F8 reader',system_permissions FROM role_definitions WHERE code='administrator'
                RETURNING id'''), {'org': org})).scalar_one()
            await db.execute(text('''INSERT INTO organization_user_roles
                (organization_id,organization_user_id,role_id) VALUES (:org,:member,:role)'''),
                {'org': org, 'member': member, 'role': role})
        async with db.begin():
            state = await seed._ensure_structure(db, owner, org, get_settings().player_data_key)
        match = seed.MATCH_SPECS[0]
        async with db.begin():
            segment = await seed._prepare_quarterfinal(db, state, match)
        await seed._close_quarterfinal(db, state, match, segment)
        async with db.begin():
            await seed._mark_tournament_live(db, state)
    fixture = {'organization_id': str(org), 'tournament_id': str(state.tournament_id),
               'match_id': str(state.matches[match.code]), 'open_match_id': str(state.matches[seed.MATCH_SPECS[1].code]),
               'owner_id': str(owner), 'reader_id': str(reader), 'member_id': str(member), 'role_id': str(role),
               'owner_email': email, 'reader_email': reader_email, 'password': seed.DEMO_USER_PASSWORD}
    tenants[str(org)] = fixture
    tenant_states[str(org)] = state
    return fixture


async def command(data):
    global barrier
    action = data['action']
    if action == 'bootstrap':
        return [await create_tenant(), await create_tenant()]
    if action == 'mode':
        for name in mode:
            if name in data:
                mode[name] = data[name] is True
        return dict(mode)
    if action == 'release':
        release.set()
        allow_connect.set()
        barrier = None
        return {}
    if action == 'release_connect':
        allow_connect.set()
        return {}
    if action == 'wait_expiry':
        await asyncio.sleep(max(0, data['deadline'] - datetime.now(timezone.utc).timestamp() + 0.05))
        return {}
    if action == 'drop_transport':
        allow_connect.clear()
        engine_sids = [main.sio.manager.eio_sid_from_sid(sid, '/') for sid in main.connected_socket_sessions]
        engine_sids = [sid for sid in engine_sids if sid]
        print(f'test-only drop_transport engine_sid count: {len(engine_sids)}', flush=True)
        for engine_sid in engine_sids:
            await main.sio.environ[engine_sid]['asgi.send']({'type': 'websocket.close', 'code': 1012})
        return {'engine_sids': len(engine_sids)}
    if action == 'probe':
        return {'paused': paused, 'delivered': list(delivered), 'connections': len(main.connected_socket_sessions),
                'suspended': len(main.private_delivery.states)}
    if action == 'stream_gap':
        event_id = str(uuid4())
        async with main.Redis.from_url(main.settings.redis_url, decode_responses=True) as redis:
            if data['kind'] == 'trim':
                await redis.xadd(main.OUTBOX_STREAM, {'event': json.dumps({'event_id': event_id,
                    'organization_id': str(uuid4()), 'event_type': 'UNKNOWN', 'payload': {}})})
                await redis.xtrim(main.OUTBOX_STREAM, maxlen=1, approximate=False)
            elif data['kind'] == 'reset':
                await redis.delete(main.OUTBOX_STREAM)
            else:
                raise ValueError('unknown stream gap')
        return {'event_id': event_id}
    if action == 'archive':
        async with SessionFactory() as db:
            async with db.begin():
                owners = (await db.execute(text("""SELECT id FROM users
                    WHERE email LIKE 'f8-owner-%@bracketcraft.dev' OR email LIKE 'f8-owner-%@example.test'"""))).scalars().all()
                for owner in owners:
                    await set_rls_context(db, None, owner)
                    organizations = (await db.execute(text("SELECT id FROM list_user_organizations() WHERE slug LIKE 'f8-%'"))).scalars().all()
                    for org in organizations:
                        await set_rls_context(db, org, owner)
                        await db.execute(text("UPDATE tournaments SET status='archived' WHERE organization_id=:org"), {'org': org})
        return {}
    fixture = tenants[data['organization_id']]
    async with SessionFactory() as db:
        async with db.begin():
            await set_rls_context(db, UUID(fixture['organization_id']), UUID(fixture['owner_id']))
            values = {'org': fixture['organization_id'], 'user': fixture['reader_id'],
                      'member': fixture['member_id'], 'role': fixture['role_id']}
            if action == 'short_token':
                await set_rls_context(db, UUID(fixture['organization_id']), UUID(fixture['reader_id']))
                session_id = (await db.execute(text('''SELECT id FROM user_sessions
                    WHERE user_id=:user AND revoked_at IS NULL'''), values)).scalar_one()
                claims = decode_access_token_claims(create_access_token(UUID(fixture['reader_id']), session_id))
                claims['exp'] = int(datetime.now(timezone.utc).timestamp()) + 15
                settings = get_settings()
                return {'token': jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm),
                        'deadline': claims['exp']}
            if action == 'prepare_open':
                await seed._prepare_quarterfinal(db, tenant_states[fixture['organization_id']], seed.MATCH_SPECS[1])
                return {}
            if action == 'inject':
                from app.workers.outbox import publish_stream_event

                event_id = data.get('event_id', str(uuid4()))
                async with main.Redis.from_url(main.settings.redis_url, decode_responses=True) as redis:
                    await publish_stream_event(redis, {'id': event_id, 'organization_id': fixture['organization_id'],
                        'event_type': data.get('event_type', 'MATCH_UPDATED'),
                        'payload': data.get('payload', {'match_id': fixture['match_id'], 'tournament_id': fixture['tournament_id']})})
                return {'event_id': event_id}
            if action == 'outbox_status':
                return (await db.execute(text('SELECT status FROM outbox_events WHERE id=:id'),
                    {'id': data['event_id']})).scalar_one()
            if action == 'link_owner':
                other = tenants[data['other_organization_id']]
                member = (await db.execute(text('''INSERT INTO organization_users (organization_id,user_id)
                    VALUES (:org,:user) RETURNING id'''), {'org': fixture['organization_id'],
                    'user': other['owner_id']})).scalar_one()
                await db.execute(text('''INSERT INTO organization_user_roles
                    (organization_id,organization_user_id,role_id) VALUES (:org,:member,:role)'''),
                    {**values, 'member': str(member)})
                return {}
            if action == 'secondary_role':
                role = (await db.execute(text('''INSERT INTO roles (organization_id,role_definition_id,name,permissions)
                    SELECT :org,id,'F8 secondary','[]'::jsonb FROM role_definitions WHERE code='viewer'
                    RETURNING id'''), values)).scalar_one()
                await db.execute(text('''INSERT INTO organization_user_roles
                    (organization_id,organization_user_id,role_id) VALUES (:org,:member,:role)'''),
                    {**values, 'role': str(role)})
                return {}
            if action == 'assign_official':
                await db.execute(text('''INSERT INTO match_officials
                    (organization_id,match_id,organization_user_id,official_role)
                    VALUES (:org,:match,:member,'assistant_referee_1')'''), {**values, 'match': fixture['match_id']})
                return {}
            if action == 'restore':
                if data['kind'] == 'roles':
                    await db.execute(text('''INSERT INTO organization_user_roles
                        (organization_id,organization_user_id,role_id) VALUES (:org,:member,:role)'''), values)
                elif data['kind'] == 'membership':
                    await db.execute(text('UPDATE organization_users SET is_active=TRUE WHERE id=:member'), values)
                else:
                    raise ValueError('a revoked session cannot be restored')
                return {'committed': True}
            if action == 'withdraw':
                kind = data['kind']
                if kind == 'session':
                    await set_rls_context(db, UUID(fixture['organization_id']), UUID(fixture['reader_id']))
                    await db.execute(text('UPDATE user_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE user_id=:user'), values)
                elif kind == 'membership':
                    await db.execute(text('UPDATE organization_users SET is_active=FALSE WHERE id=:member'), values)
                elif kind == 'roles':
                    await db.execute(text('DELETE FROM organization_user_roles WHERE organization_user_id=:member'), values)
                elif kind == 'permission':
                    await db.execute(text("UPDATE roles SET permissions='[]'::jsonb WHERE id=:role"), values)
                elif kind == 'official':
                    await db.execute(text('DELETE FROM match_officials WHERE organization_user_id=:member'), values)
                else:
                    raise ValueError('unknown withdrawal')
                return {'committed': True}
            if action == 'publish':
                payload = {'match_id': fixture['open_match_id'] if data.get('open') else fixture['match_id'],
                           'tournament_id': fixture['tournament_id']}
                if data.get('private'):
                    version = (await db.execute(text('''SELECT id FROM match_report_versions
                        WHERE match_id=:match ORDER BY version_number DESC LIMIT 1'''),
                        {'match': fixture['match_id']})).scalar_one()
                    payload.update(scope='organization', version_id=str(version))
                event_type = data.get('event_type', 'MATCH_UPDATED')
                event_id = await enqueue_outbox(db, UUID(fixture['organization_id']), event_type, payload)
                if data.get('barrier') in {'before', 'after'}:
                    release.clear()
                    barrier = (str(event_id), data['barrier'])
                return {'event_id': str(event_id)}
    raise ValueError('unknown command')


async def control_loop():
    while True:
        for path in sorted(DIRECTORY.glob('request-*.json')):
            destination = DIRECTORY / path.name.replace('request-', 'response-')
            try:
                data = json.loads(path.read_text())
                path.unlink()
                result = {'result': await command(data)}
            except Exception as exc:
                result = {'error': type(exc).__name__}
            temporary = destination.with_suffix('.pending')
            temporary.write_text(json.dumps(result))
            temporary.replace(destination)
        await asyncio.sleep(0.025)


original_lifespan = main.api.router.lifespan_context


@asynccontextmanager
async def lifespan(app):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    main.private_delivery.authorizer = AuthorizationFixture()
    main.private_delivery.validate_context = revalidate
    main.revalidate_socket_sessions_cycle = cycle
    main.emit_domain_event = deliver
    main.sio.on('connect', connect_socket_after_barrier)
    main.SOCKET_REVALIDATION_SECONDS = 2
    main.settings.auth_login_rate_limit = 1000
    async with original_lifespan(app):
        task = asyncio.create_task(control_loop())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


main.api.router.lifespan_context = lifespan
app = main.app
