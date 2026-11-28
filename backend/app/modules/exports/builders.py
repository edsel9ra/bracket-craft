"""Filas CSV de cada exportación (spec 048, T2).

Funciones puras: reciben las filas ya leídas y devuelven las celdas en el orden del
catálogo. Solo copian las columnas del catálogo, así que cualquier otro campo de la
entrada (documento, fecha de nacimiento, edad, correo, foto o escudo) nunca llega al
archivo. No leen la base de datos ni el reloj.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.modules.exports.catalog import LABELS, label
from app.modules.tournaments.public_stats import (
    assign_ranks,
    player_stats_rank_key,
    team_stats_rank_key,
)

CLOSED_STATUSES = frozenset({"finished", "administrative_resolution"})
Row = list[Any]


def _check_lang(lang: str) -> None:
    label("yes_no", "yes", lang)


def _text_key(value: Any) -> str:
    """Orden alfabético que no manda las letras acentuadas al final."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def _last(value: Any) -> tuple[bool, Any]:
    """Clave que ordena los ``None`` al final."""
    return (value is None, value if value is not None else 0)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_closed(match: Mapping[str, Any]) -> bool:
    """Partido cerrado (D7): finalizado o resuelto administrativamente, con el resultado confirmado."""
    return match.get("status") in CLOSED_STATUSES and bool(match.get("result_confirmed"))


def _standings_sorted(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            r["stage_order"],
            r.get("group_name") is not None,
            _text_key(r.get("group_name")),
            r["rank"],
            str(r["team_id"]),
        ),
    )


def standings_section_keys(rows: Iterable[Mapping[str, Any]]) -> list[tuple[Any, Any]]:
    """Fase y grupo de cada fila de ``standings_rows``, por identidad: dos fases o grupos homónimos no se mezclan."""
    return [(r.get("stage_id", r["stage_order"]), r.get("group_id")) for r in _standings_sorted(rows)]


def standings_rows(rows: Iterable[Mapping[str, Any]], lang: str) -> list[Row]:
    _check_lang(lang)
    ordered = _standings_sorted(rows)
    return [
        [
            r["stage_name"],
            r.get("group_name"),
            r["rank"],
            r["team_name"],
            r["played"],
            r["won"],
            r["drawn"],
            r["lost"],
            r["goals_for"],
            r["goals_against"],
            r["goal_difference"],
            r["points"],
            r["fair_play_points"],
        ]
        for r in ordered
    ]


def calendar_rows(matches: Iterable[Mapping[str, Any]], lang: str) -> list[Row]:
    _check_lang(lang)

    def sort_key(m: Mapping[str, Any]) -> tuple:
        scheduled = m.get("scheduled_at")
        return (_last(_iso_utc(scheduled)), _last(m.get("matchday")), str(m["id"]))

    result: list[Row] = []
    for m in sorted(matches, key=sort_key):
        closed = is_closed(m)
        score = [
            m.get(key) if closed else None
            for key in ("home_score", "away_score", "home_penalties", "away_penalties")
        ]
        result.append(
            [
                m.get("stage_name"),
                m.get("group_name"),
                m.get("bracket_code"),
                m.get("matchday"),
                _iso_utc(m.get("scheduled_at")),
                m.get("home_team_name"),
                m.get("away_team_name"),
                label("match_status", m["status"], lang),
                *score,
            ]
        )
    return result


def player_stats_rows(stats: Iterable[Mapping[str, Any]], lang: str) -> list[Row]:
    _check_lang(lang)
    ranked = assign_ranks([dict(row) for row in stats], player_stats_rank_key, "player_id")
    return [
        [
            r["rank"],
            r.get("first_name"),
            r.get("last_name"),
            r.get("team_name"),
            r.get("goals", 0),
            r.get("yellow_cards", 0),
            r.get("red_cards", 0),
            r.get("clean_sheets", 0),
            r.get("matches_played", 0),
            r.get("minutes_played", 0),
            label("main_position", r["main_position"], lang) if r.get("main_position") else None,
            r.get("penalties_saved", 0),
        ]
        for r in ranked
    ]


def team_stats_rows(stats: Iterable[Mapping[str, Any]], lang: str) -> list[Row]:
    _check_lang(lang)
    ranked = assign_ranks([dict(row) for row in stats], team_stats_rank_key, "team_id")
    return [
        [
            r["rank"],
            r.get("team_name"),
            r.get("short_code"),
            r.get("goals_for", 0),
            r.get("goals_against", 0),
            r.get("clean_sheets", 0),
            r.get("fair_play_points", 0),
        ]
        for r in ranked
    ]


def roster_rows(rows: Iterable[Mapping[str, Any]], lang: str) -> list[Row]:
    _check_lang(lang)
    ordered = sorted(
        rows,
        key=lambda r: (
            _text_key(r["team_name"]),
            _last(r.get("dorsal_number")),
            _text_key(r.get("last_name")),
            _text_key(r.get("first_name")),
        ),
    )
    return [
        [
            r["team_name"],
            r.get("dorsal_number"),
            r.get("first_name"),
            r.get("last_name"),
            label("roster_status", "active" if r.get("is_active") else "retired", lang),
            label("yes_no", "yes" if r.get("photo_consent") else "no", lang),
        ]
        for r in ordered
    ]


def _full_name(person: Mapping[str, Any] | None) -> str | None:
    if not person:
        return None
    name = f"{person.get('first_name') or ''} {person.get('last_name') or ''}".strip()
    return name or None


def _minute(event: Mapping[str, Any]) -> str | None:
    minute = event.get("minute")
    if minute is None:
        return None
    added = event.get("added_minute")
    return f"{minute}+{added}" if added else str(minute)


def _event_detail(event: Mapping[str, Any], players: Mapping[Any, Mapping[str, Any]], lang: str) -> str | None:
    etype = event.get("event_type")
    if etype == "substitution":
        name = _full_name(players.get(event.get("player_in_id")))
        parts = [f"{label('report_detail', 'player_in', lang)}: {name}"] if name else []
        if event.get("player_in_position"):
            parts.append(f"{label('report_detail', 'position', lang)}: {event['player_in_position']}")
        return " · ".join(parts) or None
    if etype in ("goal", "penalty_goal"):
        name = _full_name(players.get(event.get("assist_player_id")))
        return f"{label('report_detail', 'assist', lang)}: {name}" if name else None
    if etype == "red_card":
        red_type = (event.get("metadata") or {}).get("red_card_type")
        if isinstance(red_type, str) and red_type in LABELS["red_card_type"]:
            return label("red_card_type", red_type, lang)
    return None


def match_report_rows(
    match: Mapping[str, Any],
    officials: Sequence[Mapping[str, Any]],
    lineup: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    players: Mapping[Any, Mapping[str, Any]],
    lang: str,
) -> list[Row]:
    return [row for _, row in match_report_keyed(match, officials, lineup, events, players, lang)]


def match_report_keyed(
    match: Mapping[str, Any],
    officials: Sequence[Mapping[str, Any]],
    lineup: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    players: Mapping[Any, Mapping[str, Any]],
    lang: str,
) -> list[tuple[tuple[Any, ...], Row]]:
    """Acta en secciones: resultado, oficiales (sin correo), alineación y hechos.

    Cada fila va con su sección y, en la alineación, el lado (0 local, 1 visitante): dos equipos
    homónimos no se mezclan en el PDF. Un W.O. lleva el resultado y su motivo, sin hechos (CL-3).
    """
    _check_lang(lang)
    section = {code: label("report_section", code, lang) for code in LABELS["report_section"]}
    home_id, away_id = match.get("home_team_id"), match.get("away_team_id")
    team_names = {home_id: match.get("home_team_name"), away_id: match.get("away_team_name")}
    side_order = {home_id: 0, away_id: 1}

    rows: list[Row] = [
        [section["result"], match.get("home_team_name"), None, None,
         label("report_result", "home", lang), None, match.get("home_score")],
        [section["result"], match.get("away_team_name"), None, None,
         label("report_result", "away", lang), None, match.get("away_score")],
    ]
    if match.get("home_penalties") is not None and match.get("away_penalties") is not None:
        penalties = label("report_result", "penalties", lang)
        rows.append([section["result"], match.get("home_team_name"), None, None, penalties, None,
                     match["home_penalties"]])
        rows.append([section["result"], match.get("away_team_name"), None, None, penalties, None,
                     match["away_penalties"]])
    resolution = match.get("resolution_type")
    reason = match.get("resolution_reason")
    if resolution == "walkover" and reason:
        reason = label("walkover_reason", reason, lang)
    rows.append([section["result"], None, None, None,
                 label("resolution", resolution, lang) if resolution else None, None, reason])

    for official in officials:
        rows.append([section["official"], None, None, official.get("full_name"),
                     label("official_role", official["role"], lang), None, None])

    def lineup_key(entry: Mapping[str, Any]) -> tuple:
        person = players.get(entry.get("player_id")) or {}
        return (
            side_order.get(entry.get("team_id"), 2),
            entry.get("role") != "starter",
            _last(person.get("dorsal_number")),
            _text_key(_full_name(person)),
        )

    sides: list[int] = []
    for entry in sorted(lineup, key=lineup_key):
        person = players.get(entry.get("player_id")) or {}
        sides.append(side_order.get(entry.get("team_id"), 2))
        rows.append([section["lineup"], team_names.get(entry.get("team_id")), person.get("dorsal_number"),
                     _full_name(person), label("lineup_role", entry["role"], lang), None, None])

    if resolution == "walkover":
        return _report_keys(rows, sides, section)

    def event_key(event: Mapping[str, Any]) -> tuple:
        return (
            event.get("segment_number") or 0,
            event.get("minute") or 0,
            event.get("added_minute") or 0,
            str(event.get("id")),
        )

    for event in sorted(events, key=event_key):
        person = players.get(event.get("player_id")) or {}
        rows.append([section["event"], team_names.get(event.get("team_id")), person.get("dorsal_number"),
                     _full_name(person), label("event_type", event["event_type"], lang),
                     _minute(event), _event_detail(event, players, lang)])
    return _report_keys(rows, sides, section)


def _report_keys(rows: list[Row], sides: list[int], section: Mapping[str, str]) -> list[tuple[tuple[Any, ...], Row]]:
    codes = {text: code for code, text in section.items()}
    pending = iter(sides)
    return [((codes[row[0]], next(pending)) if codes[row[0]] == "lineup" else (codes[row[0]],), row) for row in rows]
