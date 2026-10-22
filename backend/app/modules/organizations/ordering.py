"""Criterio de orden estable del listado de organizaciones (RF-017, R32c).

El servidor devuelve las organizaciones de la persona siempre en el mismo
orden: por nombre y, en empate, por identificador. La elección de la
organización inicial al iniciar sesión usa exactamente este mismo criterio,
mientras que restaurar la última organización usada es responsabilidad del
navegador.
"""

from collections.abc import Iterable, Mapping
from typing import Any, TypeVar


Row = TypeVar("Row", bound=Mapping[str, Any])


def organization_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """Clave de orden estable: nombre y, en empate, identificador."""

    return (str(row["name"]), str(row["id"]))


def ordered_organizations(rows: Iterable[Row]) -> list[Row]:
    """Devuelve las filas ordenadas sin depender del orden de almacenamiento."""

    return sorted(rows, key=organization_sort_key)
