from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MatchRecord:
    home_team_id: UUID
    away_team_id: UUID
    home_score: int
    away_score: int
    is_finished: bool
    winner_team_id: UUID | None = None


@dataclass
class HeadToHeadStats:
    team_id: UUID
    points: int = 0
    goal_diff: int = 0
    goals_for: int = 0


def _fallback_order(
    tied_team_ids: set[UUID],
    fallback_order: Sequence[UUID] | None,
) -> list[UUID]:
    result: list[UUID] = []
    seen: set[UUID] = set()
    for team_id in fallback_order or ():
        if team_id in tied_team_ids and team_id not in seen:
            result.append(team_id)
            seen.add(team_id)
    result.extend(sorted(tied_team_ids - seen, key=str))
    return result


def calculate_head_to_head_stats(
    tied_team_ids: set[UUID],
    matches: list[MatchRecord],
    total_rounds_expected: int,
    points_system: Mapping[str, int] | None = None,
) -> dict[UUID, HeadToHeadStats] | None:
    """Build the complete mini-table or return None when direct matches are pending."""
    if type(total_rounds_expected) is not int or total_rounds_expected not in {1, 2}:
        raise ValueError("total_rounds_expected debe ser 1 o 2")

    stats = {team_id: HeadToHeadStats(team_id=team_id) for team_id in tied_team_ids}
    if len(tied_team_ids) < 2:
        return stats

    relevant_matches = [
        match
        for match in matches
        if match.is_finished
        and match.home_team_id in tied_team_ids
        and match.away_team_id in tied_team_ids
    ]
    expected_matches_count = (
        len(tied_team_ids) * (len(tied_team_ids) - 1) // 2 * total_rounds_expected
    )
    pair_counts = {
        frozenset((home_team_id, away_team_id)): 0
        for index, home_team_id in enumerate(sorted(tied_team_ids, key=str))
        for away_team_id in sorted(tied_team_ids, key=str)[index + 1:]
    }
    for match in relevant_matches:
        pair = frozenset((match.home_team_id, match.away_team_id))
        if len(pair) != 2 or pair not in pair_counts:
            return None
        pair_counts[pair] += 1
    if (
        len(relevant_matches) != expected_matches_count
        or any(count != total_rounds_expected for count in pair_counts.values())
    ):
        return None

    scoring = {"win": 3, "draw": 1, "loss": 0}
    if points_system is not None:
        scoring.update(points_system)

    for match in relevant_matches:
        home = stats[match.home_team_id]
        away = stats[match.away_team_id]

        home.goals_for += match.home_score
        away.goals_for += match.away_score
        home.goal_diff += match.home_score - match.away_score
        away.goal_diff += match.away_score - match.home_score

        if match.home_score > match.away_score:
            home.points += scoring["win"]
            away.points += scoring["loss"]
        elif match.away_score > match.home_score:
            away.points += scoring["win"]
            home.points += scoring["loss"]
        elif match.winner_team_id == match.home_team_id:
            home.points += scoring["win"]
            away.points += scoring["loss"]
        elif match.winner_team_id == match.away_team_id:
            away.points += scoring["win"]
            home.points += scoring["loss"]
        else:
            home.points += scoring["draw"]
            away.points += scoring["draw"]

    return stats


def resolve_head_to_head(
    tied_team_ids: set[UUID],
    matches: list[MatchRecord],
    total_rounds_expected: int,
    points_system: Mapping[str, int] | None = None,
    fallback_order: Sequence[UUID] | None = None,
) -> list[UUID]:
    """Order a tied group by direct results, preserving a deterministic fallback."""
    fallback = _fallback_order(tied_team_ids, fallback_order)
    stats = calculate_head_to_head_stats(
        tied_team_ids,
        matches,
        total_rounds_expected,
        points_system,
    )
    if stats is None:
        return fallback

    position = {team_id: index for index, team_id in enumerate(fallback)}
    return [
        item.team_id
        for item in sorted(
            stats.values(),
            key=lambda item: (
                item.points,
                item.goal_diff,
                item.goals_for,
                -position[item.team_id],
            ),
            reverse=True,
        )
    ]
