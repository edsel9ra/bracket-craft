"""Crest operation context and upload outside the transaction (T6).

``resolve_enrolled_team`` fixes the RLS context before any tenant query, checks
the tournament and the enrollment (never distinguishing why the team is not
reachable), and returns the current crest key and the legacy ``logo_url``. The
management permission is checked by ``require_crest_management`` (403
``CREST_FORBIDDEN``) and can be skipped for the read path, where the endpoint
only requires an active membership.

``store_crest_object`` builds the private key from the detected extension and
uploads the admitted content with its detected ``Content-Type``; it never
receives a session, so it cannot open a transaction, and a storage failure is
translated to 503 ``CREST_STORAGE_UNAVAILABLE`` without any other write. A file
name is never an input.

The tests use a scripted database and a fake storage: no real database is
needed. The real PostgreSQL behaviour (RLS, FK, concurrency) belongs to the
opt-in suite of the later tasks.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import secrets
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.storage import SignedUrls, StorageError
from app.core.tenancy import AuthContext
from app.modules.crests.errors import (
    CREST_FORBIDDEN,
    CREST_NOT_FOUND,
    CREST_STORAGE_UNAVAILABLE,
    CrestError,
)
from app.modules.crests.service import (
    EnrolledTeam,
    delete_crest,
    load_crest,
    require_crest_management,
    resolve_enrolled_team,
    store_crest_object,
)
from app.modules.crests.validation import crest_object_key, validate_crest_content
from app.modules.tournaments.schemas import TeamCrestResponse
from db_helpers import TenantContext, set_tenant_context
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)

URL_BASE = "https://signed.test/"
LOGGER_NAME = "tests.crest_service"

ORG = UUID("0c000000-0000-4000-8000-000000000001")
USER = UUID("0c000000-0000-4000-8000-000000000002")
MEMBER = UUID("0c000000-0000-4000-8000-000000000003")
TOURNAMENT = UUID("0c000000-0000-4000-8000-000000000010")
TEAM = UUID("0c000000-0000-4000-8000-000000000020")

CONTEXT = AuthContext(
    user_id=USER,
    organization_id=ORG,
    organization_user_id=MEMBER,
)

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

EXISTING_KEY = (
    "private/organizations/previous/teams/team/crest/previous.png"
)
EXISTING_LOGO = "https://crest.example.test/previous.png"


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        return False


class FakeResult:
    def __init__(self, row=None) -> None:
        self.row = row

    def scalar_one_or_none(self):
        return self.row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def all(self):
        return [] if self.row is None else [self.row]


class ScriptedDatabase:
    """Answers the reads of the context resolution, in order and on demand."""

    def __init__(self, *, tournament: bool = True, permission: bool = True, team=None):
        self.tournament = tournament
        self.permission = permission
        self.team = team
        self.calls: list[tuple[str, dict]] = []
        self.transactions = 0

    def begin(self):
        self.transactions += 1
        return FakeTransaction()

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split()).replace("public.", "")
        self.calls.append((sql, dict(params or {})))
        if "set_config" in sql:
            return FakeResult()
        if "FROM tournaments" in sql:
            return FakeResult(1 if self.tournament else None)
        if "FROM roles" in sql:
            return FakeResult(1 if self.permission else None)
        if "FROM teams" in sql and "tournament_teams" in sql:
            return FakeResult(self.team)
        raise AssertionError(f"consulta no esperada: {sql}")

    def sql_matching(self, fragment: str) -> list[tuple[str, dict]]:
        return [call for call in self.calls if fragment in call[0]]


def team_row(
    *, crest_object_key: str | None = EXISTING_KEY, logo_url: str | None = EXISTING_LOGO
) -> dict:
    return {
        "team_id": TEAM,
        "crest_object_key": crest_object_key,
        "logo_url": logo_url,
    }


class FakeStorage:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        on_put=None,
        on_delete=None,
        delete_error: Exception | None = None,
    ) -> None:
        self.error = error
        self.on_put = on_put
        self.on_delete = on_delete
        self.delete_error = delete_error
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.delete_calls: list[str] = []

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> str:
        self.put_calls.append((key, content, content_type))
        if self.on_put is not None:
            self.on_put()
        if self.error is not None:
            raise self.error
        return key

    async def delete_key(self, key: str) -> None:
        self.delete_calls.append(key)
        if self.on_delete is not None:
            self.on_delete(key)
        if self.delete_error is not None:
            raise self.delete_error

    async def signed_urls(self, keys, expires_seconds=None):
        keys = tuple(keys)
        return SignedUrls(urls={key: f"{URL_BASE}{key}" for key in keys})


# ---------------------------------------------------------------------------
# Context resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_context_sets_rls_before_any_tenant_query():
    database = ScriptedDatabase(team=team_row())

    await resolve_enrolled_team(database, CONTEXT, TOURNAMENT, TEAM)

    assert database.transactions == 1
    assert len(database.calls) >= 4
    first_sql, first_params = database.calls[0]
    second_sql, second_params = database.calls[1]
    assert "app.current_organization_id" in first_sql
    assert first_params["value"] == str(ORG)
    assert "app.current_user_id" in second_sql
    assert second_params["value"] == str(USER)

    # The first tenant read comes after both GUCs are fixed.
    first_tenant = next(
        index
        for index, (sql, _params) in enumerate(database.calls)
        if "FROM tournaments" in sql or "FROM roles" in sql or "FROM teams" in sql
    )
    assert first_tenant >= 2


@pytest.mark.asyncio
async def test_resolve_context_returns_the_current_crest_and_logo():
    database = ScriptedDatabase(team=team_row())

    resolved = await resolve_enrolled_team(database, CONTEXT, TOURNAMENT, TEAM)

    assert resolved == EnrolledTeam(
        team_id=TEAM,
        crest_object_key=EXISTING_KEY,
        logo_url=EXISTING_LOGO,
    )

    team_sql, team_params = database.sql_matching("FROM teams")[0]
    # Defense in depth: organization and enrollment are part of the query.
    assert "tt.team_id = t.id" in team_sql
    assert "tt.organization_id = t.organization_id" in team_sql
    assert "t.organization_id = :organization_id" in team_sql
    assert "tt.tournament_id = :tournament_id" in team_sql
    assert team_params["organization_id"] == str(ORG)
    assert team_params["tournament_id"] == str(TOURNAMENT)
    assert team_params["team_id"] == str(TEAM)


@pytest.mark.asyncio
async def test_resolve_context_uses_the_existing_404_when_the_tournament_is_missing():
    database = ScriptedDatabase(tournament=False)

    with pytest.raises(HTTPException) as error:
        await resolve_enrolled_team(database, CONTEXT, TOURNAMENT, TEAM)

    assert error.value.status_code == 404
    assert error.value.detail == "Torneo no encontrado"
    # Nothing else is read: no permission query and no team query.
    assert database.sql_matching("FROM roles") == []
    assert database.sql_matching("FROM teams") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    ("missing", "other_organization", "not_enrolled"),
)
async def test_resolve_context_is_identical_for_the_three_team_misses(reason):
    # All three cases reach the same query (which filters by organization and by
    # enrollment) and return no row, so the answer cannot reveal the motive.
    database = ScriptedDatabase(team=None)

    with pytest.raises(CrestError) as error:
        await resolve_enrolled_team(database, CONTEXT, TOURNAMENT, TEAM)

    assert reason  # documents the case the parametrization represents
    assert error.value.code == CREST_NOT_FOUND
    assert error.value.status_code == 404
    assert isinstance(error.value.detail, str)
    assert error.value.detail == "El equipo no fue encontrado"
    assert database.transactions == 1


@pytest.mark.asyncio
async def test_resolve_context_requires_the_management_permission():
    database = ScriptedDatabase(permission=False)

    with pytest.raises(CrestError) as error:
        await resolve_enrolled_team(database, CONTEXT, TOURNAMENT, TEAM)

    assert error.value.code == CREST_FORBIDDEN
    assert error.value.status_code == 403
    assert isinstance(error.value.detail, str)
    # The team is never resolved without the permission.
    assert database.sql_matching("FROM teams") == []
    permission_sql, permission_params = database.sql_matching("FROM roles")[0]
    assert permission_params["organization_id"] == str(ORG)
    assert permission_params["organization_user_id"] == str(MEMBER)
    assert "MANAGE_TOURNAMENTS" in permission_params["permission"]


@pytest.mark.asyncio
async def test_resolve_context_can_skip_management_for_the_read_path():
    database = ScriptedDatabase(permission=False, team=team_row())

    resolved = await resolve_enrolled_team(
        database, CONTEXT, TOURNAMENT, TEAM, require_management=False
    )

    assert resolved.team_id == TEAM
    assert database.sql_matching("FROM roles") == []


@pytest.mark.asyncio
async def test_resolve_context_locks_the_team_only_when_the_caller_owns_the_transaction():
    locked_database = ScriptedDatabase(team=team_row())

    await resolve_enrolled_team(
        locked_database, CONTEXT, TOURNAMENT, TEAM, lock=True
    )

    # With ``lock=True`` the caller holds the write transaction: the function
    # must not open a second one.
    assert locked_database.transactions == 0
    assert "FOR UPDATE OF t" in locked_database.sql_matching("FROM teams")[0][0]

    read_database = ScriptedDatabase(team=team_row())
    await resolve_enrolled_team(read_database, CONTEXT, TOURNAMENT, TEAM)
    assert read_database.transactions == 1
    assert "FOR UPDATE" not in read_database.sql_matching("FROM teams")[0][0]


@pytest.mark.asyncio
async def test_require_crest_management_translates_the_permission_error():
    allowed = ScriptedDatabase(permission=True)
    await require_crest_management(allowed, CONTEXT)
    assert allowed.sql_matching("FROM roles")

    denied = ScriptedDatabase(permission=False)
    with pytest.raises(CrestError) as error:
        await require_crest_management(denied, CONTEXT)
    assert error.value.code == CREST_FORBIDDEN
    assert error.value.status_code == 403


# ---------------------------------------------------------------------------
# Upload outside the transaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_crest_object_uploads_with_the_detected_type_and_key():
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)
    assert (crest.extension, crest.content_type) == (".png", "image/png")
    storage = FakeStorage()

    key = await store_crest_object(
        storage,
        crest,
        organization_id=ORG,
        tournament_id=TOURNAMENT,
        team_id=TEAM,
    )

    assert key.startswith(
        f"private/organizations/{ORG}/tournaments/{TOURNAMENT}/teams/{TEAM}/"
    )
    assert key.endswith(".png")
    assert key.count(".") == 1
    assert " " not in key
    assert key == crest_object_key(
        ORG, TOURNAMENT, TEAM, crest.extension, token=key.rsplit("/", 1)[1][:-4]
    )

    assert storage.put_calls == [(key, crest.content, "image/png")]
    # No original file name is ever part of the key.
    for chosen in ("escudo final.png", "Escudo.PNG", "logo.php"):
        assert chosen not in key


@pytest.mark.asyncio
async def test_store_crest_object_maps_an_upload_failure_to_unavailable():
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)
    storage = FakeStorage(error=StorageError("bucket down at private/secret"))

    with pytest.raises(CrestError) as error:
        await store_crest_object(
            storage,
            crest,
            organization_id=ORG,
            tournament_id=TOURNAMENT,
            team_id=TEAM,
        )

    assert error.value.code == CREST_STORAGE_UNAVAILABLE
    assert error.value.status_code == 503
    assert "bucket down" not in str(error.value.detail)
    assert "private/secret" not in str(error.value.detail)

    # Exactly one upload attempt and nothing else: no delete, no second write.
    assert len(storage.put_calls) == 1
    key = storage.put_calls[0][0]
    assert key.startswith("private/organizations/")


@pytest.mark.asyncio
async def test_store_crest_object_upload_runs_without_an_open_transaction():
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)
    session = AsyncSession()
    observations: list[bool] = []
    storage = FakeStorage(on_put=lambda: observations.append(session.in_transaction()))
    try:
        await store_crest_object(
            storage,
            crest,
            organization_id=ORG,
            tournament_id=TOURNAMENT,
            team_id=TEAM,
        )
    finally:
        await session.close()

    assert observations == [False]
    # The function cannot receive a session: the caller uploads after closing
    # its read transaction (N-2).
    parameters = set(inspect.signature(store_crest_object).parameters)
    assert parameters.isdisjoint({"db", "session", "database", "connection"})


def test_store_crest_object_upload_never_accepts_a_file_name():
    parameters = inspect.signature(store_crest_object).parameters
    assert list(parameters) == ["storage", "crest", "organization_id", "tournament_id", "team_id"]
    assert "filename" not in parameters
    assert "file_name" not in parameters


# ---------------------------------------------------------------------------
# Load/replace with a real database (opt-in) and a fake storage
# ---------------------------------------------------------------------------

OLD_KEY = "private/organizations/previous/teams/old-team/crest/previous.webp"
OLD_LOGO = "https://crest.example.test/previous.png"


def auth_context(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


class TrackedTransaction:
    """Delegates the ``async with db.begin()`` and counts its outcome."""

    def __init__(self, transaction, state: dict) -> None:
        self._transaction = transaction
        self._state = state

    async def __aenter__(self):
        return await self._transaction.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        result = await self._transaction.__aexit__(exc_type, exc, traceback)
        if exc_type is None:
            self._state["commits"] += 1
        else:
            self._state["rollbacks"] += 1
        return result


def track_transactions(session: AsyncSession) -> dict:
    """Run the service ``async with db.begin()`` as a savepoint of the test.

    The route/service keeps its transaction contract, the statements land in the
    fixture transaction and the fixture rollback removes everything (the same
    ``_NestedSession`` pattern the roster and match-operation suites use).
    ``commits`` counts the savepoints released, so the tests can prove the
    previous object is deleted only after the write transaction confirmed.
    """

    state = {"begins": 0, "commits": 0, "rollbacks": 0}

    def begin():
        state["begins"] += 1
        return TrackedTransaction(session.begin_nested(), state)

    session.begin = begin  # type: ignore[method-assign]
    return state


async def seed_enrolled_team(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    crest: str | None = None,
    logo: str | None = None,
) -> tuple[UUID, UUID]:
    """Create a draft tournament, a team and its enrollment inside the tenant."""

    await set_tenant_context(session, tenant)
    tournament_id = uuid4()
    team_id = uuid4()
    suffix = team_id.hex[:8].upper()

    await session.execute(
        text("""
            INSERT INTO tournaments
                (id, organization_id, name, season, start_date, status,
                 current_draft_config)
            VALUES
                (:id, :organization_id, :name, '2026', CAST('2026-01-01' AS DATE),
                 'draft', '{}'::jsonb)
        """),
        {
            "id": str(tournament_id),
            "organization_id": str(tenant.organization_id),
            "name": f"Crest Cup {suffix}",
        },
    )
    await session.execute(
        text("""
            INSERT INTO teams
                (id, organization_id, name, short_code, logo_url, crest_object_key)
            VALUES
                (:id, :organization_id, :name, :short_code, :logo_url, :crest)
        """),
        {
            "id": str(team_id),
            "organization_id": str(tenant.organization_id),
            "name": f"Crest Team {suffix}",
            "short_code": f"C{suffix[:4]}",
            "logo_url": logo,
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


async def team_crest(session: AsyncSession, team_id: UUID) -> dict:
    row = (
        await session.execute(
            text(
                "SELECT crest_object_key, logo_url FROM teams WHERE id = :team_id"
            ),
            {"team_id": str(team_id)},
        )
    ).mappings().one()
    return dict(row)


async def group_audits(session: AsyncSession, team_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            text("""
                SELECT action, entity_type, entity_id, payload,
                       performed_by_member_id
                FROM administrative_audit_logs
                WHERE entity_id = :team_id
                ORDER BY performed_at, action
            """),
            {"team_id": str(team_id)},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@pytest.mark.asyncio
async def test_load_crest_removes_logo_url_and_audits_the_first_upload(
    db_session, tenant_factory, caplog
):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    tenant = await tenant_factory("Crest Load Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, logo=OLD_LOGO
    )
    state = track_transactions(db_session)
    storage = FakeStorage()
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    response = await load_crest(
        db_session,
        auth_context(tenant),
        tournament_id,
        team_id,
        crest,
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    stored = await team_crest(db_session, team_id)
    new_key = stored["crest_object_key"]
    assert new_key.startswith(
        f"private/organizations/{tenant.organization_id}"
        f"/tournaments/{tournament_id}/teams/{team_id}/"
    )
    assert new_key.endswith(".png")
    assert storage.put_calls == [(new_key, crest.content, "image/png")]
    # RF-5: the first confirmed upload retires the legacy external URL.
    assert stored["logo_url"] is None
    assert isinstance(response, TeamCrestResponse)
    assert response.team_id == team_id
    assert response.crest_url == f"{URL_BASE}{new_key}"
    assert response.logo_url is None
    assert storage.delete_calls == []
    # Read transaction + write transaction, both confirmed.
    assert state == {"begins": 2, "commits": 2, "rollbacks": 0}

    audits = await group_audits(db_session, team_id)
    assert len(audits) == 1
    assert audits[0]["action"] == "SET_TEAM_CREST"
    assert audits[0]["entity_type"] == "teams"
    assert audits[0]["entity_id"] == team_id
    assert audits[0]["payload"] == {"tournament_id": str(tournament_id)}
    assert audits[0]["performed_by_member_id"] == tenant.member_id
    assert [record for record in caplog.records if record.name == LOGGER_NAME] == []


@pytest.mark.asyncio
async def test_replace_crest_keeps_one_reference_and_deletes_the_previous_after_commit(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Replace Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    state = track_transactions(db_session)
    deletions: list[tuple[str, int]] = []
    storage = FakeStorage(
        on_delete=lambda key: deletions.append((key, state["commits"]))
    )
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    await load_crest(
        db_session,
        auth_context(tenant),
        tournament_id,
        team_id,
        crest,
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    stored = await team_crest(db_session, team_id)
    new_key = stored["crest_object_key"]
    assert new_key != OLD_KEY
    assert stored["logo_url"] is None
    # The previous object is deleted once, only after the write commit (second
    # transaction closed).
    assert storage.delete_calls == [OLD_KEY]
    assert deletions == [(OLD_KEY, 2)]
    assert new_key not in storage.delete_calls

    audits = await group_audits(db_session, team_id)
    assert [row["action"] for row in audits] == ["SET_TEAM_CREST"]
    assert audits[0]["payload"] == {"tournament_id": str(tournament_id)}


@pytest.mark.asyncio
async def test_load_crest_never_shares_a_key_between_two_teams(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Two Teams Owner")
    tournament_one, team_one = await seed_enrolled_team(db_session, tenant)
    tournament_two, team_two = await seed_enrolled_team(db_session, tenant)
    # The service opens its own transactions: run them as savepoints of the
    # fixture transaction so everything is rolled back.
    track_transactions(db_session)
    storage = FakeStorage()
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    await load_crest(
        db_session,
        auth_context(tenant),
        tournament_one,
        team_one,
        crest,
        storage=storage,
    )
    await load_crest(
        db_session,
        auth_context(tenant),
        tournament_two,
        team_two,
        crest,
        storage=storage,
    )

    first = (await team_crest(db_session, team_one))["crest_object_key"]
    second = (await team_crest(db_session, team_two))["crest_object_key"]
    assert first != second
    # Same content, different object: each team owns its own file (RF-8).
    assert [call[0] for call in storage.put_calls] == [first, second]


@pytest.mark.asyncio
async def test_replace_crest_logs_once_when_the_previous_file_cannot_be_deleted(
    db_session, tenant_factory, caplog
):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    tenant = await tenant_factory("Crest Delete Failure Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    track_transactions(db_session)
    storage = FakeStorage(delete_error=StorageError("cannot delete private/old"))
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    response = await load_crest(
        db_session,
        auth_context(tenant),
        tournament_id,
        team_id,
        crest,
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] != OLD_KEY
    assert response.crest_url == f"{URL_BASE}{stored['crest_object_key']}"
    assert storage.delete_calls == [OLD_KEY]

    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert len(records) == 1  # one stable entry, not one per attempt
    message = records[0].getMessage()
    assert OLD_KEY not in message
    assert "private/" not in message


@pytest.mark.asyncio
async def test_load_crest_upload_failure_keeps_the_previous_image_and_row(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Upload Failure Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY, logo=OLD_LOGO
    )
    state = track_transactions(db_session)
    storage = FakeStorage(error=StorageError("bucket down"))
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    with pytest.raises(CrestError) as error:
        await load_crest(
            db_session,
            auth_context(tenant),
            tournament_id,
            team_id,
            crest,
            storage=storage,
        )

    assert error.value.code == CREST_STORAGE_UNAVAILABLE
    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] == OLD_KEY
    assert stored["logo_url"] == OLD_LOGO
    assert storage.delete_calls == []
    assert state == {"begins": 1, "commits": 1, "rollbacks": 0}
    assert await group_audits(db_session, team_id) == []


@pytest.mark.asyncio
async def test_load_crest_compensates_the_new_file_when_the_write_body_fails(
    db_session, tenant_factory, monkeypatch
):
    tenant = await tenant_factory("Crest Compensation Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    state = track_transactions(db_session)
    storage = FakeStorage()
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("forced failure inside the write body")

    monkeypatch.setattr(
        "app.modules.crests.service.record_crest_audit", fail
    )

    with pytest.raises(RuntimeError):
        await load_crest(
            db_session,
            auth_context(tenant),
            tournament_id,
            team_id,
            crest,
            storage=storage,
        )

    new_key = storage.put_calls[0][0]
    # The write body failed before its end: the transaction rolled back and the
    # new object is compensated, while the previous image stays referenced.
    assert state["rollbacks"] == 1
    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] == OLD_KEY
    assert storage.delete_calls == [new_key]
    assert OLD_KEY not in storage.delete_calls
    assert await group_audits(db_session, team_id) == []


# ---------------------------------------------------------------------------
# Deletion (T8)
# ---------------------------------------------------------------------------


async def create_member_with_role(
    session: AsyncSession,
    tenant: TenantContext,
    role_code: str,
) -> AuthContext:
    """Create an active member of the tenant with a single role and return it."""

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
                "email": f"crest-{role_code}-{suffix}@example.test",
                "full_name": f"Crest {role_code}",
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


@pytest.mark.asyncio
async def test_delete_crest_with_an_image_clears_the_reference_and_audits(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Delete Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    state = track_transactions(db_session)
    deletions: list[tuple[str, int]] = []
    storage = FakeStorage(
        on_delete=lambda key: deletions.append((key, state["commits"]))
    )

    result = await delete_crest(
        db_session,
        auth_context(tenant),
        tournament_id,
        team_id,
        storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    assert result is None
    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] is None
    # ``logo_url`` is never restored: it was already NULL and stays NULL.
    assert stored["logo_url"] is None
    # The object is deleted only after the write commit (second transaction).
    assert storage.delete_calls == [OLD_KEY]
    assert deletions == [(OLD_KEY, 2)]
    assert state == {"begins": 2, "commits": 2, "rollbacks": 0}

    audits = await group_audits(db_session, team_id)
    assert len(audits) == 1
    assert audits[0]["action"] == "REMOVE_TEAM_CREST"
    assert audits[0]["entity_type"] == "teams"
    assert audits[0]["payload"] == {"tournament_id": str(tournament_id)}


@pytest.mark.asyncio
async def test_delete_crest_without_an_image_is_idempotent_without_storage_or_audit(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Delete Empty Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=None, logo=OLD_LOGO
    )
    state = track_transactions(db_session)
    storage = FakeStorage()

    await delete_crest(
        db_session,
        auth_context(tenant),
        tournament_id,
        team_id,
        storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] is None
    # An external URL the team already had is not touched or restored.
    assert stored["logo_url"] == OLD_LOGO
    assert storage.delete_calls == []
    # Only the read gate ran: no write transaction is opened.
    assert state == {"begins": 1, "commits": 1, "rollbacks": 0}
    assert await group_audits(db_session, team_id) == []


@pytest.mark.asyncio
async def test_delete_crest_twice_leaves_a_single_audit_entry(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Delete Twice Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    track_transactions(db_session)
    storage = FakeStorage()

    await delete_crest(
        db_session, auth_context(tenant), tournament_id, team_id, storage
    )
    await delete_crest(
        db_session, auth_context(tenant), tournament_id, team_id, storage
    )

    audits = await group_audits(db_session, team_id)
    assert [row["action"] for row in audits] == ["REMOVE_TEAM_CREST"]
    # Neither the second deletion nor the repeated call deletes a second object.
    assert storage.delete_calls == [OLD_KEY]


@pytest.mark.asyncio
async def test_delete_crest_logs_once_when_the_object_cannot_be_deleted(
    db_session, tenant_factory, caplog
):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    tenant = await tenant_factory("Crest Delete Failure Owner")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    track_transactions(db_session)
    storage = FakeStorage(delete_error=StorageError("cannot delete private/old"))

    await delete_crest(
        db_session,
        auth_context(tenant),
        tournament_id,
        team_id,
        storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    # The reference is already gone: the answer is successful (204 at the
    # endpoint) and the object stays as an accepted orphan.
    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] is None
    assert storage.delete_calls == [OLD_KEY]
    assert [row["action"] for row in await group_audits(db_session, team_id)] == [
        "REMOVE_TEAM_CREST"
    ]

    records = [record for record in caplog.records if record.name == LOGGER_NAME]
    assert len(records) == 1
    message = records[0].getMessage()
    assert OLD_KEY not in message
    assert "private/" not in message


@pytest.mark.asyncio
async def test_delete_crest_returns_404_for_another_organization_or_not_enrolled(
    db_session, tenant_factory
):
    owner = await tenant_factory("Crest Delete Owner A")
    other = await tenant_factory("Crest Delete Owner B")
    other_tournament, other_team = await seed_enrolled_team(
        db_session, other, crest=OLD_KEY
    )
    own_tournament, own_team = await seed_enrolled_team(db_session, owner)
    # A team of the owner that is not enrolled in that tournament.
    _, unenrolled_team = await seed_enrolled_team(db_session, owner)
    track_transactions(db_session)
    storage = FakeStorage()

    # Tournament of another organization: existing 404.
    with pytest.raises(HTTPException) as tournament_error:
        await delete_crest(
            db_session,
            auth_context(owner),
            other_tournament,
            other_team,
            storage,
        )
    assert tournament_error.value.status_code == 404
    assert tournament_error.value.detail == "Torneo no encontrado"

    # Team of another organization and team not enrolled: the same CREST_NOT_FOUND.
    answers = []
    for team_id in (other_team, unenrolled_team):
        with pytest.raises(CrestError) as error:
            await delete_crest(
                db_session,
                auth_context(owner),
                own_tournament,
                team_id,
                storage,
            )
        answers.append(
            (error.value.code, error.value.status_code, error.value.detail)
        )
    assert answers == [
        (CREST_NOT_FOUND, 404, "El equipo no fue encontrado"),
        (CREST_NOT_FOUND, 404, "El equipo no fue encontrado"),
    ]

    assert storage.delete_calls == []
    assert await group_audits(db_session, other_team) == []
    assert await group_audits(db_session, unenrolled_team) == []
    assert await group_audits(db_session, own_team) == []


@pytest.mark.asyncio
async def test_delete_crest_requires_the_management_permission(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Delete Permission Owner")
    viewer = await create_member_with_role(db_session, tenant, "viewer")
    tournament_id, team_id = await seed_enrolled_team(
        db_session, tenant, crest=OLD_KEY
    )
    track_transactions(db_session)
    storage = FakeStorage()

    with pytest.raises(CrestError) as error:
        await delete_crest(
            db_session, viewer, tournament_id, team_id, storage
        )

    assert error.value.code == CREST_FORBIDDEN
    assert error.value.status_code == 403
    stored = await team_crest(db_session, team_id)
    assert stored["crest_object_key"] == OLD_KEY
    assert storage.delete_calls == []
    assert await group_audits(db_session, team_id) == []


# ---------------------------------------------------------------------------
# Concurrency, ambiguous commit and compensation (T9)
# ---------------------------------------------------------------------------

CREST_FILE = validate_crest_content(PNG_BYTES, max_bytes=1024)


@dataclass
class CrestCluster:
    """Throwaway cluster with one tenant, one tournament and one team."""

    admin: object
    engine: object
    organization_id: UUID
    user_id: UUID
    member_id: UUID
    tournament_id: UUID
    team_id: UUID

    @property
    def context(self) -> AuthContext:
        return AuthContext(
            user_id=self.user_id,
            organization_id=self.organization_id,
            organization_user_id=self.member_id,
        )

    async def team_crest(self) -> str | None:
        return await self.admin.fetchval(
            "SELECT crest_object_key FROM public.teams WHERE id = $1",
            self.team_id,
        )

    async def set_crest(self, key: str | None) -> None:
        await self.admin.execute(
            "UPDATE public.teams SET crest_object_key = $1 WHERE id = $2",
            key,
            self.team_id,
        )


async def _seed_crest_cluster(admin) -> dict:
    organization_id = uuid4()
    user_id = uuid4()
    member_id = uuid4()
    role_id = uuid4()
    tournament_id = uuid4()
    team_id = uuid4()

    await admin.execute(
        f"""
        INSERT INTO public.organizations (id, name, slug)
        VALUES ('{organization_id}', 'Crest Concurrency', 'crest-{organization_id.hex[:12]}');

        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES ('{user_id}', 'crest-concurrency-{user_id.hex[:12]}@example.test',
                'hash', 'Crest Owner');

        INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
        VALUES ('{member_id}', '{organization_id}', '{user_id}', TRUE);

        INSERT INTO public.roles (id, organization_id, role_definition_id, name, permissions)
        SELECT '{role_id}', '{organization_id}', rd.id, 'Owner', rd.system_permissions
        FROM public.role_definitions rd
        WHERE rd.code = 'owner';

        INSERT INTO public.organization_user_roles
            (organization_id, organization_user_id, role_id)
        VALUES ('{organization_id}', '{member_id}', '{role_id}');

        INSERT INTO public.tournaments
            (id, organization_id, name, season, start_date, status, current_draft_config)
        VALUES ('{tournament_id}', '{organization_id}', 'Crest Concurrency Cup',
                '2026', DATE '2026-01-01', 'draft', '{{}}'::jsonb);

        INSERT INTO public.teams (id, organization_id, name, short_code)
        VALUES ('{team_id}', '{organization_id}', 'Concurrent Crest Team', 'CCT01');

        INSERT INTO public.tournament_teams
            (organization_id, tournament_id, team_id, status)
        VALUES ('{organization_id}', '{tournament_id}', '{team_id}', 'registered');
        """
    )
    return {
        "organization_id": organization_id,
        "user_id": user_id,
        "member_id": member_id,
        "tournament_id": tournament_id,
        "team_id": team_id,
    }


@pytest.fixture
async def crest_cluster(database_admin_url):
    """Fresh database at init + 001..025 and a dedicated application role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    engine = None
    role_name = f"bc014_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1, last=25)
        # Dedicated role that inherits bracket_app: the shared role is never
        # altered, and the two concurrent sessions really run as the app role.
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')
        data = await _seed_crest_cluster(admin)
        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        yield CrestCluster(admin=admin, engine=engine, **data)
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.close()
        await drop_database(database_admin_url, database)
        cleaner = await connect(database_admin_url)
        try:
            await cleaner.execute(f'DROP ROLE IF EXISTS "{role_name}"')
        finally:
            await cleaner.close()


async def _run_load(cluster: CrestCluster, storage) -> TeamCrestResponse:
    async with AsyncSession(cluster.engine, expire_on_commit=False) as session:
        return await load_crest(
            session,
            cluster.context,
            cluster.tournament_id,
            cluster.team_id,
            CREST_FILE,
            storage=storage,
        )


async def _run_delete(cluster: CrestCluster, storage) -> None:
    async with AsyncSession(cluster.engine, expire_on_commit=False) as session:
        await delete_crest(
            session,
            cluster.context,
            cluster.tournament_id,
            cluster.team_id,
            storage,
        )


@pytest.mark.asyncio
async def test_two_concurrent_loads_leave_one_reference_and_never_delete_it(
    crest_cluster,
):
    storage = FakeStorage()

    await asyncio.gather(
        _run_load(crest_cluster, storage),
        _run_load(crest_cluster, storage),
    )

    stored = await crest_cluster.team_crest()
    uploaded = [key for key, _content, _type in storage.put_calls]
    assert len(set(uploaded)) == 2

    # Exactly one committed reference: the last confirmed write wins.
    assert stored in uploaded
    # No referenced object is ever deleted; the loser's file is removed only
    # after it stopped being the referenced one.
    assert stored not in storage.delete_calls
    assert set(storage.delete_calls) == set(uploaded) - {stored}


@pytest.mark.asyncio
async def test_concurrent_load_and_delete_never_reference_a_deleted_object(
    crest_cluster,
):
    storage = FakeStorage()

    await asyncio.gather(
        _run_load(crest_cluster, storage),
        _run_delete(crest_cluster, storage),
    )

    stored = await crest_cluster.team_crest()
    uploaded = [key for key, _content, _type in storage.put_calls]
    assert len(uploaded) == 1
    loaded_key = uploaded[0]

    # The team ends with the loaded image or with none, never with a reference
    # to an object the deletion removed.
    assert stored in {None, loaded_key}
    if stored is None:
        assert storage.delete_calls == [loaded_key]
    else:
        assert storage.delete_calls == []
    assert set(storage.delete_calls) <= {loaded_key}


class _AmbiguousTransaction:
    """Commits for real and then reports a failure: the outcome is ambiguous."""

    def __init__(self, transaction, *, fail: bool) -> None:
        self._transaction = transaction
        self._fail = fail

    async def __aenter__(self):
        return await self._transaction.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        result = await self._transaction.__aexit__(exc_type, exc, traceback)
        if self._fail and exc_type is None:
            raise RuntimeError("ambiguous commit: the write may be confirmed")
        return result


class AmbiguousCommitSession:
    """Wraps a session so the write transaction commits and then raises."""

    def __init__(self, session: AsyncSession, *, fail_on: int) -> None:
        self._session = session
        self._fail_on = fail_on
        self.begins = 0

    def begin(self):
        self.begins += 1
        return _AmbiguousTransaction(
            self._session.begin(), fail=self.begins == self._fail_on
        )

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.mark.asyncio
async def test_ambiguous_commit_keeps_both_files_and_deletes_nothing(crest_cluster):
    await crest_cluster.set_crest(OLD_KEY)
    storage = FakeStorage()

    async with AsyncSession(crest_cluster.engine, expire_on_commit=False) as raw:
        session = AmbiguousCommitSession(raw, fail_on=2)

        with pytest.raises(RuntimeError):
            await load_crest(
                session,
                crest_cluster.context,
                crest_cluster.tournament_id,
                crest_cluster.team_id,
                CREST_FILE,
                storage=storage,
            )

    uploaded = [key for key, _content, _type in storage.put_calls]
    assert len(uploaded) == 1
    # The write was confirmed before the ambiguity: the new reference is valid
    # and neither the new object nor the previous one is deleted.
    assert await crest_cluster.team_crest() == uploaded[0]
    assert storage.delete_calls == []


# ---------------------------------------------------------------------------
# One team in two tournaments and a published tournament (T18 / RF-1, RF-53)
# ---------------------------------------------------------------------------


async def seed_team_in_two_tournaments(session, tenant) -> tuple[UUID, UUID, UUID]:
    await set_tenant_context(session, tenant)
    team_id = uuid4()
    suffix = team_id.hex[:8].upper()
    await session.execute(
        text("""
            INSERT INTO teams (id, organization_id, name, short_code)
            VALUES (:id, :organization_id, :name, :short_code)
        """),
        {
            "id": str(team_id),
            "organization_id": str(tenant.organization_id),
            "name": f"Shared Crest {suffix}",
            "short_code": f"S{suffix[:4]}",
        },
    )
    tournaments = []
    for _ in range(2):
        tournament_id = uuid4()
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
                "name": f"Shared Cup {tournament_id.hex[:8]}",
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
        tournaments.append(tournament_id)
    return tournaments[0], tournaments[1], team_id


@pytest.mark.asyncio
async def test_load_crest_from_one_tournament_is_visible_in_the_other(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Shared Owner")
    first, second, team_id = await seed_team_in_two_tournaments(db_session, tenant)
    track_transactions(db_session)
    storage = FakeStorage()
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    await load_crest(
        db_session, auth_context(tenant), first, team_id, crest, storage=storage
    )
    first_key = (await team_crest(db_session, team_id))["crest_object_key"]
    assert first_key is not None

    # RF-1: the image belongs to the team, so the other tournament sees it.
    seen = await resolve_enrolled_team(
        db_session, auth_context(tenant), second, team_id, require_management=False
    )
    assert seen.crest_object_key == first_key

    # A replacement from the second tournament is the single current image.
    await load_crest(
        db_session, auth_context(tenant), second, team_id, crest, storage=storage
    )
    second_key = (await team_crest(db_session, team_id))["crest_object_key"]
    assert second_key != first_key
    seen_from_first = await resolve_enrolled_team(
        db_session, auth_context(tenant), first, team_id, require_management=False
    )
    assert seen_from_first.crest_object_key == second_key
    assert [call[0] for call in storage.put_calls] == [first_key, second_key]


async def seed_published_tournament(session, tenant) -> dict:
    await set_tenant_context(session, tenant)
    tournament_id = uuid4()
    version_id = uuid4()
    stage_id = uuid4()
    home_team = uuid4()
    away_team = uuid4()
    match_id = uuid4()
    suffix = tournament_id.hex[:8].upper()

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
            "name": f"Published Crest {suffix}",
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
    for team_id, name, short_code in (
        (home_team, f"Published Home {suffix}", f"P{suffix[:3]}"),
        (away_team, f"Published Away {suffix}", f"Q{suffix[:3]}"),
    ):
        await session.execute(
            text("""
                INSERT INTO teams (id, organization_id, name, short_code)
                VALUES (:id, :organization_id, :name, :short_code)
            """),
            {
                "id": str(team_id),
                "organization_id": str(tenant.organization_id),
                "name": name,
                "short_code": short_code,
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
                INSERT INTO stage_teams
                    (organization_id, tournament_id, tournament_version_id,
                     stage_id, group_id, team_id)
                VALUES (:organization_id, :tournament_id, :version_id,
                        :stage_id, NULL, :team_id)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
    await session.execute(
        text("""
            INSERT INTO matches
                (id, organization_id, tournament_id, tournament_version_id,
                 stage_id, group_id, home_team_id, away_team_id, status,
                 match_date, created_at)
            VALUES (:id, :organization_id, :tournament_id, :version_id,
                    :stage_id, NULL, :home_team, :away_team, 'scheduled',
                    CAST('2026-06-01 12:00:00+00' AS TIMESTAMPTZ),
                    CAST('2026-01-02 00:00:00+00' AS TIMESTAMPTZ))
        """),
        {
            "id": str(match_id),
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "home_team": str(home_team),
            "away_team": str(away_team),
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
            "team_id": str(home_team),
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
    return {
        "tournament_id": tournament_id,
        "version_id": version_id,
        "stage_id": stage_id,
        "home_team": home_team,
        "away_team": away_team,
        "match_id": match_id,
    }


async def published_snapshot(session, tenant, ids: dict) -> dict:
    await set_tenant_context(session, tenant)
    tournament = dict(
        (
            await session.execute(
                text("""
                    SELECT status, published_version_id, name, season, start_date
                    FROM tournaments WHERE id = :id
                """),
                {"id": str(ids["tournament_id"])},
            )
        ).mappings().one()
    )
    version = dict(
        (
            await session.execute(
                text("""
                    SELECT status, version_number, rules_config, phase_config,
                           published_at
                    FROM tournament_versions WHERE id = :id
                """),
                {"id": str(ids["version_id"])},
            )
        ).mappings().one()
    )
    stages = [
        dict(row)
        for row in (
            await session.execute(
                text("""
                    SELECT id, name, stage_type, stage_order, schedule_legs
                    FROM stages WHERE tournament_id = :id ORDER BY id
                """),
                {"id": str(ids["tournament_id"])},
            )
        ).mappings().all()
    ]
    matches = [
        dict(row)
        for row in (
            await session.execute(
                text("""
                    SELECT id, status, home_team_id, away_team_id, match_date,
                           home_score, away_score, home_penalties, away_penalties,
                           winner_team_id, resolution_type
                    FROM matches WHERE tournament_id = :id ORDER BY id
                """),
                {"id": str(ids["tournament_id"])},
            )
        ).mappings().all()
    ]
    standings = [
        dict(row)
        for row in (
            await session.execute(
                text("""
                    SELECT team_id, stage_id, played, won, drawn, lost,
                           goals_for, goals_against, goal_difference, points, rank
                    FROM standings WHERE tournament_id = :id ORDER BY team_id
                """),
                {"id": str(ids["tournament_id"])},
            )
        ).mappings().all()
    ]
    return {
        "tournament": tournament,
        "version": version,
        "stages": stages,
        "matches": matches,
        "standings": standings,
    }


@pytest.mark.asyncio
async def test_crest_changes_do_not_touch_published_structure_or_results(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Crest Published Owner")
    ids = await seed_published_tournament(db_session, tenant)
    track_transactions(db_session)
    before = await published_snapshot(db_session, tenant, ids)
    storage = FakeStorage()
    crest = validate_crest_content(PNG_BYTES, max_bytes=1024)

    await load_crest(
        db_session,
        auth_context(tenant),
        ids["tournament_id"],
        ids["home_team"],
        crest,
        storage=storage,
    )
    assert await published_snapshot(db_session, tenant, ids) == before
    stored = await team_crest(db_session, ids["home_team"])
    assert stored["crest_object_key"] == storage.put_calls[0][0]

    await delete_crest(
        db_session,
        auth_context(tenant),
        ids["tournament_id"],
        ids["home_team"],
        storage,
    )
    assert await published_snapshot(db_session, tenant, ids) == before
    assert (await team_crest(db_session, ids["home_team"]))["crest_object_key"] is None
    assert sorted(
        row["action"]
        for row in await group_audits(db_session, ids["home_team"])
    ) == ["REMOVE_TEAM_CREST", "SET_TEAM_CREST"]
