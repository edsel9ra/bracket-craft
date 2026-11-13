from contextlib import asynccontextmanager
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
