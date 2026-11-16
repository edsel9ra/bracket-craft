"""062 crea la recuperación y el cambio de contraseña (spec 039, T1)."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from migration_helpers import apply_migration, connect, throwaway_database

LOCAL = "f0000000-0000-4000-8000-000000000001"
GOOGLE = "f0000000-0000-4000-8000-000000000002"
INACTIVE = "f0000000-0000-4000-8000-000000000003"
SESSION_A = "f0000000-0000-4000-8000-0000000000a1"
SESSION_B = "f0000000-0000-4000-8000-0000000000b1"
OLD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$old"
NEW_HASH = "$argon2id$v=19$m=65536,t=3,p=4$new"

TABLES = ("account_email_jobs", "password_reset_tokens", "account_security_events")
FUNCTIONS = (
    "enqueue_password_reset_request(text)",
    "claim_account_email_jobs(integer)",
    "issue_password_reset(uuid,text,timestamp with time zone)",
    "invalidate_password_reset_token(text)",
    "account_email_notice_target(uuid)",
    "complete_account_email_job(uuid)",
    "fail_account_email_job(uuid,integer)",
    "password_reset_target(text)",
    "complete_password_reset(text,text,text)",
    "change_account_password(uuid,uuid,text,text)",
    "purge_account_recovery_records(timestamp with time zone,integer)",
)

SEED_SQL = f"""
INSERT INTO public.users (id, email, password_hash, full_name, is_active) VALUES
    ('{LOCAL}', 'Local@Example.test', '{OLD_HASH}', 'Local', TRUE),
    ('{GOOGLE}', 'google@example.test', NULL, 'Google', TRUE),
    ('{INACTIVE}', 'inactive@example.test', '{OLD_HASH}', 'Inactive', FALSE);
INSERT INTO public.user_sessions (id, user_id, expires_at) VALUES
    ('{SESSION_A}', '{LOCAL}', CURRENT_TIMESTAMP + INTERVAL '1 day'),
    ('{SESSION_B}', '{LOCAL}', CURRENT_TIMESTAMP + INTERVAL '1 day');
"""


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def in_30_minutes() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=30)


async def request_job(db, email: str):
    await db.execute("SELECT enqueue_password_reset_request($1)", email)
    jobs = await db.fetch("SELECT id FROM claim_account_email_jobs(10)")
    assert len(jobs) == 1
    return jobs[0]["id"]


async def issue(db, email: str, token: str):
    job = await request_job(db, email)
    row = await db.fetchrow(
        "SELECT outcome, recipient FROM issue_password_reset($1, $2, $3)", job, digest(token), in_30_minutes()
    )
    await db.execute("SELECT complete_account_email_job($1)", job)
    return row


async def active_sessions(db) -> set[str]:
    rows = await db.fetch("SELECT id FROM user_sessions WHERE revoked_at IS NULL")
    return {str(row["id"]) for row in rows}


async def test_062_tables_are_closed_and_only_functions_are_granted(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        for table in TABLES:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not await db.fetchval(
                    f"SELECT has_table_privilege('bracket_app', 'public.{table}', '{privilege}')"
                )
            assert await db.fetchval(f"SELECT relrowsecurity FROM pg_class WHERE oid = 'public.{table}'::regclass")
        for signature in FUNCTIONS:
            assert await db.fetchval(f"SELECT has_function_privilege('bracket_app', 'public.{signature}', 'EXECUTE')")
            assert not await db.fetchval(f"SELECT has_function_privilege('public', 'public.{signature}', 'EXECUTE')")
            definer, config = await db.fetchrow(
                f"SELECT prosecdef, proconfig::text FROM pg_proc WHERE oid = 'public.{signature}'::regprocedure"
            )
            assert definer and "search_path=pg_catalog, public" in config


async def test_062_request_does_not_resolve_the_account(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await db.execute("SELECT enqueue_password_reset_request($1)", "  LOCAL@example.TEST ")
        job = await db.fetchrow("SELECT kind, email, user_id, status FROM account_email_jobs")
        assert dict(job) == {
            "kind": "password_reset_request", "email": "local@example.test", "user_id": None, "status": "pending",
        }


async def test_062_issue_outcome_by_account_type(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        assert dict(await issue(db, "local@example.test", "t1")) == {
            "outcome": "reset", "recipient": "Local@Example.test",
        }
        assert dict(await issue(db, "google@example.test", "t2")) == {
            "outcome": "google_reminder", "recipient": "google@example.test",
        }
        for email, token in (("inactive@example.test", "t3"), ("missing@example.test", "t4")):
            assert dict(await issue(db, email, token)) == {"outcome": "none", "recipient": None}
        assert await db.fetchval("SELECT count(*) FROM password_reset_tokens") == 1
        assert await db.fetchval("SELECT count(*) FROM account_email_jobs WHERE email IS NOT NULL") == 0


async def test_062_new_link_invalidates_the_previous_one(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "first")
        await issue(db, "local@example.test", "second")
        assert await db.fetch("SELECT * FROM password_reset_target($1)", digest("first")) == []
        target = await db.fetchrow("SELECT user_id, password_hash FROM password_reset_target($1)", digest("second"))
        assert str(target["user_id"]) == LOCAL and target["password_hash"] == OLD_HASH


async def test_062_reset_is_single_use_and_revokes_every_session(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "token")
        user = await db.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("token"), OLD_HASH, NEW_HASH)
        assert str(user) == LOCAL
        assert await db.fetchval("SELECT password_hash FROM users WHERE id = $1", LOCAL) == NEW_HASH
        assert await active_sessions(db) == set()
        assert await db.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("token"), NEW_HASH, OLD_HASH) is None
        assert await db.fetchval("SELECT password_hash FROM users WHERE id = $1", LOCAL) == NEW_HASH
        events = await db.fetch("SELECT user_id, event_type FROM account_security_events")
        assert [(str(e["user_id"]), e["event_type"]) for e in events] == [(LOCAL, "password_reset")]
        notice = await db.fetchrow("SELECT kind, email, user_id FROM account_email_jobs WHERE status = 'pending'")
        assert dict(notice) == {"kind": "password_changed_notice", "email": None, "user_id": notice["user_id"]}
        assert str(notice["user_id"]) == LOCAL


async def test_062_reset_rejects_expired_stale_and_deactivated(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "expired")
        await db.execute("UPDATE password_reset_tokens SET created_at = created_at - INTERVAL '1 hour', expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second'")
        assert await db.fetch("SELECT * FROM password_reset_target($1)", digest("expired")) == []
        assert await db.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("expired"), OLD_HASH, NEW_HASH) is None

        await issue(db, "local@example.test", "stale")
        assert await db.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("stale"), "other", NEW_HASH) is None

        await db.execute("UPDATE users SET is_active = FALSE WHERE id = $1", LOCAL)
        assert await db.fetch("SELECT * FROM password_reset_target($1)", digest("stale")) == []
        assert await db.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("stale"), OLD_HASH, NEW_HASH) is None
        assert await db.fetchval("SELECT password_hash FROM users WHERE id = $1", LOCAL) == OLD_HASH
        assert len(await active_sessions(db)) == 2


async def test_062_concurrent_uses_change_the_password_once(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "race")
        database = await db.fetchval("SELECT current_database()")
        first = await connect(database_admin_url, database)
        second = await connect(database_admin_url, database)
        try:
            tx1, tx2 = first.transaction(), second.transaction()
            await tx1.start()
            await tx2.start()
            winner = await first.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("race"), OLD_HASH, NEW_HASH)
            pending = asyncio.create_task(
                second.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("race"), OLD_HASH, "$argon2id$x")
            )
            await asyncio.sleep(0.2)
            assert not pending.done()
            await tx1.commit()
            assert await pending is None
            await tx2.commit()
        finally:
            await first.close()
            await second.close()
        assert str(winner) == LOCAL
        assert await db.fetchval("SELECT password_hash FROM users WHERE id = $1", LOCAL) == NEW_HASH
        assert await db.fetchval("SELECT count(*) FROM account_security_events") == 1


async def test_062_reset_locks_the_account_before_the_link(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "order")
        database = await db.fetchval("SELECT current_database()")
        change = await connect(database_admin_url, database)
        reset = await connect(database_admin_url, database)
        try:
            tx1, tx2 = change.transaction(), reset.transaction()
            await tx1.start()
            await tx2.start()
            await change.execute("SELECT 1 FROM users WHERE id = $1 FOR UPDATE", LOCAL)
            pending = asyncio.create_task(
                reset.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("order"), OLD_HASH, NEW_HASH)
            )
            await asyncio.sleep(0.2)
            assert not pending.done()
            await change.execute("SET LOCAL lock_timeout = '2s'")
            await change.execute(
                "UPDATE password_reset_tokens SET invalidated_at = CURRENT_TIMESTAMP WHERE user_id = $1", LOCAL
            )
            await tx1.commit()
            assert await pending is None
            await tx2.commit()
        finally:
            await change.close()
            await reset.close()


async def test_062_reset_revokes_a_session_created_by_an_overlapping_login(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "overlap")
        database = await db.fetchval("SELECT current_database()")
        login = await connect(database_admin_url, database)
        reset = await connect(database_admin_url, database)
        late = "f0000000-0000-4000-8000-0000000000c1"
        try:
            tx1, tx2 = login.transaction(), reset.transaction()
            await tx1.start()
            await tx2.start()
            await login.execute(
                "INSERT INTO user_sessions (id, user_id, expires_at) VALUES ($1, $2, CURRENT_TIMESTAMP + INTERVAL '1 day')",
                late, LOCAL,
            )
            pending = asyncio.create_task(
                reset.fetchval("SELECT complete_password_reset($1, $2, $3)", digest("overlap"), OLD_HASH, NEW_HASH)
            )
            await asyncio.sleep(0.2)
            assert not pending.done()
            await tx1.commit()
            assert str(await pending) == LOCAL
            await tx2.commit()
        finally:
            await login.close()
            await reset.close()
        assert await active_sessions(db) == set()


async def test_062_change_keeps_only_the_current_session(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await issue(db, "local@example.test", "pending")
        assert not await db.fetchval(
            "SELECT change_account_password($1, $2, $3, $4)", LOCAL, SESSION_A, "wrong", NEW_HASH
        )
        assert len(await active_sessions(db)) == 2
        assert await db.fetchval("SELECT change_account_password($1, $2, $3, $4)", LOCAL, SESSION_A, OLD_HASH, NEW_HASH)
        assert await active_sessions(db) == {SESSION_A}
        assert await db.fetch("SELECT * FROM password_reset_target($1)", digest("pending")) == []
        events = await db.fetch("SELECT event_type FROM account_security_events")
        assert [e["event_type"] for e in events] == ["password_changed"]
        assert await db.fetchval(
            "SELECT count(*) FROM account_email_jobs WHERE kind = 'password_changed_notice' AND status = 'pending'"
        ) == 1


async def test_062_change_requires_an_active_session_of_the_account(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        await db.execute("UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE id = $1", SESSION_B)
        assert not await db.fetchval("SELECT change_account_password($1, $2, $3, $4)", LOCAL, SESSION_B, OLD_HASH, NEW_HASH)
        assert not await db.fetchval("SELECT change_account_password($1, $2, $3, $4)", GOOGLE, SESSION_A, OLD_HASH, NEW_HASH)
        assert await db.fetchval("SELECT password_hash FROM users WHERE id = $1", LOCAL) == OLD_HASH


async def test_062_job_retry_failure_notice_and_purge(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_SQL)
        job = await request_job(db, "local@example.test")
        await db.execute(
            "SELECT * FROM issue_password_reset($1, $2, $3)", job, digest("undelivered"), in_30_minutes()
        )
        await db.execute("SELECT invalidate_password_reset_token($1)", digest("undelivered"))
        assert await db.fetch("SELECT * FROM password_reset_target($1)", digest("undelivered")) == []
        await db.execute("SELECT fail_account_email_job($1, 2)", job)
        row = await db.fetchrow("SELECT status, attempts, email, available_at > CURRENT_TIMESTAMP AS later FROM account_email_jobs")
        assert dict(row) == {"status": "pending", "attempts": 1, "email": "local@example.test", "later": True}
        assert await db.fetch("SELECT id FROM claim_account_email_jobs(10)") == []
        await db.execute("UPDATE account_email_jobs SET available_at = CURRENT_TIMESTAMP")
        assert len(await db.fetch("SELECT id FROM claim_account_email_jobs(10)")) == 1
        await db.execute("SELECT fail_account_email_job($1, 2)", job)
        row = await db.fetchrow("SELECT status, email, processed_at IS NOT NULL AS done FROM account_email_jobs")
        assert dict(row) == {"status": "failed", "email": None, "done": True}

        await db.execute("SELECT change_account_password($1, $2, $3, $4)", LOCAL, SESSION_A, OLD_HASH, NEW_HASH)
        notice = (await db.fetch("SELECT id FROM claim_account_email_jobs(10)"))[0]["id"]
        assert await db.fetchval("SELECT recipient FROM account_email_notice_target($1)", notice) == "Local@Example.test"
        await db.execute("SELECT complete_account_email_job($1)", notice)

        future = datetime.now(timezone.utc) + timedelta(days=1)
        deleted = await db.fetchrow("SELECT * FROM purge_account_recovery_records($1, 500)", future)
        assert dict(deleted) == {"tokens_deleted": 1, "jobs_deleted": 2}
        assert await db.fetchval("SELECT count(*) FROM account_security_events") == 1


async def test_062_incremental_from_061(database_admin_url):
    async with throwaway_database(database_admin_url, last=61) as db:
        assert not await db.fetchval("SELECT to_regclass('public.password_reset_tokens') IS NOT NULL")
        await apply_migration(db, 62)
        assert await db.fetchval("SELECT to_regclass('public.password_reset_tokens') IS NOT NULL")
