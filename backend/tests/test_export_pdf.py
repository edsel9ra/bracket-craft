"""Renderizador PDF puro de las exportaciones (spec 050, T1)."""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime

import pytest
from pypdf import PdfReader

from app.modules.exports import catalog
from app.modules.exports.csv_format import ExportTooLarge
from app.modules.exports.pdf_format import PdfDocument, PdfSection, render_pdf

GENERATED_AT = datetime(2026, 11, 26, 15, 4, 59, tzinfo=UTC)
A4 = (595.2756, 841.8898)


def _doc(sections, *, title="Clasificación", meta=(("Organización", "Liga Ñandú"), ("Torneo", "Copa 2026"))):
    return PdfDocument(title=title, meta=tuple(meta), sections=tuple(sections))


def _section(rows, *, title="Fase 1 · Grupo A", header=("Pos.", "Equipo", "Puntos"), empty=None):
    return PdfSection(title=title, header=tuple(header), rows=tuple(tuple(r) for r in rows), empty_notice=empty)


def _pages(data: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def _text(data: bytes) -> str:
    return "\n".join(_pages(data))


def _many_rows(count: int):
    return [(index, f"Equipo {index}", index * 3) for index in range(1, count + 1)]


def test_catalog_declares_closed_pdf_kinds_and_texts():
    assert catalog.PDF_KINDS == ("standings", "match-report")
    for key in ("generated_at", "page"):
        assert set(catalog.PDF_TEXTS[key]) == {"es", "en"}


def test_render_is_a4_portrait_pdf_with_header_and_generation_time():
    data = render_pdf(_doc([_section([(1, "Leones", 9)])]), "es", GENERATED_AT)
    assert data.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(data))
    box = reader.pages[0].mediabox
    assert (float(box.width), float(box.height)) == pytest.approx(A4, abs=0.1)
    text = _text(data)
    for expected in ("Clasificación", "Organización", "Liga Ñandú", "Torneo", "Copa 2026",
                     "Fase 1 · Grupo A", "Leones", "Generado el 2026-11-26 15:04 (UTC)", "Página 1 de 1"):
        assert expected in text


def test_english_labels():
    text = _text(render_pdf(_doc([_section([(1, "Lions", 9)])], title="Standings"), "en", GENERATED_AT))
    assert "Generated on 2026-11-26 15:04 (UTC)" in text
    assert "Page 1 of 1" in text


def test_unknown_lang_is_rejected():
    with pytest.raises(ValueError):
        render_pdf(_doc([_section([])]), "fr", GENERATED_AT)


def test_long_table_paginates_with_repeated_header_and_page_numbers():
    pages = _pages(render_pdf(_doc([_section(_many_rows(150))]), "es", GENERATED_AT))
    total = len(pages)
    assert total > 1
    for number, page in enumerate(pages, start=1):
        assert f"Página {number} de {total}" in page
        assert "Pos." in page and "Puntos" in page


def test_accents_and_latin_letters_are_selectable_text():
    names = "Núñez Peña · Łukasz Dvořák · Ångström · Çağlar · Øyvind"
    text = _text(render_pdf(_doc([_section([(1, names, 3)])]), "es", GENERATED_AT))
    assert names in text


def test_fonts_are_embedded():
    reader = PdfReader(io.BytesIO(render_pdf(_doc([_section([(1, "Leones", 9)])]), "es", GENERATED_AT)))
    fonts = reader.pages[0]["/Resources"]["/Font"]
    names = {str(fonts[key].get_object()["/BaseFont"]) for key in fonts}
    assert any("Archivo" in name for name in names)
    for key in fonts:
        descendant = fonts[key].get_object()
        assert "/Type1" != str(descendant.get("/Subtype"))


@pytest.mark.parametrize("name", ['<b>Equipo</b> & "Socios"', "A & B <script>x</script>", "O'Higgins <br/>"])
def test_markup_in_names_is_shown_literally(name):
    data = render_pdf(_doc([_section([(1, name, 3)])], meta=(("Torneo", name),)), "es", GENERATED_AT)
    text = _text(data)
    assert text.count(name) == 2


def test_long_names_wrap_without_losing_text():
    name = "Club Deportivo " + "Muy" * 35 + " Largo de la Ciudad"
    assert len(name) > 120
    data = render_pdf(_doc([_section([(1, name, 3)])]), "es", GENERATED_AT)
    flattened = "".join(_text(data).split())
    assert "".join(name.split()) in flattened


def test_none_cells_render_empty_and_numbers_as_text():
    text = _text(render_pdf(_doc([_section([(None, "Leones", -2)])]), "es", GENERATED_AT))
    assert "None" not in text
    assert "-2" in text


def test_empty_section_shows_notice():
    text = _text(render_pdf(_doc([_section([], title=None, empty="Sin clasificación todavía")]), "es", GENERATED_AT))
    assert "Sin clasificación todavía" in text


def test_row_width_mismatch_is_rejected():
    with pytest.raises(ValueError):
        render_pdf(_doc([_section([(1, "Leones")])]), "es", GENERATED_AT)


def test_row_limit_counts_all_sections():
    render_pdf(_doc([_section(_many_rows(2)), _section(_many_rows(1))]), "es", GENERATED_AT, max_rows=3)
    with pytest.raises(ExportTooLarge):
        render_pdf(_doc([_section(_many_rows(2)), _section(_many_rows(2))]), "es", GENERATED_AT, max_rows=3)


def test_default_limit_is_ten_thousand_rows():
    with pytest.raises(ExportTooLarge):
        render_pdf(_doc([_section(_many_rows(catalog.MAX_ROWS + 1))]), "es", GENERATED_AT)


def test_invariant_output_is_deterministic():
    doc = _doc([_section(_many_rows(5))])
    assert render_pdf(doc, "es", GENERATED_AT, invariant=True) == render_pdf(doc, "es", GENERATED_AT, invariant=True)


def test_large_documents_render_under_five_seconds():
    standings = _doc([_section(_many_rows(8), title=f"Grupo {group}") for group in "ABCDEFGH"])
    header = ("Sección", "Equipo", "Dorsal", "Persona", "Detalle", "Minuto")
    report = _doc([
        _section([("Resultado", "Leones", None, None, "2", None)] * 3, header=header),
        _section([("Oficial", None, None, f"Árbitro {i}", "Principal", None) for i in range(5)], header=header),
        _section([("Alineación", "Leones", n, f"Jugador {n}", "Titular", None) for n in range(44)], header=header),
        _section([("Hecho", "Leones", n % 22, f"Jugador {n}", "Gol", f"{n}'") for n in range(60)], header=header),
    ], title="Acta del partido")
    started = time.perf_counter()
    for doc in (standings, report):
        assert render_pdf(doc, "es", GENERATED_AT).startswith(b"%PDF-")
    assert time.perf_counter() - started < 5


@pytest.mark.parametrize("lang", ["es", "en"])
def test_numbers_and_minutes_never_split_across_lines(lang):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from app.modules.exports.pdf_format import FONT, column_widths
    available = A4[0] - 2 * 18 * 72 / 25.4
    long_team = "Club Deportivo Muy Largo de la Ciudad Capital " * 3
    standings = catalog.header("standings", lang)[2:]
    row = [10, long_team, 103, 99, 4, 0, 1103, 1000, -103, 309, -12]
    widths = column_widths(standings, [row], available)
    assert sum(widths) == pytest.approx(available)
    for value, width in zip(row, widths, strict=True):
        if value is not row[1]:
            assert width >= stringWidth(str(value), FONT, 8.5) + 6
    report = catalog.header(catalog.REPORT_KIND, lang)[1:]
    row = [long_team, 99, long_team, "Tarjeta amarilla", "90+12", "Asistencia: " + long_team]
    widths = column_widths(report, [row], available)
    assert sum(widths) == pytest.approx(available)
    assert widths[1] >= stringWidth("99", FONT, 8.5) + 6
    assert widths[4] >= stringWidth("90+12", FONT, 8.5) + 6
