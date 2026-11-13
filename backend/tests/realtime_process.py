"""Test-only independent Uvicorn processes, real PostgreSQL/Redis and wire clients."""

import asyncio
import json
import multiprocessing
import os
import resource
import socket
from collections import Counter, deque
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID, uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from websockets.asyncio.client import connect

from app.core.config import DEVELOPMENT_ENVS, get_settings
from test_migration_031 import MATCH, MEMBER, ORG, TOURNAMENT, USER


def run_api(connection, listener, environment, stream):
    os.environ.update(environment)
    if os.environ['APP_ENV'] not in DEVELOPMENT_ENVS:
        raise RuntimeError('The process harness is development-only')
    asyncio.run(serve(connection, listener, stream))


async def serve(connection, listener, stream):
    import uvicorn
    from app import main
    from app.core.database import engine
    from app.core.realtime_authorization import RealtimeAuthorizer

    main.OUTBOX_STREAM = stream
    main.SOCKET_REVALIDATION_SECONDS = 3600
    modes = {'fail': False, 'delay': 0, 'control_fail': False, 'emit_fail': False}
    gate_id, phase = None, 'before'
    reached, released, ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
    completed = deque(maxlen=256)
    changed = asyncio.Condition()
    counts = Counter()
    batches, durations = deque(maxlen=256), deque(maxlen=256)

    def notice(_connection, message):
        if message.message.startswith('F8_PROFILE '):
            counts[message.message.split()[-1]] += 1

    @event.listens_for(engine.sync_engine, 'connect')
    def attach(dbapi, _record):
        async def install(driver):
            driver.add_log_listener(notice)
        dbapi.run_async(install)

    class Session(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if 'public.authorize_realtime_recipients(' in str(statement):
                if modes['delay']:
                    await super().execute(text('SELECT pg_sleep(:delay)'), {'delay': modes['delay']})
                if modes['fail']:
                    await super().execute(text('SELECT 1/0'))
            return await super().execute(statement, *args, **kwargs)

    real = RealtimeAuthorizer(async_sessionmaker(engine, class_=Session), main.private_delivery.clock)

    class ObservedAuthorizer:
        async def evaluate_batch(self, envelope, principals):
            if str(envelope.event_id) == gate_id and phase == 'before':
                reached.set()
                await released.wait()
            batches.append(len(principals))
            counts['calls'] += 1
            started = perf_counter()
            result = await real.evaluate_batch(envelope, principals)
            durations.append(perf_counter() - started)
            if str(envelope.event_id) == gate_id and phase == 'after':
                reached.set()
                await released.wait()
            return result

    original_emit = main.emit_domain_event
    original_cycle = main.relay_cycle
    original_validate = main.private_delivery.validate_context
    original_control_emit = main.private_delivery.emit

    async def observed_emit(envelope):
        await original_emit(envelope)
        async with changed:
            completed.append(str(envelope.event_id))
            changed.notify_all()

    async def observed_cycle(*args, **kwargs):
        result = await original_cycle(*args, **kwargs)
        ready.set()
        return result

    async def validate(sessions):
        if modes['control_fail']:
            async with main.SessionFactory() as db:
                await db.execute(text('SELECT 1/0'))
        return await original_validate(sessions)

    async def emit(name, payload, *, to):
        if modes['emit_fail'] and name == 'RESYNC':
            raise ConnectionError('test control transport failure')
        await original_control_emit(name, payload, to=to)

    main.private_delivery.authorizer = ObservedAuthorizer()
    main.private_delivery.validate_context = validate
    main.private_delivery.emit = emit
    main.emit_domain_event = observed_emit
    main.relay_cycle = observed_cycle
    server = uvicorn.Server(uvicorn.Config(main.app, log_level='critical', access_log=False))

    async def controls():
        nonlocal gate_id, phase
        while True:
            data = await asyncio.to_thread(connection.recv)
            action = data['action']
            try:
                if action == 'ready':
                    await asyncio.wait_for(ready.wait(), 30)
                    while not server.started:
                        await asyncio.sleep(0.01)
                    result = {'pid': os.getpid()}
                elif action == 'gate':
                    gate_id, phase = data['event_id'], data['phase']
                    reached.clear()
                    released.clear()
                    result = {}
                elif action == 'paused':
                    await asyncio.wait_for(reached.wait(), 30)
                    result = {}
                elif action == 'release':
                    released.set()
                    gate_id = None
                    result = {}
                elif action == 'processed':
                    async with changed:
                        await asyncio.wait_for(changed.wait_for(lambda: data['event_id'] in completed), 30)
                    result = {}
                elif action == 'mode':
                    modes.update(data['values'])
                    result = {}
                elif action == 'recover':
                    await main.private_delivery.recover()
                    result = {}
                elif action == 'fence':
                    for sid in list(main.connected_socket_sessions):
                        await main.sio.emit('TEST_FENCE', {'event_id': data['event_id']}, to=sid)
                    result = {}
                elif action == 'reset_metrics':
                    counts.clear()
                    batches.clear()
                    durations.clear()
                    result = {}
                elif action == 'probe':
                    result = {'pid': os.getpid(), 'connections': len(main.connected_socket_sessions),
                              'suspended': len(main.private_delivery.states), 'controls': len(main.private_delivery.controls),
                              'counts': dict(counts), 'batches': list(batches), 'durations': list(durations),
                              'rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                              'current_rss_kib': int(open('/proc/self/statm').read().split()[1]) * resource.getpagesize() // 1024}
                elif action == 'stop':
                    server.should_exit = True
                    connection.send({'result': {}})
                    return
                else:
                    raise ValueError('unknown test command')
                connection.send({'result': result})
            except Exception as exc:
                connection.send({'error': type(exc).__name__})

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(controls())
        tasks.create_task(server.serve(sockets=[listener]))
    await engine.dispose()


class Wire:
    def __init__(self, websocket):
        self.websocket = websocket
        self.frames = deque(maxlen=256)
        self.condition = asyncio.Condition()
        self.task = None

    async def packet(self, packet):
        if packet == '2':
            await self.websocket.send('3')
        elif packet.startswith('42'):
            self.frames.append(json.loads(packet[2:]))
            async with self.condition:
                self.condition.notify_all()

    async def read(self):
        async for packet in self.websocket:
            await self.packet(packet)

    def payload(self, event_id):
        return next((payload for _, payload in self.frames if payload.get('event_id') == event_id), None)

    async def wait(self, event_id):
        async with self.condition:
            await asyncio.wait_for(self.condition.wait_for(lambda: self.payload(event_id) is not None), 30)

    async def close(self):
        await self.websocket.close()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)


class ProcessCluster:
    def __init__(self, flow):
        self.flow = flow
        self.stack = AsyncExitStack()
        self.children, self.wires = [], []
        self.stream = f'f8-test:{uuid4()}'
        self.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        url = make_url(get_settings().database_url).set(database=flow.engine.url.database)
        self.url = url.render_as_string(hide_password=False)
        self.engine = create_async_engine(url)

    async def __aenter__(self):
        await self.stack.__aenter__()
        self.stack.push_async_callback(self.cleanup)
        try:
            await self.redis.ping()
            await self.flow.admin.execute('DELETE FROM outbox_events')
            other_org, other_member = ORG.replace('31000000', '32000000'), MEMBER.replace('31000000', '32000000')
            await self.flow.admin.execute('''WITH role AS (
                INSERT INTO roles (organization_id,role_definition_id,name,permissions)
                SELECT $1,id,'Reader',system_permissions FROM role_definitions WHERE code='owner' RETURNING id)
                INSERT INTO organization_user_roles (organization_id,organization_user_id,role_id)
                SELECT $1,$2,id FROM role''', UUID(other_org), UUID(other_member))
            await self.redis.xadd(self.stream, {'event': '{}'})
            for _ in range(2):
                listener = socket.socket()
                listener.bind(('127.0.0.1', 0))
                listener.listen(2048)
                parent, child = multiprocessing.get_context('spawn').Pipe()
                environment = {'APP_ENV': 'development', 'DATABASE_URL': self.url,
                               'REDIS_URL': get_settings().redis_url}
                process = multiprocessing.get_context('spawn').Process(
                    target=run_api, args=(child, listener, environment, self.stream))
                process.start()
                self.children.append((process, parent, listener.getsockname()[1]))
                child.close()
                listener.close()
            await asyncio.gather(*(self.rpc(i, 'ready') for i in range(2)))
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *args):
        return await self.stack.__aexit__(*args)

    async def cleanup(self):
        await asyncio.gather(*(wire.close() for _, wire in self.wires), return_exceptions=True)
        for process, pipe, _ in self.children:
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 10)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join)
            pipe.close()
        await self.redis.delete(self.stream)
        await self.redis.aclose()
        await self.engine.dispose()

    async def rpc(self, index, action, **values):
        pipe = self.children[index][1]
        pipe.send({'action': action, **values})
        response = await asyncio.wait_for(asyncio.to_thread(pipe.recv), 40)
        assert 'error' not in response, response.get('error')
        return response['result']

    async def identity(self, user=USER):
        from app.core.security import create_access_token

        session = uuid4()
        await self.flow.admin.execute('INSERT INTO user_sessions (id,user_id,expires_at) VALUES ($1,$2,$3)',
                                      session, UUID(user), datetime.now(timezone.utc) + timedelta(hours=1))
        class Identity(dict):
            def __repr__(self):
                return '<test session>'
        return Identity(user=user, session=session, token=create_access_token(UUID(user), session))

    async def connect(self, index, identity, organization=ORG):
        port = self.children[index][2]
        websocket = await connect(f'ws://127.0.0.1:{port}/socket.io/?EIO=4&transport=websocket',
                                  origin='http://localhost:3000', max_queue=1024)
        wire = Wire(websocket)
        self.wires.append((index, wire))
        assert (await websocket.recv()).startswith('0')
        await websocket.send('40' + json.dumps({'token': identity['token'], 'organization_id': organization}))
        while True:
            packet = await asyncio.wait_for(websocket.recv(), 30)
            if packet.startswith('44'):
                await websocket.close()
                raise PermissionError('socket authentication rejected')
            await wire.packet(packet)
            if packet.startswith('40'):
                break
        wire.task = asyncio.create_task(wire.read())
        return wire

    async def http(self, index, identity, organization=ORG):
        async with httpx.AsyncClient() as client:
            response = await client.get(f'http://127.0.0.1:{self.children[index][2]}/api/v1/matches/{MATCH}/operation',
                                        headers={'Authorization': f'Bearer {identity["token"]}',
                                                 'X-Organization-ID': organization})
            return response.status_code

    async def enqueue(self, organization=ORG, event_type='MATCH_UPDATED', payload=None):
        from app.core.outbox import enqueue_outbox

        async with async_sessionmaker(self.engine)() as db, db.begin():
            await db.execute(text("SELECT set_config('app.current_organization_id',:org,true)"), {'org': organization})
            identity = USER if organization == ORG else USER.replace('31000000', '32000000')
            await db.execute(text("SELECT set_config('app.current_user_id',:user,true)"), {'user': identity})
            event_id = await enqueue_outbox(db, organization, event_type,
                                           payload if payload is not None else {'match_id': MATCH, 'tournament_id': TOURNAMENT})
        return str(event_id)

    async def flush(self):
        from app.workers import outbox
        factory, stream = outbox.SessionFactory, outbox.OUTBOX_STREAM
        try:
            outbox.SessionFactory = async_sessionmaker(self.engine)
            outbox.OUTBOX_STREAM = self.stream
            while await outbox.process_once(self.redis):
                pass
        finally:
            outbox.SessionFactory, outbox.OUTBOX_STREAM = factory, stream

    async def publish(self, **values):
        event_id = await self.enqueue(**values)
        await self.flush()
        return event_id

    async def gate(self, event_id, phase='before'):
        await asyncio.gather(*(self.rpc(i, 'gate', event_id=event_id, phase=phase) for i in range(2)))

    async def paused(self, indices=(0, 1)):
        await asyncio.gather(*(self.rpc(i, 'paused') for i in indices))

    async def release(self):
        await asyncio.gather(*(self.rpc(i, 'release') for i in range(2)))

    async def fence(self):
        event_id = str(uuid4())
        await asyncio.gather(*(self.rpc(i, 'fence', event_id=event_id) for i in range(2)))
        await asyncio.gather(*(wire.wait(event_id) for _, wire in self.wires if wire.task and not wire.task.done()))

    async def settle(self, event_id):
        await asyncio.gather(*(self.rpc(i, 'processed', event_id=event_id) for i in range(2)))
        await self.fence()

    async def withdraw(self, kind, identity):
        async with self.flow.admin.transaction():
            if kind == 'session':
                await self.flow.admin.execute('UPDATE user_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE id=$1', identity['session'])
            elif kind == 'membership':
                await self.flow.admin.execute('UPDATE organization_users SET is_active=FALSE WHERE id=$1', UUID(MEMBER))
            elif kind == 'roles':
                await self.flow.admin.execute('DELETE FROM organization_user_roles WHERE organization_user_id=$1', UUID(MEMBER))
            elif kind == 'irrelevant_permission':
                await self.flow.admin.execute("UPDATE roles SET permissions='[]'::jsonb WHERE organization_id=$1", UUID(ORG))
            elif kind == 'irrelevant_official':
                await self.flow.admin.execute('DELETE FROM match_officials WHERE organization_id=$1', UUID(ORG))
            else:
                raise ValueError(kind)
