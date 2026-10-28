from uuid import uuid4

from pathlib import Path

from app.modules.tournaments.public_stats import (
    MIN_GOALKEEPER_MINUTES,
    assign_ranks,
    clean_sheet_team,
    goalkeeper_minutes,
    clean_sheet_goalkeeper,
    clean_sheet_goalkeepers,
    compute_player_stats,
    compute_team_stats,
    player_stats_rank_key,
    published_formations,
    team_stats_rank_key,
)

ROUTER = Path(__file__).resolve().parents[1] / "app/modules/tournaments/router.py"


def _match(**overrides):
    base = {
        "id": uuid4(),
        "status": "finished",
        "result_confirmed": True,
        "resolution_type": "regular",
        "home_team_id": None,
        "away_team_id": None,
        "home_score": 0,
        "away_score": 0,
        "regular_time_minutes": 90,
    }
    base.update(overrides)
    if base["home_team_id"] is None:
        base["home_team_id"] = uuid4()
    if base["away_team_id"] is None:
        base["away_team_id"] = uuid4()
    return base


def test_clean_sheet_team_basic_home_away():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, home_score=2, away_score=0)
    assert clean_sheet_team(m, [], team_id=home) is True
    assert clean_sheet_team(m, [], team_id=away) is False


def test_clean_sheet_team_confirmed_false():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, status="finished", result_confirmed=False)
    assert clean_sheet_team(m, [], team_id=home) is False


def test_clean_sheet_team_walkover():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, resolution_type="walkover")
    assert clean_sheet_team(m, [], team_id=home) is False


def test_clean_sheet_team_administrative():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, resolution_type="administrative")
    assert clean_sheet_team(m, [], team_id=home) is False


def test_clean_sheet_team_not_finished():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, status="scheduled")
    assert clean_sheet_team(m, [], team_id=home) is False


def test_clean_sheet_team_voided_excluded_unknown_team():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    other = uuid4()
    ev = [
        {"match_id": m["id"], "event_type": "goal", "team_id": away, "player_id": uuid4(), "is_voided": True},
    ]
    assert clean_sheet_team(m, ev, team_id=other) is True


def test_clean_sheet_team_unknown_team_counts_goals():
    home = uuid4()
    away = uuid4()
    m = _match(home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    other = uuid4()
    ev = [
        {"match_id": m["id"], "event_type": "goal", "team_id": away, "player_id": uuid4()},
    ]
    assert clean_sheet_team(m, ev, team_id=other) is False


def test_goalkeeper_minutes_titular_full():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    assert goalkeeper_minutes(m, formation, [], segs) == 90


def test_goalkeeper_minutes_substituted():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    events = [{"match_id": mid, "event_type": "substitution", "player_out_id": pid, "player_in_id": uuid4(), "minute": 50, "added_minute": 0}]
    assert goalkeeper_minutes(m, formation, events, segs) == 50


def test_goalkeeper_minutes_expelled():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    events = [{"match_id": mid, "event_type": "red_card", "player_id": pid, "minute": 70, "added_minute": 0}]
    assert goalkeeper_minutes(m, formation, events, segs) == 70


def test_goalkeeper_minutes_no_formation():
    mid = uuid4()
    m = _match(id=mid)
    assert goalkeeper_minutes(m, None, [], []) == 0


def test_goalkeeper_minutes_substitute_entry():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    pid = uuid4()
    starter = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": False}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    events = [
        {"match_id": mid, "event_type": "substitution", "player_out_id": starter, "player_in_id": pid, "minute": 30, "added_minute": 0},
    ]
    assert goalkeeper_minutes(m, formation, events, segs) == 60


def test_goalkeeper_minutes_effective_duration_no_segments():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, regular_time_minutes=90)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    assert goalkeeper_minutes(m, formation, [], []) == 90


def test_clean_sheet_goalkeeper_titular_qualifies():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    assert clean_sheet_goalkeeper(m, formation, [], segs) == pid


def test_clean_sheet_goalkeeper_titular_less_than_60():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    events = [{"match_id": mid, "event_type": "substitution", "player_out_id": pid, "player_in_id": uuid4(), "minute": 50, "added_minute": 0}]
    assert clean_sheet_goalkeeper(m, formation, events, segs) is None


def test_clean_sheet_goalkeeper_no_formation():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    assert clean_sheet_goalkeeper(m, None, [], []) is None


def test_clean_sheet_goalkeeper_not_clean_sheet():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=0)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    assert clean_sheet_goalkeeper(m, formation, [], segs) == pid


def test_clean_sheet_goalkeeper_walkover():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, resolution_type="walkover", home_score=3, away_score=0)
    pid = uuid4()
    formation = [{"player_id": pid, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    assert clean_sheet_goalkeeper(m, formation, [], segs) is None


def test_clean_sheet_goalkeeper_substitute_qualifies():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    starter = uuid4()
    sub = uuid4()
    f1 = [{"player_id": starter, "position_slot": "GK", "is_starter": True}]
    f2 = [{"player_id": sub, "position_slot": "GK", "is_starter": False}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    events = [{"match_id": mid, "event_type": "substitution", "player_out_id": starter, "player_in_id": sub, "minute": 10, "added_minute": 0}]
    res = clean_sheet_goalkeeper(m, [f1, f2], events, segs)
    vals = res if isinstance(res, list) else ([res] if res is not None else [])
    assert sub in vals


def test_clean_sheet_goalkeeper_two_porteros():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    gk1 = uuid4()
    gk2 = uuid4()
    f1 = [{"player_id": gk1, "position_slot": "GK", "is_starter": True}]
    segs = [{"match_id": mid, "segment_number": 1, "minute_end": 90}]
    events = [{"match_id": mid, "event_type": "substitution", "player_out_id": gk1, "player_in_id": gk2, "minute": 70, "added_minute": 0}]
    f2 = [{"player_id": gk2, "position_slot": "GK", "is_starter": False}]
    res = clean_sheet_goalkeeper(m, [f1, f2], events, segs)
    vals = res if isinstance(res, list) else ([res] if res is not None else [])
    assert gk1 in vals
    assert gk2 not in vals


def test_compute_player_stats_goals_and_cards():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    p1 = uuid4()
    p2 = uuid4()
    rosters = [
        {"player_id": p1, "first_name": "A", "last_name": "Z", "team_id": home, "team_name": "H"},
        {"player_id": p2, "first_name": "B", "last_name": "Y", "team_id": away, "team_name": "A"},
    ]
    events = [
        {"match_id": mid, "player_id": p1, "event_type": "goal", "team_id": home},
        {"match_id": mid, "player_id": p1, "event_type": "yellow_card", "team_id": home},
        {"match_id": mid, "player_id": p2, "event_type": "red_card", "team_id": away},
        {"match_id": mid, "player_id": p2, "event_type": "own_goal", "team_id": away},
    ]
    stats = compute_player_stats([m], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}
    assert by[p1]["goals"] == 1
    assert by[p1]["yellow_cards"] == 1
    assert by[p2]["red_cards"] == 1
    assert by[p2]["goals"] == 0


def test_compute_player_stats_voided_excluded():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    p1 = uuid4()
    rosters = [{"player_id": p1, "first_name": "A", "last_name": "Z", "team_id": home, "team_name": "H"}]
    events = [
        {"match_id": mid, "player_id": p1, "event_type": "goal", "team_id": home, "is_voided": True},
    ]
    stats = compute_player_stats([m], events, [], [], rosters)
    assert all(s.get("goals", 0) == 0 for s in stats)


def test_compute_player_stats_orphan_excluded():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    p_orphan = uuid4()
    events = [
        {"match_id": mid, "player_id": p_orphan, "event_type": "goal", "team_id": home},
    ]
    stats = compute_player_stats([m], events, [], [], [])
    assert all(s["player_id"] != p_orphan for s in stats)


def test_compute_player_stats_lineup_presence():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    p1 = uuid4()
    rosters = [{"player_id": p1, "first_name": "A", "last_name": "Z", "team_id": home, "team_name": "H"}]
    lineups = [{"match_id": mid, "player_id": p1, "team_id": home, "position_slot": "ST", "role": "starter"}]
    stats = compute_player_stats([m], [], lineups, [], rosters)
    assert len(stats) == 1
    assert stats[0]["player_id"] == p1
    assert stats[0]["matches_played"] == 1


def test_compute_player_stats_unconfirmed_not_counted():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, status="scheduled")
    p1 = uuid4()
    rosters = [{"player_id": p1, "first_name": "A", "last_name": "Z", "team_id": home, "team_name": "H"}]
    events = [{"match_id": mid, "player_id": p1, "event_type": "goal", "team_id": home}]
    stats = compute_player_stats([m], events, [], [], rosters)
    assert stats == []


def test_compute_player_stats_aggregation_by_player():
    mid1 = uuid4()
    mid2 = uuid4()
    home = uuid4()
    away = uuid4()
    m1 = _match(id=mid1, home_team_id=home, away_team_id=away)
    m2 = _match(id=mid2, home_team_id=home, away_team_id=away)
    p1 = uuid4()
    rosters = [{"player_id": p1, "first_name": "A", "last_name": "Z", "team_id": home, "team_name": "H"}]
    events = [
        {"match_id": mid1, "player_id": p1, "event_type": "goal", "team_id": home},
        {"match_id": mid2, "player_id": p1, "event_type": "goal", "team_id": home},
    ]
    stats = compute_player_stats([m1, m2], events, [], [], rosters)
    assert len(stats) == 1
    assert stats[0]["goals"] == 2
    assert stats[0]["matches_played"] == 2


def test_compute_team_stats_basic():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=2, away_score=1)
    stats = compute_team_stats([m], [], None)
    by = {s["team_id"]: s for s in stats}
    assert by[home]["goals_for"] == 2
    assert by[home]["goals_against"] == 1
    assert by[away]["goals_for"] == 1
    assert by[away]["goals_against"] == 2


def test_compute_team_stats_clean_sheet():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=0)
    stats = compute_team_stats([m], [], None)
    by = {s["team_id"]: s for s in stats}
    assert by[home]["clean_sheets"] == 1
    assert by[away]["clean_sheets"] == 0


def test_compute_team_stats_unconfirmed_not_counted():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, status="scheduled")
    stats = compute_team_stats([m], [], None)
    assert stats == []


def test_compute_team_stats_fair_play():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    fp = [{"team_id": home, "fair_play_points": 5}]
    stats = compute_team_stats([m], [], fp)
    by = {s["team_id"]: s for s in stats}
    assert by[home]["fair_play_points"] == 5


def test_compute_team_stats_walkover_counts_goals():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, resolution_type="walkover", home_score=3, away_score=0)
    stats = compute_team_stats([m], [], None)
    by = {s["team_id"]: s for s in stats}
    assert by[home]["goals_for"] == 3
    assert by[away]["goals_against"] == 3
    assert by[home]["clean_sheets"] == 0
    assert by[away]["clean_sheets"] == 0


def test_imports_and_basic_clean_sheet():
    home = uuid4()
    away = uuid4()
    match = {
        "id": uuid4(),
        "status": "finished",
        "result_confirmed": True,
        "resolution_type": "regular",
        "home_team_id": home,
        "away_team_id": away,
        "home_score": 2,
        "away_score": 0,
    }
    assert clean_sheet_team(match, [], team_id=home) is True
    assert clean_sheet_team(match, [], team_id=away) is False
    assert goalkeeper_minutes(match, None, [], []) == 0
    assert clean_sheet_goalkeeper(match, None, [], []) is None
    assert compute_player_stats([], [], [], [], []) == []
    assert compute_team_stats([match], [], None)


# ---------------------------------------------------------------------------
# Regla del portero sobre TODAS las formaciones publicadas (spec 022, T12)
# ---------------------------------------------------------------------------


def _segments(mid):
    seg1 = uuid4()
    seg2 = uuid4()
    return seg1, seg2, [
        {"id": seg1, "match_id": mid, "segment_number": 1, "minute_start": 0, "minute_end": 45},
        {"id": seg2, "match_id": mid, "segment_number": 2, "minute_start": 45, "minute_end": 90},
    ]


def _formation_rows(mid, team, segment_id, players, segment_number, is_public=True):
    """Filas planas con la forma de `public.v_public_match_formations` (031)."""

    rows = []
    for player in players:
        rows.append(
            {
                "match_id": mid,
                "team_id": team,
                "segment_id": segment_id,
                "segment_number": segment_number,
                "player_id": player["player_id"],
                "position_slot": player["position_slot"],
                "is_starter": player.get("is_starter", True),
                "is_public": is_public,
            }
        )
    return rows


def _formation(mid, team, segment_id, players, segment_number, is_public=True):
    """Formación ya agrupada (alternativa a las filas planas de la 031)."""

    return {
        "match_id": mid,
        "team_id": team,
        "segment_id": segment_id,
        "segment_number": segment_number,
        "is_public": is_public,
        "players": players,
    }


def _roster(team, *players):
    return [
        {"player_id": p["player_id"], "first_name": "N", "last_name": "A", "team_id": team, "team_name": "T"}
        for p in players
    ]


def test_published_formations_ordena_por_segmento_y_descarta_no_publicadas():
    mid = uuid4()
    home = uuid4()
    gk1 = {"player_id": uuid4(), "position_slot": "GK"}
    gk2 = {"player_id": uuid4(), "position_slot": "GK"}
    gk3 = {"player_id": uuid4(), "position_slot": "GK"}
    seg1, seg2, _ = _segments(mid)
    first = _formation(mid, home, seg1, [gk1], segment_number=1)
    second = _formation(mid, home, seg2, [gk2], segment_number=2)
    hidden = _formation(mid, home, seg2, [gk3], segment_number=2, is_public=False)

    ordered = published_formations([second, hidden, first], match_id=mid)

    assert ordered == [first, second]


def test_case_12_sin_formacion_publicada_no_hay_portero():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    _, _, segs = _segments(mid)

    # El equipo sí tiene portería imbatida, pero no hay portero identificable.
    assert clean_sheet_team(m, [], team_id=home) is True
    assert clean_sheet_goalkeepers(m, [], [], segs) == []
    assert clean_sheet_goalkeeper(m, None, [], segs) is None
    assert compute_player_stats([m], [], [], segs, []) == []


def test_case_13_formacion_no_publicada_no_atribuye_portero():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, _, segs = _segments(mid)
    player = {"player_id": gk, "position_slot": "GK", "is_starter": True}

    # La regla comprueba `is_public` ella misma: no delega en el WHERE de la vista.
    hidden = _formation(mid, home, seg1, [player], segment_number=1, is_public=False)
    assert clean_sheet_team(m, [], team_id=home) is True
    assert published_formations([hidden]) == []
    assert clean_sheet_goalkeepers(m, [hidden], [], segs) == []
    assert clean_sheet_goalkeeper(m, hidden, [], segs) is None

    # Tampoco con filas planas de la proyección marcadas como no publicadas.
    hidden_rows = _formation_rows(mid, home, seg1, [player], segment_number=1, is_public=False)
    assert clean_sheet_goalkeepers(m, hidden_rows, [], segs) == []

    stats = compute_player_stats([m], [], [hidden], segs, _roster(home, player))
    assert [s for s in stats if s.get("clean_sheets")] == []


def test_case_14_dos_porteros_uno_por_equipo():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk_home = uuid4()
    gk_away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, _, segs = _segments(mid)
    f_home = _formation(
        mid, home, seg1, [{"player_id": gk_home, "position_slot": "GK", "is_starter": True}], segment_number=1
    )
    f_away = _formation(
        mid, away, seg1, [{"player_id": gk_away, "position_slot": "GK", "is_starter": True}], segment_number=1
    )

    assert set(clean_sheet_goalkeepers(m, [f_home, f_away], [], segs)) == {gk_home, gk_away}


def test_case_16_portero_expulsado_y_reemplazado_por_jugador_de_campo():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    field_player = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, seg2, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    ) + _formation_rows(
        mid, home, seg2, [{"player_id": field_player, "position_slot": "ST", "is_starter": True}], segment_number=2
    )
    events = [
        {"match_id": mid, "event_type": "red_card", "player_id": gk, "minute": 70, "added_minute": 0},
        {
            "match_id": mid,
            "event_type": "substitution",
            "player_id": gk,
            "player_out_id": gk,
            "player_in_id": field_player,
            "minute": 70,
            "added_minute": 0,
        },
    ]

    # Expulsado a los 70: los minutos jugados (70) superan el umbral de 60.
    assert clean_sheet_goalkeepers(m, rows, events, segs) == [gk]
    assert MIN_GOALKEEPER_MINUTES == 60


def test_case_16b_portero_entrante_titular_de_formacion_posterior():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk_a = uuid4()
    gk_b = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, seg2, segs = _segments(mid)
    # B es titular de la formación del segmento 2: el código anterior lo
    # descartaba por `if _is_starter(p): continue`.
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk_a, "position_slot": "GK", "is_starter": True}], segment_number=1
    ) + _formation_rows(
        mid, home, seg2, [{"player_id": gk_b, "position_slot": "GK", "is_starter": True}], segment_number=2
    )
    events = [
        {
            "match_id": mid,
            "event_type": "substitution",
            "player_id": gk_a,
            "player_out_id": gk_a,
            "player_in_id": gk_b,
            "minute": 30,
            "added_minute": 0,
        }
    ]
    players = [
        {"player_id": gk_a, "position_slot": "GK"},
        {"player_id": gk_b, "position_slot": "GK"},
    ]

    assert clean_sheet_goalkeepers(m, rows, events, segs) == [gk_b]

    # También por el flujo agregado (no solo por la función aislada).
    stats = compute_player_stats([m], events, rows, segs, _roster(home, *players))
    by = {s["player_id"]: s for s in stats}
    assert by[gk_b]["clean_sheets"] == 1
    assert by[gk_a]["clean_sheets"] == 0


def test_case_16c_suplente_que_no_es_gk_no_recibe_porteria_imbatida():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk_a = uuid4()
    field_player = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, seg2, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk_a, "position_slot": "GK", "is_starter": True}], segment_number=1
    ) + _formation_rows(
        mid, home, seg2, [{"player_id": field_player, "position_slot": "ST", "is_starter": True}], segment_number=2
    )
    events = [
        {
            "match_id": mid,
            "event_type": "substitution",
            "player_id": gk_a,
            "player_out_id": gk_a,
            "player_in_id": field_player,
            "minute": 30,
            "added_minute": 0,
        }
    ]
    players = [
        {"player_id": gk_a, "position_slot": "GK"},
        {"player_id": field_player, "position_slot": "ST"},
    ]

    # El suplente no figura como GK en ninguna formación publicada: no se le
    # atribuye y el equipo conserva su portería imbatida.
    assert clean_sheet_goalkeepers(m, rows, events, segs) == []
    team_stats = compute_team_stats([m], events, None)
    assert {t["team_id"]: t for t in team_stats}[home]["clean_sheets"] == 1

    stats = compute_player_stats([m], events, rows, segs, _roster(home, *players))
    by = {s["player_id"]: s for s in stats}
    assert by[field_player]["clean_sheets"] == 0
    assert by[gk_a]["clean_sheets"] == 0


def test_compute_player_stats_atribuye_porteria_imbatida_al_portero_entrante():
    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk_a = uuid4()
    gk_b = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, seg2, segs = _segments(mid)
    # Formaciones ya agrupadas: A titular del segmento 1, B titular del 2.
    formations = [
        _formation(mid, home, seg1, [{"player_id": gk_a, "position_slot": "GK", "is_starter": True}], segment_number=1),
        _formation(mid, home, seg2, [{"player_id": gk_b, "position_slot": "GK", "is_starter": True}], segment_number=2),
    ]
    events = [
        {
            "match_id": mid,
            "event_type": "substitution",
            "player_id": gk_a,
            "player_out_id": gk_a,
            "player_in_id": gk_b,
            "minute": 30,
            "added_minute": 0,
        }
    ]
    players = [
        {"player_id": gk_a, "position_slot": "GK"},
        {"player_id": gk_b, "position_slot": "GK"},
    ]

    stats = compute_player_stats([m], events, formations, segs, _roster(home, *players))
    by = {s["player_id"]: s for s in stats}
    assert by[gk_b]["clean_sheets"] == 1
    assert by[gk_a]["clean_sheets"] == 0
    # Como máximo una atribución por portero y partido (RF-030).
    assert sum(s["clean_sheets"] for s in stats) == 1


def test_compute_player_stats_substitution_acredita_al_que_sale_y_al_que_entra():
    """T13 (RF-012, RF-022): la sustitución acredita a **ambos** jugadores."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=0)
    scorer = uuid4()
    entrant = uuid4()
    rosters = [
        {"player_id": scorer, "first_name": "Goleador", "last_name": "A", "team_id": home},
        {"player_id": entrant, "first_name": "Entrante", "last_name": "B", "team_id": home},
    ]
    events = [
        {"match_id": mid, "player_id": scorer, "event_type": "goal", "team_id": home, "minute": 10},
        {
            "match_id": mid,
            "player_id": scorer,
            "player_out_id": scorer,
            "player_in_id": entrant,
            "event_type": "substitution",
            "team_id": home,
            "minute": 60,
        },
    ]

    stats = compute_player_stats([m], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}

    # El que sale ya estaba acreditado por su gol; el que entra entra por la
    # sustitución (RF-012) y comparte el mismo partido disputado (RF-022).
    assert set(by) == {scorer, entrant}
    assert by[scorer]["matches_played"] == 1
    assert by[entrant]["matches_played"] == 1
    assert by[scorer]["goals"] == 1
    # El jugador entrante **no** hereda goles ni tarjetas del evento.
    assert by[entrant]["goals"] == 0
    assert by[entrant]["yellow_cards"] == 0
    assert by[entrant]["red_cards"] == 0
    assert by[entrant]["clean_sheets"] == 0


def test_compute_player_stats_entrante_en_dos_partidos_distintos():
    """T13 (RF-022): solo entrar en dos partidos suma dos partidos disputados."""

    home = uuid4()
    away = uuid4()
    mid1 = uuid4()
    mid2 = uuid4()
    m1 = _match(id=mid1, home_team_id=home, away_team_id=away)
    m2 = _match(id=mid2, home_team_id=home, away_team_id=away)
    starter = uuid4()
    entrant = uuid4()
    rosters = [
        {"player_id": starter, "first_name": "Titular", "last_name": "A", "team_id": home},
        {"player_id": entrant, "first_name": "Suplente", "last_name": "B", "team_id": home},
    ]
    events = [
        {
            "match_id": mid1,
            "player_id": starter,
            "player_out_id": starter,
            "player_in_id": entrant,
            "event_type": "substitution",
            "team_id": home,
            "minute": 70,
        },
        {
            "match_id": mid2,
            "player_id": starter,
            "player_out_id": starter,
            "player_in_id": entrant,
            "event_type": "substitution",
            "team_id": home,
            "minute": 55,
        },
    ]

    stats = compute_player_stats([m1, m2], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}
    assert by[entrant]["matches_played"] == 2
    assert by[starter]["matches_played"] == 2
    assert by[entrant]["goals"] == 0


def test_compute_player_stats_entrante_no_duplica_el_partido():
    """T13 (RF-022): varios eventos del mismo partido cuentan una sola vez."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    starter = uuid4()
    entrant = uuid4()
    rosters = [
        {"player_id": starter, "first_name": "Titular", "last_name": "A", "team_id": home},
        {"player_id": entrant, "first_name": "Suplente", "last_name": "B", "team_id": home},
    ]
    events = [
        {
            "match_id": mid,
            "player_id": starter,
            "player_out_id": starter,
            "player_in_id": entrant,
            "event_type": "substitution",
            "team_id": home,
            "minute": 46,
        },
        {"match_id": mid, "player_id": entrant, "event_type": "yellow_card", "team_id": home, "minute": 80},
    ]

    stats = compute_player_stats([m], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}
    assert by[entrant]["matches_played"] == 1
    assert by[entrant]["yellow_cards"] == 1
    assert by[starter]["matches_played"] == 1


def test_compute_player_stats_entrante_huerfano_se_ignora():
    """T13: un ``player_in_id`` fuera de la plantilla se ignora sin fallar."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away)
    starter = uuid4()
    orphan = uuid4()
    rosters = [
        {"player_id": starter, "first_name": "Titular", "last_name": "A", "team_id": home},
    ]
    events = [
        {
            "match_id": mid,
            "player_id": starter,
            "player_out_id": starter,
            "player_in_id": orphan,
            "event_type": "substitution",
            "team_id": home,
            "minute": 60,
        },
    ]

    stats = compute_player_stats([m], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}
    assert orphan not in by
    assert by[starter]["matches_played"] == 1


# ---------------------------------------------------------------------------
# T16 — columna de posición (RF-006, RF-022)
# ---------------------------------------------------------------------------


def _rank_row(player_id: str, **overrides):
    row = {
        "player_id": player_id,
        # Apellido constante: el empate se decide por goles y partidos, y el
        # identificador solo ordena dentro del grupo.
        "last_name": "Igual",
        "goals": 0,
        "matches_played": 0,
    }
    row.update(overrides)
    return row


def test_assign_ranks_empate_doble_comparte_posicion_y_continua():
    """RF-022: dos empatados → 1, 2, 2, 4 (no 1, 2, 3, 4)."""

    rows = [
        _rank_row("a", goals=3),
        _rank_row("b", goals=1),
        _rank_row("c", goals=1),
        _rank_row("d", goals=0),
    ]

    ordered = assign_ranks(rows, player_stats_rank_key, "player_id")

    assert [row["player_id"] for row in ordered] == ["a", "b", "c", "d"]
    assert [row["rank"] for row in ordered] == [1, 2, 2, 4]


def test_assign_ranks_empate_triple_comparte_posicion_y_continua():
    """RF-022: tres empatados → 1, 2, 2, 2, 5."""

    rows = [
        _rank_row("a", goals=3),
        _rank_row("b", goals=1),
        _rank_row("c", goals=1),
        _rank_row("d", goals=1),
        _rank_row("e", goals=0),
    ]

    ordered = assign_ranks(rows, player_stats_rank_key, "player_id")

    assert [row["rank"] for row in ordered] == [1, 2, 2, 2, 5]


def test_assign_ranks_sin_empates_numera_de_uno_a_n():
    """RF-006: sin empates la posición es el índice."""

    rows = [_rank_row("a", goals=3), _rank_row("b", goals=2), _rank_row("c", goals=1)]

    ordered = assign_ranks(rows, player_stats_rank_key, "player_id")

    assert [row["rank"] for row in ordered] == [1, 2, 3]


def test_assign_ranks_identificador_solo_ordena_dentro_del_empate():
    """RF-022: el identificador ordena el empate pero no lo desempata."""

    rows = [
        _rank_row("zzz", goals=2, last_name="Igual", matches_played=1),
        _rank_row("aaa", goals=2, last_name="Igual", matches_played=1),
    ]

    ordered = assign_ranks(rows, player_stats_rank_key, "player_id")

    # Orden estable por identificador dentro del empate…
    assert [row["player_id"] for row in ordered] == ["aaa", "zzz"]
    # …y la posición sigue compartida.
    assert [row["rank"] for row in ordered] == [1, 1]


def test_assign_ranks_es_reproducible_con_los_mismos_datos():
    """RF-006: dos consultas con los mismos datos devuelven el mismo orden."""

    rows = [
        _rank_row("p5", goals=1, last_name="Ruiz", matches_played=2),
        _rank_row("p1", goals=1, last_name="Ruiz", matches_played=2),
        _rank_row("p3", goals=2, last_name="Sosa", matches_played=1),
        _rank_row("p2", goals=1, last_name="Alba", matches_played=2),
        _rank_row("p4", goals=0, last_name="Vega", matches_played=3),
    ]

    first = [(row["player_id"], row["rank"]) for row in assign_ranks(rows, player_stats_rank_key, "player_id")]
    second = [(row["player_id"], row["rank"]) for row in assign_ranks(rows, player_stats_rank_key, "player_id")]

    assert first == second
    # Goles descendentes; el empate a un gol se ordena por partidos, apellido e id.
    assert [player for player, _ in first] == ["p3", "p2", "p1", "p5", "p4"]
    # p1 y p5 empatan en los tres criterios visibles; p2 no (otro apellido).
    assert [rank for _, rank in first] == [1, 2, 3, 3, 5]


def test_assign_ranks_paginar_no_reinicia_la_posicion():
    """RF-006/RF-009: la página 2 continúa la numeración global (no reinicia en 1)."""

    rows = [
        _rank_row("a", goals=3),
        _rank_row("b", goals=1),
        _rank_row("c", goals=1),
        _rank_row("d", goals=0),
    ]

    ordered = assign_ranks(rows, player_stats_rank_key, "player_id")
    first_page = ordered[0:2]
    second_page = ordered[1:3]

    assert [row["rank"] for row in first_page] == [1, 2]
    # `offset=1&limit=1` sobre el empate devuelve la posición 2, no 1.
    assert second_page[0]["rank"] == 2
    assert [row["rank"] for row in second_page] == [2, 2]
    assert [row["rank"] for row in ordered[2:4]] == [2, 4]


def test_player_stats_rank_key_ordena_por_los_criterios_visibles():
    """RF-022: goles descendente, menos partidos y apellido; sin el id."""

    assert player_stats_rank_key({"goals": 2, "matches_played": 3, "last_name": "B"}) == (
        -2,
        3,
        "B",
    )
    assert player_stats_rank_key({"goals": 0, "matches_played": 0, "last_name": None}) == (
        0,
        0,
        "",
    )


def test_team_stats_rank_key_ordena_por_los_criterios_visibles():
    """RF-022: goles a favor descendente, menos en contra y nombre; sin el id."""

    assert team_stats_rank_key({"goals_for": 5, "goals_against": 2, "team_name": "Alfa"}) == (
        -5,
        2,
        "Alfa",
    )
    assert team_stats_rank_key({"goals_for": 1, "goals_against": 0, "team_name": None}) == (
        -1,
        0,
        "",
    )


def test_assign_ranks_acepta_nombres_de_campo():
    """RF-006: los criterios visibles también pueden nombrarse por campo."""

    rows = [
        {"team_id": "b", "goals_for": 1, "goals_against": 1, "team_name": "Igual"},
        {"team_id": "a", "goals_for": 1, "goals_against": 1, "team_name": "Igual"},
    ]

    ordered = assign_ranks(rows, ("goals_for", "goals_against", "team_name"), "team_id")

    assert [row["team_id"] for row in ordered] == ["a", "b"]
    assert [row["rank"] for row in ordered] == [1, 1]


def test_compute_player_stats_con_assign_ranks_comparte_posicion():
    """RF-022: el conjunto ordenado que alimenta la respuesta comparte posición."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=4, away_score=0)
    top = uuid4()
    tie_b = uuid4()
    tie_a = uuid4()
    rosters = [
        {"player_id": top, "first_name": "T", "last_name": "Top", "team_id": home},
        {"player_id": tie_b, "first_name": "B", "last_name": "Igual", "team_id": home},
        {"player_id": tie_a, "first_name": "A", "last_name": "Igual", "team_id": home},
    ]
    events = [
        {"match_id": mid, "player_id": top, "event_type": "goal", "team_id": home, "minute": 10},
        {"match_id": mid, "player_id": top, "event_type": "goal", "team_id": home, "minute": 20},
        {"match_id": mid, "player_id": tie_b, "event_type": "goal", "team_id": home, "minute": 30},
        {"match_id": mid, "player_id": tie_a, "event_type": "goal", "team_id": home, "minute": 40},
    ]

    stats = compute_player_stats([m], events, [], [], rosters)
    ordered = assign_ranks(stats, player_stats_rank_key, "player_id")

    ordered_ids = [row["player_id"] for row in ordered]
    assert ordered_ids[0] == top
    # El empate se ordena por el identificador estable, sin desempatar la posición.
    assert ordered_ids[1:] == sorted([tie_a, tie_b], key=str)
    assert [row["rank"] for row in ordered] == [1, 2, 2]


def test_endpoints_aplican_assign_ranks_antes_de_paginar():
    """RF-006/D9: el rank se calcula en el servidor y antes del recorte."""

    source = ROUTER.read_text(encoding="utf-8")

    assert "stats.sort(" not in source
    assert source.count("assign_ranks(") == 2
    assert source.count("[offset: offset + limit]") == 2
    for section in source.split("assign_ranks(")[1:]:
        assert "[offset: offset + limit]" in section


# ---------------------------------------------------------------------------
# Cableado del endpoint a la proyección de la 031 (spec 022, T12, caso 16b)
#
# Comprobaciones **estáticas** (sin base, sin red y sin pytest de integración):
# leen el router real y aíslan el handler. Son las que demuestran aquí que la
# ruta de estadísticas de jugadores alimenta la regla con **todas** las
# formaciones publicadas y no con la última por equipo de `v_public_match_lineups`.
# ---------------------------------------------------------------------------


def _player_stats_route_source() -> str:
    """Cuerpo real de ``GET /public/{tournament_id}/player-stats``."""

    source = ROUTER.read_text(encoding="utf-8")
    start = source.index("async def public_player_stats(")
    end = source.index("async def public_team_stats(", start)
    return source[start:end]


def test_endpoint_de_jugadores_lee_las_formaciones_de_la_proyeccion_031():
    """T12/16b: la ruta lee la 031, no la vista de la última formación."""

    body = _player_stats_route_source()

    assert "FROM v_public_match_formations" in body
    assert "FROM v_public_match_lineups" not in body
    # Las filas planas de la proyección llegan a la regla como 3.er argumento.
    assert "compute_player_stats(matches, events, formations, segments, rosters)" in body
    # Columnas que la regla necesita para ver al portero entrante.
    for column in ("segment_id", "segment_number", "player_id", "position_slot", "is_starter", "is_public"):
        assert column in body, column


def test_endpoint_de_jugadores_acota_las_formaciones_al_ambito_resuelto():
    """El filtro por fase no se amplía: se acota a los `match_ids` ya resueltos."""

    body = _player_stats_route_source()
    query = body.split("FROM v_public_match_formations")[1].split('"""')[0]

    assert "WHERE tournament_id = :tournament_id" in query
    assert "match_id = ANY(CAST(:match_ids AS UUID[]))" in query


def test_la_lectura_publica_de_alineaciones_de_la_021_sigue_intacta():
    """La spec 021 conserva `v_public_match_lineups` en el detalle público."""

    source = ROUTER.read_text(encoding="utf-8")
    start = source.index("async def public_matches(")
    end = source.index("async def public_player_stats(")
    detail = source[start:end]

    assert "FROM v_public_match_lineups" in detail
    # `segment_number` es el campo aditivo de la 021 (RF-007/RF-015).
    assert "segment_number" in detail
    # Única lectura de la vista pública: la del detalle, no la de estadísticas.
    assert source.count("FROM v_public_match_lineups") == 1


# ---------------------------------------------------------------------------
# Contrato declarado de las dos rutas de estadísticas (spec 022, T5, RF-036)
#
# Comprobación **estática** (sin base, sin red y sin pydantic): declarar el
# `response_model` es lo que hace efectiva la lista cerrada de campos públicos.
# Sin él, ninguna clave que se colara en el dict del handler quedaría filtrada:
# hoy los handlers limpian a mano `photo_consent` (jugadores) y `crest_object_key`
# (equipos, vía `sign_crest_rows`), así que la respuesta coincide con el modelo
# por código y no por contrato; el filtro del modelo es la garantía.
# La prueba de lista cerrada con datos reales es la de T17
# (`test_public_stats_endpoints.py`), que además comprueba que las dos rutas
# declaran el modelo sobre la app real.
# ---------------------------------------------------------------------------

#: Handler -> `response_model` declarado (lista: la ruta devuelve una tabla).
STATS_RESPONSE_MODELS = {
    "public_player_stats": "list[PublicPlayerStatsResponse]",
    "public_team_stats": "list[PublicTeamStatsResponse]",
}


def _route_decorator_source(handler: str) -> str:
    """Texto del decorador ``@router.get(...)`` inmediatamente anterior al handler."""

    source = ROUTER.read_text(encoding="utf-8")
    handler_start = source.index(f"async def {handler}(")
    decorator_start = source.rindex("@router.get(", 0, handler_start)
    return source[decorator_start:handler_start]


def test_las_dos_rutas_de_estadisticas_declaran_su_response_model():
    """T5/RF-036: el modelo de respuesta cierra los campos de las dos tablas."""

    source = ROUTER.read_text(encoding="utf-8")
    for handler, model in STATS_RESPONSE_MODELS.items():
        decorator = _route_decorator_source(handler)
        assert f"response_model={model}" in decorator, (handler, decorator)
        # El tipo de retorno declarado coincide con el modelo del decorador.
        closing = source.index("\n) -> ", source.index(f"async def {handler}(")) + 1
        signature = source[closing : source.index(":\n", closing) + 1]
        assert f"-> {model}:" in signature, signature


# ---------------------------------------------------------------------------
# Casos límite faltantes de la tabla de porterías imbatidas (spec 022, T19)
# ---------------------------------------------------------------------------


def test_case_03_portero_expulsado_a_los_70_minutos_califica():
    """Caso 3: portero expulsado a los 70 min → equipo Sí, portero Sí (70 ≥ 60)."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0)
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )
    events = [{"match_id": mid, "event_type": "red_card", "player_id": gk, "minute": 70, "added_minute": 0}]

    assert clean_sheet_team(m, events, team_id=home) is True
    assert clean_sheet_goalkeepers(m, rows, events, segs) == [gk]


def test_case_04_marcador_final_1_1_no_hay_porteria_imbatida():
    """Caso 4: marcador final 1-1 → equipo No, portero No."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=1)
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )

    assert clean_sheet_team(m, [], team_id=home) is False
    assert clean_sheet_team(m, [], team_id=away) is False
    assert clean_sheet_goalkeepers(m, rows, [], segs) == []


def test_case_05_autogol_cuenta_como_gol_recibido():
    """Caso 5: autogol de jugador propio → equipo No, portero No; no es gol del jugador."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    scorer = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=1)
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )
    events = [{"match_id": mid, "event_type": "own_goal", "player_id": scorer, "team_id": home, "minute": 10}]

    assert clean_sheet_team(m, events, team_id=home) is False
    assert clean_sheet_goalkeepers(m, rows, events, segs) == []

    rosters = [{"player_id": scorer, "first_name": "A", "last_name": "Z", "team_id": home, "team_name": "H"}]
    stats = compute_player_stats([m], events, rows, segs, rosters)
    by = {s["player_id"]: s for s in stats}
    assert by[scorer]["goals"] == 0


def test_case_06_goles_solo_en_prorroga_se_evalua_con_marcador_final():
    """Caso 6: goles solo en prórroga → se evalúa con el marcador final (prórroga incluida)."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    # Marcador final 0-0 (incluida prórroga) → clean sheet.
    m = _match(
        id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0,
        resolution_type="extra_time", regular_time_minutes=90,
    )
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )

    assert clean_sheet_team(m, [], team_id=home) is True
    assert clean_sheet_goalkeepers(m, rows, [], segs) == [gk]

    # Gol en prórroga → marcador final con gol → no clean sheet.
    m2 = _match(
        id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=1,
        resolution_type="extra_time", regular_time_minutes=90,
    )
    assert clean_sheet_team(m2, [], team_id=home) is False


def test_case_07_tanda_penales_no_cuenta_como_gol():
    """Caso 7: tanda de penales → clean sheet si no recibió gol en juego; penales no cuentan."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0, resolution_type="penalties")
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )

    assert clean_sheet_team(m, [], team_id=home) is True
    assert clean_sheet_goalkeepers(m, rows, [], segs) == [gk]


def test_case_10_partido_suspendido_o_cancelado_no_contribuye():
    """Caso 10: partido suspendido o cancelado → no contribuye (no es resultado confirmado)."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    for status in ("suspended", "cancelled"):
        m = _match(id=mid, home_team_id=home, away_team_id=away, status=status, home_score=0, away_score=0)
        seg1, _, segs = _segments(mid)
        rows = _formation_rows(
            mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
        )
        assert clean_sheet_team(m, [], team_id=home) is False
        assert clean_sheet_goalkeepers(m, rows, [], segs) == []

    m = _match(id=mid, home_team_id=home, away_team_id=away, status="suspended", home_score=0, away_score=0)
    assert compute_team_stats([m], [], None) == []
    assert compute_player_stats([m], [], [], [], []) == []


def test_case_11_partido_terminado_con_menos_minutos_cuenta():
    """Caso 11: partido terminado con menos minutos pero acta confirmada → clean sheet si 0 recibidos."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=0, regular_time_minutes=90)
    seg_id = uuid4()
    segs = [{"id": seg_id, "match_id": mid, "segment_number": 1, "minute_start": 0, "minute_end": 60}]
    rows = _formation_rows(
        mid, home, seg_id, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )

    assert clean_sheet_team(m, [], team_id=home) is True
    assert clean_sheet_goalkeepers(m, rows, [], segs) == [gk]
    assert goalkeeper_minutes(m, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], [], segs) == 60


def test_case_15_portero_que_marca_gol_califica():
    """Caso 15: portero que marca un gol (no autogol) → equipo Sí, portero Sí."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=0)
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )
    events = [{"match_id": mid, "event_type": "goal", "player_id": gk, "team_id": home, "minute": 10}]

    assert clean_sheet_team(m, events, team_id=home) is True
    assert clean_sheet_goalkeepers(m, rows, events, segs) == [gk]


def test_case_15b_portero_que_marca_autogol_no_califica():
    """Caso 15b: portero que marca un autogol → equipo No, portero No."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    gk = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=0, away_score=1)
    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": gk, "position_slot": "GK", "is_starter": True}], segment_number=1
    )
    events = [{"match_id": mid, "event_type": "own_goal", "player_id": gk, "team_id": home, "minute": 10}]

    assert clean_sheet_team(m, events, team_id=home) is False
    assert clean_sheet_goalkeepers(m, rows, events, segs) == []


def test_case_17_dos_inscripciones_mismo_jugador_se_agregan():
    """Caso 17: dos inscripciones del mismo jugador en equipos distintos → se agrega por jugador."""

    home1 = uuid4()
    home2 = uuid4()
    away = uuid4()
    mid1 = uuid4()
    mid2 = uuid4()
    m1 = _match(id=mid1, home_team_id=home1, away_team_id=away, home_score=1, away_score=0)
    m2 = _match(id=mid2, home_team_id=home2, away_team_id=away, home_score=2, away_score=0)
    player = uuid4()
    rosters = [
        {"player_id": player, "first_name": "P", "last_name": "Q", "team_id": home1, "team_name": "T1"},
        {"player_id": player, "first_name": "P", "last_name": "Q", "team_id": home2, "team_name": "T2"},
    ]
    events = [
        {"match_id": mid1, "player_id": player, "event_type": "goal", "team_id": home1},
        {"match_id": mid2, "player_id": player, "event_type": "goal", "team_id": home2},
        {"match_id": mid2, "player_id": player, "event_type": "goal", "team_id": home2},
    ]

    stats = compute_player_stats([m1, m2], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}
    assert player in by
    assert by[player]["goals"] == 3
    assert by[player]["matches_played"] == 2


def test_case_18_jugador_retirado_aparece_con_historico():
    """Caso 18: jugador retirado lógicamente → aparece con su histórico (sin foto a nivel endpoint)."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    player = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=0)
    rosters = [
        {"player_id": player, "first_name": "R", "last_name": "S", "team_id": home,
         "team_name": "H", "is_active": False, "photo_url": "http://x", "photo_consent": True},
    ]
    events = [{"match_id": mid, "player_id": player, "event_type": "goal", "team_id": home}]

    stats = compute_player_stats([m], events, [], [], rosters)
    by = {s["player_id"]: s for s in stats}
    assert player in by
    assert by[player]["goals"] == 1
    # La foto no se deriva aquí: RF-034 la suprime en el endpoint para inscripciones retiradas.


def test_case_19_actas_historicas_se_leen_sin_error():
    """Caso 19: actas con identificadores de texto libre / referencias huérfanas → sin error ni cifra inventada."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=1, away_score=0)
    events = [
        {"match_id": mid, "player_id": uuid4(), "event_type": "goal", "team_id": home,
         "client_event_id": "free-text-id", "segment_id": "not-a-uuid"},
        {"match_id": mid, "player_id": None, "event_type": "goal", "team_id": home},
    ]

    stats = compute_player_stats([m], events, [], [], [])
    assert isinstance(stats, list)

    tstats = compute_team_stats([m], events, None)
    assert isinstance(tstats, list)

    seg1, _, segs = _segments(mid)
    rows = _formation_rows(
        mid, home, seg1, [{"player_id": uuid4(), "position_slot": "GK", "is_starter": True}], segment_number=1
    )
    # El equipo tiene clean sheet (0 recibidos en el marcador); la atribución del portero
    # no falla aunque los eventos tengan referencias huérfanas (no se inventa cifra).
    assert isinstance(clean_sheet_goalkeepers(m, rows, events, segs), list)


def test_rf_005_coherencia_goles_con_marcador_final():
    """RF-005: goles atribuidos a jugadores + autogoles coinciden con el marcador final."""

    mid = uuid4()
    home = uuid4()
    away = uuid4()
    p_home = uuid4()
    p_away = uuid4()
    p_own = uuid4()
    m = _match(id=mid, home_team_id=home, away_team_id=away, home_score=2, away_score=1)
    rosters = [
        {"player_id": p_home, "first_name": "H", "last_name": "A", "team_id": home},
        {"player_id": p_away, "first_name": "A", "last_name": "B", "team_id": away},
        {"player_id": p_own, "first_name": "O", "last_name": "C", "team_id": away},
    ]
    events = [
        {"match_id": mid, "player_id": p_home, "event_type": "goal", "team_id": home},
        {"match_id": mid, "player_id": p_own, "event_type": "own_goal", "team_id": away},
        {"match_id": mid, "player_id": p_away, "event_type": "goal", "team_id": away},
    ]

    tstats = compute_team_stats([m], events, None)
    by_team = {s["team_id"]: s for s in tstats}
    assert by_team[home]["goals_for"] == 2
    assert by_team[away]["goals_for"] == 1

    pstats = compute_player_stats([m], events, [], [], rosters)
    by_p = {s["player_id"]: s for s in pstats}
    home_player_goals = by_p[p_home]["goals"]
    # El autogol del rival cuenta como gol a favor del home.
    assert home_player_goals + 1 == by_team[home]["goals_for"]


def test_assign_ranks_team_empate_comparte_posicion():
    """RF-022: empate en la tabla de equipos comparte posición (1, 2, 2, 4)."""

    rows = [
        {"team_id": "a", "goals_for": 5, "goals_against": 1, "team_name": "Igual"},
        {"team_id": "b", "goals_for": 3, "goals_against": 2, "team_name": "Igual"},
        {"team_id": "c", "goals_for": 3, "goals_against": 2, "team_name": "Igual"},
        {"team_id": "d", "goals_for": 1, "goals_against": 0, "team_name": "Igual"},
    ]

    ordered = assign_ranks(rows, team_stats_rank_key, "team_id")
    assert [row["team_id"] for row in ordered] == ["a", "b", "c", "d"]
    assert [row["rank"] for row in ordered] == [1, 2, 2, 4]
