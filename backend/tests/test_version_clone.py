"""Version clone and bracket generation: no stage_edges, valid slot provenance.

RF-011/RF-012: ``phase_slots`` is stored provenance and keeps being cloned,
while ``stage_edges`` no longer exists as a code path. The clone endpoint must
not query or insert ``stage_edges``, and the generator may only emit the two
supported ``source_type`` values (``direct_team`` and ``match_result``).

The tests use a session double, so they do not need PostgreSQL.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.core.tenancy import AuthContext
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.tournaments.router import (
    _create_draft_version_record,
    _persist_bracket_schedule,
)
from app.modules.tournaments.scheduling import build_single_elimination_bracket

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
SOURCE_VERSION_ID = uuid4()
SOURCE_GROUP_ID = uuid4()
SOURCE_STAGE_ID = uuid4()
SOURCE_SLOT_ID = uuid4()
SOURCE_MATCH_ID = uuid4()
TEAM_ID = uuid4()

START_DATE = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)


def legacy_published_rules() -> dict:
    """A 3.2.0 config with the deprecated block and no top-level lock."""
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["schema_version"] = "3.2.0"
    config.pop("roster_lock_matchday", None)
    config["transfers"] = {
        "allow_mid_season_transfers": True,
        "same_matchday_participation_allowed": False,
        "roster_lock_matchday": 5,
    }
    return config



class Result:
    """Result double with the subset of the SQLAlchemy API the router uses."""

    def __init__(self, rows=None, scalar=None):
        self._rows = list(rows or [])
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        assert self._rows, "se esperaba una fila"
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class RecordingSession:
    """AsyncSession double that records every statement and its parameters."""

    def __init__(self, *, slot_source_type: str = "direct_team"):
        self.slot_source_type = slot_source_type
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self._result(sql)

    def _result(self, sql: str) -> Result:
        if "FROM roles r" in sql:
            return Result(scalar=1)
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1)
        if "SELECT published_version_id, status" in sql:
            return Result(
                rows=[
                    {
                        "published_version_id": SOURCE_VERSION_ID,
                        "status": "published",
                    }
                ]
            )
        if "SELECT id, rules_config, phase_config, status" in sql:
            return Result(
                rows=[
                    {
                        "id": SOURCE_VERSION_ID,
                        "rules_config": legacy_published_rules(),
                        "phase_config": {},
                        "status": "published",
                    }
                ]
            )
        if "status = 'draft'" in sql:
            return Result(scalar=None)
        if "COALESCE(MAX(version_number), 0) + 1" in sql:
            return Result(scalar=2)
        if "FROM stages" in sql:
            return Result(
                rows=[
                    {
                        "id": SOURCE_STAGE_ID,
                        "name": "Group",
                        "stage_type": "round_robin",
                        "stage_order": 1,
                    }
                ]
            )
        if "FROM groups" in sql:
            return Result(
                rows=[
                    {
                        "id": SOURCE_GROUP_ID,
                        "stage_id": SOURCE_STAGE_ID,
                        "name": "A",
                    }
                ]
            )
        if "FROM phase_slots" in sql:
            return Result(
                rows=[
                    {
                        "id": SOURCE_SLOT_ID,
                        "stage_id": SOURCE_STAGE_ID,
                        "slot_code": "M1_HOME",
                        "source_type": self.slot_source_type,
                        "source_reference": {"team_id": str(TEAM_ID)},
                    }
                ]
            )
        if "FROM stage_teams" in sql:
            return Result(
                rows=[
                    {
                        "stage_id": SOURCE_STAGE_ID,
                        "group_id": SOURCE_GROUP_ID,
                        "team_id": TEAM_ID,
                    }
                ]
            )
        if "FROM advancement_links" in sql:
            return Result(rows=[])
        if "FROM matches" in sql:
            return Result(
                rows=[
                    {
                        "id": SOURCE_MATCH_ID,
                        "stage_id": SOURCE_STAGE_ID,
                        "group_id": SOURCE_GROUP_ID,
                        "venue_id": None,
                        "replacement_match_id": None,
                        "matchday": 1,
                        "bracket_code": "M1",
                        "home_slot_id": SOURCE_SLOT_ID,
                        "away_slot_id": None,
                        "home_team_id": TEAM_ID,
                        "away_team_id": None,
                        "match_date": START_DATE,
                    }
                ]
            )
        if "SELECT id, version_number, status, published_at, created_at, rules_config" in sql:
            return Result(
                rows=[
                    {
                        "id": uuid4(),
                        "version_number": 2,
                        "status": "draft",
                        "published_at": None,
                        "created_at": START_DATE,
                        "rules_config": {},
                    }
                ]
            )
        if sql.startswith(("INSERT INTO", "UPDATE ", "DELETE FROM")):
            return Result()
        raise AssertionError(f"consulta inesperada: {sql}")

    def parameters_for(self, prefix: str) -> list[dict]:
        return [
            params
            for sql, params in self.calls
            if sql.startswith(prefix)
        ]


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


# ---------------------------------------------------------------------------
# Version clone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("slot_source_type", ["direct_team", "match_result"])
async def test_clone_never_touches_stage_edges_and_clones_phase_slots(
    slot_source_type,
):
    session = RecordingSession(slot_source_type=slot_source_type)

    result = await _create_draft_version_record(
        session, context(), TOURNAMENT_ID, None
    )

    # The retired selector table is neither read nor written.
    assert all("stage_edges" not in sql for sql in session.statements)

    # phase_slots is cloned as stored provenance.
    slot_inserts = session.parameters_for("INSERT INTO phase_slots")
    assert len(slot_inserts) == 1
    cloned_slot = slot_inserts[0]
    assert cloned_slot["source_type"] == slot_source_type
    assert cloned_slot["slot_code"] == "M1_HOME"
    assert cloned_slot["id"] != str(SOURCE_SLOT_ID)
    assert cloned_slot["stage_id"] != str(SOURCE_STAGE_ID)
    assert cloned_slot["version_id"] != str(SOURCE_VERSION_ID)

    # The cloned match points at the cloned slot, not at the source one.
    match_inserts = session.parameters_for("INSERT INTO matches")
    assert len(match_inserts) == 1
    assert match_inserts[0]["home_slot_id"] == cloned_slot["id"]
    assert match_inserts[0]["away_slot_id"] is None

    assert result["version_number"] == 2


@pytest.mark.asyncio
async def test_clone_normalizes_rules_and_promotes_the_roster_lock():
    session = RecordingSession()

    await _create_draft_version_record(session, context(), TOURNAMENT_ID, None)

    version_updates = session.parameters_for("UPDATE tournament_versions")
    assert len(version_updates) == 1
    rules = json.loads(version_updates[0]["rules"])
    assert rules["schema_version"] == "3.3.0"
    assert rules["roster_lock_matchday"] == 5
    assert "transfers" not in rules
    assert "substitutions" in rules

    tournament_updates = session.parameters_for("UPDATE tournaments")
    assert len(tournament_updates) == 1
    assert json.loads(tournament_updates[0]["rules"]) == rules


@pytest.mark.asyncio
async def test_clone_only_persists_supported_source_types():
    session = RecordingSession(slot_source_type="match_result")

    await _create_draft_version_record(session, context(), TOURNAMENT_ID, None)

    for params in session.parameters_for("INSERT INTO phase_slots"):
        assert params["source_type"] in {"direct_team", "match_result"}


# ---------------------------------------------------------------------------
# Bracket generation
# ---------------------------------------------------------------------------


def bracket():
    return build_single_elimination_bracket(
        [UUID(int=index) for index in range(1, 9)],
        seed=7,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )


@pytest.mark.asyncio
async def test_bracket_generation_emits_only_supported_slot_sources():
    generated = bracket()
    session = RecordingSession()

    count = await _persist_bracket_schedule(
        session,
        context(),
        TOURNAMENT_ID,
        SOURCE_VERSION_ID,
        SOURCE_STAGE_ID,
        generated,
    )

    assert count == len(generated.matches)
    assert all("stage_edges" not in sql for sql in session.statements)

    slot_inserts = session.parameters_for("INSERT INTO phase_slots")
    assert len(slot_inserts) == 2 * len(generated.matches)
    assert {params["source_type"] for params in slot_inserts} == {
        "direct_team",
        "match_result",
    }
    assert all(
        params["source_type"] in {"direct_team", "match_result"}
        for params in slot_inserts
    )

    # Every generated match references slots created in this same operation.
    slot_ids = {params["id"] for params in slot_inserts}
    match_inserts = session.parameters_for("INSERT INTO matches")
    assert len(match_inserts) == len(generated.matches)
    for params in match_inserts:
        assert params["home_slot_id"] in slot_ids
        assert params["away_slot_id"] in slot_ids

    # The bracket keeps its internal advancement structure.
    link_inserts = session.parameters_for("INSERT INTO advancement_links")
    assert len(link_inserts) == len(generated.advancement_links)
