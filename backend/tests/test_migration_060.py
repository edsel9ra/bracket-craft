"""060 añade segment_id al final de v_public_match_events (spec 037, T1)."""

from migration_helpers import apply_migration, throwaway_database
from test_migration_030 import EVENT, EVENTS_VIEW, SEED_SQL, view_columns

PREVIOUS_COLUMNS = [
    "id", "match_id", "tournament_id", "team_id", "player_id", "event_type",
    "minute", "added_minute", "player_out_id", "player_in_id",
    "beneficiary_team_id", "metadata", "is_voided",
]


async def test_060_appends_segment_id_after_existing_columns(database_admin_url):
    async with throwaway_database(database_admin_url, last=60) as db:
        assert await view_columns(db, EVENTS_VIEW) == [*PREVIOUS_COLUMNS, "segment_id"]


async def test_060_exposes_event_segment_and_keeps_privileges(database_admin_url):
    async with throwaway_database(database_admin_url, last=60) as db:
        await db.execute(SEED_SQL)
        segment = await db.fetchval("SELECT segment_id FROM match_events WHERE id = $1", EVENT)
        assert await db.fetchval(f"SELECT segment_id FROM {EVENTS_VIEW} WHERE id = $1", EVENT) == segment
        assert await db.fetchval(f"SELECT has_table_privilege('bracket_app', '{EVENTS_VIEW}', 'SELECT')")
        assert not await db.fetchval(f"SELECT has_table_privilege('public', '{EVENTS_VIEW}', 'SELECT')")
        options = await db.fetchval(f"SELECT reloptions::text FROM pg_class WHERE oid = '{EVENTS_VIEW}'::regclass")
        assert "security_barrier=true" in options


async def test_060_incremental_from_059_is_idempotent(database_admin_url):
    async with throwaway_database(database_admin_url, last=59) as db:
        await db.execute(SEED_SQL)
        assert await view_columns(db, EVENTS_VIEW) == PREVIOUS_COLUMNS
        before = await db.fetch(f"SELECT id FROM {EVENTS_VIEW} ORDER BY id")
        for _ in range(2):
            await apply_migration(db, 60)
        assert await view_columns(db, EVENTS_VIEW) == [*PREVIOUS_COLUMNS, "segment_id"]
        assert await db.fetch(f"SELECT id FROM {EVENTS_VIEW} ORDER BY id") == before
