"""Funciones puras de la cronología pública del partido (spec 037).

Ninguna función lee la base de datos ni el reloj: reciben el partido, los
eventos de la versión vigente, los segmentos y los nombres públicos ya cargados
y devuelven valores deterministas. El aislamiento por organización y la
visibilidad del torneo se resuelven en el endpoint.
"""

from __future__ import annotations

import json
from typing import Any, Collection, Iterable, Literal, Mapping

Availability = Literal["pending", "not_played", "available"]
RedCardType = Literal["direct_red", "double_yellow_red"]

PUBLIC_TIMELINE_TYPES = frozenset(
    {"goal", "penalty_goal", "own_goal", "yellow_card", "red_card", "substitution"}
)
PENDING_STATUSES = frozenset({"scheduled", "live", "suspended"})
PLAYED_RESOLUTIONS = frozenset({None, "regular", "extra_time", "penalties"})
RED_CARD_TYPES = frozenset({"direct_red", "double_yellow_red"})


def _v(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _key(value: Any) -> str | None:
    return None if value is None else str(value)


def timeline_availability(status: str | None, resolution_type: str | None) -> Availability:
    """RF-001–RF-003: solo un partido jugado y confirmado tiene cronología."""

    if status in PENDING_STATUSES:
        return "pending"
    if status == "finished" and resolution_type in PLAYED_RESOLUTIONS:
        return "available"
    return "not_played"


def public_red_card_type(event_type: str | None, metadata: Any) -> RedCardType | None:
    """RF-008: clasificación del acta, sin inferirla si falta o no es válida."""

    if event_type != "red_card":
        return None
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return None
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("red_card_type")
    return value if isinstance(value, str) and value in RED_CARD_TYPES else None


def timeline_sort_key(event: Mapping[str, Any]) -> tuple[int, int, int, str]:
    """RF-009: segmento, minuto, tiempo añadido y desempate estable."""

    return (
        int(event["segment_number"]),
        int(event["minute"]),
        int(event["added_minute"]),
        str(event["_event_id"]),
    )


def public_player_names(rosters: Iterable[Any]) -> dict[str, tuple[str, str]]:
    """Nombre y apellido públicos por jugador (DA-2 a); sin dorsal ni foto."""

    names: dict[str, tuple[str, str]] = {}
    for row in rosters or []:
        player = _key(_v(row, "player_id"))
        first, last = _v(row, "first_name"), _v(row, "last_name")
        if player and first and last and player not in names:
            names[player] = (str(first), str(last))
    return names


def _final_score(match: Any, side: str) -> int | None:
    for key in (f"{side}_score", f"{side}_score_regular"):
        value = _v(match, key)
        if value is not None:
            return int(value)
    return None


def timeline_matches_score(events: Iterable[Mapping[str, Any]], match: Any) -> bool:
    """RF-010: los goles publicados coinciden con el marcador final (sin penales)."""

    home, away = _final_score(match, "home"), _final_score(match, "away")
    if home is None or away is None:
        return True
    home_id, away_id = _key(_v(match, "home_team_id")), _key(_v(match, "away_team_id"))
    counted = {home_id: 0, away_id: 0}
    for event in events:
        if event["event_type"] in ("goal", "penalty_goal"):
            scorer = _key(event["team_id"])
        elif event["event_type"] == "own_goal":
            scorer = _key(event["beneficiary_team_id"])
        else:
            continue
        if scorer in counted:
            counted[scorer] += 1
    return counted[home_id] == home and counted[away_id] == away


def _player(
    names: Mapping[str, tuple[str, str]],
    player_id: Any,
    profiles: Collection[str] = frozenset(),
) -> dict[str, Any] | None:
    key = _key(player_id)
    if key is None or key not in names:
        return None
    first, last = names[key]
    return {
        "player_id": player_id,
        "first_name": first,
        "last_name": last,
        "profile_available": key in profiles,
    }


def _public_event(
    event: Any,
    segment_numbers: Mapping[str, int],
    teams: tuple[str | None, str | None],
    names: Mapping[str, tuple[str, str]],
    profiles: Collection[str] = frozenset(),
) -> dict[str, Any] | None:
    """Proyección mínima de un hecho, o ``None`` si es huérfano (RF-011)."""

    event_type = _v(event, "event_type")
    if event_type not in PUBLIC_TIMELINE_TYPES or _v(event, "is_voided"):
        return None
    segment = segment_numbers.get(_key(_v(event, "segment_id")) or "")
    team = _key(_v(event, "team_id"))
    if segment is None or team is None or team not in teams:
        return None

    beneficiary = None
    if event_type == "own_goal":
        opponent = teams[1] if team == teams[0] else teams[0]
        beneficiary = _key(_v(event, "beneficiary_team_id")) or opponent
        if beneficiary != opponent:
            return None

    player_in = None
    if event_type == "substitution":
        player = _player(names, _v(event, "player_out_id") or _v(event, "player_id"), profiles)
        player_in = _player(names, _v(event, "player_in_id"), profiles)
        if player_in is None:
            return None
    else:
        player = _player(names, _v(event, "player_id"), profiles)
    if player is None:
        return None

    return {
        "_event_id": _v(event, "id"),
        "event_type": event_type,
        "minute": int(_v(event, "minute") or 0),
        "added_minute": int(_v(event, "added_minute") or 0),
        "segment_number": segment,
        "team_id": _v(event, "team_id"),
        "beneficiary_team_id": beneficiary,
        "red_card_type": public_red_card_type(event_type, _v(event, "metadata")),
        "player": player,
        "player_in": player_in,
    }


def build_public_timeline(
    match: Any,
    events: Iterable[Any],
    segments: Iterable[Any],
    names: Mapping[str, tuple[str, str]],
    profiles: Collection[str] = frozenset(),
) -> dict[str, Any]:
    """Cronología pública de un partido (RF-001–RF-013), sin campos internos.

    ``profiles``: jugadores con ficha pública en este torneo (spec 038, RF-009).
    """

    availability = timeline_availability(_v(match, "status"), _v(match, "resolution_type"))
    result: dict[str, Any] = {
        "match_id": _v(match, "id"),
        "availability": availability,
        "score_consistent": True,
        "segment_numbers": [],
        "events": [],
    }
    if availability != "available":
        return result

    match_id = _key(_v(match, "id"))
    segment_numbers = {
        _key(_v(s, "id")): int(_v(s, "segment_number"))
        for s in segments or []
        if _key(_v(s, "match_id")) in (None, match_id) and _v(s, "segment_number") is not None
    }
    teams = (_key(_v(match, "home_team_id")), _key(_v(match, "away_team_id")))
    published = [
        item
        for event in events or []
        if _key(_v(event, "match_id")) in (None, match_id)
        and (item := _public_event(event, segment_numbers, teams, names, profiles)) is not None
    ]
    published.sort(key=timeline_sort_key)
    for item in published:
        item.pop("_event_id")
    result["segment_numbers"] = sorted(set(segment_numbers.values()))
    result["events"] = published
    result["score_consistent"] = timeline_matches_score(published, match)
    return result
