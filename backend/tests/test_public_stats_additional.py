"""Minutos, posición principal y penales atajados (spec 052, T4): cálculo puro.

DA-1: los minutos solo cuentan en partidos disputados con la alineación del
equipo publicada. DA-2: la posición principal es la línea con más partidos y,
en empate, la del partido más reciente. DA-3: la posición de entrada solo es
pública con la formación del equipo publicada. DA-4: penal atajado.
"""

import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.modules.tournaments.public_stats import assign_ranks, compute_player_stats, player_stats_rank_key

HOME, AWAY = uuid4(), uuid4()
START = datetime(2026, 3, 1, tzinfo=timezone.utc)


def match(*, days=0, resolution="regular", confirmed=True, home=HOME, away=AWAY):
    return {
        "id": uuid4(), "status": "finished", "result_confirmed": confirmed, "resolution_type": resolution,
        "home_team_id": home, "away_team_id": away, "home_score": 0, "away_score": 0,
        "match_date": None if days is None else START + timedelta(days=days),
    }


def segments(m, *ends):
    rows, start = [], 0
    for number, end in enumerate(ends or (90,), start=1):
        rows.append({"id": uuid4(), "match_id": m["id"], "segment_number": number,
                     "minute_start": start, "minute_end": end, "status": "completed"})
        start = end
    return rows


def lineup(m, team, starters, *, segment=1, public=True, substitutes=()):
    """Filas planas de `v_public_match_formations`: `starters` es {jugador: posición}."""
    rows = [
        {"match_id": m["id"], "segment_id": f"{m['id']}-{segment}", "segment_number": segment, "team_id": team,
         "player_id": pid, "position_slot": slot, "is_starter": True, "is_public": public}
        for pid, slot in starters.items()
    ]
    rows += [
        {"match_id": m["id"], "segment_id": f"{m['id']}-{segment}", "segment_number": segment, "team_id": team,
         "player_id": pid, "position_slot": None, "is_starter": False, "is_public": public}
        for pid in substitutes
    ]
    return rows


def sub(m, team, out_id, in_id, minute, position=None, **extra):
    return {"id": uuid4(), "match_id": m["id"], "team_id": team, "player_id": out_id, "event_type": "substitution",
            "minute": minute, "added_minute": 0, "player_out_id": out_id, "player_in_id": in_id,
            "player_in_position": position, "is_voided": False, **extra}


def fact(m, team, pid, kind, minute, **extra):
    return {"id": uuid4(), "match_id": m["id"], "team_id": team, "player_id": pid, "event_type": kind,
            "minute": minute, "added_minute": 0, "player_out_id": None, "player_in_id": None,
            "player_in_position": None, "is_voided": False, **extra}


def roster(*players, team=HOME):
    return [{"player_id": pid, "team_id": team, "first_name": "N", "last_name": str(pid)[:4]} for pid in players]


def stats(matches, events, formations, segs, rosters):
    rows = compute_player_stats(matches, events, formations, segs, rosters)
    return {row["player_id"]: row for row in rows}


def test_minutes_of_starters_and_substitutes_with_the_published_lineup():
    a, b, c = uuid4(), uuid4(), uuid4()
    m = match()
    by_player = stats([m], [sub(m, HOME, b, c, 60, "ST")], lineup(m, HOME, {a: "GK", b: "ST"}, substitutes=[c]),
                      segments(m), roster(a, b, c))

    assert {p: by_player[p]["minutes_played"] for p in (a, b, c)} == {a: 90, b: 60, c: 30}
    assert {p: by_player[p]["main_position"] for p in (a, b, c)} == {
        a: "goalkeeper", b: "forward", c: "forward",
    }
    assert all(row["penalties_saved"] == 0 for row in by_player.values())


@pytest.mark.parametrize("public", [False, None])
def test_without_a_published_lineup_nobody_adds_minutes_or_positions(public):
    a, b, c = uuid4(), uuid4(), uuid4()
    m = match()
    formations = [] if public is None else lineup(m, HOME, {a: "GK", b: "ST"}, public=False)
    events = [sub(m, HOME, b, c, 60, "ST"), fact(m, HOME, a, "penalty_saved", 20)]

    by_player = stats([m], events, formations, segments(m), roster(a, b, c))

    assert all(row["minutes_played"] == 0 and row["main_position"] is None for row in by_player.values())
    assert by_player[a]["penalties_saved"] == 1


def test_only_the_lineup_of_the_own_team_counts():
    a, rival = uuid4(), uuid4()
    m = match()
    formations = lineup(m, AWAY, {rival: "GK"})
    by_player = stats([m], [fact(m, HOME, a, "goal", 10)], formations, segments(m),
                      roster(a) + roster(rival, team=AWAY))

    assert by_player[a]["minutes_played"] == 0
    assert by_player[rival]["minutes_played"] == 90


@pytest.mark.parametrize(("exit_kind", "expected"), [("red_card", 40), ("substitution", 50)])
def test_a_substitute_counts_from_entry_to_exit_cl2(exit_kind, expected):
    a, b, c = uuid4(), uuid4(), uuid4()
    m = match()
    events = [sub(m, HOME, a, b, 30, "CM")]
    events.append(fact(m, HOME, b, "red_card", 70) if exit_kind == "red_card" else sub(m, HOME, b, c, 80))

    by_player = stats([m], events, lineup(m, HOME, {a: "CM"}, substitutes=[b, c]), segments(m), roster(a, b, c))

    assert by_player[b]["minutes_played"] == expected


def test_a_reentry_adds_a_new_stretch_on_the_field():
    a, b = uuid4(), uuid4()
    m = match()
    events = [sub(m, HOME, a, b, 30), sub(m, HOME, b, a, 60)]

    by_player = stats([m], events, lineup(m, HOME, {a: "CM"}, substitutes=[b]), segments(m), roster(a, b))

    assert by_player[a]["minutes_played"] == 60
    assert by_player[b]["minutes_played"] == 30


@pytest.mark.parametrize("exit_kind", ["red_card", "substitution"])
def test_an_exit_in_added_time_is_capped_at_the_effective_duration(exit_kind):
    a, b, c = uuid4(), uuid4(), uuid4()
    m = match()
    events = [sub(m, HOME, a, b, 60)]
    events.append(fact(m, HOME, b, "red_card", 90, added_minute=4) if exit_kind == "red_card"
                  else sub(m, HOME, b, c, 90, added_minute=4))

    by_player = stats([m], events, lineup(m, HOME, {a: "CM"}, substitutes=[b, c]), segments(m), roster(a, b, c))

    assert by_player[b]["minutes_played"] == 30
    assert by_player[a]["minutes_played"] == 60


def test_extra_time_uses_the_last_segment_and_the_first_segment_lineup():
    a, b = uuid4(), uuid4()
    m = match(resolution="extra_time")
    formations = lineup(m, HOME, {a: "LCB"}) + lineup(m, HOME, {a: "ST", b: "RW"}, segment=3)

    by_player = stats([m], [], formations, segments(m, 45, 90, 120), roster(a, b))

    assert by_player[a]["minutes_played"] == 120
    # b solo figura en una formación posterior: no es titular del primer segmento.
    assert by_player[b]["minutes_played"] == 0
    # a jugó en dos líneas en el mismo partido: cada una suma ese partido.
    assert by_player[a]["main_position"] in {"defender", "forward"}


@pytest.mark.parametrize("resolution", ["walkover", "administrative"])
def test_walkover_and_administrative_add_no_minutes_or_positions_cl4(resolution):
    a = uuid4()
    m = match(resolution=resolution)

    by_player = stats([m], [], lineup(m, HOME, {a: "GK"}), segments(m), roster(a))

    assert by_player[a]["minutes_played"] == 0 and by_player[a]["main_position"] is None


def test_unconfirmed_match_adds_nothing():
    a = uuid4()
    m = match(confirmed=False)

    rows = compute_player_stats([m], [fact(m, HOME, a, "penalty_saved", 10)], lineup(m, HOME, {a: "GK"}),
                                segments(m), roster(a))

    assert all(row["minutes_played"] == 0 and row["penalties_saved"] == 0 for row in rows)


def test_main_position_is_the_line_with_most_matches_da2():
    a = uuid4()
    games = [match(days=day) for day in (1, 2, 3)]
    formations = (lineup(games[0], HOME, {a: "GK"}) + lineup(games[1], HOME, {a: "GK"})
                  + lineup(games[2], HOME, {a: "CB"}))

    by_player = stats(games, [], formations, [s for g in games for s in segments(g)], roster(a))

    assert by_player[a]["main_position"] == "goalkeeper"
    assert by_player[a]["minutes_played"] == 270


@pytest.mark.parametrize(("forward_day", "defender_day", "expected"), [
    (1, 2, "defender"), (2, 1, "forward"), (None, 1, "defender"), (1, None, "forward"),
])
def test_a_tie_goes_to_the_line_of_the_most_recent_match_da2(forward_day, defender_day, expected):
    a = uuid4()
    first, second = match(days=forward_day), match(days=defender_day)
    formations = lineup(first, HOME, {a: "ST"}) + lineup(second, HOME, {a: "LCB"})

    by_player = stats([first, second], [], formations, segments(first) + segments(second), roster(a))

    assert by_player[a]["main_position"] == expected


def test_entry_without_position_counts_minutes_but_no_line_cl1_cl8():
    a, b = uuid4(), uuid4()
    m = match()

    by_player = stats([m], [sub(m, HOME, a, b, 70)], lineup(m, HOME, {a: "CM"}, substitutes=[b]),
                      segments(m), roster(a, b))

    assert by_player[b]["minutes_played"] == 20 and by_player[b]["main_position"] is None


def test_an_outfield_player_entering_as_goalkeeper_counts_as_goalkeeper_cl3():
    keeper, field = uuid4(), uuid4()
    m = match()

    by_player = stats([m], [sub(m, HOME, keeper, field, 50, "GK")],
                      lineup(m, HOME, {keeper: "GK"}, substitutes=[field]), segments(m), roster(keeper, field))

    assert by_player[field]["main_position"] == "goalkeeper"


def test_penalties_saved_skip_voided_facts_and_count_on_top_of_goals_cl5():
    keeper, shooter = uuid4(), uuid4()
    m = match()
    events = [
        fact(m, AWAY, keeper, "penalty_saved", 20),
        fact(m, HOME, shooter, "goal", 21),
        fact(m, AWAY, keeper, "penalty_saved", 60),
        fact(m, AWAY, keeper, "penalty_saved", 70, is_voided=True),
    ]

    by_player = stats([m], events, [], segments(m), roster(shooter) + roster(keeper, team=AWAY))

    assert by_player[keeper]["penalties_saved"] == 2
    assert by_player[shooter]["goals"] == 1 and by_player[shooter]["penalties_saved"] == 0


def test_a_player_in_two_teams_adds_both_cl7():
    a = uuid4()
    other = uuid4()
    first, second = match(days=1), match(days=2, home=other, away=AWAY)
    formations = lineup(first, HOME, {a: "GK"}) + lineup(second, other, {a: "GK"})
    events = [fact(first, HOME, a, "penalty_saved", 10), fact(second, other, a, "penalty_saved", 10)]

    by_player = stats([first, second], events, formations, segments(first) + segments(second),
                      roster(a) + roster(a, team=other))

    assert by_player[a]["minutes_played"] == 180 and by_player[a]["penalties_saved"] == 2


def test_the_new_figures_do_not_change_the_order_or_other_columns_rf005():
    a, b, c = uuid4(), uuid4(), uuid4()
    m = match()
    formations = lineup(m, HOME, {a: "GK", b: "ST"}, substitutes=[c])
    plain = [sub(m, HOME, b, c, 60), fact(m, HOME, b, "goal", 10), fact(m, HOME, a, "yellow_card", 30)]
    enriched = [dict(plain[0], player_in_position="ST"), *plain[1:], fact(m, HOME, a, "penalty_saved", 50)]

    def ranked(events):
        rows = assign_ranks(compute_player_stats([m], events, formations, segments(m), roster(a, b, c)),
                            player_stats_rank_key, "player_id")
        return [{k: v for k, v in row.items() if k not in {"main_position", "penalties_saved"}} for row in rows]

    assert ranked(plain) == ranked(enriched)


def test_every_row_has_the_three_figures():
    a = uuid4()
    m = match()

    rows = compute_player_stats([m], [fact(m, HOME, a, "goal", 10)], [], segments(m), roster(a))

    assert {(row["minutes_played"], row["main_position"], row["penalties_saved"]) for row in rows} == {(0, None, 0)}


def test_32_teams_and_300_matches_in_under_a_second_rnf003():
    teams = [uuid4() for _ in range(32)]
    players = {team: [uuid4() for _ in range(16)] for team in teams}
    slots = ("GK", "LB", "LCB", "RCB", "RB", "CM_L", "CM", "CM_R", "LW", "ST", "RW")
    matches, events, formations, segs, rosters = [], [], [], [], []
    for team in teams:
        rosters += roster(*players[team], team=team)
    for index in range(300):
        home, away = teams[index % 32], teams[(index * 7 + 1) % 32]
        m = match(days=index, home=home, away=away)
        matches.append(m)
        segs += segments(m, 45, 90)
        for team in (home, away):
            squad = players[team]
            formations += lineup(m, team, dict(zip(squad[:11], slots)), substitutes=squad[11:])
            events += [sub(m, team, squad[9], squad[11], 60, "ST"), fact(m, team, squad[3], "yellow_card", 30)]
        events.append(fact(m, away, players[away][0], "penalty_saved", 40))

    started = time.perf_counter()
    rows = compute_player_stats(matches, events, formations, segs, rosters)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, elapsed
    assert sum(row["penalties_saved"] for row in rows) == 300
