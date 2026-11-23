"""Integrity of a generated schedule before it is written (spec 042, RF-006).

Pure functions: no clock and no I/O. A generated schedule must not repeat a
match code and, outside elimination brackets, must not exceed the maximum
meetings per pair of the stage format, adding the meetings of previous Swiss
rounds. Pairs are unordered and counted per group; slots without both teams
never count as a pair.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

GENERATED_CODE_CONFLICT = "El calendario generado repite el código de partido {code}"
GENERATED_PAIR_CONFLICT = (
    "El calendario generado supera el máximo de enfrentamientos entre dos equipos de la fase"
)


@dataclass(frozen=True)
class PlannedMatch:
    code: str
    home_team_id: UUID | None
    away_team_id: UUID | None
    group_id: UUID | None = None


class ScheduleIntegrityError(ValueError):
    def __init__(
        self,
        kind: Literal["code", "pair"],
        *,
        code: str | None = None,
        pair: frozenset[UUID] | None = None,
    ):
        self.kind = kind
        self.code = code
        self.pair = pair
        self.detail = (
            GENERATED_CODE_CONFLICT.format(code=code) if kind == "code" else GENERATED_PAIR_CONFLICT
        )
        super().__init__(self.detail)


PriorPair = tuple[UUID | None, UUID | None, UUID | None]


def check_generated_schedule(
    planned: Iterable[PlannedMatch],
    *,
    max_meetings: int | None,
    prior_pairs: Iterable[PriorPair] = (),
) -> None:
    """Raise ``ScheduleIntegrityError`` when the schedule cannot be written.

    ``prior_pairs`` holds ``(group_id, home_team_id, away_team_id)`` of the
    matches already in the stage that count for the limit. ``max_meetings``
    ``None`` leaves the pair rule out (elimination brackets).
    """

    planned = list(planned)
    codes: set[str] = set()
    for match in planned:
        if match.code in codes:
            raise ScheduleIntegrityError("code", code=match.code)
        codes.add(match.code)

    if max_meetings is None:
        return

    meetings: Counter[tuple[UUID | None, frozenset[UUID]]] = Counter()
    sides = [*prior_pairs, *((m.group_id, m.home_team_id, m.away_team_id) for m in planned)]
    for group_id, home_team_id, away_team_id in sides:
        if home_team_id is None or away_team_id is None:
            continue
        key = (group_id, frozenset((home_team_id, away_team_id)))
        meetings[key] += 1
        if meetings[key] > max_meetings:
            raise ScheduleIntegrityError("pair", pair=key[1])
