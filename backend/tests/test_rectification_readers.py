"""Current-report readers and an explicit inventory of original-report access."""

import ast
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext, set_rls_context
from app.modules.matches.router import get_match_operation
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.standings.service import StandingsService
from app.modules.tournaments.routes.matches import list_tournament_matches
from migration_helpers import throwaway_database
from test_migration_031 import (
    MATCH, MEMBER, ORG, PLAYER_HOME_FIRST, SEED_SQL, SEGMENT_FIRST,
    STAGE, TEAM_AWAY, TEAM_HOME, TOURNAMENT, USER, VERSION,
)


ORIGINAL_READ_ALLOWLIST = {
    ("modules/rectifications/service.py", "RectificationService._original_report"):
        "Version 1 is the immutable original, including voided events; only historical detail reads it.",
    ("modules/matches/router.py", "_load_operation_match"):
        "Locks and validates the original for write operations; confirmed GET overlays it afterwards.",
    ("modules/matches/router.py", "get_match_operation"):
        "Original events only for the unconfirmed/live branch; confirmed events use the current view.",
    ("modules/matches/router.py", "save_match_lineup"):
        "Rejects changes to a live lineup once original events have been recorded.",
    ("modules/matches/service.py", "CloseMatchReportService._rewrite_segment_team_state"):
        "Replays substitutions from the report currently being closed, not a historical result.",
    ("modules/matches/service.py", "CloseMatchReportService._persist_events"):
        "Idempotency check against the original events being written by close.",
    ("modules/tournaments/routes/matches.py", "_clear_stage_schedule"):
        "Draft schedule cleanup checks for original events before deleting draft matches.",
}

RESULT_COLUMNS = r"(?:home_score(?:_regular)?|away_score(?:_regular)?|home_penalties|away_penalties|winner_team_id|resolution_type|resolution_reason)"


def reads_original(sql):
    sql = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql.lower(), flags=re.S)
    sql = re.sub(r'"([a-z_]\w*)"', r'\1', sql)
    if re.search(r"\b(?:from|join)\s+(?:public\.)?match_events\b", sql):
        return True
    matches = list(re.finditer(r"\b(?:from|join)\s+(?:public\.)?matches\b(?:\s+(?:as\s+)?([a-z_]\w*))?", sql))
    if not matches:
        return False
    if "<dynamic>" in sql:
        return True
    aliases = {"matches"}
    aliases.update(m.group(1) for m in matches if m.group(1) not in {None, "where", "join", "left", "on", "order"})
    for column in re.finditer(r"(?<![\w.:])" + RESULT_COLUMNS + r"\b", sql):
        if not re.search(r"\bas\s*$", sql[:column.start()]):
            return True
    for alias in aliases:
        if re.search(r"\b" + re.escape(alias) + r"\.\s*(?:" + RESULT_COLUMNS + r"\b|\*)", sql):
            return True
    return bool(re.search(r"(?:\bselect\s+(?:distinct\s+)?|,)\s*\*\s*(?:,|from\b)", sql))


def original_read_inventory(source):
    found = []

    def render(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(render(part) for part in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return render(node.left) + render(node.right)
        return "<dynamic>"

    class Inventory(ast.NodeVisitor):
        scope = ()

        def visit_scope(self, node):
            previous = self.scope
            self.scope = (*previous, node.name)
            self.generic_visit(node)
            self.scope = previous

        visit_FunctionDef = visit_scope
        visit_AsyncFunctionDef = visit_scope
        visit_ClassDef = visit_scope

        def visit_Constant(self, node):
            if isinstance(node.value, str) and reads_original(node.value):
                found.append((".".join(self.scope), node.lineno))

        def visit_JoinedStr(self, node):
            if reads_original(render(node)):
                found.append((".".join(self.scope), node.lineno))

        visit_BinOp = visit_JoinedStr

    Inventory().visit(ast.parse(source))
    return found


def test_original_report_reader_inventory():
    app = Path(__file__).resolve().parents[1] / "app"
    found = {(str(path.relative_to(app)), scope): line
             for path in app.rglob("*.py")
             for scope, line in original_read_inventory(path.read_text())}
    unexpected = {key: line for key, line in found.items() if key not in ORIGINAL_READ_ALLOWLIST}
    assert not unexpected, f"Original report readers without justification: {unexpected}"
    assert set(ORIGINAL_READ_ALLOWLIST) <= found.keys(), "Remove stale original-reader exemptions"
    assert all(reason.strip() for reason in ORIGINAL_READ_ALLOWLIST.values())


@pytest.mark.parametrize("sql", [
    "SELECT home_score FROM matches",
    "SELECT m.away_penalties FROM public.matches AS m",
    "SELECT m.* FROM matches m",
    "SELECT * FROM matches",
    "SELECT * FROM teams t JOIN matches m ON m.home_team_id = t.id",
    "SELECT e.id FROM public.match_events e",
    "SELECT x.id FROM teams x JOIN match_events e ON e.team_id = x.id",
    "WITH old AS (SELECT winner_team_id FROM matches) SELECT * FROM old",
    'SELECT "m"."home_score" FROM "public"."matches" AS "m"',
])
def test_inventory_detects_original_readers(sql):
    assert original_read_inventory(f"async def new_reader():\n    query = {sql!r}") == [("new_reader", 2)]


@pytest.mark.parametrize("sql", [
    "SELECT m.id FROM matches m",
    "SELECT r.home_score FROM matches m JOIN v_match_current_report r ON r.match_id = m.id",
    "SELECT r.home_score AS home_score FROM matches m JOIN v_match_current_report r ON r.match_id = m.id",
    "SELECT * FROM v_match_current_events",
    "UPDATE matches SET home_score = :home_score WHERE id = :id",
])
def test_inventory_accepts_scope_queries_and_current_views(sql):
    assert not reads_original(sql)


def test_inventory_detects_composed_and_dynamic_sql():
    assert original_read_inventory('async def reader():\n    query = "SELECT home_score " + "FROM matches"')
    assert original_read_inventory('async def reader():\n    query = f"SELECT {columns} FROM matches"')


@pytest.mark.asyncio
@pytest.mark.parametrize("rectified, confirmed, empty", [
    (False, False, False), (False, True, False), (True, True, False), (True, True, True),
], ids=["live-original", "confirmed-original", "rectified", "rectified-empty-events"])
async def test_confirmed_readers_use_the_current_report(database_admin_url, rectified, confirmed, empty):
    async with throwaway_database(database_admin_url, last=35) as admin:
        rules = json.dumps(DEFAULT_RULES_CONFIG)
        await admin.execute(SEED_SQL.replace("1, '{}'::jsonb, '{}'::jsonb,", f"1, '{rules}'::jsonb, '{{}}'::jsonb,"))
        await admin.execute("""
            INSERT INTO rosters (organization_id, tournament_id, team_id, player_id,
                                 dorsal_number, valid_from, eligible_from)
            VALUES ($1, $2, $3, $4, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, ORG, TOURNAMENT, TEAM_HOME, PLAYER_HOME_FIRST)
        await admin.execute("""
            INSERT INTO match_rosters (organization_id, match_id, roster_id, player_id, team_id, tournament_id, role)
            SELECT organization_id, $1, id, player_id, team_id, tournament_id, 'starter' FROM rosters
        """, MATCH)
        await admin.execute("""
            INSERT INTO match_events (organization_id, match_id, segment_id, team_id, player_id,
                                      event_type, minute, client_event_id)
            VALUES ($1, $2, $3, $4, $5, 'yellow_card', 10, 'original-yellow')
        """, ORG, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST)
        await admin.execute("""
            INSERT INTO match_events (organization_id, match_id, segment_id, team_id, player_id,
                                      event_type, minute, client_event_id, is_voided,
                                      voided_at, voided_by_member_id, void_reason)
            VALUES ($1, $2, $3, $4, $5, 'red_card', 11, 'voided-red', TRUE,
                    CURRENT_TIMESTAMP, $6, 'Wrong card')
        """, ORG, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST, MEMBER)
        await admin.execute("""
            UPDATE matches SET status = $2, result_confirmed = $3,
                resolution_type = 'regular', home_score_regular = 2, away_score_regular = 0,
                home_score = 2, away_score = 0, winner_team_id = home_team_id WHERE id = $1
        """, MATCH, "finished" if confirmed else "live", confirmed)
        original = await admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH)
        original_events = await admin.fetch("SELECT * FROM match_events")
        if rectified:
            request = await admin.fetchval("""
                INSERT INTO match_report_rectification_requests
                    (organization_id, match_id, base_version_number, proposed_report, reason,
                     requested_by_user_id, requested_by_member_id)
                VALUES ($1, $2, 1, '{}', 'Correction', $3, $4) RETURNING id
            """, ORG, MATCH, USER, MEMBER)
            version = await admin.fetchval("""
                INSERT INTO match_report_versions
                    (organization_id, match_id, version_number, supersedes_version_number,
                     resolution_type, home_score_regular, away_score_regular, home_score, away_score,
                     winner_team_id, request_id, published_by_user_id)
                VALUES ($1, $2, 2, 1, 'regular', 0, 3, 0, 3, $3, $4, $5) RETURNING id
            """, ORG, MATCH, TEAM_AWAY, request, USER)
            if not empty:
                await admin.execute("""
                INSERT INTO match_report_version_events
                    (organization_id, version_id, match_id, segment_id, team_id, player_id,
                     event_type, minute, client_event_id)
                VALUES ($1, $2, $3, $4, $5, $6, 'red_card', 15, 'rectified-red')
                """, ORG, version, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST)
        database = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(make_url(database_admin_url).set(database=database))
        context = AuthContext(UUID(USER), UUID(ORG), UUID(MEMBER))
        try:
            async with engine.connect() as connection, connection.begin():
                await connection.execute(text("SET LOCAL ROLE bracket_app"))
                async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as db:
                    await set_rls_context(db, context.organization_id, context.user_id)
                    await StandingsService(db).recalculate(context, UUID(TOURNAMENT), UUID(STAGE))
                    home = (await db.execute(text("SELECT * FROM standings WHERE team_id = :team"), {"team": UUID(TEAM_HOME)})).mappings().one()
                    expected = (0, 3, 0, 0 if empty else -3) if rectified else (2, 0, 3, -1)
                    assert (home["goals_for"], home["goals_against"], home["points"], home["fair_play_points"]) == (expected if confirmed else (0, 0, 0, 0))
                    history = await CloseMatchReportService(db)._load_discipline_history(context, {
                        "id": uuid4(), "tournament_id": TOURNAMENT, "stage_id": STAGE,
                        "tournament_version_id": VERSION, "rules_config": DEFAULT_RULES_CONFIG,
                    })
                    expected_cards = [] if empty else ["red_card" if rectified else "yellow_card"]
                    assert [event["event_type"] for event in history] == expected_cards
                async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as db:
                    operation = await get_match_operation(UUID(MATCH), context, db)
                    assert operation["match"]["home_score"] == (0 if rectified else 2)
                    assert operation["match"]["winner_team_id"] == UUID(TEAM_AWAY if rectified else TEAM_HOME)
                    assert [event["event_type"] for event in operation["events"]] == (expected_cards if confirmed else ["yellow_card", "red_card"])
                    assert not any(key.startswith("current_") for key in operation["match"])
                async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as db:
                    matches = await list_tournament_matches(UUID(TOURNAMENT), context=context, db=db, limit=100, offset=0)
                    assert matches[0]["home_score"] == (0 if rectified else 2)
                    assert matches[0]["winner_team_id"] == UUID(TEAM_AWAY if rectified else TEAM_HOME)
        finally:
            await engine.dispose()
        assert await admin.fetchrow("SELECT * FROM matches WHERE id = $1", MATCH) == original
        assert await admin.fetch("SELECT * FROM match_events") == original_events
