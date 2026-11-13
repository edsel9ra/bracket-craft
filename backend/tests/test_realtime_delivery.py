from contextlib import asynccontextmanager
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.realtime_authorization import RealtimeAuthorizer
from app.core import realtime_policy as policy
from test_realtime_policy import NOW, envelope, socket_metadata


class Database:
    def __init__(self, rows, fail=False):
        self.rows = rows
        self.fail = fail
        self.statements = []
        self.transactions = 0

    @asynccontextmanager
    async def begin(self):
        self.transactions += 1
        yield self

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if 'authorize_realtime_recipients' in sql:
            if self.fail:
                raise RuntimeError('database unavailable')
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: self.rows))
        return SimpleNamespace(scalar_one=lambda: NOW)


def harness(rows, fail=False):
    databases = []

    @asynccontextmanager
    async def factory():
        db = Database(rows, fail)
        databases.append(db)
        yield db

    return RealtimeAuthorizer(factory, lambda: NOW), databases


def inputs():
    event = policy.classify_organization_event(envelope())
    batches = policy.group_recipients({'sid': socket_metadata(event.organization_id)}, event.organization_id)
    principal = batches[0][0]
    return event, batches[0], {'user_id': principal.user_id, 'session_id': principal.session_id, 'decision': 'ALLOW'}


async def test_adapter_new_repeatable_read_transaction_and_context_per_evaluation():
    event, principals, row = inputs()
    adapter, databases = harness([row])
    first = await adapter.evaluate_batch(event, principals)
    second = await adapter.evaluate_batch(event, principals)
    assert len(databases) == 2 and first == second
    assert first[0].decision == policy.Decision.ALLOW and first[0].evaluation_time == NOW
    assert first[0].sid == 'sid' and first[0].generation == principals[0].sockets[0].generation
    for db in databases:
        assert db.transactions == 1
        statements = [sql for sql, _ in db.statements]
        assert statements[0] == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'
        assert statements[1] == 'SELECT statement_timestamp()'
        assert statements[2:4] == ["SELECT set_config('app.current_organization_id', :value, true)",
                                   "SELECT set_config('app.current_user_id', :value, true)"]
        assert len([sql for sql in statements if 'authorize_realtime_recipients' in sql]) == 1


@pytest.mark.parametrize('rows,fail', [([], False), ([{'user_id': uuid4(), 'session_id': uuid4(), 'decision': 'ALLOW'}], False), ([], True)])
async def test_adapter_missing_principal_or_database_error_suspends(rows, fail):
    event, principals, _ = inputs()
    adapter, _ = harness(rows, fail)
    result = await adapter.evaluate_batch(event, principals)
    assert len(result) == 1 and result[0].decision == policy.Decision.INDETERMINATE


async def test_adapter_empty_candidates_do_not_query():
    adapter, databases = harness([])
    assert await adapter.evaluate_batch(None, ()) == () and databases == []


async def test_adapter_conflicting_duplicate_decisions_fail_closed():
    event, principals, row = inputs()
    adapter, _ = harness([row, {**row, 'decision': 'DENY'}])
    result = await adapter.evaluate_batch(event, principals)
    assert result[0].decision == policy.Decision.INDETERMINATE


async def test_adapter_migration_partial_result_does_not_poison_valid_principal():
    event, principals, row = inputs()
    adapter, _ = harness([row, {'user_id': row['user_id'], 'session_id': None, 'decision': 'INDETERMINATE'}])
    assert (await adapter.evaluate_batch(event, principals))[0].decision == policy.Decision.ALLOW


@pytest.mark.parametrize('count,tabs,expected_calls', [(100, 10, 1), (257, 1, 2), (0, 1, 0)])
async def test_batching_bounded_calls_not_per_socket(count, tabs, expected_calls):
    event = policy.classify_organization_event(envelope())
    sessions, rows = {}, []
    for i in range(count):
        user, session = uuid4(), uuid4()
        rows.append({'user_id': user, 'session_id': session, 'decision': 'ALLOW'})
        for tab in range(tabs):
            sessions[f'{i}-{tab}'] = socket_metadata(event.organization_id, user, session)
    adapter, databases = harness(rows)
    results = [batch async for batch in adapter.evaluate(event, sessions)]
    assert len(databases) == expected_calls
    assert sum(len(batch) for batch in results) == count * tabs
    assert all(row.decision == policy.Decision.ALLOW for batch in results for row in batch)
    assert all(sum('authorize_realtime_recipients' in sql for sql, _ in db.statements) == 1 for db in databases)


async def test_batching_next_snapshot_is_lazy_and_errors_are_not_cached():
    event = policy.classify_organization_event(envelope())
    sessions = {str(i): socket_metadata(event.organization_id) for i in range(257)}
    adapter, databases = harness([], fail=True)
    stream = adapter.evaluate(event, sessions)
    assert not databases
    first = await anext(stream)
    assert len(databases) == 1 and len(first) == 256
    second = await anext(stream)
    assert len(databases) == 2 and len(second) == 1
    assert all(row.decision == policy.Decision.INDETERMINATE for row in first + second)


async def test_registry_handshake_expiry_generation_and_session_tabs(monkeypatch):
    from app import main

    event, _, row = inputs()
    claims = {'sub': str(row['user_id']), 'jti': str(row['session_id']),
              'exp': (NOW + timedelta(days=3650)).timestamp()}

    class HandshakeDatabase(Database):
        async def execute(self, statement, params=None):
            return SimpleNamespace(scalar_one_or_none=lambda: 'roles', scalar_one=lambda: True)

    @asynccontextmanager
    async def factory():
        yield HandshakeDatabase([])

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(main, 'SessionFactory', factory)
    monkeypatch.setattr(main, 'decode_access_token_claims', lambda token: claims)
    monkeypatch.setattr(main.sio, 'save_session', noop)
    monkeypatch.setattr(main.sio, 'enter_room', noop)
    monkeypatch.setattr(main, 'emit_join_resync', noop)
    monkeypatch.setattr(main, 'connected_socket_sessions', main.SocketRegistry())
    for sid in ('a', 'b'):
        assert await main.connect(sid, {}, {'organization_id': str(event.organization_id), 'token': 'verified'}) is True
    sessions = main.connected_socket_sessions
    assert sessions['a']['jwt_expires_at'].timestamp() == claims['exp']
    assert sessions['a']['generation'] != sessions['b']['generation']
    assert set(sessions.organization_sessions(event.organization_id)) == {'a', 'b'}
    assert len(policy.group_recipients(sessions, event.organization_id)[0]) == 1
    previous = sessions['a']['generation']
    await main.disconnect('a')
    assert set(sessions.organization_sessions(event.organization_id)) == {'b'}
    assert await main.connect('a', {}, {'organization_id': str(event.organization_id), 'token': 'verified'})
    assert sessions['a']['generation'] != previous
    assert not sessions.organization_sessions(uuid4())


def test_registry_replacement_pop_clear_and_other_tenant():
    from app import main

    first, second = uuid4(), uuid4()
    registry = main.SocketRegistry()
    registry['a'] = socket_metadata(first)
    registry['b'] = socket_metadata(first)
    registry['a'] = socket_metadata(second)
    assert set(registry.organization_sessions(first)) == {'b'}
    assert set(registry.organization_sessions(second)) == {'a'}
    registry.pop('a')
    assert not registry.organization_sessions(second)
    registry.clear()
    assert not registry.organization_sessions(first)
    assert not registry


@pytest.mark.parametrize('claims', [
    {'sub': str(uuid4()), 'jti': str(uuid4())},
    {'sub': str(uuid4()), 'exp': 2000000000},
    {'sub': 'invalid', 'jti': str(uuid4()), 'exp': 2000000000},
    {'sub': str(uuid4()), 'jti': str(uuid4()), 'exp': None},
])
async def test_registry_missing_or_invalid_verified_claims_reject_before_database(monkeypatch, claims):
    from app import main

    monkeypatch.setattr(main, 'decode_access_token_claims', lambda token: claims)
    assert await main.connect('sid', {}, {'organization_id': str(uuid4()), 'token': 'verified'}) is False


def delivery_harness():
    from app.core.realtime_delivery import PrivateDelivery
    from app.core.realtime_registry import SocketRegistry

    event, _, _ = inputs()
    sessions = SocketRegistry()
    sessions['allowed'] = socket_metadata(event.organization_id)
    sessions['denied'] = socket_metadata(event.organization_id)
    calls, disconnections, context_calls = [], [], []
    behavior = {'allowed': policy.Decision.ALLOW, 'denied': policy.Decision.DENY,
                'context': {'allowed': True, 'denied': True}, 'fail_send': False}

    class Authorizer:
        async def evaluate_batch(self, event, principals):
            from app.core.realtime_authorization import SocketDecision

            return tuple(SocketDecision(s.sid, s.generation, behavior[s.sid], NOW)
                         for p in principals for s in p.sockets)

    async def validate(snapshot):
        context_calls.append(snapshot)
        if behavior['context'] is None:
            raise RuntimeError('private diagnostic')
        return behavior['context']

    async def emit(name, payload, *, to):
        if behavior['fail_send']:
            raise RuntimeError('private diagnostic')
        calls.append((name, payload, to))

    async def disconnect(sid):
        disconnections.append(sid)
        sessions.pop(sid, None)

    delivery = PrivateDelivery(lambda: sessions, Authorizer(), validate, emit, disconnect, lambda: NOW)
    return delivery, event, sessions, behavior, calls, disconnections, context_calls


async def test_delivery_allowed_only_minimal_wire_denied_absent_no_room():
    delivery, event, _, _, calls, _, _ = delivery_harness()
    await delivery.deliver(event.envelope)
    assert [(name, sid) for name, _, sid in calls] == [(event.rule.event_type, 'allowed')]
    assert set(calls[0][1]) == {'event_id', 'match_id', 'tournament_id'}


@pytest.mark.parametrize('event_type', ['VERIFICATION_OUTBOX_PROBE', 'SANCTION_CASE_NOTICE_INTERNAL',
    'SANCTION_CASE_NOTICE_EMAIL', 'RECTIFICATION_DECISION_EMAIL', 'RESYNC', 'MATCH_DRAFT_UPDATED'])
async def test_delivery_exclusions_unknown_events_are_not_emitted(event_type):
    delivery, event, _, _, calls, _, _ = delivery_harness()
    await delivery.deliver({**event.envelope, 'event_type': event_type})
    assert not calls


async def test_suspension_recovery_cycle_without_event_and_coalesced_resync():
    delivery, event, _, behavior, calls, _, contexts = delivery_harness()
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)
    await delivery.deliver(event.envelope)
    assert not calls and 'allowed' in delivery.states
    await delivery.recover()
    assert len(calls) == 1 and calls[0][0] == 'RESYNC' and calls[0][2] == 'allowed'
    assert set(calls[0][1]) == {'event_id', 'reason'}
    assert calls[0][1]['reason'] == 'RELAY_START'
    assert contexts and not delivery.states
    await delivery.recover()
    assert len(calls) == 1


@pytest.mark.parametrize('context', [None, {}, {'allowed': False}])
async def test_recovery_cycle_032_error_missing_or_revoked_does_not_resync(context):
    delivery, event, _, behavior, calls, disconnected, _ = delivery_harness()
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)
    behavior['context'] = context
    await delivery.recover()
    assert not calls
    if context == {'allowed': False}:
        assert disconnected == ['allowed']
    else:
        assert not disconnected and 'allowed' in delivery.states


async def test_recovery_event_send_error_retains_suspension_then_reauthorizes():
    delivery, event, _, behavior, calls, _, _ = delivery_harness()
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)
    behavior.update(allowed=policy.Decision.ALLOW, fail_send=True)
    await delivery.deliver(event.envelope)
    assert not calls and delivery.states
    behavior['fail_send'] = False
    await delivery.deliver(event.envelope)
    assert [name for name, _, _ in calls] == ['RESYNC', event.rule.event_type]
    assert not delivery.states


async def test_generation_changed_between_query_and_emit_discards_old_decision():
    delivery, event, sessions, _, calls, _, _ = delivery_harness()
    evaluate = delivery.authorizer.evaluate_batch

    async def paused(event, principals):
        result = await evaluate(event, principals)
        sessions['allowed'] = socket_metadata(event.organization_id)
        return result

    delivery.authorizer.evaluate_batch = paused
    await delivery.deliver(event.envelope)
    assert not calls


@pytest.mark.parametrize('event_type,private', [
    ('MATCH_CLOSED', False), ('MATCH_UPDATED', False), ('STANDINGS_UPDATED', False),
    ('MATCH_UPDATED', True), ('STANDINGS_UPDATED', True), ('MATCH_REPORT_RECTIFIED', True),
])
async def test_delivery_all_catalog_rules_minimal_wire_with_historical_timestamp(event_type, private):
    delivery, event, _, _, calls, _, _ = delivery_harness()
    data = {**event.envelope, 'event_type': event_type, 'payload': dict(event.envelope['payload'])}
    if private:
        data['payload'].update(scope='organization', version_id=str(uuid4()), rectified_at=NOW.isoformat())
    await delivery.deliver(data)
    assert len(calls) == 1 and calls[0][0] == event_type
    assert calls[0][1] == {'event_id': data['event_id'], **event.envelope['payload']}


@pytest.mark.parametrize('event_type', ['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'])
async def test_public_contract_independent_of_private_authorization_failure(monkeypatch, event_type):
    from app import main

    delivery, event, _, behavior, private_calls, _, _ = delivery_harness()
    behavior['allowed'] = policy.Decision.INDETERMINATE
    public_calls = []

    async def emit(name, payload, **kwargs):
        public_calls.append((name, payload, kwargs))

    monkeypatch.setattr(main, 'private_delivery', delivery)
    monkeypatch.setattr(main.sio, 'emit', emit)
    data = {**event.envelope, 'event_type': event_type}
    parsed = main.parse_envelope({'event': json.dumps(data)})
    await main.emit_domain_event(parsed)
    assert public_calls == [(event_type, {'event_id': data['event_id'], **data['payload']},
                             {'room': f"tournament:{data['payload']['tournament_id']}"})]
    assert not private_calls and 'allowed' in delivery.states
    data['payload'] = {**data['payload'], 'scope': 'organization', 'version_id': str(uuid4())}
    await main.emit_domain_event(main.parse_envelope({'event': json.dumps(data)}))
    assert len(public_calls) == 1


@pytest.mark.parametrize('failure', ['exception', 'missing'])
async def test_suspension_rollout_advances_cursor_without_backlog_and_logs_no_payload(monkeypatch, caplog, failure):
    from app import main
    from test_outbox_resync import StaticStreamRedis

    delivery, event, _, _, calls, disconnected, _ = delivery_harness()

    async def broken(event, principals):
        if failure == 'exception':
            raise RuntimeError('private diagnostic')
        return ()

    delivery.authorizer.evaluate_batch = broken
    monkeypatch.setattr(main, 'private_delivery', delivery)
    # Variante privada: nunca entra en el carril público.
    data = {**event.envelope, 'payload': {**event.envelope['payload'], 'scope': 'organization',
                                         'version_id': str(uuid4())}}
    entries = [(f'{n}-0', {'event': json.dumps({**data, 'event_id': str(uuid4())})}) for n in range(1, 5)]
    redis = StaticStreamRedis(entries)
    state = main.RelayState(position='1-0', started=True)
    await main.relay_cycle(redis, state, main.emit_domain_event)
    assert state.position == '4-0' and not calls and not disconnected
    assert set(delivery.states) == {'allowed', 'denied'}
    assert all(set(vars(value)) == {'generation', 'needs_resync', 'pending_resync', 'next_attempt_at'}
               for value in delivery.states.values())
    assert data['payload']['match_id'] not in caplog.text and 'private diagnostic' not in caplog.text


@pytest.mark.parametrize('change', ['generation', 'organization_id', 'session_id', 'disconnect'])
async def test_generation_context_changed_during_control_is_discarded(change):
    delivery, event, sessions, behavior, calls, _, _ = delivery_harness()
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)

    async def validate(snapshot):
        if change == 'disconnect':
            sessions.pop('allowed')
        else:
            sessions['allowed'][change] = str(uuid4())
        return {'allowed': True}

    delivery.validate_context = validate
    await delivery.recover()
    assert not calls


async def test_generation_in_place_mutation_during_authorization_discards_old_decision():
    delivery, event, sessions, _, calls, _, _ = delivery_harness()
    evaluate = delivery.authorizer.evaluate_batch

    async def changed(event, principals):
        result = await evaluate(event, principals)
        sessions['allowed']['generation'] = str(uuid4())
        return result

    delivery.authorizer.evaluate_batch = changed
    await delivery.deliver(event.envelope)
    assert not calls


async def test_recovery_cycle_batches_contexts_and_coalesces_concurrent_controls():
    delivery, event, sessions, _, calls, _, _ = delivery_harness()
    sessions.clear()
    for n in range(513):
        sessions[str(n)] = socket_metadata(event.organization_id)
        delivery.suspend(str(n), sessions[str(n)])
    batch_sizes = []

    async def validate(snapshot):
        batch_sizes.append(len(snapshot))
        await asyncio.sleep(0)
        return dict.fromkeys(snapshot, True)

    delivery.validate_context = validate
    await asyncio.gather(delivery.recover(), delivery.recover())
    assert batch_sizes == [256, 256, 1]
    assert len(calls) == 513 and len({payload['event_id'] for _, payload, _ in calls}) == 513
    assert not delivery.states and not delivery.controls


async def test_recovery_cycle_error_then_retry_and_expired_jwt_disconnects():
    delivery, event, sessions, behavior, calls, disconnected, _ = delivery_harness()
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)
    behavior['context'] = None
    await delivery.recover()
    assert not calls and delivery.states
    behavior['context'] = {'allowed': True}
    await delivery.recover()
    assert len(calls) == 1 and not delivery.states
    calls.clear()
    sessions['allowed']['jwt_expires_at'] = NOW
    delivery.suspend('allowed', sessions['allowed'])
    await delivery.recover()
    assert not calls and disconnected == ['allowed']


@pytest.mark.parametrize('valid', [True, False, None, 'error'])
async def test_recovery_cycle_uses_032_once_for_suspended_socket_without_event(monkeypatch, valid):
    from unittest.mock import AsyncMock, MagicMock
    from app import main

    delivery, event, sessions, behavior, calls, disconnected, _ = delivery_harness()
    sessions.pop('denied')
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.begin = MagicMock(return_value=AsyncMock())
    if valid == 'error':
        db.execute.side_effect = RuntimeError('private diagnostic')
    else:
        result = MagicMock()
        result.mappings.return_value.all.return_value = [] if valid is None else [{'sid': 'allowed', 'is_valid': valid}]
        db.execute.return_value = result
    monkeypatch.setattr(main, 'connected_socket_sessions', sessions)
    monkeypatch.setattr(main, 'SessionFactory', lambda: db)
    monkeypatch.setattr(main, 'private_delivery', delivery)
    delivery.validate_context = main.revalidate_socket_contexts
    await main.revalidate_socket_sessions_cycle()
    db.execute.assert_awaited_once()
    assert 'revalidate_socket_sessions' in str(db.execute.call_args.args[0])
    assert len(calls) == (1 if valid is True else 0)
    assert disconnected == (['allowed'] if valid is False else [])
    assert bool(delivery.states) is (valid is None or valid == 'error')


@pytest.mark.parametrize('reason', ['JOIN', 'RELAY_START', 'STREAM_TRIMMED', 'REDIS_RESET'])
@pytest.mark.parametrize('valid', [True, False, None])
async def test_recovery_cycle_all_organization_controls_are_directed_and_revalidated(monkeypatch, reason, valid):
    from app import main

    delivery, _, sessions, behavior, calls, disconnected, contexts = delivery_harness()
    sessions.pop('denied')
    behavior['context'] = {'allowed': valid}
    monkeypatch.setattr(main, 'connected_socket_sessions', sessions)
    monkeypatch.setattr(main, 'private_delivery', delivery)
    if reason == 'JOIN':
        await main.emit_join_resync('allowed')
    else:
        await main.emit_gap_resync(reason)
    assert len(contexts) == 1 and set(contexts[0]) == {'allowed'}
    if valid is True:
        assert len(calls) == 1 and calls[0][0] == 'RESYNC' and calls[0][2] == 'allowed'
        assert calls[0][1]['reason'] == reason and set(calls[0][1]) == {'event_id', 'reason'}
    else:
        assert not calls and disconnected == (['allowed'] if valid is False else [])


async def test_recovery_event_denial_keeps_suspension_and_other_tenant_is_untouched():
    delivery, event, sessions, behavior, calls, _, _ = delivery_harness()
    sessions['foreign'] = socket_metadata(uuid4())
    behavior['allowed'] = policy.Decision.INDETERMINATE
    await delivery.deliver(event.envelope)
    behavior['allowed'] = policy.Decision.DENY
    await delivery.deliver(event.envelope)
    assert not calls and set(delivery.states) == {'allowed'}


async def test_delivery_multiple_tabs_share_batch_and_never_cache_an_allow():
    from app.core.realtime_authorization import SocketDecision

    delivery, event, sessions, _, calls, _, _ = delivery_harness()
    sessions.pop('denied')
    sessions['tab'] = {**sessions['allowed'], 'generation': str(uuid4())}
    batches = []

    async def evaluate(event, principals):
        batches.append(principals)
        decision = policy.Decision.ALLOW if len(batches) == 1 else policy.Decision.DENY
        return tuple(SocketDecision(socket.sid, socket.generation, decision, NOW)
                     for principal in principals for socket in principal.sockets)

    delivery.authorizer.evaluate_batch = evaluate
    await delivery.deliver(event.envelope)
    assert {sid for _, _, sid in calls} == {'allowed', 'tab'}
    await delivery.deliver(event.envelope)
    assert len(batches) == 2 and all(len(batch) == 1 and len(batch[0].sockets) == 2 for batch in batches)
    assert len(calls) == 2
