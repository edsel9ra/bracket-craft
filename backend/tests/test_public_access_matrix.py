"""Matriz de acceso y aislamiento entre organizaciones (spec 020, T8).

Verifica las lecturas públicas sin sesión: 200/404, torneo no público
indistinguible de inexistente, aislamiento entre dos tenants y parámetros
de consulta fuera de rango (422 estructural, sin ``code``).

Desde la spec 022 (T18) la matriz incluye también las dos lecturas de
estadísticas, ``player-stats`` y ``team-stats``: lectura anónima de un torneo
visible, el mismo ``404`` indistinguible cuando el torneo no es visible y ``422``
de parámetros. El aislamiento **con datos** de esas dos rutas —dos
organizaciones con partidos, eventos, formaciones y plantillas— y la lista
cerrada de sus campos viven en ``test_public_stats_endpoints.py``; aquí basta el
código de estado y la forma básica de la respuesta.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.main import api
from db_helpers import (
    admin_database_url,
    clear_rls_context,
    create_tenant_owner,
    database_tests_enabled,
    set_tenant_context,
)


def _skip_if_no_db():
    if not database_tests_enabled():
        pytest.skip("RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas")


async def _create_tournament(session, tenant, *, label: str = "pub") -> tuple[UUID, UUID, UUID]:
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, :season, DATE '2026-01-01',
                     'draft', '{}'::jsonb)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T020 {label} {uuid4().hex[:8]}",
                "season": "2026",
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
                    (:organization_id, :tournament_id, :version_id, 'Group stage',
                     'round_robin', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
            },
        )
    ).scalar_one()

    return tournament_id, version_id, stage_id


async def _register_team(session, tenant, tournament_id: UUID) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"Team {uuid4().hex[:6]}",
                "short_code": f"T{uuid4().hex[:5].upper()}",
            },
        )
    ).scalar_one()

    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _publish_tournament(session, tournament_id: UUID, version_id: UUID) -> None:
    await session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
        """),
        {"version_id": str(version_id)},
    )
    await session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :tournament_id
        """),
        {"tournament_id": str(tournament_id), "version_id": str(version_id)},
    )


@asynccontextmanager
async def _public_api(session):
    connection = await session.connection()

    async def database():
        request_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield request_session
        finally:
            await request_session.close()

    api.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)


@asynccontextmanager
async def _application_session(database_url: str):
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            await session.execute(text("SET LOCAL ROLE bracket_app"))
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


def _assert_404_indistinguishable(response, expected_detail: str = "Torneo público no encontrado"):
    assert response.status_code == 404, response.text
    body = response.json()
    assert body.get("detail") == expected_detail


def _assert_422_structural(response):
    assert response.status_code == 422, response.text
    body = response.json()
    assert "code" not in body
    detail = body.get("detail")
    assert isinstance(detail, list) and detail, body
    for item in detail:
        assert set(item).issuperset({"type", "loc", "msg"}), item
        assert "code" not in item


@pytest.mark.asyncio
async def test_public_reads_are_anonymous(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Public Access Owner")
    await set_tenant_context(db_session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(db_session, tenant, label="published")
    await _register_team(db_session, tenant, tournament_id)
    await _publish_tournament(db_session, tournament_id, version_id)
    await clear_rls_context(db_session)

    missing = uuid4()
    async with _public_api(db_session) as client:
        list_response = await client.get("/api/v1/tournaments/public")
        assert list_response.status_code == 200
        assert any(row["id"] == str(tournament_id) for row in list_response.json())

        detail_response = await client.get(f"/api/v1/tournaments/public/{tournament_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == str(tournament_id)

        standings_response = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/standings"
        )
        assert standings_response.status_code == 200

        matches_response = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/matches"
        )
        assert matches_response.status_code == 200

        # Spec 022, RF-036: las dos tablas de estadísticas se sirven sin sesión.
        for endpoint in ("player-stats", "team-stats"):
            stats_response = await client.get(
                f"/api/v1/tournaments/public/{tournament_id}/{endpoint}"
            )
            assert stats_response.status_code == 200
            assert isinstance(stats_response.json(), list)

        for path in (
            f"/api/v1/tournaments/public/{missing}",
            f"/api/v1/tournaments/public/{missing}/standings",
            f"/api/v1/tournaments/public/{missing}/matches",
            f"/api/v1/tournaments/public/{missing}/player-stats",
            f"/api/v1/tournaments/public/{missing}/team-stats",
        ):
            response = await client.get(path)
            _assert_404_indistinguishable(response)


@pytest.mark.asyncio
async def test_non_public_tournaments_are_indistinguishable_404(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Draft Owner")
    await set_tenant_context(db_session, tenant)

    # Draft tournament (never published).
    draft_id, draft_version_id, _ = await _create_tournament(db_session, tenant, label="draft")

    # Tournament with a published version flag but status still draft (no publish).
    unpublished_id, unpublished_version_id, _ = await _create_tournament(
        db_session, tenant, label="unpublished"
    )

    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        for tid in (draft_id, unpublished_id):
            for path in (
                f"/api/v1/tournaments/public/{tid}",
                f"/api/v1/tournaments/public/{tid}/standings",
                f"/api/v1/tournaments/public/{tid}/matches",
                f"/api/v1/tournaments/public/{tid}/player-stats",
                f"/api/v1/tournaments/public/{tid}/team-stats",
            ):
                response = await client.get(path)
                _assert_404_indistinguishable(response)

            list_response = await client.get("/api/v1/tournaments/public")
            assert list_response.status_code == 200
            ids = {row["id"] for row in list_response.json()}
            assert str(tid) not in ids


@pytest.mark.asyncio
async def test_inactive_organization_tournament_is_404():
    _skip_if_no_db()
    url = admin_database_url()
    if not url:
        pytest.skip("DATABASE_ADMIN_URL no configurado")

    async with _application_session(url) as session:
        tenant = await create_tenant_owner(session, full_name="Inactive Org Owner")
        await set_tenant_context(session, tenant)
        tournament_id, version_id, _ = await _create_tournament(session, tenant, label="inactive-org")
        await _register_team(session, tenant, tournament_id)
        await _publish_tournament(session, tournament_id, version_id)

        # Deactivate the organization as administrator.
        await session.execute(text("RESET ROLE"))
        await session.execute(
            text("UPDATE public.organizations SET is_active = FALSE WHERE id = :id"),
            {"id": str(tenant.organization_id)},
        )
        await session.execute(text("SET LOCAL ROLE bracket_app"))
        await clear_rls_context(session)

        async with _public_api(session) as client:
            for path in (
                f"/api/v1/tournaments/public/{tournament_id}",
                f"/api/v1/tournaments/public/{tournament_id}/standings",
                f"/api/v1/tournaments/public/{tournament_id}/matches",
                f"/api/v1/tournaments/public/{tournament_id}/player-stats",
                f"/api/v1/tournaments/public/{tournament_id}/team-stats",
            ):
                response = await client.get(path)
                _assert_404_indistinguishable(response)

            list_response = await client.get("/api/v1/tournaments/public")
            assert list_response.status_code == 200
            ids = {row["id"] for row in list_response.json()}
            assert str(tournament_id) not in ids


@pytest.mark.asyncio
async def test_two_tenants_do_not_mix_public_data(db_session, tenant_factory):
    _skip_if_no_db()
    first = await tenant_factory("Tenant A")
    second = await tenant_factory("Tenant B")

    await set_tenant_context(db_session, first)
    first_tournament, first_version, first_stage = await _create_tournament(
        db_session, first, label="A"
    )
    first_team = await _register_team(db_session, first, first_tournament)
    await _publish_tournament(db_session, first_tournament, first_version)

    await set_tenant_context(db_session, second)
    second_tournament, second_version, second_stage = await _create_tournament(
        db_session, second, label="B"
    )
    second_team = await _register_team(db_session, second, second_tournament)
    await _publish_tournament(db_session, second_tournament, second_version)

    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        # Detail responses stay scoped to their own tournament.
        first_detail = await client.get(f"/api/v1/tournaments/public/{first_tournament}")
        second_detail = await client.get(f"/api/v1/tournaments/public/{second_tournament}")
        assert first_detail.status_code == 200
        assert second_detail.status_code == 200
        first_team_names = {t["name"] for t in first_detail.json()["teams"]}
        second_team_names = {t["name"] for t in second_detail.json()["teams"]}
        # The team registered in B must not appear in A's detail and vice versa.
        # We compare by id sets instead of names (names are random).
        first_team_ids = {t["team_id"] for t in first_detail.json()["teams"]}
        second_team_ids = {t["team_id"] for t in second_detail.json()["teams"]}
        assert first_team_ids == {str(first_team)}
        assert second_team_ids == {str(second_team)}
        assert first_team_ids.isdisjoint(second_team_ids)

        # Standings/matches of A with B's identifiers return empty, no leak.
        for foreign_stage in (second_stage,):
            r = await client.get(
                f"/api/v1/tournaments/public/{first_tournament}/standings",
                params={"stage_id": str(foreign_stage)},
            )
            assert r.status_code == 200
            assert r.json() == []

        # A's standings/matches never contain B's team id.
        a_standings = await client.get(
            f"/api/v1/tournaments/public/{first_tournament}/standings"
        )
        a_matches = await client.get(
            f"/api/v1/tournaments/public/{first_tournament}/matches"
        )
        assert a_standings.status_code == 200
        assert a_matches.status_code == 200
        for row in a_standings.json():
            assert row["team_id"] != str(second_team)
        for row in a_matches.json():
            assert row["home_team_id"] != str(second_team)
            assert row["away_team_id"] != str(second_team)


@pytest.mark.asyncio
async def test_public_query_params_out_of_range_return_422(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Query Params Owner")
    await set_tenant_context(db_session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(db_session, tenant, label="qp")
    await _publish_tournament(db_session, tournament_id, version_id)
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        # limit below minimum
        r = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/standings",
            params={"limit": 0},
        )
        _assert_422_structural(r)

        # limit above maximum
        r = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/standings",
            params={"limit": 501},
        )
        _assert_422_structural(r)

        # offset negative
        r = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/standings",
            params={"offset": -1},
        )
        _assert_422_structural(r)

        # invalid UUID for stage_id
        r = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/standings",
            params={"stage_id": "not-a-uuid"},
        )
        _assert_422_structural(r)

        # list endpoint limit out of range
        r = await client.get("/api/v1/tournaments/public", params={"limit": 0})
        _assert_422_structural(r)
        r = await client.get("/api/v1/tournaments/public", params={"limit": 201})
        _assert_422_structural(r)
        r = await client.get("/api/v1/tournaments/public", params={"offset": -1})
        _assert_422_structural(r)

        # matches endpoint too
        r = await client.get(
            f"/api/v1/tournaments/public/{tournament_id}/matches",
            params={"limit": 0},
        )
        _assert_422_structural(r)

        # Las dos tablas de estadísticas (spec 022, RF-036) tienen su propio tope
        # de paginación (500) y los mismos filtros de fase y grupo, así que un
        # límite fuera de rango o un identificador mal formado son 422 estructural.
        for endpoint in ("player-stats", "team-stats"):
            base = f"/api/v1/tournaments/public/{tournament_id}/{endpoint}"
            for params in (
                {"limit": 0},
                {"limit": 501},
                {"offset": -1},
                {"stage_id": "not-a-uuid"},
                {"group_id": "not-a-uuid"},
            ):
                r = await client.get(base, params=params)
                _assert_422_structural(r)
