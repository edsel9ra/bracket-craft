from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from app.modules.rules_engine.engine import deterministic_tie_value
from app.modules.standings.head_to_head import MatchRecord, calculate_head_to_head_stats


def ranking_value(item: Mapping, criterion: str, tie_seed: str):
    if criterion == "goals_against":
        return -int(item["goals_against"])
    if criterion == "random_draw":
        return deterministic_tie_value(tie_seed, item["team_id"])
    return item.get(criterion, 0)


def rank_buckets(
    items: Iterable[Mapping],
    pipeline: Sequence[Mapping],
    *,
    points_system: Mapping[str, int],
    tie_seed: str,
    match_records: Sequence[MatchRecord] = (),
    include_head_to_head: bool = True,
) -> tuple[list[list[Mapping]], list[list[Mapping]]]:
    """Order one table by the version pipeline.

    Returns the final buckets (a bucket with more than one item is a tie no
    declared criterion breaks) and the buckets that reached ``random_draw``.
    """

    def split(bucket: list[Mapping], step: Mapping) -> list[list[Mapping]]:
        if len(bucket) < 2:
            return [bucket]
        criterion = step["criterion"]
        if criterion == "head_to_head":
            if not include_head_to_head:
                return [bucket]
            stats = calculate_head_to_head_stats(
                {item["team_id"] for item in bucket},
                list(match_records),
                step["params"]["total_rounds_expected"],
                points_system,
            )
            if stats is None:
                return [bucket]

            def key_for(item):
                value = stats[item["team_id"]]
                return (value.points, value.goal_diff, value.goals_for)
        else:
            def key_for(item):
                return ranking_value(item, criterion, tie_seed)

        by_key: defaultdict = defaultdict(list)
        for item in bucket:
            by_key[key_for(item)].append(item)
        return [by_key[key] for key in sorted(by_key, reverse=True)]

    buckets = [list(items)]
    draw_buckets: list[list[Mapping]] = []
    for step in pipeline:
        next_buckets = []
        for bucket in buckets:
            if step["criterion"] == "random_draw" and len(bucket) > 1:
                draw_buckets.append(bucket)
            next_buckets.extend(split(bucket, step))
        buckets = next_buckets
    return [bucket for bucket in buckets if bucket], draw_buckets
