"""Crest in the Workspace surfaces: team listing and match operation (T12).

``GET /tournaments/{id}/teams`` adds ``crest_url`` to every row and
``GET /matches/{id}/operation`` adds ``match.home_team_crest_url`` and
``match.away_team_crest_url``. Both read inside a transaction, close it and sign
the whole answer with **one** batch call (N-2); the internal object keys are
removed from the payload. A signing failure is the Workspace 503
``CREST_STORAGE_UNAVAILABLE`` with the additive ``code``.

The tests use ``httpx.ASGITransport`` with a scripted session (which reports
whether a transaction is open during signing) and a storage double: no database
is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.storage import SignedUrls
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.crests.errors import CREST_STORAGE_UNAVAILABLE

ORG = UUID("0e000000-0000-4000-8000-000000000001")
USER = UUID("0e000000-0000-4000-8000-000000000002")
MEMBER = UUID("0e000000-0000-4000-8000-000000000003")
TOURNAMENT = UUID("0e000000-0000-4000-8000-000000000010")
MATCH = UUID("0e000000-0000-4000-8000-000000000030")
VERSION = UUID("0e000000-0000-4000-8000-000000000031")
STAGE = UUID("0e000000-0000-4000-8000-000000000032")
HOME_TEAM = UUID("0e000000-0000-4000-8000-000000000040")
AWAY_TEAM = UUID("0e000000-0000-4000-8000-000000000041")
OTHER_TEAM = UUID("0e000000-0000-4000-8000-000000000042")

CONTEXT = AuthContext(
    user_id=USER,
    organization_id=ORG,
    organization_user_id=MEMBER,
)
TEAMS_URL = f"/api/v1/tournaments/{TOURNAMENT}/teams"
OPERATION_URL = f"/api/v1/matches/{MATCH}/operation"

HOME_KEY = (
    f"private/organizations/{ORG}/tournaments/{TOURNAMENT}"
    f"/teams/{HOME_TEAM}/crest/home.webp"
)
AWAY_KEY = (
    f"private/organizations/{ORG}/tournaments/{TOURNAMENT}"
    f"/teams/{AWAY_TEAM}/crest/away.jpg"
)
LEGACY_LOGO = "https://crest.example.test/legacy.png"
HOME_LOGO = "https://legacy.test/home.png"
AWAY_LOGO = "https://legacy.test/away.png"


class FakeTransaction:
    def __init__(self, database: "SurfaceDatabase") -> None:
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


class SurfaceDatabase:
    """Answers the two reads and reports whether a transaction is open."""

    def __init__(self, *, team_rows=(), match=None) -> None:
        self.team_rows = [dict(row) for row in team_rows]
        self.match = dict(match) if match is not None else None
        self.open_transactions = 0

    def begin(self):
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.open_transactions > 0

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split()).replace("public.", "")
        if "set_config" in sql:
            return FakeResult()
        if "FROM tournament_teams" in sql:
            return FakeResult(self.team_rows)
        if "FROM tournaments" in sql:
            return FakeResult([1])
        if "FROM matches m" in sql:
            return FakeResult([self.match] if self.match else [])
        return FakeResult()


class SurfaceStorage:
    """One batch of signatures; ``fail`` makes every key fail."""

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


def team_row(team_id, *, crest, logo=None) -> dict:
    return {
        "team_id": team_id,
        "name": f"Team {str(team_id)[:4]}",
        "short_code": str(team_id)[:3].upper(),
        "logo_url": logo,
        "crest_object_key": crest,
        "status": "registered",
        "registered_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "stage_ids": [],
    }


def match_row(*, home_key, away_key) -> dict:
    return {
        "id": MATCH,
        "tournament_id": TOURNAMENT,
        "tournament_version_id": VERSION,
        "stage_id": STAGE,
        "group_id": None,
        "matchday": 1,
        "match_date": None,
        "status": "scheduled",
        "result_confirmed": False,
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
        "resolution_type": "regular",
        "resolution_reason": None,
        "version_status": "published",
        "rules_config": {},
        "tournament_name": "Crest Cup",
        "stage_name": "Group stage",
        "group_name": None,
        "home_team_crest_object_key": home_key,
        "away_team_crest_object_key": away_key,
        "home_team_logo_url": HOME_LOGO,
        "away_team_logo_url": AWAY_LOGO,
    }


@pytest.fixture
async def client():
    api.dependency_overrides[get_auth_context] = lambda: CONTEXT
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
# Team listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teams_listing_signs_crest_url_after_closing_the_transaction(
    client, monkeypatch
):
    database = SurfaceDatabase(
        team_rows=[
            team_row(HOME_TEAM, crest=HOME_KEY),
            team_row(OTHER_TEAM, crest=None, logo=LEGACY_LOGO),
        ]
    )
    observations: list[bool] = []
    storage = SurfaceStorage(
        on_sign=lambda: observations.append(database.in_transaction())
    )
    use_storage(monkeypatch, storage)

    response = await get(client, database, TEAMS_URL)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2

    by_team = {row["team_id"]: row for row in payload}
    with_crest = by_team[str(HOME_TEAM)]
    without_crest = by_team[str(OTHER_TEAM)]
    assert with_crest["crest_url"] == "https://signed.test/0.png"
    assert with_crest["logo_url"] is None
    assert without_crest["crest_url"] is None
    assert without_crest["logo_url"] == LEGACY_LOGO

    # The contract keeps every previous field and never exposes the key.
    assert set(with_crest) == {
        "team_id",
        "name",
        "short_code",
        "logo_url",
        "crest_url",
        "status",
        "registered_at",
        "stage_ids",
    }
    assert "crest_object_key" not in response.text
    assert "private/" not in response.text
    # One batch for the whole answer, with only the existing key.
    assert storage.calls == [(HOME_KEY,)]
    assert observations == [False]


@pytest.mark.asyncio
async def test_teams_listing_without_any_crest_does_not_call_the_storage(
    client, monkeypatch
):
    database = SurfaceDatabase(
        team_rows=[team_row(HOME_TEAM, crest=None, logo=LEGACY_LOGO)]
    )
    storage = SurfaceStorage()
    use_storage(monkeypatch, storage)

    response = await get(client, database, TEAMS_URL)

    assert response.status_code == 200
    assert response.json()[0]["crest_url"] is None
    assert response.json()[0]["logo_url"] == LEGACY_LOGO
    assert storage.calls == []


@pytest.mark.asyncio
async def test_teams_listing_signature_failure_answers_503(client, monkeypatch):
    database = SurfaceDatabase(team_rows=[team_row(HOME_TEAM, crest=HOME_KEY)])
    storage = SurfaceStorage(fail=True)
    use_storage(monkeypatch, storage)

    response = await get(client, database, TEAMS_URL)

    assert response.status_code == 503
    assert response.json()["code"] == CREST_STORAGE_UNAVAILABLE
    assert isinstance(response.json()["detail"], str)
    assert storage.calls == [(HOME_KEY,)]


# ---------------------------------------------------------------------------
# Match operation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_operation_signs_both_crests_in_one_batch_after_commit(
    client, monkeypatch
):
    database = SurfaceDatabase(
        match=match_row(home_key=HOME_KEY, away_key=AWAY_KEY)
    )
    observations: list[bool] = []
    storage = SurfaceStorage(
        on_sign=lambda: observations.append(database.in_transaction())
    )
    use_storage(monkeypatch, storage)

    response = await get(client, database, OPERATION_URL)

    assert response.status_code == 200
    match = response.json()["match"]
    assert match["home_team_crest_url"] == "https://signed.test/0.png"
    assert match["away_team_crest_url"] == "https://signed.test/1.png"
    assert "home_team_crest_object_key" not in match
    assert "away_team_crest_object_key" not in match
    assert "home_team_crest_object_key" not in response.text
    assert "private/" not in response.text
    # RF-4 in the Workspace: the legacy external URL travels as the fallback.
    assert match["home_team_logo_url"] == HOME_LOGO
    assert match["away_team_logo_url"] == AWAY_LOGO
    # Both teams in the same one batch.
    assert storage.calls == [(HOME_KEY, AWAY_KEY)]
    assert observations == [False]
    # The previous contract is preserved.
    assert match["home_team_name"] == "Home FC"
    assert match["away_team_short_code"] == "AWY"
    assert "limits" in response.json()


@pytest.mark.asyncio
async def test_match_operation_without_crests_does_not_call_the_storage(
    client, monkeypatch
):
    database = SurfaceDatabase(match=match_row(home_key=None, away_key=None))
    storage = SurfaceStorage()
    use_storage(monkeypatch, storage)

    response = await get(client, database, OPERATION_URL)

    assert response.status_code == 200
    match = response.json()["match"]
    assert match["home_team_crest_url"] is None
    assert match["away_team_crest_url"] is None
    assert storage.calls == []


def test_operation_selects_the_legacy_logo_for_the_workspace():
    from app.modules.matches.router import _load_operation_match

    source = inspect.getsource(_load_operation_match)
    assert "ht.logo_url AS home_team_logo_url" in source
    assert "at.logo_url AS away_team_logo_url" in source


@pytest.mark.asyncio
async def test_match_operation_signature_failure_answers_503(client, monkeypatch):
    database = SurfaceDatabase(
        match=match_row(home_key=HOME_KEY, away_key=AWAY_KEY)
    )
    storage = SurfaceStorage(fail=True)
    use_storage(monkeypatch, storage)

    response = await get(client, database, OPERATION_URL)

    assert response.status_code == 503
    assert response.json()["code"] == CREST_STORAGE_UNAVAILABLE
    assert storage.calls == [(HOME_KEY, AWAY_KEY)]


# ---------------------------------------------------------------------------
# Real PostgreSQL (opt-in): the listing SQL, the aggregate and the batch
# ---------------------------------------------------------------------------

from sqlalchemy import text  # noqa: E402

from db_helpers import TenantContext, set_tenant_context  # noqa: E402


class SavepointAdapter:
    """Run the endpoint's ``db.begin()`` as a savepoint of the fixture."""

    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


async def seed_listing(session, tenant) -> tuple[UUID, UUID, UUID]:
    await set_tenant_context(session, tenant)
    tournament_id = uuid4()
    with_crest = uuid4()
    with_logo = uuid4()
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
            "name": f"Crest Listing {tournament_id.hex[:8]}",
        },
    )
    for team_id, name, crest, logo in (
        (with_crest, "With Crest", HOME_KEY, None),
        (with_logo, "With Logo", None, LEGACY_LOGO),
    ):
        await session.execute(
            text("""
                INSERT INTO teams
                    (id, organization_id, name, short_code, logo_url,
                     crest_object_key)
                VALUES (:id, :organization_id, :name, :short_code, :logo, :crest)
            """),
            {
                "id": str(team_id),
                "organization_id": str(tenant.organization_id),
                "name": name,
                "short_code": f"L{team_id.hex[:4].upper()}",
                "logo": logo,
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
    return tournament_id, with_crest, with_logo


@pytest.mark.asyncio
async def test_teams_listing_with_a_real_database_signs_after_the_savepoint(
    db_session, tenant_factory, monkeypatch
):
    tenant: TenantContext = await tenant_factory("Crest Listing Owner")
    tournament_id, with_crest, with_logo = await seed_listing(db_session, tenant)
    storage = SurfaceStorage()
    use_storage(monkeypatch, storage)
    context = AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )

    async def _db():
        yield SavepointAdapter(db_session)

    api.dependency_overrides[get_auth_context] = lambda: context
    api.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/tournaments/{tournament_id}/teams"
            )
    finally:
        api.dependency_overrides.clear()

    assert response.status_code == 200
    rows = {row["team_id"]: row for row in response.json()}
    assert set(rows) == {str(with_crest), str(with_logo)}
    assert rows[str(with_crest)]["crest_url"] == "https://signed.test/0.png"
    assert rows[str(with_crest)]["logo_url"] is None
    assert rows[str(with_logo)]["crest_url"] is None
    assert rows[str(with_logo)]["logo_url"] == LEGACY_LOGO
    assert "crest_object_key" not in response.text
    assert storage.calls == [(HOME_KEY,)]
