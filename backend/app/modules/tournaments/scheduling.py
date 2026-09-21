from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from uuid import UUID


MAX_SINGLE_ELIMINATION_TEAMS = 512


@dataclass(frozen=True)
class BracketEntrant:
    team_id: UUID | None = None
    source_match_code: str | None = None
    source_outcome: str = "winner"


@dataclass(frozen=True)
class GeneratedMatch:
    code: str
    round_number: int
    match_date: datetime
    home: BracketEntrant
    away: BracketEntrant
    lane: str = "main"


@dataclass(frozen=True)
class AdvancementLinkSpec:
    source_match_code: str
    target_match_code: str
    target_side: str
    outcome: str = "winner"


@dataclass(frozen=True)
class SingleEliminationBracket:
    seed: int
    bracket_size: int
    round_count: int
    matches: tuple[GeneratedMatch, ...]
    advancement_links: tuple[AdvancementLinkSpec, ...]
    reset_code: str | None = None
    reset_date: datetime | None = None


@dataclass(frozen=True)
class RoundRobinMatch:
    code: str
    round_number: int
    match_date: datetime
    home_team_id: UUID
    away_team_id: UUID


@dataclass(frozen=True)
class RoundRobinSchedule:
    seed: int
    legs: int
    round_count: int
    bye_count: int
    matches: tuple[RoundRobinMatch, ...]


@dataclass(frozen=True)
class GroupDraw:
    seed: int
    groups: tuple[tuple[UUID, ...], ...]


@dataclass(frozen=True)
class SwissPairing:
    home_team_id: UUID | None
    away_team_id: UUID | None
    bye_team_id: UUID | None = None


def _validate_team_ids(team_ids: list[UUID], minimum: int = 2) -> None:
    if len(team_ids) < minimum:
        raise ValueError(f"La fase necesita al menos {minimum} equipos")
    if len(set(team_ids)) != len(team_ids):
        raise ValueError("La fase contiene equipos repetidos")


def _schedule_date(start_date: datetime, round_number: int, match_number: int, round_interval_days: int, match_interval_hours: int) -> datetime:
    return start_date + timedelta(
        days=(round_number - 1) * round_interval_days,
        hours=(match_number - 1) * match_interval_hours,
    )


def distribute_groups(
    team_ids: list[UUID],
    *,
    group_count: int,
    seed: int,
    head_team_ids: list[UUID] | None = None,
) -> GroupDraw:
    _validate_team_ids(team_ids)
    if group_count < 2 or group_count > len(team_ids):
        raise ValueError("La cantidad de grupos debe estar entre 2 y la cantidad de equipos")
    if seed < 0:
        raise ValueError("La semilla no puede ser negativa")

    heads = list(head_team_ids or [])
    if heads and len(heads) != group_count:
        raise ValueError("Debe seleccionarse exactamente una cabeza de grupo por grupo")
    if len(set(heads)) != len(heads) or any(team_id not in team_ids for team_id in heads):
        raise ValueError("Las cabezas de grupo deben ser equipos distintos de la fase")

    rng = Random(seed)
    remaining = [team_id for team_id in team_ids if team_id not in heads]
    rng.shuffle(remaining)
    groups: list[list[UUID]] = [[team_id] if heads else [] for team_id in heads]
    if not groups:
        groups = [[] for _ in range(group_count)]

    for offset in range(0, len(remaining), group_count):
        order = list(range(group_count))
        rng.shuffle(order)
        for group_index, team_id in zip(order, remaining[offset:offset + group_count]):
            groups[group_index].append(team_id)

    if any(len(group) < 2 for group in groups):
        raise ValueError("Cada grupo debe tener al menos dos equipos")
    return GroupDraw(seed=seed, groups=tuple(tuple(group) for group in groups))


def build_round_robin_schedule(
    team_ids: list[UUID],
    *,
    seed: int,
    start_date: datetime,
    round_interval_days: int,
    match_interval_hours: int,
    legs: int = 2,
    code_prefix: str = "RR",
) -> RoundRobinSchedule:
    _validate_team_ids(team_ids)
    if seed < 0:
        raise ValueError("La semilla no puede ser negativa")
    if legs not in {1, 2}:
        raise ValueError("La fase round robin debe tener una o dos vueltas")
    if round_interval_days < 1:
        raise ValueError("El intervalo entre jornadas debe ser de al menos un día")
    if match_interval_hours < 1:
        raise ValueError("El intervalo entre partidos debe ser positivo")

    rng = Random(seed)
    rotation: list[UUID | None] = list(team_ids)
    rng.shuffle(rotation)
    if len(rotation) % 2:
        rotation.append(None)
    round_count = len(rotation) - 1
    base_matches: list[tuple[int, int, UUID, UUID]] = []

    for round_number in range(1, round_count + 1):
        match_number = 0
        for pair_index in range(len(rotation) // 2):
            left = rotation[pair_index]
            right = rotation[-pair_index - 1]
            if left is None or right is None:
                continue
            match_number += 1
            if (round_number + pair_index) % 2:
                left, right = right, left
            base_matches.append((round_number, match_number, left, right))
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]

    matches: list[RoundRobinMatch] = []
    for leg in range(legs):
        for round_number, match_number, home, away in base_matches:
            scheduled_round = round_number + leg * round_count
            if leg:
                home, away = away, home
            matches.append(
                RoundRobinMatch(
                    code=f"{code_prefix}{scheduled_round}-{match_number}",
                    round_number=scheduled_round,
                    match_date=_schedule_date(
                        start_date,
                        scheduled_round,
                        match_number,
                        round_interval_days,
                        match_interval_hours,
                    ),
                    home_team_id=home,
                    away_team_id=away,
                )
            )

    return RoundRobinSchedule(
        seed=seed,
        legs=legs,
        round_count=round_count * legs,
        bye_count=(round_count * legs) if len(team_ids) % 2 else 0,
        matches=tuple(matches),
    )


def build_swiss_pairings(
    team_ids: list[UUID],
    *,
    standings: list[dict],
    prior_pairs: set[frozenset[UUID]],
    seed: int,
    round_number: int,
    home_counts: dict[UUID, int] | None = None,
    away_counts: dict[UUID, int] | None = None,
    home_target: int | None = None,
    away_target: int | None = None,
    bye_counts: dict[UUID, int] | None = None,
) -> tuple[SwissPairing, ...]:
    _validate_team_ids(team_ids)
    if seed < 0:
        raise ValueError("La semilla no puede ser negativa")
    if round_number < 1:
        raise ValueError("La ronda Swiss debe ser positiva")

    home_counts = home_counts or {}
    away_counts = away_counts or {}
    bye_counts = bye_counts or {}
    rng = Random(seed)
    standing_by_id = {row["team_id"]: row for row in standings if row.get("team_id") in team_ids}
    random_order = {team_id: rng.random() for team_id in team_ids}

    def score_key(team_id: UUID) -> tuple[int, int, int, float, str]:
        row = standing_by_id.get(team_id, {})
        return (
            -int(row.get("points", 0)),
            -int(row.get("won", 0)),
            int(row.get("rank", len(team_ids) + 1)),
            random_order[team_id],
            str(team_id),
        )

    ordered = sorted(team_ids, key=score_key)

    def candidate_key(first: UUID, second: UUID) -> tuple[int, int, float]:
        first_row = standing_by_id.get(first, {})
        second_row = standing_by_id.get(second, {})
        same_record = (
            int(first_row.get("points", 0)) == int(second_row.get("points", 0))
            and int(first_row.get("won", 0)) == int(second_row.get("won", 0))
        )
        return (0 if same_record else 1, abs(score_key(first)[0] - score_key(second)[0]), random_order[second])

    def orientation_options(
        first: UUID,
        second: UUID,
        current_home_counts: dict[UUID, int],
        current_away_counts: dict[UUID, int],
    ) -> list[tuple[UUID, UUID]]:
        options = [(first, second), (second, first)]
        options.sort(
            key=lambda pair: (
                int(current_home_counts.get(pair[0], 0) >= (home_target if home_target is not None else 10**9)),
                int(current_away_counts.get(pair[1], 0) >= (away_target if away_target is not None else 10**9)),
                abs((current_home_counts.get(pair[0], 0) + 1) - current_away_counts.get(pair[0], 0)),
                random_order[pair[0]],
            )
        )
        valid = [
            pair for pair in options
            if home_target is None or current_home_counts.get(pair[0], 0) < home_target
            if away_target is None or current_away_counts.get(pair[1], 0) < away_target
        ]
        return valid if home_target is not None or away_target is not None else options

    def pair_remaining(
        remaining: tuple[UUID, ...],
        current_home_counts: dict[UUID, int],
        current_away_counts: dict[UUID, int],
    ) -> list[tuple[UUID, UUID]] | None:
        if not remaining:
            return []
        first = remaining[0]
        candidates = sorted(remaining[1:], key=lambda team_id: candidate_key(first, team_id))
        for second in candidates:
            if frozenset((first, second)) in prior_pairs:
                continue
            rest = tuple(team_id for team_id in remaining[1:] if team_id != second)
            for home, away in orientation_options(first, second, current_home_counts, current_away_counts):
                current_home_counts[home] = current_home_counts.get(home, 0) + 1
                current_away_counts[away] = current_away_counts.get(away, 0) + 1
                result = pair_remaining(rest, current_home_counts, current_away_counts)
                current_home_counts[home] -= 1
                current_away_counts[away] -= 1
                if result is not None:
                    return [(home, away), *result]
        return None

    bye_candidates = ordered
    if len(bye_candidates) % 2:
        bye_candidates = sorted(
            bye_candidates,
            key=lambda team_id: (
                bye_counts.get(team_id, 0),
                int(standing_by_id.get(team_id, {}).get("points", 0)),
                int(standing_by_id.get(team_id, {}).get("won", 0)),
                -int(standing_by_id.get(team_id, {}).get("rank", len(team_ids) + 1)),
                random_order[team_id],
            ),
        )
        for bye_team in bye_candidates:
            remaining = tuple(team_id for team_id in ordered if team_id != bye_team)
            pairs = pair_remaining(remaining, dict(home_counts), dict(away_counts))
            if pairs is not None:
                return (*[SwissPairing(home, away) for home, away in pairs], SwissPairing(None, None, bye_team))
    else:
        pairs = pair_remaining(tuple(ordered), dict(home_counts), dict(away_counts))
        if pairs is not None:
            return tuple(SwissPairing(home, away) for home, away in pairs)

    raise ValueError("No existe un sorteo Swiss válido sin repetir rivales")


def _next_power_of_two(value: int) -> int:
    return 1 << (value - 1).bit_length()


def _match_code(round_count: int, round_number: int, match_number: int) -> str:
    teams_in_round = 2 ** (round_count - round_number + 1)
    if round_number == round_count:
        return "FINAL"
    if teams_in_round == 4:
        return f"SF{match_number}"
    if teams_in_round == 8:
        return f"QF{match_number}"
    return f"R{teams_in_round}-{match_number}"


def build_single_elimination_bracket(
    team_ids: list[UUID],
    *,
    seed: int,
    start_date: datetime,
    round_interval_days: int,
    match_interval_hours: int,
) -> SingleEliminationBracket:
    if len(team_ids) < 2:
        raise ValueError("La fase necesita al menos dos equipos para generar una llave")
    if len(team_ids) > MAX_SINGLE_ELIMINATION_TEAMS:
        raise ValueError(f"La llave admite como máximo {MAX_SINGLE_ELIMINATION_TEAMS} equipos")
    if len(set(team_ids)) != len(team_ids):
        raise ValueError("La fase contiene equipos repetidos")
    if seed < 0:
        raise ValueError("La semilla no puede ser negativa")
    if round_interval_days < 1:
        raise ValueError("El intervalo entre rondas debe ser de al menos un día")
    if match_interval_hours < 1:
        raise ValueError("El intervalo entre partidos debe ser positivo")

    bracket_size = _next_power_of_two(len(team_ids))
    round_count = bracket_size.bit_length() - 1
    shuffled_team_ids = list(team_ids)
    Random(seed).shuffle(shuffled_team_ids)
    entries: list[BracketEntrant | None] = [
        *(BracketEntrant(team_id=team_id) for team_id in shuffled_team_ids),
        *([None] * (bracket_size - len(shuffled_team_ids))),
    ]
    matches: list[GeneratedMatch] = []
    advancement_links: list[AdvancementLinkSpec] = []

    for round_number in range(1, round_count + 1):
        next_entries: list[BracketEntrant | None] = []
        match_number = 0
        round_start = start_date + timedelta(days=(round_number - 1) * round_interval_days)

        for index in range(0, len(entries), 2):
            home = entries[index]
            away = entries[index + 1]
            if home is None or away is None:
                next_entries.append(home or away)
                continue

            match_number += 1
            code = _match_code(round_count, round_number, match_number)
            matches.append(
                GeneratedMatch(
                    code=code,
                    round_number=round_number,
                    match_date=round_start + timedelta(hours=(match_number - 1) * match_interval_hours),
                    home=home,
                    away=away,
                )
            )
            if home.source_match_code:
                advancement_links.append(
                    AdvancementLinkSpec(home.source_match_code, code, "home", home.source_outcome)
                )
            if away.source_match_code:
                advancement_links.append(
                    AdvancementLinkSpec(away.source_match_code, code, "away", away.source_outcome)
                )
            next_entries.append(BracketEntrant(source_match_code=code, source_outcome="winner"))

        entries = next_entries

    if not matches or matches[-1].code != "FINAL":
        raise ValueError("No se pudo construir la final de la llave")

    return SingleEliminationBracket(
        seed=seed,
        bracket_size=bracket_size,
        round_count=round_count,
        matches=tuple(matches),
        advancement_links=tuple(advancement_links),
    )


def build_double_elimination_bracket(
    team_ids: list[UUID],
    *,
    seed: int,
    start_date: datetime,
    round_interval_days: int,
    match_interval_hours: int,
) -> SingleEliminationBracket:
    _validate_team_ids(team_ids, minimum=4)
    if seed < 0:
        raise ValueError("La semilla no puede ser negativa")
    if round_interval_days < 1:
        raise ValueError("El intervalo entre rondas debe ser de al menos un día")
    if match_interval_hours < 1:
        raise ValueError("El intervalo entre partidos debe ser positivo")
    if len(team_ids) & (len(team_ids) - 1):
        raise ValueError("La doble eliminación necesita una cantidad de equipos potencia de dos")

    shuffled = list(team_ids)
    Random(seed).shuffle(shuffled)
    round_count = len(shuffled).bit_length() - 1
    matches: list[GeneratedMatch] = []
    advancement_links: list[AdvancementLinkSpec] = []

    def append_match(
        code: str,
        round_number: int,
        lane: str,
        home: BracketEntrant,
        away: BracketEntrant,
    ) -> GeneratedMatch:
        match = GeneratedMatch(
            code=code,
            round_number=round_number,
            match_date=_schedule_date(start_date, round_number, 1, round_interval_days, match_interval_hours),
            home=home,
            away=away,
            lane=lane,
        )
        matches.append(match)
        if home.source_match_code:
            advancement_links.append(
                AdvancementLinkSpec(home.source_match_code, code, "home", home.source_outcome)
            )
        if away.source_match_code:
            advancement_links.append(
                AdvancementLinkSpec(away.source_match_code, code, "away", away.source_outcome)
            )
        return match

    winners_rounds: list[list[GeneratedMatch]] = []
    entries: list[BracketEntrant] = [BracketEntrant(team_id=team_id) for team_id in shuffled]
    for round_number in range(1, round_count + 1):
        current_round: list[GeneratedMatch] = []
        for match_number in range(0, len(entries), 2):
            current_round.append(
                append_match(
                    f"W{round_number}-{match_number // 2 + 1}",
                    round_number,
                    "winners",
                    entries[match_number],
                    entries[match_number + 1],
                )
            )
        winners_rounds.append(current_round)
        entries = [BracketEntrant(source_match_code=match.code) for match in current_round]

    previous_major: list[GeneratedMatch] = []
    losers_round_number = round_count + 1
    for winners_round_number in range(1, round_count):
        if winners_round_number == 1:
            minor_entries = [
                BracketEntrant(source_match_code=match.code, source_outcome="loser")
                for match in winners_rounds[0]
            ]
        else:
            minor_entries = [BracketEntrant(source_match_code=match.code) for match in previous_major]

        minor_round: list[GeneratedMatch] = []
        for match_number in range(0, len(minor_entries), 2):
            minor_round.append(
                append_match(
                    f"L{losers_round_number}-{match_number // 2 + 1}",
                    losers_round_number,
                    "losers",
                    minor_entries[match_number],
                    minor_entries[match_number + 1],
                )
            )
        losers_round_number += 1

        major_round: list[GeneratedMatch] = []
        for match_number, minor_match in enumerate(minor_round):
            major_round.append(
                append_match(
                    f"L{losers_round_number}-{match_number + 1}",
                    losers_round_number,
                    "losers",
                    BracketEntrant(source_match_code=minor_match.code),
                    BracketEntrant(
                        source_match_code=winners_rounds[winners_round_number][match_number].code,
                        source_outcome="loser",
                    ),
                )
            )
        previous_major = major_round
        losers_round_number += 1

    if not previous_major:
        raise ValueError("No se pudo construir la llave de perdedores")

    grand_final_round = losers_round_number
    append_match(
        "GF1",
        grand_final_round,
        "final",
        BracketEntrant(source_match_code=winners_rounds[-1][0].code),
        BracketEntrant(source_match_code=previous_major[0].code),
    )
    reset_round = grand_final_round + 1
    return SingleEliminationBracket(
        seed=seed,
        bracket_size=len(team_ids),
        round_count=reset_round,
        matches=tuple(matches),
        advancement_links=tuple(advancement_links),
        reset_code="GF2",
        reset_date=_schedule_date(start_date, reset_round, 1, round_interval_days, match_interval_hours),
    )
