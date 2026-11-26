"""Exportaciones CSV del Workspace contra PostgreSQL (spec 048, T3; opt-in ``RUN_DATABASE_TESTS=1``)."""

from __future__ import annotations

import csv
import io
import json
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
TOURNAMENT_KINDS = ("standings", "calendar", "player-stats", "team-stats", "rosters")
UNAUDITED_KINDS = TOURNAMENT_KINDS[:4]


@dataclass
class Exports:
    client: AsyncClient
    admin: object
    owner: AuthContext
    viewer: AuthContext
    stranger: AuthContext
    match: object
    foreign_tournament_id: object
    live_match_id: object
    foreign_match_id: object
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
            live_match_id = await admin.fetchval(
                """INSERT INTO matches (organization_id, tournament_id, tournament_version_id, stage_id,
                       home_team_id, away_team_id, status, matchday, match_date)
                   VALUES ($1,$2,$3,$4,$6,$5,'live',2,'2026-12-01T15:00:00-05:00') RETURNING id""",
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

            state = Exports(None, admin, owner, viewer, stranger, match, foreign.tournament_id,
                            live_match_id, foreign.match_id, owner)

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


@pytest.mark.parametrize("kind", UNAUDITED_KINDS)
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


# ---------------------------------------------------------------- plantillas (T4)


async def roster_audits(admin):
    rows = await admin.fetch(
        """SELECT organization_id, entity_type, entity_id, payload, performed_by_member_id
           FROM administrative_audit_logs WHERE action = 'EXPORT_TOURNAMENT_ROSTERS' ORDER BY performed_at, id""")
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]


async def expected_rosters(exports):
    return await exports.admin.fetch(
        """SELECT t.name AS team, r.dorsal_number, p.first_name, p.last_name, r.is_active, r.photo_consent
           FROM rosters r JOIN players p ON p.id = r.player_id JOIN teams t ON t.id = r.team_id
           WHERE r.tournament_id = $1""", exports.match.tournament_id)


async def test_rosters_list_every_player_with_status_and_consent(exports):
    await exports.admin.execute(
        "UPDATE rosters SET is_active = FALSE WHERE player_id = $1 AND tournament_id = $2",
        exports.match.home_assist_id, exports.match.tournament_id)
    await exports.admin.execute(
        """UPDATE rosters SET photo_consent = TRUE, photo_object_key = 'org/fotos/secreta-048.jpg'
           WHERE player_id = $1 AND tournament_id = $2""",
        exports.match.home_scorer_id, exports.match.tournament_id)
    response = await download(exports, "rosters")
    assert response.status_code == 200, response.text
    rows = parse(response)
    assert rows[0] == catalog.header("rosters", "es")
    expected = sorted(
        [row["team"], str(row["dorsal_number"]), row["first_name"], row["last_name"],
         "Activo" if row["is_active"] else "Retirado", "Sí" if row["photo_consent"] else "No"]
        for row in await expected_rosters(exports))
    assert sorted(rows[1:]) == expected
    assert ["Retirado"] == [row[4] for row in rows[1:] if row[4] == "Retirado"]
    assert ["Sí"] == [row[5] for row in rows[1:] if row[5] == "Sí"]
    body = response.content.decode("utf-8")
    assert "secreta-048" not in body
    for row in await exports.admin.fetch(
            "SELECT id, national_id_hmac FROM players WHERE organization_id=$1", exports.owner.organization_id):
        assert str(row["id"]) not in body and row["national_id_hmac"] not in body


async def test_rosters_do_not_depend_on_the_published_version(exports):
    await exports.admin.execute(
        "UPDATE tournaments SET status='draft', published_version_id=NULL WHERE id=$1",
        exports.match.tournament_id)
    rows = parse(await download(exports, "rosters", "en"))
    assert rows[0] == catalog.header("rosters", "en")
    assert len(rows) - 1 == len(await expected_rosters(exports))


async def test_roster_download_is_audited_with_the_row_count_only(exports):
    response = await download(exports, "rosters")
    count = len(parse(response)) - 1
    assert count > 0
    assert await roster_audits(exports.admin) == [{
        "organization_id": exports.owner.organization_id,
        "entity_type": "tournaments",
        "entity_id": exports.match.tournament_id,
        "payload": {"row_count": count},
        "performed_by_member_id": exports.owner.organization_user_id,
    }]
    for row in await expected_rosters(exports):
        assert row["first_name"] not in json.dumps((await roster_audits(exports.admin))[0]["payload"])


async def test_viewer_roster_download_is_audited_as_the_viewer(exports):
    exports.context = exports.viewer
    assert (await download(exports, "rosters")).status_code == 200
    [entry] = await roster_audits(exports.admin)
    assert entry["performed_by_member_id"] == exports.viewer.organization_user_id


async def test_other_exports_leave_no_audit_entry(exports):
    before = await exports.admin.fetchval("SELECT count(*) FROM administrative_audit_logs")
    for kind in UNAUDITED_KINDS:
        assert (await download(exports, kind)).status_code == 200
    assert await exports.admin.fetchval("SELECT count(*) FROM administrative_audit_logs") == before


async def test_failed_roster_exports_leave_no_audit_entry(exports, monkeypatch):
    missing = await download(exports, "rosters", tournament_id=exports.foreign_tournament_id)
    assert (missing.status_code, missing.json()) == (404, NOT_FOUND)
    monkeypatch.setattr(catalog, "MAX_ROWS", 1)
    too_large = await download(exports, "rosters")
    assert (too_large.status_code, too_large.json()) == (422, {"detail": "EXPORT_TOO_LARGE"})
    assert await roster_audits(exports.admin) == []


# ---------------------------------------------------------------- acta (T5)

MATCH_NOT_FOUND = {"detail": "Partido no encontrado"}


async def download_report(exports, match_id=None, lang=None):
    params = {"lang": lang} if lang else {}
    return await exports.client.get(f"/api/v1/matches/{match_id or exports.match.match_id}/export", params=params)


def section(rows, name):
    return [row for row in rows[1:] if row[0] == name]


async def test_report_route_is_registered():
    routes = {(path, method) for path, route in walk_routes(api.routes) for method in route.methods}
    assert ("/api/v1/matches/{match_id}/export", "GET") in routes


async def test_report_of_a_closed_match_has_result_lineup_and_events(exports):
    names = await team_names(exports)
    home, away = names[exports.match.home_team_id][0], names[exports.match.away_team_id][0]
    response = await download_report(exports)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    short = str(exports.match.match_id)[:8]
    assert response.headers["content-disposition"] == f'attachment; filename="match-report-{short}.csv"'
    rows = parse(response)
    assert rows[0] == catalog.header(catalog.REPORT_KIND, "es")
    assert section(rows, "Resultado") == [
        ["Resultado", home, "", "", "Local", "", "1"],
        ["Resultado", away, "", "", "Visitante", "", "0"],
        ["Resultado", "", "", "", "Tiempo reglamentario", "", ""],
    ]
    valid = await exports.admin.fetchval(
        "SELECT count(*) FROM match_rosters WHERE match_id=$1 AND is_valid", exports.match.match_id)
    lineup = section(rows, "Alineación")
    assert len(lineup) == valid and lineup[0][1] == home
    scorer = await exports.admin.fetchrow(
        "SELECT first_name, last_name FROM players WHERE id=$1", exports.match.home_scorer_id)
    events = section(rows, "Hecho")
    assert [(row[1], row[3], row[4], row[5]) for row in events] == [
        (home, f"{scorer['first_name']} {scorer['last_name']}", "Gol", "30"),
        (away, events[1][3], "Tarjeta roja", "60"),
    ]
    assert events[0][2] == "9"


async def test_report_lists_officials_without_email(exports):
    await exports.admin.execute(
        """INSERT INTO match_officials (organization_id, match_id, organization_user_id, official_role)
           VALUES ($1,$2,$3,'main_referee')""",
        exports.owner.organization_id, exports.match.match_id, exports.viewer.organization_user_id)
    response = await download_report(exports, lang="en")
    assert section(parse(response), "Official") == [["Official", "", "", "Olga Observadora", "Referee", "", ""]]
    assert "observador-048@example.test" not in response.content.decode("utf-8")


async def test_report_of_an_open_match_is_a_conflict(exports):
    response = await download_report(exports, exports.live_match_id)
    assert (response.status_code, response.json()) == (409, {"detail": "MATCH_NOT_CLOSED"})


async def test_foreign_and_missing_matches_get_the_same_404(exports):
    foreign = await download_report(exports, exports.foreign_match_id)
    missing = await download_report(exports, uuid4())
    assert (foreign.status_code, foreign.json()) == (404, MATCH_NOT_FOUND)
    assert (missing.status_code, missing.json()) == (404, MATCH_NOT_FOUND)
    exports.context = exports.stranger
    other = await download_report(exports)
    assert (other.status_code, other.json()) == (404, MATCH_NOT_FOUND)


async def test_viewer_can_download_the_report(exports):
    exports.context = exports.viewer
    assert (await download_report(exports)).status_code == 200


async def test_rectified_report_uses_the_current_version_without_voided_events(exports):
    org, match_id = exports.owner.organization_id, exports.match.match_id
    goal = await exports.admin.fetchrow(
        "SELECT segment_id, team_id, player_id FROM match_events WHERE match_id=$1 AND event_type='goal'", match_id)
    request = await exports.admin.fetchval(
        """INSERT INTO match_report_rectification_requests
               (organization_id, match_id, base_version_number, proposed_report, reason,
                requested_by_user_id, requested_by_member_id)
           VALUES ($1,$2,1,'{}','Corrección',$3,$4) RETURNING id""",
        org, match_id, exports.owner.user_id, exports.owner.organization_user_id)
    version = await exports.admin.fetchval(
        """INSERT INTO match_report_versions
               (organization_id, match_id, version_number, supersedes_version_number, resolution_type,
                home_score_regular, away_score_regular, home_score, away_score, request_id, published_by_user_id)
           VALUES ($1,$2,2,1,'regular',2,0,2,0,$3,$4) RETURNING id""",
        org, match_id, request, exports.owner.user_id)
    await exports.admin.execute(
        """INSERT INTO match_report_version_events
               (organization_id, version_id, match_id, segment_id, team_id, player_id,
                event_type, minute, client_event_id, is_voided)
           SELECT $1,$2,$3,$4,$5,$6,'goal',e.minute,e.client_id,e.voided
           FROM (VALUES (70,'late',FALSE),(20,'early',FALSE),(80,'voided',TRUE)) AS e(minute, client_id, voided)""",
        org, version, match_id, goal["segment_id"], goal["team_id"], goal["player_id"])
    rows = parse(await download_report(exports))
    assert [row[6] for row in section(rows, "Resultado")[:2]] == ["2", "0"]
    assert [(row[4], row[5]) for row in section(rows, "Hecho")] == [("Gol", "20"), ("Gol", "70")]


async def test_walkover_report_has_the_reason_and_no_events(exports):
    await exports.admin.execute("SET session_replication_role = replica")
    await exports.admin.execute(
        """UPDATE matches SET status='finished', result_confirmed=TRUE, resolution_type='walkover',
               resolution_reason='no_show', home_score_regular=3, away_score_regular=0,
               home_score=3, away_score=0, winner_team_id=home_team_id
           WHERE id=$1""", exports.live_match_id)
    await exports.admin.execute("SET session_replication_role = DEFAULT")
    rows = parse(await download_report(exports, exports.live_match_id))
    assert section(rows, "Resultado")[-1] == ["Resultado", "", "", "", "W.O.", "", "Incomparecencia"]
    assert section(rows, "Hecho") == []


async def test_report_over_the_limit_fails_without_a_file(exports, monkeypatch):
    monkeypatch.setattr(catalog, "MAX_ROWS", 1)
    response = await download_report(exports)
    assert (response.status_code, response.json()) == (422, {"detail": "EXPORT_TOO_LARGE"})


async def test_report_rejects_unknown_lang(exports):
    assert (await download_report(exports, lang="fr")).status_code == 422
