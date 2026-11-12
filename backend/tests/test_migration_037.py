"""037 adds immutable suspension provenance without rewriting existing sanctions."""

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MATCH, MEMBER, ORG, PLAYER_AWAY, PLAYER_HOME_FIRST, SEGMENT_FIRST, TEAM_HOME, TOURNAMENT
from test_migration_035 import seed


@pytest.mark.parametrize("incremental", [False, True])
async def test_migration_037_clean_and_incremental(database_admin_url, incremental):
    async with throwaway_database(database_admin_url, last=36 if incremental else 37) as db:
        await seed(db)
        old_id = await db.fetchval("""INSERT INTO player_suspensions (organization_id, source_tournament_id,
            player_id, origin_match_id, source_type, dedupe_key, scope_type, matches_suspended, reason)
            VALUES ($1,$2,$3,$4,'competition_rule','historical','tournament',1,'historical') RETURNING id""", ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH)
        before = dict(await db.fetchrow("SELECT * FROM player_suspensions WHERE id=$1", old_id))
        if incremental:
            await apply_migration(db, 37)
        after = dict(await db.fetchrow("SELECT * FROM player_suspensions WHERE id=$1", old_id))
        assert all(after[key] == value for key, value in before.items())
        assert after["source_version_event_id"] is None
        assert "match_events" in await db.fetchval("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='fk_player_suspensions_source_event'")
        for column, value in [("reason", "'changed'"), ("matches_suspended", "2"), ("created_at", "now() + interval '1 day'"), ("dedupe_key", "'replacement'")]:
            with pytest.raises(asyncpg.CheckViolationError):
                await db.execute(f"UPDATE player_suspensions SET {column}={value} WHERE id=$1", old_id)
        await db.execute("UPDATE player_suspensions SET status='served' WHERE id=$1", old_id)
        event = await db.fetchval("SELECT id FROM match_report_version_events WHERE organization_id=$1", ORG)
        new_id = await db.fetchval("""INSERT INTO player_suspensions (organization_id, source_tournament_id,
            player_id, origin_match_id, source_type, source_version_event_id, dedupe_key, scope_type, matches_suspended, reason)
            VALUES ($1,$2,$3,$4,'match_event',$5,'versioned','organization',1,'direct_red_card') RETURNING id""", ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH, event)
        assert await db.fetchval("SELECT source_event_id IS NULL FROM player_suspensions WHERE id=$1", new_id)
        await db.execute("""INSERT INTO rosters
            (organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
            VALUES ($1,$2,$3,$4,1,now(),now())""", ORG, TOURNAMENT, TEAM_HOME, PLAYER_HOME_FIRST)
        await db.execute("""INSERT INTO match_rosters
            (organization_id,match_id,roster_id,player_id,team_id,tournament_id,role)
            SELECT organization_id,$1,id,player_id,team_id,tournament_id,'starter' FROM rosters""", MATCH)
        original_event = await db.fetchval("""INSERT INTO match_events
            (organization_id,match_id,segment_id,team_id,player_id,event_type,minute,client_event_id)
            VALUES ($1,$2,$3,$4,$5,'red_card',30,'original-red') RETURNING id""", ORG, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST)
        await db.execute("""INSERT INTO player_suspensions
            (organization_id,source_tournament_id,player_id,origin_match_id,source_event_id,source_type,
             dedupe_key,scope_type,matches_suspended,reason)
            VALUES ($1,$2,$3,$4,$5,'match_event','original','organization',1,'direct_red_card')""",
            ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH, original_event)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute("""INSERT INTO player_suspensions
                (organization_id,source_tournament_id,player_id,origin_match_id,source_event_id,source_version_event_id,
                 source_type,dedupe_key,scope_type,matches_suspended,reason)
                VALUES ($1,$2,$3,$4,$5,$6,'match_event','both','organization',1,'red')""",
                ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH, original_event, event)
        with pytest.raises(asyncpg.ForeignKeyViolationError) as mismatch:
            await db.execute("""INSERT INTO player_suspensions
                (organization_id,source_tournament_id,player_id,origin_match_id,source_version_event_id,
                 source_type,dedupe_key,scope_type,matches_suspended,reason)
                VALUES ($1,$2,$3,$4,$5,'match_event','wrong-player','organization',1,'red')""",
                ORG, TOURNAMENT, PLAYER_AWAY, MATCH, event)
        assert mismatch.value.constraint_name == "fk_player_suspensions_version_event"
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute("""INSERT INTO player_suspensions (organization_id, source_tournament_id, player_id,
                origin_match_id, source_type, dedupe_key, scope_type, matches_suspended, reason)
                VALUES ($1,$2,$3,$4,'match_event','missing','organization',1,'red')""", ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await db.execute("""INSERT INTO player_suspensions (organization_id, source_tournament_id, player_id,
                origin_match_id, source_type, source_version_event_id, dedupe_key, scope_type, matches_suspended, reason)
                VALUES ($1,$2,$3,$4,'match_event',gen_random_uuid(),'unknown','organization',1,'red')""", ORG, TOURNAMENT, PLAYER_HOME_FIRST, MATCH)


async def test_037_backfills_first_original_audit_and_preserves_unknown_time(database_admin_url):
    async with throwaway_database(database_admin_url, last=36) as db:
        await seed(db)
        await db.execute("UPDATE matches SET result_confirmed=TRUE WHERE id=$1", MATCH)
        await db.execute("""INSERT INTO administrative_audit_logs
            (organization_id,entity_type,entity_id,action,payload,performed_by_member_id,performed_at)
            VALUES ($1,'matches',$2,'CLOSE_MATCH_REPORT','{}',$3,'2026-02-02'),
                   ($1,'matches',$2,'ADMINISTRATIVE_MATCH_RESOLUTION','{}',$3,'2026-02-01')""", ORG, MATCH, MEMBER)
        old = dict(await db.fetchrow("SELECT * FROM matches WHERE id=$1", MATCH))
        await apply_migration(db, 37)
        row = dict(await db.fetchrow("SELECT * FROM matches WHERE id=$1", MATCH))
        assert {key: value for key, value in row.items() if key != "original_report_confirmed_at"} == old
        assert row["original_report_confirmed_at"].isoformat() == "2026-02-01T00:00:00+00:00"
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute("UPDATE matches SET original_report_confirmed_at=NULL WHERE id=$1", MATCH)


async def test_037_confirmation_and_suspensions_share_transaction_time(database_admin_url):
    async with throwaway_database(database_admin_url, last=37) as db:
        await seed(db)
        async with db.transaction():
            await db.execute("UPDATE matches SET result_confirmed=TRUE WHERE id=$1", MATCH)
            confirmed = await db.fetchval("SELECT original_report_confirmed_at FROM matches WHERE id=$1", MATCH)
            created = await db.fetchval("""INSERT INTO player_suspensions
                (organization_id,source_tournament_id,player_id,source_type,dedupe_key,scope_type,matches_suspended,reason)
                VALUES ($1,$2,$3,'competition_rule','same-transaction','organization',1,'test') RETURNING created_at""",
                ORG, TOURNAMENT, PLAYER_HOME_FIRST)
            assert confirmed == created == await db.fetchval("SELECT now()")
        for expression in ["NULL", "now() + interval '1 day'"]:
            with pytest.raises(asyncpg.CheckViolationError):
                await db.execute(f"UPDATE matches SET original_report_confirmed_at={expression} WHERE id=$1", MATCH)
