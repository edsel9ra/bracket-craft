"""061 crea v_public_player_profile_rosters (spec 038, T1)."""

from migration_helpers import apply_migration, throwaway_database
from test_migration_030 import (
    DRAFT_TOURNAMENT,
    HOME_PHOTO_KEY,
    ORG,
    PLAYER_AWAY,
    PLAYER_HOME,
    SEED_SQL,
    TOURNAMENT,
    view_columns,
)

VIEW = "v_public_player_profile_rosters"
COLUMNS = [
    "organization_id", "tournament_id", "tournament_name", "start_date", "team_id",
    "team_name", "player_id", "first_name", "last_name", "is_active", "valid_from",
    "photo_consent", "photo_object_key",
]


async def test_061_columns_privileges_and_security_barrier(database_admin_url):
    async with throwaway_database(database_admin_url, last=61) as db:
        assert await view_columns(db, VIEW) == COLUMNS
        assert await db.fetchval(f"SELECT has_table_privilege('bracket_app', '{VIEW}', 'SELECT')")
        assert not await db.fetchval(f"SELECT has_table_privilege('public', '{VIEW}', 'SELECT')")
        options = await db.fetchval(f"SELECT reloptions::text FROM pg_class WHERE oid = '{VIEW}'::regclass")
        assert "security_barrier=true" in options


async def test_061_only_visible_tournaments_and_photo_only_with_consent(database_admin_url):
    async with throwaway_database(database_admin_url, last=61) as db:
        await db.execute(SEED_SQL)
        rows = {
            str(row["player_id"]): row
            for row in await db.fetch(f"SELECT * FROM {VIEW} ORDER BY player_id")
        }
        assert set(rows) == {PLAYER_HOME, PLAYER_AWAY}
        assert {str(row["tournament_id"]) for row in rows.values()} == {TOURNAMENT}
        assert DRAFT_TOURNAMENT not in {str(row["tournament_id"]) for row in rows.values()}
        assert all(str(row["organization_id"]) == ORG for row in rows.values())
        assert rows[PLAYER_HOME]["photo_object_key"] == HOME_PHOTO_KEY
        assert rows[PLAYER_AWAY]["photo_consent"] is False
        assert rows[PLAYER_AWAY]["photo_object_key"] is None
        assert rows[PLAYER_HOME]["tournament_name"] == "Migration 030 Cup"

        await db.execute("UPDATE organizations SET is_active = FALSE WHERE id = $1", ORG)
        assert await db.fetchval(f"SELECT count(*) FROM {VIEW}") == 0


async def test_061_incremental_from_060_is_idempotent(database_admin_url):
    async with throwaway_database(database_admin_url, last=60) as db:
        await db.execute(SEED_SQL)
        assert not await db.fetchval(f"SELECT to_regclass('public.{VIEW}') IS NOT NULL")
        for _ in range(2):
            await apply_migration(db, 61)
        assert await view_columns(db, VIEW) == COLUMNS
        assert await db.fetchval(f"SELECT count(*) FROM {VIEW}") == 2
