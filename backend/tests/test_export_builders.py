"""Construcción de las filas de cada exportación (spec 048, T2). Funciones puras."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.modules.exports import builders, catalog

HOME = UUID("00000000-0000-0000-0000-0000000000a1")
AWAY = UUID("00000000-0000-0000-0000-0000000000b2")
P1 = UUID("00000000-0000-0000-0000-000000000001")
P2 = UUID("00000000-0000-0000-0000-000000000002")
P3 = UUID("00000000-0000-0000-0000-000000000003")

FORBIDDEN_KEYS = (
    "national_id",
    "birth_date",
    "age",
    "age_years",
    "email",
    "photo_object_key",
    "photo_url",
    "crest_url",
)


def _width(kind: str) -> int:
    return len(catalog.header(kind, "es"))


def _flat(rows: list[list]) -> list:
    return [cell for row in rows for cell in row]


def _assert_no_forbidden(rows: list[list], *values: str) -> None:
    cells = [str(cell) for cell in _flat(rows)]
    for value in values:
        assert all(value not in cell for cell in cells), value


# ---------------------------------------------------------------- clasificación


def _standing(**overrides):
    row = {
        "stage_name": "Liga",
        "stage_order": 1,
        "group_name": None,
        "rank": 1,
        "team_id": HOME,
        "team_name": "Halcones",
        "short_code": "HAL",
        "played": 3,
        "won": 2,
        "drawn": 0,
        "lost": 1,
        "goals_for": 5,
        "goals_against": 8,
        "goal_difference": -3,
        "points": 6,
        "fair_play_points": -2,
        "crest_url": "https://cdn.example/escudo.png",
    }
    row.update(overrides)
    return row


def test_standings_rows_follow_catalog_columns():
    rows = builders.standings_rows([_standing()], "es")
    assert rows == [["Liga", None, 1, "Halcones", 3, 2, 0, 1, 5, 8, -3, 6, -2]]
    assert len(rows[0]) == _width("standings")


def test_standings_rows_order_by_stage_group_without_group_first_rank_and_team():
    data = [
        _standing(stage_name="Final", stage_order=2, rank=1, team_name="Z"),
        _standing(group_name="B", rank=1, team_name="B1"),
        _standing(group_name="A", rank=2, team_name="A2"),
        _standing(group_name="A", rank=1, team_name="A1b", team_id=AWAY),
        _standing(group_name="A", rank=1, team_name="A1a", team_id=HOME),
        _standing(group_name=None, rank=1, team_name="Sin grupo"),
    ]
    assert [row[3] for row in builders.standings_rows(data, "es")] == [
        "Sin grupo",
        "A1a",
        "A1b",
        "A2",
        "B1",
        "Z",
    ]


def test_standings_rows_never_include_the_crest():
    _assert_no_forbidden(builders.standings_rows([_standing()], "en"), "cdn.example")


def test_empty_inputs_produce_no_rows():
    assert builders.standings_rows([], "es") == []
    assert builders.calendar_rows([], "es") == []
    assert builders.player_stats_rows([], "es") == []
    assert builders.team_stats_rows([], "es") == []
    assert builders.roster_rows([], "es") == []


# ---------------------------------------------------------------- calendario


def _match(**overrides):
    row = {
        "id": UUID("00000000-0000-0000-0000-00000000c001"),
        "stage_name": "Liga",
        "group_name": "A",
        "bracket_code": None,
        "matchday": 1,
        "scheduled_at": datetime(2026, 11, 25, 20, 0, tzinfo=UTC),
        "home_team_name": "Halcones",
        "away_team_name": "Águilas",
        "status": "finished",
        "result_confirmed": True,
        "home_score": 2,
        "away_score": 1,
        "home_penalties": None,
        "away_penalties": None,
    }
    row.update(overrides)
    return row


def test_calendar_rows_follow_catalog_columns_with_iso_utc_dates():
    rows = builders.calendar_rows([_match()], "es")
    assert rows == [
        [
            "Liga",
            "A",
            None,
            1,
            "2026-11-25T20:00:00Z",
            "Halcones",
            "Águilas",
            "Finalizado",
            2,
            1,
            None,
            None,
        ]
    ]
    assert len(rows[0]) == _width("calendar")


def test_calendar_dates_are_converted_to_utc():
    bogota = timezone(timedelta(hours=-5))
    rows = builders.calendar_rows([_match(scheduled_at=datetime(2026, 11, 25, 15, 0, tzinfo=bogota))], "en")
    assert rows[0][4] == "2026-11-25T20:00:00Z"


@pytest.mark.parametrize(
    ("status", "es", "en"),
    [
        ("scheduled", "Programado", "Scheduled"),
        ("live", "En juego", "Live"),
        ("suspended", "Suspendido", "Suspended"),
    ],
)
def test_calendar_rows_hide_score_of_open_matches(status, es, en):
    match = _match(status=status, result_confirmed=False, home_penalties=4, away_penalties=3)
    for lang, label in (("es", es), ("en", en)):
        row = builders.calendar_rows([match], lang)[0]
        assert row[7] == label
        assert row[8:] == [None, None, None, None]


def test_calendar_rows_hide_score_of_unconfirmed_finished_match():
    row = builders.calendar_rows([_match(result_confirmed=False)], "es")[0]
    assert row[8:] == [None, None, None, None]


def test_calendar_rows_show_penalties_and_administrative_resolution():
    match = _match(status="administrative_resolution", home_penalties=4, away_penalties=3)
    row = builders.calendar_rows([match], "en")[0]
    assert row[7] == "Administrative resolution"
    assert row[8:] == [2, 1, 4, 3]


def test_calendar_rows_order_by_date_with_undated_last_then_matchday_and_id():
    day = datetime(2026, 11, 25, 20, 0, tzinfo=UTC)
    data = [
        _match(id=UUID(int=4), scheduled_at=None, matchday=1, home_team_name="sin fecha"),
        _match(id=UUID(int=3), scheduled_at=day + timedelta(days=1), home_team_name="mañana"),
        _match(id=UUID(int=2), scheduled_at=day, matchday=2, home_team_name="hoy j2"),
        _match(id=UUID(int=1), scheduled_at=day, matchday=1, home_team_name="hoy j1 b"),
        _match(id=UUID(int=0), scheduled_at=day, matchday=1, home_team_name="hoy j1 a"),
    ]
    assert [row[5] for row in builders.calendar_rows(data, "es")] == [
        "hoy j1 a",
        "hoy j1 b",
        "hoy j2",
        "mañana",
        "sin fecha",
    ]


def test_calendar_rows_keep_pending_teams_empty():
    row = builders.calendar_rows([_match(home_team_name=None, away_team_name=None, bracket_code="SF1")], "es")[0]
    assert row[2] == "SF1"
    assert row[5:7] == [None, None]


# ---------------------------------------------------------------- estadísticas


def _player_stat(pid, first, last, goals, played=3, **overrides):
    row = {
        "player_id": pid,
        "first_name": first,
        "last_name": last,
        "team_id": HOME,
        "team_name": "Halcones",
        "goals": goals,
        "yellow_cards": 1,
        "red_cards": 0,
        "clean_sheets": 0,
        "matches_played": played,
        "photo_url": "https://cdn.example/foto.jpg",
        "photo_consent": True,
    }
    row.update(overrides)
    return row


def test_player_stats_rows_rank_like_the_public_view():
    data = [
        _player_stat(P1, "Ana", "Ruiz", 2),
        _player_stat(P2, "Bea", "Diaz", 5),
        _player_stat(P3, "Eva", "Ruiz", 2),
    ]
    rows = builders.player_stats_rows(data, "es")
    assert rows == [
        [1, "Bea", "Diaz", "Halcones", 5, 1, 0, 0, 3],
        [2, "Ana", "Ruiz", "Halcones", 2, 1, 0, 0, 3],
        [2, "Eva", "Ruiz", "Halcones", 2, 1, 0, 0, 3],
    ]
    assert len(rows[0]) == _width("player-stats")
    _assert_no_forbidden(rows, "cdn.example", str(P1))
    assert "rank" not in data[0]


def test_team_stats_rows_rank_like_the_public_view_without_ids_or_crests():
    data = [
        {"team_id": HOME, "team_name": "Halcones", "short_code": "HAL", "goals_for": 3,
         "goals_against": 1, "clean_sheets": 1, "fair_play_points": -4, "crest_url": "https://cdn.example/e.png"},
        {"team_id": AWAY, "team_name": "Águilas", "short_code": "AGU", "goals_for": 7,
         "goals_against": 2, "clean_sheets": 0, "fair_play_points": 0},
    ]
    rows = builders.team_stats_rows(data, "en")
    assert rows == [[1, "Águilas", "AGU", 7, 2, 0, 0], [2, "Halcones", "HAL", 3, 1, 1, -4]]
    assert len(rows[0]) == _width("team-stats")
    _assert_no_forbidden(rows, "cdn.example", str(HOME), str(AWAY))


# ---------------------------------------------------------------- plantillas


def _roster(**overrides):
    row = {
        "team_name": "Halcones",
        "dorsal_number": 10,
        "first_name": "Ana",
        "last_name": "Ruiz",
        "is_active": True,
        "photo_consent": True,
        "age": 17,
        "age_years": 17,
        "birth_date": "2009-05-15",
        "national_id": "12345678",
        "photo_object_key": "org/fotos/ana.jpg",
    }
    row.update(overrides)
    return row


def test_roster_rows_have_status_and_consent_without_age_or_photo():
    rows = builders.roster_rows([_roster(), _roster(first_name="Eva", dorsal_number=7, is_active=False,
                                                    photo_consent=False)], "es")
    assert rows == [
        ["Halcones", 7, "Eva", "Ruiz", "Retirado", "No"],
        ["Halcones", 10, "Ana", "Ruiz", "Activo", "Sí"],
    ]
    assert len(rows[0]) == _width("rosters")
    _assert_no_forbidden(rows, "12345678", "2009", "ana.jpg")
    assert 17 not in _flat(rows)


def test_roster_rows_translate_status_and_consent():
    rows = builders.roster_rows([_roster(is_active=False, photo_consent=False)], "en")
    assert rows[0][4:] == ["Withdrawn", "No"]
    assert builders.roster_rows([_roster()], "en")[0][4:] == ["Active", "Yes"]


def test_roster_rows_order_by_team_dorsal_last_and_first_name():
    data = [
        _roster(team_name="Zorros", dorsal_number=1, first_name="Z"),
        _roster(dorsal_number=None, first_name="Sin dorsal"),
        _roster(dorsal_number=5, last_name="Ruiz", first_name="Eva"),
        _roster(dorsal_number=5, last_name="Ruiz", first_name="Ana"),
        _roster(dorsal_number=5, last_name="Diaz", first_name="Luz"),
        _roster(team_name="Águilas", dorsal_number=9, first_name="Ágata"),
    ]
    assert [row[2] for row in builders.roster_rows(data, "es")] == [
        "Ágata",
        "Luz",
        "Ana",
        "Eva",
        "Sin dorsal",
        "Z",
    ]


# ---------------------------------------------------------------- acta


def _report_match(**overrides):
    row = {
        "home_team_id": HOME,
        "away_team_id": AWAY,
        "home_team_name": "Halcones",
        "away_team_name": "Águilas",
        "resolution_type": "regular",
        "resolution_reason": None,
        "home_score": 2,
        "away_score": 1,
        "home_penalties": None,
        "away_penalties": None,
    }
    row.update(overrides)
    return row


PLAYERS = {
    P1: {"first_name": "Ana", "last_name": "Ruiz", "dorsal_number": 10},
    P2: {"first_name": "Bea", "last_name": "Diaz", "dorsal_number": 4},
    P3: {"first_name": "Eva", "last_name": "Sol", "dorsal_number": 12},
}

OFFICIALS = [
    {"full_name": "Carla Juez", "role": "main_referee", "email": "carla@example.com"},
    {"full_name": "Dani Banda", "role": "assistant_referee_1", "email": "dani@example.com"},
]

LINEUP = [
    {"team_id": AWAY, "player_id": P2, "role": "starter"},
    {"team_id": HOME, "player_id": P3, "role": "substitute"},
    {"team_id": HOME, "player_id": P1, "role": "starter"},
]

EVENTS = [
    {"id": UUID(int=3), "segment_number": 2, "team_id": HOME, "player_id": P1, "event_type": "goal",
     "minute": 50, "added_minute": None, "assist_player_id": P3, "player_in_id": None, "metadata": {}},
    {"id": UUID(int=2), "segment_number": 1, "team_id": AWAY, "player_id": P2, "event_type": "red_card",
     "minute": 45, "added_minute": 2, "assist_player_id": None, "player_in_id": None,
     "metadata": {"red_card_type": "double_yellow_red"}},
    {"id": UUID(int=1), "segment_number": 1, "team_id": HOME, "player_id": P1, "event_type": "substitution",
     "minute": 30, "added_minute": 0, "assist_player_id": None, "player_in_id": P3, "metadata": {}},
]


def test_match_report_rows_have_result_officials_lineup_and_events_in_order():
    rows = builders.match_report_rows(_report_match(), OFFICIALS, LINEUP, EVENTS, PLAYERS, "es")
    assert rows == [
        ["Resultado", "Halcones", None, None, "Local", None, 2],
        ["Resultado", "Águilas", None, None, "Visitante", None, 1],
        ["Resultado", None, None, None, "Tiempo reglamentario", None, None],
        ["Oficial", None, None, "Carla Juez", "Árbitro principal", None, None],
        ["Oficial", None, None, "Dani Banda", "Asistente 1", None, None],
        ["Alineación", "Halcones", 10, "Ana Ruiz", "Titular", None, None],
        ["Alineación", "Halcones", 12, "Eva Sol", "Suplente", None, None],
        ["Alineación", "Águilas", 4, "Bea Diaz", "Titular", None, None],
        ["Hecho", "Halcones", 10, "Ana Ruiz", "Sustitución", "30", "Entra: Eva Sol"],
        ["Hecho", "Águilas", 4, "Bea Diaz", "Tarjeta roja", "45+2", "Doble amarilla"],
        ["Hecho", "Halcones", 10, "Ana Ruiz", "Gol", "50", "Asistencia: Eva Sol"],
    ]
    assert {len(row) for row in rows} == {_width(catalog.REPORT_KIND)}


def test_match_report_rows_translate_to_english():
    rows = builders.match_report_rows(_report_match(), OFFICIALS, LINEUP, EVENTS, PLAYERS, "en")
    assert rows[0][0] == "Result" and rows[0][4] == "Home"
    assert rows[3][4] == "Referee"
    assert rows[5][4] == "Starter"
    assert rows[8][4:] == ["Substitution", "30", "In: Eva Sol"]
    assert rows[9][6] == "Second yellow"
    assert rows[10][6] == "Assist: Eva Sol"


def test_match_report_rows_never_include_official_emails():
    rows = builders.match_report_rows(_report_match(), OFFICIALS, LINEUP, EVENTS, PLAYERS, "es")
    _assert_no_forbidden(rows, "@example.com")


def test_match_report_rows_add_penalties():
    match = _report_match(resolution_type="penalties", home_score=1, away_score=1,
                          home_penalties=4, away_penalties=3)
    rows = builders.match_report_rows(match, [], [], [], {}, "es")
    assert rows == [
        ["Resultado", "Halcones", None, None, "Local", None, 1],
        ["Resultado", "Águilas", None, None, "Visitante", None, 1],
        ["Resultado", "Halcones", None, None, "Penales", None, 4],
        ["Resultado", "Águilas", None, None, "Penales", None, 3],
        ["Resultado", None, None, None, "Penales", None, None],
    ]


def test_walkover_report_has_result_and_reason_without_events():
    match = _report_match(resolution_type="walkover", home_score=3, away_score=0, resolution_reason="no_show")
    rows = builders.match_report_rows(match, OFFICIALS, LINEUP, EVENTS, PLAYERS, "es")
    assert ["Resultado", None, None, None, "W.O.", None, "Incomparecencia"] in rows
    assert not [row for row in rows if row[0] == "Hecho"]
    english = builders.match_report_rows(match, [], [], EVENTS, PLAYERS, "en")
    assert english[-1] == ["Result", None, None, None, "Walkover", None, "No-show"]


def test_administrative_reason_is_kept_as_written():
    match = _report_match(resolution_type="administrative", resolution_reason="no_show en el acta")
    rows = builders.match_report_rows(match, [], [], [], {}, "es")
    assert rows[-1] == ["Resultado", None, None, None, "Administrativa", None, "no_show en el acta"]


def test_match_report_rows_tolerate_unknown_players_and_red_card_without_type():
    events = [
        {"id": UUID(int=9), "segment_number": 1, "team_id": HOME, "player_id": None, "event_type": "own_goal",
         "minute": 10, "added_minute": None, "assist_player_id": None, "player_in_id": None,
         "metadata": None},
        {"id": UUID(int=8), "segment_number": 1, "team_id": AWAY, "player_id": UUID(int=77),
         "event_type": "red_card", "minute": 12, "added_minute": None, "assist_player_id": None,
         "player_in_id": None, "metadata": {"red_card_type": 5}},
    ]
    rows = builders.match_report_rows(_report_match(), [], [], events, PLAYERS, "es")
    facts = [row for row in rows if row[0] == "Hecho"]
    assert facts == [
        ["Hecho", "Halcones", None, None, "Gol en propia", "10", None],
        ["Hecho", "Águilas", None, None, "Tarjeta roja", "12", None],
    ]


def test_builders_reject_unknown_lang():
    with pytest.raises(ValueError):
        builders.roster_rows([_roster()], "fr")
