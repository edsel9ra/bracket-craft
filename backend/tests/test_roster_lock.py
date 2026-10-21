"""Roster lock on roster registrations (RF-021, RF-022, RF-024-RF-028).

The effective ``roster_lock_matchday`` comes from the **published** version's
``rules_config`` (the draft never prevails). The lock is active when the first
stage of that version (by ``stage_order``, then ``id``) has at least one match
for the reference matchday and every non-cancelled one is confirmed
(``status IN ('finished','administrative_resolution')`` and
``result_confirmed = TRUE``).

The bulk import checks the lock twice: before uploading photos and again inside
the write transaction. When it turns active between both checks the request
answers 409, writes no rows and compensates the uploaded objects.

Most tests use a recording session double. The opt-in test at the end exercises
the real aggregate SQL against PostgreSQL (``RUN_DATABASE_TESTS=1``).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.tournaments import router as tournaments_router
from app.modules.tournaments.router import _active_roster_lock_matchday
from app.modules.tournaments.roster_import import ImportedRosterRow, PhotoFile
from app.modules.tournaments.schemas import CreateRosterPlayerRequest

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
TOURNAMENT_ID = uuid4()
VERSION_ID = uuid4()
TEAM_ID = uuid4()
ROSTER_ID = uuid4()
PLAYER_ID = uuid4()

MATCHDAY = 2
LOCK_DETAIL = (
    "La plantilla está cerrada desde la jornada 2: "
    "no se pueden inscribir jugadores nuevos"
)
PHOTO_FILE = PhotoFile(content=b"jpeg-bytes", content_type="image/jpeg", extension=".jpg")


def config_with_lock(matchday: int | None) -> dict:
    config = json.loads(json.dumps(DEFAULT_RULES_CONFIG))
    config["roster_lock_matchday"] = matchday
    return config


# ---------------------------------------------------------------------------
# Session double for the lock queries
# ---------------------------------------------------------------------------


class FakeRows:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0]

    def scalar_one_or_none(self):
        row = self.one_or_none()
        return None if row is None else next(iter(row.values()))


class LockSession:
    """Answers the published-version read and the aggregate count query."""

    def __init__(self, *, published=None, counts=()):
        self.published = published
        self.counts = list(counts)
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append((sql, dict(params or {})))
        if "FROM tournament_versions" in sql:
            if self.published is None:
                return FakeRows([])
            version_id, config = self.published
            return FakeRows([{"version_id": version_id, "rules_config": config}])
        if "FROM matches m" in sql:
            total, confirmed = self.counts.pop(0)
            return FakeRows([{"total": total, "confirmed": confirmed}])
        raise AssertionError(f"consulta inesperada: {sql}")

    def statements_matching(self, fragment: str) -> list[tuple[str, dict]]:
        return [entry for entry in self.statements if fragment in entry[0]]


def published(lock: int | None = None, *, config: dict | None = None):
    return (VERSION_ID, config if config is not None else config_with_lock(lock))


# ---------------------------------------------------------------------------
# Effective source: published wins, draft never applies
# ---------------------------------------------------------------------------


async def test_the_published_version_blocks_when_every_match_is_confirmed():
    session = LockSession(published=published(4), counts=[(2, 2)])

    matchday = await _active_roster_lock_matchday(
        session, ORGANIZATION_ID, TOURNAMENT_ID
    )

    assert matchday == 4
    (published_sql, published_params) = session.statements_matching(
        "FROM tournament_versions"
    )[0]
    assert "status = 'published'" in published_sql
    assert published_params["tournament_id"] == str(TOURNAMENT_ID)
    assert published_params["organization_id"] == str(ORGANIZATION_ID)
    (aggregate_sql, aggregate_params) = session.statements_matching("FROM matches m")[0]
    assert aggregate_params == {
        "organization_id": str(ORGANIZATION_ID),
        "tournament_id": str(TOURNAMENT_ID),
        "version_id": str(VERSION_ID),
        "matchday": 4,
    }
    assert "status <> 'cancelled'" in aggregate_sql
    assert "status IN ('finished', 'administrative_resolution')" in aggregate_sql
    assert "result_confirmed = TRUE" in aggregate_sql
    assert "ORDER BY s.stage_order, s.id" in aggregate_sql


async def test_without_a_published_version_the_draft_never_blocks():
    session = LockSession(published=None)

    assert (
        await _active_roster_lock_matchday(session, ORGANIZATION_ID, TOURNAMENT_ID)
        is None
    )
    assert session.statements_matching("FROM matches m") == []


async def test_a_null_lock_does_not_block():
    session = LockSession(published=published(None))

    assert (
        await _active_roster_lock_matchday(session, ORGANIZATION_ID, TOURNAMENT_ID)
        is None
    )
    assert session.statements_matching("FROM matches m") == []


async def test_a_published_lock_prevails_over_the_draft_value():
    # Only the published row is read; a different draft value is never consulted.
    session = LockSession(published=published(3), counts=[(1, 1)])

    assert await _active_roster_lock_matchday(
        session, ORGANIZATION_ID, TOURNAMENT_ID
    ) == 3
    assert session.statements_matching("FROM matches m")[0][1]["matchday"] == 3


async def test_the_deprecated_transfers_block_is_consumed():
    config = {
        **config_with_lock(None),
        "transfers": {"roster_lock_matchday": 2},
    }
    session = LockSession(published=published(config=config), counts=[(2, 2)])

    assert await _active_roster_lock_matchday(
        session, ORGANIZATION_ID, TOURNAMENT_ID
    ) == 2


async def test_a_partial_confirmation_does_not_block():
    session = LockSession(published=published(2), counts=[(3, 2)])

    assert (
        await _active_roster_lock_matchday(session, ORGANIZATION_ID, TOURNAMENT_ID)
        is None
    )


async def test_no_matches_for_the_reference_matchday_does_not_block():
    session = LockSession(published=published(2), counts=[(0, 0)])

    assert (
        await _active_roster_lock_matchday(session, ORGANIZATION_ID, TOURNAMENT_ID)
        is None
    )


async def test_an_entirely_cancelled_matchday_does_not_block():
    # Cancelled rows are excluded by the query, so they never reach the count.
    session = LockSession(published=published(2), counts=[(0, 0)])

    assert (
        await _active_roster_lock_matchday(session, ORGANIZATION_ID, TOURNAMENT_ID)
        is None
    )
    assert "status <> 'cancelled'" in session.statements_matching("FROM matches m")[0][0]


# ---------------------------------------------------------------------------
# Route integration: checks happen before any write or upload
# ---------------------------------------------------------------------------


class FakeTransaction:
    def __init__(self, session: "RosterSession"):
        self._session = session

    async def __aenter__(self):
        self._session.active = True
        return self

    async def __aexit__(self, exc_type, exc_info, traceback):
        self._session.active = False
        if exc_type is None:
            self._session.commits += 1
        else:
            self._session.rollbacks += 1
        return False


class RosterSession(LockSession):
    """Lock queries plus the tournament/team reads of the roster routes."""

    def __init__(self, *, published=None, counts=(), team_registered: bool = True):
        super().__init__(published=published, counts=counts)
        self.team_registered = team_registered
        self.active = False
        self.begins = 0
        self.commits = 0
        self.rollbacks = 0

    def begin(self):
        self.begins += 1
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.active

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        if "set_config" in sql:
            self.statements.append((sql, dict(params or {})))
            return FakeRows([])
        if "FROM tournaments" in sql:
            self.statements.append((sql, dict(params or {})))
            return FakeRows([{"exists": 1}])
        if "FROM tournament_teams" in sql:
            self.statements.append((sql, dict(params or {})))
            return FakeRows([{"exists": 1}] if self.team_registered else [])
        return await super().execute(statement, params)


class RosterStorage:
    """Storage double: records uploads and compensations."""

    def __init__(self, *, session: RosterSession):
        self.session = session
        self.puts: list[str] = []
        self.deleted: list[str] = []
        self.put_transaction_states: list[bool] = []

    async def put_bytes(self, key, content, content_type):
        self.puts.append(key)
        self.put_transaction_states.append(self.session.in_transaction())
        return key

    async def delete_key(self, key):
        self.deleted.append(key)

    async def signed_urls(self, keys, expires_seconds=None):  # pragma: no cover
        raise AssertionError("no debe firmarse una respuesta bloqueada")


def context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


@asynccontextmanager
async def client_for(session: RosterSession):
    async def database():
        yield session

    async def auth():
        return context()

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = auth
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
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


def install_storage(monkeypatch, storage: RosterStorage) -> None:
    monkeypatch.setattr(tournaments_router, "get_object_storage", lambda: storage)


def player_payload() -> dict:
    return {
        "team_id": str(TEAM_ID),
        "first_name": "Ana",
        "last_name": "Pérez",
        "document_type": "internal",
        "national_id": "1029384756",
        "issuing_country": "COL",
        "birth_date": "2000-01-01",
        "dorsal_number": 9,
        "photo_consent": True,
    }


def imported_rows() -> list[ImportedRosterRow]:
    return [
        ImportedRosterRow(
            2,
            CreateRosterPlayerRequest(
                team_id=TEAM_ID,
                first_name="Ana",
                last_name="Pérez",
                national_id="1029384756",
                birth_date=date(2000, 1, 1),
                dorsal_number=9,
                photo_consent=True,
            ),
            "ana.jpg",
        ),
        ImportedRosterRow(
            3,
            CreateRosterPlayerRequest(
                team_id=TEAM_ID,
                first_name="Luis",
                last_name="Gómez",
                national_id="99887766",
                birth_date=date(1999, 2, 2),
                dorsal_number=7,
                photo_consent=True,
            ),
            "luis.jpg",
        ),
    ]


def install_import(monkeypatch) -> None:
    monkeypatch.setattr(
        tournaments_router, "parse_roster_csv", lambda raw, team_id: imported_rows()
    )
    monkeypatch.setattr(
        tournaments_router,
        "extract_zip_photos",
        lambda raw: {"ana.jpg": PHOTO_FILE, "luis.jpg": PHOTO_FILE},
    )


def assert_no_writes(session: RosterSession) -> None:
    assert not any(
        sql.startswith(("INSERT INTO", "UPDATE ", "DELETE FROM"))
        for sql, _ in session.statements
    )


async def test_individual_registration_is_blocked_without_creating_rows(
    monkeypatch, allow_management
):
    session = RosterSession(published=published(MATCHDAY), counts=[(2, 2)])
    calls: list[object] = []

    async def fake_create(*args, **kwargs):  # pragma: no cover - must not run
        calls.append(args)
        raise AssertionError("no debe crearse un jugador bloqueado")

    monkeypatch.setattr(tournaments_router, "_create_roster_player_record", fake_create)

    async with client_for(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters", json=player_payload()
        )

    assert response.status_code == 409
    assert response.json() == {"detail": LOCK_DETAIL}
    assert calls == []
    assert_no_writes(session)
    assert session.rollbacks == 1


async def test_individual_registration_is_allowed_without_a_published_lock(
    monkeypatch, allow_management
):
    # Draft-only configuration: no published version, so the lock cannot apply.
    session = RosterSession(published=None)
    install_storage(monkeypatch, RosterStorage(session=session))
    monkeypatch.setattr(
        tournaments_router,
        "_create_roster_player_record",
        _successful_create,
    )
    monkeypatch.setattr(
        tournaments_router,
        "_load_roster_player_row",
        _load_row,
    )

    async with client_for(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters", json=player_payload()
        )

    assert response.status_code == 201
    assert session.statements_matching("FROM matches m") == []


async def _successful_create(db, context, tournament_id, payload, settings, roster_id=None):
    return ROSTER_ID, PLAYER_ID


async def _load_row(db, organization_id, roster_id):
    return {
        "roster_id": ROSTER_ID,
        "player_id": PLAYER_ID,
        "team_id": TEAM_ID,
        "first_name": "Ana",
        "last_name": "Pérez",
        "dorsal_number": 9,
        "photo_object_key": None,
        "photo_consent": True,
        "is_active": True,
    }


async def test_import_is_blocked_before_uploading_photos(monkeypatch, allow_management):
    session = RosterSession(published=published(MATCHDAY), counts=[(2, 2)])
    storage = RosterStorage(session=session)
    install_storage(monkeypatch, storage)
    install_import(monkeypatch)

    async with client_for(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
            data={"team_id": str(TEAM_ID)},
            files={
                "csv_file": ("roster.csv", b"", "text/csv"),
                "photos_zip": ("photos.zip", b"", "application/zip"),
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": LOCK_DETAIL}
    assert storage.puts == []
    assert_no_writes(session)
    assert session.begins == 1


async def test_import_rechecks_the_lock_inside_the_write_transaction(
    monkeypatch, allow_management
):
    # First check sees one pending match; the second one sees the matchday closed.
    session = RosterSession(published=published(MATCHDAY), counts=[(2, 1), (2, 2)])
    storage = RosterStorage(session=session)
    install_storage(monkeypatch, storage)
    install_import(monkeypatch)
    created: list[object] = []

    async def fake_create(*args, **kwargs):  # pragma: no cover - must not run
        created.append(args)
        raise AssertionError("no debe crearse un jugador bloqueado")

    monkeypatch.setattr(tournaments_router, "_create_roster_player_record", fake_create)

    async with client_for(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
            data={"team_id": str(TEAM_ID)},
            files={
                "csv_file": ("roster.csv", b"", "text/csv"),
                "photos_zip": ("photos.zip", b"", "application/zip"),
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": LOCK_DETAIL}
    assert len(session.statements_matching("FROM matches m")) == 2
    assert storage.puts and storage.deleted == storage.puts
    assert all(state is False for state in storage.put_transaction_states)
    assert created == []
    assert_no_writes(session)
    assert session.begins == 2
    assert session.commits == 1
    assert session.rollbacks == 1


# ---------------------------------------------------------------------------
# Opt-in: the real aggregate query against PostgreSQL
# ---------------------------------------------------------------------------


async def _create_tournament(session, tenant) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status)
                VALUES
                    (:organization_id, :name, '2026', '2026-01-01', 'draft')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"Roster lock {uuid4().hex[:8]}",
            },
        )
    ).scalar_one()


async def _create_version(session, tenant, tournament_id: UUID, config: dict) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config,
                     phase_config, status, created_by_member_id)
                VALUES
                    (:organization_id, :tournament_id, 1, CAST(:config AS jsonb),
                     '{}'::jsonb, 'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
                "config": json.dumps(config),
            },
        )
    ).scalar_one()


async def _create_stage(
    session, tenant, tournament_id: UUID, version_id: UUID, *, order: int, stage_id=None
) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO stages
                    (id, organization_id, tournament_id, tournament_version_id, name,
                     stage_type, stage_order)
                VALUES
                    (:id, :organization_id, :tournament_id, :version_id, :name,
                     'round_robin', :stage_order)
                RETURNING id
            """),
            {
                "id": str(stage_id or uuid4()),
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "name": f"Stage {order}-{uuid4().hex[:4]}",
                "stage_order": order,
            },
        )
    ).scalar_one()


async def _create_teams(session, tenant, tournament_id: UUID, version_id: UUID, stage_id: UUID) -> tuple[UUID, UUID]:
    team_ids = []
    for label in ("home", "away"):
        team_id = (
            await session.execute(
                text("""
                    INSERT INTO teams (organization_id, name, short_code)
                    VALUES (:organization_id, :name, :short_code)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "name": f"Lock {label} {uuid4().hex[:6]}",
                    "short_code": f"L{uuid4().hex[:5].upper()}",
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
                    (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
                VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :team_id)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
        team_ids.append(team_id)
    return team_ids[0], team_ids[1]


async def _create_match(
    session,
    tenant,
    *,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    matchday: int | None,
    status: str,
    teams: tuple[UUID, UUID] | None = None,
) -> UUID:
    terminal = status in ("finished", "administrative_resolution")
    resolution_type = None
    resolution_reason = None
    scores = None
    winner_team_id = None
    if terminal:
        resolution_type = "regular" if status == "finished" else "administrative"
        scores = (0, 0, 0, 0)
        if resolution_type == "administrative":
            resolution_reason = "Resolución administrativa de prueba"
            winner_team_id = teams[0]
    return (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, matchday, status, resolution_type,
                     resolution_reason, result_confirmed, home_score_regular,
                     away_score_regular, home_score, away_score, winner_team_id)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, :matchday, :status, :resolution_type,
                     :resolution_reason, :confirmed, :home_regular, :away_regular,
                     :home_score, :away_score, :winner_team_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(teams[0]) if teams else None,
                "away_team_id": str(teams[1]) if teams else None,
                "matchday": matchday,
                "status": status,
                "resolution_type": resolution_type,
                "resolution_reason": resolution_reason,
                "confirmed": terminal,
                "home_regular": scores[0] if scores else None,
                "away_regular": scores[1] if scores else None,
                "home_score": scores[2] if scores else None,
                "away_score": scores[3] if scores else None,
                "winner_team_id": str(winner_team_id) if winner_team_id else None,
            },
        )
    ).scalar_one()


async def _publish(session, version_id: UUID) -> None:
    await session.execute(
        text("UPDATE tournament_versions SET status = 'published' WHERE id = :version_id"),
        {"version_id": str(version_id)},
    )


async def test_postgres_uses_the_first_stage_and_ignores_cancelled_matches(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Roster Lock")
    tournament_id = await _create_tournament(db_session, tenant)
    version_id = await _create_version(
        db_session, tenant, tournament_id, config_with_lock(MATCHDAY)
    )
    first_stage = await _create_stage(
        db_session, tenant, tournament_id, version_id, order=1
    )
    second_stage = await _create_stage(
        db_session, tenant, tournament_id, version_id, order=2
    )
    teams = await _create_teams(db_session, tenant, tournament_id, version_id, first_stage)

    await _create_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=first_stage,
        matchday=MATCHDAY,
        status="finished",
    )
    await _create_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=first_stage,
        matchday=MATCHDAY,
        status="administrative_resolution",
        teams=teams,
    )
    await _create_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=first_stage,
        matchday=MATCHDAY,
        status="cancelled",
    )
    await _create_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=first_stage,
        matchday=MATCHDAY + 1,
        status="scheduled",
    )
    # A later stage cannot activate the lock: the reference is the first stage.
    await _create_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=second_stage,
        matchday=MATCHDAY,
        status="scheduled",
    )
    await _publish(db_session, version_id)

    assert (
        await _active_roster_lock_matchday(
            db_session, tenant.organization_id, tournament_id
        )
        == MATCHDAY
    )


async def test_postgres_does_not_block_with_a_pending_match_or_a_draft_only_lock(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Roster Lock")

    # Published lock, but the reference matchday still has a scheduled match.
    pending_tournament = await _create_tournament(db_session, tenant)
    pending_version = await _create_version(
        db_session, tenant, pending_tournament, config_with_lock(MATCHDAY)
    )
    pending_stage = await _create_stage(
        db_session, tenant, pending_tournament, pending_version, order=1
    )
    await _create_match(
        db_session,
        tenant,
        tournament_id=pending_tournament,
        version_id=pending_version,
        stage_id=pending_stage,
        matchday=MATCHDAY,
        status="finished",
    )
    await _create_match(
        db_session,
        tenant,
        tournament_id=pending_tournament,
        version_id=pending_version,
        stage_id=pending_stage,
        matchday=MATCHDAY,
        status="scheduled",
    )
    await _publish(db_session, pending_version)

    assert (
        await _active_roster_lock_matchday(
            db_session, tenant.organization_id, pending_tournament
        )
        is None
    )

    # Only a draft version declares the lock: it never applies.
    draft_tournament = await _create_tournament(db_session, tenant)
    draft_version = await _create_version(
        db_session, tenant, draft_tournament, config_with_lock(MATCHDAY)
    )
    draft_stage = await _create_stage(
        db_session, tenant, draft_tournament, draft_version, order=1
    )
    await _create_match(
        db_session,
        tenant,
        tournament_id=draft_tournament,
        version_id=draft_version,
        stage_id=draft_stage,
        matchday=MATCHDAY,
        status="finished",
    )

    assert (
        await _active_roster_lock_matchday(
            db_session, tenant.organization_id, draft_tournament
        )
        is None
    )
