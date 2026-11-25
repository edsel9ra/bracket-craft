"""Exportaciones CSV del Workspace contra PostgreSQL (spec 048, T3; opt-in ``RUN_DATABASE_TESTS=1``)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.exports import catalog
from migration_helpers import connect
from test_match_assists_db import close, committed_application, goal_and_red_report, seeded_match
from test_notification_api import add_member
from test_request_schema_strictness import walk_routes

BOM = "\ufeff"
NOT_FOUND = {"detail": "Torneo no encontrado"}
TOURNAMENT_KINDS = ("standings", "calendar", "player-stats", "team-stats")


@dataclass
class Exports:
    client: AsyncClient
    admin: object
    owner: AuthContext
    viewer: AuthContext
    stranger: AuthContext
    match: object
    foreign_tournament_id: object
    context: AuthContext | None = None


@pytest.fixture
async def exports(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        owner, match = await seeded_match(engine)
        await close(engine, owner, match.match_id, goal_and_red_report(match))
        admin = await connect(database_admin_url, engine.url.database)
        try:
            # Un partido en juego en la versión ya publicada: la base de datos de prueba
            # desactiva sus triggers solo para insertarlo (la estructura publicada es inmutable).
            await admin.execute("SET session_replication_role = replica")
            await admin.execute(
                """INSERT INTO matches (organization_id, tournament_id, tournament_version_id, stage_id,
                       home_team_id, away_team_id, status, matchday, match_date)
                   VALUES ($1,$2,$3,$4,$6,$5,'live',2,'2026-12-01T15:00:00-05:00')""",
                owner.organization_id, match.tournament_id, match.version_id, match.stage_id,
                match.home_team_id, match.away_team_id)
            await admin.execute("SET session_replication_role = DEFAULT")
            user = await admin.fetchval("""INSERT INTO users (email,password_hash,full_name)
                VALUES ('observador-048@example.test','hash','Olga Observadora') RETURNING id""")
            viewer = await add_member(admin, owner.organization_id, user, "viewer")
            stranger, foreign = await seeded_match(engine)

            async def database():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    yield session

            state = Exports(None, admin, owner, viewer, stranger, match, foreign.tournament_id, owner)

            async def auth_context():
                return state.context

            api.dependency_overrides[get_db] = database
            api.dependency_overrides[get_auth_context] = auth_context
            try:
                async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
                    state.client = client
                    yield state
            finally:
                api.dependency_overrides.clear()
        finally:
            await admin.close()


def url(tournament_id, kind):
    return f"/api/v1/tournaments/{tournament_id}/exports/{kind}"


async def download(exports, kind, lang=None, tournament_id=None):
    params = {"lang": lang} if lang else {}
    return await exports.client.get(url(tournament_id or exports.match.tournament_id, kind), params=params)


def parse(response) -> list[list[str]]:
    text = response.content.decode("utf-8")
    assert text.startswith(BOM)
    return list(csv.reader(io.StringIO(text[len(BOM):], newline="")))


async def team_names(exports):
    rows = await exports.admin.fetch(
        "SELECT id, name, short_code FROM teams WHERE id = ANY($1::uuid[])",
        [exports.match.home_team_id, exports.match.away_team_id])
    return {row["id"]: (row["name"], row["short_code"]) for row in rows}


async def test_route_is_registered():
    routes = {(path, method) for path, route in walk_routes(api.routes)
              if "/exports/" in path for method in route.methods}
    assert ("/api/v1/tournaments/{tournament_id}/exports/{kind}", "GET") in routes


@pytest.mark.parametrize("kind", TOURNAMENT_KINDS)
async def test_each_export_is_a_csv_download(exports, kind):
    response = await download(exports, kind)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    short = str(exports.match.tournament_id)[:8]
    assert response.headers["content-disposition"] == f'attachment; filename="{kind}-{short}.csv"'
    assert parse(response)[0] == catalog.header(kind, "es")


async def test_headers_and_labels_follow_lang(exports):
    response = await download(exports, "calendar", "en")
    rows = parse(response)
    assert rows[0] == catalog.header("calendar", "en")
    assert rows[2][7] == "Finished"


async def test_standings_come_from_the_published_version(exports):
    names = await team_names(exports)
    rows = parse(await download(exports, "standings"))[1:]
    assert len(rows) == 2
    home, away = names[exports.match.home_team_id][0], names[exports.match.away_team_id][0]
    by_team = {row[3]: row for row in rows}
    assert by_team[home][2] == "1" and by_team[home][11] == "3"
    assert by_team[away][2] == "2" and by_team[away][11] == "0"
    assert by_team[home][0] == "Group stage"


async def test_calendar_shows_the_closed_result(exports):
    names = await team_names(exports)
    rows = parse(await download(exports, "calendar"))[2:]
    assert rows == [[
        "Group stage", "", "", "1", "",
        names[exports.match.home_team_id][0], names[exports.match.away_team_id][0],
        "Finalizado", "1", "0", "", "",
    ]]


async def test_calendar_hides_the_score_of_an_open_match(exports):
    rows = parse(await download(exports, "calendar"))[1:]
    assert rows[0][3:5] == ["2", "2026-12-01T20:00:00Z"]
    assert rows[0][7:] == ["En juego", "", "", "", ""]
    assert rows[1][7] == "Finalizado"


async def test_player_stats_count_the_current_events(exports):
    rows = parse(await download(exports, "player-stats"))[1:]
    scorer = await exports.admin.fetchrow(
        "SELECT first_name, last_name FROM players WHERE id=$1", exports.match.home_scorer_id)
    sent_off = await exports.admin.fetchrow(
        "SELECT first_name, last_name FROM players WHERE id=$1", exports.match.away_scorer_id)
    by_name = {(row[1], row[2]): row for row in rows}
    assert by_name[(scorer["first_name"], scorer["last_name"])][4:7] == ["1", "0", "0"]
    assert by_name[(sent_off["first_name"], sent_off["last_name"])][4:7] == ["0", "0", "1"]
    assert rows[0][0] == "1"


async def test_team_stats_have_names_and_codes_without_ids(exports):
    names = await team_names(exports)
    response = await download(exports, "team-stats")
    rows = parse(response)[1:]
    home_name, home_code = names[exports.match.home_team_id]
    assert rows[0][:5] == ["1", home_name, home_code, "1", "0"]
    body = response.content.decode("utf-8")
    for identifier in (exports.match.home_team_id, exports.match.away_team_id, exports.match.tournament_id):
        assert str(identifier) not in body


async def test_exports_never_carry_identifiers_or_personal_data(exports):
    secrets_ = await exports.admin.fetch(
        "SELECT id, national_id_hmac FROM players WHERE organization_id=$1", exports.owner.organization_id)
    for kind in TOURNAMENT_KINDS:
        body = (await download(exports, kind)).content.decode("utf-8")
        for row in secrets_:
            assert str(row["id"]) not in body
            if row["national_id_hmac"]:
                assert row["national_id_hmac"] not in body
        assert "@example" not in body


@pytest.mark.parametrize("kind", TOURNAMENT_KINDS)
async def test_without_published_version_only_the_header_is_returned(exports, kind):
    await exports.admin.execute(
        "UPDATE tournaments SET status='draft', published_version_id=NULL WHERE id=$1",
        exports.match.tournament_id)
    response = await download(exports, kind)
    assert response.status_code == 200
    assert parse(response) == [catalog.header(kind, "es")]


async def test_archived_tournament_can_still_be_exported(exports):
    await exports.admin.execute("UPDATE tournaments SET status='archived' WHERE id=$1", exports.match.tournament_id)
    assert len(parse(await download(exports, "standings"))) == 3


async def test_viewer_can_download(exports):
    exports.context = exports.viewer
    for kind in TOURNAMENT_KINDS:
        assert (await download(exports, kind)).status_code == 200


@pytest.mark.parametrize("kind", TOURNAMENT_KINDS)
async def test_foreign_and_missing_tournaments_get_the_same_404(exports, kind):
    foreign = await download(exports, kind, tournament_id=exports.foreign_tournament_id)
    missing = await download(exports, kind, tournament_id=uuid4())
    assert (foreign.status_code, foreign.json()) == (404, NOT_FOUND)
    assert (missing.status_code, missing.json()) == (404, NOT_FOUND)
    exports.context = exports.stranger
    other = await download(exports, kind)
    assert (other.status_code, other.json()) == (404, NOT_FOUND)


async def test_unknown_kind_and_lang_are_rejected(exports):
    assert (await download(exports, "audit")).status_code == 422
    assert (await download(exports, "standings", "fr")).status_code == 422


async def test_exports_over_the_limit_fail_without_a_file(exports, monkeypatch):
    monkeypatch.setattr(catalog, "MAX_ROWS", 1)
    response = await download(exports, "standings")
    assert response.status_code == 422
    assert response.json() == {"detail": "EXPORT_TOO_LARGE"}
    assert not response.headers["content-type"].startswith("text/csv")


async def test_exports_are_read_inside_the_tenant_context(exports):
    # Con RLS forzado, una organización nunca lee filas de otra aunque conozca el id.
    exports.context = exports.stranger
    response = await download(exports, "player-stats", tournament_id=exports.foreign_tournament_id)
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    owner_players = await exports.admin.fetch(
        "SELECT last_name FROM players WHERE organization_id=$1", exports.owner.organization_id)
    assert owner_players
    assert all(f",{row['last_name']}," not in body for row in owner_players)
