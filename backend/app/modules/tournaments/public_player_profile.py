"""Ficha pública del jugador (spec 038): funciones puras sin E/S.

Las filas vienen de ``v_public_player_profile_rosters`` (061): solo torneos
visibles de una organización y clave de foto anulada sin consentimiento.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

PROFILE_TOURNAMENT_LIMIT = 50
STAT_FIELDS = ("matches_played", "goals", "yellow_cards", "red_cards", "clean_sheets")


def _v(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _key(value: Any) -> str | None:
    return None if value is None else str(value)


def _inscription_rank(row: Any) -> tuple[bool, float, str]:
    valid_from = _v(row, "valid_from")
    stamp = valid_from.timestamp() if isinstance(valid_from, datetime) else float("-inf")
    return (bool(_v(row, "is_active")), stamp, _key(_v(row, "team_id")) or "")


def representative_inscriptions(rows: Iterable[Any]) -> dict[tuple[str, str], Any]:
    """CL-11: por (torneo, jugador), la vigente; si no hay, la retirada más reciente."""

    reps: dict[tuple[str, str], Any] = {}
    for row in rows or []:
        tournament, player = _key(_v(row, "tournament_id")), _key(_v(row, "player_id"))
        if not tournament or not player:
            continue
        current = reps.get((tournament, player))
        if current is None or _inscription_rank(row) > _inscription_rank(current):
            reps[(tournament, player)] = row
    return reps


def _recent_first(row: Any) -> tuple[int, str]:
    start = _v(row, "start_date")
    ordinal = start.toordinal() if isinstance(start, date) else 0
    return (-ordinal, _key(_v(row, "tournament_id")) or "")


def authorized_tournaments(rows: Iterable[Any], limit: int = PROFILE_TOURNAMENT_LIMIT) -> list[Any]:
    """DA-1/RF-003/RF-010/RNF-001: representativas con consentimiento, recientes primero."""

    authorized = [row for row in representative_inscriptions(rows).values() if _v(row, "photo_consent") is True]
    return sorted(authorized, key=_recent_first)[:limit]


def profile_available_ids(rows: Iterable[Any]) -> set[str]:
    """RF-009: jugadores cuya inscripción representativa en el torneo tiene consentimiento."""

    return {
        player
        for (_, player), row in representative_inscriptions(rows).items()
        if _v(row, "photo_consent") is True
    }


def profile_photo_candidate(tournaments: Iterable[Any]) -> Any | None:
    """RF-007/CL-2/CL-10: la vigente autorizada con foto del torneo más reciente."""

    for row in sorted(tournaments or [], key=_recent_first):
        if _v(row, "is_active") is True and _v(row, "photo_consent") is True and _v(row, "photo_object_key"):
            return row
    return None


def build_player_profile(
    tournaments: list[Any],
    stats_by_tournament: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """RF-005/RF-006: filas por torneo con las cifras de la 022 (o ceros) y totales."""

    ordered = sorted(tournaments, key=_recent_first)
    first = ordered[0] if ordered else {}
    rows = []
    for row in ordered:
        tournament = _key(_v(row, "tournament_id"))
        stats = stats_by_tournament.get(tournament or "", {})
        rows.append({
            "tournament_id": tournament,
            "tournament_name": _v(row, "tournament_name"),
            "team_id": _key(_v(row, "team_id")),
            "team_name": _v(row, "team_name"),
            **{field: int(stats.get(field) or 0) for field in STAT_FIELDS},
        })
    return {
        "player_id": _key(_v(first, "player_id")),
        "first_name": _v(first, "first_name"),
        "last_name": _v(first, "last_name"),
        "totals": {field: sum(item[field] for item in rows) for field in STAT_FIELDS},
        "tournaments": rows,
    }
