"""Qué partidos públicos tienen resultado compartible (spec 043, RF-004/RF-005)."""

from collections.abc import Mapping
from typing import Any

SHAREABLE_STATUSES = frozenset({"finished", "administrative_resolution"})


def is_shareable_result(match: Mapping[str, Any]) -> bool:
    if match.get("status") not in SHAREABLE_STATUSES:
        return False
    return all(
        match.get(field) is not None
        for field in ("home_team_id", "away_team_id", "home_score", "away_score")
    )
