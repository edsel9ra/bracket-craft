"""Funciones puras de la spec 040 (T2): orígenes, plantilla, resolución y huella."""

from uuid import UUID

import pytest

from app.modules.stage_advancement.origins import (
    BEST_OF_POSITION,
    GROUP_POSITION,
    SlotOrigin,
    SourceGroup,
    SourceStage,
    SourceState,
    TemplateError,
    classic_template,
    first_round_pairs,
    resolve_slots,
    seed_order,
    stage_finished,
    standings_fingerprint,
    validate_origins,
)
from app.modules.standings.ranking import rank_buckets

STAGE = UUID("40000000-0000-4000-8000-000000000001")
OTHER_STAGE = UUID("40000000-0000-4000-8000-000000000002")
PIPELINE = [
    {"step": 1, "criterion": "points", "params": {}},
    {"step": 2, "criterion": "head_to_head", "params": {"total_rounds_expected": 1}},
    {"step": 3, "criterion": "goal_difference", "params": {}},
    {"step": 4, "criterion": "goals_for", "params": {}},
]
DRAW_PIPELINE = [*PIPELINE, {"step": 5, "criterion": "random_draw", "params": {}}]


def gid(index: int) -> UUID:
    return UUID(f"41000000-0000-4000-8000-{index:012d}")


def tid(group: int, position: int) -> UUID:
    return UUID(f"42000000-0000-4000-8000-{group:06d}{position:06d}")


def groups_of(*sizes: int) -> tuple[SourceGroup, ...]:
    return tuple(SourceGroup(id=gid(i), name=chr(65 + i), size=size) for i, size in enumerate(sizes))


def stage_of(*sizes: int, stage_id: UUID = STAGE) -> SourceStage:
    return SourceStage(id=stage_id, groups=groups_of(*sizes))


def gp(group: int | None, position: int, stage_id: UUID = STAGE) -> SlotOrigin:
    return SlotOrigin(
        kind=GROUP_POSITION,
        source_stage_id=stage_id,
        group_id=None if group is None else gid(group),
        position=position,
    )


def best(position: int, ordinal: int, stage_id: UUID = STAGE) -> SlotOrigin:
    return SlotOrigin(kind=BEST_OF_POSITION, source_stage_id=stage_id, position=position, ordinal=ordinal)


def row(group: int, position: int, points: int, gd: int = 0, gf: int = 0) -> dict:
    return {
        "team_id": tid(group, position),
        "group_id": gid(group),
        "points": points,
        "goal_difference": gd,
        "goals_for": gf,
        "goals_against": 0,
        "fair_play_points": 0,
    }


def state_of(table: dict[int, list[dict]], *, sizes=None, matches=None, statuses=None, pipeline=PIPELINE):
    sizes = sizes or tuple(len(rows) for rows in table.values())
    buckets = {
        gid(group): rank_buckets(rows, pipeline, points_system={"win": 3, "draw": 1, "loss": 0}, tie_seed="t")[0]
        for group, rows in table.items()
    }
    teams = {item["team_id"] for rows in table.values() for item in rows}
    return SourceState(
        stage=stage_of(*sizes),
        buckets=buckets,
        team_statuses={team: "registered" for team in teams} | (statuses or {}),
        matches=matches if matches is not None else (("m1", "finished", True),),
        pipeline=pipeline,
        tie_seed="t",
    )


def four_groups_table() -> dict[int, list[dict]]:
    return {
        group: [row(group, 1, 9, 5), row(group, 2, 6, 2), row(group, 3, 3, group), row(group, 4, 0)]
        for group in range(4)
    }


# --- bracket shape ------------------------------------------------------------

@pytest.mark.parametrize(
    ("slots", "expected"),
    [
        (2, [1, 2]),
        (4, [1, 4, 2, 3]),
        (8, [1, 8, 4, 5, 2, 7, 3, 6]),
        (6, [1, None, 4, 5, 2, None, 3, 6]),
        (3, [1, None, 2, 3]),
    ],
)
def test_seed_order_gives_byes_to_top_seeds(slots, expected):
    assert seed_order(slots) == expected


def test_first_round_pairs_skip_byes():
    assert first_round_pairs(6) == [(4, 5), (3, 6)]
    assert len(first_round_pairs(64)) == 32
    for invalid in (1, 65):
        with pytest.raises(ValueError):
            seed_order(invalid)


# --- validation ---------------------------------------------------------------

def codes(errors):
    return [(error.seed, error.code) for error in errors]


def test_valid_declaration_has_no_errors():
    origins = [gp(0, 1), gp(1, 1), gp(0, 2), gp(1, 2)]
    assert validate_origins(origins, {STAGE: stage_of(4, 4)}) == []


def test_single_table_stage_counts_as_one_group():
    stage = SourceStage(id=STAGE, groups=(SourceGroup(id=None, name=None, size=6),))
    assert validate_origins([gp(None, 1), gp(None, 2)], {STAGE: stage}) == []
    assert codes(validate_origins([gp(0, 1), gp(None, 2)], {STAGE: stage})) == [(1, "group_not_found")]


@pytest.mark.parametrize(
    ("origin", "code"),
    [
        (gp(0, 1, stage_id=OTHER_STAGE), "invalid_source_stage"),
        (gp(None, 1), "group_required"),
        (gp(7, 1), "group_not_found"),
        (gp(0, 5), "position_out_of_range"),
        (best(5, 1), "position_out_of_range"),
        (best(3, 3), "ordinal_out_of_range"),
    ],
)
def test_invalid_origin_identifies_the_slot(origin, code):
    origins = [gp(0, 1), origin]
    assert codes(validate_origins(origins, {STAGE: stage_of(4, 4)})) == [(2, code)]


def test_duplicate_and_overlapping_origins_are_rejected():
    stages = {STAGE: stage_of(4, 4)}
    assert codes(validate_origins([gp(0, 1), gp(0, 1)], stages)) == [(2, "duplicate_origin")]
    assert codes(validate_origins([best(3, 1), best(3, 1)], stages)) == [(2, "duplicate_origin")]
    assert codes(validate_origins([gp(0, 3), best(3, 1)], stages)) == [(2, "overlapping_origin")]


def test_best_of_requires_equal_groups_but_group_position_does_not():
    stages = {STAGE: stage_of(3, 4)}
    assert validate_origins([gp(0, 1), gp(1, 4)], stages) == []
    assert codes(validate_origins([gp(0, 1), best(2, 1)], stages)) == [(2, "unequal_groups")]
    assert codes(validate_origins([gp(0, 4), gp(1, 1)], stages)) == [(1, "position_out_of_range")]


def test_slot_count_bounds():
    stages = {STAGE: stage_of(4)}
    assert codes(validate_origins([gp(0, 1)], stages)) == [(None, "invalid_slots_count")]


def test_reference_round_trip():
    for origin in (gp(0, 1), gp(None, 2), best(3, 2)):
        assert SlotOrigin.from_reference(origin.to_reference()) == origin
    assert "group_id" not in best(3, 2).to_reference()
    assert "ordinal" not in gp(0, 1).to_reference()
    with pytest.raises(ValueError):
        SlotOrigin.from_reference({"kind": "winner", "source_stage_id": str(STAGE), "position": 1})


# --- classic template ---------------------------------------------------------

def opponents(origins):
    return [(origins[a - 1], origins[b - 1]) for a, b in first_round_pairs(len(origins))]


def test_template_two_groups_crosses_first_with_second():
    origins = classic_template(stage_of(4, 4), 4)
    assert opponents(origins) == [(gp(0, 1), gp(1, 2)), (gp(1, 1), gp(0, 2))]


def test_template_four_groups_classic_pairs():
    origins = classic_template(stage_of(4, 4, 4, 4), 8)
    assert opponents(origins) == [
        (gp(0, 1), gp(1, 2)), (gp(3, 1), gp(2, 2)), (gp(1, 1), gp(0, 2)), (gp(2, 1), gp(3, 2))
    ]
    assert validate_origins(origins, {STAGE: stage_of(4, 4, 4, 4)}) == []


@pytest.mark.parametrize(("sizes", "slots"), [((4, 4, 4), 4), ((4, 4, 4, 4, 4, 4), 16), ((4, 4, 4), 8), ((4, 4, 4, 4), 12)])
def test_template_completes_with_best_of_and_avoids_same_group(sizes, slots):
    origins = classic_template(stage_of(*sizes), slots)
    assert len(origins) == slots
    assert validate_origins(origins, {STAGE: stage_of(*sizes)}) == []
    for home, away in opponents(origins):
        assert home.group_id is None or home.group_id != away.group_id
    firsts = [origin for origin in origins if origin.position == 1]
    assert origins[: len(firsts)] == firsts


def test_template_byes_go_to_best_ranked():
    origins = classic_template(stage_of(4, 4, 4), 6)
    order = seed_order(6)
    bye_seeds = {order[i] for i in range(0, len(order), 2) if order[i + 1] is None}
    assert {origins[seed - 1].position for seed in bye_seeds} == {1}


def test_template_with_unequal_groups_only_when_no_best_of_needed():
    assert len(classic_template(stage_of(3, 4), 6)) == 6
    assert len(classic_template(stage_of(3, 4), 7)) == 7
    with pytest.raises(TemplateError) as error:
        classic_template(stage_of(3, 4, 4), 4)
    assert error.value.code == "unequal_groups"
    with pytest.raises(TemplateError) as error:
        classic_template(stage_of(2, 2), 6)
    assert error.value.code == "not_enough_teams"


def test_template_single_table():
    stage = SourceStage(id=STAGE, groups=(SourceGroup(id=None, name=None, size=8),))
    origins = classic_template(stage, 4)
    assert sorted(origin.position for origin in origins) == [1, 2, 3, 4]
    assert opponents(origins) == [(gp(None, 1), gp(None, 4)), (gp(None, 2), gp(None, 3))]


# --- resolution ---------------------------------------------------------------

def test_resolve_firsts_seconds_and_best_thirds():
    table = four_groups_table()
    origins = [gp(0, 1), gp(1, 1), best(3, 1), best(3, 2)]
    resolved = resolve_slots(origins, {STAGE: state_of(table)})
    assert [item.team_id for item in resolved] == [tid(0, 1), tid(1, 1), tid(3, 3), tid(2, 3)]
    assert all(item.reason is None for item in resolved)


def test_best_of_ignores_head_to_head_and_uses_next_criteria():
    table = four_groups_table()
    for group in range(4):
        table[group][2] = row(group, 3, 4, gd=1, gf=group)
    resolved = resolve_slots([best(3, 1), best(3, 2)], {STAGE: state_of(table)})
    assert [item.team_id for item in resolved] == [tid(3, 3), tid(2, 3)]


def test_unresolved_tie_blocks_only_affected_slots():
    table = four_groups_table()
    table[0][0] = row(0, 1, 6, 2)
    resolved = resolve_slots([gp(0, 1), gp(1, 1), gp(0, 3)], {STAGE: state_of(table)})
    assert [item.reason for item in resolved] == ["unresolved_tie", None, None]
    assert resolved[0].team_id is None


def test_best_of_tie_across_groups_blocks_and_random_draw_breaks_it():
    table = four_groups_table()
    for group in range(4):
        table[group][2] = row(group, 3, 4, gd=1, gf=1)
    origins = [best(3, 1), best(3, 2)]
    assert {item.reason for item in resolve_slots(origins, {STAGE: state_of(table)})} == {"unresolved_tie"}
    drawn = resolve_slots(origins, {STAGE: state_of(table, pipeline=DRAW_PIPELINE)})
    assert all(item.reason is None for item in drawn)
    assert len({item.team_id for item in drawn}) == 2
    assert drawn == resolve_slots(origins, {STAGE: state_of(table, pipeline=DRAW_PIPELINE)})


def test_tie_inside_group_blocks_best_of_from_that_position():
    table = four_groups_table()
    table[1][2] = row(1, 3, 0)
    resolved = resolve_slots([best(3, 1)], {STAGE: state_of(table)})
    assert resolved[0].reason == "unresolved_tie"


@pytest.mark.parametrize(
    ("matches", "finished"),
    [
        ((("a", "finished", True), ("b", "administrative_resolution", True)), True),
        ((("a", "finished", True), ("b", "cancelled", False)), False),
        ((("a", "finished", True), ("b", "scheduled", False)), False),
        ((("a", "live", False),), False),
        ((("a", "suspended", False),), False),
        ((("a", "finished", False),), False),
        ((), False),
    ],
)
def test_stage_finished(matches, finished):
    assert stage_finished(matches) is finished


def test_unfinished_stage_blocks_every_slot_from_it():
    state = state_of(four_groups_table(), matches=(("a", "finished", True), ("b", "scheduled", False)))
    resolved = resolve_slots([gp(0, 1), best(3, 1)], {STAGE: state})
    assert [item.reason for item in resolved] == ["source_stage_unfinished"] * 2
    assert all(item.team_id is None for item in resolved)


def test_ineligible_team_blocks_its_slot():
    state = state_of(four_groups_table(), statuses={tid(0, 1): "disqualified"})
    resolved = resolve_slots([gp(0, 1), gp(1, 1)], {STAGE: state})
    assert [item.reason for item in resolved] == ["team_ineligible", None]
    assert resolved[0].team_id == tid(0, 1)


def test_group_size_changed_after_declaring():
    table = four_groups_table()
    table[3] = table[3][:3]
    state = state_of(table)
    resolved = resolve_slots([best(3, 1), gp(3, 4), gp(0, 1)], {STAGE: state})
    assert [item.reason for item in resolved] == ["unequal_groups", "position_missing", None]


# --- fingerprint --------------------------------------------------------------

def test_fingerprint_is_stable_and_sensitive():
    base = standings_fingerprint([state_of(four_groups_table())])
    assert len(base) == 64
    shuffled = four_groups_table()
    shuffled[0] = list(reversed(shuffled[0]))
    assert standings_fingerprint([state_of(shuffled)]) == base
    changed = four_groups_table()
    changed[0][3] = row(0, 4, 1)
    assert standings_fingerprint([state_of(changed)]) != base
    assert standings_fingerprint([state_of(four_groups_table(), statuses={tid(0, 1): "withdrawn"})]) != base
    assert standings_fingerprint(
        [state_of(four_groups_table(), matches=(("m1", "finished", True), ("m2", "finished", True)))]
    ) != base
