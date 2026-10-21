"""Internal rule contract: GF1/GF2 and the closed formation catalog.

Covers T011 (RF-050, RF-051, RF-052):

* ``GF1``/``GF2`` are named constants and the schedule produces exactly them;
* the closing and the advancement path recognise those constants, and the
  bracket reset is only activated when the losers-bracket finalist wins;
* the four formations are a closed catalog whose positions match the
  documented contract and the database ``CHECK``;
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
from app.modules.matches import service as matches_service
from app.modules.matches.formations import FORMATION_SLOTS, slots_for_formation
from app.modules.matches.schemas import FormationCode, MatchTeamLineupConfig
from app.modules.rule_contract import (
    ENGINE_VERSION,
    FORMATION_CODES,
    GRAND_FINAL_CODE,
    RESET_CODE,
    requires_decisive_winner,
)
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.engine import RULES_SCHEMA
from app.modules.rules_engine.schemas import TournamentRulesConfig
from app.modules.tournaments.scheduling import build_double_elimination_bracket

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DOC = ROOT / "docs" / "contrato-reglas.md"
FORMATION_MIGRATION = ROOT / "infra" / "postgres" / "migrations" / "007_tactical_lineups.sql"

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


def test_the_formation_catalog_is_closed_and_has_eleven_positions():
    assert len(FORMATION_CODES) == 4
    assert tuple(FORMATION_SLOTS) == FORMATION_CODES
    for code, slots in FORMATION_SLOTS.items():
        assert len(slots) == 11, code
        assert len(set(slots)) == 11, code
        assert slots_for_formation(code) == slots
    assert slots_for_formation("4-1-4-1") is None


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
    assert check is not None, "no se encontró el CHECK de formaciones en 007"
    codes = tuple(re.findall(r"'([^']+)'", check.group(1)))
    assert codes == FORMATION_CODES


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
