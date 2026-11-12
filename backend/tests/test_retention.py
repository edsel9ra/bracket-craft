from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest

from app.workers import outbox, retention
from migration_helpers import throwaway_database

NOW = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)


def test_retention_cutoffs_are_pure_and_preserve_the_instant():
    assert retention.retention_cutoffs(NOW) == (
        datetime(2026, 1, 30, 12, tzinfo=timezone.utc),
        datetime(2026, 2, 22, 12, tzinfo=timezone.utc),
    )
    local = NOW.astimezone(timezone(timedelta(hours=5)))
    assert retention.retention_cutoffs(local) == retention.retention_cutoffs(NOW)


def test_retention_rejects_a_naive_timestamp():
    with pytest.raises(ValueError, match="zona horaria"):
        retention.retention_cutoffs(NOW.replace(tzinfo=None))


@pytest.mark.parametrize("last,now,due", [
    (None, 0, True), (0, 3599, False), (0, 3600, True), (50, 49, True),
])
def test_purge_interval(last, now, due):
    assert retention.purge_is_due(last, now) is due


@pytest.mark.asyncio
@pytest.mark.parametrize("counts", [(0, 0), (3, 4)])
async def test_purge_once_passes_cutoffs_and_logs_counts(monkeypatch, caplog, counts):
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.begin = MagicMock(return_value=AsyncMock())
    result = MagicMock()
    result.one.return_value = counts
    db.execute.return_value = result
    monkeypatch.setattr(retention, "SessionFactory", lambda: db)
    caplog.set_level("INFO", logger=retention.__name__)
    assert await retention.purge_once(NOW) == counts
    assert db.execute.await_args.args[1] == {
        "sessions": NOW - timedelta(days=30),
        "outbox": NOW - timedelta(days=7),
        "batch_limit": 500,
    }
    assert f"sesiones={counts[0]}, eventos outbox={counts[1]}" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("batches,totals", [
    ([(500, 1), (2, 500), (3, 4)], (505, 505)),
    ([(0, 500), (0, 0)], (0, 500)),
    ([(500, 0)] * 20, (10000, 0)),
])
async def test_purge_repeats_full_batches_in_separate_transactions(monkeypatch, caplog, batches, totals):
    db = AsyncMock()
    db.__aenter__.return_value = db
    transactions = [AsyncMock() for _ in batches]
    db.begin = MagicMock(side_effect=transactions)
    calls = 0

    async def execute(_query, parameters):
        nonlocal calls
        assert transactions[calls].__aenter__.await_count == 1
        if calls:
            assert transactions[calls - 1].__aexit__.await_count == 1
        assert parameters == {
            "sessions": NOW - timedelta(days=30),
            "outbox": NOW - timedelta(days=7),
            "batch_limit": 500,
        }
        result = MagicMock()
        result.one.return_value = batches[calls]
        calls += 1
        return result

    db.execute.side_effect = execute
    monkeypatch.setattr(retention, "SessionFactory", lambda: db)
    caplog.set_level("INFO", logger=retention.__name__)
    assert await retention.purge_once(NOW) == totals
    assert calls == len(batches)
    assert db.begin.call_count == len(batches)
    for transaction in transactions:
        transaction.__aexit__.assert_awaited_once_with(None, None, None)
    assert f"sesiones={totals[0]}, eventos outbox={totals[1]}" in caplog.text


@pytest.mark.asyncio
async def test_worker_purges_hourly_and_continues_after_a_failure(monkeypatch, caplog):
    clock = SimpleNamespace(now=0)
    process = AsyncMock(return_value=0)
    purge = AsyncMock(side_effect=[RuntimeError("purge unavailable"), (0, 0)])
    monkeypatch.setattr(outbox, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(outbox, "process_once", process)
    monkeypatch.setattr(outbox, "purge_once", purge)
    monkeypatch.setattr(outbox, "publish_heartbeat", lambda: None)

    class StopLoop(Exception):
        pass

    async def advance(_seconds):
        if process.await_count == 1:
            clock.now = 3599
        elif process.await_count == 2:
            clock.now = 3600
        else:
            raise StopLoop

    monkeypatch.setattr(outbox.asyncio, "sleep", advance)
    with pytest.raises(StopLoop):
        await outbox._run_loop(AsyncMock())
    assert process.await_count == 3
    assert purge.await_count == 2
    assert "No se pudo completar la purga periódica" in caplog.text


async def _seed_retention(connection):
    user_id = uuid4()
    organizations = [uuid4(), uuid4()]
    await connection.execute(
        "INSERT INTO users (id,email,full_name) VALUES ($1,'retention@example.test','Retention fixture')",
        user_id,
    )
    for org_id in organizations:
        await connection.execute(
            "INSERT INTO organizations (id,name,slug) VALUES ($1,'Retention fixture',$2)",
            org_id, str(org_id),
        )
    session_cutoff, outbox_cutoff = retention.retention_cutoffs(NOW)
    old = timedelta(seconds=1)
    sessions = {
        "expired_old": (session_cutoff - old, None),
        "revoked_old": (NOW + timedelta(days=1), session_cutoff - old),
        "active": (NOW + timedelta(days=1), None),
        "expired_recent": (NOW - old, None),
        "revoked_recent": (NOW + timedelta(days=1), NOW - old),
        "expiry_boundary": (session_cutoff, None),
        "revocation_boundary": (NOW + timedelta(days=1), session_cutoff),
    }
    session_ids = {}
    for label, (expires_at, revoked_at) in sessions.items():
        session_ids[label] = uuid4()
        await connection.execute("""
            INSERT INTO user_sessions(id,user_id,expires_at,revoked_at) VALUES ($1,$2,$3,$4)
        """, session_ids[label], user_id, expires_at, revoked_at)
    events = {
        "old_processed_a": ("processed", outbox_cutoff - old, None),
        "old_processed_b": ("processed", outbox_cutoff - old, None),
        "recent_processed": ("processed", NOW - old, None),
        "boundary": ("processed", outbox_cutoff, None),
        "pending_retry": ("pending", outbox_cutoff - old, None),
        "processing": ("processing", outbox_cutoff - old, NOW),
        "failed": ("failed", outbox_cutoff - old, None),
        "processed_without_timestamp": ("processed", None, None),
        "processed_locked": ("processed", outbox_cutoff - old, NOW),
    }
    event_ids = {}
    for index, (label, (status, processed_at, locked_at)) in enumerate(events.items()):
        event_ids[label] = uuid4()
        await connection.execute("""
            INSERT INTO outbox_events
                (id,organization_id,event_type,payload,status,processed_at,locked_at,attempts,available_at)
            VALUES ($1,$2,'RETENTION_TEST','{}',$3,$4,$5,1,$6)
        """, event_ids[label], organizations[index % 2], status, processed_at, locked_at, NOW)
    member_id = await connection.fetchval("""
        INSERT INTO organization_users(organization_id,user_id) VALUES ($1,$2) RETURNING id
    """, organizations[0], user_id)
    await connection.execute("""
        INSERT INTO organization_invitations
            (organization_id,email,role_code,token_hash,expires_at,invited_by_member_id)
        VALUES ($1,'retention-invitation@example.test','viewer','retention-hash',$2,$3)
    """, organizations[0], NOW - timedelta(days=90), member_id)
    return session_ids, event_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_limit", [1, 500])
async def test_purge_is_bounded_cross_tenant_and_preserves_live_records(database_admin_url, batch_limit):
    async with throwaway_database(database_admin_url, last=34) as connection:
        session_ids, event_ids = await _seed_retention(connection)
        await connection.execute("SET ROLE bracket_app")
        assert not await connection.fetchval("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
        assert not await connection.fetchval("SELECT has_table_privilege(current_user,'user_sessions','DELETE')")
        counts = await connection.fetchrow(
            "SELECT * FROM purge_retained_records($1,$2,$3)",
            *retention.retention_cutoffs(NOW), batch_limit,
        )
        assert tuple(counts) == (min(2, batch_limit), min(2, batch_limit))
        await connection.fetchrow("SELECT * FROM purge_retained_records($1,$2,500)", *retention.retention_cutoffs(NOW))
        empty = await connection.fetchrow("SELECT * FROM purge_retained_records($1,$2,500)", *retention.retention_cutoffs(NOW))
        assert tuple(empty) == (0, 0)
        await connection.execute("RESET ROLE")
        remaining_sessions = {row[0] for row in await connection.fetch("SELECT id FROM user_sessions")}
        assert remaining_sessions == {value for key, value in session_ids.items() if key not in {"expired_old", "revoked_old"}}
        remaining_events = {row[0] for row in await connection.fetch("SELECT id FROM outbox_events")}
        assert remaining_events == {value for key, value in event_ids.items() if not key.startswith("old_processed")}
        assert await connection.fetchval("SELECT count(*) FROM organization_invitations") == 1
        permissions = await connection.fetchrow("""
            SELECT p.prosecdef, p.proconfig,
                   EXISTS (SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
            FROM pg_proc p WHERE p.oid='public.purge_retained_records(timestamptz,timestamptz,integer)'::regprocedure
        """)
        assert permissions[0] is True
        assert permissions[1] == ["search_path=pg_catalog, public"]
        assert permissions[2] is False


@pytest.mark.asyncio
async def test_purge_rejects_invalid_parameters(database_admin_url):
    async with throwaway_database(database_admin_url, last=34) as connection:
        await connection.execute("SET ROLE bracket_app")
        for session_cutoff, outbox_cutoff, limit in [
            (NOW, NOW, 0), (NOW, NOW, 501), (NOW, NOW, None),
            (None, NOW, 1), (NOW, None, 1),
        ]:
            with pytest.raises(asyncpg.PostgresError, match="invalid retention parameters"):
                await connection.fetchrow(
                    "SELECT * FROM purge_retained_records($1,$2,$3)", session_cutoff, outbox_cutoff, limit
                )
