"""066 amplía el CHECK de formaciones al catálogo por modalidad (spec 044, T1)."""

import asyncpg
import pytest

from app.modules.rule_contract import FORMATION_CODES, FORMATIONS_BY_GAME_FORMAT
from migration_helpers import apply_migration, throwaway_database
from test_migration_021 import MATCH, ORG, SEED_SQL, SEGMENT, TEAM

LINEUP = "21000000-0000-4000-8000-000000000066"
NEW_CHECK = "chk_match_team_lineup_formation_code"
OLD_CHECK = "match_team_lineups_formation_code_check"


async def formation_checks(db) -> list[str]:
    rows = await db.fetch(
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'public.match_team_lineups'::regclass
          AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%formation_code%'
        ORDER BY conname
        """
    )
    return [row["conname"] for row in rows]


async def insert_lineup(db, code: str) -> None:
    await db.execute(SEED_SQL)
    await db.execute(
        """
        INSERT INTO public.match_team_lineups (id, organization_id, match_id, segment_id, team_id, formation_code)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        LINEUP, ORG, MATCH, SEGMENT, TEAM, code,
    )


async def set_formation(db, code: str) -> None:
    await db.execute("UPDATE public.match_team_lineups SET formation_code = $1 WHERE id = $2", code, LINEUP)


async def test_066_clean_volume_accepts_exactly_the_catalog_per_game_format(database_admin_url):
    async with throwaway_database(database_admin_url, last=66) as db:
        assert await formation_checks(db) == [NEW_CHECK]
        await insert_lineup(db, FORMATION_CODES[0])
        for code in FORMATION_CODES:
            await set_formation(db, code)
        assert await db.fetchval("SELECT formation_code FROM public.match_team_lineups WHERE id = $1", LINEUP) == FORMATION_CODES[-1]
        for outside in ("4-1-4-1", "1-1-1", "2-3"):
            with pytest.raises(asyncpg.CheckViolationError):
                await set_formation(db, outside)


async def test_065_volume_rejects_reduced_formations_until_066(database_admin_url):
    async with throwaway_database(database_admin_url, last=65) as db:
        assert await formation_checks(db) == [OLD_CHECK]
        await insert_lineup(db, "4-3-3")
        with pytest.raises(asyncpg.CheckViolationError):
            await set_formation(db, FORMATIONS_BY_GAME_FORMAT["7v7"][0])


async def test_066_incremental_keeps_existing_lineups_and_is_idempotent(database_admin_url):
    async with throwaway_database(database_admin_url, last=65) as db:
        await insert_lineup(db, "4-2-3-1")
        before = await db.fetch("SELECT * FROM public.match_team_lineups ORDER BY id")
        for _ in range(2):
            await apply_migration(db, 66)
        assert await formation_checks(db) == [NEW_CHECK]
        assert await db.fetch("SELECT * FROM public.match_team_lineups ORDER BY id") == before
        await set_formation(db, "2-2")
        with pytest.raises(asyncpg.CheckViolationError):
            await set_formation(db, "4-1-4-1")
