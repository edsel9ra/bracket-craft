"""Crest in the anonymous public surfaces (T13).

``GET /tournaments/public/{id}`` adds ``teams`` (exactly ``team_id``, ``name``,
``short_code`` and ``crest_url``), ``standings`` adds ``crest_url`` per row and
``matches`` adds ``home_team_crest_url``, ``away_team_crest_url`` and the
``crest_url`` of each published lineup. Every crest comes from the public view
``v_public_tournament_teams`` —never from ``teams``, ``players`` or ``rosters``—
and is signed with ``policy="null"`` after the read transaction closes: a failed
signature leaves ``null`` with 200 and one log entry per response.

The tests use ``httpx.ASGITransport`` with a scripted session and a storage
double; an opt-in test runs the same endpoints against PostgreSQL.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.storage import SignedUrls
from app.main import api
from app.modules.tournaments import router as tournaments_router_module
from db_helpers import TenantContext, set_tenant_context

ORG = UUID("0f000000-0000-4000-8000-000000000001")
TOURNAMENT = UUID("0f000000-0000-4000-8000-000000000010")
STAGE = UUID("0f000000-0000-4000-8000-000000000011")
MATCH = UUID("0f000000-0000-4000-8000-000000000012")
HOME_TEAM = UUID("0f000000-0000-4000-8000-000000000020")
AWAY_TEAM = UUID("0f000000-0000-4000-8000-000000000021")
HOME_PLAYER = UUID("0f000000-0000-4000-8000-000000000030")

DETAIL_URL = f"/api/v1/tournaments/public/{TOURNAMENT}"
STANDINGS_URL = f"/api/v1/tournaments/public/{TOURNAMENT}/standings"
MATCHES_URL = f"/api/v1/tournaments/public/{TOURNAMENT}/matches"

HOME_KEY = (
    f"private/organizations/{ORG}/tournaments/{TOURNAMENT}"
    f"/teams/{HOME_TEAM}/crest/home.webp"
)
AWAY_KEY = (
    f"private/organizations/{ORG}/tournaments/{TOURNAMENT}"
    f"/teams/{AWAY_TEAM}/crest/away.jpg"
)
PHOTO_KEY = (
    f"private/organizations/{ORG}/tournaments/{TOURNAMENT}"
    f"/rosters/{HOME_PLAYER}/photo.jpg"
)


class FakeTransaction:
    def __init__(self, database: "PublicDatabase") -> None:
        self._database = database

    async def __aenter__(self):
        self._database.open_transactions += 1
        return self

    async def __aexit__(self, *_exc_info):
        self._database.open_transactions -= 1
        return False


class FakeResult:
    def __init__(self, rows=()) -> None:
        self.rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class PublicDatabase:
    """Answers the public reads and reports whether a transaction is open."""

    def __init__(
        self,
        *,
        tournament=None,
        stages=(),
        teams=(),
        standings=(),
        matches=(),
        lineups=(),
    ) -> None:
        self.tournament = dict(tournament) if tournament is not None else None
        self.stages = [dict(row) for row in stages]
        self.teams = [dict(row) for row in teams]
        self.standings = [dict(row) for row in standings]
        self.matches = [dict(row) for row in matches]
        self.lineups = [dict(row) for row in lineups]
        self.open_transactions = 0
        self.statements: list[str] = []

    def begin(self):
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.open_transactions > 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split()).replace("public.", "")
        self.statements.append(sql)
        if "FROM v_public_standings" in sql:
            return FakeResult(self.standings)
        if "FROM v_public_matches" in sql:
            return FakeResult(self.matches)
        if "FROM v_public_match_lineups" in sql:
            return FakeResult(self.lineups)
        if "FROM v_public_tournament_teams" in sql:
            return FakeResult(self.teams)
        if "FROM v_public_stages" in sql:
            return FakeResult(self.stages)
        if "FROM v_public_tournaments" in sql:
            return FakeResult([self.tournament] if self.tournament else [])
        return FakeResult()


class PublicStorage:
    def __init__(self, *, fail: bool = False, on_sign=None) -> None:
        self.fail = fail
        self.on_sign = on_sign
        self.calls: list[tuple[str, ...]] = []

    async def signed_urls(self, keys, expires_seconds=None):
        keys = tuple(keys)
        self.calls.append(keys)
        if self.on_sign is not None:
            self.on_sign()
        if self.fail:
            return SignedUrls(urls={}, failed=keys, reason="sign_failed")
        return SignedUrls(
            urls={
                key: f"https://signed.test/{index}.png"
                for index, key in enumerate(keys)
            }
        )


def tournament_row() -> dict:
    return {
        "id": TOURNAMENT,
        "name": "Public Cup",
        "season": "2026",
        "start_date": date(2026, 1, 1),
        "status": "published",
    }


def stage_row() -> dict:
    return {
        "id": STAGE,
        "name": "Group stage",
        "stage_type": "round_robin",
        "stage_order": 1,
    }


def public_team(team_id, name, short_code, *, crest) -> dict:
    return {
        "team_id": team_id,
        "name": name,
        "short_code": short_code,
        "crest_object_key": crest,
    }


def standing_row(*, crest) -> dict:
    return {
        "tournament_id": TOURNAMENT,
        "stage_id": STAGE,
        "stage_name": "Group stage",
        "stage_order": 1,
        "group_id": None,
        "group_name": None,
        "team_id": HOME_TEAM,
        "team_name": "Home FC",
        "short_code": "HOM",
        "played": 1,
        "won": 1,
        "drawn": 0,
        "lost": 0,
        "goals_for": 2,
        "goals_against": 0,
        "goal_difference": 2,
        "points": 3,
        "fair_play_points": 0,
        "rank": 1,
        "calculated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "crest_object_key": crest,
    }


def match_row(*, home_crest, away_crest) -> dict:
    return {
        "id": MATCH,
        "tournament_id": TOURNAMENT,
        "stage_id": STAGE,
        "stage_name": "Group stage",
        "stage_order": 1,
        "group_id": None,
        "group_name": None,
        "bracket_code": None,
        "matchday": 1,
        "match_date": datetime(2026, 1, 3, tzinfo=timezone.utc),
        "home_team_id": HOME_TEAM,
        "home_team_name": "Home FC",
        "home_team_short_code": "HOM",
        "away_team_id": AWAY_TEAM,
        "away_team_name": "Away FC",
        "away_team_short_code": "AWY",
        "home_score_regular": None,
        "away_score_regular": None,
        "home_score": None,
        "away_score": None,
        "home_penalties": None,
        "away_penalties": None,
        "winner_team_id": None,
        "status": "scheduled",
        "resolution_type": None,
        "home_team_crest_object_key": home_crest,
        "away_team_crest_object_key": away_crest,
    }


def lineup_row(*, side, team_id, team_name, player_id, photo) -> dict:
    return {
        "match_id": MATCH,
        "team_id": team_id,
        "team_name": team_name,
        "side": side,
        "formation_code": "4-3-3",
        "player_id": player_id,
        "first_name": "Home",
        "last_name": "Player",
        "dorsal_number": 9,
        "role": "starter",
        "position_slot": "GK",
        "photo_url": photo,
    }


@pytest.fixture
async def client():
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as value:
            yield value
    finally:
        api.dependency_overrides.clear()


async def get(client, database, url: str):
    async def _db():
        yield database

    api.dependency_overrides[get_db] = _db
    return await client.get(url)


def use_storage(monkeypatch, storage):
    monkeypatch.setattr(
        "app.modules.crests.resolver.get_object_storage", lambda: storage
    )


# ---------------------------------------------------------------------------
# Tournament detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_detail_returns_the_team_list_with_signed_crests(
    client, monkeypatch
):
    database = PublicDatabase(
        tournament=tournament_row(),
        stages=[stage_row()],
        teams=[
            public_team(HOME_TEAM, "Home FC", "HOM", crest=HOME_KEY),
            public_team(AWAY_TEAM, "Away FC", "AWY", crest=None),
        ],
    )
    observations: list[bool] = []
    storage = PublicStorage(
        on_sign=lambda: observations.append(database.in_transaction())
    )
    use_storage(monkeypatch, storage)

    response = await get(client, database, DETAIL_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(TOURNAMENT)
    assert body["stages"] == [
        {
            "id": str(STAGE),
            "name": "Group stage",
            "stage_type": "round_robin",
            "stage_order": 1,
        }
    ]
    assert body["teams"] == [
        {
            "team_id": str(HOME_TEAM),
            "name": "Home FC",
            "short_code": "HOM",
            "crest_url": "https://signed.test/0.png",
        },
        {
            "team_id": str(AWAY_TEAM),
            "name": "Away FC",
            "short_code": "AWY",
            "crest_url": None,
        },
    ]
    for team in body["teams"]:
        assert set(team) == {"team_id", "name", "short_code", "crest_url"}
    assert "logo_url" not in response.text
    assert "crest_object_key" not in response.text
    assert "private/" not in response.text
    assert storage.calls == [(HOME_KEY,)]
    assert observations == [False]


@pytest.mark.asyncio
async def test_public_detail_without_teams_returns_an_empty_list(client, monkeypatch):
    database = PublicDatabase(tournament=tournament_row(), stages=[stage_row()])
    storage = PublicStorage()
    use_storage(monkeypatch, storage)

    response = await get(client, database, DETAIL_URL)

    assert response.status_code == 200
    assert response.json()["teams"] == []
    assert response.json()["stages"][0]["name"] == "Group stage"
    assert storage.calls == []


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_standings_add_crest_url_per_row(client, monkeypatch):
    database = PublicDatabase(
        tournament=tournament_row(), standings=[standing_row(crest=HOME_KEY)]
    )
    storage = PublicStorage()
    use_storage(monkeypatch, storage)

    response = await get(client, database, STANDINGS_URL)

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["crest_url"] == "https://signed.test/0.png"
    assert rows[0]["team_name"] == "Home FC"
    assert "logo_url" not in response.text
    assert "crest_object_key" not in response.text
    assert storage.calls == [(HOME_KEY,)]


# ---------------------------------------------------------------------------
# Matches and published lineups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_matches_sign_photos_and_crests_in_one_batch(
    client, monkeypatch
):
    database = PublicDatabase(
        tournament=tournament_row(),
        matches=[match_row(home_crest=HOME_KEY, away_crest=AWAY_KEY)],
        lineups=[
            lineup_row(
                side="home",
                team_id=HOME_TEAM,
                team_name="Home FC",
                player_id=HOME_PLAYER,
                photo=PHOTO_KEY,
            )
        ],
    )
    observations: list[bool] = []
    storage = PublicStorage(
        on_sign=lambda: observations.append(database.in_transaction())
    )
    use_storage(monkeypatch, storage)

    response = await get(client, database, MATCHES_URL)

    assert response.status_code == 200
    match = response.json()[0]
    assert match["home_team_crest_url"] == "https://signed.test/0.png"
    assert match["away_team_crest_url"] == "https://signed.test/1.png"
    assert "home_team_crest_object_key" not in match
    assert "away_team_crest_object_key" not in match
    assert match["lineup"]["home"]["crest_url"] == "https://signed.test/0.png"
    assert match["lineup"]["away"] is None
    # The photo is signed in the same single batch as both crests.
    assert match["lineup"]["home"]["starters"][0]["photo_url"] == (
        "https://signed.test/2.png"
    )
    assert storage.calls == [(HOME_KEY, AWAY_KEY, PHOTO_KEY)]
    assert observations == [False]
    assert "logo_url" not in response.text
    assert "crest_object_key" not in response.text
    assert "private/" not in response.text


# ---------------------------------------------------------------------------
# Degradation: one log entry and null fields with 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_surfaces_degrade_to_null_with_one_log_entry(
    client, monkeypatch, caplog
):
    caplog.set_level("WARNING", logger="app.modules.crests.resolver")
    storage = PublicStorage(fail=True)
    use_storage(monkeypatch, storage)

    detail_database = PublicDatabase(
        tournament=tournament_row(),
        teams=[public_team(HOME_TEAM, "Home FC", "HOM", crest=HOME_KEY)],
    )
    detail = await get(client, detail_database, DETAIL_URL)
    standings_database = PublicDatabase(
        tournament=tournament_row(), standings=[standing_row(crest=HOME_KEY)]
    )
    standings = await get(client, standings_database, STANDINGS_URL)
    matches_database = PublicDatabase(
        tournament=tournament_row(),
        matches=[match_row(home_crest=HOME_KEY, away_crest=AWAY_KEY)],
        lineups=[
            lineup_row(
                side="home",
                team_id=HOME_TEAM,
                team_name="Home FC",
                player_id=HOME_PLAYER,
                photo=PHOTO_KEY,
            )
        ],
    )
    matches = await get(client, matches_database, MATCHES_URL)

    assert detail.status_code == 200
    assert detail.json()["teams"][0]["crest_url"] is None
    assert standings.status_code == 200
    assert standings.json()[0]["crest_url"] is None
    assert matches.status_code == 200
    match = matches.json()[0]
    assert match["home_team_crest_url"] is None
    assert match["away_team_crest_url"] is None
    assert match["lineup"]["home"]["crest_url"] is None
    assert match["lineup"]["home"]["starters"][0]["photo_url"] is None

    records = [
        record
        for record in caplog.records
        if record.name == "app.modules.crests.resolver"
    ]
    assert len(records) == 3  # one per response, never one per key


# ---------------------------------------------------------------------------
# Source contract: crest data comes only from the public view
# ---------------------------------------------------------------------------


def test_public_crest_queries_only_use_the_public_team_view():
    for endpoint in (
        tournaments_router_module.public_tournament,
        tournaments_router_module.public_standings,
        tournaments_router_module.public_matches,
    ):
        source = inspect.getsource(endpoint)
        assert "v_public_tournament_teams" in source, endpoint.__name__
        for forbidden in (
            "FROM teams",
            "JOIN teams",
            "FROM players",
            "JOIN players",
            "FROM rosters",
            "JOIN rosters",
            "logo_url",
            "SECURITY DEFINER",
        ):
            assert forbidden not in source, f"{endpoint.__name__}: {forbidden}"


# ---------------------------------------------------------------------------
# Real PostgreSQL (opt-in): visibility through the public view
# ---------------------------------------------------------------------------


class SavepointAdapter:
    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


async def seed_public_tournament(session, tenant) -> tuple[UUID, UUID, UUID]:
    await set_tenant_context(session, tenant)
    tournament_id = uuid4()
    version_id = uuid4()
    stage_id = uuid4()
    with_crest = uuid4()
    without_crest = uuid4()
    await session.execute(
        text("""
            INSERT INTO tournaments
                (id, organization_id, name, season, start_date, status,
                 current_draft_config)
            VALUES (:id, :organization_id, :name, '2026',
                    CAST('2026-01-01' AS DATE), 'draft', '{}'::jsonb)
        """),
        {
            "id": str(tournament_id),
            "organization_id": str(tenant.organization_id),
            "name": f"Public Crest {tournament_id.hex[:8]}",
        },
    )
    await session.execute(
        text("""
            INSERT INTO tournament_versions
                (id, organization_id, tournament_id, version_number,
                 rules_config, phase_config, status, created_by_member_id)
            VALUES (:id, :organization_id, :tournament_id, 1, '{}'::jsonb,
                    '{}'::jsonb, 'draft', :member_id)
        """),
        {
            "id": str(version_id),
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "member_id": str(tenant.member_id),
        },
    )
    await session.execute(
        text("""
            INSERT INTO stages
                (id, organization_id, tournament_id, tournament_version_id,
                 name, stage_type, stage_order)
            VALUES (:id, :organization_id, :tournament_id, :version_id,
                    'Group stage', 'round_robin', 1)
        """),
        {
            "id": str(stage_id),
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
        },
    )
    for team_id, name, crest in (
        (with_crest, "With Crest", HOME_KEY),
        (without_crest, "Without Crest", None),
    ):
        await session.execute(
            text("""
                INSERT INTO teams
                    (id, organization_id, name, short_code, crest_object_key)
                VALUES (:id, :organization_id, :name, :short_code, :crest)
            """),
            {
                "id": str(team_id),
                "organization_id": str(tenant.organization_id),
                "name": name,
                "short_code": f"P{team_id.hex[:4].upper()}",
                "crest": crest,
            },
        )
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
            INSERT INTO standings
                (organization_id, tournament_id, stage_id, group_id, team_id,
                 played, won, drawn, lost, goals_for, goals_against,
                 goal_difference, points, fair_play_points, rank)
            VALUES (:organization_id, :tournament_id, :stage_id, NULL, :team_id,
                    1, 1, 0, 0, 2, 0, 2, 3, 0, 1)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "stage_id": str(stage_id),
            "team_id": str(with_crest),
        },
    )
    await session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {"id": str(version_id)},
    )
    await session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :id
        """),
        {"id": str(tournament_id), "version_id": str(version_id)},
    )
    return tournament_id, with_crest, without_crest


@pytest.mark.asyncio
async def test_public_detail_and_standings_read_the_view_in_postgres(
    db_session, tenant_factory, monkeypatch
):
    tenant: TenantContext = await tenant_factory("Public Crest Owner")
    tournament_id, with_crest, without_crest = await seed_public_tournament(
        db_session, tenant
    )
    storage = PublicStorage()
    use_storage(monkeypatch, storage)

    async def _db():
        yield SavepointAdapter(db_session)

    api.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            detail = await client.get(f"/api/v1/tournaments/public/{tournament_id}")
            standings = await client.get(
                f"/api/v1/tournaments/public/{tournament_id}/standings"
            )
    finally:
        api.dependency_overrides.clear()

    assert detail.status_code == 200
    teams = {row["team_id"]: row for row in detail.json()["teams"]}
    assert set(teams) == {str(with_crest), str(without_crest)}
    assert teams[str(with_crest)]["crest_url"] == "https://signed.test/0.png"
    assert teams[str(without_crest)]["crest_url"] is None
    for row in detail.json()["teams"]:
        assert set(row) == {"team_id", "name", "short_code", "crest_url"}

    assert standings.status_code == 200
    assert standings.json()[0]["team_id"] == str(with_crest)
    assert standings.json()[0]["crest_url"] == "https://signed.test/0.png"
    assert "crest_object_key" not in detail.text + standings.text
