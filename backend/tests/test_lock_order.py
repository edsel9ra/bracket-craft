"""Lock protocol: stage -> version -> matches -> segments -> players (T004).

The tests use a recording session double. They do not need PostgreSQL: they
assert the order in which the real route/service code issues the ``FOR UPDATE``
statements and that no write happens before the locks.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.locking import lock_matches, lock_stage_and_version, lock_version
from app.core.tenancy import AuthContext
from app.modules.advancement.service import AdvancementService
from app.modules.matches.router import assign_match_official, remove_match_official
from app.modules.matches.schemas import OfficialAssignmentRequest
from app.modules.matches.service import CloseMatchReportService
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.standings.service import StandingsService
from app.modules.tournaments import router as tournaments_router
from app.modules.tournaments.router import (
    create_match,
    create_stage,
    create_tournament_team,
    create_tournament_teams_bulk,
    draw_stage_schedule,
    generate_single_elimination_matches,
    publish_version,
)
from app.modules.tournaments.schemas import (
    BulkTournamentTeamItem,
    BulkTournamentTeamRequest,
    CreateMatchRequest,
    CreateStageRequest,
    CreateTournamentTeamRequest,
    GenerateSingleEliminationRequest,
)

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
VERSION_ID = uuid4()
STAGE_ID = uuid4()
TEAM_A = uuid4()
TEAM_B = uuid4()
MATCH_ID = uuid4()
SEGMENT_ID = uuid4()
TARGET_LOW = UUID("00000000-0000-4000-8000-000000000001")
TARGET_HIGH = UUID("00000000-0000-4000-8000-0000000000ff")
RESET_ID = UUID("00000000-0000-4000-8000-0000000000f0")
PLAYER_ID = uuid4()

START_DATE = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)


def close_rules_config() -> dict:
    """Configuración de reglas completa: el cierre valida el resultado (paso 13)."""

    return deepcopy(DEFAULT_RULES_CONFIG)


class StopExecution(Exception):
    """Stop a route once the assertion point has been reached."""


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

    def one(self):
        assert self._rows, "se esperaba una fila"
        return self._rows[0]

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class Transaction:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class RecordingSession:
    """AsyncSession double that records every statement in order."""

    def __init__(self, **kwargs):
        self.statements: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.stop_on: str | None = kwargs.pop("stop_on", None)
        self.version_status: str = kwargs.pop("version_status", "draft")
        self.stage_type: str = kwargs.pop("stage_type", "round_robin")
        for key, value in kwargs.items():
            setattr(self, key, value)

    def begin(self):
        return Transaction()

    def in_transaction(self):
        return True

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    # -- helpers ---------------------------------------------------------
    def index(self, fragment: str) -> int:
        for position, sql in enumerate(self.statements):
            if fragment in sql:
                return position
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    def parameters(self, fragment: str) -> dict:
        for sql, params in self.calls:
            if fragment in sql:
                return params
        raise AssertionError(f"no se encontró {fragment!r} en {self.statements}")

    # -- routing ---------------------------------------------------------
    def handle(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "SELECT 1 FROM tournaments" in sql:
            return Result(scalar=1)
        if "FROM roles r" in sql:
            return Result(scalar=1)
        # Effective roster limits of the stage's version (RF-045): no limits.
        if "SELECT rules_config" in sql and "FROM tournament_versions" in sql:
            return Result(rows=[{"rules_config": {}}])
        # Lock helpers.
        if "SELECT id, tournament_version_id" in sql and "FROM stages" in sql:
            return Result(
                rows=[{"id": self.stage_id, "tournament_version_id": self.version_id}]
            )
        if (
            "SELECT status" in sql
            and "FROM tournament_versions" in sql
            and "FOR UPDATE" in sql
        ):
            return Result(scalar=self.version_status)
        # _load_draft_stage_context.
        if "tv.status AS version_status" in sql and "FROM stages s" in sql:
            return Result(
                rows=[
                    {
                        "version_status": self.version_status,
                        "tournament_version_id": self.version_id,
                        "stage_type": self.stage_type,
                    }
                ]
            )
        # Stage lookup in create_tournament_team / bulk.
        if (
            "SELECT s.id, s.tournament_version_id, tv.status AS version_status" in sql
        ):
            return Result(
                rows=[
                    {
                        "id": self.stage_id,
                        "tournament_version_id": self.version_id,
                        "version_status": self.version_status,
                    }
                ]
            )
        if self.stop_on is not None and self.stop_on in sql:
            raise StopExecution(sql)
        if "FROM stage_teams st" in sql:
            return Result(rows=self.team_rows)
        if "FROM matches" in sql:
            return Result(scalar=None, rows=[])
        if "FROM tournament_teams" in sql:
            return Result(scalar=1)
        if "FROM groups" in sql:
            return Result(scalar=1)
        if "FROM teams" in sql:
            return Result(rows=[])
        raise StopExecution(sql)


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


def stage_session(**overrides) -> RecordingSession:
    return RecordingSession(
        stage_id=STAGE_ID,
        version_id=VERSION_ID,
        **overrides,
    )


def assert_stage_version_before(session: RecordingSession, stop_index: int) -> None:
    stage_index = session.index("SELECT id, tournament_version_id")
    version_index = session.index("SELECT status FROM tournament_versions")
    assert "FOR UPDATE" in session.statements[stage_index]
    assert "FOR UPDATE" in session.statements[version_index]
    assert stage_index < version_index < stop_index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_stage_and_version_locks_stage_before_version():
    session = stage_session()
    version_id, status = await lock_stage_and_version(
        session, ORGANIZATION_ID, TOURNAMENT_ID, STAGE_ID
    )

    assert version_id == VERSION_ID
    assert status == "draft"
    assert "FROM stages" in session.statements[0]
    assert "FOR UPDATE" in session.statements[0]
    assert "FROM tournament_versions" in session.statements[1]
    assert "FOR UPDATE" in session.statements[1]


@pytest.mark.asyncio
async def test_lock_version_is_version_only():
    session = stage_session()
    status = await lock_version(
        session, ORGANIZATION_ID, VERSION_ID, tournament_id=TOURNAMENT_ID
    )

    assert status == "draft"
    assert len(session.statements) == 1
    assert "FROM tournament_versions" in session.statements[0]
    assert "FOR UPDATE" in session.statements[0]


@pytest.mark.asyncio
async def test_lock_matches_deduplicates_and_orders_by_id():
    session = stage_session()
    session.handle = lambda sql, params: Result(
        rows=[{"id": TARGET_LOW}, {"id": TARGET_HIGH}]
    )
    await lock_matches(
        session,
        ORGANIZATION_ID,
        (TARGET_HIGH, TARGET_LOW, TARGET_HIGH),
    )

    sql, params = session.calls[0]
    assert "ORDER BY id" in sql
    assert "FOR UPDATE" in sql
    assert params["match_ids"] == [str(TARGET_HIGH), str(TARGET_LOW)]


# ---------------------------------------------------------------------------
# Route locks: phase before version, version before matches/teams
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_match_locks_stage_and_version_before_team_checks():
    session = stage_session(stop_on="FROM tournament_teams")
    payload = CreateMatchRequest(
        version_id=VERSION_ID,
        stage_id=STAGE_ID,
        home_team_id=TEAM_A,
        away_team_id=TEAM_B,
        match_date=START_DATE,
    )

    with pytest.raises(StopExecution):
        await create_match(TOURNAMENT_ID, payload, context(), session)

    stop_index = session.index("FROM tournament_teams")
    assert_stage_version_before(session, stop_index)
    assert not any(sql.startswith("INSERT INTO matches") for sql in session.statements)


@pytest.mark.asyncio
async def test_team_creation_locks_stage_and_version_before_writes():
    session = stage_session(stop_on="INSERT INTO teams")
    payload = CreateTournamentTeamRequest(
        name="Alpha", short_code="ALPHA", stage_id=STAGE_ID
    )

    with pytest.raises(StopExecution):
        await create_tournament_team(TOURNAMENT_ID, payload, context(), session)

    stop_index = session.index("INSERT INTO teams")
    assert_stage_version_before(session, stop_index)
    assert not any(
        sql.startswith("INSERT INTO stage_teams") for sql in session.statements
    )


@pytest.mark.asyncio
async def test_bulk_team_creation_locks_stage_and_version_before_writes():
    session = stage_session(stop_on="INSERT INTO teams")
    payload = BulkTournamentTeamRequest(
        teams=[BulkTournamentTeamItem(name="Alpha", short_code="ALPHA")],
        stage_id=STAGE_ID,
    )

    with pytest.raises(StopExecution):
        await create_tournament_teams_bulk(
            TOURNAMENT_ID, payload, context(), session
        )

    stop_index = session.index("INSERT INTO teams")
    assert_stage_version_before(session, stop_index)
    assert not any(
        sql.startswith("INSERT INTO stage_teams") for sql in session.statements
    )


def generation_payload() -> GenerateSingleEliminationRequest:
    return GenerateSingleEliminationRequest(
        version_id=VERSION_ID,
        stage_id=STAGE_ID,
        start_date=START_DATE,
        seed=7,
    )


@pytest.mark.asyncio
async def test_bracket_generation_locks_before_reading_stage_teams():
    session = stage_session(
        stage_type="single_elimination", stop_on="FROM stage_teams"
    )

    with pytest.raises(StopExecution):
        await generate_single_elimination_matches(
            TOURNAMENT_ID, generation_payload(), context(), session
        )

    stop_index = session.index("FROM stage_teams")
    assert_stage_version_before(session, stop_index)
    assert not any(sql.startswith("INSERT INTO") for sql in session.statements)


@pytest.mark.asyncio
async def test_draw_locks_before_reading_stage_teams():
    session = stage_session(stage_type="round_robin", stop_on="FROM stage_teams")

    with pytest.raises(StopExecution):
        await draw_stage_schedule(
            TOURNAMENT_ID, generation_payload(), context(), session
        )

    stop_index = session.index("FROM stage_teams")
    assert_stage_version_before(session, stop_index)
    assert not any(sql.startswith("INSERT INTO") for sql in session.statements)


@pytest.mark.asyncio
async def test_generation_locks_version_before_matches():
    session = stage_session(
        stage_type="single_elimination",
        stop_on="SELECT id, status FROM matches",
        team_rows=[
            {"team_id": TEAM_A, "group_id": None},
            {"team_id": TEAM_B, "group_id": None},
        ],
    )
    payload = GenerateSingleEliminationRequest(
        version_id=VERSION_ID,
        stage_id=STAGE_ID,
        start_date=START_DATE,
        seed=7,
        replace_existing=True,
    )

    with pytest.raises(StopExecution):
        await generate_single_elimination_matches(
            TOURNAMENT_ID, payload, context(), session
        )

    match_lock_index = session.index("SELECT id, status FROM matches")
    assert_stage_version_before(session, match_lock_index)
    assert "FOR UPDATE" in session.statements[match_lock_index]
    assert "ORDER BY id" in session.statements[match_lock_index]
    assert "ORDER BY bracket_code" not in session.statements[match_lock_index]
    assert not any(sql.startswith("INSERT INTO") for sql in session.statements)


# ---------------------------------------------------------------------------
# Closing: source and destinations are locked by id before writing events
# ---------------------------------------------------------------------------


class CloseSession(RecordingSession):
    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.calls.append((sql, dict(params or {})))
        return self.handle(sql, dict(params or {}))

    def handle(self, sql: str, params: dict) -> Result:
        if "set_config" in sql:
            return Result()
        if "SELECT id, tournament_id, tournament_version_id, stage_id, bracket_code" in sql:
            return Result(
                rows=[
                    {
                        "id": MATCH_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "tournament_version_id": VERSION_ID,
                        "stage_id": STAGE_ID,
                        "bracket_code": "GF1",
                    }
                ]
            )
        if "SELECT id, tournament_version_id" in sql and "FROM stages" in sql:
            return Result(
                rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}]
            )
        if "SELECT status" in sql and "FROM tournament_versions" in sql:
            return Result(scalar="published")
        if "FROM advancement_links" in sql:
            return Result(
                rows=[
                    {"target_match_id": TARGET_HIGH},
                    {"target_match_id": TARGET_LOW},
                ]
            )
        if "bracket_code = :reset_code" in sql:
            return Result(rows=[{"id": RESET_ID}])
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql:
            ids = sorted(UUID(match_id) for match_id in params["match_ids"])
            return Result(rows=[{"id": match_id} for match_id in ids])
        if "FOR UPDATE OF m" in sql:
            return Result(
                rows=[
                    {
                        "id": MATCH_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "tournament_version_id": VERSION_ID,
                        "matchday": 1,
                        "match_date": START_DATE,
                        "bracket_code": "GF1",
                        "status": "scheduled",
                        "stage_id": STAGE_ID,
                        "home_team_id": TEAM_A,
                        "away_team_id": TEAM_B,
                        "rules_config": close_rules_config(),
                        "version_status": "published",
                    }
                ]
            )
        if "FROM roles r" in sql:
            return Result(scalar=1)
        if "FROM match_segments" in sql and "status = 'active'" in sql:
            return Result(rows=[{"id": SEGMENT_ID, "minute_start": 0}])
        raise StopExecution(sql)


@pytest.mark.asyncio
async def test_close_locks_source_and_destinations_by_id_before_persisting_events():
    session = CloseSession()
    service = CloseMatchReportService(session)

    async def no_rosters(context, match_id):
        return []

    async def no_segments(context, match_id):
        return []

    async def no_suspensions(context, tournament_id, player_ids):
        return None

    service._load_match_rosters = no_rosters
    service._load_match_segments = no_segments
    service._validate_suspensions = no_suspensions
    service._validate_rosters = lambda match, rosters: None
    service._validate_segments = lambda *args, **kwargs: None
    service._validate_substitutions = lambda dto, match, rosters, limits: None
    service._validate_event_score_consistency = lambda *args, **kwargs: None

    # El resultado se calcula en el paso 13 (antes de persistir), así que el
    # doble declara un desenlace decisivo: esta prueba solo mide el orden de
    # bloqueo. Un walkover con el marcador de la configuración (3-0) y ganador
    # no necesita eventos ni plantilla y evita el 409 de la gran final (GF1).
    dto = SimpleNamespace(
        resolution_type="walkover",
        events=[],
        home_score_regular=3,
        away_score_regular=0,
        home_score=None,
        away_score=None,
        home_penalties=None,
        away_penalties=None,
        winner_team_id=TEAM_A,
        # RF-007: el motivo de catálogo viaja al acta y a la auditoría.
        reason="no_show",
    )

    with pytest.raises(StopExecution):
        await service.execute(context(), MATCH_ID, dto)

    # El walkover **no recorre el tronco** (spec 016): su rama escribe en el
    # paso 14′ y el doble se detiene justo ahí, cuando todos los bloqueos ya se
    # tomaron. La última sentencia registrada es esa primera escritura.
    assert session.statements[-1].upper().startswith("UPDATE MATCHES")
    statements = session.statements[:-1]
    stage_index = next(
        index for index, sql in enumerate(statements) if "FROM stages" in sql
    )
    version_index = next(
        index
        for index, sql in enumerate(statements)
        if "FROM tournament_versions" in sql
    )
    lock_index = next(
        index
        for index, sql in enumerate(statements)
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql
    )
    identity_index = next(
        index
        for index, sql in enumerate(statements)
        if "SELECT id, tournament_id, tournament_version_id, stage_id, bracket_code" in sql
    )

    # Identity is read unlocked, then phase, version and the whole match set.
    assert identity_index < stage_index
    assert stage_index < version_index < lock_index
    assert "ORDER BY id" in statements[lock_index]
    assert "FOR UPDATE" in statements[lock_index]
    lock_params = next(
        params
        for sql, params in session.calls
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql
    )
    assert set(lock_params["match_ids"]) == {
        str(MATCH_ID),
        str(TARGET_LOW),
        str(TARGET_HIGH),
        str(RESET_ID),
    }
    # Nothing was persisted before the complete set was locked.
    assert not any("INSERT INTO match_events" in sql for sql in statements)


@pytest.mark.asyncio
async def test_advancement_reset_does_not_lock_gf2_again():
    session = RecordingSession()

    def handle(sql, params):
        if "set_config" in sql:
            return Result()
        if "bracket_code = :reset_code" in sql:
            return Result(rows=[{"id": RESET_ID}])
        if sql.startswith("UPDATE matches"):
            return Result(rowcount=1)
        if sql.startswith("INSERT INTO outbox_events"):
            return Result()
        raise StopExecution(sql)

    session.handle = handle
    match = {
        "bracket_code": "GF1",
        "tournament_id": TOURNAMENT_ID,
        "tournament_version_id": VERSION_ID,
        "stage_id": STAGE_ID,
        "home_team_id": TEAM_A,
        "away_team_id": TEAM_B,
    }
    outcome = SimpleNamespace(winner_team_id=TEAM_B)

    await AdvancementService(session).activate_double_elimination_reset(
        context(), match, outcome
    )

    assert session.statements
    assert not any("FOR UPDATE" in sql for sql in session.statements)


# ---------------------------------------------------------------------------
# Standings: stage before the advisory lock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standings_locks_stage_before_the_advisory_lock():
    session = stage_session()

    def handle(sql, params):
        if "SELECT id, tournament_version_id" in sql and "FROM stages" in sql:
            return Result(
                rows=[{"id": STAGE_ID, "tournament_version_id": VERSION_ID}]
            )
        if "SELECT status" in sql and "FROM tournament_versions" in sql:
            return Result(scalar="draft")
        if "pg_advisory_xact_lock" in sql:
            return Result()
        if "SELECT tv.rules_config" in sql:
            raise StopExecution(sql)
        raise StopExecution(sql)

    session.handle = handle

    with pytest.raises(StopExecution):
        await StandingsService(session).recalculate(
            context(), TOURNAMENT_ID, STAGE_ID
        )

    assert "FROM stages" in session.statements[0]
    assert "FOR UPDATE" in session.statements[0]
    assert "FROM tournament_versions" in session.statements[1]
    assert "pg_advisory_xact_lock" in session.statements[2]
    assert session.index("pg_advisory_xact_lock") > session.index("FROM stages")


# ---------------------------------------------------------------------------
# Version-only exceptions: no stage lock, and never version after a stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_stage_locks_the_version_before_inserting():
    session = stage_session(stop_on="INSERT INTO stages")
    payload = CreateStageRequest(
        version_id=VERSION_ID,
        name="Group",
        stage_type="round_robin",
        stage_order=1,
    )

    with pytest.raises(StopExecution):
        await create_stage(TOURNAMENT_ID, payload, context(), session)

    version_index = session.index("FROM tournament_versions")
    stop_index = session.index("INSERT INTO stages")
    assert "FOR UPDATE" in session.statements[version_index]
    assert version_index < stop_index
    assert not any(
        "FROM stages" in sql and "FOR UPDATE" in sql for sql in session.statements
    )


@pytest.mark.asyncio
async def test_publish_locks_only_the_version():
    session = stage_session(stop_on="FROM tournament_versions tv")

    def handle(sql, params):
        if "set_config" in sql:
            return Result()
        if "FROM tournament_versions tv" in sql:
            return Result(
                rows=[
                    {
                        "id": VERSION_ID,
                        "tournament_id": TOURNAMENT_ID,
                        "status": "published",
                        "rules_config": {},
                        "tournament_status": "draft",
                        "published_version_id": None,
                    }
                ]
            )
        if "FROM roles r" in sql:
            return Result(scalar=1)
        raise StopExecution(sql)

    session.handle = handle
    session.stop_on = None

    with pytest.raises(HTTPException) as error:
        await publish_version(VERSION_ID, context(), session)

    assert error.value.status_code == 409
    version_index = session.index("FROM tournament_versions tv")
    assert "FOR UPDATE" in session.statements[version_index]
    assert not any("FROM stages" in sql for sql in session.statements)


# ---------------------------------------------------------------------------
# Official assignment locks the match (T011/H7)
# ---------------------------------------------------------------------------


def _official_session() -> RecordingSession:
    session = stage_session()

    def handle(sql, params):
        if "set_config" in sql:
            return Result()
        if "id = ANY(CAST(:match_ids AS uuid[]))" in sql:
            return Result(rows=[{"id": MATCH_ID}])
        if "FROM roles r" in sql:
            return Result(scalar=1)
        raise StopExecution(sql)

    session.handle = handle
    return session


@pytest.mark.asyncio
async def test_assign_official_locks_the_match_before_writing():
    session = _official_session()
    payload = OfficialAssignmentRequest(
        organization_user_id=MEMBER_ID,
        official_role="main_referee",
    )

    with pytest.raises(StopExecution):
        await assign_match_official(
            MATCH_ID, payload, context(), session
        )

    lock_index = session.index("id = ANY(CAST(:match_ids AS uuid[]))")
    assert "FOR UPDATE" in session.statements[lock_index]
    assert not any(sql.startswith("INSERT INTO match_officials") for sql in session.statements)


@pytest.mark.asyncio
async def test_remove_official_locks_the_match_before_deleting():
    session = _official_session()

    with pytest.raises(StopExecution):
        await remove_match_official(
            MATCH_ID, MEMBER_ID, "main_referee", context(), session
        )

    lock_index = session.index("id = ANY(CAST(:match_ids AS uuid[]))")
    assert "FOR UPDATE" in session.statements[lock_index]


# ---------------------------------------------------------------------------
# GF2 is part of the target set whenever the source is GF1 (T011/H8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gf2_target_is_included_even_when_it_is_not_cancelled():
    session = stage_session()

    def handle(sql, params):
        if "FROM advancement_links" in sql:
            return Result(rows=[])
        if "bracket_code = :reset_code" in sql:
            return Result(rows=[{"id": RESET_ID}])
        raise StopExecution(sql)

    session.handle = handle
    match = {
        "bracket_code": "GF1",
        "tournament_id": TOURNAMENT_ID,
        "tournament_version_id": VERSION_ID,
        "stage_id": STAGE_ID,
    }

    targets = await AdvancementService(session).target_ids(
        context(), MATCH_ID, match
    )

    assert targets == (RESET_ID,)
    gf2_sql = next(sql for sql in session.statements if "bracket_code = :reset_code" in sql)
    assert "status = 'cancelled'" not in gf2_sql
