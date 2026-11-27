"""Documentos PDF a partir de las filas CSV de la 048 (spec 050, D4).

Puro: solo agrupa las mismas celdas del CSV en secciones; nunca añade datos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.exports.catalog import header, pdf_text
from app.modules.exports.pdf_format import PdfDocument, PdfSection


def _meta(info: Mapping[str, str], lang: str) -> tuple[tuple[str, str], ...]:
    return (
        (pdf_text("organization", lang), info["organization"]),
        (pdf_text("tournament", lang), info["tournament"]),
    )


def _stage_title(stage: Any, group: Any) -> str:
    return f"{stage} · {group}" if group else str(stage)


def standings_document(rows: Sequence[Sequence[Any]], info: Mapping[str, str], lang: str) -> PdfDocument:
    """Una tabla por fase y grupo, en el orden del CSV; las columnas Fase y Grupo pasan al título."""
    columns = tuple(header("standings", lang)[2:])
    sections: list[PdfSection] = []
    current: tuple[Any, Any] | None = None
    bucket: list[tuple[Any, ...]] = []
    for row in rows:
        key = (row[0], row[1])
        if key != current and bucket:
            sections.append(PdfSection(_stage_title(*current), columns, tuple(bucket)))
            bucket = []
        current = key
        bucket.append(tuple(row[2:]))
    if bucket:
        sections.append(PdfSection(_stage_title(*current), columns, tuple(bucket)))
    if not sections:
        sections.append(PdfSection(None, columns, (), pdf_text("no_standings", lang)))
    return PdfDocument(pdf_text("standings_title", lang), _meta(info, lang), tuple(sections))
