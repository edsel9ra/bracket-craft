"""Crest endpoints: route registration and the coded error contract (T10).

The three routes live under ``/api/v1/tournaments/{tournament_id}/teams/
{team_id}/crest`` with ``GET`` (200), ``POST`` (multipart ``file``, 200) and
``DELETE`` (204). The global handler of ``app/main.py`` answers every
``CrestError`` with the additive ``code`` next to the string ``detail``, whatever
its status, and keeps the ``Retry-After`` header when the exception carries one.

The tests use ``httpx.ASGITransport`` against the real application and replace
the auth/database dependencies and the service/storage functions, so no database
nor storage is needed. The full status/authorization catalog belongs to T11.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.storage import SignedUrls, StorageError
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.crests import router as crests_router_module
from app.modules.crests.errors import (
    CREST_ANIMATION_UNSUPPORTED,
    CREST_ERROR_DETAILS,
    CREST_FILE_EMPTY,
    CREST_FORBIDDEN,
    CREST_FORMAT_UNSUPPORTED,
    CREST_NOT_FOUND,
    CREST_STORAGE_UNAVAILABLE,
    CREST_TOO_LARGE,
    CREST_UPLOAD_FAILED,
    CrestError,
)
from app.modules.crests.service import EnrolledTeam
from app.modules.tournaments.schemas import TeamCrestResponse
from db_helpers import TenantContext, set_tenant_context

ORG = UUID("0d000000-0000-4000-8000-000000000001")
USER = UUID("0d000000-0000-4000-8000-000000000002")
MEMBER = UUID("0d000000-0000-4000-8000-000000000003")
TOURNAMENT = UUID("0d000000-0000-4000-8000-000000000010")
TEAM = UUID("0d000000-0000-4000-8000-000000000020")

CONTEXT = AuthContext(
    user_id=USER,
    organization_id=ORG,
    organization_user_id=MEMBER,
)
CREST_PATH = (
    "/api/v1/tournaments/{tournament_id}/teams/{team_id}/crest"
)
CREST_URL = f"/api/v1/tournaments/{TOURNAMENT}/teams/{TEAM}/crest"

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    + (13).to_bytes(4, "big")
    + b"IHDR"
    + b"\x00\x00\x00\x01" * 2
    + b"\x08\x06\x00\x00\x00"
    + b"\x00\x00\x00\x00"
    + (4).to_bytes(4, "big")
    + b"IDAT"
    + b"\x78\x9c\x03\x00"
    + b"\x00\x00\x00\x00"
    + (0).to_bytes(4, "big")
    + b"IEND"
    + b"\x00\x00\x00\x00"
)
GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff;"

CODED_STATUSES = (
    (CREST_FILE_EMPTY, 422),
    (CREST_FORMAT_UNSUPPORTED, 422),
    (CREST_ANIMATION_UNSUPPORTED, 422),
    (CREST_TOO_LARGE, 422),
    (CREST_NOT_FOUND, 404),
    (CREST_FORBIDDEN, 403),
    (CREST_STORAGE_UNAVAILABLE, 503),
    (CREST_UPLOAD_FAILED, 500),
)


class _FakeSession:
    """Placeholder session: every service call is replaced in these tests."""


async def _fake_db():
    yield _FakeSession()


@pytest.fixture
async def client():
    api.dependency_overrides[get_auth_context] = lambda: CONTEXT
    api.dependency_overrides[get_db] = _fake_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as value:
            yield value
    finally:
        api.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_crest_routes_are_registered_with_their_methods():
    schema = api.openapi()
    operations = schema["paths"][CREST_PATH]
    assert {"get", "post", "delete"} <= set(operations)
    # POST takes the multipart field ``file``; the other two take no body.
    assert "multipart/form-data" in operations["post"]["requestBody"]["content"]
    assert "requestBody" not in operations["get"]
    assert "requestBody" not in operations["delete"]
    # The router lives in its own module and the global handler is registered.
    assert crests_router_module.router.prefix == "/tournaments"
    assert CrestError in api.exception_handlers


# ---------------------------------------------------------------------------
# Coded error handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected_status"),
    CODED_STATUSES,
    ids=[code for code, _status in CODED_STATUSES],
)
async def test_coded_errors_keep_detail_and_add_the_code(code, expected_status):
    def raiser():
        raise CrestError(code)

    api.dependency_overrides[get_auth_context] = raiser
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.get(CREST_URL)
    finally:
        api.dependency_overrides.clear()

    assert response.status_code == expected_status
    body = response.json()
    assert set(body) == {"detail", "code"}
    assert body["code"] == code
    assert isinstance(body["detail"], str)
    assert body["detail"] == CREST_ERROR_DETAILS[code]


@pytest.mark.asyncio
async def test_coded_error_preserves_the_retry_after_header():
    def raiser():
        error = CrestError(CREST_STORAGE_UNAVAILABLE)
        error.headers = {"Retry-After": "30"}
        raise error

    api.dependency_overrides[get_auth_context] = raiser
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.get(CREST_URL)
    finally:
        api.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.json()["code"] == CREST_STORAGE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Wiring of the three operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_crest_signs_the_current_key_with_the_error_policy(
    client, monkeypatch
):
    calls: dict = {}

    async def fake_resolve(db, context, tournament_id, team_id, *, lock=False, require_management=True):
        calls["arguments"] = (context, tournament_id, team_id, lock, require_management)
        return EnrolledTeam(
            team_id=TEAM,
            crest_object_key="private/organizations/org/teams/team/crest.png",
            logo_url=None,
        )

    async def fake_sign(rows, *, policy, storage=None, logger=None):
        calls["policy"] = policy
        for row in rows:
            row.pop("crest_object_key", None)
            row["crest_url"] = "https://signed.test/crest.png"

    monkeypatch.setattr(crests_router_module, "resolve_enrolled_team", fake_resolve)
    monkeypatch.setattr(crests_router_module, "sign_crest_rows", fake_sign)

    response = await client.get(CREST_URL)

    assert response.status_code == 200
    assert response.json() == {
        "team_id": str(TEAM),
        "crest_url": "https://signed.test/crest.png",
        "logo_url": None,
    }
    # The read path does not require the management permission.
    assert calls["policy"] == "error"
    assert calls["arguments"] == (CONTEXT, TOURNAMENT, TEAM, False, False)


@pytest.mark.asyncio
async def test_post_crest_reads_the_file_and_delegates_to_the_service(
    client, monkeypatch
):
    captured: dict = {}

    def fake_storage():
        return object()

    async def fake_load(db, context, tournament_id, team_id, crest, *, storage, logger=None, enrolled=None):
        captured["crest"] = crest
        captured["arguments"] = (context, tournament_id, team_id)
        captured["enrolled"] = enrolled
        return TeamCrestResponse(
            team_id=TEAM, crest_url="https://signed.test/new.png", logo_url=None
        )

    monkeypatch.setattr(crests_router_module, "get_object_storage", fake_storage)
    monkeypatch.setattr(crests_router_module, "load_crest", fake_load)

    async def _db():
        yield ScriptedDatabase(team={"team_id": TEAM, "crest_object_key": None, "logo_url": None})

    api.dependency_overrides[get_db] = _db
    response = await client.post(
        CREST_URL,
        files={"file": ("escudo elegido.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "team_id": str(TEAM),
        "crest_url": "https://signed.test/new.png",
        "logo_url": None,
    }
    crest = captured["crest"]
    assert crest.content == PNG_BYTES
    assert crest.extension == ".png"
    assert crest.content_type == "image/png"
    assert captured["arguments"] == (CONTEXT, TOURNAMENT, TEAM)


@pytest.mark.asyncio
async def test_post_crest_rejects_unsupported_content_with_the_coded_error(
    client, monkeypatch
):
    called = {"load": 0}

    async def fake_load(*_args, **_kwargs):
        called["load"] += 1
        raise AssertionError("no debe llegar al servicio")

    monkeypatch.setattr(crests_router_module, "load_crest", fake_load)

    async def _db():
        yield ScriptedDatabase(team={"team_id": TEAM, "crest_object_key": None, "logo_url": None})

    api.dependency_overrides[get_db] = _db
    response = await client.post(
        CREST_URL,
        files={"file": ("escudo.png", GIF_BYTES, "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": CREST_ERROR_DETAILS[CREST_FORMAT_UNSUPPORTED],
        "code": CREST_FORMAT_UNSUPPORTED,
    }
    assert called["load"] == 0


@pytest.mark.asyncio
async def test_delete_crest_answers_204_without_a_body(client, monkeypatch):
    called: dict = {}

    def fake_storage():
        return object()

    async def fake_delete(db, context, tournament_id, team_id, storage, *, logger=None):
        called["arguments"] = (context, tournament_id, team_id)

    monkeypatch.setattr(crests_router_module, "get_object_storage", fake_storage)
    monkeypatch.setattr(crests_router_module, "delete_crest", fake_delete)

    response = await client.delete(CREST_URL)

    assert response.status_code == 204
    assert response.content == b""
    assert called["arguments"] == (CONTEXT, TOURNAMENT, TEAM)


# ---------------------------------------------------------------------------
# Authorization, isolation and the status catalog (T11)
# ---------------------------------------------------------------------------

ORG_OTHER = UUID("0d000000-0000-4000-8000-0000000000b1")
USER_OTHER = UUID("0d000000-0000-4000-8000-0000000000b2")
MEMBER_OTHER = UUID("0d000000-0000-4000-8000-0000000000b3")
TOURNAMENT_OTHER = UUID("0d000000-0000-4000-8000-0000000000b4")
TEAM_OTHER = UUID("0d000000-0000-4000-8000-0000000000b5")
OLD_KEY = "private/organizations/previous/teams/team/crest/previous.png"

#: PNG with an ``acTL`` chunk before ``IDAT``: animation declared.
APNG_BYTES = (
    PNG_BYTES[:8]
    + (13).to_bytes(4, "big")
    + b"IHDR"
    + b"\x00\x00\x00\x01" * 2
    + b"\x08\x06\x00\x00\x00"
    + b"\x00\x00\x00\x00"
    + (8).to_bytes(4, "big")
    + b"acTL"
    + b"\x00" * 8
    + b"\x00\x00\x00\x00"
    + (4).to_bytes(4, "big")
    + b"IDAT"
    + b"\x78\x9c\x03\x00"
    + b"\x00\x00\x00\x00"
    + (0).to_bytes(4, "big")
    + b"IEND"
    + b"\x00\x00\x00\x00"
)


class ScriptedResult:
    def __init__(self, row=None) -> None:
        self.row = row

    def scalar_one_or_none(self):
        return self.row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class ScriptedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False


class ScriptedDatabase:
    """Answers the context reads and applies the two writes of the service."""

    def __init__(self, *, tournament=True, permission=True, team=None):
        self.tournament = tournament
        self.permission = permission
        self.team = dict(team) if team is not None else None
        self.calls: list[tuple[str, dict]] = []
        self.writes: list[str] = []

    def begin(self):
        return ScriptedTransaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split()).replace("public.", "")
        self.calls.append((sql, dict(params or {})))
        if "set_config" in sql:
            return ScriptedResult()
        if "FROM tournaments" in sql:
            return ScriptedResult(1 if self.tournament else None)
        if "FROM roles" in sql:
            return ScriptedResult(1 if self.permission else None)
        if "FROM teams" in sql and "tournament_teams" in sql:
            return ScriptedResult(dict(self.team) if self.team else None)
        if sql.startswith("UPDATE teams"):
            self.writes.append(sql)
            if self.team is not None:
                if "crest_object_key" in params:
                    self.team["crest_object_key"] = params["crest_object_key"]
                    self.team["logo_url"] = None
                else:
                    self.team["crest_object_key"] = None
            return ScriptedResult()
        if sql.startswith("INSERT INTO administrative_audit_logs"):
            self.writes.append(sql)
            return ScriptedResult()
        raise AssertionError(f"consulta no esperada: {sql}")

    def statements(self, fragment: str) -> list[str]:
        return [sql for sql, _params in self.calls if fragment in sql]


class RecordingStorage:
    """Storage double: records uploads, deletes and one batch of signatures."""

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.delete_calls: list[str] = []
        self.signed_calls: list[tuple[str, ...]] = []

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> str:
        self.put_calls.append((key, content, content_type))
        return key

    async def delete_key(self, key: str) -> None:
        self.delete_calls.append(key)

    async def signed_urls(self, keys, expires_seconds=None):
        keys = tuple(keys)
        self.signed_calls.append(keys)
        return SignedUrls(urls={key: "https://signed.test/crest.png" for key in keys})


class NoStorage:
    """Storage double that fails the test if any method is used."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _forbidden(self, name: str):
        def called(*_args, **_kwargs):
            self.calls.append(name)
            raise AssertionError(f"no debe llamarse al almacenamiento: {name}")

        return called

    async def put_bytes(self, *args, **kwargs):
        return self._forbidden("put_bytes")(*args, **kwargs)

    async def delete_key(self, *args, **kwargs):
        return self._forbidden("delete_key")(*args, **kwargs)

    async def signed_urls(self, *args, **kwargs):
        return self._forbidden("signed_urls")(*args, **kwargs)


class FailingPutStorage(NoStorage):
    def __init__(self) -> None:
        super().__init__()
        self.put_attempts = 0

    async def put_bytes(self, *_args, **_kwargs):
        self.put_attempts += 1
        raise StorageError("bucket down at private/secret")


@asynccontextmanager
async def crest_client(monkeypatch, *, context=CONTEXT, db=None, storage=None):
    api.dependency_overrides[get_auth_context] = lambda: context

    async def _fake_db():
        yield db if db is not None else _FakeSession()

    api.dependency_overrides[get_db] = _fake_db
    if storage is not None:
        monkeypatch.setattr(
            crests_router_module, "get_object_storage", lambda: storage
        )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as value:
            yield value
    finally:
        api.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 403 without permission: no write, no storage, no audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_without_management_permission_the_write_is_rejected_without_effects(
    monkeypatch,
):
    database = ScriptedDatabase(permission=False, team={"team_id": TEAM, "crest_object_key": OLD_KEY, "logo_url": None})
    storage = NoStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        post = await client.post(
            CREST_URL, files={"file": ("escudo.png", PNG_BYTES, "image/png")}
        )
        delete = await client.delete(CREST_URL)

    for response in (post, delete):
        assert response.status_code == 403
        assert response.json() == {
            "detail": CREST_ERROR_DETAILS[CREST_FORBIDDEN],
            "code": CREST_FORBIDDEN,
        }
    assert database.writes == []
    assert database.statements("FROM teams") == []
    assert storage.calls == []


# ---------------------------------------------------------------------------
# 404: the three team misses are indistinguishable; the tournament keeps its own
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ("missing", "other_organization", "not_enrolled")
)
async def test_team_404_is_identical_for_the_three_misses(monkeypatch, reason):
    assert reason
    database = ScriptedDatabase(team=None)
    storage = NoStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        post = await client.post(
            CREST_URL, files={"file": ("escudo.png", PNG_BYTES, "image/png")}
        )
        delete = await client.delete(CREST_URL)

    for response in (post, delete):
        assert response.status_code == 404
        assert response.json() == {
            "detail": CREST_ERROR_DETAILS[CREST_NOT_FOUND],
            "code": CREST_NOT_FOUND,
        }
    assert database.writes == []
    assert storage.calls == []


@pytest.mark.asyncio
async def test_missing_tournament_answers_the_existing_404_before_the_permission(
    monkeypatch,
):
    database = ScriptedDatabase(tournament=False, permission=False)
    storage = NoStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo.png", PNG_BYTES, "image/png")}
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Torneo no encontrado"}
    assert database.statements("FROM roles") == []
    assert database.writes == []
    assert storage.calls == []


# ---------------------------------------------------------------------------
# 422: the four validation codes, before the service and the storage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "code", "settings"),
    [
        (b"", CREST_FILE_EMPTY, None),
        (GIF_BYTES, CREST_FORMAT_UNSUPPORTED, None),
        (APNG_BYTES, CREST_ANIMATION_UNSUPPORTED, None),
        (PNG_BYTES, CREST_TOO_LARGE, 16),
    ],
    ids=[
        CREST_FILE_EMPTY,
        CREST_FORMAT_UNSUPPORTED,
        CREST_ANIMATION_UNSUPPORTED,
        CREST_TOO_LARGE,
    ],
)
async def test_validation_codes_reject_the_upload_before_the_service(
    monkeypatch, content, code, settings
):
    called = {"load": 0}

    async def fake_load(*_args, **_kwargs):
        called["load"] += 1
        raise AssertionError("no debe llegar al servicio")

    def storage_factory():
        raise AssertionError("no debe crearse el almacenamiento")

    monkeypatch.setattr(crests_router_module, "load_crest", fake_load)
    monkeypatch.setattr(crests_router_module, "get_object_storage", storage_factory)
    if settings is not None:
        monkeypatch.setitem(
            crests_router_module.__dict__,
            "get_settings",
            lambda: SimpleNamespace(storage_max_image_bytes=settings),
        )

    async with crest_client(
        monkeypatch, db=ScriptedDatabase(team={"team_id": TEAM, "crest_object_key": None, "logo_url": None})
    ) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo.png", content, "image/png")}
        )

    assert response.status_code == 422
    assert response.json() == {"detail": CREST_ERROR_DETAILS[code], "code": code}
    assert called["load"] == 0


# ---------------------------------------------------------------------------
# 503 and 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_failure_answers_503_without_writing_or_deleting(monkeypatch):
    database = ScriptedDatabase(
        team={"team_id": TEAM, "crest_object_key": OLD_KEY, "logo_url": None}
    )
    storage = FailingPutStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo.png", PNG_BYTES, "image/png")}
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": CREST_ERROR_DETAILS[CREST_STORAGE_UNAVAILABLE],
        "code": CREST_STORAGE_UNAVAILABLE,
    }
    assert storage.put_attempts == 1
    assert database.writes == []
    assert database.team["crest_object_key"] == OLD_KEY
    assert storage.calls == []  # no delete of the previous file


@pytest.mark.asyncio
async def test_unclassified_failure_answers_500_with_upload_failed(monkeypatch):
    storage = NoStorage()

    async def broken_load(*_args, **_kwargs):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(crests_router_module, "load_crest", broken_load)

    async with crest_client(
        monkeypatch, db=ScriptedDatabase(team={"team_id": TEAM, "crest_object_key": None, "logo_url": None}), storage=storage
    ) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo.png", PNG_BYTES, "image/png")}
        )

    assert response.status_code == 500
    assert response.json() == {
        "detail": CREST_ERROR_DETAILS[CREST_UPLOAD_FAILED],
        "code": CREST_UPLOAD_FAILED,
    }
    assert storage.calls == []


# ---------------------------------------------------------------------------
# 200 without the internal key; 204 idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_answers_the_contract_without_the_internal_key(monkeypatch):
    database = ScriptedDatabase(
        team={"team_id": TEAM, "crest_object_key": None, "logo_url": "https://old.test/logo.png"}
    )
    storage = RecordingStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo elegido.png", PNG_BYTES, "image/png")}
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"team_id", "crest_url", "logo_url"}
    assert body["team_id"] == str(TEAM)
    assert body["crest_url"] == "https://signed.test/crest.png"
    assert body["logo_url"] is None
    assert "crest_object_key" not in response.text
    assert "private/" not in response.text
    assert database.team["crest_object_key"] is not None
    assert database.team["logo_url"] is None
    assert len(storage.put_calls) == 1
    assert [sql.split()[0] for sql in database.writes] == ["UPDATE", "INSERT"]


@pytest.mark.asyncio
async def test_delete_is_idempotent_and_only_the_first_call_has_effects(monkeypatch):
    database = ScriptedDatabase(
        team={"team_id": TEAM, "crest_object_key": OLD_KEY, "logo_url": None}
    )
    storage = RecordingStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        first = await client.delete(CREST_URL)
        second = await client.delete(CREST_URL)

    assert first.status_code == 204 and first.content == b""
    assert second.status_code == 204 and second.content == b""
    assert database.team["crest_object_key"] is None
    # One UPDATE and one audit INSERT in total.
    assert [sql.split()[0] for sql in database.writes] == ["UPDATE", "INSERT"]
    assert storage.delete_calls == [OLD_KEY]
    assert storage.put_calls == []


# ---------------------------------------------------------------------------
# Origin: the CSRF middleware rejects before the handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_foreign_origin_is_rejected_before_the_handler(monkeypatch):
    called = {"load": 0, "storage": 0}

    async def fake_load(*_args, **_kwargs):
        called["load"] += 1
        raise AssertionError("el manejador no debe ejecutarse")

    def storage_factory():
        called["storage"] += 1
        return NoStorage()

    monkeypatch.setattr(crests_router_module, "load_crest", fake_load)
    monkeypatch.setattr(crests_router_module, "get_object_storage", storage_factory)

    async with crest_client(monkeypatch, db=ScriptedDatabase()) as client:
        response = await client.post(
            CREST_URL,
            files={"file": ("escudo.png", PNG_BYTES, "image/png")},
            headers={"Origin": "http://evil.test"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Origen no permitido"}
    assert called == {"load": 0, "storage": 0}


# ---------------------------------------------------------------------------
# Real PostgreSQL (opt-in): permissions and isolation through the endpoint
# ---------------------------------------------------------------------------


class SavepointSession:
    """Run the service transactions as savepoints of the fixture transaction."""

    def __init__(self, session) -> None:
        self._session = session

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)


@asynccontextmanager
async def db_crest_client(monkeypatch, *, session, context, storage):
    api.dependency_overrides[get_auth_context] = lambda: context

    async def _fake_db():
        yield SavepointSession(session)

    api.dependency_overrides[get_db] = _fake_db
    monkeypatch.setattr(crests_router_module, "get_object_storage", lambda: storage)
    # GET signs through the resolver, which resolves its own storage client.
    monkeypatch.setattr(
        "app.modules.crests.resolver.get_object_storage", lambda: storage
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as value:
            yield value
    finally:
        api.dependency_overrides.clear()


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


async def seed_enrolled_team(session, tenant, *, crest=None, logo=None):
    await set_tenant_context(session, tenant)
    tournament_id = uuid4()
    team_id = uuid4()
    suffix = team_id.hex[:8].upper()
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
            "name": f"Crest Endpoint Cup {suffix}",
        },
    )
    await session.execute(
        text("""
            INSERT INTO teams
                (id, organization_id, name, short_code, logo_url, crest_object_key)
            VALUES (:id, :organization_id, :name, :short_code, :logo, :crest)
        """),
        {
            "id": str(team_id),
            "organization_id": str(tenant.organization_id),
            "name": f"Crest Endpoint Team {suffix}",
            "short_code": f"E{suffix[:4]}",
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
    return tournament_id, team_id


async def seed_member(session, tenant, role_code: str) -> AuthContext:
    await set_tenant_context(session, tenant)
    suffix = uuid4().hex
    user_id = (
        await session.execute(
            text("""
                INSERT INTO users (email, password_hash, full_name)
                VALUES (:email, 'hash', :full_name)
                RETURNING id
            """),
            {
                "email": f"endpoint-{role_code}-{suffix}@example.test",
                "full_name": f"Endpoint {role_code}",
            },
        )
    ).scalar_one()
    member_id = (
        await session.execute(
            text("""
                INSERT INTO organization_users (organization_id, user_id, is_active)
                VALUES (:organization_id, :user_id, TRUE)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "user_id": str(user_id),
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO roles (organization_id, role_definition_id, name, permissions)
            SELECT :organization_id, rd.id, rd.name, rd.system_permissions
            FROM role_definitions rd
            WHERE rd.code = :role_code
            ON CONFLICT (organization_id, name) DO UPDATE
                SET role_definition_id = EXCLUDED.role_definition_id,
                    permissions = EXCLUDED.permissions
        """),
        {
            "organization_id": str(tenant.organization_id),
            "role_code": role_code,
        },
    )
    await session.execute(
        text("""
            INSERT INTO organization_user_roles
                (organization_id, organization_user_id, role_id)
            SELECT :organization_id, :member_id, r.id
            FROM roles r
            JOIN role_definitions rd ON rd.id = r.role_definition_id
            WHERE r.organization_id = :organization_id
              AND rd.code = :role_code
            ON CONFLICT DO NOTHING
        """),
        {
            "organization_id": str(tenant.organization_id),
            "member_id": str(member_id),
            "role_code": role_code,
        },
    )
    return AuthContext(
        user_id=user_id,
        organization_id=tenant.organization_id,
        organization_user_id=member_id,
    )


async def stored_crest(session, tenant, team_id) -> dict:
    await set_tenant_context(session, tenant)
    return dict(
        (
            await session.execute(
                text(
                    "SELECT crest_object_key, logo_url FROM teams WHERE id = :team_id"
                ),
                {"team_id": str(team_id)},
            )
        )
        .mappings()
        .one()
    )


async def team_audits(session, tenant, team_id) -> list[dict]:
    await set_tenant_context(session, tenant)
    rows = (
        await session.execute(
            text("""
                SELECT action, payload
                FROM administrative_audit_logs
                WHERE entity_id = :team_id
                ORDER BY performed_at, action
            """),
            {"team_id": str(team_id)},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_viewer_can_read_but_cannot_write_the_crest(
    db_session, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Crest Endpoint Viewer Owner")
    viewer = await seed_member(db_session, tenant, "viewer")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    storage = RecordingStorage()
    url = f"/api/v1/tournaments/{tournament_id}/teams/{team_id}/crest"

    async with db_crest_client(
        monkeypatch, session=db_session, context=viewer, storage=storage
    ) as client:
        read = await client.get(url)
        # C-1: the permission (403) decides before the invalid file (422).
        post = await client.post(
            url, files={"file": ("escudo.png", GIF_BYTES, "image/png")}
        )
        delete = await client.delete(url)

    assert read.status_code == 200
    assert set(read.json()) == {"team_id", "crest_url", "logo_url"}
    assert "crest_object_key" not in read.text
    assert read.json()["crest_url"] == "https://signed.test/crest.png"
    for response in (post, delete):
        assert response.status_code == 403
        assert response.json() == {
            "detail": CREST_ERROR_DETAILS[CREST_FORBIDDEN],
            "code": CREST_FORBIDDEN,
        }

    stored = await stored_crest(db_session, tenant, team_id)
    assert stored["crest_object_key"] == OLD_KEY
    assert storage.put_calls == []
    assert storage.delete_calls == []
    assert await team_audits(db_session, tenant, team_id) == []


@pytest.mark.asyncio
async def test_isolated_404_is_identical_for_foreign_and_unenrolled_teams(
    db_session, tenant_factory, monkeypatch
):
    owner = await tenant_factory("Crest Endpoint Isolation A")
    other = await tenant_factory("Crest Endpoint Isolation B")
    tournament_id, enrolled_team = await seed_enrolled_team(db_session, owner)
    _, unenrolled_team = await seed_enrolled_team(db_session, owner)
    other_tournament, other_team = await seed_enrolled_team(
        db_session, other, crest=OLD_KEY
    )
    missing_team = uuid4()
    storage = NoStorage()
    base = f"/api/v1/tournaments/{tournament_id}/teams"

    async with db_crest_client(
        monkeypatch, session=db_session, context=context_for(owner), storage=storage
    ) as client:
        answers = []
        for team_id in (missing_team, other_team, unenrolled_team):
            response = await client.post(
                f"{base}/{team_id}/crest",
                files={"file": ("escudo.png", PNG_BYTES, "image/png")},
            )
            answers.append((response.status_code, response.json()))
        delete = await client.delete(f"{base}/{missing_team}/crest")
        foreign_tournament = await client.post(
            f"/api/v1/tournaments/{other_tournament}/teams/{other_team}/crest",
            files={"file": ("escudo.png", PNG_BYTES, "image/png")},
        )

    expected = {
        "detail": CREST_ERROR_DETAILS[CREST_NOT_FOUND],
        "code": CREST_NOT_FOUND,
    }
    assert answers == [(404, expected)] * 3
    assert delete.status_code == 404
    assert delete.json() == expected
    assert foreign_tournament.status_code == 404
    assert foreign_tournament.json() == {"detail": "Torneo no encontrado"}

    # The foreign team keeps its image and nothing is written anywhere.
    assert (await stored_crest(db_session, other, other_team))[
        "crest_object_key"
    ] == OLD_KEY
    assert (await stored_crest(db_session, owner, enrolled_team))[
        "crest_object_key"
    ] is None
    assert await team_audits(db_session, owner, enrolled_team) == []
    assert storage.calls == []


@pytest.mark.asyncio
async def test_owner_upload_and_delete_run_the_real_service(
    db_session, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Crest Endpoint Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=None, logo="https://old.test/logo.png"
    )
    storage = RecordingStorage()
    url = f"/api/v1/tournaments/{tournament_id}/teams/{team_id}/crest"

    async with db_crest_client(
        monkeypatch, session=db_session, context=context_for(tenant), storage=storage
    ) as client:
        upload = await client.post(
            url, files={"file": ("escudo elegido.png", PNG_BYTES, "image/png")}
        )
        remove = await client.delete(url)

    assert upload.status_code == 200
    assert set(upload.json()) == {"team_id", "crest_url", "logo_url"}
    assert "crest_object_key" not in upload.text
    assert "private/" not in upload.text
    assert remove.status_code == 204 and remove.content == b""

    stored = await stored_crest(db_session, tenant, team_id)
    assert stored["crest_object_key"] is None  # the second call removed it
    assert stored["logo_url"] is None  # never restored
    assert sorted(
        row["action"] for row in await team_audits(db_session, tenant, team_id)
    ) == ["REMOVE_TEAM_CREST", "SET_TEAM_CREST"]
    assert len(storage.put_calls) == 1
    assert storage.delete_calls == [storage.put_calls[0][0]]


# ---------------------------------------------------------------------------
# Guard order (C-1): authorization decides before the file is read or validated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("database", "expected_status", "expected_body"),
    [
        (
            lambda: ScriptedDatabase(permission=False),
            403,
            {"detail": CREST_ERROR_DETAILS[CREST_FORBIDDEN], "code": CREST_FORBIDDEN},
        ),
        (
            lambda: ScriptedDatabase(tournament=False),
            404,
            {"detail": "Torneo no encontrado"},
        ),
        (
            lambda: ScriptedDatabase(team=None),
            404,
            {"detail": CREST_ERROR_DETAILS[CREST_NOT_FOUND], "code": CREST_NOT_FOUND},
        ),
    ],
    ids=["without-permission", "missing-tournament", "missing-team"],
)
async def test_guards_precede_file_validation(
    monkeypatch, database, expected_status, expected_body
):
    scripted = database()
    storage = NoStorage()

    async with crest_client(monkeypatch, db=scripted, storage=storage) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo.png", GIF_BYTES, "image/png")}
        )

    assert response.status_code == expected_status
    assert response.json() == expected_body
    # The invalid file is never read nor sent to the storage, and nothing is written.
    assert storage.calls == []
    assert scripted.writes == []
    if expected_status == 403:
        assert scripted.statements("FROM teams") == []


@pytest.mark.asyncio
async def test_an_authorized_member_gets_422_for_an_invalid_file(monkeypatch):
    database = ScriptedDatabase(
        team={"team_id": TEAM, "crest_object_key": None, "logo_url": None}
    )
    storage = NoStorage()

    async with crest_client(monkeypatch, db=database, storage=storage) as client:
        response = await client.post(
            CREST_URL, files={"file": ("escudo.png", GIF_BYTES, "image/png")}
        )

    assert response.status_code == 422
    assert response.json()["code"] == CREST_FORMAT_UNSUPPORTED
    assert storage.calls == []
    assert database.writes == []
