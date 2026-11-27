"""Documentos PDF a partir de las filas CSV de la 048 (spec 050, D4).

Puro: solo agrupa las mismas celdas del CSV en secciones; nunca añade datos.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from datetime import UTC
from typing import Any

from app.modules.exports.catalog import REPORT_KIND, header, label, pdf_text
from app.modules.exports.pdf_format import PdfDocument, PdfSection


def _meta(info: Mapping[str, str], lang: str) -> tuple[tuple[str, str], ...]:
    return (
        (pdf_text("organization", lang), info["organization"]),
        (pdf_text("tournament", lang), info["tournament"]),
    )


def _stage_title(stage: Any, group: Any) -> str:
    return f"{stage} · {group}" if group else str(stage)


def standings_document(
    rows: Sequence[Sequence[Any]],
    info: Mapping[str, str],
    lang: str,
    keys: Sequence[Hashable] | None = None,
) -> PdfDocument:
    """Una tabla por fase y grupo, en el orden del CSV; las columnas Fase y Grupo pasan al título.

    ``keys`` (``builders.standings_section_keys``) separa fases o grupos homónimos; sin él, por nombre.
    """
    columns = tuple(header("standings", lang)[2:])
    sections: list[PdfSection] = []
    current: Hashable | None = None
    title = ""
    bucket: list[tuple[Any, ...]] = []
    for index, row in enumerate(rows):
        key = keys[index] if keys is not None else (row[0], row[1])
        if key != current and bucket:
            sections.append(PdfSection(title, columns, tuple(bucket)))
            bucket = []
        current, title = key, _stage_title(row[0], row[1])
        bucket.append(tuple(row[2:]))
    if bucket:
        sections.append(PdfSection(title, columns, tuple(bucket)))
    if not sections:
        sections.append(PdfSection(None, columns, (), pdf_text("no_standings", lang)))
    return PdfDocument(pdf_text("standings_title", lang), _meta(info, lang), tuple(sections))


def _report_meta(info: Mapping[str, Any], lang: str) -> tuple[tuple[str, str], ...]:
    match = f"{info.get('home') or ''} {pdf_text('vs', lang)} {info.get('away') or ''}".strip()
    meta = [*_meta(info, lang), (pdf_text("match", lang), match)]
    if info.get("stage"):
        meta.append((pdf_text("stage", lang), info["stage"]))
    if info.get("match_date"):
        when = info["match_date"].astimezone(UTC).strftime("%Y-%m-%d %H:%M")
        meta.append((pdf_text("date", lang), f"{when} (UTC)"))
    return tuple(meta)


def match_report_document(
    rows: Sequence[Sequence[Any]],
    info: Mapping[str, Any],
    lang: str,
    keys: Sequence[tuple[Any, ...]] | None = None,
) -> PdfDocument:
    """Bloques Resultado, Oficiales, una Alineación por equipo y Hechos, según la columna «Sección» del CSV.

    ``keys`` (``builders.match_report_keyed``) separa las alineaciones por lado aunque los equipos se
    llamen igual; sin él, por nombre. Un bloque sin filas no aparece: un W.O. no tiene hechos (CL-3).
    """
    columns = tuple(header(REPORT_KIND, lang)[1:])
    codes = {label("report_section", code, lang): code for code in ("result", "official", "lineup", "event")}
    sections: list[PdfSection] = []
    current: tuple[Any, ...] | None = None
    title = ""
    bucket: list[tuple[Any, ...]] = []
    for index, row in enumerate(rows):
        code = codes[row[0]]
        key = keys[index] if keys is not None else (code, row[1] if code == "lineup" else None)
        if key != current and bucket:
            sections.append(PdfSection(title, columns, tuple(bucket)))
            bucket = []
        block = pdf_text(f"block_{code}", lang)
        current, title = key, f"{block} · {row[1]}" if code == "lineup" else block
        bucket.append(tuple(row[1:]))
    if bucket:
        sections.append(PdfSection(title, columns, tuple(bucket)))
    return PdfDocument(pdf_text("report_title", lang), _report_meta(info, lang), tuple(sections))
