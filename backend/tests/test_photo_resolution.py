"""Photo resolution policy and the public signing boundary (RF-002, RF-003, RF-004).

``sign_photo_rows`` is the single resolver for every response that signs player
photos: it signs a whole batch once, degrades to ``null`` on the public path and
raises 503 on the Workspace path, with exactly one log entry per response.

The HTTP tests override ``get_db`` with an in-memory double that records
``in_transaction()``, so the N-2 boundary (queries inside the transaction,
signing after it closes) is verified without PostgreSQL or S3.
"""

from __future__ import annotations

import asyncio
import io
import logging
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import UploadFile

from app.core import storage as storage_module
from app.core.database import get_db
from app.core.storage import ObjectStorage, SignedUrls, StorageError
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.tournaments import photos as photos_module
from app.modules.tournaments import router as tournaments_router
from app.modules.tournaments.photos import sign_photo_rows
from app.modules.tournaments.roster_import import ImportedRosterRow, PhotoFile
from app.modules.tournaments.schemas import CreateRosterPlayerRequest

STORAGE_DETAIL = "El almacenamiento de fotos no está disponible"
PHOTOS_LOGGER = "app.modules.tournaments.photos"
PHOTO_KEY = "private/organizations/org-1/rosters/roster-1/photo.jpg"
OTHER_KEY = "private/organizations/org-1/rosters/roster-2/photo.jpg"


def signed(key: str) -> str:
    return f"https://signed.example/{key}"


class FakeStorage:
    """Signing double: records batches, failures and the transaction state."""

    def __init__(self, *, failed=(), reason=None, error=None, session=None):
        self.failed = tuple(failed)
        self.reason = reason
        self.error = error
        self.session = session
        self.calls: list[list[str]] = []
        self.transaction_states: list[bool] = []

    async def signed_urls(self, keys, expires_seconds=None):
        keys = list(keys)
        self.calls.append(keys)
        if self.session is not None:
            self.transaction_states.append(self.session.in_transaction())
        if self.error is not None:
            raise self.error
        urls = {key: signed(key) for key in keys if key not in self.failed}
        if self.failed:
            return SignedUrls(
                urls=urls,
                failed=self.failed,
                reason=self.reason or "sign_failed",
            )
        return SignedUrls(urls=urls, failed=(), reason=None)


class ExplodingStorage:
    async def signed_urls(self, keys, expires_seconds=None):  # pragma: no cover - must not run
        raise AssertionError("el almacenamiento no debe usarse sin claves")


def resolver_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == PHOTOS_LOGGER]


async def test_null_policy_degrades_only_the_failed_photos():
    storage = FakeStorage(failed=(OTHER_KEY,))
    rows = [
        {
            "player_id": 1,
            "first_name": "Ana",
            "last_name": "Pérez",
            "photo_object_key": PHOTO_KEY,
            "photo_consent": True,
        },
        {
            "player_id": 2,
            "first_name": "Luis",
            "last_name": "Gómez",
            "photo_object_key": OTHER_KEY,
            "photo_consent": True,
        },
        {
            "player_id": 3,
            "first_name": "Eva",
            "last_name": "Díaz",
            "photo_object_key": None,
            "photo_consent": False,
        },
    ]

    resolved = await sign_photo_rows(
        rows, key_field="photo_object_key", policy="null", storage=storage
    )

    assert resolved is rows
    assert [row["photo_url"] for row in rows] == [signed(PHOTO_KEY), None, None]
    assert [row["player_id"] for row in rows] == [1, 2, 3]
    assert rows[0]["first_name"] == "Ana"
    assert all("photo_object_key" not in row for row in rows)
    assert storage.calls == [[PHOTO_KEY, OTHER_KEY]]


async def test_error_policy_raises_503_without_internal_details(caplog):
    storage = FakeStorage(failed=(PHOTO_KEY,))
    rows = [{"photo_object_key": PHOTO_KEY, "photo_consent": True}]

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        with pytest.raises(HTTPException) as failure:
            await sign_photo_rows(
                rows, key_field="photo_object_key", policy="error", storage=storage
            )

    assert failure.value.status_code == 503
    assert failure.value.detail == STORAGE_DETAIL
    assert "storage" not in failure.value.detail
    assert len(resolver_records(caplog)) == 1


async def test_a_single_stable_warning_per_response_without_personal_data(caplog):
    storage = FakeStorage(failed=(PHOTO_KEY, OTHER_KEY))
    rows = [
        {
            "first_name": "Ana",
            "last_name": "Pérez",
            "national_id": "1029384756",
            "birth_date": "2000-01-01",
            "photo_object_key": PHOTO_KEY,
            "photo_consent": True,
        },
        {
            "first_name": "Luis",
            "last_name": "Gómez",
            "national_id": "99887766",
            "birth_date": "1999-02-02",
            "photo_object_key": OTHER_KEY,
            "photo_consent": True,
        },
    ]

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        await sign_photo_rows(
            rows, key_field="photo_object_key", policy="null", storage=storage
        )

    records = resolver_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert message == "No se pudieron firmar 2 fotos (sign_failed)"
    for fragment in (
        PHOTO_KEY,
        OTHER_KEY,
        "Ana",
        "Pérez",
        "Luis",
        "Gómez",
        "1029384756",
        "99887766",
        "2000-01-01",
        "1999-02-02",
    ):
        assert fragment not in message


async def test_rows_without_consent_or_key_do_not_call_storage(caplog):
    rows = [
        {"photo_object_key": PHOTO_KEY, "photo_consent": False},
        {"photo_object_key": None, "photo_consent": True},
    ]

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        resolved = await sign_photo_rows(
            rows,
            key_field="photo_object_key",
            policy="error",
            storage=ExplodingStorage(),
        )

    assert [row["photo_url"] for row in resolved] == [None, None]
    assert all("photo_object_key" not in row for row in rows)
    assert resolver_records(caplog) == []


async def test_repeated_keys_are_signed_once_and_share_the_url():
    storage = FakeStorage()
    rows = [
        {"photo_object_key": PHOTO_KEY, "photo_consent": True},
        {"photo_object_key": PHOTO_KEY, "photo_consent": True},
        {"photo_object_key": OTHER_KEY, "photo_consent": True},
    ]

    resolved = await sign_photo_rows(
        rows, key_field="photo_object_key", policy="error", storage=storage
    )

    assert storage.calls == [[PHOTO_KEY, OTHER_KEY]]
    assert [row["photo_url"] for row in resolved] == [
        signed(PHOTO_KEY),
        signed(PHOTO_KEY),
        signed(OTHER_KEY),
    ]


async def test_public_rows_keep_the_key_field_position():
    storage = FakeStorage()
    rows = [{"player_id": 1, "photo_url": PHOTO_KEY}]

    resolved = await sign_photo_rows(
        rows,
        key_field="photo_url",
        consent_field=None,
        policy="null",
        storage=storage,
    )

    assert list(resolved[0]) == ["player_id", "photo_url"]
    assert resolved[0]["photo_url"] == signed(PHOTO_KEY)


async def test_a_raising_storage_degrades_to_null_on_the_public_path(caplog):
    storage = FakeStorage(error=StorageError("storage down"))
    rows = [{"player_id": 1, "photo_url": PHOTO_KEY}]

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        resolved = await sign_photo_rows(
            rows,
            key_field="photo_url",
            consent_field=None,
            policy="null",
            storage=storage,
        )

    assert resolved[0]["photo_url"] is None
    records = resolver_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == "No se pudieron firmar 1 fotos (sign_failed)"


async def test_a_raising_storage_keeps_the_workspace_error():
    storage = FakeStorage(error=StorageError("storage down"))
    rows = [{"photo_object_key": PHOTO_KEY, "photo_consent": True}]

    with pytest.raises(HTTPException) as failure:
        await sign_photo_rows(
            rows, key_field="photo_object_key", policy="error", storage=storage
        )

    assert failure.value.status_code == 503
    assert failure.value.detail == STORAGE_DETAIL


MATCH_ID = uuid4()
TOURNAMENT_ID = uuid4()
STAGE_ID = uuid4()
HOME_TEAM_ID = uuid4()
AWAY_TEAM_ID = uuid4()
HOME_STARTER_ID = uuid4()
HOME_SUBSTITUTE_ID = uuid4()
AWAY_STARTER_ID = uuid4()
AWAY_SUBSTITUTE_ID = uuid4()


def match_row() -> dict:
    return {
        "id": MATCH_ID,
        "tournament_id": TOURNAMENT_ID,
        "stage_id": STAGE_ID,
        "stage_name": "Group stage",
        "stage_order": 1,
        "group_id": None,
        "group_name": None,
        "bracket_code": None,
        "matchday": 1,
        "match_date": None,
        "home_team_id": HOME_TEAM_ID,
        "home_team_name": "Home FC",
        "home_team_short_code": "HOM",
        "away_team_id": AWAY_TEAM_ID,
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
    }


def lineup_row(
    *,
    side: str,
    team_id: UUID,
    team_name: str,
    player_id: UUID,
    first_name: str,
    last_name: str,
    dorsal_number: int | None,
    role: str,
    position_slot: str | None,
    photo_url: str | None,
) -> dict:
    return {
        "match_id": MATCH_ID,
        "team_id": team_id,
        "team_name": team_name,
        "side": side,
        "formation_code": "4-3-3",
        "player_id": player_id,
        "first_name": first_name,
        "last_name": last_name,
        "dorsal_number": dorsal_number,
        "role": role,
        "position_slot": position_slot,
        "photo_url": photo_url,
    }


def lineup_rows() -> list[dict]:
    """Rows in the order the view returns them (match, side, role, dorsal)."""

    return [
        lineup_row(
            side="away",
            team_id=AWAY_TEAM_ID,
            team_name="Away FC",
            player_id=AWAY_STARTER_ID,
            first_name="Marta",
            last_name="Ruiz",
            dorsal_number=7,
            role="starter",
            position_slot="RW",
            photo_url=OTHER_KEY,
        ),
        lineup_row(
            side="away",
            team_id=AWAY_TEAM_ID,
            team_name="Away FC",
            player_id=AWAY_SUBSTITUTE_ID,
            first_name="Pablo",
            last_name="Santos",
            dorsal_number=15,
            role="substitute",
            position_slot=None,
            photo_url=PHOTO_KEY,
        ),
        lineup_row(
            side="home",
            team_id=HOME_TEAM_ID,
            team_name="Home FC",
            player_id=HOME_STARTER_ID,
            first_name="Ana",
            last_name="Pérez",
            dorsal_number=9,
            role="starter",
            position_slot="ST",
            photo_url=PHOTO_KEY,
        ),
        lineup_row(
            side="home",
            team_id=HOME_TEAM_ID,
            team_name="Home FC",
            player_id=HOME_SUBSTITUTE_ID,
            first_name="Eva",
            last_name="Díaz",
            dorsal_number=20,
            role="substitute",
            position_slot=None,
            photo_url=None,
        ),
    ]


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeTransaction:
    def __init__(self, session: "FakeSession"):
        self._session = session

    async def __aenter__(self):
        self._session.active = True
        return self

    async def __aexit__(self, *exc_info):
        self._session.active = False
        return False


class FakeSession:
    """Minimal session double that records query and signing transaction states."""

    def __init__(self, matches, lineups, *, tournament_exists: bool = True):
        self.matches = matches
        self.lineups = lineups
        self.tournament_exists = tournament_exists
        self.active = False
        self.statements: list[str] = []
        self.query_transaction_states: list[bool] = []

    def begin(self):
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.active

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.query_transaction_states.append(self.active)
        if "v_public_tournaments" in sql:
            return FakeResult([1] if self.tournament_exists else [])
        if "v_public_match_lineups" in sql:
            return FakeResult(self.lineups)
        if "v_public_matches" in sql:
            return FakeResult(self.matches)
        raise AssertionError(f"consulta inesperada: {sql}")


@asynccontextmanager
async def public_matches_client(session: FakeSession):
    async def database():
        yield session

    api.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)


async def get_public_matches(session: FakeSession):
    async with public_matches_client(session) as client:
        return await client.get(f"/api/v1/tournaments/public/{TOURNAMENT_ID}/matches")


def install_storage(monkeypatch, storage: FakeStorage) -> None:
    monkeypatch.setattr(photos_module, "get_object_storage", lambda: storage)


def players_by_id(payload: list[dict]) -> dict[str, dict]:
    players = {}
    for match in payload:
        for team in (match.get("lineup") or {}).values():
            if not team:
                continue
            for player in team["starters"] + team["substitutes"]:
                players[player["player_id"]] = player
    return players


async def test_public_matches_degrades_failed_photos_to_null(monkeypatch, caplog):
    session = FakeSession([match_row()], lineup_rows())
    storage = FakeStorage(error=StorageError("storage down"), session=session)
    install_storage(monkeypatch, storage)

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        response = await get_public_matches(session)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    players = players_by_id(payload)
    assert players[str(HOME_STARTER_ID)]["photo_url"] is None
    assert players[str(HOME_STARTER_ID)]["first_name"] == "Ana"
    assert players[str(HOME_SUBSTITUTE_ID)]["photo_url"] is None
    assert players[str(AWAY_STARTER_ID)]["last_name"] == "Ruiz"
    assert payload[0]["home_team_name"] == "Home FC"
    assert payload[0]["status"] == "scheduled"
    assert len(resolver_records(caplog)) == 1


async def test_public_matches_signs_after_the_read_transaction_closes(monkeypatch):
    session = FakeSession([match_row()], lineup_rows())
    storage = FakeStorage(session=session)
    install_storage(monkeypatch, storage)

    response = await get_public_matches(session)

    assert response.status_code == 200
    assert session.query_transaction_states == [True, True, True]
    assert storage.transaction_states == [False]
    assert session.in_transaction() is False


async def test_public_matches_keeps_the_reference_payload(monkeypatch):
    session = FakeSession([match_row()], lineup_rows())
    storage = FakeStorage(session=session)
    install_storage(monkeypatch, storage)

    response = await get_public_matches(session)

    assert response.status_code == 200
    assert response.json() == [
        {
            **{key: _json(value) for key, value in match_row().items()},
            "lineup": {
                "home": {
                    "team_id": str(HOME_TEAM_ID),
                    "team_name": "Home FC",
                    "formation_code": "4-3-3",
                    "starters": [
                        {
                            "player_id": str(HOME_STARTER_ID),
                            "first_name": "Ana",
                            "last_name": "Pérez",
                            "dorsal_number": 9,
                            "role": "starter",
                            "position_slot": "ST",
                            "photo_url": signed(PHOTO_KEY),
                        }
                    ],
                    "substitutes": [
                        {
                            "player_id": str(HOME_SUBSTITUTE_ID),
                            "first_name": "Eva",
                            "last_name": "Díaz",
                            "dorsal_number": 20,
                            "role": "substitute",
                            "position_slot": None,
                            "photo_url": None,
                        }
                    ],
                },
                "away": {
                    "team_id": str(AWAY_TEAM_ID),
                    "team_name": "Away FC",
                    "formation_code": "4-3-3",
                    "starters": [
                        {
                            "player_id": str(AWAY_STARTER_ID),
                            "first_name": "Marta",
                            "last_name": "Ruiz",
                            "dorsal_number": 7,
                            "role": "starter",
                            "position_slot": "RW",
                            "photo_url": signed(OTHER_KEY),
                        }
                    ],
                    "substitutes": [
                        {
                            "player_id": str(AWAY_SUBSTITUTE_ID),
                            "first_name": "Pablo",
                            "last_name": "Santos",
                            "dorsal_number": 15,
                            "role": "substitute",
                            "position_slot": None,
                            "photo_url": signed(PHOTO_KEY),
                        }
                    ],
                },
            },
        }
    ]
    # Deduplicated once per distinct key, in first-appearance order.
    assert storage.calls == [[OTHER_KEY, PHOTO_KEY]]


async def test_public_matches_without_photo_keys_skips_storage(monkeypatch, caplog):
    rows = [
        lineup_row(
            side="home",
            team_id=HOME_TEAM_ID,
            team_name="Home FC",
            player_id=HOME_STARTER_ID,
            first_name="Ana",
            last_name="Pérez",
            dorsal_number=9,
            role="starter",
            position_slot="ST",
            photo_url=None,
        )
    ]
    session = FakeSession([match_row()], rows)
    storage = FakeStorage(session=session)
    install_storage(monkeypatch, storage)

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        response = await get_public_matches(session)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["lineup"]["home"]["starters"][0]["photo_url"] is None
    assert storage.calls == []
    assert session.in_transaction() is False
    assert resolver_records(caplog) == []


def _json(value):
    return str(value) if isinstance(value, UUID) else value


# ---------------------------------------------------------------------------
# Workspace paths: read/write inside the transaction, sign after it (T003)
# ---------------------------------------------------------------------------

ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
MEMBER_ID = uuid4()
WORKSPACE_TEAM_ID = uuid4()
ROSTER_ID = uuid4()
PLAYER_ID = uuid4()
ROSTER_A = uuid4()
ROSTER_B = uuid4()
OLD_KEY = "private/organizations/org-1/rosters/roster-1/old.jpg"
NEW_KEY = "private/organizations/org-1/rosters/roster-1/new.jpg"
PHOTO_FILE = PhotoFile(content=b"jpeg-bytes", content_type="image/jpeg", extension=".jpg")


class FakeScalar:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class WorkspaceTransaction:
    def __init__(self, session: "WorkspaceSession"):
        self._session = session

    async def __aenter__(self):
        self._session.active = True
        return self

    async def __aexit__(self, exc_type, exc_info, traceback):
        session = self._session
        session.active = False
        if exc_type is None:
            session.committed = True
        else:
            session.rolled_back = True
        if (
            exc_type is None
            and session.cancel_commit_on_begin == session.begins
        ):
            # Simulate a cancellation delivered while committing: the fake
            # marks the transaction committed and then raises.
            raise asyncio.CancelledError()
        if exc_type is None and session.fail_commit_on_begin == session.begins:
            # Simulate a commit that fails and rolls back.
            session.committed = False
            session.rolled_back = True
            raise RuntimeError("commit failed")
        return False


class WorkspaceSession:
    """Session double that records query and signing transaction states."""

    def __init__(
        self,
        *,
        roster_rows=None,
        roster_lookup=None,
        set_photo_result=None,
        set_consent_result=None,
        team_registered: bool = True,
        cancel_commit_on_begin: int | None = None,
        fail_commit_on_begin: int | None = None,
    ):
        self.roster_rows = roster_rows if roster_rows is not None else []
        self.roster_lookup = roster_lookup
        self.set_photo_result = set_photo_result
        self.set_consent_result = set_consent_result
        self.team_registered = team_registered
        self.cancel_commit_on_begin = cancel_commit_on_begin
        self.fail_commit_on_begin = fail_commit_on_begin
        self.active = False
        self.committed = False
        self.rolled_back = False
        self.begins = 0
        self.statements: list[str] = []
        self.query_transaction_states: list[bool] = []

    def begin(self):
        self.begins += 1
        return WorkspaceTransaction(self)

    def in_transaction(self) -> bool:
        return self.active

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append(sql)
        self.query_transaction_states.append(self.active)
        if "set_config" in sql:
            return FakeResult([])
        if "set_roster_photo_object" in sql:
            return FakeScalar(self.set_photo_result)
        if "set_roster_photo_consent" in sql:
            return FakeScalar(self.set_consent_result)
        if "FROM tournament_versions" in sql:
            # These flows do not model a published version, so the roster lock
            # never applies (RF-022).
            return FakeResult([])
        if "FROM tournaments" in sql:
            return FakeScalar(1)
        if "FROM tournament_teams" in sql:
            return FakeScalar(1 if self.team_registered else None)
        if "JOIN players p" in sql:
            roster_ids = (params or {}).get("roster_ids")
            if roster_ids and self.roster_rows:
                rows = []
                for index, roster_id in enumerate(roster_ids):
                    template = dict(self.roster_rows[index % len(self.roster_rows)])
                    template["roster_id"] = roster_id
                    rows.append(template)
                return FakeResult(rows)
            return FakeResult(self.roster_rows)
        if "FROM rosters r" in sql:
            lookup = [self.roster_lookup] if self.roster_lookup is not None else []
            return FakeResult(lookup)
        if "FROM rosters" in sql:
            lookup = [self.roster_lookup] if self.roster_lookup is not None else []
            return FakeResult(lookup)
        raise AssertionError(f"consulta inesperada: {sql}")


class WorkspaceStorage:
    """Storage double for uploads, deletions and batch signing."""

    def __init__(self, *, session: WorkspaceSession, failed=(), error=None):
        self.session = session
        self.failed = tuple(failed)
        self.error = error
        self.signed_calls: list[list[str]] = []
        self.signed_transaction_states: list[bool] = []
        self.puts: list[str] = []
        self.put_transaction_states: list[bool] = []
        self.deleted: list[str] = []
        self.delete_transaction_states: list[bool] = []
        self.fail_put_at: int | None = None
        self.on_put = None

    async def put_bytes(self, key, content, content_type):
        self.puts.append(key)
        self.put_transaction_states.append(self.session.in_transaction())
        if self.fail_put_at is not None and len(self.puts) == self.fail_put_at:
            raise StorageError("upload failed")
        if self.on_put is not None:
            self.on_put(key)
        return key

    async def delete_key(self, key):
        self.deleted.append(key)
        self.delete_transaction_states.append(self.session.in_transaction())

    async def signed_urls(self, keys, expires_seconds=None):
        keys = list(keys)
        self.signed_calls.append(keys)
        self.signed_transaction_states.append(self.session.in_transaction())
        if self.error is not None:
            raise self.error
        urls = {key: signed(key) for key in keys if key not in self.failed}
        if self.failed:
            return SignedUrls(urls=urls, failed=self.failed, reason="sign_failed")
        return SignedUrls(urls=urls)


def roster_row(
    roster_id: UUID,
    *,
    player_id: UUID = PLAYER_ID,
    photo_object_key: str | None = None,
    photo_consent: bool = True,
    first_name: str = "Ana",
    last_name: str = "Pérez",
    dorsal_number: int = 9,
) -> dict:
    return {
        "roster_id": roster_id,
        "player_id": player_id,
        "team_id": WORKSPACE_TEAM_ID,
        "first_name": first_name,
        "last_name": last_name,
        "dorsal_number": dorsal_number,
        "photo_object_key": photo_object_key,
        "photo_consent": photo_consent,
        "is_active": True,
        "age": 24,
    }


def player_payload(**overrides) -> dict:
    payload = {
        "team_id": str(WORKSPACE_TEAM_ID),
        "first_name": "Ana",
        "last_name": "Pérez",
        "document_type": "internal",
        "national_id": "1029384756",
        "issuing_country": "COL",
        "birth_date": "2000-01-01",
        "dorsal_number": 9,
        "photo_consent": True,
    }
    payload.update(overrides)
    return payload


def workspace_context() -> AuthContext:
    return AuthContext(
        user_id=USER_ID,
        organization_id=ORGANIZATION_ID,
        organization_user_id=MEMBER_ID,
    )


@asynccontextmanager
async def workspace_client(session: WorkspaceSession):
    async def database():
        yield session

    async def context():
        return workspace_context()

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = context
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


def install_workspace_storage(monkeypatch, storage: WorkspaceStorage) -> None:
    monkeypatch.setattr(tournaments_router, "get_object_storage", lambda: storage)
    monkeypatch.setattr(photos_module, "get_object_storage", lambda: storage)


def install_roster_record(
    monkeypatch, session: WorkspaceSession, roster_ids=(ROSTER_ID,), player_id=PLAYER_ID
):
    """Replace the write helper; record the transaction state of each create."""

    states: list[bool] = []
    ids = list(roster_ids)

    async def fake_create(
        db, context, tournament_id, payload, settings, roster_id=None
    ):
        states.append(session.in_transaction())
        return (roster_id or ids[len(states) - 1]), player_id

    monkeypatch.setattr(
        tournaments_router, "_create_roster_player_record", fake_create
    )
    return states


def imported_rows(*, with_photos: bool) -> list[ImportedRosterRow]:
    return [
        ImportedRosterRow(
            2,
            CreateRosterPlayerRequest(
                team_id=WORKSPACE_TEAM_ID,
                first_name="Ana",
                last_name="Pérez",
                national_id="1029384756",
                birth_date=date(2000, 1, 1),
                dorsal_number=9,
                photo_consent=with_photos,
            ),
            "ana.jpg" if with_photos else None,
        ),
        ImportedRosterRow(
            3,
            CreateRosterPlayerRequest(
                team_id=WORKSPACE_TEAM_ID,
                first_name="Luis",
                last_name="Gómez",
                national_id="99887766",
                birth_date=date(1999, 2, 2),
                dorsal_number=7,
                photo_consent=with_photos,
            ),
            "luis.jpg" if with_photos else None,
        ),
    ]


def install_import(monkeypatch, *, with_photos: bool) -> None:
    monkeypatch.setattr(
        tournaments_router, "parse_roster_csv", lambda raw, team_id: imported_rows(with_photos=with_photos)
    )
    if with_photos:
        monkeypatch.setattr(
            tournaments_router,
            "extract_zip_photos",
            lambda raw: {"ana.jpg": PHOTO_FILE, "luis.jpg": PHOTO_FILE},
        )


async def test_roster_list_signs_in_one_batch_after_the_transaction(
    monkeypatch, allow_management
):
    rows = [
        roster_row(ROSTER_ID, photo_object_key=PHOTO_KEY),
        roster_row(
            ROSTER_A,
            player_id=uuid4(),
            photo_object_key=OTHER_KEY,
            first_name="Luis",
            last_name="Gómez",
            dorsal_number=7,
        ),
        roster_row(
            ROSTER_B,
            player_id=uuid4(),
            photo_object_key=None,
            photo_consent=False,
            first_name="Eva",
            last_name="Díaz",
            dorsal_number=20,
        ),
    ]
    session = WorkspaceSession(roster_rows=rows)
    storage = WorkspaceStorage(session=session)
    install_workspace_storage(monkeypatch, storage)

    async with workspace_client(session) as client:
        response = await client.get(f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters")

    assert response.status_code == 200
    payload = response.json()
    assert [player["first_name"] for player in payload] == ["Ana", "Luis", "Eva"]
    assert [player["photo_url"] for player in payload] == [
        signed(PHOTO_KEY),
        signed(OTHER_KEY),
        None,
    ]
    assert all("photo_object_key" not in player for player in payload)
    assert payload[0]["age"] == 24
    assert storage.signed_calls == [[PHOTO_KEY, OTHER_KEY]]
    assert storage.signed_transaction_states == [False]
    assert session.query_transaction_states and all(session.query_transaction_states)
    assert session.committed is True


async def test_roster_list_returns_503_when_signing_fails(monkeypatch, allow_management):
    session = WorkspaceSession(
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=PHOTO_KEY)]
    )
    storage = WorkspaceStorage(session=session, error=StorageError("storage down"))
    install_workspace_storage(monkeypatch, storage)

    async with workspace_client(session) as client:
        response = await client.get(f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters")

    assert response.status_code == 503
    assert response.json() == {"detail": STORAGE_DETAIL}
    assert session.committed is True
    assert session.rolled_back is False


async def test_create_roster_player_signs_after_the_commit(monkeypatch, allow_management):
    session = WorkspaceSession(
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=PHOTO_KEY)]
    )
    storage = WorkspaceStorage(session=session)
    install_workspace_storage(monkeypatch, storage)
    create_states = install_roster_record(monkeypatch, session)

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters", json=player_payload()
        )

    assert response.status_code == 201
    body = response.json()
    assert body["photo_url"] == signed(PHOTO_KEY)
    assert "photo_object_key" not in body
    assert create_states == [True]
    assert storage.signed_calls == [[PHOTO_KEY]]
    assert storage.signed_transaction_states == [False]
    assert session.committed is True


async def test_create_roster_player_keeps_the_committed_row_on_signing_failure(
    monkeypatch, allow_management
):
    # Consequence of N-2: the row is committed before signing, so a signing
    # failure answers 503 but never rolls the row back.
    session = WorkspaceSession(
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=PHOTO_KEY)]
    )
    storage = WorkspaceStorage(session=session, error=StorageError("storage down"))
    install_workspace_storage(monkeypatch, storage)
    create_states = install_roster_record(monkeypatch, session)

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters", json=player_payload()
        )

    assert response.status_code == 503
    assert response.json() == {"detail": STORAGE_DETAIL}
    assert create_states == [True]
    assert session.committed is True
    assert session.rolled_back is False


async def test_bulk_import_signs_all_rows_in_one_batch(monkeypatch, allow_management):
    session = WorkspaceSession(
        roster_rows=[
            roster_row(ROSTER_A, player_id=uuid4()),
            roster_row(ROSTER_B, player_id=uuid4(), first_name="Luis", last_name="Gómez"),
        ]
    )
    storage = WorkspaceStorage(session=session)
    installed: list[str] = []

    def assign_key(key: str) -> None:
        installed.append(key)
        session.roster_rows[len(installed) - 1]["photo_object_key"] = key

    storage.on_put = assign_key
    install_workspace_storage(monkeypatch, storage)
    create_states = install_roster_record(
        monkeypatch, session, roster_ids=(ROSTER_A, ROSTER_B)
    )
    install_import(monkeypatch, with_photos=True)

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
            data={"team_id": str(WORKSPACE_TEAM_ID)},
            files={
                "csv_file": ("roster.csv", b"", "text/csv"),
                "photos_zip": ("photos.zip", b"", "application/zip"),
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["count"] == 2
    assert [player["photo_url"] for player in body["players"]] == [
        signed(key) for key in installed
    ]
    assert create_states == [True, True]
    assert storage.put_transaction_states == [False, False]
    assert len(storage.signed_calls) == 1
    assert storage.signed_calls[0] == installed
    assert storage.signed_transaction_states == [False]
    assert all("photo_object_key" not in player for player in body["players"])
    assert session.committed is True


async def test_bulk_import_keeps_uploaded_keys_on_signing_failure(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_rows=[
            roster_row(ROSTER_A, player_id=uuid4()),
            roster_row(ROSTER_B, player_id=uuid4(), first_name="Luis", last_name="Gómez"),
        ]
    )
    storage = WorkspaceStorage(session=session, error=StorageError("storage down"))
    installed: list[str] = []

    def assign_key(key: str) -> None:
        installed.append(key)
        session.roster_rows[len(installed) - 1]["photo_object_key"] = key

    storage.on_put = assign_key
    install_workspace_storage(monkeypatch, storage)
    install_roster_record(monkeypatch, session, roster_ids=(ROSTER_A, ROSTER_B))
    install_import(monkeypatch, with_photos=True)

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
            data={"team_id": str(WORKSPACE_TEAM_ID)},
            files={
                "csv_file": ("roster.csv", b"", "text/csv"),
                "photos_zip": ("photos.zip", b"", "application/zip"),
            },
        )

    assert response.status_code == 503
    assert len(storage.puts) == 2
    assert storage.put_transaction_states == [False, False]
    assert storage.deleted == []
    assert session.committed is True
    assert session.rolled_back is False


async def test_bulk_import_compensates_a_failed_upload_before_the_transaction(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_rows=[
            roster_row(ROSTER_A, player_id=uuid4()),
            roster_row(ROSTER_B, player_id=uuid4(), first_name="Luis", last_name="Gómez"),
        ]
    )
    storage = WorkspaceStorage(session=session)
    storage.fail_put_at = 2
    install_workspace_storage(monkeypatch, storage)
    install_roster_record(monkeypatch, session, roster_ids=(ROSTER_A, ROSTER_B))
    install_import(monkeypatch, with_photos=True)

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
            data={"team_id": str(WORKSPACE_TEAM_ID)},
            files={
                "csv_file": ("roster.csv", b"", "text/csv"),
                "photos_zip": ("photos.zip", b"", "application/zip"),
            },
        )

    assert response.status_code == 503
    # M1: the failing key was registered before put_bytes, so both are cleaned.
    assert storage.deleted == storage.puts
    assert storage.delete_transaction_states == [False, False]
    assert storage.put_transaction_states == [False, False]
    assert not any(
        sql.startswith(("INSERT INTO", "UPDATE ", "DELETE FROM"))
        for sql in session.statements
    )
    assert session.rolled_back is False
    # Only the authorization read transaction ran; no write transaction opened.
    assert session.committed is True


async def test_upload_photo_signs_after_commit_and_deletes_the_old_object(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    storage = WorkspaceStorage(session=session)

    def assign_key(key: str) -> None:
        session.roster_rows[0]["photo_object_key"] = key

    storage.on_put = assign_key
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo",
            files={"photo": ("photo.jpg", b"jpeg-bytes", "image/jpeg")},
        )

    assert response.status_code == 200
    new_key = storage.puts[0]
    assert response.json()["photo_url"] == signed(new_key)
    assert storage.put_transaction_states == [False]
    assert storage.signed_calls == [[new_key]]
    assert storage.signed_transaction_states == [False]
    assert storage.deleted == [OLD_KEY]
    assert storage.delete_transaction_states == [False]
    assert session.committed is True


async def test_upload_photo_does_not_delete_the_new_object_on_signing_failure(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    storage = WorkspaceStorage(session=session, error=StorageError("storage down"))

    def assign_key(key: str) -> None:
        session.roster_rows[0]["photo_object_key"] = key

    storage.on_put = assign_key
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo",
            files={"photo": ("photo.jpg", b"jpeg-bytes", "image/jpeg")},
        )

    assert response.status_code == 503
    new_key = storage.puts[0]
    assert new_key not in storage.deleted
    assert storage.deleted == [OLD_KEY]
    assert storage.delete_transaction_states == [False]
    assert storage.signed_transaction_states == [False]
    assert session.committed is True
    assert session.rolled_back is False


async def test_upload_photo_compensates_a_failed_upload_before_the_write_transaction(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    storage = WorkspaceStorage(session=session)
    storage.fail_put_at = 1
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo",
            files={"photo": ("photo.jpg", b"jpeg-bytes", "image/jpeg")},
        )

    assert response.status_code == 503
    assert storage.deleted == [storage.puts[0]]
    assert storage.put_transaction_states == [False]
    assert storage.delete_transaction_states == [False]
    assert not any(
        sql.startswith(("INSERT INTO", "UPDATE ", "DELETE FROM"))
        for sql in session.statements
    )
    assert session.rolled_back is False
    assert session.committed is True


async def test_revoking_consent_deletes_the_object_and_signs_nothing(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={"id": ROSTER_ID},
        set_consent_result=OLD_KEY,
        roster_rows=[
            roster_row(ROSTER_ID, photo_object_key=None, photo_consent=False)
        ],
    )
    storage = WorkspaceStorage(session=session)
    install_workspace_storage(monkeypatch, storage)

    async with workspace_client(session) as client:
        response = await client.patch(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo-consent",
            json={"photo_consent": False},
        )

    assert response.status_code == 200
    assert response.json()["photo_url"] is None
    assert "photo_object_key" not in response.json()
    assert storage.signed_calls == []
    assert storage.deleted == [OLD_KEY]
    assert storage.delete_transaction_states == [False]
    assert session.committed is True


async def test_granting_consent_signs_after_the_commit(monkeypatch, allow_management):
    session = WorkspaceSession(
        roster_lookup={"id": ROSTER_ID},
        set_consent_result=None,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=PHOTO_KEY)],
    )
    storage = WorkspaceStorage(session=session)
    install_workspace_storage(monkeypatch, storage)

    async with workspace_client(session) as client:
        response = await client.patch(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo-consent",
            json={"photo_consent": True},
        )

    assert response.status_code == 200
    assert response.json()["photo_url"] == signed(PHOTO_KEY)
    assert storage.signed_calls == [[PHOTO_KEY]]
    assert storage.signed_transaction_states == [False]
    assert storage.deleted == []
    assert session.committed is True


async def test_workspace_photo_routes_never_do_storage_io_inside_a_transaction(
    monkeypatch, allow_management
):
    bulk_session = WorkspaceSession(
        roster_rows=[
            roster_row(ROSTER_A, player_id=uuid4()),
            roster_row(ROSTER_B, player_id=uuid4(), first_name="Luis", last_name="Gómez"),
        ]
    )
    bulk_storage = WorkspaceStorage(session=bulk_session)
    installed: list[str] = []

    def assign_bulk_key(key: str) -> None:
        installed.append(key)
        bulk_session.roster_rows[len(installed) - 1]["photo_object_key"] = key

    bulk_storage.on_put = assign_bulk_key
    install_workspace_storage(monkeypatch, bulk_storage)
    install_roster_record(monkeypatch, bulk_session, roster_ids=(ROSTER_A, ROSTER_B))
    install_import(monkeypatch, with_photos=True)

    async with workspace_client(bulk_session) as client:
        bulk_response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
            data={"team_id": str(WORKSPACE_TEAM_ID)},
            files={
                "csv_file": ("roster.csv", b"", "text/csv"),
                "photos_zip": ("photos.zip", b"", "application/zip"),
            },
        )
    assert bulk_response.status_code == 201

    upload_session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    upload_storage = WorkspaceStorage(session=upload_session)
    upload_storage.on_put = lambda key: upload_session.roster_rows[0].update(
        photo_object_key=key
    )
    install_workspace_storage(monkeypatch, upload_storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    async with workspace_client(upload_session) as client:
        upload_response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo",
            files={"photo": ("photo.jpg", b"jpeg-bytes", "image/jpeg")},
        )
    assert upload_response.status_code == 200

    states = (
        bulk_storage.put_transaction_states
        + bulk_storage.signed_transaction_states
        + upload_storage.put_transaction_states
        + upload_storage.delete_transaction_states
        + upload_storage.signed_transaction_states
    )
    assert states
    assert not any(states)


def _no_db_writes(session) -> bool:
    return not any(
        sql.startswith(("INSERT INTO", "UPDATE ", "DELETE FROM"))
        for sql in session.statements
    )


async def _bulk_request(client, session):
    return await client.post(
        f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/bulk",
        data={"team_id": str(WORKSPACE_TEAM_ID)},
        files={
            "csv_file": ("roster.csv", b"", "text/csv"),
            "photos_zip": ("photos.zip", b"", "application/zip"),
        },
    )


def _bulk_session() -> WorkspaceSession:
    return WorkspaceSession(
        roster_rows=[
            roster_row(ROSTER_A, player_id=uuid4()),
            roster_row(ROSTER_B, player_id=uuid4(), first_name="Luis", last_name="Gómez"),
        ]
    )


def _assign_put_keys(session: WorkspaceSession):
    installed: list[str] = []

    def assign(key: str) -> None:
        installed.append(key)
        session.roster_rows[len(installed) - 1]["photo_object_key"] = key

    return assign


async def test_bulk_import_authorizes_before_uploading(monkeypatch):
    session = _bulk_session()
    storage = WorkspaceStorage(session=session)
    install_workspace_storage(monkeypatch, storage)
    install_import(monkeypatch, with_photos=True)

    async def deny(*args, **kwargs):
        raise PermissionError("La membresía no permite gestionar el torneo")

    monkeypatch.setattr(tournaments_router, "require_permission", deny)

    async with workspace_client(session) as client:
        response = await _bulk_request(client, session)

    assert response.status_code == 403
    assert storage.puts == []
    assert storage.put_transaction_states == []
    assert _no_db_writes(session)


async def test_bulk_import_compensates_uploaded_objects_on_cancellation(monkeypatch, allow_management):
    session = _bulk_session()
    storage = WorkspaceStorage(session=session)
    storage.on_put = _assign_put_keys(session)
    install_workspace_storage(monkeypatch, storage)
    install_import(monkeypatch, with_photos=True)

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(tournaments_router, "_create_roster_player_record", cancel)

    with pytest.raises(asyncio.CancelledError):
        await tournaments_router.create_roster_players_bulk(
            TOURNAMENT_ID,
            WORKSPACE_TEAM_ID,
            UploadFile(filename="roster.csv", file=io.BytesIO(b"")),
            UploadFile(filename="photos.zip", file=io.BytesIO(b"")),
            context=workspace_context(),
            db=session,
        )

    assert storage.puts
    assert storage.deleted == storage.puts
    assert storage.put_transaction_states == [False, False]
    assert storage.delete_transaction_states == [False, False]


async def test_bulk_import_compensates_when_the_write_fails(monkeypatch, allow_management):
    session = _bulk_session()
    storage = WorkspaceStorage(session=session)
    storage.on_put = _assign_put_keys(session)
    install_workspace_storage(monkeypatch, storage)
    install_import(monkeypatch, with_photos=True)

    async def fail(*args, **kwargs):
        raise IntegrityError(
            "INSERT INTO rosters (...) VALUES (...)",
            {},
            Exception("duplicate key value violates unique constraint"),
        )

    monkeypatch.setattr(tournaments_router, "_create_roster_player_record", fail)

    async with workspace_client(session) as client:
        response = await _bulk_request(client, session)

    assert response.status_code == 409
    assert session.rolled_back is True
    assert storage.put_transaction_states == [False, False]
    assert storage.deleted == storage.puts


async def test_upload_photo_revalidates_permission_before_writing(monkeypatch):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    storage = WorkspaceStorage(session=session)
    storage.on_put = lambda key: session.roster_rows[0].update(photo_object_key=key)
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )
    calls: list[str] = []

    async def permission(db, context, code, match_id=None, **kwargs):
        calls.append(code)
        if len(calls) == 2:
            raise PermissionError("La membresía ya no permite gestionar el torneo")

    monkeypatch.setattr(tournaments_router, "require_permission", permission)

    async with workspace_client(session) as client:
        response = await client.post(
            f"/api/v1/tournaments/{TOURNAMENT_ID}/rosters/{ROSTER_ID}/photo",
            files={"photo": ("photo.jpg", b"jpeg-bytes", "image/jpeg")},
        )

    assert response.status_code == 403
    assert calls == ["MANAGE_TOURNAMENTS", "MANAGE_TOURNAMENTS"]
    assert storage.puts
    assert storage.deleted == [storage.puts[0]]
    assert not any("set_roster_photo_object" in sql for sql in session.statements)
    assert session.rolled_back is True


async def test_upload_photo_compensates_the_new_object_on_cancellation(monkeypatch, allow_management):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    storage = WorkspaceStorage(session=session)
    storage.on_put = lambda key: session.roster_rows[0].update(photo_object_key=key)
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(tournaments_router, "_load_roster_player_row", cancel)

    with pytest.raises(asyncio.CancelledError):
        await tournaments_router.upload_roster_player_photo(
            TOURNAMENT_ID,
            ROSTER_ID,
            UploadFile(filename="photo.jpg", file=io.BytesIO(b"jpeg-bytes")),
            context=workspace_context(),
            db=session,
        )

    assert storage.puts
    assert storage.deleted == [storage.puts[0]]
    assert storage.delete_transaction_states == [False]


def _object_storage_without_clients(monkeypatch):
    settings = SimpleNamespace(
        storage_provider="s3",
        storage_signing_endpoint_url=None,
        storage_public_base_url="http://photos.example:9000/media",
        storage_endpoint_url="http://upload.example:9000",
        storage_bucket="media",
        storage_region="us-east-1",
        storage_access_key="key",
        storage_secret_key="secret",
        storage_presign_seconds=300,
    )
    monkeypatch.setattr(storage_module, "get_settings", lambda: settings)

    def fail_factory(endpoint):
        raise AssertionError(
            "no debe construirse un cliente para claves inválidas"
        )

    return ObjectStorage(client_factory=fail_factory)


async def test_invalid_object_keys_degrade_like_a_signing_failure(monkeypatch, caplog):
    storage = _object_storage_without_clients(monkeypatch)
    rows = [
        {"photo_object_key": "/absolute.jpg", "photo_consent": True},
        {"photo_object_key": "private/../escape.jpg", "photo_consent": True},
    ]

    with caplog.at_level(logging.WARNING, logger=PHOTOS_LOGGER):
        resolved = await sign_photo_rows(
            rows, key_field="photo_object_key", policy="null", storage=storage
        )

    assert [row["photo_url"] for row in resolved] == [None, None]
    assert len(resolver_records(caplog)) == 1

    with pytest.raises(HTTPException) as failure:
        await sign_photo_rows(
            [{"photo_object_key": "/absolute.jpg", "photo_consent": True}],
            key_field="photo_object_key",
            policy="error",
            storage=storage,
        )
    assert failure.value.status_code == 503


class BlockingPutStorage(WorkspaceStorage):
    """put_bytes that signals it started and then waits until cancelled."""

    def __init__(self, *, session):
        super().__init__(session=session)
        self.put_started = asyncio.Event()

    async def put_bytes(self, key, content, content_type):
        self.puts.append(key)
        self.put_transaction_states.append(self.session.in_transaction())
        self.put_started.set()
        await asyncio.Event().wait()
        return key  # pragma: no cover


async def test_real_task_cancellation_during_upload_compensates(
    monkeypatch, allow_management
):
    session = _bulk_session()
    storage = BlockingPutStorage(session=session)
    install_workspace_storage(monkeypatch, storage)
    install_import(monkeypatch, with_photos=True)

    task = asyncio.create_task(
        tournaments_router.create_roster_players_bulk(
            TOURNAMENT_ID,
            WORKSPACE_TEAM_ID,
            UploadFile(filename="roster.csv", file=io.BytesIO(b"")),
            UploadFile(filename="photos.zip", file=io.BytesIO(b"")),
            context=workspace_context(),
            db=session,
        )
    )
    await asyncio.wait_for(storage.put_started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # M1: the key was registered before the upload, so the cancellation
    # compensates the object that may have been written.
    assert storage.puts
    assert storage.deleted == [storage.puts[0]]
    assert storage.delete_transaction_states == [False]


async def test_bulk_import_does_not_delete_objects_when_cancelled_during_commit(
    monkeypatch, allow_management
):
    session = _bulk_session()
    session.cancel_commit_on_begin = 2
    storage = WorkspaceStorage(session=session)
    storage.on_put = _assign_put_keys(session)
    install_workspace_storage(monkeypatch, storage)
    install_roster_record(monkeypatch, session, roster_ids=(ROSTER_A, ROSTER_B))
    install_import(monkeypatch, with_photos=True)

    with pytest.raises(asyncio.CancelledError):
        await tournaments_router.create_roster_players_bulk(
            TOURNAMENT_ID,
            WORKSPACE_TEAM_ID,
            UploadFile(filename="roster.csv", file=io.BytesIO(b"")),
            UploadFile(filename="photos.zip", file=io.BytesIO(b"")),
            context=workspace_context(),
            db=session,
        )

    assert storage.puts
    # M2: success is marked before the commit, so a cancellation while
    # committing never deletes objects that may already be referenced.
    assert storage.deleted == []
    assert session.committed is True


async def test_upload_photo_keeps_both_objects_when_cancelled_during_commit(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
        cancel_commit_on_begin=2,
    )
    storage = WorkspaceStorage(session=session)
    storage.on_put = lambda key: session.roster_rows[0].update(photo_object_key=key)
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    with pytest.raises(asyncio.CancelledError):
        await tournaments_router.upload_roster_player_photo(
            TOURNAMENT_ID,
            ROSTER_ID,
            UploadFile(filename="photo.jpg", file=io.BytesIO(b"jpeg-bytes")),
            context=workspace_context(),
            db=session,
        )

    new_key = storage.puts[0]
    # The commit is ambiguous: keep both objects. The previous one may still be
    # referenced (commit failed) and the new one may already be (commit won).
    assert new_key not in storage.deleted
    assert storage.deleted == []


async def test_bulk_import_compensates_when_permission_is_revoked_in_the_write(
    monkeypatch,
):
    session = _bulk_session()
    storage = WorkspaceStorage(session=session)
    storage.on_put = _assign_put_keys(session)
    install_workspace_storage(monkeypatch, storage)
    install_import(monkeypatch, with_photos=True)
    calls: list[str] = []

    async def permission(db, context, code, match_id=None, **kwargs):
        calls.append(code)
        if len(calls) == 2:
            raise PermissionError("La membresía ya no permite gestionar el torneo")

    monkeypatch.setattr(tournaments_router, "require_permission", permission)

    async with workspace_client(session) as client:
        response = await _bulk_request(client, session)

    # M5: permission is checked again in the write transaction, after uploads.
    assert response.status_code == 403
    assert calls == ["MANAGE_TOURNAMENTS", "MANAGE_TOURNAMENTS"]
    assert storage.puts
    assert storage.deleted == storage.puts
    assert _no_db_writes(session)
    assert session.rolled_back is True


async def test_bulk_import_validates_the_team_before_uploading(
    monkeypatch, allow_management
):
    session = _bulk_session()
    session.team_registered = False
    storage = WorkspaceStorage(session=session)
    install_workspace_storage(monkeypatch, storage)
    install_import(monkeypatch, with_photos=True)

    async with workspace_client(session) as client:
        response = await _bulk_request(client, session)

    # M6: an unknown team answers 404 before any storage write.
    assert response.status_code == 404
    assert response.json() == {"detail": "El equipo no está registrado en el torneo"}
    assert storage.puts == []
    assert _no_db_writes(session)


class CancellingOldDeleteStorage(WorkspaceStorage):
    """Delete that is cancelled, to prove the cancellation is not swallowed."""

    async def delete_key(self, key):
        self.deleted.append(key)
        self.delete_transaction_states.append(self.session.in_transaction())
        raise asyncio.CancelledError()


async def test_upload_photo_keeps_the_previous_object_when_the_commit_fails(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
        fail_commit_on_begin=2,
    )
    storage = WorkspaceStorage(session=session)
    storage.on_put = lambda key: session.roster_rows[0].update(photo_object_key=key)
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await tournaments_router.upload_roster_player_photo(
            TOURNAMENT_ID,
            ROSTER_ID,
            UploadFile(filename="photo.jpg", file=io.BytesIO(b"jpeg-bytes")),
            context=workspace_context(),
            db=session,
        )

    # The row was rolled back, so it still references OLD_KEY: deleting it
    # would break the reference. The new object is the accepted orphan.
    assert storage.puts
    assert storage.deleted == []
    assert session.rolled_back is True
    assert session.committed is False


async def test_upload_photo_propagates_cancellation_while_deleting_the_previous_object(
    monkeypatch, allow_management
):
    session = WorkspaceSession(
        roster_lookup={
            "id": ROSTER_ID,
            "photo_consent": True,
            "photo_object_key": OLD_KEY,
        },
        set_photo_result=OLD_KEY,
        roster_rows=[roster_row(ROSTER_ID, photo_object_key=OLD_KEY)],
    )
    storage = CancellingOldDeleteStorage(session=session)
    storage.on_put = lambda key: session.roster_rows[0].update(photo_object_key=key)
    install_workspace_storage(monkeypatch, storage)
    monkeypatch.setattr(
        tournaments_router,
        "validate_photo_content",
        lambda raw, filename: PHOTO_FILE,
    )

    with pytest.raises(asyncio.CancelledError):
        await tournaments_router.upload_roster_player_photo(
            TOURNAMENT_ID,
            ROSTER_ID,
            UploadFile(filename="photo.jpg", file=io.BytesIO(b"jpeg-bytes")),
            context=workspace_context(),
            db=session,
        )

    # The cleanup was attempted and the cancellation was not swallowed.
    assert storage.deleted == [OLD_KEY]


async def test_bulk_import_keeps_orphans_when_the_commit_fails(
    monkeypatch, allow_management
):
    session = _bulk_session()
    session.fail_commit_on_begin = 2
    storage = WorkspaceStorage(session=session)
    storage.on_put = _assign_put_keys(session)
    install_workspace_storage(monkeypatch, storage)
    install_roster_record(monkeypatch, session, roster_ids=(ROSTER_A, ROSTER_B))
    install_import(monkeypatch, with_photos=True)

    with pytest.raises(RuntimeError, match="commit failed"):
        await tournaments_router.create_roster_players_bulk(
            TOURNAMENT_ID,
            WORKSPACE_TEAM_ID,
            UploadFile(filename="roster.csv", file=io.BytesIO(b"")),
            UploadFile(filename="photos.zip", file=io.BytesIO(b"")),
            context=workspace_context(),
            db=session,
        )

    # A failed commit leaves no rows but may leave the uploaded objects behind:
    # best-effort trade-off accepted for the bulk import.
    assert storage.puts
    assert storage.deleted == []
    assert session.rolled_back is True
    assert session.committed is False
