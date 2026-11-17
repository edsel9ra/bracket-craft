"""Funciones puras de la spec 040: orígenes de plaza, plantilla, resolución y huella."""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.standings.ranking import rank_buckets

GROUP_POSITION = "group_position"
BEST_OF_POSITION = "best_of_position"
ORIGIN_KINDS = frozenset({GROUP_POSITION, BEST_OF_POSITION})
MIN_SLOTS = 2
MAX_SLOTS = 64
FINISHED_MATCH_STATUSES = frozenset({"finished", "administrative_resolution"})
ELIGIBLE_TEAM_STATUS = "registered"
DEFAULT_POINTS_SYSTEM = {"win": 3, "draw": 1, "loss": 0}


@dataclass(frozen=True)
class SlotOrigin:
    kind: str
    source_stage_id: UUID
    position: int
    group_id: UUID | None = None
    ordinal: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in ORIGIN_KINDS:
            raise ValueError("Tipo de origen no admitido")
        if type(self.position) is not int or self.position < 1:
            raise ValueError("La posición debe ser un entero positivo")
        if self.kind == GROUP_POSITION and self.ordinal is not None:
            raise ValueError("Una posición de grupo no lleva ordinal")
        if self.kind == BEST_OF_POSITION and (
            self.group_id is not None or type(self.ordinal) is not int or self.ordinal < 1
        ):
            raise ValueError("«Mejores N.º» necesita un ordinal y ningún grupo")

    @property
    def key(self) -> tuple:
        return (self.kind, self.source_stage_id, self.group_id, self.position, self.ordinal)

    def to_reference(self) -> dict:
        reference: dict = {
            "kind": self.kind,
            "source_stage_id": str(self.source_stage_id),
            "position": self.position,
        }
        if self.kind == GROUP_POSITION:
            reference["group_id"] = str(self.group_id) if self.group_id is not None else None
        else:
            reference["ordinal"] = self.ordinal
        return reference

    @classmethod
    def from_reference(cls, reference: Mapping) -> "SlotOrigin":
        group_id = reference.get("group_id")
        return cls(
            kind=reference.get("kind"),
            source_stage_id=UUID(str(reference["source_stage_id"])),
            position=reference.get("position"),
            group_id=UUID(str(group_id)) if group_id is not None else None,
            ordinal=reference.get("ordinal"),
        )


@dataclass(frozen=True)
class SourceGroup:
    id: UUID | None
    name: str | None
    size: int


@dataclass(frozen=True)
class SourceStage:
    """Fase de origen admitida; una fase sin grupos tiene un único grupo con ``id=None``."""

    id: UUID
    groups: tuple[SourceGroup, ...]

    @property
    def has_groups(self) -> bool:
        return any(group.id is not None for group in self.groups)

    def group(self, group_id: UUID | None) -> SourceGroup | None:
        return next((group for group in self.groups if group.id == group_id), None)


@dataclass(frozen=True)
class SlotError:
    seed: int | None
    code: str


@dataclass(frozen=True)
class SlotResolution:
    seed: int
    origin: SlotOrigin
    team_id: UUID | None
    reason: str | None


@dataclass(frozen=True)
class SourceState:
    """Clasificación vigente de una fase de origen, ya ordenada por grupo."""

    stage: SourceStage
    buckets: Mapping[UUID | None, Sequence[Sequence[Mapping]]]
    team_statuses: Mapping[UUID, str]
    matches: Sequence[tuple[str, str, bool]]
    pipeline: Sequence[Mapping]
    tie_seed: str
    points_system: Mapping[str, int] = field(default_factory=lambda: DEFAULT_POINTS_SYSTEM)

    @property
    def finished(self) -> bool:
        return stage_finished(self.matches)


class TemplateError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _check_slots_count(slots_count: int) -> None:
    if type(slots_count) is not int or not MIN_SLOTS <= slots_count <= MAX_SLOTS:
        raise ValueError(f"La llave admite entre {MIN_SLOTS} y {MAX_SLOTS} plazas")


def seed_order(slots_count: int) -> list[int | None]:
    """Cabezas de serie por posición de la primera ronda (1 contra N…); ``None`` es pase libre."""

    _check_slots_count(slots_count)
    order = [1]
    while len(order) < slots_count:
        size = len(order) * 2
        order = [seed for item in order for seed in (item, size + 1 - item)]
    return [seed if seed <= slots_count else None for seed in order]


def first_round_pairs(slots_count: int) -> list[tuple[int, int]]:
    order = seed_order(slots_count)
    return [
        (order[index], order[index + 1])
        for index in range(0, len(order), 2)
        if order[index] is not None and order[index + 1] is not None
    ]


def validate_origins(
    origins: Sequence[SlotOrigin],
    source_stages: Mapping[UUID, SourceStage],
) -> list[SlotError]:
    """Errores por plaza (``seed`` 1-based) de una declaración (RF-002, RF-013, CL-8)."""

    if not MIN_SLOTS <= len(origins) <= MAX_SLOTS:
        return [SlotError(None, "invalid_slots_count")]

    errors: list[SlotError] = []
    seen: set[tuple] = set()
    group_positions: set[tuple[UUID, int]] = set()
    best_positions: set[tuple[UUID, int]] = set()
    for seed, origin in enumerate(origins, start=1):
        code = _origin_error(origin, source_stages.get(origin.source_stage_id))
        if code is None:
            position_key = (origin.source_stage_id, origin.position)
            if origin.key in seen:
                code = "duplicate_origin"
            elif origin.kind == GROUP_POSITION and position_key in best_positions:
                code = "overlapping_origin"
            elif origin.kind == BEST_OF_POSITION and position_key in group_positions:
                code = "overlapping_origin"
            seen.add(origin.key)
            (group_positions if origin.kind == GROUP_POSITION else best_positions).add(position_key)
        if code is not None:
            errors.append(SlotError(seed, code))
    return errors


def _origin_error(origin: SlotOrigin, stage: SourceStage | None) -> str | None:
    if stage is None:
        return "invalid_source_stage"
    if origin.kind == GROUP_POSITION:
        if origin.group_id is None and stage.has_groups:
            return "group_required"
        group = stage.group(origin.group_id)
        if group is None:
            return "group_not_found"
        return "position_out_of_range" if origin.position > group.size else None
    sizes = {group.size for group in stage.groups}
    if len(sizes) != 1:
        return "unequal_groups"
    if origin.position > sizes.pop():
        return "position_out_of_range"
    return "ordinal_out_of_range" if origin.ordinal > len(stage.groups) else None


def classic_template(stage: SourceStage, slots_count: int) -> list[SlotOrigin]:
    """Plantilla clásica en orden de cabeza de serie (RF-001b, CL-7)."""

    _check_slots_count(slots_count)
    if sum(group.size for group in stage.groups) < slots_count:
        raise TemplateError("not_enough_teams")

    tiers: list[list[SlotOrigin]] = []
    remaining = slots_count
    position = 0
    while remaining:
        position += 1
        available = [group for group in stage.groups if group.size >= position]
        if remaining >= len(available):
            tiers.append([
                SlotOrigin(GROUP_POSITION, stage.id, position, group_id=group.id) for group in available
            ])
            remaining -= len(available)
            continue
        if len({group.size for group in stage.groups}) != 1:
            raise TemplateError("unequal_groups")
        tiers.append([
            SlotOrigin(BEST_OF_POSITION, stage.id, position, ordinal=ordinal)
            for ordinal in range(1, remaining + 1)
        ])
        remaining = 0

    group_index = {group.id: index for index, group in enumerate(stage.groups)}
    opponent = {}
    for home, away in first_round_pairs(slots_count):
        opponent[home], opponent[away] = away, home

    seeds: dict[int, SlotOrigin] = {}
    tier_of: dict[int, list[int]] = {}
    next_seed = 1
    for tier in tiers:
        tier_seeds = list(range(next_seed, next_seed + len(tier)))
        next_seed += len(tier)
        candidates = list(tier)
        for seed in tier_seeds:
            rival = seeds.get(opponent.get(seed))
            choice = candidates[0]
            if rival is not None and rival.group_id is not None:
                preferred = group_index[rival.group_id] ^ 1
                choice = next(
                    (item for item in candidates if item.group_id is not None and group_index[item.group_id] == preferred),
                    next((item for item in candidates if item.group_id != rival.group_id), choice),
                )
            candidates.remove(choice)
            seeds[seed] = choice
            tier_of[seed] = tier_seeds

    _repair_same_group_pairs(seeds, tier_of, slots_count)
    return [seeds[seed] for seed in range(1, slots_count + 1)]


def _repair_same_group_pairs(seeds: dict[int, SlotOrigin], tier_of: dict[int, list[int]], slots_count: int) -> None:
    pairs = first_round_pairs(slots_count)

    def conflicts() -> int:
        return sum(
            1 for home, away in pairs
            if seeds[home].group_id is not None and seeds[home].group_id == seeds[away].group_id
        )

    current = conflicts()
    improved = True
    while current and improved:
        improved = False
        for home, away in pairs:
            if seeds[home].group_id is None or seeds[home].group_id != seeds[away].group_id:
                continue
            for other in tier_of[away]:
                if other == away:
                    continue
                seeds[away], seeds[other] = seeds[other], seeds[away]
                candidate = conflicts()
                if candidate < current:
                    current, improved = candidate, True
                    break
                seeds[away], seeds[other] = seeds[other], seeds[away]
            if improved:
                break


def stage_finished(matches: Iterable[tuple[str, str, bool]]) -> bool:
    """Terminada si hay partidos y todos están finalizados o resueltos con resultado confirmado (CL-2)."""

    items = list(matches)
    return bool(items) and all(
        status in FINISHED_MATCH_STATUSES and confirmed for _, status, confirmed in items
    )


def _position_in(buckets: Sequence[Sequence[Mapping]], position: int) -> tuple[Mapping | None, bool]:
    index = 0
    for bucket in buckets:
        if position <= index + len(bucket):
            return bucket[position - index - 1], len(bucket) > 1
        index += len(bucket)
    return None, False


def resolve_slots(
    origins: Sequence[SlotOrigin],
    states: Mapping[UUID, SourceState],
) -> list[SlotResolution]:
    """Equipo o motivo de bloqueo por plaza con la clasificación vigente (RF-004–RF-006, RF-012, RF-013)."""

    best_cache: dict[tuple[UUID, int], tuple[list[list[Mapping]] | None, str | None]] = {}
    resolutions = []
    for seed, origin in enumerate(origins, start=1):
        state = states.get(origin.source_stage_id)
        team, reason = None, None
        if state is None:
            reason = "invalid_source_stage"
        elif not state.finished:
            reason = "source_stage_unfinished"
        elif origin.kind == GROUP_POSITION:
            buckets = state.buckets.get(origin.group_id)
            if buckets is None:
                reason = "group_not_found"
            else:
                row, tied = _position_in(buckets, origin.position)
                if row is None:
                    reason = "position_missing"
                elif tied:
                    reason = "unresolved_tie"
                else:
                    team = row["team_id"]
        else:
            cache_key = (origin.source_stage_id, origin.position)
            if cache_key not in best_cache:
                best_cache[cache_key] = _rank_best_of(state, origin.position)
            ranked, reason = best_cache[cache_key]
            if ranked is not None:
                row, tied = _position_in(ranked, origin.ordinal)
                if row is None:
                    reason = "position_missing"
                elif tied:
                    reason = "unresolved_tie"
                else:
                    team = row["team_id"]
        if team is not None and state.team_statuses.get(team) != ELIGIBLE_TEAM_STATUS:
            reason = "team_ineligible"
        resolutions.append(SlotResolution(seed=seed, origin=origin, team_id=team, reason=reason))
    return resolutions


def _rank_best_of(state: SourceState, position: int) -> tuple[list[list[Mapping]] | None, str | None]:
    sizes = {sum(len(bucket) for bucket in buckets) for buckets in state.buckets.values()}
    if len(sizes) != 1:
        return None, "unequal_groups"
    candidates = []
    for group_id in sorted(state.buckets, key=lambda value: str(value)):
        row, tied = _position_in(state.buckets[group_id], position)
        if row is None:
            return None, "position_missing"
        if tied:
            return None, "unresolved_tie"
        candidates.append(row)
    buckets, _ = rank_buckets(
        candidates,
        state.pipeline,
        points_system=state.points_system,
        tie_seed=f"{state.tie_seed}:best_of:{position}",
        include_head_to_head=False,
    )
    return buckets, None


def standings_fingerprint(states: Iterable[SourceState]) -> str:
    """SHA-256 estable de clasificación, estados de equipos y partidos de las fases de origen (RF-008)."""

    payload = []
    for state in sorted(states, key=lambda item: str(item.stage.id)):
        payload.append({
            "stage": str(state.stage.id),
            "matches": sorted([list(item) for item in state.matches], key=lambda item: str(item[0])),
            "teams": sorted([str(team), status] for team, status in state.team_statuses.items()),
            "groups": [
                [str(group_id), [
                    sorted((dict(item) for item in bucket), key=lambda item: str(item["team_id"]))
                    for bucket in state.buckets[group_id]
                ]]
                for group_id in sorted(state.buckets, key=lambda value: str(value))
            ],
        })
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
