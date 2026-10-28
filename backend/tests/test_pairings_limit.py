"""Límite de enfrentamientos manuales por formato de fase (RF-009, R26).

El máximo lo fija el formato de la fase, no la configuración de desempates:
uno por pareja por defecto y dos solo en liga o grupos generados a ida y
vuelta. Swiss se queda en uno y las eliminatorias quedan fuera de la regla.
"""

from __future__ import annotations

import pytest

from app.modules.tournaments.pairings import max_meetings_per_pair, pair_limit_detail


@pytest.mark.parametrize(
    ("stage_type", "schedule_legs", "expected"),
    [
        # League and groups: one leg means one meeting, two legs mean two.
        ("round_robin", 1, 1),
        ("round_robin", 2, 2),
        ("custom_group", 1, 1),
        ("custom_group", 2, 2),
        # Swiss never admits a second meeting by format, even if the column says 2.
        ("swiss", 1, 1),
        ("swiss", 2, 1),
        ("swiss", None, 1),
        # Elimination brackets are out of the rule: legitimate repeats.
        ("single_elimination", 1, None),
        ("single_elimination", 2, None),
        ("double_elimination", 1, None),
        ("double_elimination", 2, None),
        # Defensive defaults: unknown formats and unknown legs keep one meeting.
        ("mystery_format", 1, 1),
        ("mystery_format", 2, 1),
        ("round_robin", None, 1),
        ("round_robin", 0, 1),
        ("round_robin", 3, 1),
        ("custom_group", None, 1),
    ],
)
def test_max_meetings_per_pair_by_format(
    stage_type: str, schedule_legs: int | None, expected: int | None
):
    assert max_meetings_per_pair(stage_type, schedule_legs) == expected


def test_pair_limit_detail_singular_and_plural():
    assert pair_limit_detail(
        stage_name="Liga", home_team_name="A", away_team_name="B", max_meetings=1
    ) == "La fase «Liga» ya alcanzó el máximo de 1 enfrentamiento por pareja entre «A» y «B»"
    assert pair_limit_detail(
        stage_name="Liga", home_team_name="A", away_team_name="B", max_meetings=2
    ) == "La fase «Liga» ya alcanzó el máximo de 2 enfrentamientos por pareja entre «A» y «B»"
