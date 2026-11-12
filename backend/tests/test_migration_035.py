"""Rectification storage: clean chain and 034 → 035, including tenant isolation."""

import json

from uuid import uuid4

import asyncpg
import pytest

from migration_helpers import apply_migration, migration_path, throwaway_database
from test_migration_031 import MATCH, MEMBER, ORG, SEED_SQL, SEGMENT_FIRST, TEAM_HOME, USER, PLAYER_HOME_FIRST

APPEND_ONLY = (
    "match_report_rectification_decisions",
    "match_report_versions",
    "match_report_version_events",
    "match_report_rectification_effects",
    "match_report_rectification_notifications",
    "player_suspension_annulments",
)
MUTABLE = {
    "match_report_rectification_requests": {"status", "withdrawn_at", "resulting_version_id"},
    "match_report_platform_authorizations": {"revoked_at", "consumed_at"},
    "competitive_impact_procedures": {"status", "resolution", "reason", "closed_by_user_id", "closed_at"},
}
TABLES = (*APPEND_ONLY, *MUTABLE)


async def seed(connection, *, include_decision=True):
    await connection.execute(SEED_SQL)
    approver = await connection.fetchval("""
        INSERT INTO users (email, full_name) VALUES ('approver-035@example.test', 'Approver') RETURNING id
    """)
    request = await connection.fetchval("""
        INSERT INTO match_report_rectification_requests
            (organization_id, match_id, base_version_number, proposed_report, reason,
             evidence, requested_by_user_id, requested_by_member_id)
        VALUES ($1, $2, 1, '{}', 'Correction', 'Score sheet', $3, $4) RETURNING id
    """, ORG, MATCH, USER, MEMBER)
    version = await connection.fetchval("""
        INSERT INTO match_report_versions
            (organization_id, match_id, version_number, supersedes_version_number,
             resolution_type, home_score_regular, away_score_regular, home_score,
             away_score, request_id, published_by_user_id)
        VALUES ($1, $2, 2, 1, 'regular', 1, 0, 1, 0, $3, $4) RETURNING id
    """, ORG, MATCH, request, USER)
    authorization = await connection.fetchval("""
        INSERT INTO match_report_platform_authorizations
            (organization_id, request_id, granted_by_member_id, platform_admin_user_id, reason)
        VALUES ($1, $2, $3, $4, 'Owner authorization') RETURNING id
    """, ORG, request, MEMBER, approver)
    if include_decision:
        await connection.execute("""
        INSERT INTO match_report_rectification_decisions
            (organization_id, request_id, decision, reason, decided_by_user_id,
             decided_as, authorization_id)
        VALUES ($1, $2, 'approve', 'Verified', $3, 'platform_admin', $4)
        """, ORG, request, approver, authorization)
    await connection.execute("""
        INSERT INTO match_report_version_events
            (organization_id, version_id, match_id, segment_id, team_id, player_id,
             event_type, minute, client_event_id)
        VALUES ($1, $2, $3, $4, $5, $6, 'goal', 10, 'goal-1')
    """, ORG, version, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST)
    await connection.execute("""
        INSERT INTO match_report_rectification_effects
            (organization_id, version_id, effect_type, entity_type, entity_id, payload)
        VALUES ($1, $2, 'standings', 'matches', $3, '{}')
    """, ORG, version, MATCH)
    outbox = await connection.fetchval("""
        INSERT INTO outbox_events (organization_id, event_type, payload)
        VALUES ($1, 'MATCH_REPORT_RECTIFIED', '{}') RETURNING id
    """, ORG)
    await connection.execute("""
        INSERT INTO match_report_rectification_notifications
            (organization_id, request_id, channel, notification_type, outbox_event_id)
        VALUES ($1, $2, 'realtime', 'MATCH_REPORT_RECTIFIED', $3)
    """, ORG, request, outbox)
    await connection.execute("DELETE FROM outbox_events WHERE id = $1", outbox)
    assert await connection.fetchval("SELECT outbox_event_id FROM match_report_rectification_notifications") == outbox
    await connection.execute("""
        INSERT INTO competitive_impact_procedures
            (organization_id, version_id, match_id, affected_items)
        VALUES ($1, $2, $3, '[]')
    """, ORG, version, MATCH)
    suspension = await connection.fetchval("""
        INSERT INTO player_suspensions
            (organization_id, source_tournament_id, player_id, source_type,
             dedupe_key, scope_type, matches_suspended, reason)
        SELECT organization_id, tournament_id, $2, 'competition_rule',
               'migration-035', 'tournament', 1, 'Rule'
        FROM matches WHERE id = $1 RETURNING id
    """, MATCH, PLAYER_HOME_FIRST)
    await connection.execute("""
        INSERT INTO player_suspension_annulments
            (organization_id, suspension_id, version_id, reason)
        VALUES ($1, $2, $3, 'Corrected report')
    """, ORG, suspension, version)
    return request


@pytest.mark.parametrize("incremental", [False, True], ids=["clean", "034-to-035"])
async def test_035_storage_contract(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=34 if incremental else 0) as db:
        if incremental:
            for table in TABLES:
                assert await db.fetchval("SELECT to_regclass($1)", f"public.{table}") is None
            await apply_migration(db, 35)
        else:
            for number in range(1, 36):
                await apply_migration(db, number)

        for table in TABLES:
            flags = await db.fetchrow("""
                SELECT relrowsecurity, relforcerowsecurity FROM pg_class
                WHERE oid = to_regclass($1)
            """, f"public.{table}")
            assert flags is not None and all(flags)
            policy = await db.fetchrow("""
                SELECT cmd, qual, with_check FROM pg_policies
                WHERE schemaname = 'public' AND tablename = $1
            """, table)
            assert policy["cmd"] == "ALL"
            for expression in (policy["qual"], policy["with_check"]):
                assert "app.current_organization_id" in expression
                assert "fn_verify_user_org_membership" in expression
            for privilege in ("SELECT", "INSERT"):
                assert await db.fetchval("SELECT has_table_privilege('bracket_app', $1, $2)", table, privilege)
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not await db.fetchval("SELECT has_table_privilege('bracket_app', $1, $2)", table, privilege)
            columns = await db.fetch("""
                SELECT column_name FROM information_schema.column_privileges
                WHERE grantee = 'bracket_app' AND table_name = $1 AND privilege_type = 'UPDATE'
            """, table)
            assert {row["column_name"] for row in columns} == MUTABLE.get(table, set())

        event_columns = await db.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'match_events'
            EXCEPT
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'match_report_version_events'
        """)
        assert not event_columns

        request = await seed(db)
        for table in APPEND_ONLY:
            for statement in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
                with pytest.raises(asyncpg.CheckViolationError, match="append-only"):
                    await db.execute(statement)

        insert_request = """
            INSERT INTO match_report_rectification_requests
                (organization_id, match_id, base_version_number, proposed_report,
                 reason, requested_by_user_id, requested_by_member_id)
            VALUES ($1, $2, 1, '{}', 'Correction', $3, $4)
        """
        with pytest.raises(asyncpg.UniqueViolationError):
            await db.execute(insert_request, ORG, MATCH, USER, MEMBER)
        await db.execute("UPDATE match_report_rectification_requests SET status = 'withdrawn', withdrawn_at = CURRENT_TIMESTAMP WHERE id = $1", request)
        await db.execute(insert_request, ORG, MATCH, USER, MEMBER)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute("UPDATE match_report_rectification_requests SET status = 'unknown'")

        other_org = uuid4()
        await db.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Other', 'other-035')", other_org)
        await db.execute("UPDATE match_report_rectification_requests SET status = 'rejected' WHERE status = 'pending'")
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await db.execute(insert_request, other_org, MATCH, USER, MEMBER)

        rows = {
            table: await db.fetchval(f"SELECT row_to_json(t)::text FROM {table} t LIMIT 1")
            for table in TABLES
        }

        async with db.transaction():
            await db.execute("SET LOCAL ROLE bracket_app")
            for table in TABLES:
                assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0
            await db.execute("SELECT set_config('app.current_organization_id', $1, true), set_config('app.current_user_id', $2, true)", ORG, USER)
            for table in TABLES:
                assert await db.fetchval(f"SELECT count(*) FROM {table}") > 0
            await db.execute(insert_request, ORG, MATCH, USER, MEMBER)
            await db.execute("SELECT set_config('app.current_user_id', $1, true)", str(uuid4()))
            for table in TABLES:
                assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0
            await db.execute("SELECT set_config('app.current_user_id', $1, true)", USER)
            await db.execute("SELECT set_config('app.current_organization_id', $1, true)", str(other_org))
            for table in TABLES:
                assert await db.fetchval(f"SELECT count(*) FROM {table}") == 0
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    async with db.transaction():
                        await db.execute(
                            f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, $1::jsonb)).*",
                            rows[table],
                        )

PERMISSIONS = ("REQUEST_MATCH_REPORT_RECTIFICATION", "APPROVE_MATCH_REPORT_RECTIFICATION")


async def expect_rejected(db, sql, *args, code="23514", message="RECTIFICATION_INVALID_TRANSITION"):
    with pytest.raises(asyncpg.PostgresError, match=message) as error:
        async with db.transaction():
            await db.execute(sql, *args)
    assert error.value.sqlstate == code


@pytest.mark.parametrize("decided_as", ["member", "platform_admin"])
@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_035_self_decision_rejected(database_admin_url, decided_as, decision):
    async with throwaway_database(database_admin_url, last=35) as db:
        request = await seed(db, include_decision=False)
        await expect_rejected(db, """
            INSERT INTO match_report_rectification_decisions
                (organization_id, request_id, decision, reason, decided_by_user_id,
                 decided_by_member_id, decided_as)
            VALUES ($1, $2, $3, 'Checked', $4, $5, $6)
        """, ORG, request, decision, USER, MEMBER if decided_as == "member" else None,
            decided_as, code="42501", message="RECTIFICATION_SELF_APPROVAL")
        assert await db.fetchval("SELECT count(*) FROM match_report_rectification_decisions") == 0
        approver = await db.fetchval("SELECT id FROM users WHERE email = 'approver-035@example.test'")
        await db.execute("""
            INSERT INTO match_report_rectification_decisions
                (organization_id, request_id, decision, reason, decided_by_user_id, decided_as)
            VALUES ($1, $2, $3, 'Checked', $4, $5)
        """, ORG, request, decision, approver, decided_as)
        assert await db.fetchval("SELECT count(*) FROM match_report_rectification_decisions") == 1


@pytest.mark.parametrize("status", ["rejected", "withdrawn", "published"])
async def test_035_request_transitions(database_admin_url, status):
    async with throwaway_database(database_admin_url, last=35) as db:
        request = await seed(db)
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET reason = 'Changed'")
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET status = status")
        await expect_rejected(db, """
            UPDATE match_report_rectification_requests
            SET status = 'rejected', proposed_report = '{"home_score": 2}'
        """)
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET status = 'withdrawn'")
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET status = 'published'")
        version = await db.fetchval("SELECT id FROM match_report_versions")
        await expect_rejected(db, """
            UPDATE match_report_rectification_requests
            SET status = 'rejected', withdrawn_at = CURRENT_TIMESTAMP, resulting_version_id = $1
        """, version)
        await db.execute("""
            UPDATE match_report_rectification_requests SET status = $1::varchar,
                withdrawn_at = CASE WHEN $1::varchar = 'withdrawn' THEN CURRENT_TIMESTAMP END,
                resulting_version_id = CASE WHEN $1::varchar = 'published' THEN $2::uuid END
            WHERE id = $3
        """, status, version, request)
        assert await db.fetchval("SELECT status FROM match_report_rectification_requests") == status
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET status = 'pending'")
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET status = status")
        await expect_rejected(db, "UPDATE match_report_rectification_requests SET reason = 'Changed'")


@pytest.mark.parametrize("column", ["revoked_at", "consumed_at"])
async def test_035_authorization_transitions(database_admin_url, column):
    async with throwaway_database(database_admin_url, last=35) as db:
        await seed(db)
        await expect_rejected(db, "UPDATE match_report_platform_authorizations SET reason = 'Changed'")
        await expect_rejected(db, "UPDATE match_report_platform_authorizations SET revoked_at = revoked_at")
        await expect_rejected(db, """
            UPDATE match_report_platform_authorizations
            SET revoked_at = CURRENT_TIMESTAMP, consumed_at = CURRENT_TIMESTAMP
        """)
        await expect_rejected(db, f"""
            UPDATE match_report_platform_authorizations
            SET {column} = CURRENT_TIMESTAMP, reason = 'Changed'
        """)
        await db.execute(f"UPDATE match_report_platform_authorizations SET {column} = CURRENT_TIMESTAMP")
        assert await db.fetchval(f"SELECT {column} IS NOT NULL FROM match_report_platform_authorizations")
        await expect_rejected(db, f"UPDATE match_report_platform_authorizations SET {column} = CURRENT_TIMESTAMP")
        await expect_rejected(db, f"UPDATE match_report_platform_authorizations SET {column} = NULL")
        other = "consumed_at" if column == "revoked_at" else "revoked_at"
        await expect_rejected(db, f"UPDATE match_report_platform_authorizations SET {other} = CURRENT_TIMESTAMP")


async def test_035_impact_transitions(database_admin_url):
    async with throwaway_database(database_admin_url, last=35) as db:
        await seed(db)
        await expect_rejected(db, "UPDATE competitive_impact_procedures SET affected_items = '[{}]'")
        await expect_rejected(db, "UPDATE competitive_impact_procedures SET status = status")
        valid = """
            UPDATE competitive_impact_procedures SET status = 'closed',
                resolution = 'keep_as_played', reason = 'Keep results',
                closed_by_user_id = $1, closed_at = CURRENT_TIMESTAMP
        """
        for defect in (
            "resolution = NULL", "reason = NULL", "reason = ''", "reason = '   '",
            "closed_by_user_id = NULL", "closed_at = NULL",
        ):
            field = defect.split(" = ")[0]
            original = {
                "resolution": "resolution = 'keep_as_played'",
                "reason": "reason = 'Keep results'",
                "closed_by_user_id": "closed_by_user_id = $1",
                "closed_at": "closed_at = CURRENT_TIMESTAMP",
            }[field]
            statement = valid.replace(original, defect)
            await expect_rejected(db, statement, *(() if field == "closed_by_user_id" else (USER,)))
        await expect_rejected(db, valid + ", affected_items = '[{}]'", USER)
        await db.execute(valid, USER)
        assert await db.fetchval("SELECT status FROM competitive_impact_procedures") == "closed"
        await expect_rejected(db, "UPDATE competitive_impact_procedures SET status = 'open'")
        await expect_rejected(db, "UPDATE competitive_impact_procedures SET reason = 'Changed'")


@pytest.mark.parametrize("incremental", [False, True], ids=["clean", "034-to-035"])
async def test_035_permissions(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=34 if incremental else 0) as db:
        await db.execute("INSERT INTO organizations (id, name, slug) VALUES ($1, 'Permissions', 'permissions-035')", ORG)
        await db.execute("""
            INSERT INTO roles (organization_id, role_definition_id, name, permissions)
            SELECT $1, id, code,
                CASE WHEN code = 'owner' THEN '["REQUEST_MATCH_REPORT_RECTIFICATION"]'::jsonb
                     WHEN code = 'administrator' THEN '["APPROVE_MATCH_REPORT_RECTIFICATION"]'::jsonb
                     ELSE '[]'::jsonb END
            FROM role_definitions
        """, ORG)
        before = {
            row["code"]: row["system_permissions"]
            for row in await db.fetch("SELECT code, system_permissions FROM role_definitions")
        }
        if not incremental:
            for number in range(1, 35):
                await apply_migration(db, number)
        await apply_migration(db, 35)
        rows = await db.fetch("""
            SELECT rd.code, rd.system_permissions, r.permissions
            FROM role_definitions rd JOIN roles r ON r.role_definition_id = rd.id
        """)
        for row in rows:
            definition = json.loads(row["system_permissions"])
            role = json.loads(row["permissions"])
            for permission in PERMISSIONS:
                expected = 1 if row["code"] in {"owner", "administrator"} else 0
                assert definition.count(permission) == expected
                assert role.count(permission) == expected
            assert set(json.loads(before[row["code"]])) <= set(definition)
        sql = migration_path(35).read_text()
        marker = "$rectification_permissions$"
        permission_block = "DO " + marker + sql.split(marker)[1] + marker + ";"
        await db.execute(permission_block)
        await db.execute(permission_block)
        after = await db.fetch("""
            SELECT rd.code, rd.system_permissions, r.permissions
            FROM role_definitions rd JOIN roles r ON r.role_definition_id = rd.id
        """)
        assert sorted(map(tuple, after)) == sorted(map(tuple, rows))
