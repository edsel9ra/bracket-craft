"""Composición de los documentos PDF a partir de las filas CSV (spec 050, D4)."""

from __future__ import annotations

import pytest

from app.modules.exports import catalog
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
