"""Serialización CSV de las exportaciones (spec 048): UTF-8 con BOM, comas, CRLF y celdas neutralizadas."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Any

from app.modules.exports.catalog import MAX_ROWS

BOM = "\ufeff"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ExportTooLarge(Exception):
    """La exportación supera el límite de filas; no se genera un archivo truncado."""


def neutralize(value: Any) -> Any:
    """Antepone ``'`` a un texto que una hoja de cálculo interpretaría como fórmula.

    Solo afecta a textos: los números (p. ej. una diferencia de goles negativa) se dejan igual.
    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _cell(value: Any) -> Any:
    return "" if value is None else neutralize(value)


def render_csv(
    header: Sequence[str], rows: Sequence[Sequence[Any]], *, max_rows: int = MAX_ROWS
) -> bytes:
    if len(rows) > max_rows:
        raise ExportTooLarge(len(rows))
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([_cell(value) for value in header])
    width = len(header)
    for row in rows:
        if len(row) != width:
            raise ValueError(f"Fila con {len(row)} columnas; se esperaban {width}")
        writer.writerow([_cell(value) for value in row])
    return (BOM + buffer.getvalue()).encode("utf-8")
