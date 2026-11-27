"""Composición PDF de las exportaciones (spec 050): A4 vertical, fuentes TTF incrustadas y texto seleccionable.

Puro: recibe el documento ya construido y la fecha de generación; no lee el reloj ni la base de datos.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.exports.catalog import MAX_ROWS, pdf_text
from app.modules.exports.csv_format import ExportTooLarge

FONTS_DIR = Path(__file__).parent / "fonts"
FONT = "Archivo"
FONT_BOLD = "Archivo-Bold"
MARGIN = 18 * mm
FOOTER_SIZE = 8
# Peso mínimo y máximo de una columna al repartir el ancho según su texto más largo.
MIN_WEIGHT, MAX_WEIGHT = 3, 28


@dataclass(frozen=True)
class PdfSection:
    title: str | None
    header: Sequence[str]
    rows: Sequence[Sequence[Any]]
    empty_notice: str | None = None


@dataclass(frozen=True)
class PdfDocument:
    title: str
    meta: Sequence[tuple[str, str]]
    sections: Sequence[PdfSection]


@cache
def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(FONT, str(FONTS_DIR / "Archivo-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / "Archivo-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)


@cache
def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName=FONT, fontSize=8.5, leading=10.5)
    return {
        "title": ParagraphStyle("title", base, fontName=FONT_BOLD, fontSize=16, leading=20, spaceAfter=4),
        "meta": ParagraphStyle("meta", base, fontSize=9.5, leading=12.5),
        "section": ParagraphStyle("section", base, fontName=FONT_BOLD, fontSize=11, leading=14,
                                  spaceBefore=8, spaceAfter=4),
        "cell": base,
        "head": ParagraphStyle("head", base, fontName=FONT_BOLD),
    }


def _text(value: Any) -> str:
    """Texto literal: Platypus interpreta marcas, así que ``<``, ``>``, ``&`` y comillas se escapan."""
    return escape("" if value is None else str(value), {'"': "&quot;", "'": "&#39;"})


def _paragraph(value: Any, style: str) -> Paragraph:
    return Paragraph(_text(value), _styles()[style])


def column_widths(header: Sequence[str], rows: Sequence[Sequence[Any]], available: float) -> list[float]:
    weights = []
    for index, title in enumerate(header):
        longest = max([len(str(title))] + [len(str(row[index] or "")) for row in rows])
        weights.append(min(max(longest, MIN_WEIGHT), MAX_WEIGHT))
    total = sum(weights)
    return [available * weight / total for weight in weights]


def _table(section: PdfSection, available: float) -> Table:
    data = [[_paragraph(title, "head") for title in section.header]]
    data += [[_paragraph(value, "cell") for value in row] for row in section.rows]
    table = Table(data, colWidths=column_widths(section.header, section.rows, available), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6E8EC")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#9AA0A8")),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _numbered_canvas(label: str):
    class NumberedCanvas(Canvas):
        """Dos pasadas: guarda cada página y, al final, escribe «Página n de m» con el total ya conocido."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self.setFont(FONT, FOOTER_SIZE)
                self.drawRightString(A4[0] - MARGIN, MARGIN / 2,
                                     label.format(page=self._pageNumber, total=total))
                super().showPage()
            super().save()

    return NumberedCanvas


def _check(document: PdfDocument, max_rows: int) -> None:
    total = sum(len(section.rows) for section in document.sections)
    if total > max_rows:
        raise ExportTooLarge(total)
    for section in document.sections:
        width = len(section.header)
        for row in section.rows:
            if len(row) != width:
                raise ValueError(f"Fila con {len(row)} columnas; se esperaban {width}")


def render_pdf(
    document: PdfDocument,
    lang: str,
    generated_at: datetime,
    *,
    invariant: bool = False,
    max_rows: int = MAX_ROWS,
) -> bytes:
    generated = pdf_text("generated_at", lang).format(at=generated_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M"))
    page_label = pdf_text("page", lang)
    _check(document, max_rows)
    _register_fonts()
    buffer = io.BytesIO()
    template = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN,
        title=document.title, lang=lang, invariant=1 if invariant else 0, creator="Bracket Craft",
        # Sin esto el lienzo declara Helvetica (no incrustada) como fuente inicial.
        initialFontName=FONT,
    )
    story: list[Any] = [_paragraph(document.title, "title")]
    story += [_paragraph(f"{label}: {value}", "meta") for label, value in document.meta]
    story.append(_paragraph(generated, "meta"))
    for section in document.sections:
        if section.title:
            story.append(_paragraph(section.title, "section"))
        else:
            story.append(Spacer(1, 6))
        if section.rows:
            story.append(_table(section, template.width))
        elif section.empty_notice:
            story.append(_paragraph(section.empty_notice, "meta"))
    template.build(story, canvasmaker=_numbered_canvas(page_label))
    return buffer.getvalue()
