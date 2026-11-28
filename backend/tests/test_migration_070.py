"""070 añade `penalty_saved` y `player_in_position` a los hechos (spec 052, T1)."""

from uuid import uuid4

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MATCH, ORG, PLAYER_HOME_FIRST, PLAYER_HOME_SECOND, SEGMENT_FIRST, TEAM_HOME
from test_migration_021 import MATCH as MATCH_21, ORG as ORG_21, PLAYER_IN, PLAYER_OUT, SEED_SQL as SEED_SQL_21, SEGMENT, TEAM
from test_migration_056 import app, seed, state

TABLES = ("match_events", "match_report_version_events", "match_live_events")
EVENT_TYPES = ("goal", "own_goal", "penalty_goal", "yellow_card", "red_card", "substitution", "foul", "penalty_saved")


async def event_type_checks(db, table: str) -> list[tuple[str, str]]:
    rows = await db.fetch(
        """
        SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint
        WHERE conrelid = ('public.' || $1)::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) ~ '\\mevent_type\\M'
          AND pg_get_constraintdef(oid) ~ '\\mfoul\\M'
        ORDER BY conname
        """,
        table,
    )
    return [(row["conname"], row["definition"]) for row in rows]


async def insert_event(db, **changes) -> None:
    data = dict(
        id=uuid4(), organization_id=ORG_21, match_id=MATCH_21, segment_id=SEGMENT, team_id=TEAM,
        player_id=PLAYER_OUT, event_type="penalty_saved", minute=10, client_event_id=str(uuid4()),
    )
    data.update({k: CLASSIC.get(v, v) if isinstance(v, str) else v for k, v in changes.items()})
    columns = ",".join(data)
    placeholders = ",".join(f"${i}" for i in range(1, len(data) + 1))
    await db.execute(f"INSERT INTO public.match_events({columns}) VALUES ({placeholders})", *data.values())


async def insert_live_event(db, **changes) -> None:
    data = dict(
        organization_id=ORG, match_id=MATCH, segment_id=SEGMENT_FIRST, team_id=TEAM_HOME,
        player_id=PLAYER_HOME_FIRST, event_type="penalty_saved", minute=10, client_event_id=uuid4(),
    )
    data.update(changes)
    columns = ",".join(data)
    placeholders = ",".join(f"${i}" for i in range(1, len(data) + 1))
    async with app(db):
        await db.execute(f"INSERT INTO match_live_events({columns}) VALUES ({placeholders})", *data.values())


CLASSIC = {PLAYER_HOME_FIRST: PLAYER_OUT, PLAYER_HOME_SECOND: PLAYER_IN}
SUBSTITUTION = dict(
    event_type="substitution", player_id=PLAYER_HOME_FIRST,
    player_out_id=PLAYER_HOME_FIRST, player_in_id=PLAYER_HOME_SECOND,
)


@pytest.fixture
async def db_069(database_admin_url):
    async with throwaway_database(database_admin_url, last=69) as db:
        await db.execute(SEED_SQL_21)
        await seed(db)
        async with app(db):
            await state(db)
        yield db


async def test_069_rejects_penalty_saved_and_has_no_position(db_069):
    with pytest.raises(asyncpg.CheckViolationError):
        await insert_event(db_069)
    for table in TABLES:
        assert await db_069.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = $1 AND column_name = 'player_in_position'",
            table,
        ) == 0


async def test_070_incremental_keeps_events_and_is_idempotent(db_069):
    legacy = uuid4()
    await insert_event(db_069, id=legacy, event_type="goal")
    before = await db_069.fetch("SELECT * FROM public.match_events ORDER BY id")
    for _ in range(2):
        await apply_migration(db_069, 70)
    for table in TABLES:
        checks = await event_type_checks(db_069, table)
        assert [name for name, _ in checks] == [f"chk_{table}_event_type"]
        assert all(f"'{code}'" in checks[0][1] for code in EVENT_TYPES)
        names = await db_069.fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = ('public.' || $1)::regclass AND conname = $2",
            table, f"chk_{table}_player_in_position",
        )
        assert len(names) == 1
    after = await db_069.fetch("SELECT * FROM public.match_events ORDER BY id")
    assert [{k: v for k, v in dict(row).items() if k != "player_in_position"} for row in after] == [dict(r) for r in before]
    assert all(row["player_in_position"] is None for row in after)


@pytest.fixture
async def db_070(database_admin_url):
    async with throwaway_database(database_admin_url, last=70) as db:
        await db.execute(SEED_SQL_21)
        await seed(db)
        async with app(db):
            await state(db)
        yield db


async def test_070_accepts_penalty_saved_and_entry_position(db_070):
    await insert_event(db_070)
    await insert_event(db_070, **SUBSTITUTION, player_in_position="LCB")
    await insert_event(db_070, **SUBSTITUTION, minute=20)
    await insert_live_event(db_070)
    await insert_live_event(db_070, **SUBSTITUTION, player_in_position="GK")
    rows = await db_070.fetch("SELECT event_type, player_in_position FROM public.match_events ORDER BY minute, player_in_position")
    assert [tuple(row) for row in rows] == [("substitution", "LCB"), ("penalty_saved", None), ("substitution", None)]


@pytest.mark.parametrize("changes", [
    {"player_in_position": "GK"},
    {"event_type": "goal", "player_in_position": "ST"},
    {**SUBSTITUTION, "player_in_position": "lcb"},
    {**SUBSTITUTION, "player_in_position": "L-CB"},
    {**SUBSTITUTION, "player_in_position": "X" * 21},
])
async def test_070_rejects_invalid_entry_position(db_070, changes):
    with pytest.raises(asyncpg.PostgresError):
        await insert_event(db_070, **changes)
    with pytest.raises(asyncpg.PostgresError):
        await insert_live_event(db_070, **changes)


async def test_070_version_events_constraints(db_070):
    definitions = {
        row["conname"]: row["definition"]
        for row in await db_070.fetch(
            """SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint
               WHERE conrelid = 'public.match_report_version_events'::regclass AND contype = 'c'"""
        )
    }
    assert "'penalty_saved'" in definitions["chk_match_report_version_events_event_type"]
    position = definitions["chk_match_report_version_events_player_in_position"]
    assert "substitution" in position and "player_in_position" in position


async def test_070_public_view_appends_entry_position(db_070):
    columns = [
        row["column_name"]
        for row in await db_070.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'v_public_match_events' ORDER BY ordinal_position"""
        )
    ]
    assert columns[-2:] == ["segment_id", "player_in_position"]
    assert columns[:-1] == [
        "id", "match_id", "tournament_id", "team_id", "player_id", "event_type", "minute", "added_minute",
        "player_out_id", "player_in_id", "beneficiary_team_id", "metadata", "is_voided", "segment_id",
    ]
    assert await db_070.fetchval(
        "SELECT has_table_privilege('bracket_app', 'public.v_public_match_events', 'SELECT')"
    )


async def test_070_current_events_view_appends_entry_position(db_070):
    columns = [
        row["column_name"]
        for row in await db_070.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'v_match_current_events' ORDER BY ordinal_position"""
        )
    ]
    assert columns[-2:] == ["assist_player_id", "player_in_position"]
    options = await db_070.fetchval(
        "SELECT reloptions FROM pg_class WHERE oid = 'public.v_match_current_events'::regclass"
    )
    assert set(options) == {"security_barrier=true", "security_invoker=true"}
    assert await db_070.fetchval(
        "SELECT has_table_privilege('bracket_app', 'public.v_match_current_events', 'SELECT')"
    )


async def test_070_phase_minutes_view_resolves_defaults_and_stage_override(db_070):
    stage = await db_070.fetchval("SELECT stage_id FROM matches WHERE id = $1", MATCH)
    await db_070.execute("SET session_replication_role = replica")
    await db_070.execute(
        """UPDATE tournament_versions tv SET rules_config = jsonb_set(jsonb_set(tv.rules_config,
               '{stage_defaults}', '{"regular_time_minutes": 50, "extra_time_enabled": false}'::jsonb),
               '{stage_overrides}', jsonb_build_object($2::text, '{"extra_time_enabled": true, "extra_time_minutes": 70}'::jsonb))
           FROM matches m WHERE m.id = $1 AND tv.id = m.tournament_version_id""",
        MATCH, str(stage),
    )
    await db_070.execute("SET session_replication_role = origin")
    row = await db_070.fetchrow(
        "SELECT regular_time_minutes, extra_time_minutes, extra_time_enabled FROM v_public_match_phase_minutes WHERE match_id = $1",
        MATCH,
    )
    assert tuple(row) == (50, 70, True)
    columns = [r["column_name"] for r in await db_070.fetch(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'v_public_match_phase_minutes' ORDER BY ordinal_position""")]
    assert columns == ["match_id", "tournament_id", "regular_time_minutes", "extra_time_minutes", "extra_time_enabled"]
    assert await db_070.fetchval("SELECT has_table_privilege('bracket_app', 'public.v_public_match_phase_minutes', 'SELECT')")

    await db_070.execute("UPDATE tournaments SET status = 'draft' WHERE id = (SELECT tournament_id FROM matches WHERE id = $1)", MATCH)
    assert await db_070.fetchval("SELECT count(*) FROM v_public_match_phase_minutes WHERE match_id = $1", MATCH) == 0


async def test_070_phase_minutes_view_ignores_an_unused_decimal_extra_time(db_070):
    await db_070.execute("SET session_replication_role = replica")
    await db_070.execute(
        """UPDATE tournament_versions tv SET rules_config = jsonb_set(tv.rules_config, '{stage_defaults}',
               '{"regular_time_minutes": 50, "extra_time_enabled": false, "extra_time_minutes": 120.0}'::jsonb)
           FROM matches m WHERE m.id = $1 AND tv.id = m.tournament_version_id""",
        MATCH,
    )
    await db_070.execute("SET session_replication_role = origin")
    row = await db_070.fetchrow(
        "SELECT regular_time_minutes, extra_time_minutes, extra_time_enabled FROM v_public_match_phase_minutes WHERE match_id = $1",
        MATCH,
    )
    assert tuple(row) == (50, None, False)
