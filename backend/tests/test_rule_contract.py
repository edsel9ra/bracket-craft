"""Internal rule contract: GF1/GF2 and the closed formation catalog.

Covers T011 (RF-050, RF-051, RF-052):

* ``GF1``/``GF2`` are named constants and the schedule produces exactly them;
* the closing and the advancement path recognise those constants, and the
  bracket reset is only activated when the losers-bracket finalist wins;
* the formations are a closed catalog per game format (spec 044) whose
  positions match the documented contract and the database ``CHECK``;
* ``engine_version`` stays at the documented value.

No PostgreSQL is needed here. The database ``CHECK`` is verified opt-in in
``test_migration_021.py``; this file checks the migration source so a drift is
caught even when the database suite is skipped.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.advancement.service import AdvancementService
from app.modules.matches.formations import (
    FORMATION_SLOTS,
    FORMATIONS_BY_GAME_FORMAT,
    formation_game_format,
    slots_for_formation,
    starters_for_game_format,
)
from app.modules.matches.schemas import FormationCode, MatchTeamLineupConfig
from app.modules.rule_contract import (
    ENGINE_VERSION,
    FORMATION_CODES,
    GRAND_FINAL_CODE,
    POSITION_LINE_CODES,
    POSITION_LINES,
    RESET_CODE,
    positions_for_game_format,
    requires_decisive_winner,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import RULES_SCHEMA
from app.modules.rules_engine.schemas import TournamentRulesConfig
from app.modules.tournaments.scheduling import build_double_elimination_bracket

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOC = ROOT / "docs" / "contrato-reglas.md"
MIGRATIONS = ROOT / "infra" / "postgres" / "migrations"
LEGACY_FORMATION_MIGRATION = MIGRATIONS / "007_tactical_lineups.sql"
FORMATION_MIGRATION = MIGRATIONS / "066_formations_by_game_format.sql"

ELEVEN_A_SIDE_SLOTS = {
    "4-3-3": ("GK", "LB", "LCB", "RCB", "RB", "CM_L", "CM", "CM_R", "LW", "ST", "RW"),
    "4-4-2": ("GK", "LB", "LCB", "RCB", "RB", "LM", "LCM", "RCM", "RM", "ST_L", "ST_R"),
    "3-5-2": ("GK", "LCB", "CB", "RCB", "LWB", "LCM", "CM", "RCM", "RWB", "ST_L", "ST_R"),
    "4-2-3-1": ("GK", "LB", "LCB", "RCB", "RB", "CDM_L", "CDM_R", "LW", "CAM", "RW", "ST"),
}

# Spec 044, RF-001 (DA-1): three formations per reduced game format.
REDUCED_FORMATION_SLOTS = {
    "1-2-1": ("GK", "CB", "LM", "RM", "ST"),
    "2-1-1": ("GK", "LCB", "RCB", "CM", "ST"),
    "2-2": ("GK", "LCB", "RCB", "ST_L", "ST_R"),
    "2-3-1": ("GK", "LCB", "RCB", "LM", "CM", "RM", "ST"),
    "3-2-1": ("GK", "LCB", "CB", "RCB", "LCM", "RCM", "ST"),
    "3-1-2": ("GK", "LCB", "CB", "RCB", "CM", "ST_L", "ST_R"),
    "3-3-2": ("GK", "LCB", "CB", "RCB", "LM", "CM", "RM", "ST_L", "ST_R"),
    "3-4-1": ("GK", "LCB", "CB", "RCB", "LM", "LCM", "RCM", "RM", "ST"),
    "4-3-1": ("GK", "LB", "LCB", "RCB", "RB", "CM_L", "CM", "CM_R", "ST"),
}

EXPECTED_BY_GAME_FORMAT = {
    "5v5": ("1-2-1", "2-1-1", "2-2"),
    "7v7": ("2-3-1", "3-2-1", "3-1-2"),
    "9v9": ("3-3-2", "3-4-1", "4-3-1"),
    "11v11": ("4-3-3", "4-4-2", "3-5-2", "4-2-3-1"),
}

MATCH_DATE = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class Result:
    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class RecordingSession:
    def __init__(self, reset_id: UUID | None = None):
        self.reset_id = reset_id
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        if "FROM advancement_links" in sql:
            return Result()
        if "SELECT id" in sql and "bracket_code = :reset_code" in sql:
            return Result(rows=[{"id": self.reset_id}])
        if sql.startswith("UPDATE matches"):
            return Result(rowcount=1)
        if sql.startswith("INSERT INTO outbox_events"):
            return Result()
        if sql.startswith("INSERT INTO match_slot_assignments"):
            return Result()
        raise AssertionError(f"consulta no esperada: {sql}")


class MatchStub:
    """GF1 row as the closing service passes it to the advancement service."""

    def __init__(self, **overrides):
        self.home_team_id = uuid4()
        self.away_team_id = uuid4()
        self.tournament_id = uuid4()
        self.tournament_version_id = uuid4()
        self.stage_id = uuid4()
        self.bracket_code = GRAND_FINAL_CODE
        for name, value in overrides.items():
            setattr(self, name, value)

    def as_mapping(self) -> dict:
        return {
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "tournament_id": self.tournament_id,
            "tournament_version_id": self.tournament_version_id,
            "stage_id": self.stage_id,
            "bracket_code": self.bracket_code,
        }


def outcome(winner: UUID):
    return type("Outcome", (), {"winner_team_id": winner})()


# ---------------------------------------------------------------------------
# GF1/GF2: single source and schedule
# ---------------------------------------------------------------------------


def test_bracket_codes_are_the_documented_constants():
    assert GRAND_FINAL_CODE == "GF1"
    assert RESET_CODE == "GF2"
    assert GRAND_FINAL_CODE != RESET_CODE


def test_the_schedule_creates_the_grand_final_and_the_cancelled_repetition():
    bracket = build_double_elimination_bracket(
        [uuid4() for _ in range(4)],
        seed=7,
        start_date=MATCH_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    codes = [match.code for match in bracket.matches]
    assert codes.count(GRAND_FINAL_CODE) == 1
    assert bracket.reset_code == RESET_CODE
    # The repetition is created by the router as a cancelled match, not as a
    # regular bracket match, and no other GF* code exists.
    assert RESET_CODE not in codes
    assert not [code for code in codes if code.startswith("GF") and code != GRAND_FINAL_CODE]


def test_the_closing_requires_a_winner_for_both_grand_final_codes():
    assert requires_decisive_winner(GRAND_FINAL_CODE) is True
    assert requires_decisive_winner(RESET_CODE) is True
    assert requires_decisive_winner("FINAL") is False
    assert requires_decisive_winner("SF1") is False
    assert requires_decisive_winner(None) is False


@pytest.mark.asyncio
async def test_advancement_targets_include_the_reset_match_for_the_grand_final():
    reset_id = uuid4()
    session = RecordingSession(reset_id=reset_id)
    match = MatchStub()
    context = type("Context", (), {"organization_id": uuid4()})()

    targets = await AdvancementService(session).target_ids(context, uuid4(), match.as_mapping())

    assert targets == (reset_id,)
    reset_queries = [
        params
        for sql, params in session.calls
        if "SELECT id" in sql and "bracket_code = :reset_code" in sql
    ]
    assert reset_queries == [
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(match.tournament_id),
            "version_id": str(match.tournament_version_id),
            "stage_id": str(match.stage_id),
            "reset_code": RESET_CODE,
        }
    ]


# ---------------------------------------------------------------------------
# Bracket reset activation (RF-052)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reset_is_activated_with_both_grand_final_teams():
    match = MatchStub()
    reset_id = uuid4()
    session = RecordingSession(reset_id=reset_id)
    context = type("Context", (), {"organization_id": uuid4()})()

    # The away team is the losers-bracket finalist.
    await AdvancementService(session).activate_double_elimination_reset(
        context,
        match.as_mapping(),
        outcome(match.away_team_id),
    )

    update_sql, update_params = next(
        (sql, params) for sql, params in session.calls if sql.startswith("UPDATE matches")
    )
    assert "status = 'scheduled'" in update_sql
    assert "status = 'cancelled'" in update_sql
    assert update_params["match_id"] == str(reset_id)
    assert update_params["home_team_id"] == str(match.home_team_id)
    assert update_params["away_team_id"] == str(match.away_team_id)
    assert update_params["organization_id"] == str(context.organization_id)
    assignments = [params for sql, params in session.calls if sql.startswith("INSERT INTO match_slot_assignments")]
    assert len(assignments) == 1
    assert assignments[0]["match_id"] == str(reset_id)
    assert assignments[0]["origin"] == "manual"
    assert assignments[0]["side"] is None
    assert assignments[0]["advancement_link_id"] is None

    outbox = [
        json.loads(params["payload"])
        for sql, params in session.calls
        if sql.startswith("INSERT INTO outbox_events")
    ]
    assert outbox == [
        {"match_id": str(reset_id), "tournament_id": str(match.tournament_id)}
    ]


@pytest.mark.asyncio
async def test_the_reset_is_not_activated_when_the_winners_bracket_finalist_wins():
    match = MatchStub()
    session = RecordingSession(reset_id=uuid4())
    context = type("Context", (), {"organization_id": uuid4()})()

    await AdvancementService(session).activate_double_elimination_reset(
        context,
        match.as_mapping(),
        outcome(match.home_team_id),
    )

    assert session.statements == []


@pytest.mark.asyncio
async def test_the_repetition_itself_never_reactivates_the_reset():
    match = MatchStub(bracket_code=RESET_CODE)
    session = RecordingSession(reset_id=uuid4())
    context = type("Context", (), {"organization_id": uuid4()})()

    await AdvancementService(session).activate_double_elimination_reset(
        context,
        match.as_mapping(),
        outcome(match.away_team_id),
    )

    assert session.statements == []


# ---------------------------------------------------------------------------
# Formation catalog: closed and coincident with schemas and schema
# ---------------------------------------------------------------------------


def test_the_formation_catalog_is_closed_per_game_format():
    assert FORMATIONS_BY_GAME_FORMAT == EXPECTED_BY_GAME_FORMAT
    # 11v11 keeps its original order first; the reduced formats follow.
    assert FORMATION_CODES == (*ELEVEN_A_SIDE_SLOTS, *REDUCED_FORMATION_SLOTS)
    assert len(FORMATION_CODES) == 13
    assert tuple(FORMATION_SLOTS) == FORMATION_CODES
    assert dict(FORMATION_SLOTS) == {**ELEVEN_A_SIDE_SLOTS, **REDUCED_FORMATION_SLOTS}
    assert slots_for_formation("4-1-4-1") is None


def test_every_formation_has_one_goalkeeper_and_the_starters_of_its_format():
    known_positions = {slot for slots in ELEVEN_A_SIDE_SLOTS.values() for slot in slots}
    assert len(known_positions) == 23
    for game_format, codes in FORMATIONS_BY_GAME_FORMAT.items():
        starters = starters_for_game_format(game_format)
        assert starters == int(game_format.split("v")[0])
        for code in codes:
            slots = FORMATION_SLOTS[code]
            assert formation_game_format(code) == game_format
            assert slots_for_formation(code) == slots
            assert len(slots) == starters, code
            assert len(set(slots)) == starters, code
            assert slots.count("GK") == 1 and slots[0] == "GK", code
            assert set(slots) <= known_positions, code
    assert formation_game_format("4-1-4-1") is None
    # A version without game_format reads as 11v11 (spec 024, RF-013).
    assert starters_for_game_format(None) == 11
    with pytest.raises(ValueError):
        starters_for_game_format("6v6")


def test_the_api_schema_accepts_exactly_the_catalog():
    assert get_args(FormationCode) == FORMATION_CODES

    for code in FORMATION_CODES:
        lineup = MatchTeamLineupConfig(team_id=uuid4(), formation_code=code)
        assert lineup.formation_code == code

    with pytest.raises(ValidationError, match="formation_code"):
        MatchTeamLineupConfig(team_id=uuid4(), formation_code="4-1-4-1")


def test_the_database_check_lists_exactly_the_catalog():
    source = FORMATION_MIGRATION.read_text(encoding="utf-8")
    check = re.search(r"formation_code IN \(([^)]*)\)", source)
    assert check is not None, "no se encontró el CHECK de formaciones en 066"
    codes = tuple(re.findall(r"'([^']+)'", check.group(1)))
    assert codes == FORMATION_CODES

    # 007 keeps the original 11v11 catalog; 066 replaces its CHECK.
    legacy = re.search(r"formation_code IN \(([^)]*)\)", LEGACY_FORMATION_MIGRATION.read_text(encoding="utf-8"))
    assert legacy is not None
    assert tuple(re.findall(r"'([^']+)'", legacy.group(1))) == FORMATIONS_BY_GAME_FORMAT["11v11"]


# ---------------------------------------------------------------------------
# Documented contract (RF-051)
# ---------------------------------------------------------------------------


def test_the_contract_document_exists_and_declares_the_engine_version():
    document = CONTRACT_DOC.read_text(encoding="utf-8")

    assert ENGINE_VERSION == "2026.1"
    assert f"`{ENGINE_VERSION}`" in document
    assert "engine_version" in document
    # Stability: the contract version is the one the rules engine accepts.
    assert DEFAULT_RULES_CONFIG["engine_version"] == ENGINE_VERSION
    assert RULES_SCHEMA["properties"]["engine_version"]["const"] == ENGINE_VERSION
    assert TournamentRulesConfig.model_fields["engine_version"].default == ENGINE_VERSION


def test_the_contract_document_names_both_bracket_codes():
    document = CONTRACT_DOC.read_text(encoding="utf-8")

    for constant, code in (
        ("GRAND_FINAL_CODE", GRAND_FINAL_CODE),
        ("RESET_CODE", RESET_CODE),
    ):
        assert f"`{code}`" in document
        assert constant in document
    assert "bracket reset" in document.lower()
    assert "no configurable" in document.lower()


def test_the_contract_document_lists_every_formation_with_its_positions():
    document = CONTRACT_DOC.read_text(encoding="utf-8")

    for code, slots in FORMATION_SLOTS.items():
        heading = re.search(
            rf"^### `{re.escape(code)}`\s*$(.*?)(?=^### |\Z)",
            document,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert heading is not None, f"falta la formación {code} en el contrato"
        section = heading.group(1)
        for slot in slots:
            assert f"`{slot}`" in section, f"falta la posición {slot} de {code}"
    assert document.count("### `") == len(FORMATION_CODES)


# ---------------------------------------------------------------------------
# Spec 052 (F17, D3/D4): línea de cada posición y catálogo por modalidad
# ---------------------------------------------------------------------------

EXPECTED_POSITION_LINES = {
    "GK": "goalkeeper",
    **{code: "defender" for code in ("CB", "LCB", "RCB", "LB", "RB", "LWB", "RWB")},
    **{
        code: "midfielder"
        for code in ("CDM_L", "CDM_R", "CM", "CM_L", "CM_R", "LCM", "RCM", "LM", "RM", "CAM")
    },
    **{code: "forward" for code in ("ST", "ST_L", "ST_R", "LW", "RW")},
}


def test_position_lines_cover_exactly_the_catalog_positions():
    catalog_positions = {slot for slots in FORMATION_SLOTS.values() for slot in slots}
    assert set(POSITION_LINES) == catalog_positions
    assert dict(POSITION_LINES) == EXPECTED_POSITION_LINES
    assert POSITION_LINE_CODES == ("goalkeeper", "defender", "midfielder", "forward")
    assert set(POSITION_LINES.values()) == set(POSITION_LINE_CODES)


def test_positions_for_game_format_are_the_union_of_its_formations():
    for game_format, codes in FORMATIONS_BY_GAME_FORMAT.items():
        expected = frozenset(slot for code in codes for slot in FORMATION_SLOTS[code])
        positions = positions_for_game_format(game_format)
        assert positions == expected
        assert isinstance(positions, frozenset)
        assert "GK" in positions
    assert positions_for_game_format("5v5") == frozenset(
        {"GK", "CB", "LCB", "RCB", "LM", "RM", "CM", "ST", "ST_L", "ST_R"}
    )
    # LWB only exists in 11v11 (3-5-2): outside the catalog of the reduced formats.
    assert "LWB" in positions_for_game_format("11v11")
    assert all("LWB" not in positions_for_game_format(f) for f in ("5v5", "7v7", "9v9"))
    # A version without game_format reads as 11v11 (spec 024, RF-013).
    assert positions_for_game_format(None) == positions_for_game_format("11v11")
    with pytest.raises(ValueError):
        positions_for_game_format("6v6")
