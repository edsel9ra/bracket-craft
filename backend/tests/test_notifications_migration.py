"""Migración 067: avisos, destinatarios y preferencias (spec 046, T1).

Cada test crea una base desechable con los scripts ``init`` y las migraciones
numeradas reales. Se valida la cadena ya migrada (066 -> 067) y la de volumen
limpio (init + 001..067). Requiere ``RUN_DATABASE_TESTS=1`` y
``DATABASE_ADMIN_URL``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MATCH, ORG, PLAYER_HOME_FIRST, SEED_SQL, TOURNAMENT, USER

USER_B = "46000000-0000-4000-8000-000000000002"
MEMBER_B = "46000000-0000-4000-8000-000000000003"
USER_GONE = "46000000-0000-4000-8000-000000000004"
MEMBER_GONE = "46000000-0000-4000-8000-000000000005"
OTHER_ORG = "46000000-0000-4000-8000-000000000010"
OTHER_USER = "46000000-0000-4000-8000-000000000011"
OTHER_MEMBER = "46000000-0000-4000-8000-000000000012"
OTHER_TOURNAMENT = "46000000-0000-4000-8000-000000000013"
SUSPENSION = "46000000-0000-4000-8000-000000000020"

TABLES = ("notifications", "notification_recipients", "notification_preferences")
APP_FUNCTIONS = (
    "notification_member_active(uuid,uuid)",
    "record_notification(text,uuid,uuid,uuid,integer)",
    "deliver_notification_inbox(uuid)",
    "notification_email_payload(uuid)",
    "record_notification_email_delivery(uuid)",
    "mark_notifications_read(uuid[])",
    "claim_outbox_events(integer)",
    "claim_notification_email_events(integer)",
)
INTERNAL_FUNCTIONS = (
    "notification_channel_enabled(uuid,uuid,text,text)",
    "notification_claimed_event(uuid,text)",
    "notification_claimed_email(uuid)",
)

EXTRA_SEED = f"""
INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER_B}', 'member-b@example.test', 'hash', 'Member B'),
    ('{USER_GONE}', 'gone@example.test', 'hash', 'Gone'),
    ('{OTHER_USER}', 'other@example.test', 'hash', 'Other');
INSERT INTO public.organizations (id, name, slug) VALUES ('{OTHER_ORG}', 'Other 046', 'other-046');
INSERT INTO public.organization_users (id, organization_id, user_id, is_active) VALUES
    ('{MEMBER_B}', '{ORG}', '{USER_B}', TRUE),
    ('{MEMBER_GONE}', '{ORG}', '{USER_GONE}', FALSE),
    ('{OTHER_MEMBER}', '{OTHER_ORG}', '{OTHER_USER}', TRUE);
INSERT INTO public.tournaments (id, organization_id, name, season, start_date, status, current_draft_config)
VALUES ('{OTHER_TOURNAMENT}', '{OTHER_ORG}', 'Other Cup', '2026', DATE '2026-01-01', 'draft', '{{}}'::jsonb);
INSERT INTO public.player_suspensions
    (id, organization_id, source_tournament_id, player_id, origin_match_id, source_type,
     dedupe_key, scope_type, matches_suspended, reason)
VALUES ('{SUSPENSION}', '{ORG}', '{TOURNAMENT}', '{PLAYER_HOME_FIRST}', '{MATCH}', 'competition_rule',
        'notification-046', 'tournament', 1, 'test');
"""


@pytest.fixture
async def db(database_admin_url):
    async with throwaway_database(database_admin_url, last=66) as connection:
        await connection.execute(SEED_SQL)
        await connection.execute(EXTRA_SEED)
        await apply_migration(connection, 67)
        yield connection


@asynccontextmanager
async def as_app(db, org=ORG, user=USER):
    async with db.transaction():
        await db.execute("SET LOCAL ROLE bracket_app")
        await db.execute(
            "SELECT set_config('app.current_organization_id',$1,true)", org
        )
        await db.execute("SELECT set_config('app.current_user_id',$1,true)", user)
        yield


async def record(
    db,
    kind="result_confirmed",
    match=MATCH,
    suspension=None,
    count=None,
    tournament=TOURNAMENT,
):
    async with as_app(db):
        return await db.fetchval(
            "SELECT record_notification($1,$2,$3,$4,$5)",
            kind,
            tournament,
            match,
            suspension,
            count,
        )


async def recipients(db, notice):
    rows = await db.fetch(
        "SELECT user_id::text, channel, outcome FROM notification_recipients WHERE notification_id=$1 ORDER BY 1,2",
        notice,
    )
    return [tuple(row) for row in rows]


async def set_preference(db, user, kind, channel, enabled, org=ORG):
    await db.execute(
        """INSERT INTO notification_preferences (organization_id,user_id,notification_type,channel,enabled)
           VALUES ($1,$2,$3,$4,$5)""",
        org,
        user,
        kind,
        channel,
        enabled,
    )


async def claim(db, function="claim_outbox_events"):
    async with as_app(db):
        return await db.fetch(f"SELECT * FROM {function}(100)")  # noqa: S608 - nombre fijo del test


async def test_tables_rls_privileges_and_functions(db):
    for table in TABLES:
        assert await db.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass",
            table,
        )
    privileges = {
        table: {
            privilege
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if await db.fetchval(
                "SELECT has_table_privilege('bracket_app',$1,$2)", table, privilege
            )
        }
        for table in TABLES
    }
    assert privileges == {
        "notifications": {"SELECT"},
        "notification_recipients": {"SELECT"},
        "notification_preferences": {"SELECT", "INSERT", "UPDATE"},
    }
    assert not await db.fetchval(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname='bracket_app'"
    )
    for name in APP_FUNCTIONS + INTERNAL_FUNCTIONS:
        row = await db.fetchrow(
            """SELECT p.prosecdef, p.proconfig,
                      EXISTS (SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0) AS public_execute,
                      has_function_privilege('bracket_app', p.oid, 'EXECUTE') AS app_execute
               FROM pg_proc p WHERE p.oid=$1::regprocedure""",
            name,
        )
        assert row["prosecdef"], name
        assert row["proconfig"] == ["search_path=pg_catalog, public"], name
        assert not row["public_execute"], name
        assert row["app_execute"] is (name in APP_FUNCTIONS), name


@pytest.mark.parametrize(
    ("kind", "match", "suspension", "count"),
    [
        ("unknown", MATCH, None, None),
        ("match_scheduled", None, None, 0),
        ("match_scheduled", MATCH, None, 2),
        ("result_confirmed", None, None, None),
        ("result_confirmed", MATCH, None, 3),
        ("walkover_declared", MATCH, SUSPENSION, None),
        ("sanction_generated", MATCH, None, None),
    ],
)
async def test_notification_shape_is_closed(db, kind, match, suspension, count):
    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            """INSERT INTO notifications (organization_id,notification_type,tournament_id,match_id,suspension_id,match_count)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            ORG,
            kind,
            TOURNAMENT,
            match,
            suspension,
            count,
        )


async def test_record_defaults_inbox_on_email_off_and_active_members_only(db):
    notice = await record(db)
    assert await recipients(db, notice) == [
        (USER, "inbox", "pending"),
        (USER_B, "inbox", "pending"),
    ]
    events = await db.fetch(
        "SELECT event_type, payload FROM outbox_events WHERE event_type LIKE 'NOTIFICATION_%'"
    )
    assert [(e["event_type"], json.loads(e["payload"])) for e in events] == [
        ("NOTIFICATION_INBOX", {"notification_id": str(notice)})
    ]
    shape = await db.fetchrow(
        "SELECT notification_type, match_id::text, match_count FROM notifications WHERE id=$1",
        notice,
    )
    assert tuple(shape) == ("result_confirmed", MATCH, None)


async def test_record_follows_preferences_per_type_and_channel(db):
    await set_preference(db, USER, "result_confirmed", "inbox", False)
    await set_preference(db, USER_B, "result_confirmed", "email", True)
    await set_preference(db, USER_B, "walkover_declared", "email", False)
    notice = await record(db)
    assert await recipients(db, notice) == [
        (USER_B, "email", "pending"),
        (USER_B, "inbox", "pending"),
    ]
    email = await db.fetchrow(
        "SELECT r.id::text, e.event_type, e.payload FROM notification_recipients r "
        "JOIN outbox_events e ON e.id=r.outbox_event_id WHERE r.channel='email'"
    )
    assert email["event_type"] == "NOTIFICATION_EMAIL"
    assert json.loads(email["payload"]) == {"recipient_id": email["id"]}
    scheduled = await record(db, "match_scheduled", None, None, 4)
    assert await recipients(db, scheduled) == [
        (USER, "inbox", "pending"),
        (USER_B, "inbox", "pending"),
    ]


async def test_record_requires_member_context_and_own_subjects(db):
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_WRITER_REQUIRED"
    ):
        async with as_app(db, user=USER_GONE):
            await db.fetchval(
                "SELECT record_notification('result_confirmed',$1,$2,NULL,NULL)",
                TOURNAMENT,
                MATCH,
            )
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_SUBJECT_REQUIRED"
    ):
        await record(db, tournament=OTHER_TOURNAMENT)
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_SUBJECT_REQUIRED"
    ):
        async with as_app(db, org=OTHER_ORG, user=OTHER_USER):
            await db.fetchval(
                "SELECT record_notification('result_confirmed',$1,$2,NULL,NULL)",
                TOURNAMENT,
                MATCH,
            )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(db):
            await db.execute(
                "INSERT INTO notifications (organization_id,notification_type,tournament_id,match_count) "
                "VALUES ($1,'match_scheduled',$2,1)",
                ORG,
                TOURNAMENT,
            )
    assert await db.fetchval("SELECT count(*) FROM notifications") == 0


async def test_rollback_of_the_fact_leaves_no_notice(db):
    with pytest.raises(RuntimeError):
        async with as_app(db):
            await db.fetchval(
                "SELECT record_notification('result_confirmed',$1,$2,NULL,NULL)",
                TOURNAMENT,
                MATCH,
            )
            raise RuntimeError("hecho revertido")
    assert await db.fetchval("SELECT count(*) FROM notifications") == 0
    assert await db.fetchval("SELECT count(*) FROM notification_recipients") == 0
    assert (
        await db.fetchval(
            "SELECT count(*) FROM outbox_events WHERE event_type LIKE 'NOTIFICATION_%'"
        )
        == 0
    )


async def test_main_claim_skips_email_and_email_claim_is_separate(db):
    await set_preference(db, USER, "result_confirmed", "email", True)
    await record(db)
    main = await claim(db)
    assert {row["event_type"] for row in main} == {"NOTIFICATION_INBOX"}
    email = await claim(db, "claim_notification_email_events")
    assert [row["event_type"] for row in email] == ["NOTIFICATION_EMAIL"]
    assert await claim(db, "claim_notification_email_events") == []


async def deliver_inbox(db, notice):
    events = [
        row["id"]
        for row in await claim(db)
        if row["event_type"] == "NOTIFICATION_INBOX"
    ]
    async with as_app(db, user=USER):
        await db.execute(
            "SELECT set_config('app.current_user_id','',true), set_config('app.current_organization_id','',true)"
        )
        return [
            await db.fetchval("SELECT deliver_notification_inbox($1)", event)
            for event in events
        ]


async def test_inbox_delivery_requires_claim_and_revalidates(db):
    notice = await record(db)
    event = await db.fetchval(
        "SELECT id FROM outbox_events WHERE event_type='NOTIFICATION_INBOX'"
    )
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_CLAIMED_EVENT_REQUIRED"
    ):
        async with as_app(db):
            await db.fetchval("SELECT deliver_notification_inbox($1)", event)
    await db.execute(
        "UPDATE organization_users SET is_active=FALSE WHERE id=$1", MEMBER_B
    )
    assert await deliver_inbox(db, notice) == [1]
    assert await recipients(db, notice) == [
        (USER, "inbox", "delivered"),
        (USER_B, "inbox", "withheld"),
    ]
    async with as_app(db):
        assert await db.fetchval("SELECT deliver_notification_inbox($1)", event) == 1
    assert await recipients(db, notice) == [
        (USER, "inbox", "delivered"),
        (USER_B, "inbox", "withheld"),
    ]


async def test_reads_are_limited_to_own_delivered_inbox(db):
    notice = await record(db)
    async with as_app(db):
        assert await db.fetchval("SELECT count(*) FROM notifications") == 0
    await deliver_inbox(db, notice)
    async with as_app(db):
        assert await db.fetchval("SELECT id FROM notifications") == notice
        assert [
            r["user_id"]
            for r in await db.fetch("SELECT user_id::text FROM notification_recipients")
        ] == [USER]
    await db.execute(
        "UPDATE notification_recipients SET outcome='withheld', delivered_at=NULL WHERE user_id=$1",
        USER_B,
    )
    async with as_app(db, user=USER_B):
        assert await db.fetchval("SELECT count(*) FROM notifications") == 0
    async with as_app(db, org=OTHER_ORG, user=OTHER_USER):
        assert await db.fetchval("SELECT count(*) FROM notifications") == 0
        assert await db.fetchval("SELECT count(*) FROM notification_recipients") == 0


async def test_mark_read_only_touches_own_delivered_inbox(db):
    first = await record(db)
    second = await record(db, "match_scheduled", None, None, 2)
    await deliver_inbox(db, first)
    async with as_app(db):
        assert (
            await db.fetchval("SELECT mark_notifications_read($1::uuid[])", [first])
            == 1
        )
        assert (
            await db.fetchval("SELECT mark_notifications_read($1::uuid[])", [first])
            == 0
        )
        assert await db.fetchval("SELECT mark_notifications_read(NULL)") == 1
    unread = await db.fetch(
        "SELECT user_id::text, notification_id FROM notification_recipients WHERE read_at IS NULL ORDER BY 1"
    )
    assert {(row["user_id"], row["notification_id"]) for row in unread} == {
        (USER_B, first),
        (USER_B, second),
    }
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_READER_REQUIRED"
    ):
        async with as_app(db, user=USER_GONE):
            await db.fetchval("SELECT mark_notifications_read(NULL)")


async def email_event(db):
    rows = await claim(db, "claim_notification_email_events")
    assert len(rows) == 1
    return rows[0]["id"]


async def test_email_payload_hides_player_and_delivery_is_single(db):
    await set_preference(db, USER_B, "sanction_generated", "email", True)
    notice = await record(db, "sanction_generated", MATCH, SUSPENSION)
    event = await email_event(db)
    async with as_app(db):
        payload = json.loads(
            await db.fetchval("SELECT notification_email_payload($1)", event)
        )
    assert payload == {
        "recipient": "member-b@example.test",
        "notification_id": str(notice),
        "type": "sanction_generated",
        "tournament_name": "Migration 031 Cup",
        "match_id": MATCH,
        "home_team_name": "Home Team",
        "away_team_name": "Away Team",
        "match_count": None,
    }
    assert "Keeper" not in json.dumps(payload)
    async with as_app(db):
        assert (
            await db.fetchval("SELECT record_notification_email_delivery($1)", event)
            is True
        )
        assert (
            await db.fetchval("SELECT record_notification_email_delivery($1)", event)
            is False
        )
        assert await db.fetchval("SELECT notification_email_payload($1)", event) is None
    assert (USER_B, "email", "delivered") in await recipients(db, notice)


async def test_email_is_withheld_when_preference_or_membership_changes(db):
    await set_preference(db, USER_B, "result_confirmed", "email", True)
    notice = await record(db)
    await db.execute(
        "UPDATE notification_preferences SET enabled=FALSE WHERE user_id=$1", USER_B
    )
    event = await email_event(db)
    async with as_app(db):
        assert await db.fetchval("SELECT notification_email_payload($1)", event) is None
    assert (USER_B, "email", "withheld") in await recipients(db, notice)
    with pytest.raises(
        asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_CLAIMED_EVENT_REQUIRED"
    ):
        inbox = await db.fetchval(
            "SELECT id FROM outbox_events WHERE event_type='NOTIFICATION_INBOX'"
        )
        async with as_app(db):
            await db.fetchval("SELECT notification_email_payload($1)", inbox)


async def test_preferences_are_own_and_require_active_membership(db):
    async with as_app(db):
        await db.execute(
            "INSERT INTO notification_preferences (organization_id,user_id,notification_type,channel,enabled) "
            "VALUES ($1,$2,'match_scheduled','email',TRUE)",
            ORG,
            USER,
        )
    for org, user, target in ((ORG, USER, USER_B), (OTHER_ORG, OTHER_USER, USER)):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with as_app(db, org=org, user=user):
                await db.execute(
                    "INSERT INTO notification_preferences (organization_id,user_id,notification_type,channel,enabled) "
                    "VALUES ($1,$2,'match_scheduled','email',TRUE)",
                    ORG,
                    target,
                )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(db, user=USER_GONE):
            await db.execute(
                "INSERT INTO notification_preferences (organization_id,user_id,notification_type,channel,enabled) "
                "VALUES ($1,$2,'match_scheduled','inbox',FALSE)",
                ORG,
                USER_GONE,
            )
    async with as_app(db, user=USER_B):
        assert await db.fetchval("SELECT count(*) FROM notification_preferences") == 0


SCHEMA_SQL = """
SELECT 'column:' || table_name || '.' || column_name || ':' || data_type || ':' || is_nullable
FROM information_schema.columns WHERE table_schema='public' AND table_name = ANY($1::text[])
UNION ALL
SELECT 'constraint:' || conrelid::regclass || ':' || conname || ':' || pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid::regclass::text = ANY($1::text[])
UNION ALL
SELECT 'index:' || indexdef FROM pg_indexes WHERE schemaname='public' AND tablename = ANY($1::text[])
UNION ALL
SELECT 'policy:' || tablename || ':' || policyname || ':' || cmd || ':' || coalesce(qual,'') || ':' || coalesce(with_check,'')
FROM pg_policies WHERE schemaname='public' AND tablename = ANY($1::text[])
UNION ALL
SELECT 'function:' || pg_get_functiondef(oid) FROM pg_proc WHERE oid = ANY($2::regprocedure[])
ORDER BY 1
"""


async def schema(db):
    rows = await db.fetch(
        SCHEMA_SQL, list(TABLES), list(APP_FUNCTIONS + INTERNAL_FUNCTIONS)
    )
    return [row[0] for row in rows]


async def test_clean_volume_matches_migrated_volume_and_reapply_is_noop(
    db, database_admin_url
):
    migrated = await schema(db)
    await apply_migration(db, 67)
    assert await schema(db) == migrated
    async with throwaway_database(database_admin_url, last=67) as clean:
        assert await schema(clean) == migrated
