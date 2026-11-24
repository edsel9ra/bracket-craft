"""Catálogo cerrado de avisos (spec 046, RF-001, RF-006 y RF-011).

Funciones puras: tipos y canales en orden fijo, preferencias efectivas con los
valores por defecto y el texto bilingüe del correo, que nunca nombra a un
jugador ni usa campos fuera de los declarados.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

NOTIFICATION_TYPES = (
    "match_scheduled",
    "result_confirmed",
    "walkover_declared",
    "sanction_generated",
)
CHANNELS = ("inbox", "email")
DEFAULT_ENABLED = {"inbox": True, "email": False}

_LABELS = {
    "match_scheduled": ("Partidos programados", "Matches scheduled"),
    "result_confirmed": ("Resultado confirmado", "Result confirmed"),
    "walkover_declared": ("W.O. declarado", "Walkover declared"),
    "sanction_generated": ("Sanción generada", "Sanction issued"),
}
_SUMMARIES = {
    "match_scheduled": (
        "Se programaron {count} partidos.",
        "{count} matches were scheduled.",
    ),
    "result_confirmed": (
        "Se confirmó el resultado de {match}.",
        "The result of {match} was confirmed.",
    ),
    "walkover_declared": (
        "Se declaró W.O. en {match}.",
        "A walkover was declared in {match}.",
    ),
    "sanction_generated": (
        "Se generó una sanción en {match}.",
        "A sanction was issued in {match}.",
    ),
}
_UNDEFINED_TEAM = ("Por definir", "TBD")


@dataclass(frozen=True)
class Preference:
    notification_type: str
    channel: str
    enabled: bool


def effective_preferences(saved: Iterable[Mapping[str, Any]]) -> list[Preference]:
    stored = {
        (row["notification_type"], row["channel"]): bool(row["enabled"])
        for row in saved
        if row["notification_type"] in NOTIFICATION_TYPES and row["channel"] in CHANNELS
    }
    return [
        Preference(kind, channel, stored.get((kind, channel), DEFAULT_ENABLED[channel]))
        for kind in NOTIFICATION_TYPES
        for channel in CHANNELS
    ]


def _single_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _match(payload: Mapping[str, Any], language: int) -> str:
    home = _single_line(payload.get("home_team_name")) or _UNDEFINED_TEAM[language]
    away = _single_line(payload.get("away_team_name")) or _UNDEFINED_TEAM[language]
    return f"{home} vs {away}"


def email_message(payload: Mapping[str, Any], base_url: str) -> tuple[str, str]:
    kind = payload.get("type")
    if kind not in NOTIFICATION_TYPES:
        raise ValueError("NOTIFICATION_TYPE_UNKNOWN")
    tournament = _single_line(payload.get("tournament_name"))
    spanish, english = _LABELS[kind]
    link = f"{base_url.rstrip('/')}/workspace/notifications"
    sections = []
    for language, (label, summary, tournament_label, link_label) in enumerate(
        (
            (
                spanish,
                _SUMMARIES[kind][0],
                "Torneo",
                "Consulta el aviso en el Workspace",
            ),
            (
                english,
                _SUMMARIES[kind][1],
                "Tournament",
                "See the notification in the Workspace",
            ),
        )
    ):
        text = summary.format(
            count=payload.get("match_count"), match=_match(payload, language)
        )
        sections.append(
            f"{label}\n{tournament_label}: {tournament}\n{text}\n{link_label}."
        )
    subject = f"{spanish} / {english} — {tournament} — Bracket Craft"
    return subject, "\n\n".join(sections) + f"\n\n{link}\n"
