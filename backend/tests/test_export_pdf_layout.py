"""Composición de los documentos PDF a partir de las filas CSV (spec 050, D4)."""

from __future__ import annotations

import pytest

from app.modules.exports import builders, catalog
from app.modules.exports.pdf_layout import standings_document

INFO = {"organization": "Liga Ñandú", "tournament": "Copa <2026>"}


def _row(stage, group, rank, team, points):
    return [stage, group, rank, team, 3, 3, 0, 0, 7, 1, 6, points, 0]


ROWS = [
    _row("Grupos", "A", 1, "Leones", 9),
    _row("Grupos", "A", 2, "Tigres", 6),
    _row("Grupos", "B", 1, "Pumas", 7),
    _row("Final", None, 1, "Leones", 3),
]


def test_standings_document_has_title_and_header_info():
    doc = standings_document(ROWS, INFO, "es")
    assert doc.title == "Clasificación"
    assert tuple(doc.meta) == (("Organización", "Liga Ñandú"), ("Torneo", "Copa <2026>"))
    assert standings_document(ROWS, INFO, "en").title == "Standings"
    assert tuple(standings_document(ROWS, INFO, "en").meta)[0] == ("Organization", "Liga Ñandú")


def test_standings_are_split_by_stage_and_group_in_the_csv_order():
    doc = standings_document(ROWS, INFO, "es")
    assert [section.title for section in doc.sections] == ["Grupos · A", "Grupos · B", "Final"]
    assert [len(section.rows) for section in doc.sections] == [2, 1, 1]


def test_sections_carry_exactly_the_csv_cells_without_stage_and_group():
    doc = standings_document(ROWS, INFO, "es")
    header = catalog.header("standings", "es")
    for section in doc.sections:
        assert list(section.header) == header[2:]
    cells = [list(row) for section in doc.sections for row in section.rows]
    assert cells == [row[2:] for row in ROWS]


def test_header_follows_lang():
    doc = standings_document(ROWS, INFO, "en")
    assert list(doc.sections[0].header) == catalog.header("standings", "en")[2:]


@pytest.mark.parametrize(("lang", "notice"), [("es", "Sin clasificación todavía"), ("en", "No standings yet")])
def test_empty_standings_have_a_notice(lang, notice):
    [section] = standings_document([], INFO, lang).sections
    assert section.rows == ()
    assert section.empty_notice == notice


def test_unknown_lang_is_rejected():
    with pytest.raises(ValueError):
        standings_document(ROWS, INFO, "fr")


# ---------------------------------------------------------------- acta (T3)

from datetime import UTC, datetime  # noqa: E402

from app.modules.exports.pdf_layout import match_report_document  # noqa: E402

REPORT_INFO = {
    **INFO, "home": "Leones", "away": "Tigres & Cía", "stage": "Grupos",
    "match_date": datetime(2026, 11, 20, 20, 30, tzinfo=UTC),
}
REPORT_ROWS = [
    ["Resultado", "Leones", None, None, "Local", None, 2],
    ["Resultado", "Tigres & Cía", None, None, "Visitante", None, 1],
    ["Resultado", None, None, None, "Tiempo reglamentario", None, None],
    ["Oficial", None, None, "Olga Observadora", "Árbitro principal", None, None],
    ["Alineación", "Leones", 1, "Ana Pérez", "Titular", None, None],
    ["Alineación", "Leones", 9, "Bea Núñez", "Suplente", None, None],
    ["Alineación", "Tigres & Cía", 4, "Carla Ruiz", "Titular", None, None],
    ["Hecho", "Leones", 9, "Bea Núñez", "Gol", "30", None],
]


def test_report_document_has_title_and_match_header():
    doc = match_report_document(REPORT_ROWS, REPORT_INFO, "es")
    assert doc.title == "Acta del partido"
    assert tuple(doc.meta) == (
        ("Organización", "Liga Ñandú"), ("Torneo", "Copa <2026>"), ("Partido", "Leones vs Tigres & Cía"),
        ("Fase", "Grupos"), ("Fecha", "2026-11-20 20:30 (UTC)"),
    )
    en = match_report_document([], REPORT_INFO, "en")
    assert en.title == "Match report"
    assert [label for label, _ in en.meta] == ["Organization", "Tournament", "Match", "Stage", "Date"]


def test_report_without_date_or_stage_omits_those_lines():
    info = {**REPORT_INFO, "stage": None, "match_date": None}
    labels = [label for label, _ in match_report_document(REPORT_ROWS, info, "es").meta]
    assert labels == ["Organización", "Torneo", "Partido"]


def test_report_blocks_follow_the_csv_sections_and_split_lineups_by_team():
    doc = match_report_document(REPORT_ROWS, REPORT_INFO, "es")
    assert [section.title for section in doc.sections] == [
        "Resultado", "Oficiales", "Alineación · Leones", "Alineación · Tigres & Cía", "Hechos"]
    header = catalog.header(catalog.REPORT_KIND, "es")[1:]
    assert all(list(section.header) == header for section in doc.sections)
    cells = [list(row) for section in doc.sections for row in section.rows]
    assert cells == [row[1:] for row in REPORT_ROWS]


def test_walkover_report_has_no_events_block():
    rows = [row for row in REPORT_ROWS if row[0] != "Hecho"]
    titles = [section.title for section in match_report_document(rows, REPORT_INFO, "es").sections]
    assert "Hechos" not in titles


def test_report_blocks_in_english():
    rows = [["Result", "Lions", None, None, "Home", None, 2], ["Event", "Lions", 9, "Bea", "Goal", "30", None]]
    titles = [section.title for section in match_report_document(rows, REPORT_INFO, "en").sections]
    assert titles == ["Result", "Events"]


def test_homonymous_stages_and_groups_stay_apart_with_their_keys():
    rows = [["Liga", None, 1, "A", 1, 1, 0, 0, 2, 0, 2, 3, 0],
            ["Liga", None, 1, "B", 1, 1, 0, 0, 2, 0, 2, 3, 0]]
    assert len(standings_document(rows, INFO, "es").sections) == 1
    doc = standings_document(rows, INFO, "es", [("s1", None), ("s2", None)])
    assert [section.title for section in doc.sections] == ["Liga", "Liga"]
    assert [len(section.rows) for section in doc.sections] == [1, 1]


def test_homonymous_teams_get_one_lineup_block_per_side():
    rows = [["Resultado", "Leones", None, None, "Local", None, 1],
            ["Alineación", "Leones", 1, "Ana", "Titular", None, None],
            ["Alineación", "Leones", 2, "Eva", "Titular", None, None]]
    keys = [("result",), ("lineup", 0), ("lineup", 1)]
    doc = match_report_document(rows, REPORT_INFO, "es", keys)
    assert [section.title for section in doc.sections] == ["Resultado", "Alineación · Leones", "Alineación · Leones"]


def test_report_keys_follow_the_builder_rows():
    match = {"home_team_id": "h", "away_team_id": "a", "home_team_name": "Leones", "away_team_name": "Leones",
             "home_score": 1, "away_score": 0, "resolution_type": "regular"}
    lineup = [{"team_id": "a", "player_id": "p2", "role": "starter"},
              {"team_id": "h", "player_id": "p1", "role": "starter"}]
    players = {"p1": {"first_name": "Ana", "last_name": "A", "dorsal_number": 1},
               "p2": {"first_name": "Eva", "last_name": "E", "dorsal_number": 2}}
    keyed = builders.match_report_keyed(match, [], lineup, [], players, "es")
    assert [row for _, row in keyed] == builders.match_report_rows(match, [], lineup, [], players, "es")
    assert [key for key, row in keyed if row[0] == "Alineación"] == [("lineup", 0), ("lineup", 1)]


def test_standings_keys_follow_the_builder_rows():
    data = [{"stage_name": "Liga", "stage_order": order, "stage_id": f"s{order}", "group_name": None,
             "group_id": None, "team_id": f"t{order}", "team_name": "X", "played": 0, "won": 0, "drawn": 0,
             "lost": 0, "goals_for": 0, "goals_against": 0, "goal_difference": 0, "points": 0,
             "fair_play_points": 0, "rank": 1} for order in (2, 1)]
    assert builders.standings_section_keys(data) == [("s1", None), ("s2", None)]
