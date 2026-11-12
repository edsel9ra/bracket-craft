"""Rectification storage: clean chain and 034 → 035, including tenant isolation."""

from uuid import uuid4

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
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


async def seed(connection):
    await connection.execute(SEED_SQL)
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
    """, ORG, request, MEMBER, USER)
    await connection.execute("""
        INSERT INTO match_report_rectification_decisions
            (organization_id, request_id, decision, reason, decided_by_user_id,
             decided_as, authorization_id)
        VALUES ($1, $2, 'approve', 'Verified', $3, 'platform_admin', $4)
    """, ORG, request, USER, authorization)
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
        await db.execute("UPDATE match_report_rectification_requests SET status = 'withdrawn' WHERE id = $1", request)
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
