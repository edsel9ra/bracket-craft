"""GET /tournaments/{id}/stages/{stage_id}/teams (T005, RF-018).

The endpoint is read-only: it fixes the RLS context, resolves the tournament and
the stage of the requested organization, and returns the teams assigned to that
stage/version plus the registered teams that are not assigned to it.

The tests use a recording session double and assert the SQL filters, not just
the response shape: deduplication, the stage version, tenant ownership and the
``registered`` status of ``unassigned``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.core.tenancy import AuthContext
from app.modules.tournaments.roster_status import (
    ROSTER_SIZE_OUT_OF_RANGE,
    RosterSizeOutOfRange,
)
from app.modules.tournaments.router import (
    assign_stage_teams,
    list_stage_teams,
    remove_stage_team,
)
from app.modules.tournaments.schemas import AssignStageTeamsRequest

ORGANIZATION_ID = uuid4()
OTHER_ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
STAGE_ID = uuid4()
VERSION_ID = uuid4()
OTHER_VERSION_ID = uuid4()
TEAM_ASSIGNED = uuid4()
TEAM_ASSIGNED_TWICE = uuid4()
TEAM_FREE = uuid4()
TEAM_PENDING = uuid4()
TEAM_OTHER_VERSION = uuid4()


class StopExecution(Exception):
    """Unexpected statement in the session double."""


class Result:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = list(rows or [])
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class StageTeamsSession:
    def __init__(
        self,
        *,
        tournament_exists: bool = True,
        stage_row=None,
        assigned_rows=(),
        unassigned_rows=(),
        stop_on: str | None = None,
    ):
        self.tournament_exists = tournament_exists
        self.stage_row = stage_row
        self.assigned_rows = list(assigned_rows)
        self.unassigned_rows = list(unassigned_rows)
        self.stop_on = stop_on
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []

    def begin(self):
        class Transaction:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        return Transaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        if "set_config" in sql:
            return Result()
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1 if self.tournament_exists else None)
        if "SELECT s.id, s.tournament_version_id" in sql and "FROM stages s" in sql:
            return Result(rows=[self.stage_row] if self.stage_row else [])
        if self.stop_on is not None and self.stop_on in sql:
            raise StopExecution(sql)
        # The unassigned query joins tournament_teams and has a stage_teams
        # NOT EXISTS subquery; check it before the assigned query.
        if "FROM tournament_teams tt" in sql:
            return Result(rows=self.unassigned_rows)
        if "FROM stage_teams st" in sql:
            return Result(rows=self.assigned_rows)
        raise StopExecution(sql)

    def sql_for(self, fragment: str) -> str:
        for sql in self.statements:
            if fragment in sql:
                return sql
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def params_for(self, fragment: str) -> dict:
        for sql, params in self.calls:
            if fragment in sql:
                return params
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def index_of(self, fragment: str) -> int:
        for index, sql in enumerate(self.statements):
            if fragment in sql:
                return index
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def stage() -> dict:
    return {"id": STAGE_ID, "tournament_version_id": VERSION_ID}


def team(team_id: UUID, name: str, short_code: str) -> dict:
    return {"team_id": team_id, "name": name, "short_code": short_code}


# ---------------------------------------------------------------------------
# 404: tournament and stage (same organization only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tournament_is_404():
    session = StageTeamsSession(tournament_exists=False)

    with pytest.raises(HTTPException) as error:
        await list_stage_teams(
            TOURNAMENT_ID, STAGE_ID, context(), session
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Torneo no encontrado"
    assert not any("FROM stages s" in sql for sql in session.statements)


@pytest.mark.asyncio
async def test_unknown_or_foreign_stage_is_404():
    session = StageTeamsSession(stage_row=None)

    with pytest.raises(HTTPException) as error:
        await list_stage_teams(
            TOURNAMENT_ID, STAGE_ID, context(), session
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Fase no encontrada en el torneo"

    stage_sql = session.sql_for("FROM stages s")
    stage_params = session.params_for("FROM stages s")
    assert "organization_id = :organization_id" in stage_sql
    assert "tournament_id = :tournament_id" in stage_sql
    assert stage_params["organization_id"] == str(ORGANIZATION_ID)
    assert stage_params["tournament_id"] == str(TOURNAMENT_ID)
    assert stage_params["stage_id"] == str(STAGE_ID)


# ---------------------------------------------------------------------------
# 200: assigned + unassigned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_assigned_and_unassigned_teams():
    session = StageTeamsSession(
        stage_row=stage(),
        assigned_rows=[
            team(TEAM_ASSIGNED, "Alpha", "ALP"),
            team(TEAM_ASSIGNED_TWICE, "Beta", "BET"),
        ],
        unassigned_rows=[
            team(TEAM_FREE, "Gamma", "GAM"),
        ],
    )

    response = await list_stage_teams(
        TOURNAMENT_ID, STAGE_ID, context(), session
    )

    assert response["stage_id"] == STAGE_ID
    assert response["version_id"] == VERSION_ID
    assert response["assigned"] == [
        {"team_id": TEAM_ASSIGNED, "name": "Alpha", "short_code": "ALP"},
        {"team_id": TEAM_ASSIGNED_TWICE, "name": "Beta", "short_code": "BET"},
    ]
    assert response["unassigned"] == [
        {"team_id": TEAM_FREE, "name": "Gamma", "short_code": "GAM"},
    ]


@pytest.mark.asyncio
async def test_assigned_is_deduplicated_by_team():
    session = StageTeamsSession(
        stage_row=stage(),
        assigned_rows=[team(TEAM_ASSIGNED_TWICE, "Beta", "BET")],
        unassigned_rows=[],
    )

    await list_stage_teams(TOURNAMENT_ID, STAGE_ID, context(), session)

    assigned_sql = session.sql_for("FROM stage_teams st")
    assert "DISTINCT" in assigned_sql.upper()
    assert "st.stage_id = :stage_id" in assigned_sql
    assert "st.tournament_version_id = :version_id" in assigned_sql

    assigned_params = session.params_for("FROM stage_teams st")
    assert assigned_params["version_id"] == str(VERSION_ID)
    assert assigned_params["stage_id"] == str(STAGE_ID)
    assert assigned_params["organization_id"] == str(ORGANIZATION_ID)


# ---------------------------------------------------------------------------
# Version isolation and registered-only unassigned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_queries_use_the_version_of_the_stage():
    session = StageTeamsSession(
        stage_row=stage(),
        assigned_rows=[team(TEAM_ASSIGNED, "Alpha", "ALP")],
        unassigned_rows=[team(TEAM_FREE, "Gamma", "GAM")],
    )

    await list_stage_teams(TOURNAMENT_ID, STAGE_ID, context(), session)

    assigned_sql = session.sql_for("FROM stage_teams st")
    unassigned_sql = session.sql_for("FROM tournament_teams tt")
    assert "tournament_version_id = :version_id" in assigned_sql
    assert "st.tournament_version_id = :version_id" in unassigned_sql
    assert "st.stage_id = :stage_id" in unassigned_sql
    assert "st.team_id = tt.team_id" in unassigned_sql

    assigned_params = session.params_for("FROM stage_teams st")
    unassigned_params = session.params_for("FROM tournament_teams tt")
    assert assigned_params["version_id"] == str(VERSION_ID) == unassigned_params["version_id"]
    assert assigned_params["version_id"] != str(OTHER_VERSION_ID)
    # A team assigned only in another version is not excluded from unassigned.
    assert TEAM_OTHER_VERSION not in {
        row["team_id"] for row in session.unassigned_rows
    }


@pytest.mark.asyncio
async def test_unassigned_only_contains_registered_teams():
    session = StageTeamsSession(
        stage_row=stage(),
        assigned_rows=[team(TEAM_ASSIGNED, "Alpha", "ALP")],
        unassigned_rows=[team(TEAM_FREE, "Gamma", "GAM")],
    )

    response = await list_stage_teams(
        TOURNAMENT_ID, STAGE_ID, context(), session
    )

    unassigned_sql = session.sql_for("FROM tournament_teams tt")
    assert "tt.status = 'registered'" in unassigned_sql
    assert "NOT EXISTS" in unassigned_sql.upper()
    assert TEAM_PENDING not in {row["team_id"] for row in response["unassigned"]}


# ---------------------------------------------------------------------------
# RLS: context, tenant filters and read-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sets_rls_context_and_filters_every_table_by_organization():
    session = StageTeamsSession(
        stage_row=stage(),
        assigned_rows=[],
        unassigned_rows=[],
    )

    await list_stage_teams(TOURNAMENT_ID, STAGE_ID, context(), session)

    assert session.statements[0].startswith(
        "SELECT set_config('app.current_organization_id'"
    )
    assert session.statements[1].startswith(
        "SELECT set_config('app.current_user_id'"
    )
    assert session.params_for("set_config('app.current_organization_id'")[
        "value"
    ] == str(ORGANIZATION_ID)

    tournament_sql = session.sql_for("SELECT 1 FROM tournaments")
    assert "organization_id = :organization_id" in tournament_sql
    assert session.params_for("SELECT 1 FROM tournaments")[
        "organization_id"
    ] == str(ORGANIZATION_ID)

    for fragment in ("FROM stage_teams st", "FROM tournament_teams tt"):
        sql = session.sql_for(fragment)
        params = session.params_for(fragment)
        assert "organization_id = :organization_id" in sql
        assert params["organization_id"] == str(ORGANIZATION_ID)
        assert params["organization_id"] != str(OTHER_ORGANIZATION_ID)


@pytest.mark.asyncio
async def test_is_read_only():
    session = StageTeamsSession(
        stage_row=stage(),
        assigned_rows=[team(TEAM_ASSIGNED, "Alpha", "ALP")],
        unassigned_rows=[team(TEAM_FREE, "Gamma", "GAM")],
    )

    await list_stage_teams(TOURNAMENT_ID, STAGE_ID, context(), session)

    assert not any(
        sql.startswith(("INSERT INTO", "UPDATE ", "DELETE FROM"))
        for sql in session.statements
    )


# ===========================================================================
# POST /tournaments/{id}/stages/{stage_id}/teams (T006)
# ===========================================================================


class AssignmentTransaction:
    def __init__(self, session: "AssignmentSession"):
        self.session = session
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        self.session.active = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.session.active = False
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class AssignmentSession:
    """Session double for the atomic assignment endpoint."""

    def __init__(
        self,
        *,
        tournament_exists: bool = True,
        stage_exists: bool = True,
        version_status: str = "draft",
        permission: bool = True,
        registered_ids=(),
        existing_ids=(),
        fail_on_team: UUID | None = None,
        rules_config=None,
        active_counts: dict[UUID, int] | None = None,
    ):
        self.tournament_exists = tournament_exists
        self.stage_exists = stage_exists
        self.version_status = version_status
        self.permission = permission
        self.registered_ids = set(registered_ids)
        self.existing_ids = set(existing_ids)
        self.fail_on_team = fail_on_team
        self.rules_config = rules_config
        self.active_counts = dict(active_counts or {})
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.writes: list[tuple[str, dict]] = []
        self.transactions: list[AssignmentTransaction] = []
        self.active = False

    def begin(self):
        transaction = AssignmentTransaction(self)
        self.transactions.append(transaction)
        return transaction

    def in_transaction(self):
        return self.active

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = dict(params or {})
        self.statements.append(sql)
        self.calls.append((sql, params))
        if "set_config" in sql:
            return Result()
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1 if self.tournament_exists else None)
        if "tv.status AS version_status" in sql and "FROM stages s" in sql:
            if not self.stage_exists:
                return Result(rows=[])
            return Result(
                rows=[
                    {
                        "id": STAGE_ID,
                        "tournament_version_id": VERSION_ID,
                        "version_status": self.version_status,
                    }
                ]
            )
        if "FROM roles r" in sql:
            return Result(scalar=1 if self.permission else None)
        if "SELECT id, tournament_version_id FROM stages" in sql:
            if not self.stage_exists:
                return Result(rows=[])
            return Result(
                rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}]
            )
        if "SELECT status FROM tournament_versions" in sql and "FOR UPDATE" in sql:
            return Result(scalar=self.version_status)
        if "SELECT rules_config FROM tournament_versions" in sql:
            return Result(rows=[{"rules_config": self.rules_config}])
        if "FROM teams t" in sql and "LEFT JOIN rosters r" in sql:
            requested = [UUID(value) for value in params["team_ids"]]
            return Result(
                rows=[
                    {
                        "team_id": team_id,
                        "team_name": f"Equipo {str(team_id)[:8]}",
                        "active_count": self.active_counts.get(team_id, 0),
                    }
                    for team_id in requested
                ]
            )
        if "FROM tournament_teams" in sql and "status = 'registered'" in sql:
            requested = [UUID(value) for value in params["team_ids"]]
            return Result(
                rows=[
                    {"team_id": team_id}
                    for team_id in requested
                    if team_id in self.registered_ids
                ]
            )
        if "DISTINCT team_id" in sql and "FROM stage_teams" in sql:
            requested = [UUID(value) for value in params["team_ids"]]
            return Result(
                rows=[
                    {"team_id": team_id}
                    for team_id in requested
                    if team_id in self.existing_ids
                ]
            )
        if sql.startswith("INSERT INTO stage_teams"):
            self.writes.append((sql, params))
            if self.fail_on_team is not None and params["team_id"] == str(
                self.fail_on_team
            ):
                raise RuntimeError("insert failed")
            return Result()
        raise StopExecution(sql)

    def sql_for(self, fragment: str) -> str:
        for sql in self.statements:
            if fragment in sql:
                return sql
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def params_for(self, fragment: str) -> dict:
        for sql, params in self.calls:
            if fragment in sql:
                return params
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def index_of(self, fragment: str) -> int:
        for index, sql in enumerate(self.statements):
            if fragment in sql:
                return index
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")


async def post_assignment(session: AssignmentSession, team_ids, response=None):
    return await assign_stage_teams(
        TOURNAMENT_ID,
        STAGE_ID,
        AssignStageTeamsRequest(team_ids=team_ids),
        response if response is not None else Response(),
        context(),
        session,
    )


# ---------------------------------------------------------------------------
# Payload validation (422 before the handler)
# ---------------------------------------------------------------------------


def test_assignment_request_rejects_empty_and_oversized_batches():
    with pytest.raises(ValidationError):
        AssignStageTeamsRequest(team_ids=[])
    with pytest.raises(ValidationError):
        AssignStageTeamsRequest(team_ids=[uuid4() for _ in range(65)])


def test_assignment_request_rejects_duplicates_without_deduplicating():
    duplicate = uuid4()
    with pytest.raises(ValidationError) as error:
        AssignStageTeamsRequest(team_ids=[duplicate, duplicate])

    assert "duplicados" in str(error.value)


def test_assignment_request_rejects_invalid_uuid():
    with pytest.raises(ValidationError):
        AssignStageTeamsRequest.model_validate({"team_ids": ["not-a-uuid"]})


def test_assignment_request_accepts_the_64_team_limit():
    request = AssignStageTeamsRequest(team_ids=[uuid4() for _ in range(64)])
    assert len(request.team_ids) == 64


# ---------------------------------------------------------------------------
# 404 / 409 / 403 precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_unknown_tournament_is_404_before_permission():
    session = AssignmentSession(tournament_exists=False)

    with pytest.raises(HTTPException) as error:
        await post_assignment(session, [TEAM_ASSIGNED])

    assert error.value.status_code == 404
    assert not any("FROM roles r" in sql for sql in session.statements)
    assert session.writes == []


@pytest.mark.asyncio
async def test_assignment_unknown_or_foreign_stage_is_404():
    session = AssignmentSession(stage_exists=False)

    with pytest.raises(HTTPException) as error:
        await post_assignment(session, [TEAM_ASSIGNED])

    assert error.value.status_code == 404
    assert error.value.detail == "Fase no encontrada en el torneo"
    stage_sql = session.sql_for("tv.status AS version_status")
    params = session.params_for("tv.status AS version_status")
    assert "organization_id = :organization_id" in stage_sql
    assert params["organization_id"] == str(ORGANIZATION_ID)
    assert params["tournament_id"] == str(TOURNAMENT_ID)
    assert params["stage_id"] == str(STAGE_ID)
    assert session.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("version_status", ["published", "archived"])
async def test_assignment_non_draft_is_409_before_permission(version_status):
    session = AssignmentSession(
        version_status=version_status,
        permission=True,
        registered_ids=[TEAM_ASSIGNED],
    )

    with pytest.raises(HTTPException) as error:
        await post_assignment(session, [TEAM_ASSIGNED])

    assert error.value.status_code == 409
    # Version comes before permission, team validation and idempotency.
    assert not any("FROM roles r" in sql for sql in session.statements)
    assert not any("SELECT id, tournament_version_id" in sql for sql in session.statements)
    assert not any("FROM tournament_teams" in sql for sql in session.statements)
    assert session.writes == []


@pytest.mark.asyncio
async def test_assignment_without_permission_is_403_in_a_draft():
    session = AssignmentSession(permission=False, registered_ids=[TEAM_ASSIGNED])

    with pytest.raises(HTTPException) as error:
        await post_assignment(session, [TEAM_ASSIGNED])

    assert error.value.status_code == 403
    assert not any("SELECT id, tournament_version_id" in sql for sql in session.statements)
    assert session.writes == []


@pytest.mark.asyncio
async def test_assignment_rejects_a_non_registered_team_without_writes():
    session = AssignmentSession(
        permission=True,
        registered_ids=[TEAM_ASSIGNED],
    )

    with pytest.raises(HTTPException) as error:
        await post_assignment(session, [TEAM_ASSIGNED, TEAM_PENDING])

    assert error.value.status_code == 409
    assert session.writes == []
    assert session.transactions[-1].rolled_back is True


# ---------------------------------------------------------------------------
# Idempotency and response arrays
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_inserts_new_teams_and_returns_201():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_FREE],
    )
    response = Response()

    result = await post_assignment(
        session, [TEAM_FREE, TEAM_ASSIGNED], response
    )

    assert response.status_code == 201
    assert result == {
        "stage_id": STAGE_ID,
        "version_id": VERSION_ID,
        "team_ids": [TEAM_FREE, TEAM_ASSIGNED],
        "assigned": [TEAM_FREE, TEAM_ASSIGNED],
        "already_assigned": [],
    }
    assert len(session.writes) == 2
    inserted = [params["team_id"] for _, params in session.writes]
    assert inserted == [str(TEAM_FREE), str(TEAM_ASSIGNED)]
    for _, params in session.writes:
        assert params["organization_id"] == str(ORGANIZATION_ID)
        assert params["tournament_id"] == str(TOURNAMENT_ID)
        assert params["version_id"] == str(VERSION_ID)
        assert params["stage_id"] == str(STAGE_ID)
        assert params["group_id"] is None


@pytest.mark.asyncio
async def test_assignment_mixed_batch_returns_201_with_both_arrays():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_ASSIGNED_TWICE, TEAM_FREE],
        existing_ids=[TEAM_ASSIGNED_TWICE],
    )
    response = Response()

    result = await post_assignment(
        session,
        [TEAM_ASSIGNED, TEAM_ASSIGNED_TWICE, TEAM_FREE],
        response,
    )

    assert response.status_code == 201
    assert result["team_ids"] == [
        TEAM_ASSIGNED,
        TEAM_ASSIGNED_TWICE,
        TEAM_FREE,
    ]
    assert result["assigned"] == [TEAM_ASSIGNED, TEAM_FREE]
    assert result["already_assigned"] == [TEAM_ASSIGNED_TWICE]
    assert len(result["assigned"]) == len(set(result["assigned"]))
    assert len(result["already_assigned"]) == len(set(result["already_assigned"]))
    assert len(session.writes) == 2


@pytest.mark.asyncio
async def test_assignment_all_already_assigned_returns_200_without_writes():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_FREE],
        existing_ids=[TEAM_ASSIGNED, TEAM_FREE],
    )
    response = Response()

    result = await post_assignment(
        session, [TEAM_FREE, TEAM_ASSIGNED], response
    )

    assert response.status_code == 200
    assert result["assigned"] == []
    assert result["already_assigned"] == [TEAM_FREE, TEAM_ASSIGNED]
    assert session.writes == []


@pytest.mark.asyncio
async def test_assignment_reads_existing_rows_for_the_stage_version():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_FREE],
        existing_ids=[TEAM_ASSIGNED],
    )

    await post_assignment(session, [TEAM_ASSIGNED, TEAM_FREE])

    existing_sql = session.sql_for("DISTINCT team_id")
    existing_params = session.params_for("DISTINCT team_id")
    assert "stage_id = :stage_id" in existing_sql
    assert "tournament_version_id = :version_id" in existing_sql
    assert "organization_id = :organization_id" in existing_sql
    assert existing_params["version_id"] == str(VERSION_ID)
    assert existing_params["stage_id"] == str(STAGE_ID)


# ---------------------------------------------------------------------------
# Roster size block (RF-045)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_with_limits_inside_the_range_still_returns_201():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED],
        rules_config={"min_players_per_team": 11, "max_players_per_team": 20},
        active_counts={TEAM_ASSIGNED: 12},
    )
    response = Response()

    await post_assignment(session, [TEAM_ASSIGNED], response)

    assert response.status_code == 201
    assert len(session.writes) == 1
    # The version limits and the count are read before the first insert.
    assert session.index_of(
        "SELECT rules_config FROM tournament_versions"
    ) < session.index_of("INSERT INTO stage_teams")
    assert session.index_of("LEFT JOIN rosters r") < session.index_of(
        "INSERT INTO stage_teams"
    )


@pytest.mark.asyncio
async def test_assignment_without_limits_does_not_count_rosters():
    session = AssignmentSession(registered_ids=[TEAM_ASSIGNED])
    response = Response()

    await post_assignment(session, [TEAM_ASSIGNED], response)

    assert response.status_code == 201
    assert not any("LEFT JOIN rosters r" in sql for sql in session.statements)


@pytest.mark.asyncio
async def test_assignment_with_a_team_out_of_range_is_the_coded_409_without_writes():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_FREE],
        rules_config={"min_players_per_team": 11, "max_players_per_team": 20},
        active_counts={TEAM_ASSIGNED: 3, TEAM_FREE: 15},
    )

    with pytest.raises(RosterSizeOutOfRange) as error:
        await post_assignment(session, [TEAM_FREE, TEAM_ASSIGNED])

    assert error.value.status_code == 409
    assert error.value.code == ROSTER_SIZE_OUT_OF_RANGE
    assert "«" in error.value.detail and "mínimo: 11" in error.value.detail
    # All-or-nothing: the team inside the range is not enrolled either.
    assert session.writes == []
    assert session.transactions[-1].rolled_back is True


# ---------------------------------------------------------------------------
# Lock order, atomicity and untouched structures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_locks_stage_then_version_before_reading_or_writing():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_FREE],
        existing_ids=[TEAM_ASSIGNED],
    )

    await post_assignment(session, [TEAM_ASSIGNED, TEAM_FREE])

    stage_lock = session.index_of("SELECT id, tournament_version_id FROM stages")
    version_lock = session.index_of("SELECT status FROM tournament_versions")
    registered = session.index_of("FROM tournament_teams")
    existing = session.index_of("DISTINCT team_id")
    first_write = session.index_of("INSERT INTO stage_teams")

    assert stage_lock < version_lock < registered < existing < first_write
    assert "FOR UPDATE" in session.statements[stage_lock]
    assert "FOR UPDATE" in session.statements[version_lock]


@pytest.mark.asyncio
async def test_assignment_is_atomic_when_an_insert_fails():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED, TEAM_FREE],
        fail_on_team=TEAM_FREE,
    )

    with pytest.raises(RuntimeError):
        await post_assignment(session, [TEAM_ASSIGNED, TEAM_FREE])

    assert session.transactions[-1].rolled_back is True
    assert session.transactions[-1].committed is False


@pytest.mark.asyncio
async def test_assignment_does_not_touch_calendar_groups_slots_or_matches():
    session = AssignmentSession(
        registered_ids=[TEAM_ASSIGNED],
    )

    await post_assignment(session, [TEAM_ASSIGNED])

    joined = " ".join(session.statements)
    assert "INSERT INTO matches" not in joined
    assert "UPDATE matches" not in joined
    assert "DELETE FROM matches" not in joined
    assert "phase_slots" not in joined
    assert "groups" not in joined
    assert not any(
        sql.startswith(("UPDATE ", "DELETE FROM")) for sql in session.statements
    )


# ===========================================================================
# DELETE /tournaments/{id}/stages/{stage_id}/teams/{team_id} (T007)
# ===========================================================================


class DeleteSession:
    """Session double for the guarded removal of a team from a stage."""

    def __init__(
        self,
        *,
        tournament_exists: bool = True,
        stage_exists: bool = True,
        version_status: str = "draft",
        permission: bool = True,
        team_registered: bool = True,
        has_match: bool = False,
        has_standings: bool = False,
        stage_team_rows: int = 1,
        stop_on: str | None = None,
    ):
        self.tournament_exists = tournament_exists
        self.stage_exists = stage_exists
        self.version_status = version_status
        self.permission = permission
        self.team_registered = team_registered
        self.has_match = has_match
        self.has_standings = has_standings
        self.stage_team_rows = stage_team_rows
        self.stop_on = stop_on
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.deletes: list[tuple[str, dict]] = []
        self.transactions: list[AssignmentTransaction] = []
        self.active = False

    def begin(self):
        transaction = AssignmentTransaction(self)
        self.transactions.append(transaction)
        return transaction

    def in_transaction(self):
        return self.active

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = dict(params or {})
        self.statements.append(sql)
        self.calls.append((sql, params))
        if "set_config" in sql:
            return Result()
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1 if self.tournament_exists else None)
        if "tv.status AS version_status" in sql and "FROM stages s" in sql:
            if not self.stage_exists:
                return Result(rows=[])
            return Result(
                rows=[
                    {
                        "id": STAGE_ID,
                        "tournament_version_id": VERSION_ID,
                        "version_status": self.version_status,
                    }
                ]
            )
        if "FROM roles r" in sql:
            return Result(scalar=1 if self.permission else None)
        if "SELECT id, tournament_version_id FROM stages" in sql:
            if not self.stage_exists:
                return Result(rows=[])
            return Result(
                rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}]
            )
        if "SELECT status FROM tournament_versions" in sql and "FOR UPDATE" in sql:
            return Result(scalar=self.version_status)
        if "SELECT 1" in sql and "FROM tournament_teams" in sql:
            return Result(scalar=1 if self.team_registered else None)
        if "FROM matches" in sql:
            return Result(scalar=1 if self.has_match else None)
        if "FROM standings" in sql:
            return Result(scalar=1 if self.has_standings else None)
        if self.stop_on is not None and self.stop_on in sql:
            raise StopExecution(sql)
        if sql.startswith("DELETE FROM stage_teams"):
            self.deletes.append((sql, params))
            return Result(rowcount=self.stage_team_rows)
        raise StopExecution(sql)

    def sql_for(self, fragment: str) -> str:
        for sql in self.statements:
            if fragment in sql:
                return sql
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def params_for(self, fragment: str) -> dict:
        for sql, params in self.calls:
            if fragment in sql:
                return params
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def index_of(self, fragment: str) -> int:
        for index, sql in enumerate(self.statements):
            if fragment in sql:
                return index
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")


async def delete_assignment(session: DeleteSession):
    return await remove_stage_team(
        TOURNAMENT_ID,
        STAGE_ID,
        TEAM_ASSIGNED,
        context(),
        session,
    )


# ---------------------------------------------------------------------------
# 404 / 409 published / 403 precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_unknown_tournament_is_404_before_permission():
    session = DeleteSession(tournament_exists=False)

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 404
    assert not any("FROM roles r" in sql for sql in session.statements)
    assert session.deletes == []


@pytest.mark.asyncio
async def test_delete_unknown_or_foreign_stage_is_404():
    session = DeleteSession(stage_exists=False)

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 404
    assert error.value.detail == "Fase no encontrada en el torneo"
    stage_sql = session.sql_for("tv.status AS version_status")
    params = session.params_for("tv.status AS version_status")
    assert "organization_id = :organization_id" in stage_sql
    assert params["organization_id"] == str(ORGANIZATION_ID)
    assert params["tournament_id"] == str(TOURNAMENT_ID)
    assert params["stage_id"] == str(STAGE_ID)
    assert session.deletes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("version_status", ["published", "archived"])
async def test_delete_non_draft_is_409_even_when_not_assigned(version_status):
    session = DeleteSession(
        version_status=version_status,
        permission=True,
        team_registered=True,
        stage_team_rows=0,
    )

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 409
    # Version precedes permission, registration and idempotency.
    assert not any("FROM roles r" in sql for sql in session.statements)
    assert not any("FROM tournament_teams" in sql for sql in session.statements)
    assert session.deletes == []


@pytest.mark.asyncio
async def test_delete_without_permission_is_403_in_a_draft():
    session = DeleteSession(permission=False)

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 403
    assert not any("SELECT id, tournament_version_id" in sql for sql in session.statements)
    assert session.deletes == []


# ---------------------------------------------------------------------------
# Team guards: registered, matches, standings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_non_registered_team_is_409_without_writes():
    session = DeleteSession(team_registered=False)

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 409
    assert "registrado" in error.value.detail
    assert session.deletes == []
    assert session.transactions[-1].rolled_back is True


@pytest.mark.asyncio
async def test_delete_team_with_a_match_in_the_stage_is_409():
    session = DeleteSession(team_registered=True, has_match=True)

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 409
    assert "partido" in error.value.detail
    match_sql = session.sql_for("FROM matches")
    assert "home_team_id = :team_id" in match_sql
    assert "away_team_id = :team_id" in match_sql
    assert "stage_id = :stage_id" in match_sql
    assert "tournament_version_id = :version_id" in match_sql
    assert session.deletes == []


@pytest.mark.asyncio
async def test_delete_team_with_standings_and_no_matches_is_409():
    session = DeleteSession(
        team_registered=True,
        has_match=False,
        has_standings=True,
    )

    with pytest.raises(HTTPException) as error:
        await delete_assignment(session)

    assert error.value.status_code == 409
    assert "clasificación" in error.value.detail
    standings_sql = session.sql_for("FROM standings")
    assert "team_id = :team_id" in standings_sql
    assert "stage_id = :stage_id" in standings_sql
    assert session.deletes == []
    # Standings are never deleted by this endpoint.
    assert not any(
        sql.startswith("DELETE FROM standings") for sql in session.statements
    )


# ---------------------------------------------------------------------------
# 204 idempotent and multi-row removal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_returns_204_when_the_team_was_not_assigned():
    session = DeleteSession(stage_team_rows=0)

    result = await delete_assignment(session)

    assert result is None
    assert len(session.deletes) == 1
    assert session.transactions[-1].committed is True


@pytest.mark.asyncio
async def test_delete_removes_every_row_of_the_team_in_the_stage():
    session = DeleteSession(stage_team_rows=2)

    await delete_assignment(session)

    assert len(session.deletes) == 1
    sql, params = session.deletes[0]
    assert "DELETE FROM stage_teams" in sql
    assert "stage_id = :stage_id" in sql
    assert "tournament_version_id = :version_id" in sql
    assert "team_id = :team_id" in sql
    # No group filter: all rows of the team in the stage are removed.
    assert "group_id" not in sql
    assert params["organization_id"] == str(ORGANIZATION_ID)
    assert params["tournament_id"] == str(TOURNAMENT_ID)
    assert params["version_id"] == str(VERSION_ID)
    assert params["stage_id"] == str(STAGE_ID)
    assert params["team_id"] == str(TEAM_ASSIGNED)


@pytest.mark.asyncio
async def test_delete_does_not_touch_matches_groups_slots_or_standings():
    session = DeleteSession(stage_team_rows=2)

    await delete_assignment(session)

    joined = " ".join(session.statements)
    assert "DELETE FROM matches" not in joined
    assert "DELETE FROM standings" not in joined
    assert "DELETE FROM groups" not in joined
    assert "phase_slots" not in joined
    assert not any(sql.startswith("UPDATE ") for sql in session.statements)


# ---------------------------------------------------------------------------
# Lock order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_locks_stage_then_version_before_reading_or_writing():
    session = DeleteSession(has_match=False, has_standings=False)

    await delete_assignment(session)

    stage_lock = session.index_of("SELECT id, tournament_version_id FROM stages")
    version_lock = session.index_of("SELECT status FROM tournament_versions")
    registered = session.index_of("FROM tournament_teams")
    matches = session.index_of("FROM matches")
    standings = session.index_of("FROM standings")
    delete = session.index_of("DELETE FROM stage_teams")

    assert stage_lock < version_lock < registered < matches < standings < delete
    assert "FOR UPDATE" in session.statements[stage_lock]
    assert "FOR UPDATE" in session.statements[version_lock]
