"""Política de resultados compartibles (spec 043, T1)."""

import pytest

from app.modules.tournaments.share_policy import is_shareable_result

HOME, AWAY = "00000000-0000-4000-8000-0000000000aa", "00000000-0000-4000-8000-0000000000bb"


def match(**overrides):
    base = {"status": "finished", "home_team_id": HOME, "away_team_id": AWAY,
            "home_score": 2, "away_score": 1}
    return base | overrides


@pytest.mark.parametrize("status", ["finished", "administrative_resolution"])
def test_final_results_are_shareable(status):
    assert is_shareable_result(match(status=status)) is True


@pytest.mark.parametrize("status", ["scheduled", "live", "suspended", "cancelled", None])
def test_other_statuses_are_not_shareable(status):
    assert is_shareable_result(match(status=status)) is False


@pytest.mark.parametrize("field", ["home_team_id", "away_team_id", "home_score", "away_score"])
def test_missing_team_or_score_is_not_shareable(field):
    assert is_shareable_result(match(**{field: None})) is False


def test_missing_keys_are_not_shareable():
    assert is_shareable_result({"status": "finished"}) is False
