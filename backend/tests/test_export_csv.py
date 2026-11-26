"""Catálogo y formato CSV de las exportaciones (spec 048, T1)."""

from __future__ import annotations

import csv
import io

import pytest

from app.modules.exports import catalog
from app.modules.exports.csv_format import ExportTooLarge, neutralize, render_csv

BOM = b"\xef\xbb\xbf"


def _parse(data: bytes) -> list[list[str]]:
    assert data.startswith(BOM)
    return list(csv.reader(io.StringIO(data[len(BOM):].decode("utf-8"), newline="")))


def test_catalog_constants_follow_the_spec():
    assert catalog.EXPORT_KINDS == ("standings", "calendar", "player-stats", "team-stats", "rosters")
    assert catalog.REPORT_KIND == "match-report"
    assert catalog.MAX_ROWS == 10_000
    assert catalog.LANGS == ("es", "en")


EXPECTED_HEADERS = {
    "standings": (
        ["Fase", "Grupo", "Posición", "Equipo", "PJ", "G", "E", "P", "GF", "GC", "DG", "Puntos", "Juego limpio"],
        ["Stage", "Group", "Position", "Team", "P", "W", "D", "L", "GF", "GA", "GD", "Points", "Fair play"],
    ),
    "calendar": (
        ["Fase", "Grupo", "Llave", "Jornada", "Fecha (UTC)", "Local", "Visitante", "Estado",
         "Goles local", "Goles visitante", "Penales local", "Penales visitante"],
        ["Stage", "Group", "Bracket", "Matchday", "Date (UTC)", "Home", "Away", "Status",
         "Home goals", "Away goals", "Home penalties", "Away penalties"],
    ),
    "player-stats": (
        ["Posición", "Nombre", "Apellidos", "Equipo", "Goles", "Amarillas", "Rojas",
         "Porterías imbatidas", "Partidos jugados"],
        ["Position", "First name", "Last name", "Team", "Goals", "Yellow cards", "Red cards",
         "Clean sheets", "Matches played"],
    ),
    "team-stats": (
        ["Posición", "Equipo", "Código", "GF", "GC", "Porterías imbatidas", "Juego limpio"],
        ["Position", "Team", "Code", "GF", "GA", "Clean sheets", "Fair play"],
    ),
    "rosters": (
        ["Equipo", "Dorsal", "Nombre", "Apellidos", "Estado", "Consentimiento de imagen"],
        ["Team", "Number", "First name", "Last name", "Status", "Image consent"],
    ),
    "match-report": (
        ["Sección", "Equipo", "Dorsal", "Jugador", "Función o tipo", "Minuto", "Detalle"],
        ["Section", "Team", "Number", "Player", "Role or type", "Minute", "Detail"],
    ),
}


@pytest.mark.parametrize("kind", sorted(EXPECTED_HEADERS))
def test_headers_are_fixed_and_translated(kind):
    es, en = EXPECTED_HEADERS[kind]
    assert catalog.header(kind, "es") == es
    assert catalog.header(kind, "en") == en
    assert len(catalog.column_keys(kind)) == len(es)
    assert len(set(catalog.column_keys(kind))) == len(es)


def test_header_rejects_unknown_kind_and_lang():
    with pytest.raises(KeyError):
        catalog.header("audit", "es")
    with pytest.raises(ValueError):
        catalog.header("standings", "fr")


def test_columns_never_include_forbidden_fields():
    forbidden = ("age", "birth", "date", "document", "national", "email", "photo", "crest", "url")
    for kind in (*catalog.EXPORT_KINDS, catalog.REPORT_KIND):
        for key in catalog.column_keys(kind):
            assert not set(key.split("_")) & set(forbidden), (kind, key)


@pytest.mark.parametrize(
    ("group", "code", "es", "en"),
    [
        ("match_status", "suspended", "Suspendido", "Suspended"),
        ("match_status", "administrative_resolution", "Resolución administrativa", "Administrative resolution"),
        ("event_type", "own_goal", "Gol en propia", "Own goal"),
        ("event_type", "red_card", "Tarjeta roja", "Red card"),
        ("official_role", "main_referee", "Árbitro principal", "Referee"),
        ("resolution", "walkover", "W.O.", "Walkover"),
        ("lineup_role", "substitute", "Suplente", "Substitute"),
        ("report_section", "event", "Hecho", "Event"),
        ("roster_status", "retired", "Retirado", "Withdrawn"),
        ("yes_no", "yes", "Sí", "Yes"),
        ("walkover_reason", "no_show", "Incomparecencia", "No-show"),
        ("walkover_reason", "insufficient_players", "Jugadores insuficientes", "Insufficient players"),
    ],
)
def test_labels_are_translated(group, code, es, en):
    assert catalog.label(group, code, "es") == es
    assert catalog.label(group, code, "en") == en


def test_label_groups_cover_the_database_catalogs():
    assert set(catalog.LABELS["match_status"]) == {
        "scheduled", "live", "finished", "suspended", "cancelled", "administrative_resolution"}
    assert set(catalog.LABELS["event_type"]) == {
        "goal", "own_goal", "penalty_goal", "yellow_card", "red_card", "substitution", "foul"}
    assert set(catalog.LABELS["official_role"]) == {
        "main_referee", "assistant_referee_1", "assistant_referee_2", "fourth_official", "match_commissioner"}
    assert set(catalog.LABELS["resolution"]) == {"regular", "extra_time", "penalties", "walkover", "administrative"}
    assert set(catalog.LABELS["walkover_reason"]) == {
        "no_show",
        "withdrawal",
        "insufficient_players",
        "sanction",
    }
    assert set(catalog.LABELS["report_section"]) == {"result", "official", "lineup", "event"}


def test_unknown_label_code_is_returned_as_is():
    assert catalog.label("event_type", "new_type", "es") == "new_type"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_prefixes_are_neutralized(prefix):
    assert neutralize(f"{prefix}HYPERLINK(1)") == f"'{prefix}HYPERLINK(1)"


@pytest.mark.parametrize("value", ["Halcones", "", " =espacio delante", "Ñandú FC", "1-0"])
def test_plain_text_is_kept(value):
    assert neutralize(value) == value


@pytest.mark.parametrize("value", [-3, 0, 12, None])
def test_non_text_values_are_not_neutralized(value):
    assert neutralize(value) == value


def test_render_csv_writes_utf8_bom_commas_and_crlf():
    data = render_csv(["Equipo", "DG"], [["Ñandú", -3], ["Águilas", None]])
    assert data.startswith(BOM)
    assert data[len(BOM):] == "Equipo,DG\r\nÑandú,-3\r\nÁguilas,\r\n".encode()


def test_render_csv_escapes_commas_quotes_and_newlines():
    rows = [['Club "A", B', "línea 1\nlínea 2"]]
    assert _parse(render_csv(["a", "b"], rows)) == [["a", "b"], ['Club "A", B', "línea 1\nlínea 2"]]


def test_render_csv_neutralizes_malicious_team_and_player_names():
    rows = [["=cmd|' /C calc'!A0", "@SUM(1+1)", "+1", "-2+3", -3]]
    parsed = _parse(render_csv(["Equipo", "Jugador", "x", "y", "DG"], rows))
    assert parsed[1] == ["'=cmd|' /C calc'!A0", "'@SUM(1+1)", "'+1", "'-2+3", "-3"]


def test_render_csv_neutralizes_the_header_too():
    assert _parse(render_csv(["=x"], []))[0] == ["'=x"]


def test_render_csv_with_no_rows_has_only_the_header():
    assert render_csv(["a", "b"], []) == BOM + b"a,b\r\n"


def test_render_csv_accepts_exactly_the_row_limit():
    data = render_csv(["n"], [[i] for i in range(catalog.MAX_ROWS)])
    assert len(_parse(data)) == catalog.MAX_ROWS + 1


def test_render_csv_rejects_more_than_the_row_limit():
    with pytest.raises(ExportTooLarge):
        render_csv(["n"], [[i] for i in range(catalog.MAX_ROWS + 1)])


def test_render_csv_honours_a_custom_limit():
    with pytest.raises(ExportTooLarge):
        render_csv(["n"], [[1], [2], [3]], max_rows=2)


def test_render_csv_rejects_rows_with_the_wrong_width():
    with pytest.raises(ValueError):
        render_csv(["a", "b"], [["solo uno"]])
