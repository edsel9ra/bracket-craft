"""Workspace roster listing: ``age`` only in ``GET /tournaments/{id}/rosters`` (RF-009).

The listing is the only Workspace response that exposes the materialized age
(``age_at_reference + (tournament start year - age_reference_year)``); the
registration, bulk import and photo responses keep the original
``RosterPlayerResponse`` contract without ``age``.

The HTTP tests run against PostgreSQL as ``bracket_app`` (``RUN_DATABASE_TESTS=1``)
and override only the database session and the auth context, so the real
endpoint, the real query and the real response model are exercised inside the
rolled-back test transaction. The contract test is pure Python and always runs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.tournaments import router as tournaments_router
from app.modules.tournaments.schemas import (
    BulkRosterPlayerResponse,
    RosterPlayerListResponse,
    RosterPlayerResponse,
)
from db_helpers import TenantContext, insert_player, set_tenant_context

EXPECTED_LIST_KEYS = {
    "roster_id",
    "player_id",
    "team_id",
    "first_name",
    "last_name",
    "dorsal_number",
    "photo_url",
    "photo_consent",
    "is_active",
    "age",
}

EXPECTED_WRITE_KEYS = EXPECTED_LIST_KEYS - {"age"}


class _NoopTransaction:
    """The endpoint opens ``db.begin()``; the test already owns the transaction."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _RequestSession:
    """Delegate to the test session and record every statement the request runs."""

    def __init__(self, session):
        self._session = session
        self.statements: list[str] = []

    def begin(self):
        return _NoopTransaction()

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(" ".join(str(statement).split()))
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


def _context(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


@asynccontextmanager
async def _listing_client(session, context: AuthContext):
    """Run one real HTTP request against the in-transaction test session."""

    request_session = _RequestSession(session)

    async def database():
        yield request_session

    async def current_context():
        return context

    api.dependency_overrides[get_db] = database
    api.dependency_overrides[get_auth_context] = current_context
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client, request_session
    finally:
        api.dependency_overrides.pop(get_db, None)
        api.dependency_overrides.pop(get_auth_context, None)


async def _get_rosters(
    session, tenant: TenantContext, tournament_id: UUID
) -> tuple:
    async with _listing_client(session, _context(tenant)) as (client, request_session):
        response = await client.get(f"/api/v1/tournaments/{tournament_id}/rosters")
        statements = list(request_session.statements)
    return response, statements


async def _create_tournament(
    session, organization_id: UUID, *, start_date: str = "2026-01-01"
) -> UUID:
    result = await session.execute(
        text("""
            INSERT INTO tournaments
                (organization_id, name, season, start_date, status, current_draft_config)
            VALUES
                (:organization_id, :name, :season, CAST(:start_date AS DATE),
                 'draft', '{}'::jsonb)
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "name": f"Age {uuid4().hex[:8]}",
            "season": start_date[:4],
            "start_date": date.fromisoformat(start_date),
        },
    )
    return result.scalar_one()


async def _register_team(session, organization_id: UUID, tournament_id: UUID) -> UUID:
    suffix = uuid4().hex[:6]
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(organization_id),
                "name": f"Age Team {suffix}",
                "short_code": f"AG{suffix.upper()}",
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _insert_roster(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    team_id: UUID,
    player_id: UUID,
    *,
    dorsal_number: int,
) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id,
                     dorsal_number, photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id,
                     :dorsal_number, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": dorsal_number,
            },
        )
    ).scalar_one()


async def _seed_roster(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    team_id: UUID,
    *,
    first_name: str,
    last_name: str,
    birth_date: str,
    reference_year: int,
    dorsal_number: int,
) -> UUID:
    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        reference_year=reference_year,
    )
    await _insert_roster(
        session,
        tenant,
        tournament_id,
        team_id,
        player_id,
        dorsal_number=dorsal_number,
    )
    return player_id


@pytest.mark.asyncio
async def test_listing_returns_the_adjusted_age_as_an_integer(db_session, tenant_factory):
    tenant = await tenant_factory("Age Listing")
    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_tournament(
        db_session, tenant.organization_id, start_date="2026-01-01"
    )
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)

    older = await _seed_roster(
        db_session,
        tenant,
        tournament_id,
        team_id,
        first_name="Ana",
        last_name="Ancestral",
        birth_date="2000-01-01",
        reference_year=2026,
        dorsal_number=7,
    )
    younger = await _seed_roster(
        db_session,
        tenant,
        tournament_id,
        team_id,
        first_name="Beto",
        last_name="Bisnieto",
        birth_date="2010-01-01",
        reference_year=2026,
        dorsal_number=9,
    )

    response, _ = await _get_rosters(db_session, tenant, tournament_id)

    assert response.status_code == 200
    players = {row["player_id"]: row for row in response.json()}
    assert set(players) == {str(older), str(younger)}

    # age = age_at_reference + (2026 - 2026) = year(tournament) - year(birth date).
    assert players[str(older)]["age"] == 26
    assert players[str(younger)]["age"] == 16
    assert all(isinstance(row["age"], int) for row in players.values())
    assert all(type(row["age"]) is int for row in players.values())

    for row in players.values():
        assert set(row) == EXPECTED_LIST_KEYS

    # The response never exposes the birth date nor the ciphertext.
    assert "birth_date" not in response.text
    assert "birth_date_encrypted" not in response.text


@pytest.mark.asyncio
async def test_changing_the_tournament_start_year_moves_the_age_by_the_delta(
    db_session, tenant_factory
):
    tenant = await tenant_factory("Age Delta")
    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_tournament(
        db_session, tenant.organization_id, start_date="2026-01-01"
    )
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)
    player_id = await _seed_roster(
        db_session,
        tenant,
        tournament_id,
        team_id,
        first_name="Carla",
        last_name="Cambio",
        birth_date="2000-01-01",
        reference_year=2026,
        dorsal_number=4,
    )

    async def _age() -> int:
        response, _ = await _get_rosters(db_session, tenant, tournament_id)
        assert response.status_code == 200
        rows = [row for row in response.json() if row["player_id"] == str(player_id)]
        assert len(rows) == 1
        return rows[0]["age"]

    assert await _age() == 26

    # Two years later the adjusted age grows by exactly the delta.
    await db_session.execute(
        text("UPDATE tournaments SET start_date = DATE '2028-01-01' WHERE id = :tournament_id"),
        {"tournament_id": str(tournament_id)},
    )
    assert await _age() == 28

    # A different day inside the same year does not change the age.
    await db_session.execute(
        text("UPDATE tournaments SET start_date = DATE '2028-11-30' WHERE id = :tournament_id"),
        {"tournament_id": str(tournament_id)},
    )
    assert await _age() == 28


@pytest.mark.asyncio
async def test_listing_does_not_query_once_per_player(db_session, tenant_factory):
    tenant = await tenant_factory("Age Queries")
    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_tournament(
        db_session, tenant.organization_id, start_date="2026-01-01"
    )
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)
    await _seed_roster(
        db_session,
        tenant,
        tournament_id,
        team_id,
        first_name="One",
        last_name="Player",
        birth_date="2000-01-01",
        reference_year=2026,
        dorsal_number=1,
    )

    _, single_statement_count = await _get_rosters(db_session, tenant, tournament_id)

    for index in range(2, 6):
        await _seed_roster(
            db_session,
            tenant,
            tournament_id,
            team_id,
            first_name=f"Player{index}",
            last_name="Many",
            birth_date="2001-01-01",
            reference_year=2026,
            dorsal_number=index + 10,
        )

    response, many_statements = await _get_rosters(db_session, tenant, tournament_id)

    assert response.status_code == 200
    assert len(response.json()) == 5
    # A constant statement count proves the age comes from the same joined query
    # instead of one extra query per player.
    assert len(many_statements) == len(single_statement_count)

    listing_queries = [
        statement
        for statement in many_statements
        if "age_at_reference" in statement and "FROM rosters r" in statement
    ]
    assert len(listing_queries) == 1
    listing_query = listing_queries[0]
    assert "JOIN tournaments t" in listing_query
    assert "t.start_date" in listing_query
    assert "age_reference_year" in listing_query


@pytest.mark.asyncio
async def test_listing_keeps_the_rosters_of_another_organization_isolated(
    db_session, tenant_factory
):
    first = await tenant_factory("Age Isolation A")
    second = await tenant_factory("Age Isolation B")

    await set_tenant_context(db_session, first)
    first_tournament = await _create_tournament(
        db_session, first.organization_id, start_date="2026-01-01"
    )
    first_team = await _register_team(db_session, first.organization_id, first_tournament)
    first_player = await _seed_roster(
        db_session,
        first,
        first_tournament,
        first_team,
        first_name="Alice",
        last_name="Alpha",
        birth_date="2000-01-01",
        reference_year=2026,
        dorsal_number=1,
    )

    await set_tenant_context(db_session, second)
    second_tournament = await _create_tournament(
        db_session, second.organization_id, start_date="2026-01-01"
    )
    second_team = await _register_team(db_session, second.organization_id, second_tournament)
    second_player = await _seed_roster(
        db_session,
        second,
        second_tournament,
        second_team,
        first_name="Bruno",
        last_name="Beta",
        birth_date="1990-01-01",
        reference_year=2026,
        dorsal_number=2,
    )

    # B cannot even see A's tournament.
    forbidden, _ = await _get_rosters(db_session, second, first_tournament)
    assert forbidden.status_code == 404

    own, _ = await _get_rosters(db_session, second, second_tournament)
    assert own.status_code == 200
    assert {row["player_id"] for row in own.json()} == {str(second_player)}
    assert str(first_player) not in own.text


def test_write_responses_keep_the_contract_without_age():
    assert "age" not in RosterPlayerResponse.model_fields
    assert set(RosterPlayerResponse.model_fields) == EXPECTED_WRITE_KEYS
    assert RosterPlayerListResponse.model_fields["age"].annotation is int
    assert set(RosterPlayerListResponse.model_fields) == EXPECTED_LIST_KEYS
    assert set(BulkRosterPlayerResponse.model_fields["players"].annotation.__args__) == {
        RosterPlayerResponse
    }

    def _route(path: str, method: str):
        for route in tournaments_router.router.routes:
            if getattr(route, "path", None) == path and method in getattr(
                route, "methods", set()
            ):
                return route
        raise AssertionError(f"No existe la ruta {method} {path}")

    listing = _route("/tournaments/{tournament_id}/rosters", "GET")
    create = _route("/tournaments/{tournament_id}/rosters", "POST")
    bulk = _route("/tournaments/{tournament_id}/rosters/bulk", "POST")
    photo = _route("/tournaments/{tournament_id}/rosters/{roster_id}/photo", "POST")

    assert listing.response_model == list[RosterPlayerListResponse]
    assert create.response_model is RosterPlayerResponse
    assert bulk.response_model is BulkRosterPlayerResponse
    assert photo.response_model is RosterPlayerResponse
