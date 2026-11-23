"""065 impide códigos repetidos de partidos generados por fase y versión (spec 042, T1)."""

from uuid import uuid4

import asyncpg
import pytest

from migration_helpers import (
    ORG,
    STAGE_SOURCE,
    STAGE_TARGET,
    TOURNAMENT,
    VERSION,
    apply_migration,
    seed_retired_structures,
    throwaway_database,
)

INDEX = "uq_matches_generated_code"


async def insert_match(db, code: str | None, *, stage_id: str = STAGE_SOURCE, version_id: str = VERSION) -> str:
    match_id = str(uuid4())
    await db.execute(
        """
        INSERT INTO public.matches (id, organization_id, tournament_id, tournament_version_id, stage_id, bracket_code, status)
        VALUES ($1, $2, $3, $4, $5, $6, 'scheduled')
        """,
        match_id, ORG, TOURNAMENT, version_id, stage_id, code,
    )
    return match_id


async def clone_version(db) -> tuple[str, str]:
    version_id, stage_id = str(uuid4()), str(uuid4())
    await db.execute(
        """
        INSERT INTO public.tournament_versions (id, organization_id, tournament_id, version_number, rules_config,
                                                phase_config, status, created_by_member_id)
        SELECT $1, organization_id, tournament_id, 2, rules_config, phase_config, 'draft', created_by_member_id
        FROM public.tournament_versions WHERE id = $2
        """,
        version_id, VERSION,
    )
    await db.execute(
        """
        INSERT INTO public.stages (id, organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order)
        VALUES ($1, $2, $3, $4, 'Clone', 'round_robin', 1)
        """,
        stage_id, ORG, TOURNAMENT, version_id,
    )
    return version_id, stage_id


async def index_definition(db) -> str | None:
    return await db.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname = $1", INDEX)


async def snapshot(db) -> list[tuple]:
    rows = await db.fetch("SELECT id, stage_id, bracket_code, status FROM public.matches ORDER BY id")
    return [tuple(row) for row in rows]


async def test_065_clean_volume_creates_a_partial_unique_index(database_admin_url):
    async with throwaway_database(database_admin_url, last=65) as db:
        definition = await index_definition(db)
        assert definition is not None
        assert definition.startswith("CREATE UNIQUE INDEX")
        assert "(organization_id, tournament_version_id, stage_id, bracket_code)" in definition
        assert "WHERE (bracket_code IS NOT NULL)" in definition


async def test_065_rejects_a_repeated_generated_code_in_the_same_stage(database_admin_url):
    async with throwaway_database(database_admin_url, last=65) as db:
        await seed_retired_structures(db)
        await insert_match(db, "RR1-1")
        with pytest.raises(asyncpg.UniqueViolationError):
            await insert_match(db, "RR1-1")


async def test_065_allows_manual_matches_other_stages_and_cloned_versions(database_admin_url):
    async with throwaway_database(database_admin_url, last=65) as db:
        await seed_retired_structures(db)
        await insert_match(db, None)
        await insert_match(db, None)
        await insert_match(db, "SF1")
        await insert_match(db, "SF1", stage_id=STAGE_TARGET)
        version_id, stage_id = await clone_version(db)
        await insert_match(db, "SF1", stage_id=stage_id, version_id=version_id)
        assert await db.fetchval("SELECT count(*) FROM public.matches") == 5


async def test_065_incremental_from_064_keeps_valid_matches_and_is_idempotent(database_admin_url):
    async with throwaway_database(database_admin_url, last=64) as db:
        await seed_retired_structures(db)
        await insert_match(db, "RR1-1")
        await insert_match(db, "RR1-2")
        await insert_match(db, None)
        await insert_match(db, None)
        before = await snapshot(db)
        for _ in range(2):
            await apply_migration(db, 65)
        assert await snapshot(db) == before
        assert await db.fetchval("SELECT count(*) FROM pg_indexes WHERE indexname = $1", INDEX) == 1


async def test_065_aborts_without_changes_and_lists_the_affected_stages(database_admin_url):
    async with throwaway_database(database_admin_url, last=64) as db:
        await seed_retired_structures(db)
        for stage_id in (STAGE_SOURCE, STAGE_TARGET):
            await insert_match(db, "R1-1", stage_id=stage_id)
            await insert_match(db, "R1-1", stage_id=stage_id)
        await insert_match(db, "R1-2")
        before = await snapshot(db)
        with pytest.raises(asyncpg.RaiseError) as error:
            await apply_migration(db, 65)
        message = str(error.value)
        assert "2 fase(s)" in message
        assert message.index(min(STAGE_SOURCE, STAGE_TARGET)) < message.index(max(STAGE_SOURCE, STAGE_TARGET))
        if db.is_in_transaction():
            await db.execute("ROLLBACK")
        assert await index_definition(db) is None
        assert await snapshot(db) == before
