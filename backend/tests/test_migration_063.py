"""063 crea los orígenes de plaza por clasificación y su resolución (spec 040, T1)."""

import json

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_030 import (
    DRAFT_TOURNAMENT,
    MEMBER,
    ORG,
    SEED_SQL,
    STAGE,
    TEAM_AWAY,
    TEAM_HOME,
    TOURNAMENT,
    VERSION,
)

KO_STAGE = "63000000-0000-4000-8000-000000000001"
SLOT_HOME = "63000000-0000-4000-8000-000000000002"
SLOT_AWAY = "63000000-0000-4000-8000-000000000003"
KO_MATCH = "63000000-0000-4000-8000-000000000004"
GROUP_A = "63000000-0000-4000-8000-000000000005"
OTHER_TEAM = "63000000-0000-4000-8000-000000000006"
FINGERPRINT = "a" * 64
VIEW = "v_public_match_slot_origins"

PUBLISH_MARKER = "UPDATE public.tournament_versions"
SEED_DRAFT, SEED_PUBLISH = SEED_SQL.split(PUBLISH_MARKER)
SEED_PUBLISH = PUBLISH_MARKER + SEED_PUBLISH


def ref(**values) -> str:
    return json.dumps(values)


HOME_REF = ref(kind="group_position", source_stage_id=STAGE, group_id=GROUP_A, position=1)
AWAY_REF = ref(kind="best_of_position", source_stage_id=STAGE, position=2, ordinal=1)

KO_SQL = f"""
INSERT INTO public.groups (id, organization_id, tournament_id, tournament_version_id, stage_id, name)
VALUES ('{GROUP_A}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', 'A');
INSERT INTO public.teams (id, organization_id, name, short_code)
VALUES ('{OTHER_TEAM}', '{ORG}', 'Other Team', 'O63');
INSERT INTO public.tournament_teams (organization_id, tournament_id, team_id, status)
VALUES ('{ORG}', '{TOURNAMENT}', '{OTHER_TEAM}', 'registered');
INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order
) VALUES ('{KO_STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Final', 'single_elimination', 2);
INSERT INTO public.phase_slots (
    id, organization_id, tournament_id, tournament_version_id, stage_id, slot_code,
    source_type, source_reference
) VALUES
    ('{SLOT_HOME}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{KO_STAGE}', 'R1M1H',
     'stage_rank', '{HOME_REF}'::jsonb),
    ('{SLOT_AWAY}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{KO_STAGE}', 'R1M1A',
     'stage_rank', '{AWAY_REF}'::jsonb);
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    home_slot_id, away_slot_id, status, bracket_code
) VALUES (
    '{KO_MATCH}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{KO_STAGE}',
    '{SLOT_HOME}', '{SLOT_AWAY}', 'scheduled', 'R1M1'
);
"""

ASSIGNMENTS = json.dumps([
    {"slot_id": SLOT_HOME, "team_id": TEAM_HOME},
    {"slot_id": SLOT_AWAY, "team_id": TEAM_AWAY},
])


async def seed_published(db) -> None:
    await db.execute(SEED_DRAFT)
    await db.execute(KO_SQL)
    await db.execute(SEED_PUBLISH)


async def insert_resolution(db, stage_id: str = KO_STAGE) -> str:
    return str(await db.fetchval(
        """
        INSERT INTO stage_slot_resolutions (
            organization_id, tournament_id, tournament_version_id, stage_id,
            resolved_by_member_id, standings_fingerprint, assignments
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) RETURNING id
        """,
        ORG, TOURNAMENT, VERSION, stage_id, MEMBER, FINGERPRINT, ASSIGNMENTS,
    ))


async def insert_stage_team(db, team_id: str, group_id: str | None = None, stage_id: str = KO_STAGE) -> None:
    await db.execute(
        """
        INSERT INTO stage_teams (organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        ORG, TOURNAMENT, VERSION, stage_id, group_id, team_id,
    )


async def assert_zz409(db, statement) -> None:
    with pytest.raises(asyncpg.PostgresError) as error:
        async with db.transaction():
            await statement()
    assert error.value.sqlstate == "ZZ409"


async def test_063_structure_rls_and_privileges(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as db:
        table = "public.stage_slot_resolutions"
        assert await db.fetchval(f"SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid = '{table}'::regclass")
        assert await db.fetchval("SELECT count(*) FROM pg_policies WHERE tablename = 'stage_slot_resolutions'") == 1
        for privilege, expected in (("SELECT", True), ("INSERT", True), ("UPDATE", False), ("DELETE", False)):
            assert await db.fetchval(f"SELECT has_table_privilege('bracket_app', '{table}', '{privilege}')") is expected
        assert await db.fetchval(f"SELECT has_table_privilege('bracket_app', '{VIEW}', 'SELECT')")
        assert not await db.fetchval(f"SELECT has_table_privilege('public', '{VIEW}', 'SELECT')")
        options = await db.fetchval(f"SELECT reloptions::text FROM pg_class WHERE oid = '{VIEW}'::regclass")
        assert "security_barrier=true" in options
        definitions = await db.fetch(
            "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conrelid = 'public.phase_slots'::regclass AND contype = 'c'"
        )
        assert any("stage_rank" in row["d"] and "manual" not in row["d"] for row in definitions)
        assert not await db.fetchval(
            "SELECT prosecdef FROM pg_proc WHERE proname = 'prevent_published_structure_mutation'"
        )


@pytest.mark.parametrize(
    "reference",
    [
        ref(kind="group_position", position=1),
        ref(kind="group_position", source_stage_id="no-uuid", position=1),
        ref(kind="group_position", source_stage_id=STAGE, position=0),
        ref(kind="group_position", source_stage_id=STAGE, position="1"),
        ref(kind="group_position", source_stage_id=STAGE, position=1, ordinal=1),
        ref(kind="best_of_position", source_stage_id=STAGE, position=3),
        ref(kind="best_of_position", source_stage_id=STAGE, position=3, ordinal=1, group_id=GROUP_A),
        ref(kind="winner", source_stage_id=STAGE, position=1),
    ],
)
async def test_063_rejects_malformed_stage_rank_reference(database_admin_url, reference):
    async with throwaway_database(database_admin_url, last=63) as db:
        await db.execute(SEED_DRAFT)
        await db.execute(KO_SQL)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(
                """
                INSERT INTO phase_slots (organization_id, tournament_id, tournament_version_id, stage_id,
                                         slot_code, source_type, source_reference)
                VALUES ($1, $2, $3, $4, 'BAD', 'stage_rank', $5::jsonb)
                """,
                ORG, TOURNAMENT, VERSION, KO_STAGE, reference,
            )


async def test_063_published_stage_teams_only_through_a_resolution(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as db:
        await seed_published(db)
        await assert_zz409(db, lambda: insert_stage_team(db, TEAM_HOME))

        async with db.transaction():
            resolution = await insert_resolution(db)
            await db.execute("SELECT set_config('app.stage_slot_resolution_id', $1, true)", resolution)
            await insert_stage_team(db, TEAM_HOME)
            await insert_stage_team(db, TEAM_AWAY)
            await assert_zz409(db, lambda: insert_stage_team(db, OTHER_TEAM))

        async with db.transaction():
            await db.execute("SELECT set_config('app.stage_slot_resolution_id', $1, true)", resolution)
            await assert_zz409(db, lambda: insert_stage_team(db, TEAM_HOME))
            await assert_zz409(db, lambda: insert_stage_team(db, TEAM_HOME, stage_id=STAGE))
        assert await db.fetchval("SELECT count(*) FROM stage_teams WHERE stage_id = $1", KO_STAGE) == 2

        await assert_zz409(db, lambda: db.execute("DELETE FROM stage_teams WHERE stage_id = $1", KO_STAGE))
        with pytest.raises(asyncpg.UniqueViolationError):
            await insert_resolution(db)


async def test_063_resolution_only_for_published_elimination_stage(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as db:
        await db.execute(SEED_DRAFT)
        await db.execute(KO_SQL)
        await assert_zz409(db, lambda: insert_resolution(db))
        await db.execute(SEED_PUBLISH)
        await assert_zz409(db, lambda: insert_resolution(db, stage_id=STAGE))


async def test_063_stage_rank_assignment_requires_resolution(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as db:
        await seed_published(db)
        resolution = await insert_resolution(db)
        insert = """
            INSERT INTO match_slot_assignments (organization_id, tournament_id, match_id, side, team_id,
                                                origin, stage_slot_resolution_id)
            VALUES ($1, $2, $3, 'home', $4, $5, $6)
        """
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(insert, ORG, TOURNAMENT, KO_MATCH, TEAM_HOME, "stage_rank", None)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(insert, ORG, TOURNAMENT, KO_MATCH, TEAM_HOME, "manual", resolution)
        await db.execute(insert, ORG, TOURNAMENT, KO_MATCH, TEAM_HOME, "stage_rank", resolution)


async def test_063_public_view_labels_only_unresolved_slots(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as db:
        await seed_published(db)
        rows = {row["side"]: row for row in await db.fetch(f"SELECT * FROM {VIEW} WHERE match_id = $1", KO_MATCH)}
        assert rows["home"]["origin_kind"] == "group_position"
        assert rows["home"]["group_name"] == "A"
        assert rows["home"]["position"] == 1 and rows["home"]["ordinal"] is None
        assert rows["away"]["origin_kind"] == "best_of_position"
        assert rows["away"]["ordinal"] == 1 and rows["away"]["group_name"] is None
        assert str(rows["away"]["source_stage_id"]) == STAGE

        await db.execute("UPDATE matches SET home_team_id = $1 WHERE id = $2", TEAM_HOME, KO_MATCH)
        assert [row["side"] for row in await db.fetch(f"SELECT side FROM {VIEW}")] == ["away"]
        assert DRAFT_TOURNAMENT not in {str(row["tournament_id"]) for row in await db.fetch(f"SELECT * FROM {VIEW}")}

        await db.execute("UPDATE organizations SET is_active = FALSE WHERE id = $1", ORG)
        assert await db.fetchval(f"SELECT count(*) FROM {VIEW}") == 0


async def test_063_incremental_from_062_is_idempotent(database_admin_url):
    async with throwaway_database(database_admin_url, last=62) as db:
        await db.execute(SEED_DRAFT)
        with pytest.raises(asyncpg.CheckViolationError):
            await db.execute(KO_SQL)
        for _ in range(2):
            await apply_migration(db, 63)
        await db.execute(KO_SQL)
        await db.execute(SEED_PUBLISH)
        assert await db.fetchval(f"SELECT count(*) FROM {VIEW}") == 2
