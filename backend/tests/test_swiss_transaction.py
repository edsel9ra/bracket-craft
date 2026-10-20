"""Swiss draw: team cap, read/calculate/write boundary and 409 outcomes (T005).

The endpoint loads everything inside its read transaction (RLS included),
closes it, runs the pure pairing off-thread and only then opens the write
transaction. These tests use a session double that records the transaction
state of every query, write and calculator call, so the N-2 boundary and the
"no writes on failure" rule are verified without PostgreSQL.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.tournaments import router as tournaments_router
from app.modules.tournaments.schemas import GenerateSingleEliminationRequest
from app.modules.tournaments.scheduling import (
    SwissPairing,
    SwissPairingFailure,
    SwissPairingTimeout,
)
from db_helpers import create_tenant_owner, set_tenant_context

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
VERSION_ID = uuid4()
STAGE_ID = uuid4()


class EmptyResult:
    def mappings(self):
        return self

    def all(self):
        return []

    def one_or_none(self):
        return None

    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return None


class RowsResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        return self.rows[0] if self.rows else None


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def all(self):
        return [] if self.value is None else [self.value]


class DrawTransaction:
    def __init__(self, session: "DrawSession"):
        self._session = session

    async def __aenter__(self):
        self._session.active = True
        self._session.transaction_writes = []
        return self

    async def __aexit__(self, exc_type, exc_info, traceback):
        self._session.active = False
        if exc_type is None:
            self._session.committed = True
            self._session.committed_writes.extend(self._session.transaction_writes)
        else:
            self._session.rolled_back = True
        self._session.transaction_writes = []
        return False


class DrawSession:
    """Session double for the Swiss draw endpoint."""

    def __init__(
        self,
        *,
        team_count: int = 8,
        stage_type: str = "swiss",
        version_status: str = "draft",
        existing_ids=(),
        t2_existing_ids=None,
        configured_rounds: int | None = None,
        previous_rows=None,
        t2_previous_rows=None,
        placeholder_rows=None,
        t2_placeholder_rows=None,
        history=(),
        standings=(),
        fail_write_on: str | None = None,
    ):
        self.team_rows = [
            {"team_id": UUID(int=index), "group_id": None}
            for index in range(1, team_count + 1)
        ]
        self.stage = {
            "version_status": version_status,
            "tournament_version_id": VERSION_ID,
            "stage_type": stage_type,
        }
        self.existing_ids = list(existing_ids)
        self.t2_existing_ids = (
            None if t2_existing_ids is None else list(t2_existing_ids)
        )
        self.configured_rounds = configured_rounds
        self.previous_rows = list(previous_rows or [])
        self.t2_previous_rows = (
            None if t2_previous_rows is None else list(t2_previous_rows)
        )
        self.placeholder_rows = list(placeholder_rows or [])
        self.t2_placeholder_rows = (
            None if t2_placeholder_rows is None else list(t2_placeholder_rows)
        )
        self.history = list(history)
        self.standings = list(standings)
        self.fail_write_on = fail_write_on
        self.active = False
        self.committed = False
        self.rolled_back = False
        self.begins = 0
        self.statements: list[str] = []
        self.query_transaction_states: list[bool] = []
        self.write_statements: list[str] = []
        self.write_calls: list[tuple[str, dict]] = []
        self.write_transaction_states: list[bool] = []
        self.committed_writes: list[str] = []
        self.transaction_writes: list[str] = []
        self.locked_queries: list[tuple[int, str]] = []
        self.t2_statements: list[str] = []
        self.clear_requested = False

    def begin(self):
        self.begins += 1
        return DrawTransaction(self)

    def in_transaction(self) -> bool:
        return self.active

    @property
    def in_write_transaction(self) -> bool:
        return self.begins >= 2

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.query_transaction_states.append(self.active)
        if self.in_write_transaction:
            self.t2_statements.append(sql)
        if "FOR UPDATE" in sql:
            self.locked_queries.append((self.begins, sql))
        if "set_config" in sql:
            return EmptyResult()
        if "FROM stages s" in sql:
            return RowsResult([self.stage])
        if "FROM stage_teams st" in sql:
            return RowsResult(self.team_rows)
        if "FROM standings" in sql:
            return RowsResult(self.standings)
        if "SELECT 1 FROM tournaments" in sql:
            return ScalarResult(1)
        if "SELECT MAX(matchday)" in sql:
            return ScalarResult(self.configured_rounds)
        if "has_external_links" in sql:
            return ScalarResult(False)
        if "has_external_replacements" in sql:
            return ScalarResult(False)
        if "match_officials" in sql:
            return ScalarResult(False)
        if "matchday < :round_number" in sql:
            if self.in_write_transaction and self.t2_previous_rows is not None:
                return RowsResult(self.t2_previous_rows)
            return RowsResult(self.previous_rows)
        if "matchday = :round_number" in sql:
            if "FOR UPDATE" in sql and self.t2_placeholder_rows is not None:
                return RowsResult(self.t2_placeholder_rows)
            return RowsResult(self.placeholder_rows)
        if "SELECT id, status FROM matches" in sql and "FOR UPDATE" in sql:
            self.clear_requested = True
            return RowsResult([])
        if "SELECT id FROM matches" in sql and "FOR UPDATE" in sql:
            ids = (
                self.t2_existing_ids
                if self.t2_existing_ids is not None
                else self.existing_ids
            )
            return RowsResult([{"id": match_id} for match_id in ids])
        if "SELECT id FROM matches" in sql:
            return RowsResult(
                [{"id": match_id} for match_id in self.existing_ids]
            )
        if "home_team_id IS NOT NULL" in sql:
            return RowsResult(self.history)
        if self._is_write(sql):
            self._record_write(sql, params or {})
            return EmptyResult()
        raise AssertionError(f"consulta inesperada: {sql}")

    @staticmethod
    def _is_write(sql: str) -> bool:
        return any(
            sql.startswith(prefix)
            for prefix in ("INSERT INTO", "UPDATE ", "DELETE FROM")
        )

    def _record_write(self, sql: str, params: dict) -> None:
        if self.fail_write_on is not None and self.fail_write_on in sql:
            raise RuntimeError("write failed")
        self.write_statements.append(sql)
        self.write_calls.append((sql, params))
        self.write_transaction_states.append(self.active)
        self.transaction_writes.append(sql)


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


@asynccontextmanager
async def draw_client(session: DrawSession, *, raise_app_exceptions: bool = True):
    async def database():
        yield session

    async def current_context():
        return context()

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = current_context
    try:
        async with AsyncClient(
            transport=ASGITransport(
                app=api, raise_app_exceptions=raise_app_exceptions
            ),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_auth_context, None)


@pytest.fixture
def allow_management(monkeypatch):
    async def allow(*args, **kwargs):
        return None

    monkeypatch.setattr(tournaments_router, "require_permission", allow)


def payload(**overrides) -> dict:
    body = {
        "version_id": str(VERSION_ID),
        "stage_id": str(STAGE_ID),
        "start_date": "2026-09-18T18:00:00+00:00",
        "swiss_rounds": 1,
        "swiss_round": 1,
    }
    body.update(overrides)
    return body


def install_runner(monkeypatch, session: DrawSession, result=None, error=None):
    calls: list[dict] = []

    async def fake_runner(team_ids, **kwargs):
        calls.append(
            {
                "team_ids": list(team_ids),
                "kwargs": kwargs,
                "in_transaction": session.in_transaction(),
                "writes_so_far": len(session.write_statements),
                "queries_so_far": len(session.query_transaction_states),
            }
        )
        if error is not None:
            raise error
        return result

    monkeypatch.setattr(tournaments_router, "run_swiss_pairing", fake_runner)
    return calls


def pairings_for(team_count: int) -> list[SwissPairing]:
    teams = [UUID(int=index) for index in range(1, team_count + 1)]
    return [
        SwissPairing(teams[index], teams[index + 1])
        for index in range(0, team_count - 1, 2)
    ]


async def post_draw(session: DrawSession, body=None, *, raise_app_exceptions=True):
    async with draw_client(
        session, raise_app_exceptions=raise_app_exceptions
    ) as client:
        return await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/matches/draw",
            json=body or payload(),
        )


async def test_sixty_five_teams_are_rejected_before_writing_or_calculating(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=65)
    calls = install_runner(monkeypatch, session, result=pairings_for(64))

    response = await post_draw(session)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "La fase Swiss admite como máximo 64 equipos"
    }
    assert calls == []
    assert session.write_statements == []
    assert session.committed_writes == []


async def test_sixty_four_teams_are_accepted(monkeypatch, allow_management):
    session = DrawSession(team_count=64)
    calls = install_runner(monkeypatch, session, result=pairings_for(64))

    response = await post_draw(session)

    assert response.status_code == 201
    body = response.json()
    assert body["stage_type"] == "swiss"
    assert body["match_count"] == 32
    assert body["round_number"] == 1
    assert len(calls) == 1
    assert len(calls[0]["team_ids"]) == 64
    assert len(session.write_statements) == 64  # 32 inserts + 32 updates


async def test_calculation_runs_after_the_read_transaction_closes(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=8)
    calls = install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session)

    assert response.status_code == 201
    assert calls[0]["in_transaction"] is False
    assert calls[0]["writes_so_far"] == 0
    assert all(session.query_transaction_states[: calls[0]["queries_so_far"]])
    assert all(session.write_transaction_states)
    assert session.committed is True


async def test_round_one_creates_placeholders_and_pairings_in_the_write_transaction(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=8)
    calls = install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session)

    assert response.status_code == 201
    assert len(calls) == 1
    inserts = [sql for sql in session.write_statements if sql.startswith("INSERT INTO")]
    updates = [sql for sql in session.write_statements if sql.startswith("UPDATE ")]
    assert len(inserts) == 4
    assert len(updates) == 4
    assert all(session.write_transaction_states)
    # No writes were confirmed by the read transaction.
    assert session.committed_writes == session.write_statements


async def test_replace_existing_is_cleared_in_the_write_transaction(
    monkeypatch, allow_management
):
    session = DrawSession(
        team_count=8,
        existing_ids=[uuid4() for _ in range(4)],
        history=[{"home_team_id": UUID(int=1), "away_team_id": UUID(int=2)}],
    )
    calls = install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(
        session, payload(replace_existing=True)
    )

    assert response.status_code == 201
    assert len(calls) == 1
    assert session.clear_requested is True
    assert session.write_statements
    assert all(session.write_transaction_states)
    # The stage is regenerated from scratch: the old history is not an input.
    assert calls[0]["kwargs"]["prior_pairs"] == set()
    assert calls[0]["kwargs"]["home_counts"] == {}
    assert calls[0]["kwargs"]["away_counts"] == {}


async def test_later_rounds_do_not_delete_placeholders_or_previous_matches(
    monkeypatch, allow_management
):
    placeholder_ids = [uuid4() for _ in range(4)]
    session = DrawSession(
        team_count=8,
        version_status="published",
        configured_rounds=8,
        previous_rows=[
            {"id": uuid4(), "status": "finished"} for _ in range(20)
        ],
        placeholder_rows=[
            {"id": match_id, "status": "cancelled"} for match_id in placeholder_ids
        ],
        history=[
            {"home_team_id": UUID(int=1), "away_team_id": UUID(int=2)},
            {"home_team_id": UUID(int=1), "away_team_id": UUID(int=3)},
        ],
    )
    calls = install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session, payload(swiss_round=2, swiss_rounds=8))

    assert response.status_code == 201
    assert response.json()["round_number"] == 2
    assert len(calls) == 1
    assert session.clear_requested is False
    assert not any(
        sql.startswith(("INSERT INTO", "DELETE FROM"))
        for sql in session.write_statements
    )
    assert len(session.write_statements) == 4
    assert all(sql.startswith("UPDATE ") for sql in session.write_statements)
    assert calls[0]["kwargs"]["prior_pairs"] == {
        frozenset((UUID(int=1), UUID(int=2))),
        frozenset((UUID(int=1), UUID(int=3))),
    }
    assert calls[0]["kwargs"]["home_counts"] == {UUID(int=1): 2}
    assert calls[0]["kwargs"]["away_counts"] == {UUID(int=2): 1, UUID(int=3): 1}


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (
            SwissPairingFailure("budget_exhausted", 50_000),
            "presupuesto de emparejamiento agotado",
        ),
        (
            SwissPairingFailure("no_valid_pairing", 120),
            "no existe un sorteo válido sin repetir rivales",
        ),
        (
            SwissPairingTimeout("timeout"),
            "tiempo máximo de cálculo del sorteo excedido",
        ),
    ],
)
async def test_pairing_failures_are_distinct_409_without_writes(
    monkeypatch, allow_management, error, detail, caplog
):
    session = DrawSession(team_count=8)
    install_runner(monkeypatch, session, error=error)

    with caplog.at_level(logging.ERROR, logger="app.modules.tournaments.router"):
        response = await post_draw(session)

    assert response.status_code == 409
    assert response.json() == {"detail": detail}
    assert session.write_statements == []
    assert session.committed_writes == []
    if isinstance(error, SwissPairingTimeout):
        errors = [
            record
            for record in caplog.records
            if record.name == "app.modules.tournaments.router"
            and record.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        assert "tiempo máximo" in errors[0].getMessage()


async def test_validation_value_errors_keep_their_behaviour(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=8)
    install_runner(
        monkeypatch,
        session,
        error=ValueError("La fase necesita al menos dos equipos"),
    )

    response = await post_draw(session, raise_app_exceptions=False)

    # A validation ValueError keeps the sanitized 500 it had before: it is not
    # converted into the new 409 business errors.
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert session.write_statements == []


async def test_revoked_management_permission_in_the_write_phase_is_a_403(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=8)
    install_runner(monkeypatch, session, result=pairings_for(8))
    calls: list[str] = []

    async def permission(db, context, code, tournament_id=None, **kwargs):
        calls.append(code)
        if len(calls) == 2:
            raise PermissionError("La membresía ya no permite gestionar el torneo")

    monkeypatch.setattr(tournaments_router, "require_permission", permission)

    response = await post_draw(session)

    assert response.status_code == 403
    assert calls == ["MANAGE_TOURNAMENTS", "MANAGE_TOURNAMENTS"]
    assert session.write_statements == []
    assert session.committed_writes == []
    # The permission check comes before the state revalidation in T2.
    assert not any("FOR UPDATE" in sql for sql in session.t2_statements)


async def test_a_write_failure_rolls_back_the_whole_schedule(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=8, fail_write_on="INSERT INTO matches")
    install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session, raise_app_exceptions=False)

    assert response.status_code == 500
    assert session.rolled_back is True
    assert session.committed_writes == []


STATE_CHANGED = "el estado de la fase cambió durante el sorteo; vuelve a intentarlo"


async def test_round_one_state_change_in_the_write_phase_is_a_409(
    monkeypatch, allow_management
):
    session = DrawSession(team_count=8, t2_existing_ids=[uuid4()])
    install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session)

    assert response.status_code == 409
    assert response.json() == {"detail": STATE_CHANGED}
    assert session.write_statements == []
    assert session.committed_writes == []
    assert session.rolled_back is True


async def test_later_round_placeholder_no_longer_cancelled_is_a_409(
    monkeypatch, allow_management
):
    placeholder_ids = [uuid4() for _ in range(4)]
    session = DrawSession(
        team_count=8,
        version_status="published",
        configured_rounds=8,
        previous_rows=[{"id": uuid4(), "status": "finished"}],
        placeholder_rows=[
            {"id": match_id, "status": "cancelled"} for match_id in placeholder_ids
        ],
        t2_placeholder_rows=[
            {"id": match_id, "status": "scheduled"} for match_id in placeholder_ids
        ],
    )
    install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session, payload(swiss_round=2, swiss_rounds=8))

    assert response.status_code == 409
    assert response.json() == {"detail": STATE_CHANGED}
    assert session.write_statements == []
    assert session.committed_writes == []


async def test_later_round_previous_round_no_longer_finished_is_a_409(
    monkeypatch, allow_management
):
    placeholder_ids = [uuid4() for _ in range(4)]
    previous_ids = [uuid4(), uuid4()]
    session = DrawSession(
        team_count=8,
        version_status="published",
        configured_rounds=8,
        previous_rows=[
            {"id": match_id, "status": "finished"} for match_id in previous_ids
        ],
        t2_previous_rows=[
            {"id": previous_ids[0], "status": "scheduled"},
            {"id": previous_ids[1], "status": "finished"},
        ],
        placeholder_rows=[
            {"id": match_id, "status": "cancelled"} for match_id in placeholder_ids
        ],
    )
    install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session, payload(swiss_round=2, swiss_rounds=8))

    assert response.status_code == 409
    assert response.json() == {"detail": STATE_CHANGED}
    assert session.write_statements == []


async def test_later_round_detects_a_changed_previous_round_set(
    monkeypatch, allow_management
):
    placeholder_ids = [uuid4() for _ in range(4)]
    previous_ids = [uuid4(), uuid4()]
    session = DrawSession(
        team_count=8,
        version_status="published",
        configured_rounds=8,
        previous_rows=[
            {"id": match_id, "status": "finished"} for match_id in previous_ids
        ],
        t2_previous_rows=[{"id": previous_ids[0], "status": "finished"}],
        placeholder_rows=[
            {"id": match_id, "status": "cancelled"} for match_id in placeholder_ids
        ],
    )
    install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session, payload(swiss_round=2, swiss_rounds=8))

    assert response.status_code == 409
    assert response.json() == {"detail": STATE_CHANGED}
    assert session.write_statements == []


async def test_write_transaction_sets_rls_locks_and_confirms_the_expected_rows(
    monkeypatch, allow_management
):
    placeholder_ids = [uuid4() for _ in range(4)]
    previous_rows = [
        {"id": uuid4(), "status": "finished"},
        {"id": uuid4(), "status": "administrative_resolution"},
    ]
    session = DrawSession(
        team_count=8,
        version_status="published",
        configured_rounds=8,
        previous_rows=previous_rows,
        placeholder_rows=[
            {"id": match_id, "status": "cancelled"} for match_id in placeholder_ids
        ],
    )
    install_runner(monkeypatch, session, result=pairings_for(8))

    response = await post_draw(session, payload(swiss_round=2, swiss_rounds=8))

    assert response.status_code == 201
    # RLS context is fixed before any other statement of the write transaction.
    assert session.t2_statements[0].startswith(
        "SELECT set_config('app.current_organization_id'"
    )
    assert session.t2_statements[1].startswith(
        "SELECT set_config('app.current_user_id'"
    )
    # Previous round and placeholders are locked before writing.
    locks = [(begin, sql) for begin, sql in session.locked_queries if begin == 2]
    assert len(locks) == 2
    assert all("FOR UPDATE" in sql for _, sql in locks)
    first_write = next(
        index
        for index, sql in enumerate(session.t2_statements)
        if sql.startswith("UPDATE ")
    )
    last_lock = max(
        index
        for index, sql in enumerate(session.t2_statements)
        if "FOR UPDATE" in sql
    )
    assert last_lock < first_write

    updates = [
        params
        for sql, params in session.write_calls
        if sql.startswith("UPDATE ")
    ]
    assert [params["match_id"] for params in updates] == [
        str(match_id) for match_id in placeholder_ids
    ]
    expected = pairings_for(8)
    assert [
        (params["home_team_id"], params["away_team_id"]) for params in updates
    ] == [
        (str(pairing.home_team_id), str(pairing.away_team_id))
        for pairing in expected
    ]
    assert session.committed_writes == session.write_statements

    # The read transaction only read; the write transaction held every lock.
    assert all(begin == 2 for begin, _ in session.locked_queries)


# ---------------------------------------------------------------------------
# Opt-in PostgreSQL checks (RF-006, RF-010): skipped without RUN_DATABASE_TESTS=1
# ---------------------------------------------------------------------------


class _NestedTransactions:
    """Run the endpoint's explicit transactions as savepoints of the fixture."""

    def __init__(self, session):
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def in_transaction(self):
        return self._session.in_transaction()

    def __getattr__(self, name):
        return getattr(self._session, name)


def _tenant_context(tenant) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


async def _seed_swiss_stage(session, tenant, *, team_count: int = 4):
    suffix = uuid4().hex[:8]
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', CAST('2026-01-01' AS DATE),
                     'draft', '{}'::jsonb)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"Swiss opt-in {suffix}",
            },
        )
    ).scalar_one()
    version_id = (
        await session.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config,
                     phase_config, status, created_by_member_id)
                VALUES
                    (:organization_id, :tournament_id, 1, '{}'::jsonb, '{}'::jsonb,
                     'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
            },
        )
    ).scalar_one()
    stage_id = (
        await session.execute(
            text("""
                INSERT INTO stages
                    (organization_id, tournament_id, tournament_version_id, name,
                     stage_type, stage_order)
                VALUES
                    (:organization_id, :tournament_id, :version_id, 'Swiss',
                     'swiss', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
            },
        )
    ).scalar_one()
    for index in range(team_count):
        team_id = (
            await session.execute(
                text("""
                    INSERT INTO teams (organization_id, name, short_code)
                    VALUES (:organization_id, :name, :short_code)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "name": f"Team {suffix} {index}",
                    "short_code": f"T{suffix[:4]}{index}",
                },
            )
        ).scalar_one()
        await session.execute(
            text("""
                INSERT INTO tournament_teams
                    (organization_id, tournament_id, team_id, status)
                VALUES (:organization_id, :tournament_id, :team_id, 'registered')
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
            },
        )
        await session.execute(
            text("""
                INSERT INTO stage_teams
                    (organization_id, tournament_id, tournament_version_id,
                     stage_id, team_id)
                VALUES (:organization_id, :tournament_id, :version_id,
                        :stage_id, :team_id)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
    return tournament_id, version_id, stage_id


def _draw_payload(version_id: UUID, stage_id: UUID, *, seed: int = 1):
    return GenerateSingleEliminationRequest(
        version_id=version_id,
        stage_id=stage_id,
        start_date=datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc),
        swiss_rounds=1,
        swiss_round=1,
        seed=seed,
    )


async def _match_count(session, stage_id: UUID) -> int:
    return (
        await session.execute(
            text("SELECT count(*) FROM matches WHERE stage_id = :stage_id"),
            {"stage_id": str(stage_id)},
        )
    ).scalar_one()


async def test_opt_in_pairing_failure_leaves_no_new_or_modified_matches(
    db_session, monkeypatch
):
    tenant = await create_tenant_owner(db_session)
    tournament_id, version_id, stage_id = await _seed_swiss_stage(db_session, tenant)
    before = await _match_count(db_session, stage_id)

    async def fail(*args, **kwargs):
        raise SwissPairingFailure("budget_exhausted", 50_000)

    monkeypatch.setattr(tournaments_router, "run_swiss_pairing", fail)

    with pytest.raises(HTTPException) as failure:
        await tournaments_router.draw_stage_schedule(
            tournament_id,
            _draw_payload(version_id, stage_id),
            context=_tenant_context(tenant),
            db=_NestedTransactions(db_session),
        )

    assert failure.value.status_code == 409
    assert await _match_count(db_session, stage_id) == before == 0


async def test_opt_in_rls_isolation_and_write_phase_reapplies_the_context(
    db_session, monkeypatch
):
    tenant_a = await create_tenant_owner(db_session)
    tournament_a, version_a, stage_a = await _seed_swiss_stage(db_session, tenant_a)
    tenant_b = await create_tenant_owner(db_session)
    _, version_b, stage_b = await _seed_swiss_stage(db_session, tenant_b)

    await set_tenant_context(db_session, tenant_b)
    b_match_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO matches
                (id, organization_id, tournament_id, tournament_version_id, stage_id,
                 bracket_code, matchday, match_date, status)
            VALUES
                (:id, :organization_id, :tournament_id, :version_id, :stage_id,
                 'SW1-1', 1, :match_date, 'cancelled')
        """),
        {
            "id": str(b_match_id),
            "organization_id": str(tenant_b.organization_id),
            "tournament_id": str(tournament_b),
            "version_id": str(version_b),
            "stage_id": str(stage_b),
            "match_date": datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc),
        },
    )

    # Tenant A cannot read or write tenant B's stage.
    await set_tenant_context(db_session, tenant_a)
    assert await _match_count(db_session, stage_b) == 0
    denied = await db_session.execute(
        text("UPDATE matches SET updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
        {"id": str(b_match_id)},
    )
    assert denied.rowcount == 0

    captured: list[str] = []
    original_revalidate = tournaments_router._revalidate_swiss_draw_state

    async def capture_context(db, context, tournament_id, payload, swiss_draw):
        setting = (
            await db.execute(
                text("SELECT current_setting('app.current_organization_id', true)")
            )
        ).scalar_one()
        captured.append(setting)
        return await original_revalidate(
            db, context, tournament_id, payload, swiss_draw
        )

    monkeypatch.setattr(
        tournaments_router, "_revalidate_swiss_draw_state", capture_context
    )

    async def pairings_for_teams(team_ids, **kwargs):
        teams = list(team_ids)
        return tuple(
            SwissPairing(teams[index], teams[index + 1])
            for index in range(0, len(teams) - 1, 2)
        )

    monkeypatch.setattr(
        tournaments_router, "run_swiss_pairing", pairings_for_teams
    )

    await tournaments_router.draw_stage_schedule(
        tournament_a,
        _draw_payload(version_a, stage_a),
        context=_tenant_context(tenant_a),
        db=_NestedTransactions(db_session),
    )

    # The write transaction re-fixed A's RLS context before validating.
    assert captured == [str(tenant_a.organization_id)]

    await set_tenant_context(db_session, tenant_b)
    assert await _match_count(db_session, stage_b) == 1
    await set_tenant_context(db_session, tenant_a)
    assert await _match_count(db_session, stage_a) == 2
