"""Catálogo cerrado de exportaciones CSV (spec 048) y PDF (spec 050): columnas, cabeceras y etiquetas ES/EN."""

from __future__ import annotations

EXPORT_KINDS: tuple[str, ...] = ("standings", "calendar", "player-stats", "team-stats", "rosters")
REPORT_KIND = "match-report"
MAX_ROWS = 10_000
LANGS: tuple[str, ...] = ("es", "en")
# Solo la clasificación y el acta tienen versión PDF (spec 050, DA-1).
PDF_KINDS: tuple[str, ...] = ("standings", REPORT_KIND)

# Textos fijos del documento PDF; ``{at}``, ``{page}`` y ``{total}`` se rellenan al componerlo.
PDF_TEXTS: dict[str, dict[str, str]] = {
    "generated_at": {"es": "Generado el {at} (UTC)", "en": "Generated on {at} (UTC)"},
    "page": {"es": "Página {page} de {total}", "en": "Page {page} of {total}"},
    "organization": {"es": "Organización", "en": "Organization"},
    "tournament": {"es": "Torneo", "en": "Tournament"},
    "standings_title": {"es": "Clasificación", "en": "Standings"},
    "no_standings": {"es": "Sin clasificación todavía", "en": "No standings yet"},
    "report_title": {"es": "Acta del partido", "en": "Match report"},
    "match": {"es": "Partido", "en": "Match"},
    "stage": {"es": "Fase", "en": "Stage"},
    "date": {"es": "Fecha", "en": "Date"},
    "vs": {"es": "vs", "en": "vs"},
    "block_result": {"es": "Resultado", "en": "Result"},
    "block_official": {"es": "Oficiales", "en": "Officials"},
    "block_lineup": {"es": "Alineación", "en": "Lineup"},
    "block_event": {"es": "Hechos", "en": "Events"},
}

# Cada columna: (clave interna, cabecera ES, cabecera EN). El orden es el del archivo.
COLUMNS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "standings": (
        ("stage", "Fase", "Stage"),
        ("group", "Grupo", "Group"),
        ("position", "Posición", "Position"),
        ("team", "Equipo", "Team"),
        ("played", "PJ", "P"),
        ("won", "G", "W"),
        ("drawn", "E", "D"),
        ("lost", "P", "L"),
        ("goals_for", "GF", "GF"),
        ("goals_against", "GC", "GA"),
        ("goal_difference", "DG", "GD"),
        ("points", "Puntos", "Points"),
        ("fair_play", "Juego limpio", "Fair play"),
    ),
    "calendar": (
        ("stage", "Fase", "Stage"),
        ("group", "Grupo", "Group"),
        ("bracket_code", "Llave", "Bracket"),
        ("matchday", "Jornada", "Matchday"),
        ("scheduled_at", "Fecha (UTC)", "Date (UTC)"),
        ("home_team", "Local", "Home"),
        ("away_team", "Visitante", "Away"),
        ("status", "Estado", "Status"),
        ("home_goals", "Goles local", "Home goals"),
        ("away_goals", "Goles visitante", "Away goals"),
        ("home_penalties", "Penales local", "Home penalties"),
        ("away_penalties", "Penales visitante", "Away penalties"),
    ),
    "player-stats": (
        ("position", "Posición", "Position"),
        ("first_name", "Nombre", "First name"),
        ("last_name", "Apellidos", "Last name"),
        ("team", "Equipo", "Team"),
        ("goals", "Goles", "Goals"),
        ("yellow_cards", "Amarillas", "Yellow cards"),
        ("red_cards", "Rojas", "Red cards"),
        ("clean_sheets", "Porterías imbatidas", "Clean sheets"),
        ("matches_played", "Partidos jugados", "Matches played"),
    ),
    "team-stats": (
        ("position", "Posición", "Position"),
        ("team", "Equipo", "Team"),
        ("team_code", "Código", "Code"),
        ("goals_for", "GF", "GF"),
        ("goals_against", "GC", "GA"),
        ("clean_sheets", "Porterías imbatidas", "Clean sheets"),
        ("fair_play", "Juego limpio", "Fair play"),
    ),
    "rosters": (
        ("team", "Equipo", "Team"),
        ("dorsal_number", "Dorsal", "Number"),
        ("first_name", "Nombre", "First name"),
        ("last_name", "Apellidos", "Last name"),
        ("status", "Estado", "Status"),
        ("image_consent", "Consentimiento de imagen", "Image consent"),
    ),
    REPORT_KIND: (
        ("section", "Sección", "Section"),
        ("team", "Equipo", "Team"),
        ("dorsal_number", "Dorsal", "Number"),
        ("player", "Jugador", "Player"),
        ("role_or_type", "Función o tipo", "Role or type"),
        ("minute", "Minuto", "Minute"),
        ("detail", "Detalle", "Detail"),
    ),
}

# Etiquetas de los códigos que aparecen en las celdas: código -> (ES, EN).
LABELS: dict[str, dict[str, tuple[str, str]]] = {
    "match_status": {
        "scheduled": ("Programado", "Scheduled"),
        "live": ("En juego", "Live"),
        "finished": ("Finalizado", "Finished"),
        "suspended": ("Suspendido", "Suspended"),
        "cancelled": ("Cancelado", "Cancelled"),
        "administrative_resolution": ("Resolución administrativa", "Administrative resolution"),
    },
    "event_type": {
        "goal": ("Gol", "Goal"),
        "own_goal": ("Gol en propia", "Own goal"),
        "penalty_goal": ("Gol de penal", "Penalty goal"),
        "yellow_card": ("Tarjeta amarilla", "Yellow card"),
        "red_card": ("Tarjeta roja", "Red card"),
        "substitution": ("Sustitución", "Substitution"),
        "foul": ("Falta", "Foul"),
    },
    "official_role": {
        "main_referee": ("Árbitro principal", "Referee"),
        "assistant_referee_1": ("Asistente 1", "Assistant referee 1"),
        "assistant_referee_2": ("Asistente 2", "Assistant referee 2"),
        "fourth_official": ("Cuarto árbitro", "Fourth official"),
        "match_commissioner": ("Comisario", "Match commissioner"),
    },
    "resolution": {
        "regular": ("Tiempo reglamentario", "Regular time"),
        "extra_time": ("Prórroga", "Extra time"),
        "penalties": ("Penales", "Penalties"),
        "walkover": ("W.O.", "Walkover"),
        "administrative": ("Administrativa", "Administrative"),
    },
    "walkover_reason": {
        "no_show": ("Incomparecencia", "No-show"),
        "withdrawal": ("Retirada", "Withdrawal"),
        "insufficient_players": ("Jugadores insuficientes", "Insufficient players"),
        "sanction": ("Sanción", "Sanction"),
    },
    "lineup_role": {
        "starter": ("Titular", "Starter"),
        "substitute": ("Suplente", "Substitute"),
    },
    "report_section": {
        "result": ("Resultado", "Result"),
        "official": ("Oficial", "Official"),
        "lineup": ("Alineación", "Lineup"),
        "event": ("Hecho", "Event"),
    },
    "roster_status": {
        "active": ("Activo", "Active"),
        "retired": ("Retirado", "Withdrawn"),
    },
    "report_result": {
        "home": ("Local", "Home"),
        "away": ("Visitante", "Away"),
        "penalties": ("Penales", "Penalties"),
    },
    "report_detail": {
        "assist": ("Asistencia", "Assist"),
        "player_in": ("Entra", "In"),
    },
    "red_card_type": {
        "direct_red": ("Roja directa", "Straight red"),
        "double_yellow_red": ("Doble amarilla", "Second yellow"),
    },
    "yes_no": {
        "yes": ("Sí", "Yes"),
        "no": ("No", "No"),
    },
}


def pdf_text(key: str, lang: str) -> str:
    _lang_index(lang)
    return PDF_TEXTS[key][lang]


def _lang_index(lang: str) -> int:
    if lang not in LANGS:
        raise ValueError(f"Idioma de exportación no admitido: {lang!r}")
    return LANGS.index(lang)


def column_keys(kind: str) -> list[str]:
    return [key for key, _, _ in COLUMNS[kind]]


def header(kind: str, lang: str) -> list[str]:
    index = _lang_index(lang) + 1
    return [column[index] for column in COLUMNS[kind]]


def label(group: str, code: str, lang: str) -> str:
    index = _lang_index(lang)
    labels = LABELS[group].get(code)
    return labels[index] if labels else code
