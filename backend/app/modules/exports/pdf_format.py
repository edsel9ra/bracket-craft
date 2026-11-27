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
CELL_SIZE = 8.5
# Relleno horizontal de cada celda (3 pt por lado) más un margen de redondeo.
CELL_PADDING = 6.5


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
    base = ParagraphStyle("base", fontName=FONT, fontSize=CELL_SIZE, leading=10.5)
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


def _width(text: str, font: str) -> float:
    return pdfmetrics.stringWidth(text, font, CELL_SIZE) + CELL_PADDING


def _cap_widest(minimum: list[float], available: float) -> list[float]:
    """Una palabra más ancha que la página (p. ej. un enlace): las columnas estrechas conservan su
    mínimo y las más anchas comparten un mismo tope; ReportLab parte esa palabra dentro de su celda."""
    used, cap = 0.0, available / len(minimum)
    for count, width in enumerate(sorted(minimum)):
        cap = (available - used) / (len(minimum) - count)
        if width > cap:
            break
        used += width
    return [min(width, cap) for width in minimum]


def column_widths(header: Sequence[str], rows: Sequence[Sequence[Any]], available: float) -> list[float]:
    """Cada columna recibe al menos su palabra más ancha (una cifra o un minuto nunca se parten);
    el resto del ancho va a las columnas cuyo texto completo no cabe, en proporción a lo que les falta."""
    _register_fonts()
    columns = [[(str(title), FONT_BOLD)] + [("" if row[i] is None else str(row[i]), FONT) for row in rows]
               for i, title in enumerate(header)]

    def least(cells, fonts=(FONT, FONT_BOLD)) -> float:
        return max([CELL_PADDING] + [_width(word, font) for text, font in cells if font in fonts
                                     for word in text.split()])

    minimum = [least(cells) for cells in columns]
    if sum(minimum) > available:
        # Las cabeceras pueden partirse; las celdas, no, salvo que ni así quepan.
        minimum = [least(cells, (FONT,)) for cells in columns]
    if sum(minimum) > available:
        return _cap_widest(minimum, available)
    full = [max(_width(text, font) for text, font in cells) for cells in columns]
    missing = [whole - low for whole, low in zip(full, minimum, strict=True)]
    spare = available - sum(minimum)
    if sum(missing) > spare:
        return [low + spare * gap / sum(missing) for low, gap in zip(minimum, missing, strict=True)]
    left = spare - sum(missing)
    return [whole + left * whole / sum(full) for whole in full]


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
