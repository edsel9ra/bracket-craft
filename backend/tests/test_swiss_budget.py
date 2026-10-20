"""Swiss pairing budget, strict fallback and dedicated runner (RF-005, RF-006, RF-010).

The budget is a single deterministic counter shared by the backtracking search,
every bye candidate and the greedy fallback. The fallback never relaxes the
"do not repeat rivals" rule: it either finds a full pairing or the calculation
fails with a classified ``SwissPairingFailure``. The runner executes the pure
calculation in a dedicated two-thread executor with a safety timeout, so the
event loop keeps serving other requests.
"""

from __future__ import annotations

import asyncio
import threading
from random import Random
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.tournaments import scheduling as scheduling_module
from app.modules.tournaments.scheduling import (
    MAX_SWISS_TEAMS,
    PairingBudget,
    SWISS_FALLBACK_RESERVE,
    SWISS_PAIRING_LIMIT,
    SWISS_PAIRING_MAX_WORKERS,
    SWISS_PAIRING_TIMEOUT_SECONDS,
    SWISS_SEARCH_LIMIT,
    SwissPairing,
    SwissPairingFailure,
    SwissPairingTimeout,
    build_swiss_pairings,
    run_swiss_pairing,
)
from app.modules.tournaments.schemas import GenerateSingleEliminationRequest

# Frozen before the T004 refactor: the output inside the budget must not change.
EXPECTED_36_TEAMS = [
    [[14, 36], [21, 10], [27, 20], [9, 1], [25, 33], [28, 17], [32, 31], [4, 35], [24, 26], [12, 29], [15, 6], [34, 5], [30, 22], [7, 16], [13, 3], [8, 11], [2, 19], [23, 18]],
    [[30, 21], [22, 3], [4, 32], [36, 12], [29, 20], [8, 24], [31, 25], [14, 13], [19, 23], [33, 27], [18, 28], [11, 9], [10, 7], [35, 15], [6, 5], [26, 2], [17, 1], [16, 34]],
    [[7, 26], [22, 6], [16, 10], [1, 25], [9, 3], [33, 35], [12, 28], [19, 14], [2, 24], [5, 4], [17, 15], [21, 31], [29, 23], [20, 34], [13, 8], [27, 18], [32, 30], [36, 11]],
    [[5, 26], [32, 2], [14, 4], [13, 30], [20, 15], [10, 1], [12, 21], [36, 3], [6, 31], [11, 29], [35, 27], [28, 22], [23, 9], [19, 8], [18, 17], [24, 34], [25, 7], [16, 33]],
    [[27, 17], [7, 12], [26, 22], [24, 29], [30, 18], [33, 14], [19, 13], [8, 35], [15, 16], [25, 10], [1, 36], [5, 2], [3, 21], [23, 28], [11, 32], [20, 6], [4, 9], [34, 31]],
    [[5, 25], [29, 17], [35, 30], [4, 20], [11, 24], [9, 32], [28, 14], [3, 7], [15, 18], [34, 36], [31, 16], [6, 13], [22, 8], [10, 26], [1, 12], [21, 27], [33, 19], [2, 23]],
    [[9, 22], [7, 35], [34, 11], [12, 4], [26, 15], [25, 2], [29, 36], [16, 24], [27, 1], [6, 32], [20, 13], [10, 8], [30, 5], [17, 33], [31, 19], [3, 28], [14, 23], [18, 21]],
    [[17, 25], [36, 5], [15, 29], [22, 16], [3, 6], [35, 19], [13, 27], [8, 12], [1, 11], [23, 10], [18, 34], [21, 9], [31, 30], [26, 4], [32, 14], [28, 33], [2, 20], [24, 7]],
]
EXPECTED_ODD_FIELD = [[2, 1, None], [4, 3, None], [None, None, 5]]


def team_ids(count: int) -> list[UUID]:
    return [UUID(int=index) for index in range(1, count + 1)]


def signature(pairings) -> list[tuple[int | None, int | None, int | None]]:
    return [
        (
            pairing.home_team_id.int if pairing.home_team_id else None,
            pairing.away_team_id.int if pairing.away_team_id else None,
            pairing.bye_team_id.int if pairing.bye_team_id else None,
        )
        for pairing in pairings
    ]


def swiss(team_ids_value, budget=None, **overrides):
    arguments = {
        "standings": [],
        "prior_pairs": set(),
        "seed": 5,
        "round_number": 1,
    }
    arguments.update(overrides)
    return build_swiss_pairings(team_ids_value, budget=budget, **arguments)


def test_production_limits_are_the_approved_constants():
    assert MAX_SWISS_TEAMS == 64
    assert SWISS_SEARCH_LIMIT == 40_000
    assert SWISS_PAIRING_LIMIT == 50_000
    assert SWISS_FALLBACK_RESERVE == 10_000
    assert SWISS_PAIRING_TIMEOUT_SECONDS == 10.0
    assert SWISS_PAIRING_MAX_WORKERS == 2

    budget = PairingBudget()
    assert budget.search_limit == SWISS_SEARCH_LIMIT
    assert budget.total_limit == SWISS_PAIRING_LIMIT
    assert budget.evaluations == 0


def test_pairing_budget_take_boundary_semantics():
    budget = PairingBudget(search_limit=3, total_limit=5)

    assert [budget.take(budget.search_limit) for _ in range(3)] == [True, True, True]
    assert budget.evaluations == 3
    # The evaluation that reaches the limit is performed; the next one is not.
    assert budget.take(budget.search_limit) is False
    assert budget.evaluations == 3
    # A larger limit accepts the next evaluation: no hidden reset.
    assert budget.take(budget.total_limit) is True
    assert budget.evaluations == 4
    assert budget.take(budget.total_limit) is True
    assert budget.evaluations == 5
    assert budget.take(budget.total_limit) is False
    assert budget.evaluations == 5


def test_same_input_produces_the_same_pairings_and_evaluations():
    ids = team_ids(12)
    first_budget = PairingBudget()
    second_budget = PairingBudget()

    first = swiss(ids, first_budget, seed=17, round_number=2)
    second = swiss(ids, second_budget, seed=17, round_number=2)

    assert signature(first) == signature(second)
    assert first_budget.evaluations == second_budget.evaluations
    assert first_budget.evaluations > 0


def test_search_boundary_keeps_the_result_and_shares_the_counter_with_the_fallback():
    ids = team_ids(8)
    base_budget = PairingBudget()
    baseline = swiss(ids, base_budget)
    needed = base_budget.evaluations
    assert needed > 1

    exact_budget = PairingBudget(
        search_limit=needed, total_limit=SWISS_PAIRING_LIMIT
    )
    exact = swiss(ids, exact_budget)
    assert signature(exact) == signature(baseline)
    assert exact_budget.evaluations == needed

    cut_budget = PairingBudget(
        search_limit=needed - 1, total_limit=SWISS_PAIRING_LIMIT
    )
    from_fallback = swiss(ids, cut_budget)
    assert signature(from_fallback) == signature(baseline)
    assert cut_budget.evaluations >= needed


def test_fallback_failure_after_the_search_limit_is_budget_exhaustion():
    # H1: the fallback only runs after the search used its whole share, so a
    # fallback failure is budget exhaustion even when it stops before 50 000.
    ids = team_ids(8)
    prior_pairs = {frozenset((ids[0], ids[1]))}
    budget = PairingBudget(search_limit=1, total_limit=100)

    with pytest.raises(SwissPairingFailure) as failure:
        swiss(ids, budget, seed=2, prior_pairs=prior_pairs)

    assert failure.value.reason == "budget_exhausted"
    assert failure.value.evaluations < 100
    assert budget.evaluations == failure.value.evaluations


@pytest.mark.parametrize(
    ("search_limit", "start", "expected"),
    [
        (39_999, 39_998, 39_999),  # the evaluation that reaches the limit runs
        (39_999, 39_999, 40_000),  # rejected at the limit; the fallback runs one
        (40_000, 39_999, 40_000),
        (40_001, 40_000, 40_001),
    ],
)
def test_search_limit_boundaries_count_the_exact_evaluation(
    search_limit, start, expected
):
    ids = team_ids(2)
    budget = PairingBudget(
        search_limit=search_limit,
        total_limit=SWISS_PAIRING_LIMIT,
        evaluations=start,
    )

    result = swiss(ids, budget)

    assert len(result) == 1
    assert budget.evaluations == expected


@pytest.mark.parametrize(
    ("total_limit", "start", "succeeds", "expected"),
    [
        (49_999, 49_998, True, 49_999),  # the evaluation that reaches the limit runs
        (49_999, 49_999, False, 49_999),  # rejected at the limit; nothing left
        (50_000, 49_999, True, 50_000),
        (50_001, 50_000, True, 50_001),
    ],
)
def test_total_limit_boundaries_count_the_exact_evaluation(
    total_limit, start, succeeds, expected
):
    ids = team_ids(2)
    budget = PairingBudget(
        search_limit=0,
        total_limit=total_limit,
        evaluations=start,
    )

    if succeeds:
        result = swiss(ids, budget)
        assert len(result) == 1
    else:
        with pytest.raises(SwissPairingFailure) as failure:
            swiss(ids, budget)
        assert failure.value.reason == "budget_exhausted"
        assert failure.value.evaluations == expected
    assert budget.evaluations == expected


def test_fallback_uses_the_same_candidate_order_as_the_search():
    ids = team_ids(6)
    standings = [
        {"team_id": ids[0], "points": 10, "won": 5, "rank": 1},
        {"team_id": ids[1], "points": 9, "won": 4, "rank": 2},
        {"team_id": ids[2], "points": 8, "won": 3, "rank": 3},
        {"team_id": ids[3], "points": 10, "won": 5, "rank": 4},
        {"team_id": ids[4], "points": 10, "won": 5, "rank": 5},
        {"team_id": ids[5], "points": 6, "won": 1, "rank": 6},
    ]
    seed = 3
    rng = Random(seed)
    random_order = {team_id: rng.random() for team_id in ids}
    expected_partner = min(ids[3], ids[4], key=lambda team_id: random_order[team_id])
    budget = PairingBudget(search_limit=0, total_limit=SWISS_PAIRING_LIMIT)

    pairings = swiss(ids, budget, seed=seed, standings=standings)

    first = next(
        pairing
        for pairing in pairings
        if ids[0] in (pairing.home_team_id, pairing.away_team_id)
    )
    assert frozenset((first.home_team_id, first.away_team_id)) == frozenset(
        (ids[0], expected_partner)
    )


def test_total_limit_exhaustion_reports_budget_exhausted():
    ids = team_ids(8)
    base_budget = PairingBudget()
    swiss(ids, base_budget)
    needed = base_budget.evaluations

    budget = PairingBudget(search_limit=needed - 1, total_limit=needed - 1)
    with pytest.raises(SwissPairingFailure) as failure:
        swiss(ids, budget)

    assert failure.value.reason == "budget_exhausted"
    assert failure.value.evaluations == needed - 1
    assert budget.evaluations == needed - 1


def test_complete_search_without_solution_reports_no_valid_pairing():
    ids = team_ids(4)
    every_pair = {
        frozenset((first, second))
        for index, first in enumerate(ids)
        for second in ids[index + 1:]
    }
    budget = PairingBudget()

    with pytest.raises(SwissPairingFailure) as failure:
        swiss(ids, budget, prior_pairs=every_pair)

    assert failure.value.reason == "no_valid_pairing"
    # First team's three candidates were examined and the search was conclusive.
    assert failure.value.evaluations == 3
    assert budget.evaluations == 3


def test_fallback_never_repeats_rivals():
    ids = team_ids(8)
    prior_pairs = {frozenset((ids[0], ids[1]))}
    budget = PairingBudget(search_limit=1, total_limit=SWISS_PAIRING_LIMIT)

    pairings = swiss(ids, budget, seed=1, prior_pairs=prior_pairs)

    generated = [
        frozenset((pairing.home_team_id, pairing.away_team_id))
        for pairing in pairings
        if pairing.home_team_id is not None
    ]
    assert len(generated) == 4
    assert len(set(generated)) == 4
    assert set(generated).isdisjoint(prior_pairs)
    assert budget.evaluations >= 2


def test_exhaustion_with_an_existing_solution_is_found_by_the_fallback():
    ids = team_ids(8)
    base_budget = PairingBudget()
    expected = swiss(ids, base_budget)

    budget = PairingBudget(
        search_limit=max(base_budget.evaluations - 1, 1),
        total_limit=SWISS_PAIRING_LIMIT,
    )

    result = swiss(ids, budget)

    assert signature(result) == signature(expected)
    assert budget.evaluations <= SWISS_PAIRING_LIMIT


def test_validation_errors_are_unchanged():
    with pytest.raises(ValueError, match="al menos"):
        swiss(team_ids(1))
    with pytest.raises(ValueError, match="repetidos"):
        repeated = team_ids(2)
        swiss([repeated[0], repeated[0]])
    with pytest.raises(ValueError, match="semilla"):
        swiss(team_ids(4), seed=-1)
    with pytest.raises(ValueError, match="positiva"):
        swiss(team_ids(4), round_number=0)


def test_invalid_home_and_away_targets_stay_validated_by_the_schema():
    payload = {
        "version_id": UUID(int=900),
        "stage_id": UUID(int=901),
        "start_date": "2026-09-18T18:00:00+00:00",
        "swiss_home_target": -1,
        "swiss_away_target": 4,
    }

    with pytest.raises(ValidationError):
        GenerateSingleEliminationRequest(**payload)


def test_36_team_format_is_identical_to_the_previous_implementation():
    ids = team_ids(36)
    prior_pairs = set()
    home_counts = {}
    away_counts = {}
    rounds = []

    for round_number in range(1, 9):
        pairings = swiss(
            ids,
            prior_pairs=prior_pairs,
            seed=round_number,
            round_number=round_number,
            home_counts=home_counts,
            away_counts=away_counts,
            home_target=4,
            away_target=4,
        )
        rounds.append([[home, away] for home, away, _ in signature(pairings)])
        for pairing in pairings:
            prior_pairs.add(frozenset((pairing.home_team_id, pairing.away_team_id)))
            home_counts[pairing.home_team_id] = (
                home_counts.get(pairing.home_team_id, 0) + 1
            )
            away_counts[pairing.away_team_id] = away_counts.get(pairing.away_team_id, 0) + 1

    assert rounds == EXPECTED_36_TEAMS
    assert set(home_counts.values()) == {4}
    assert set(away_counts.values()) == {4}


def test_odd_field_bye_is_identical_to_the_previous_implementation():
    ids = team_ids(5)
    standings = [
        {"team_id": team_id, "points": 10 - index, "won": 3 - index % 2, "rank": index + 1}
        for index, team_id in enumerate(ids)
    ]

    pairings = build_swiss_pairings(
        ids,
        standings=standings,
        prior_pairs=set(),
        seed=4,
        round_number=1,
        bye_counts={},
    )

    assert [list(item) for item in signature(pairings)] == EXPECTED_ODD_FIELD


def test_runner_uses_a_dedicated_two_thread_executor():
    executor = scheduling_module._get_swiss_executor()

    assert executor is scheduling_module._get_swiss_executor()
    assert executor._max_workers == SWISS_PAIRING_MAX_WORKERS == 2
    assert executor._thread_name_prefix == "swiss-pairing"


async def test_event_loop_progresses_while_a_slow_pairing_runs(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_pairing(*args, **kwargs):
        started.set()
        try:
            release.wait(5)
            return ()
        finally:
            finished.set()

    monkeypatch.setattr(scheduling_module, "build_swiss_pairings", slow_pairing)
    progressed = asyncio.Event()

    async def other_request():
        await asyncio.sleep(0)
        progressed.set()

    task = asyncio.create_task(
        run_swiss_pairing(
            team_ids(4),
            standings=[],
            prior_pairs=set(),
            seed=1,
            round_number=1,
            timeout=5,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 5)
        await other_request()
        assert progressed.is_set()
        assert not task.done()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)

    assert await task == ()


async def test_runner_times_out_and_discards_the_result(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def stuck_pairing(*args, **kwargs):
        started.set()
        try:
            release.wait(10)
            return (SwissPairing(UUID(int=1), UUID(int=2)),)
        finally:
            finished.set()

    monkeypatch.setattr(scheduling_module, "build_swiss_pairings", stuck_pairing)
    try:
        with pytest.raises(SwissPairingTimeout):
            await run_swiss_pairing(
                team_ids(4),
                standings=[],
                prior_pairs=set(),
                seed=1,
                round_number=1,
                timeout=0.05,
            )
        assert started.is_set()
    finally:
        # A Python thread cannot be cancelled: it finishes on its own and its
        # result is discarded instead of being returned to the request.
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)


async def test_runner_keeps_validation_errors_unchanged():
    with pytest.raises(ValueError, match="al menos"):
        await run_swiss_pairing(
            [],
            standings=[],
            prior_pairs=set(),
            seed=1,
            round_number=1,
        )
