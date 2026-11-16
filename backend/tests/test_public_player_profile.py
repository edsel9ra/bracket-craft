"""Funciones puras de la ficha pública del jugador (spec 038, T2)."""

from datetime import date, datetime, timezone

from app.modules.tournaments.public_player_profile import (
    PROFILE_TOURNAMENT_LIMIT,
    authorized_tournaments,
    build_player_profile,
    profile_available_ids,
    profile_photo_candidate,
    representative_inscriptions,
)

P1, P2 = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
T1, T2, T3 = (f"00000000-0000-4000-8000-0000000001{i}" for i in range(3))
TEAM_A, TEAM_B = "00000000-0000-4000-8000-0000000002aa", "00000000-0000-4000-8000-0000000002bb"


def row(tournament, *, player=P1, team=TEAM_A, active=True, consent=True, photo=None,
        start=date(2026, 1, 1), valid=datetime(2026, 1, 1, tzinfo=timezone.utc)):
    return {
        "tournament_id": tournament, "tournament_name": f"Copa {tournament[-2:]}",
        "start_date": start, "team_id": team, "team_name": f"Equipo {team[-2:]}",
        "player_id": player, "first_name": "Ana", "last_name": "Gol",
        "is_active": active, "valid_from": valid, "photo_consent": consent,
        "photo_object_key": photo if consent else None,
    }


def test_representative_prefers_active_inscription_cl11():
    retired = row(T1, active=False, consent=True, valid=datetime(2026, 6, 1, tzinfo=timezone.utc))
    active = row(T1, team=TEAM_B, active=True, consent=False)
    reps = representative_inscriptions([retired, active])
    assert reps[(T1, P1)] is active
    assert authorized_tournaments([retired, active]) == []


def test_representative_without_active_uses_latest_retired_cl11():
    old = row(T1, active=False, consent=False, valid=datetime(2026, 1, 1, tzinfo=timezone.utc))
    new = row(T1, team=TEAM_B, active=False, consent=True, valid=datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert representative_inscriptions([new, old])[(T1, P1)] is new
    assert authorized_tournaments([old, new]) == [new]


def test_representative_tie_is_deterministic():
    a = row(T1, team=TEAM_A, active=False)
    b = row(T1, team=TEAM_B, active=False)
    assert representative_inscriptions([a, b])[(T1, P1)] is representative_inscriptions([b, a])[(T1, P1)]


def test_authorized_only_with_consent_and_ordered_recent_first_cl1_rf010():
    rows = [
        row(T1, start=date(2025, 1, 1)),
        row(T2, start=date(2026, 5, 1), consent=False),
        row(T3, start=date(2026, 2, 1)),
    ]
    assert [r["tournament_id"] for r in authorized_tournaments(rows)] == [T3, T1]


def test_authorized_tie_on_start_date_is_stable():
    rows = [row(T2), row(T1)]
    assert [r["tournament_id"] for r in authorized_tournaments(rows)] == [T1, T2]


def test_authorized_is_capped_rnf001():
    rows = [
        row(f"00000000-0000-4000-8000-{i:012d}", start=date(2000, 1, 1).replace(year=2000 + i % 50, day=1 + i % 28))
        for i in range(60)
    ]
    result = authorized_tournaments(rows)
    assert PROFILE_TOURNAMENT_LIMIT == 50
    assert len(result) == 50
    assert authorized_tournaments(rows, limit=3) == result[:3]


def test_profile_available_ids_per_tournament_rf009():
    rows = [
        row(T1, player=P1, consent=True),
        row(T1, player=P2, consent=False),
        row(T1, player=P2, active=False, consent=True, valid=datetime(2027, 1, 1, tzinfo=timezone.utc)),
    ]
    assert profile_available_ids(rows) == {P1}


def test_photo_from_most_recent_active_authorized_with_photo_rf007_cl2_cl10():
    retired = row(T3, start=date(2027, 1, 1), active=False, photo="retired.jpg")
    no_photo = row(T2, start=date(2026, 6, 1), photo=None)
    with_photo = row(T1, start=date(2026, 1, 1), photo="photo.jpg")
    tournaments = authorized_tournaments([retired, no_photo, with_photo])
    assert profile_photo_candidate(tournaments) is with_photo
    assert profile_photo_candidate([retired, no_photo]) is None
    assert profile_photo_candidate([]) is None


def test_build_profile_rows_and_totals_cl7_cl9():
    t_recent = row(T2, team=TEAM_B, start=date(2026, 6, 1))
    t_old = row(T1, team=TEAM_A, start=date(2025, 6, 1))
    stats = {
        T2: {"matches_played": 3, "goals": 2, "yellow_cards": 1, "red_cards": 0, "clean_sheets": 1,
             "rank": 1, "photo_url": "x", "dorsal_number": 9},
    }
    profile = build_player_profile([t_recent, t_old], stats)
    assert profile["first_name"] == "Ana" and profile["last_name"] == "Gol"
    assert [t["tournament_id"] for t in profile["tournaments"]] == [T2, T1]
    recent, old = profile["tournaments"]
    assert recent == {
        "tournament_id": T2, "tournament_name": "Copa 11", "team_id": TEAM_B, "team_name": "Equipo bb",
        "matches_played": 3, "goals": 2, "yellow_cards": 1, "red_cards": 0, "clean_sheets": 1,
    }
    assert old["team_id"] == TEAM_A
    assert all(old[k] == 0 for k in ("matches_played", "goals", "yellow_cards", "red_cards", "clean_sheets"))
    assert profile["totals"] == {
        "matches_played": 3, "goals": 2, "yellow_cards": 1, "red_cards": 0, "clean_sheets": 1,
    }
