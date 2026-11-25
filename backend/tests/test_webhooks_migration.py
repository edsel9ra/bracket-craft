"""Migración 068: webhooks firmados por organización (spec 047, T1).

Cada test crea una base desechable con los scripts ``init`` y las migraciones
numeradas reales. Se valida la cadena ya migrada (067 -> 068) y la de volumen
limpio (init + 001..068). Requiere ``RUN_DATABASE_TESTS=1`` y
``DATABASE_ADMIN_URL``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import timedelta

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import (
    MATCH,
    MEMBER,
    ORG,
    PLAYER_HOME_FIRST,
    SEED_SQL,
    TEAM_AWAY,
    TEAM_HOME,
    TOURNAMENT,
    USER,
)

KEY = "test-webhook-key-with-at-least-32-characters"
OTHER_KEY = "another-webhook-key-with-at-least-32-chars"
USER_VIEWER = "47000000-0000-4000-8000-000000000002"
MEMBER_VIEWER = "47000000-0000-4000-8000-000000000003"
OTHER_ORG = "47000000-0000-4000-8000-000000000010"
OTHER_USER = "47000000-0000-4000-8000-000000000011"
OTHER_MEMBER = "47000000-0000-4000-8000-000000000012"
SUSPENSION = "47000000-0000-4000-8000-000000000020"
PERMISSION = "MANAGE_WEBHOOKS"
EVENT_TYPES = ["match_scheduled", "result_confirmed", "walkover_declared", "sanction_generated"]

TABLES = ("organization_webhooks", "webhook_deliveries")
APP_FUNCTIONS = (
    "record_notification(text,uuid,uuid,uuid,integer)",
    "enqueue_webhook_test(uuid)",
    "discard_webhook_deliveries(uuid)",
    "webhook_claimed_delivery(uuid,text)",
    "record_webhook_attempt(uuid,text,integer)",
    "claim_outbox_events(integer)",
    "claim_webhook_delivery_events(integer)",
    "purge_webhook_deliveries(timestamp with time zone,integer)",
)
INTERNAL_FUNCTIONS = ("webhook_event_body(uuid,uuid,text,uuid,uuid,integer)",)

EXTRA_SEED = f"""
INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER_VIEWER}', 'viewer-047@example.test', 'hash', 'Viewer'),
    ('{OTHER_USER}', 'other-047@example.test', 'hash', 'Other');
INSERT INTO public.organizations (id, name, slug) VALUES ('{OTHER_ORG}', 'Other 047', 'other-047');
INSERT INTO public.organization_users (id, organization_id, user_id, is_active) VALUES
    ('{MEMBER_VIEWER}', '{ORG}', '{USER_VIEWER}', TRUE),
    ('{OTHER_MEMBER}', '{OTHER_ORG}', '{OTHER_USER}', TRUE);
INSERT INTO public.roles (organization_id, role_definition_id, name, permissions)
SELECT o.id, rd.id, rd.name, rd.system_permissions
FROM public.role_definitions rd CROSS JOIN (VALUES ('{ORG}'::uuid), ('{OTHER_ORG}'::uuid)) AS o(id);
INSERT INTO public.organization_user_roles (organization_id, organization_user_id, role_id)
SELECT r.organization_id, m.member, r.id
FROM (VALUES ('{ORG}'::uuid, '{MEMBER}'::uuid, 'owner'), ('{ORG}'::uuid, '{MEMBER_VIEWER}'::uuid, 'viewer'),
             ('{OTHER_ORG}'::uuid, '{OTHER_MEMBER}'::uuid, 'owner')) AS m(org, member, code)
JOIN public.role_definitions rd ON rd.code = m.code
JOIN public.roles r ON r.role_definition_id = rd.id AND r.organization_id = m.org;
INSERT INTO public.player_suspensions
    (id, organization_id, source_tournament_id, player_id, origin_match_id, source_type,
     dedupe_key, scope_type, matches_suspended, reason)
VALUES ('{SUSPENSION}', '{ORG}', '{TOURNAMENT}', '{PLAYER_HOME_FIRST}', '{MATCH}', 'competition_rule',
        'webhook-047', 'tournament', 1, 'test');
"""


@pytest.fixture
async def db(database_admin_url):
    async with throwaway_database(database_admin_url, last=67) as connection:
        await connection.execute(SEED_SQL)
        await connection.execute(EXTRA_SEED)
        await apply_migration(connection, 68)
        yield connection


@asynccontextmanager
async def as_app(db, org=ORG, user=USER):
    async with db.transaction():
        await db.execute("SET LOCAL ROLE bracket_app")
        await db.execute("SELECT set_config('app.current_organization_id',$1,true)", org)
        await db.execute("SELECT set_config('app.current_user_id',$1,true)", user)
        yield


async def create_webhook(db, types=None, *, org=ORG, user=USER, member=MEMBER, secret="s3cret", active=True):
    async with as_app(db, org=org, user=user):
        return str(
            await db.fetchval(
                """INSERT INTO organization_webhooks
                       (organization_id, url, event_types, is_active, secret_encrypted, created_by_member_id)
                   VALUES ($1, $2, $3, $4, pgp_sym_encrypt($5, $6), $7) RETURNING id""",
                org,
                "https://hooks.example.test/bc?x=1",
                types or EVENT_TYPES,
                active,
                secret,
                KEY,
                member,
            )
        )


async def record(db, kind="result_confirmed", match=MATCH, suspension=None, count=None):
    async with as_app(db):
        return await db.fetchval(
            "SELECT record_notification($1,$2,$3,$4,$5)", kind, TOURNAMENT, match, suspension, count
        )


async def deliveries(db):
    rows = await db.fetch(
        "SELECT id::text, webhook_id::text, event_type, status, attempts, body, outbox_event_id"
        " FROM webhook_deliveries ORDER BY created_at, id"
    )
    return [dict(row) | {"body": json.loads(row["body"])} for row in rows]


async def claim(db, function="claim_webhook_delivery_events"):
    async with as_app(db):
        return await db.fetch(f"SELECT * FROM {function}(100)")  # noqa: S608 - nombre fijo del test


async def claimed(db, key=KEY):
    rows = await claim(db)
    assert len(rows) == 1
    async with as_app(db):
        target = await db.fetchval("SELECT webhook_claimed_delivery($1,$2)", rows[0]["id"], key)
    return rows[0]["id"], json.loads(target) if target is not None else None


async def attempt(db, event, outcome, status=None):
    async with as_app(db):
        return await db.fetchval("SELECT record_webhook_attempt($1,$2,$3)", event, outcome, status)


async def test_tables_rls_column_privileges_and_functions(db):
    for table in TABLES:
        assert await db.fetchval(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=$1::regclass", table
        )
    columns = await db.fetch(
        """SELECT column_name, privilege_type FROM information_schema.column_privileges
           WHERE table_name='organization_webhooks' AND grantee='bracket_app'"""
    )
    readable = {row["column_name"] for row in columns if row["privilege_type"] == "SELECT"}
    assert "secret_encrypted" not in readable
    assert {"id", "organization_id", "url", "event_types", "is_active"} <= readable
    assert {row["column_name"] for row in columns if row["privilege_type"] == "UPDATE"} == {
        "url", "event_types", "is_active", "secret_encrypted", "updated_at",
    }
    assert await db.fetchval("SELECT has_table_privilege('bracket_app','organization_webhooks','INSERT')")
    assert await db.fetchval("SELECT has_table_privilege('bracket_app','organization_webhooks','DELETE')")
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        assert not await db.fetchval(
            "SELECT has_table_privilege('bracket_app','webhook_deliveries',$1)", privilege
        )
    assert await db.fetchval("SELECT has_table_privilege('bracket_app','webhook_deliveries','SELECT')")
    for function in APP_FUNCTIONS:
        assert await db.fetchval("SELECT has_function_privilege('bracket_app',$1,'EXECUTE')", function)
    for function in APP_FUNCTIONS + INTERNAL_FUNCTIONS:
        assert await db.fetchval("SELECT prosecdef FROM pg_proc WHERE oid=$1::regprocedure", function)
        assert not await db.fetchval("SELECT has_function_privilege('public',$1,'EXECUTE')", function)
    for function in INTERNAL_FUNCTIONS:
        assert not await db.fetchval("SELECT has_function_privilege('bracket_app',$1,'EXECUTE')", function)


async def test_permission_goes_to_owner_and_administrator_only(db):
    granted = await db.fetch(
        "SELECT code FROM role_definitions WHERE system_permissions @> $1::jsonb", f'["{PERMISSION}"]'
    )
    assert {row["code"] for row in granted} == {"owner", "administrator"}
    rows = await db.fetch(
        """SELECT rd.code FROM roles r JOIN role_definitions rd ON rd.id = r.role_definition_id
           WHERE r.organization_id=$1 AND r.permissions @> $2::jsonb""",
        ORG,
        f'["{PERMISSION}"]',
    )
    assert {row["code"] for row in rows} == {"owner", "administrator"}
    await apply_migration(db, 68)
    assert (
        await db.fetchval(
            """SELECT count(*) FROM roles r, jsonb_array_elements_text(r.permissions) p
               WHERE r.organization_id=$1 AND p=$2""",
            ORG,
            PERMISSION,
        )
        == 2
    )


@pytest.mark.parametrize(
    "url, types",
    [
        ("http://hooks.example.test/", EVENT_TYPES),
        ("https://" + "a" * 2041, EVENT_TYPES),
        ("https://hooks.example.test/", []),
        ("https://hooks.example.test/", ["webhook_test"]),
        ("https://hooks.example.test/", ["unknown"]),
    ],
)
async def test_webhook_shape_is_closed(db, url, types):
    with pytest.raises(asyncpg.CheckViolationError):
        async with as_app(db):
            await db.execute(
                """INSERT INTO organization_webhooks
                       (organization_id, url, event_types, secret_encrypted, created_by_member_id)
                   VALUES ($1,$2,$3,pgp_sym_encrypt('s',$4),$5)""",
                ORG, url, types, KEY, MEMBER,
            )


async def test_rls_isolates_webhooks_and_deliveries_and_hides_the_secret(db):
    hook = await create_webhook(db)
    await record(db)
    async with as_app(db, org=OTHER_ORG, user=OTHER_USER):
        assert await db.fetchval("SELECT count(*) FROM organization_webhooks") == 0
        assert await db.fetchval("SELECT count(*) FROM webhook_deliveries") == 0
        assert await db.execute("UPDATE organization_webhooks SET is_active=FALSE") == "UPDATE 0"
        assert await db.execute("DELETE FROM organization_webhooks") == "DELETE 0"
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(db, org=OTHER_ORG, user=OTHER_USER):
            await db.execute(
                """INSERT INTO organization_webhooks
                       (organization_id, url, event_types, secret_encrypted, created_by_member_id)
                   VALUES ($1,'https://x.test/',$2,pgp_sym_encrypt('s',$3),$4)""",
                ORG, EVENT_TYPES, KEY, MEMBER,
            )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(db):
            await db.fetchval("SELECT secret_encrypted FROM organization_webhooks WHERE id=$1", hook)
    async with as_app(db):
        assert await db.fetchval("SELECT count(*) FROM webhook_deliveries") == 1


async def test_record_creates_one_delivery_per_active_subscribed_webhook(db):
    subscribed = await create_webhook(db)
    await create_webhook(db, ["match_scheduled"])
    await create_webhook(db, active=False)
    await create_webhook(db, org=OTHER_ORG, user=OTHER_USER, member=OTHER_MEMBER)
    await db.execute("UPDATE matches SET home_score=2, away_score=1 WHERE id=$1", MATCH)
    notice = await record(db)
    rows = await deliveries(db)
    assert [(row["webhook_id"], row["event_type"], row["status"], row["attempts"]) for row in rows] == [
        (subscribed, "result_confirmed", "pending", 0)
    ]
    delivery = rows[0]
    event = await db.fetchrow("SELECT event_type, payload, status FROM outbox_events WHERE id=$1", delivery["outbox_event_id"])
    assert (event["event_type"], json.loads(event["payload"]), event["status"]) == (
        "WEBHOOK_DELIVERY", {"delivery_id": delivery["id"]}, "pending",
    )
    body = delivery["body"]
    assert body.pop("occurred_at").endswith("Z")
    assert body == {
        "id": delivery["id"],
        "type": "result_confirmed",
        "organization_id": ORG,
        "tournament_id": TOURNAMENT,
        "match_id": MATCH,
        "data": {
            "tournament_name": "Migration 031 Cup",
            "home_team": {"id": TEAM_HOME, "name": "Home Team"},
            "away_team": {"id": TEAM_AWAY, "name": "Away Team"},
            "home_score": 2,
            "away_score": 1,
        },
    }
    assert await db.fetchval("SELECT notification_id FROM webhook_deliveries") == notice


async def test_bodies_by_type_hide_the_sanctioned_player(db):
    await create_webhook(db)
    await db.execute(
        "UPDATE matches SET home_score=3, away_score=0, winner_team_id=$2 WHERE id=$1", MATCH, TEAM_HOME
    )
    await record(db, "match_scheduled", None, None, 6)
    await record(db, "walkover_declared")
    await record(db, "sanction_generated", MATCH, SUSPENSION)
    scheduled, walkover, sanction = [row["body"] for row in await deliveries(db)]
    assert "match_id" not in scheduled
    assert scheduled["data"] == {"tournament_name": "Migration 031 Cup", "match_count": 6}
    assert walkover["data"]["winner_team_id"] == TEAM_HOME
    assert walkover["data"]["home_score"] == 3
    assert sanction["match_id"] == MATCH
    assert sanction["data"] == {"tournament_name": "Migration 031 Cup"}
    text = json.dumps(sanction)
    assert PLAYER_HOME_FIRST not in text and "Keeper" not in text and TEAM_HOME not in text


async def test_rollback_of_the_fact_leaves_no_delivery(db):
    await create_webhook(db)
    with pytest.raises(RuntimeError):
        async with as_app(db):
            await db.fetchval("SELECT record_notification('result_confirmed',$1,$2,NULL,NULL)", TOURNAMENT, MATCH)
            raise RuntimeError
    assert await db.fetchval("SELECT count(*) FROM webhook_deliveries") == 0
    assert await db.fetchval("SELECT count(*) FROM outbox_events WHERE event_type='WEBHOOK_DELIVERY'") == 0


async def test_main_claim_skips_webhooks_and_webhook_claim_is_separate(db):
    await create_webhook(db)
    await record(db)
    main = await claim(db, "claim_outbox_events")
    assert {row["event_type"] for row in main} == {"NOTIFICATION_INBOX"}
    email = await claim(db, "claim_notification_email_events")
    assert email == []
    hooks = await claim(db)
    assert [row["event_type"] for row in hooks] == ["WEBHOOK_DELIVERY"]
    assert await claim(db) == []


async def test_claimed_delivery_requires_claim_and_signs_with_current_secret(db):
    hook = await create_webhook(db, secret="first")
    await record(db)
    event = await db.fetchval("SELECT id FROM outbox_events WHERE event_type='WEBHOOK_DELIVERY'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="NOTIFICATION_CLAIMED_EVENT_REQUIRED"):
        async with as_app(db):
            await db.fetchval("SELECT webhook_claimed_delivery($1,$2)", event, KEY)
    async with as_app(db):
        await db.execute(
            "UPDATE organization_webhooks SET secret_encrypted=pgp_sym_encrypt('second',$2) WHERE id=$1", hook, KEY
        )
    event, target = await claimed(db)
    delivery = (await deliveries(db))[0]
    assert target == {
        "delivery_id": delivery["id"],
        "url": "https://hooks.example.test/bc?x=1",
        "secret": "second",
        "event_type": "result_confirmed",
        "body": delivery["body"],
    }
    with pytest.raises(asyncpg.PostgresError):
        async with as_app(db):
            await db.fetchval("SELECT webhook_claimed_delivery($1,$2)", event, OTHER_KEY)


async def test_inactive_or_unsubscribed_webhook_discards_at_delivery(db):
    hook = await create_webhook(db)
    await record(db)
    async with as_app(db):
        await db.execute("UPDATE organization_webhooks SET event_types=ARRAY['match_scheduled'] WHERE id=$1", hook)
    _, target = await claimed(db)
    assert target is None
    assert [row["status"] for row in await deliveries(db)] == ["discarded"]


async def test_attempts_follow_backoff_and_stop_at_six(db):
    await create_webhook(db)
    await record(db)
    waits = []
    for number in range(1, 7):
        event, target = await claimed(db)
        assert target is not None
        result = await attempt(db, event, "failed", 503)
        row = await db.fetchrow(
            "SELECT status, attempts, available_at - CURRENT_TIMESTAMP AS wait, last_error FROM outbox_events WHERE id=$1",
            event,
        )
        delivery = (await deliveries(db))[0]
        assert delivery["attempts"] == number
        if number < 6:
            assert (result, row["status"], delivery["status"]) == ("pending", "pending", "pending")
            waits.append(round(row["wait"] / timedelta(minutes=1)))
            await db.execute("UPDATE outbox_events SET available_at=CURRENT_TIMESTAMP WHERE id=$1", event)
        else:
            assert (result, row["status"], delivery["status"]) == ("failed", "processed", "failed")
    assert waits == [1, 5, 15, 30, 120]
    assert await db.fetchval("SELECT last_status_code FROM webhook_deliveries") == 503
    assert await claim(db) == []


@pytest.mark.parametrize("outcome, status", [("delivered", "delivered"), ("rejected", "rejected")])
async def test_delivered_and_rejected_are_final(db, outcome, status):
    await create_webhook(db)
    await record(db)
    event, _ = await claimed(db)
    assert await attempt(db, event, outcome, 204 if outcome == "delivered" else None) == status
    assert await db.fetchval("SELECT status FROM outbox_events WHERE id=$1", event) == "processed"
    assert [row["status"] for row in await deliveries(db)] == [status]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await attempt(db, event, "failed", 500)


async def test_unknown_outcome_is_rejected(db):
    await create_webhook(db)
    await record(db)
    event, _ = await claimed(db)
    with pytest.raises(asyncpg.PostgresError, match="WEBHOOK_ATTEMPT_OUTCOME"):
        await attempt(db, event, "maybe")


async def test_discard_marks_pending_and_requires_permission(db):
    hook = await create_webhook(db)
    await record(db)
    await record(db, "match_scheduled", None, None, 2)
    for org, user, error in (
        (ORG, USER_VIEWER, "WEBHOOK_MANAGER_REQUIRED"),
        (OTHER_ORG, OTHER_USER, "WEBHOOK_NOT_FOUND"),
    ):
        with pytest.raises(asyncpg.PostgresError, match=error):
            async with as_app(db, org=org, user=user):
                await db.fetchval("SELECT discard_webhook_deliveries($1)", hook)
    async with as_app(db):
        assert await db.fetchval("SELECT discard_webhook_deliveries($1)", hook) == 2
        assert await db.fetchval("SELECT discard_webhook_deliveries($1)", hook) == 0
    assert {row["status"] for row in await deliveries(db)} == {"discarded"}
    assert await claim(db) == []
    async with as_app(db):
        await db.execute("UPDATE organization_webhooks SET is_active=TRUE WHERE id=$1", hook)
    assert await claim(db) == []


async def test_discard_of_another_organization_webhook_is_not_found(db):
    foreign = await create_webhook(db, org=OTHER_ORG, user=OTHER_USER, member=OTHER_MEMBER)
    with pytest.raises(asyncpg.PostgresError, match="WEBHOOK_NOT_FOUND"):
        async with as_app(db):
            await db.fetchval("SELECT discard_webhook_deliveries($1)", foreign)


async def test_test_delivery_has_no_fact_and_requires_an_active_own_webhook(db):
    hook = await create_webhook(db, ["match_scheduled"])
    async with as_app(db):
        delivery = str(await db.fetchval("SELECT enqueue_webhook_test($1)", hook))
    [row] = await deliveries(db)
    body = row["body"]
    body.pop("occurred_at")
    assert (row["id"], row["event_type"]) == (delivery, "webhook_test")
    assert body == {"id": delivery, "type": "webhook_test", "organization_id": ORG, "data": {}}
    _, target = await claimed(db)
    assert target["event_type"] == "webhook_test"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="WEBHOOK_MANAGER_REQUIRED"):
        async with as_app(db, user=USER_VIEWER):
            await db.fetchval("SELECT enqueue_webhook_test($1)", hook)
    foreign = await create_webhook(db, org=OTHER_ORG, user=OTHER_USER, member=OTHER_MEMBER)
    with pytest.raises(asyncpg.PostgresError, match="WEBHOOK_NOT_FOUND"):
        async with as_app(db):
            await db.fetchval("SELECT enqueue_webhook_test($1)", foreign)
    async with as_app(db):
        await db.execute("UPDATE organization_webhooks SET is_active=FALSE WHERE id=$1", hook)
    with pytest.raises(asyncpg.PostgresError, match="WEBHOOK_INACTIVE"):
        async with as_app(db):
            await db.fetchval("SELECT enqueue_webhook_test($1)", hook)


async def test_deleting_the_webhook_removes_its_deliveries_and_the_event_is_dropped(db):
    hook = await create_webhook(db)
    await record(db)
    async with as_app(db):
        assert await db.execute("DELETE FROM organization_webhooks WHERE id=$1", hook) == "DELETE 1"
    assert await deliveries(db) == []
    _, target = await claimed(db)
    assert target is None


async def test_purge_keeps_recent_and_pending_deliveries(db):
    await create_webhook(db)
    await record(db)
    await record(db, "match_scheduled", None, None, 2)
    first, second = await deliveries(db)
    await db.execute("UPDATE webhook_deliveries SET status='delivered' WHERE id=$1", first["id"])
    await db.execute("UPDATE webhook_deliveries SET created_at = CURRENT_TIMESTAMP - INTERVAL '31 days'")
    async with as_app(db):
        assert await db.fetchval(
            "SELECT purge_webhook_deliveries(CURRENT_TIMESTAMP - INTERVAL '30 days', 500)"
        ) == 1
    assert [row["id"] for row in await deliveries(db)] == [second["id"]]
    with pytest.raises(asyncpg.PostgresError):
        async with as_app(db):
            await db.fetchval("SELECT purge_webhook_deliveries(NULL, 500)")


async def test_outbox_retention_keeps_the_delivery_history(db):
    await create_webhook(db)
    await record(db)
    event, _ = await claimed(db)
    await attempt(db, event, "delivered", 200)
    await db.execute("UPDATE outbox_events SET processed_at=CURRENT_TIMESTAMP - INTERVAL '8 days' WHERE id=$1", event)
    async with as_app(db):
        await db.fetchrow(
            "SELECT * FROM purge_retained_records(CURRENT_TIMESTAMP, CURRENT_TIMESTAMP - INTERVAL '7 days', 500)"
        )
    [row] = await deliveries(db)
    assert (row["status"], row["outbox_event_id"]) == ("delivered", None)


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
SELECT 'grant:' || table_name || '.' || column_name || ':' || privilege_type
FROM information_schema.column_privileges WHERE grantee='bracket_app' AND table_name = ANY($1::text[])
UNION ALL
SELECT 'function:' || pg_get_functiondef(oid) FROM pg_proc WHERE oid = ANY($2::regprocedure[])
UNION ALL
SELECT 'role:' || code || ':' || (system_permissions @> '["MANAGE_WEBHOOKS"]'::jsonb)::text FROM role_definitions
ORDER BY 1
"""


async def schema(db):
    rows = await db.fetch(SCHEMA_SQL, list(TABLES), list(APP_FUNCTIONS + INTERNAL_FUNCTIONS))
    return [row[0] for row in rows]


async def test_clean_volume_matches_migrated_volume_and_reapply_is_noop(db, database_admin_url):
    migrated = await schema(db)
    await apply_migration(db, 68)
    assert await schema(db) == migrated
    async with throwaway_database(database_admin_url, last=68) as clean:
        assert await schema(clean) == migrated
