"""Persisted rules configuration on tournament creation and version updates.

Saving a configuration normalizes it to ``3.3.0``, materializes the
substitution defaults, promotes ``transfers.roster_lock_matchday`` to the
top-level key and omits ``transfers`` (RF-003, RF-020, RF-021, RF-046). The
tests use a recording session double; they do not need PostgreSQL.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.tenancy import AuthContext
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.schemas import (
    CreateTournamentRequest,
    UpdateRulesConfigRequest,
)
from app.modules.tournaments.router import (
    _update_version_rules_record,
    create_tournament,
)

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
VERSION_ID = uuid4()


class Result:
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


class Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RecordingSession:
    """AsyncSession double that records every statement and its parameters."""

    def __init__(self, *, version_status: str = "draft"):
        self.version_status = version_status
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.version_rules: str | None = None
        self.tournament_rules: str | None = None

    def begin(self):
        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self._result(sql, dict(params or {}))

    def _result(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "FROM roles r" in sql:
            return Result(scalar=1)
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1)
        if (
            "SELECT status" in sql
            and "FROM tournament_versions" in sql
            and "FOR UPDATE" in sql
        ):
            return Result(rows=[{"status": self.version_status}])
        if sql.startswith("INSERT INTO tournaments"):
            return Result(scalar=TOURNAMENT_ID)
        if sql.startswith("INSERT INTO tournament_versions"):
            return Result(scalar=VERSION_ID)
        if sql.startswith("UPDATE tournament_versions"):
            self.version_rules = params["rules"]
            return Result()
        if sql.startswith("UPDATE tournaments"):
            self.tournament_rules = params["rules"]
            return Result()
        if "SELECT id, version_number, status, published_at, created_at, rules_config" in sql:
            return Result(
                rows=[
                    {
                        "id": VERSION_ID,
                        "version_number": 1,
                        "status": self.version_status,
                        "published_at": None,
                        "created_at": None,
                        "rules_config": json.loads(self.version_rules or "{}"),
                    }
                ]
            )
        raise AssertionError(f"consulta inesperada: {sql}")

    def parameters_for(self, prefix: str) -> list[dict]:
        return [params for sql, params in self.calls if sql.startswith(prefix)]


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def legacy_config(**overrides) -> dict:
    """A 3.2.0 config with a deprecated block, no top-level lock and no substitutions."""
    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["schema_version"] = "3.2.0"
    config.pop("roster_lock_matchday", None)
    config.pop("substitutions", None)
    config["transfers"] = {
        "allow_mid_season_transfers": True,
        "same_matchday_participation_allowed": False,
        "roster_lock_matchday": 4,
    }
    config.update(overrides)
    return config


def assert_normalized(rules: dict, matchday: int | None) -> None:
    assert rules["schema_version"] == "3.3.0"
    assert rules["roster_lock_matchday"] == matchday
    assert "transfers" not in rules
    assert rules["substitutions"] == {
        "max_per_team": 5,
        "max_windows": 3,
        "allow_reentry": False,
    }


@pytest.mark.asyncio
async def test_create_tournament_persists_normalized_rules():
    session = RecordingSession()
    payload = CreateTournamentRequest(
        name="Copa 007",
        season="2026",
        start_date=date(2026, 1, 1),
        rules_config=legacy_config(),
    )

    response = await create_tournament(payload, context=context(), db=session)

    assert response == {
        "id": str(TOURNAMENT_ID),
        "version_id": str(VERSION_ID),
        "status": "draft",
    }
    version_inserts = session.parameters_for("INSERT INTO tournament_versions")
    assert len(version_inserts) == 1
    assert_normalized(json.loads(version_inserts[0]["rules"]), 4)

    tournament_inserts = session.parameters_for("INSERT INTO tournaments")
    assert len(tournament_inserts) == 1
    assert_normalized(json.loads(tournament_inserts[0]["config"]), 4)


@pytest.mark.asyncio
async def test_update_version_rules_promotes_and_drops_transfers():
    session = RecordingSession()
    payload = UpdateRulesConfigRequest(rules_config=legacy_config())

    result = await _update_version_rules_record(
        session, context(), TOURNAMENT_ID, VERSION_ID, payload
    )

    assert_normalized(result["rules_config"], 4)
    assert_normalized(json.loads(session.version_rules), 4)
    assert_normalized(json.loads(session.tournament_rules), 4)


@pytest.mark.asyncio
async def test_top_level_roster_lock_prevails_when_both_keys_exist():
    session = RecordingSession()
    config = legacy_config()
    config["roster_lock_matchday"] = 6
    payload = UpdateRulesConfigRequest(rules_config=config)

    await _update_version_rules_record(
        session, context(), TOURNAMENT_ID, VERSION_ID, payload
    )

    assert_normalized(json.loads(session.version_rules), 6)


@pytest.mark.asyncio
async def test_published_versions_are_never_rewritten():
    session = RecordingSession(version_status="published")
    payload = UpdateRulesConfigRequest(rules_config=legacy_config())

    with pytest.raises(HTTPException) as excinfo:
        await _update_version_rules_record(
            session, context(), TOURNAMENT_ID, VERSION_ID, payload
        )

    assert excinfo.value.status_code == 409
    assert session.parameters_for("UPDATE tournament_versions") == []
    assert session.parameters_for("UPDATE tournaments") == []
