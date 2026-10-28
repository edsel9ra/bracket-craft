"""Aislamiento y lista cerrada de campos públicos para las estadísticas (spec 022, T7).

La lista cerrada de campos se verifica **con datos reales** (T17): cada fila de
las dos respuestas se compara con ``model_fields`` del modelo que declara su
ruta, una respuesta vacía es un fallo y las claves internas se comprueban
aparte. El **aislamiento entre organizaciones** también se verifica con datos
reales (T18): dos organizaciones con torneo publicado, partido confirmado,
eventos, formaciones y plantillas producen recuentos distintos y ninguna
respuesta mezcla filas de la otra. Las pruebas con base son opt-in
(``RUN_DATABASE_TESTS=1`` con PostgreSQL de pruebas); las que no necesitan base
—la comparación no vacua y la declaración de ``response_model`` de las dos
rutas— corren en ``pytest -q``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import get_args, get_origin
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.storage import SignedUrls
from app.main import api
from app.modules.tournaments.schemas import (
    PublicPlayerStatsResponse,
    PublicTeamStatsResponse,
)
from assertion_messages import describe_response
from db_helpers import (
    clear_rls_context,
    create_tenant_owner,
    database_tests_enabled,
    insert_player,
    set_tenant_context,
)


def _skip_if_no_db():
    if not database_tests_enabled():
        pytest.skip("RUN_DATABASE_TESTS=1 requiere una base PostgreSQL de pruebas")


async def _create_published_tournament(session: AsyncSession, tenant) -> tuple:
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', DATE '2026-01-01', 'draft', '{}'::jsonb)
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "name": f"T022 {uuid4().hex[:8]}"},
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
    return tournament_id


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
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)


#: Modelo que cierra la lista de campos de cada tabla pública de estadísticas
#: (RF-036, RNF-001). La respuesta se compara contra ``model_fields``, nunca
#: contra una lista copiada a mano: `test_public_field_allowlist.py` es quien
#: fija el contrato del modelo.
STATS_MODELS = {
    "player-stats": PublicPlayerStatsResponse,
    "team-stats": PublicTeamStatsResponse,
}

#: Claves internas que **nunca** pueden salir en una respuesta pública. La
#: comparación exacta contra el modelo ya las excluye; se comprueban aparte para
#: que el fallo nombre la clave interna concreta.
SENSITIVE = {
    "national_id", "birth_date", "age", "logo_url", "crest_object_key",
    "photo_object_key", "object_key", "photo_consent", "metadata", "is_voided",
    "organization_id", "resolution_reason", "reason", "suspension", "suspensions",
    "sanction", "sanctions",
}


def _closed_field_problems(rows: list[dict], model) -> list[str]:
    """Diferencias entre las claves de cada fila y las que declara el modelo.

    Devuelve un mensaje por fila y tipo de diferencia —claves de más, claves de
    menos y claves internas— y **nunca** el valor de un campo: solo nombres, que
    son contrato y no datos de la respuesta. Una lista vacía no demuestra nada
    por sí sola (``[]`` también da cero problemas), así que la prueba con base
    exige además un recuento de filas mayor que cero.
    """

    expected = set(model.model_fields)
    problems: list[str] = []
    for index, row in enumerate(rows):
        actual = set(row)
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        leaked = sorted(actual & SENSITIVE)
        if extra:
            problems.append(f"fila {index}: claves fuera de {model.__name__}: {extra}")
        if missing:
            problems.append(
                f"fila {index}: claves de {model.__name__} ausentes: {missing}"
            )
        if leaked:
            problems.append(f"fila {index}: claves internas publicadas: {leaked}")
    return problems


@pytest.mark.asyncio
async def test_public_stats_endpoints_empty_for_published_tournament(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Stats Owner")
    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_published_tournament(db_session, tenant)
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        for path in (
            f"/api/v1/tournaments/public/{tournament_id}/player-stats",
            f"/api/v1/tournaments/public/{tournament_id}/team-stats",
        ):
            r = await client.get(path)
            assert r.status_code == 200, r.text
            assert r.json() == []


@pytest.mark.asyncio
async def test_public_stats_non_public_tournament_is_404(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Draft Owner")
    await set_tenant_context(db_session, tenant)
    # Draft tournament: create without publishing.
    tournament_id = (
        await db_session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', DATE '2026-01-01', 'draft', '{}'::jsonb)
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "name": "draft"},
        )
    ).scalar_one()
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        for path in (
            f"/api/v1/tournaments/public/{tournament_id}/player-stats",
            f"/api/v1/tournaments/public/{tournament_id}/team-stats",
        ):
            r = await client.get(path)
            assert r.status_code == 404, r.text
            assert r.json().get("detail") == "Torneo público no encontrado"


@pytest.mark.asyncio
async def test_public_stats_query_params_out_of_range_return_422(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Query Params Owner")
    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_published_tournament(db_session, tenant)
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        for endpoint in ("player-stats", "team-stats"):
            base = f"/api/v1/tournaments/public/{tournament_id}/{endpoint}"
            for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
                r = await client.get(base, params=params)
                assert r.status_code == 422, r.text
                body = r.json()
                assert "code" not in body
                assert isinstance(body.get("detail"), list)
            r = await client.get(base, params={"stage_id": "not-a-uuid"})
            assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_public_stats_field_sets_are_closed(
    db_session, tenant_factory, monkeypatch
):
    """RF-036/RNF-001: la lista cerrada se verifica con **datos reales**.

    Siembra un torneo publicado con un partido confirmado, tres jugadores con
    gol y una foto firmable, así que las **dos** rutas devuelven filas: la
    versión anterior de esta prueba pedía un torneo sin datos, recorría un `[]`
    y por eso la comparación de claves no comprobaba nada. Aquí el recuento es
    lo primero que se exige y una respuesta vacía es un fallo explícito.

    **Discriminación (comprobación manual, sin tocar el router desde la prueba).**
    Borra a mano `response_model=list[PublicPlayerStatsResponse]` (y el de
    equipos) del decorador en `backend/app/modules/tournaments/router.py` y
    ejecuta `pytest -q tests/test_public_stats_endpoints.py`: se ponen en rojo
    esta prueba y `test_la_lista_cerrada_depende_del_response_model_de_la_ruta`,
    porque la ruta deja de declarar su modelo y el filtro deja de aplicarse.
    Ojo: **quitar solo el `response_model` no añade claves al JSON de hoy**,
    porque el handler de jugadores elimina `photo_consent` antes de devolver y
    `sign_crest_rows` sustituye `crest_object_key` por `crest_url`; por eso la
    garantía de que el modelo siga declarado es una aserción propia. Que la
    comparación exacta **no sea vacua** lo demuestra
    `test_la_comprobacion_de_lista_cerrada_no_es_vacua`, que alimenta al
    ayudante con `photo_consent`, `crest_object_key` y una clave ausente.
    """

    _skip_if_no_db()
    tenant = await tenant_factory("Fields Owner")
    await set_tenant_context(db_session, tenant)
    tournament_id, _seeded = await _seed_players_with_photos(db_session, tenant)
    await clear_rls_context(db_session)

    storage = _StatsStorage()
    _use_stats_storage(monkeypatch, storage)

    # Jugadores: los tres del sembrado. Equipos: los dos del partido.
    expected_rows = {"player-stats": 3, "team-stats": 2}

    async with _public_api(db_session) as client:
        for endpoint, model in STATS_MODELS.items():
            response = await client.get(
                f"/api/v1/tournaments/public/{tournament_id}/{endpoint}"
            )
            assert response.status_code == 200, describe_response(
                f"{endpoint} lista cerrada", response
            )
            rows = response.json()
            # Raíz del defecto anterior: `[]` hacía pasar la comprobación.
            assert len(rows) == expected_rows[endpoint], (
                f"{endpoint}: se sembraron {expected_rows[endpoint]} filas y "
                f"llegaron {len(rows)}; una respuesta vacía no verifica la lista "
                "cerrada de campos públicos"
            )
            # Comprobación manual de la discriminación: si se borra el
            # `response_model` del decorador, esta misma prueba se pone en rojo
            # aquí (la ruta deja de declarar el modelo y deja de filtrar).
            declared = _stats_route(endpoint).response_model
            assert get_origin(declared) is list and get_args(declared)[0] is model, (
                f"{endpoint}: la ruta no declara response_model={model.__name__} "
                f"(declara {declared!r}), así que el modelo no filtra la respuesta"
            )
            problems = _closed_field_problems(rows, model)
            assert not problems, f"{endpoint}: {'; '.join(problems)}"
            for row in rows:
                leaked = sorted(set(row) & SENSITIVE)
                assert not leaked, (endpoint, leaked)
                # RF-006/RF-022: cada fila trae su posición global.
                assert isinstance(row["rank"], int) and row["rank"] >= 1, endpoint

    # La firma ocurrió de verdad: el sembrado trae una foto con consentimiento,
    # así que `photo_url` viajó como enlace y no como clave interna.
    assert storage.calls, "el sembrado de la lista cerrada no llegó a firmar"


def test_la_comprobacion_de_lista_cerrada_no_es_vacua():
    """T17: la comparación exacta señala una clave de más y una de menos.

    Es la prueba que demuestra que el ayudante no acepta cualquier cosa: sin
    ella, una comparación mal escrita (o un `rows` vacío) pasaría en verde y el
    defecto de la validación volvería.
    """

    complete = {name: None for name in PublicTeamStatsResponse.model_fields}

    leaked = dict(complete)
    leaked["crest_object_key"] = "private/organizations/x/crests/x.png"
    problems = _closed_field_problems([leaked], PublicTeamStatsResponse)
    assert any("crest_object_key" in problem for problem in problems), problems
    assert any("internas" in problem for problem in problems), problems

    injected = {name: None for name in PublicPlayerStatsResponse.model_fields}
    injected["photo_consent"] = True
    problems = _closed_field_problems([injected], PublicPlayerStatsResponse)
    assert any("photo_consent" in problem for problem in problems), problems

    missing = dict(complete)
    missing.pop("crest_url")
    problems = _closed_field_problems([missing], PublicTeamStatsResponse)
    assert any("ausentes" in problem and "crest_url" in problem for problem in problems), (
        problems
    )

    # Y la comparación sola **no** distingue «sin filas» de «lista cerrada»:
    # de ahí el recuento explícito de la prueba con datos reales.
    assert _closed_field_problems([], PublicTeamStatsResponse) == []


def _stats_route(endpoint: str):
    """Ruta real de la app para ``GET /tournaments/public/{id}/{endpoint}``."""

    expected_name = "public_player_stats" if endpoint == "player-stats" else "public_team_stats"
    for route in api.routes:
        name = getattr(route, "name", None)
        methods = getattr(route, "methods", set()) or set()
        if name == expected_name and "GET" in methods:
            return route
    suffix = f"/{endpoint}"
    for route in api.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.endswith(suffix) and "GET" in methods:
            return route
    raise AssertionError(f"no hay ruta GET para {endpoint}")


def test_la_lista_cerrada_depende_del_response_model_de_la_ruta():
    """T17/RF-036: sin `response_model` el modelo deja de filtrar la respuesta.

    Comprobación manual de la discriminación: borra
    `response_model=list[...]` del decorador de la ruta en
    `backend/app/modules/tournaments/router.py` y ejecuta
    `pytest -q tests/test_public_stats_endpoints.py`; esta prueba pasa a rojo
    porque la ruta deja de declarar el modelo (`response_model` vale `None`) y
    la lista cerrada deja de aplicarse. La prueba no modifica el router en
    tiempo de ejecución: lee las rutas ya registradas por la app real.
    """

    for endpoint, model in STATS_MODELS.items():
        route = _stats_route(endpoint)
        declared = route.response_model
        assert get_origin(declared) is list, (endpoint, declared)
        assert get_args(declared)[0] is model, (endpoint, declared)


async def _create_published_tournament_with_teams(
    session: AsyncSession, tenant, names: tuple[str, ...]
) -> tuple:
    """Published tournament with one stage and the given enrolled teams.

    The team table is fed only by confirmed matches, so this seeds exactly what
    the ``team-stats`` endpoint reads: no events, no lineups, no rosters.
    """

    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', DATE '2026-01-01', 'draft', '{}'::jsonb)
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "name": f"T022rank {uuid4().hex[:8]}"},
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

    team_ids = []
    for index, name in enumerate(names, start=1):
        team_id = (
            await session.execute(
                text("""
                    INSERT INTO teams (organization_id, name, short_code)
                    VALUES (:organization_id, :name, :short_code)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "name": name,
                    "short_code": f"R{index}{uuid4().hex[:5].upper()}",
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
        team_ids.append(team_id)

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
    return tournament_id, version_id, stage_id, team_ids


async def _insert_finished_match(
    session: AsyncSession,
    tenant,
    *,
    tournament_id,
    version_id,
    stage_id,
    home_team_id,
    away_team_id,
    home_score: int,
    away_score: int,
) -> None:
    """Insert an already confirmed regular-time result (the closing shape)."""

    await session.execute(
        text("""
            INSERT INTO matches
                (organization_id, tournament_id, tournament_version_id, stage_id,
                 home_team_id, away_team_id, status, matchday,
                 home_score_regular, away_score_regular, home_score, away_score,
                 resolution_type, result_confirmed)
            VALUES
                (:organization_id, :tournament_id, :version_id, :stage_id,
                 :home_team_id, :away_team_id, 'finished', 1,
                 :home_score, :away_score, :home_score, :away_score,
                 'regular', TRUE)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "home_team_id": str(home_team_id),
            "away_team_id": str(away_team_id),
            "home_score": home_score,
            "away_score": away_score,
        },
    )


@pytest.mark.asyncio
async def test_team_stats_rank_does_not_restart_when_paginating(db_session, tenant_factory):
    """RF-006/RF-022: el `rank` se calcula sobre el conjunto completo."""

    _skip_if_no_db()
    tenant = await tenant_factory("Rank Teams")
    await set_tenant_context(db_session, tenant)
    tournament_id, version_id, stage_id, team_ids = await _create_published_tournament_with_teams(
        db_session, tenant, ("Alfa", "Bravo", "Charlie")
    )
    alfa, bravo, charlie = team_ids
    # Alfa: 5 goles a favor y 0 en contra; Charlie: 0 y 2; Bravo: 0 y 3.
    await _insert_finished_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=alfa,
        away_team_id=bravo,
        home_score=3,
        away_score=0,
    )
    await _insert_finished_match(
        db_session,
        tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        home_team_id=alfa,
        away_team_id=charlie,
        home_score=2,
        away_score=0,
    )
    await clear_rls_context(db_session)

    path = f"/api/v1/tournaments/public/{tournament_id}/team-stats"
    async with _public_api(db_session) as client:
        full = await client.get(path)
        assert full.status_code == 200, full.text
        rows = full.json()
        assert [row["team_name"] for row in rows] == ["Alfa", "Charlie", "Bravo"]
        assert [row["rank"] for row in rows] == [1, 2, 3]

        second_page = await client.get(path, params={"offset": 1, "limit": 1})
        assert second_page.status_code == 200, second_page.text
        # Continúa la numeración global: 2, no un 1 reiniciado por la página.
        assert [row["rank"] for row in second_page.json()] == [2]


class _StatsStorage:
    """Stub del almacenamiento para la firma en lote (T4).

    ``test_public_stats_endpoints.py`` no tenía doble de firma porque sus casos
    anteriores no sembraban fotos. Se reutiliza la forma de ``PublicStorage`` de
    ``test_crest_public.py``: registra la única llamada por respuesta y devuelve
    URLs deterministas, de modo que la prueba mide **qué claves llegan a
    firmar** (lo que decide RF-034) y no la red ni el proveedor S3.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def signed_urls(self, keys, expires_seconds=None):
        keys = tuple(keys)
        self.calls.append(keys)
        return SignedUrls(
            urls={
                key: f"https://signed.test/{index}.jpg"
                for index, key in enumerate(keys)
            }
        )


async def _insert_roster_with_photo(
    session: AsyncSession,
    tenant,
    *,
    tournament_id,
    team_id,
    dorsal_number: int,
    is_active: bool,
    photo_consent: bool,
    label: str,
):
    """Create a player and a roster with (or without) a stored photo.

    The photo metadata is written through ``set_roster_photo_object`` because
    the application role only holds column-scoped grants (010). A retired roster
    keeps both the consent and the object key in the row: that is exactly the
    case RF-034 forbids publishing.
    """

    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name="Foto",
        last_name=label,
        reference_year=2026,
    )
    roster_id = (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, :dorsal_number,
                     :photo_consent, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": dorsal_number,
                "photo_consent": photo_consent,
            },
        )
    ).scalar_one()

    photo_key = (
        f"private/organizations/{tenant.organization_id}/tournaments/{tournament_id}"
        f"/rosters/{roster_id}/photo-{label}.jpg"
    )
    if photo_consent:
        # ``set_roster_photo_object`` exige consentimiento: sin él no hay clave
        # guardada. El caso de C (vigente sin consentimiento) se demuestra con
        # una fila sin foto almacenada.
        await session.execute(
            text("SELECT set_roster_photo_object(:roster_id, :photo_object_key)"),
            {"roster_id": str(roster_id), "photo_object_key": photo_key},
        )
    else:
        photo_key = None

    if not is_active:
        await session.execute(
            text("UPDATE rosters SET is_active = FALSE WHERE id = :roster_id"),
            {"roster_id": str(roster_id)},
        )

    return player_id, roster_id, photo_key


async def _seed_players_with_photos(session: AsyncSession, tenant):
    """Published tournament where A is current, B retired and C has no consent.

    Every player scores one goal in a confirmed match, so all three appear in
    the public table with their history. Only A meets the full photo condition
    (current roster + consent + stored photo); B keeps consent and a stored
    photo but is retired (RF-034); C is current but never consented.
    """

    tournament_id, version_id, stage_id, team_ids = (
        await _create_published_tournament_with_teams(
            session, tenant, ("Foto Local", "Foto Visitante")
        )
    )
    home_team_id, away_team_id = team_ids

    match_id = (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'live', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()

    segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 90, 'active')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()

    seeded = {
        "current_with_photo": {"is_active": True, "photo_consent": True},
        "retired_with_photo": {"is_active": False, "photo_consent": True},
        "current_without_consent": {"is_active": True, "photo_consent": False},
    }
    result = {}
    for index, (label, flags) in enumerate(seeded.items(), start=1):
        player_id, roster_id, photo_key = await _insert_roster_with_photo(
            session,
            tenant,
            tournament_id=tournament_id,
            team_id=home_team_id,
            dorsal_number=index,
            label=label,
            **flags,
        )
        await session.execute(
            text("""
                INSERT INTO match_rosters
                    (organization_id, match_id, tournament_id, roster_id, player_id,
                     team_id, role, is_valid)
                VALUES
                    (:organization_id, :match_id, :tournament_id, :roster_id, :player_id,
                     :team_id, 'starter', TRUE)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "tournament_id": str(tournament_id),
                "roster_id": str(roster_id),
                "player_id": str(player_id),
                "team_id": str(home_team_id),
            },
        )
        # Un gol por jugador: sin evento no habría fila en la tabla.
        await session.execute(
            text("""
                INSERT INTO match_events
                    (organization_id, match_id, segment_id, team_id, player_id,
                     event_type, minute, added_minute, client_event_id, metadata)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                     'goal', :minute, 0, :client_event_id, '{}'::jsonb)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "team_id": str(home_team_id),
                "player_id": str(player_id),
                "minute": index * 10,
                "client_event_id": str(uuid4()),
            },
        )
        result[label] = {
            "player_id": player_id,
            "roster_id": roster_id,
            "photo_key": photo_key,
        }

    # El acta se confirma: solo entonces las estadísticas cuentan el partido.
    await session.execute(
        text("""
            UPDATE matches
            SET status = 'finished', resolution_type = 'regular',
                home_score_regular = 3, away_score_regular = 0,
                home_score = 3, away_score = 0, result_confirmed = TRUE
            WHERE id = :match_id
        """),
        {"match_id": str(match_id)},
    )
    return tournament_id, result


def _use_stats_storage(monkeypatch, storage: _StatsStorage) -> None:
    monkeypatch.setattr(
        "app.modules.crests.resolver.get_object_storage", lambda: storage
    )


@pytest.mark.asyncio
async def test_retired_roster_never_publishes_a_photo(
    db_session, tenant_factory, monkeypatch
):
    """RF-007, RF-034, RF-008: la foto exige inscripción **vigente**.

    A: vigente + consentimiento + foto → recibe el enlace firmado.
    B: **retirado** + consentimiento + foto → `photo_url` nulo, pero aparece con
       su histórico (el retiro no lo saca de las estadísticas).
    C: vigente sin consentimiento → `photo_url` nulo.
    La llamada de firma solo recibe la clave de A, así que la foto del retirado
    nunca llega al lote y no puede publicarse por error.
    """

    _skip_if_no_db()
    tenant = await tenant_factory("Photo Stats")
    await set_tenant_context(db_session, tenant)
    tournament_id, seeded = await _seed_players_with_photos(db_session, tenant)
    await clear_rls_context(db_session)

    storage = _StatsStorage()
    _use_stats_storage(monkeypatch, storage)

    path = f"/api/v1/tournaments/public/{tournament_id}/player-stats"
    async with _public_api(db_session) as client:
        response = await client.get(path)
        assert response.status_code == 200, response.text
        rows = {row["player_id"]: row for row in response.json()}

    current = rows[str(seeded["current_with_photo"]["player_id"])]
    retired = rows[str(seeded["retired_with_photo"]["player_id"])]
    no_consent = rows[str(seeded["current_without_consent"]["player_id"])]

    # A: la única foto firmada de la respuesta.
    assert current["photo_url"] == "https://signed.test/0.jpg"
    assert "photo_consent" not in current
    # B: retirado lógicamente, con su histórico y sin foto (RF-034).
    assert retired["photo_url"] is None
    assert retired["goals"] == 1
    assert retired["matches_played"] == 1
    # C: vigente pero sin consentimiento (RF-007).
    assert no_consent["photo_url"] is None

    # La clave del retirado no se firmó: la lectura la dejó en nulo y tampoco
    # viajó la de quien no consintió.
    assert storage.calls == [(seeded["current_with_photo"]["photo_key"],)]

async def _insert_goalkeeper(
    session: AsyncSession,
    tenant,
    *,
    tournament_id,
    match_id,
    team_id,
    dorsal_number: int,
    first_name: str,
    last_name: str,
):
    """Jugador + inscripción + planilla válida del partido (una fila de cada)."""

    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name=first_name,
        last_name=last_name,
        reference_year=2026,
    )
    roster_id = (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, :dorsal_number,
                     FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
    await session.execute(
        text("""
            INSERT INTO match_rosters
                (organization_id, match_id, tournament_id, roster_id, player_id,
                 team_id, role, is_valid)
            VALUES
                (:organization_id, :match_id, :tournament_id, :roster_id, :player_id,
                 :team_id, 'starter', TRUE)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "tournament_id": str(tournament_id),
            "roster_id": str(roster_id),
            "player_id": str(player_id),
            "team_id": str(team_id),
        },
    )
    return player_id


async def _publish_formation(
    session: AsyncSession,
    tenant,
    *,
    match_id,
    segment_id,
    team_id,
    formation_code: str,
    players: list[tuple],
) -> None:
    """Publica la formación de un segmento con sus jugadores y posiciones.

    Es la forma real de las tablas de la 007: una fila en `match_team_lineups`
    con `is_public` y `published_at`, más una instantánea por jugador en
    `match_lineup_snapshots`, que es de donde la 031 lee `position_slot` e
    `is_starter`.
    """

    await session.execute(
        text("""
            INSERT INTO match_team_lineups
                (organization_id, match_id, segment_id, team_id, formation_code,
                 is_public, published_at)
            VALUES
                (:organization_id, :match_id, :segment_id, :team_id, :formation_code,
                 TRUE, CURRENT_TIMESTAMP)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "segment_id": str(segment_id),
            "team_id": str(team_id),
            "formation_code": formation_code,
        },
    )
    for player_id, position_slot, is_starter in players:
        await session.execute(
            text("""
                INSERT INTO match_lineup_snapshots
                    (organization_id, match_id, segment_id, team_id, player_id,
                     is_starter, position_slot)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                     :is_starter, :position_slot)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "is_starter": is_starter,
                "position_slot": position_slot,
            },
        )


async def _create_live_match_with_two_segments(session: AsyncSession, tenant):
    """Torneo publicado con un partido `live` 0-0 y dos segmentos (0-45, 45-90).

    El partido nace `live` porque `trg_validate_match_event_context` (009)
    rechaza eventos sobre un acta ya cerrada; se confirma al final del sembrado.
    """

    tournament_id, version_id, stage_id, team_ids = (
        await _create_published_tournament_with_teams(
            session, tenant, ("Portero Local", "Portero Visitante")
        )
    )
    home_team_id, away_team_id = team_ids

    match_id = (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'live', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()

    segment_ids = []
    for number, (start, end) in enumerate(((0, 45), (45, 90)), start=1):
        segment_ids.append(
            (
                await session.execute(
                    text("""
                        INSERT INTO match_segments
                            (organization_id, match_id, segment_number, minute_start,
                             minute_end, status)
                        VALUES
                            (:organization_id, :match_id, :segment_number, :minute_start,
                             :minute_end, 'completed')
                        RETURNING id
                    """),
                    {
                        "organization_id": str(tenant.organization_id),
                        "match_id": str(match_id),
                        "segment_number": number,
                        "minute_start": start,
                        "minute_end": end,
                    },
                )
            ).scalar_one()
        )

    return tournament_id, match_id, home_team_id, segment_ids[0], segment_ids[1]


async def _confirm_goalless_match(session: AsyncSession, match_id) -> None:
    """Cierra el acta 0-0: el local recibe cero goles (portería imbatida)."""

    await session.execute(
        text("""
            UPDATE matches
            SET status = 'finished', resolution_type = 'regular',
                home_score_regular = 0, away_score_regular = 0,
                home_score = 0, away_score = 0, result_confirmed = TRUE
            WHERE id = :match_id
        """),
        {"match_id": str(match_id)},
    )


async def _seed_goalkeeper_change_with_two_published_formations(session: AsyncSession, tenant):
    """Caso 16b: cambio de portero entre dos formaciones publicadas.

    Partido confirmado 0-0 con dos segmentos y **dos** formaciones publicadas
    del equipo local: el `GK` titular del primero sale a los 30' y el `GK` de la
    formación del segundo (allí titular) juega los 60' restantes, así que solo
    el entrante alcanza el umbral. El visitante no publica formación.
    """

    tournament_id, match_id, home_team_id, first_segment, second_segment = (
        await _create_live_match_with_two_segments(session, tenant)
    )

    gk_first = await _insert_goalkeeper(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=home_team_id,
        dorsal_number=1,
        first_name="Titular",
        last_name="Portero",
    )
    gk_second = await _insert_goalkeeper(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=home_team_id,
        dorsal_number=12,
        first_name="Entrante",
        last_name="Portero",
    )

    await _publish_formation(
        session,
        tenant,
        match_id=match_id,
        segment_id=first_segment,
        team_id=home_team_id,
        formation_code="4-3-3",
        players=[(gk_first, "GK", True)],
    )
    await _publish_formation(
        session,
        tenant,
        match_id=match_id,
        segment_id=second_segment,
        team_id=home_team_id,
        formation_code="4-4-2",
        players=[(gk_second, "GK", True)],
    )

    # Cambio de portero a los 30': `player_id` es `player_out_id` (catálogo 015).
    await session.execute(
        text("""
            INSERT INTO match_events
                (organization_id, match_id, segment_id, team_id, player_id,
                 event_type, minute, added_minute, player_out_id, player_in_id,
                 client_event_id, metadata)
            VALUES
                (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                 'substitution', 30, 0, :player_out_id, :player_in_id,
                 :client_event_id, '{}'::jsonb)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "segment_id": str(first_segment),
            "team_id": str(home_team_id),
            "player_id": str(gk_first),
            "player_out_id": str(gk_first),
            "player_in_id": str(gk_second),
            "client_event_id": str(uuid4()),
        },
    )

    await _confirm_goalless_match(session, match_id)
    return tournament_id, {
        "gk_first": gk_first,
        "gk_second": gk_second,
        "team_id": home_team_id,
    }


@pytest.mark.asyncio
async def test_endpoint_attributes_clean_sheet_to_incoming_goalkeeper(db_session, tenant_factory):
    """RF-015/RF-026/16b: el **endpoint** atribuye la portería al portero entrante.

    La ruta de estadísticas debe alimentar la regla con **todas** las formaciones
    publicadas (`public.v_public_match_formations`, migración 031): la del primer
    segmento acredita al titular y la del segundo reconoce al entrante como `GK`,
    que junto a la sustitución de los 30' alcanza los 60 minutos exigidos.
    La prueba que **falla** si el endpoint vuelve a leer solo la última formación
    es la del caso 16 (`test_endpoint_reads_the_first_published_formation_of_the_match`),
    porque allí la formación posterior no tiene `GK`; aquí la última formación sí
    contiene al portero y por eso el caso 16b por sí solo no distingue ambas
    lecturas (comprobado con las dos formas de entrada sobre la misma regla).
    """

    _skip_if_no_db()
    tenant = await tenant_factory("Goalkeeper Stats")
    await set_tenant_context(db_session, tenant)
    tournament_id, seeded = await _seed_goalkeeper_change_with_two_published_formations(
        db_session, tenant
    )
    await clear_rls_context(db_session)

    path = f"/api/v1/tournaments/public/{tournament_id}/player-stats"
    async with _public_api(db_session) as client:
        response = await client.get(path)
        assert response.status_code == 200, response.text
        rows = {row["player_id"]: row for row in response.json()}

    first = rows[str(seeded["gk_first"])]
    second = rows[str(seeded["gk_second"])]

    # 30' jugados el titular y 60' el entrante: solo el segundo cruza el umbral.
    assert second["clean_sheets"] == 1, second
    assert first["clean_sheets"] == 0, first
    # La sustitución acredita a los dos como participantes del partido.
    assert first["matches_played"] == 1, first
    assert second["matches_played"] == 1, second
    # Ninguna otra fila se lleva la portería imbatida del equipo local.
    assert [row["player_id"] for row in rows.values() if row["clean_sheets"] == 1] == [
        str(seeded["gk_second"])
    ]

    # La portería imbatida del **equipo** sigue siendo una, con su portero
    # identificado aparte.
    team_path = f"/api/v1/tournaments/public/{tournament_id}/team-stats"
    async with _public_api(db_session) as client:
        team_response = await client.get(team_path)
        assert team_response.status_code == 200, team_response.text
    home_rows = [
        row for row in team_response.json() if row["team_id"] == str(seeded["team_id"])
    ]
    assert home_rows and home_rows[0]["clean_sheets"] == 1, home_rows


async def _seed_ejected_goalkeeper_with_two_published_formations(session: AsyncSession, tenant):
    """Caso 16: el portero titular sale a los 70' y la formación posterior no tiene `GK`.

    El equipo publica la formación del primer segmento con su `GK` y la del
    segundo ya con un jugador de campo (`ST`) en su lugar, como ocurre cuando el
    portero es expulsado y lo reemplaza alguien de campo. La portería imbatida
    es del portero (70' ≥ 60) y solo se puede atribuir leyendo **también** la
    primera formación: con `v_public_match_lineups` (la última por equipo) el
    cálculo recibiría una única formación sin `GK` y no atribuiría nada.
    """

    tournament_id, match_id, home_team_id, first_segment, second_segment = (
        await _create_live_match_with_two_segments(session, tenant)
    )

    gk = await _insert_goalkeeper(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=home_team_id,
        dorsal_number=1,
        first_name="Expulsado",
        last_name="Portero",
    )
    field_player = await _insert_goalkeeper(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=home_team_id,
        dorsal_number=9,
        first_name="Jugador",
        last_name="DeCampo",
    )

    await _publish_formation(
        session,
        tenant,
        match_id=match_id,
        segment_id=first_segment,
        team_id=home_team_id,
        formation_code="4-3-3",
        players=[(gk, "GK", True)],
    )
    await _publish_formation(
        session,
        tenant,
        match_id=match_id,
        segment_id=second_segment,
        team_id=home_team_id,
        formation_code="4-4-2",
        players=[(field_player, "ST", True)],
    )

    await session.execute(
        text("""
            INSERT INTO match_events
                (organization_id, match_id, segment_id, team_id, player_id,
                 event_type, minute, added_minute, client_event_id, metadata)
            VALUES
                (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                 'red_card', 70, 0, :client_event_id, :metadata)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "segment_id": str(second_segment),
            "team_id": str(home_team_id),
            "player_id": str(gk),
            "client_event_id": str(uuid4()),
            "metadata": '{"red_card_type": "direct_red"}',
        },
    )

    await _confirm_goalless_match(session, match_id)
    return tournament_id, {"gk": gk, "field_player": field_player}


@pytest.mark.asyncio
async def test_endpoint_reads_the_first_published_formation_of_the_match(
    db_session, tenant_factory
):
    """RF-015/16: la ruta lee la **primera** formación publicada, no solo la última.

    Es la guarda que distingue la proyección de la 031 de `v_public_match_lineups`
    (`DISTINCT ON (match_id, team_id)`): si el endpoint siguiera leyendo la vista
    pública de la spec 021, el cálculo recibiría una única formación —la del
    segundo segmento, sin `GK`— y esta respuesta daría `clean_sheets: 0`.
    """

    _skip_if_no_db()
    tenant = await tenant_factory("Ejected Goalkeeper Stats")
    await set_tenant_context(db_session, tenant)
    tournament_id, seeded = await _seed_ejected_goalkeeper_with_two_published_formations(
        db_session, tenant
    )
    await clear_rls_context(db_session)

    path = f"/api/v1/tournaments/public/{tournament_id}/player-stats"
    async with _public_api(db_session) as client:
        response = await client.get(path)
        assert response.status_code == 200, response.text
        rows = {row["player_id"]: row for row in response.json()}

    keeper = rows[str(seeded["gk"])]
    replacement = rows[str(seeded["field_player"])]

    # Expulsado a los 70': sus minutos superan el umbral de 60.
    assert keeper["clean_sheets"] == 1, keeper
    assert keeper["red_cards"] == 1, keeper
    assert keeper["matches_played"] == 1, keeper
    # El reemplazo es de campo: no es portero identificable en ninguna formación.
    assert replacement["clean_sheets"] == 0, replacement


# ---------------------------------------------------------------------------
# T18 — aislamiento entre organizaciones con datos reales (RF-017, spec 020)
# ---------------------------------------------------------------------------


async def _insert_rostered_player(
    session: AsyncSession,
    tenant,
    *,
    tournament_id,
    match_id,
    team_id,
    dorsal_number: int,
    first_name: str,
    last_name: str,
):
    """Jugador con inscripción en el torneo y planilla válida del partido.

    Envoltorio con nombre general de :func:`_insert_goalkeeper` (misma forma:
    jugador + ``rosters`` + ``match_rosters``), que el sembrado de aislamiento
    usa también para los goleadores de campo.
    """

    return await _insert_goalkeeper(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=team_id,
        dorsal_number=dorsal_number,
        first_name=first_name,
        last_name=last_name,
    )


async def _seed_organization_stats(
    session: AsyncSession,
    tenant,
    *,
    label: str,
    scoring_side: str,
    goals: int,
) -> dict:
    """Torneo publicado de **una** organización con datos propios y distinguibles.

    Siembra lo mínimo que produce filas en las dos tablas públicas: un partido
    confirmado, dos equipos con nombre propio de la organización (``label``) y,
    en el equipo ganador, una formación publicada con su portero titular y un
    jugador por gol. El resultado es determinista y **distinto** por
    organización: ``player-stats`` devuelve ``1 + goals`` filas (portero y
    goleadores) y ``team-stats`` devuelve 2 (los dos equipos del partido). El
    marcador es ``goals``-0, así que el ganador suma la portería imbatida y el
    primer goleador recibe además una amarilla: el recuento disciplinario
    también distingue filas.

    Los eventos se insertan con el partido ``live`` porque
    ``trg_validate_match_event_context`` (009) rechaza eventos sobre un acta
    cerrada; el acta se confirma al final. Sin fotos ni escudos: la respuesta no
    necesita el almacenamiento para firmar nada.
    """

    if scoring_side not in {"home", "away"}:
        raise AssertionError(f"lado de marcador desconocido: {scoring_side}")

    home_name = f"Org {label} Local"
    away_name = f"Org {label} Visitante"
    tournament_id, version_id, stage_id, team_ids = (
        await _create_published_tournament_with_teams(
            session, tenant, (home_name, away_name)
        )
    )
    home_team_id, away_team_id = team_ids
    if scoring_side == "home":
        winning_team_id, losing_team_id = home_team_id, away_team_id
        winning_name, losing_name = home_name, away_name
        home_score, away_score = goals, 0
    else:
        winning_team_id, losing_team_id = away_team_id, home_team_id
        winning_name, losing_name = away_name, home_name
        home_score, away_score = 0, goals

    match_id = (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'live', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()

    segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start,
                     minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 90, 'completed')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()

    keeper_id = await _insert_rostered_player(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=winning_team_id,
        dorsal_number=1,
        first_name=f"Portero {label}",
        last_name=f"Imbatido {label}",
    )
    scorers = []
    formation_players = [(keeper_id, "GK", True)]
    for index in range(1, goals + 1):
        scorer_id = await _insert_rostered_player(
            session,
            tenant,
            tournament_id=tournament_id,
            match_id=match_id,
            team_id=winning_team_id,
            dorsal_number=1 + index,
            first_name=f"Goleador {label} {index}",
            last_name=f"Gol {label} {index}",
        )
        scorers.append(scorer_id)
        formation_players.append((scorer_id, "ST", True))

    # Un gol por goleador (minutos 10, 20, ...) y una amarilla al primero: el
    # acta tiene eventos de las dos tablas y el recuento es distinguible.
    events = [
        (index * 10, "goal", scorer_id)
        for index, scorer_id in enumerate(scorers, start=1)
    ]
    events.append((5, "yellow_card", scorers[0]))
    for minute, event_type, player_id in events:
        await session.execute(
            text("""
                INSERT INTO match_events
                    (organization_id, match_id, segment_id, team_id, player_id,
                     event_type, minute, added_minute, client_event_id, metadata)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                     :event_type, :minute, 0, :client_event_id, '{}'::jsonb)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "team_id": str(winning_team_id),
                "player_id": str(player_id),
                "event_type": event_type,
                "minute": minute,
                "client_event_id": str(uuid4()),
            },
        )

    await _publish_formation(
        session,
        tenant,
        match_id=match_id,
        segment_id=segment_id,
        team_id=winning_team_id,
        formation_code="4-4-2",
        players=formation_players,
    )

    # El acta se confirma: solo entonces las estadísticas cuentan el partido.
    await session.execute(
        text("""
            UPDATE matches
            SET status = 'finished', resolution_type = 'regular',
                home_score_regular = :home_score, away_score_regular = :away_score,
                home_score = :home_score, away_score = :away_score,
                result_confirmed = TRUE
            WHERE id = :match_id
        """),
        {
            "match_id": str(match_id),
            "home_score": home_score,
            "away_score": away_score,
        },
    )

    return {
        "label": label,
        "tournament_id": tournament_id,
        "stage_id": stage_id,
        "winning_team_id": winning_team_id,
        "winning_team_name": winning_name,
        "losing_team_id": losing_team_id,
        "losing_team_name": losing_name,
        "team_ids": tuple(team_ids),
        "keeper_id": keeper_id,
        "scorers": tuple(scorers),
        "player_ids": (keeper_id, *scorers),
        "goals": goals,
        "home_score": home_score,
        "away_score": away_score,
    }


def _expected_players(seeded: dict) -> dict[str, dict]:
    """Filas exactas que ``player-stats`` debe devolver para ese sembrado."""

    expected = {
        str(seeded["keeper_id"]): {
            "goals": 0,
            "yellow_cards": 0,
            "red_cards": 0,
            "clean_sheets": 1,
            "matches_played": 1,
        }
    }
    for index, scorer_id in enumerate(seeded["scorers"]):
        expected[str(scorer_id)] = {
            "goals": 1,
            "yellow_cards": 1 if index == 0 else 0,
            "red_cards": 0,
            "clean_sheets": 0,
            "matches_played": 1,
        }
    return expected


def _expected_teams(seeded: dict) -> dict[str, dict]:
    """Filas exactas que ``team-stats`` debe devolver para ese sembrado."""

    goals = seeded["goals"]
    winner = {
        "goals_for": seeded["home_score"] if seeded["home_score"] else seeded["away_score"],
        "goals_against": seeded["away_score"] if seeded["home_score"] else seeded["home_score"],
        "clean_sheets": 1,
    }
    loser = {
        "goals_for": winner["goals_against"],
        "goals_against": winner["goals_for"],
        "clean_sheets": 0,
    }
    assert winner["goals_for"] == goals, (seeded["label"], winner)
    return {
        seeded["winning_team_name"]: winner,
        seeded["losing_team_name"]: loser,
    }


@pytest.mark.asyncio
async def test_two_organizations_with_data_do_not_mix_public_stats(
    db_session, tenant_factory
):
    """RF-017 (spec 020), RNF-005, RF-036 (spec 022): aislamiento con datos reales.

    La prueba anterior de aislamiento sembraba **dos torneos publicados sin
    partidos, eventos ni plantillas** y comparaba ``[] == []``, así que no
    demostraba nada. Aquí cada organización tiene un torneo publicado con
    partido confirmado, eventos, formaciones publicadas y plantillas, y las dos
    producen recuentos **distintos** —A: 2 jugadores y 1-0; B: 3 jugadores y
    0-2—, de modo que una respuesta vacía, mezclada o duplicada falla con el
    recuento exacto en la mano. Los identificadores de las dos organizaciones
    se comprueban disjuntos antes de preguntar, para que una fuga sea
    atribuible.

    **Filtro por fase ajena.** Pedir el torneo de A con el ``stage_id`` de B (y
    al revés) devuelve ``200`` con lista vacía y no amplía el resultado: es el
    contrato ya vigente de las lecturas públicas, no una invención de esta
    prueba. La spec 020 lo fija en su caso límite 11 —«``stage_id`` o
    ``group_id`` ajeno o inexistente en una lectura pública: la respuesta es una
    lista vacía, no un error ni una fuga de datos (RF-017)»— y es lo que ya
    hacen `standings` y `matches` (ver ``test_public_access_matrix.py``). El
    filtro por la fase **propia** se comprueba en la misma prueba y devuelve
    exactamente lo mismo que sin filtro: es lo que demuestra que el ``[]``
    ajeno no viene de que el filtro vacíe siempre la tabla.
    """

    _skip_if_no_db()
    first = await tenant_factory("Stats Isolation A")
    second = await tenant_factory("Stats Isolation B")

    await set_tenant_context(db_session, first)
    seeded_a = await _seed_organization_stats(
        db_session, first, label="A", scoring_side="home", goals=1
    )

    await set_tenant_context(db_session, second)
    seeded_b = await _seed_organization_stats(
        db_session, second, label="B", scoring_side="away", goals=2
    )
    await clear_rls_context(db_session)

    # El sembrado produce datos distintos: sin identificadores disjuntos la
    # prueba no podría distinguir una fuga de una coincidencia.
    assert set(seeded_a["player_ids"]).isdisjoint(seeded_b["player_ids"])
    assert set(seeded_a["team_ids"]).isdisjoint(seeded_b["team_ids"])
    assert seeded_a["tournament_id"] != seeded_b["tournament_id"]
    assert seeded_a["stage_id"] != seeded_b["stage_id"]
    assert seeded_a["winning_team_name"] != seeded_b["winning_team_name"]
    assert seeded_a["winning_team_name"] != seeded_a["losing_team_name"]

    expected_players = {
        "A": _expected_players(seeded_a),
        "B": _expected_players(seeded_b),
    }
    expected_teams = {
        "A": _expected_teams(seeded_a),
        "B": _expected_teams(seeded_b),
    }
    # A produce 2 filas de jugador y B 3: un recuento vacío o intercambiado
    # falla, que es lo que la versión anterior no podía detectar.
    assert len(expected_players["A"]) == 2
    assert len(expected_players["B"]) == 3
    assert len(expected_teams["A"]) == len(expected_teams["B"]) == 2

    seeded = {"A": seeded_a, "B": seeded_b}
    responses: dict[tuple[str, str], list] = {}

    async with _public_api(db_session) as client:
        for label, side in seeded.items():
            base = f"/api/v1/tournaments/public/{side['tournament_id']}"
            for endpoint in ("player-stats", "team-stats"):
                response = await client.get(f"{base}/{endpoint}")
                assert response.status_code == 200, describe_response(
                    f"{label} {endpoint}", response
                )
                responses[(label, endpoint)] = response.json()

        for label, side in seeded.items():
            other_label = "B" if label == "A" else "A"
            other = seeded[other_label]
            # Los identificadores del sembrado son ``UUID`` y los de la respuesta
            # llegan como cadena JSON: se comparan ya normalizados, porque un
            # ``UUID`` nunca es igual a su texto y la comprobación sería vacua.
            other_team_ids = {str(team_id) for team_id in other["team_ids"]}

            # --- Jugadores: solo los de la organización pedida -------------
            rows = responses[(label, "player-stats")]
            expected = expected_players[label]
            assert len(rows) == len(expected), (
                f"{label} player-stats: se sembraron {len(expected)} jugadores y "
                f"llegaron {len(rows)}"
            )
            by_player = {row["player_id"]: row for row in rows}
            assert len(by_player) == len(rows), f"{label} player-stats: filas duplicadas"
            assert set(by_player) == set(expected), (
                f"{label} player-stats: los identificadores de la respuesta no son "
                "exactamente los sembrados en esa organización"
            )
            for player_id, fields in expected.items():
                for field, value in fields.items():
                    assert by_player[player_id][field] == value, (
                        f"{label} player-stats: campo {field}"
                    )
            foreign_players = set(expected_players[other_label])
            for row in rows:
                # Afirmación positiva: el jugador se publica con su equipo de la
                # organización pedida (los dos equipos propios están sembrados
                # con nombre propio, así que una mezcla se ve por nombre).
                assert row["team_name"] == side["winning_team_name"], (
                    f"{label} player-stats: equipo del jugador {row['player_id']}"
                )
                assert row["player_id"] not in foreign_players, (
                    f"{label} player-stats: jugador de la organización {other_label}"
                )
                assert row["team_id"] not in other_team_ids, (
                    f"{label} player-stats: equipo de la organización {other_label}"
                )

            # --- Equipos: solo los dos del partido de esa organización -----
            team_rows = responses[(label, "team-stats")]
            assert len(team_rows) == len(expected_teams[label]), (
                f"{label} team-stats: se sembraron {len(expected_teams[label])} "
                f"equipos y llegaron {len(team_rows)}"
            )
            by_name = {row["team_name"]: row for row in team_rows}
            assert set(by_name) == set(expected_teams[label]), (
                f"{label} team-stats: los nombres de equipo no son exactamente los "
                "sembrados en esa organización"
            )
            for name, fields in expected_teams[label].items():
                for field, value in fields.items():
                    assert by_name[name][field] == value, (
                        f"{label} team-stats: campo {field} de {name}"
                    )
            assert {row["team_id"] for row in team_rows}.isdisjoint(other_team_ids), (
                f"{label} team-stats: identificador de equipo de la organización "
                f"{other_label}"
            )

            # --- Filtro por fase ajena: vacío, sin fuga ni ampliación ------
            base = f"/api/v1/tournaments/public/{side['tournament_id']}"
            for endpoint in ("player-stats", "team-stats"):
                own_stage = await client.get(
                    f"{base}/{endpoint}", params={"stage_id": str(side["stage_id"])}
                )
                assert own_stage.status_code == 200, describe_response(
                    f"{label} {endpoint} fase propia", own_stage
                )
                assert own_stage.json() == responses[(label, endpoint)], (
                    f"{label} {endpoint}: el filtro por su propia fase cambió el "
                    "resultado, así que el caso de la fase ajena no probaría nada"
                )

                foreign_stage = await client.get(
                    f"{base}/{endpoint}", params={"stage_id": str(other["stage_id"])}
                )
                assert foreign_stage.status_code == 200, describe_response(
                    f"{label} {endpoint} fase ajena", foreign_stage
                )
                assert foreign_stage.json() == [], (
                    f"{label} {endpoint}: el filtro por la fase de la organización "
                    f"{other_label} debe devolver lista vacía (spec 020, caso límite "
                    "11) y no ampliar el resultado"
                )
