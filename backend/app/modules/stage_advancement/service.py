"""Lecturas y escrituras de la spec 040 sobre la sesión con RLS del llamador."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.stage_advancement.origins import (
    GROUP_POSITION,
    SlotError,
    SlotOrigin,
    SlotResolution,
    SourceGroup,
    SourceStage,
    SourceState,
    resolve_slots,
    standings_fingerprint,
)
from app.modules.standings.service import StandingsService

ELIMINATION_STAGE_TYPES = frozenset({"single_elimination", "double_elimination"})
SLOT_ORIGINS_CONFLICT = "La llave tiene orígenes declarados: sus equipos se asignan al confirmar la clasificación de origen"


async def load_destination_stage(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID, stage_id: UUID
) -> Mapping:
    result = await db.execute(
        text("""
            SELECT s.id, s.tournament_version_id, s.stage_type, s.stage_order,
                   tv.status AS version_status
            FROM stages s
            JOIN tournament_versions tv
              ON tv.id = s.tournament_version_id
             AND tv.tournament_id = s.tournament_id
             AND tv.organization_id = s.organization_id
            WHERE s.id = :stage_id
              AND s.tournament_id = :tournament_id
              AND s.organization_id = :organization_id
        """),
        {"stage_id": str(stage_id), "tournament_id": str(tournament_id), "organization_id": str(organization_id)},
    )
    stage = result.mappings().one_or_none()
    if stage is None:
        raise HTTPException(status_code=404, detail="Fase no encontrada")
    return stage


def require_elimination(stage: Mapping) -> None:
    if stage["stage_type"] not in ELIMINATION_STAGE_TYPES:
        raise HTTPException(status_code=422, detail="Solo una llave eliminatoria admite orígenes de plaza")


async def load_source_stages(
    db: AsyncSession, organization_id: UUID, stage: Mapping
) -> tuple[dict[UUID, SourceStage], list[dict]]:
    """Fases anteriores de la misma versión que pueden alimentar la llave, con sus grupos y tamaños."""

    stage_rows = (await db.execute(
        text("""
            SELECT s.id, s.name, s.stage_type
            FROM stages s
            WHERE s.organization_id = :organization_id
              AND s.tournament_version_id = :version_id
              AND s.stage_order < :stage_order
              AND s.stage_type IN ('round_robin', 'custom_group', 'swiss')
            ORDER BY s.stage_order, s.id
        """),
        {
            "organization_id": str(organization_id),
            "version_id": str(stage["tournament_version_id"]),
            "stage_order": stage["stage_order"],
        },
    )).mappings().all()
    if not stage_rows:
        return {}, []
    team_rows = (await db.execute(
        text("""
            SELECT s.id AS stage_id, g.id AS group_id, g.name AS group_name,
                   count(st.team_id) AS size
            FROM stages s
            LEFT JOIN groups g
              ON g.stage_id = s.id AND g.organization_id = s.organization_id
            LEFT JOIN stage_teams st
              ON st.stage_id = s.id
             AND st.organization_id = s.organization_id
             AND st.group_id IS NOT DISTINCT FROM g.id
            WHERE s.organization_id = :organization_id
              AND s.tournament_version_id = :version_id
              AND s.stage_order < :stage_order
              AND s.stage_type IN ('round_robin', 'custom_group', 'swiss')
            GROUP BY s.id, g.id, g.name
            ORDER BY s.id, g.name, g.id
        """),
        {
            "organization_id": str(organization_id),
            "version_id": str(stage["tournament_version_id"]),
            "stage_order": stage["stage_order"],
        },
    )).mappings().all()
    groups_by_stage: dict[UUID, list[SourceGroup]] = {}
    for row in team_rows:
        groups_by_stage.setdefault(row["stage_id"], []).append(
            SourceGroup(id=row["group_id"], name=row["group_name"], size=int(row["size"]))
        )
    stages: dict[UUID, SourceStage] = {}
    described: list[dict] = []
    for row in stage_rows:
        source = SourceStage(id=row["id"], groups=tuple(groups_by_stage.get(row["id"], ())))
        stages[row["id"]] = source
        described.append({
            "id": row["id"],
            "name": row["name"],
            "stage_type": row["stage_type"],
            "groups": [{"id": group.id, "name": group.name, "size": group.size} for group in source.groups],
        })
    return stages, described


async def load_declared_origins(
    db: AsyncSession, organization_id: UUID, stage_id: UUID
) -> list[tuple[int, SlotOrigin]]:
    rows = (await db.execute(
        text("""
            SELECT ps.source_reference
            FROM phase_slots ps
            WHERE ps.organization_id = :organization_id
              AND ps.stage_id = :stage_id
              AND ps.source_type = 'stage_rank'
            ORDER BY (ps.source_reference->>'seed')::int, ps.id
        """),
        {"organization_id": str(organization_id), "stage_id": str(stage_id)},
    )).mappings().all()
    return [
        (int(row["source_reference"]["seed"]), SlotOrigin.from_reference(row["source_reference"]))
        for row in rows
    ]


async def stage_has_slot_origins(db: AsyncSession, organization_id: UUID, stage_id: UUID) -> bool:
    result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM phase_slots
                WHERE organization_id = :organization_id
                  AND stage_id = :stage_id
                  AND source_type = 'stage_rank'
            )
        """),
        {"organization_id": str(organization_id), "stage_id": str(stage_id)},
    )
    return bool(result.scalar_one())


async def stage_is_resolved(db: AsyncSession, organization_id: UUID, stage_id: UUID) -> bool:
    result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM stage_slot_resolutions
                WHERE organization_id = :organization_id AND stage_id = :stage_id
            )
        """),
        {"organization_id": str(organization_id), "stage_id": str(stage_id)},
    )
    return bool(result.scalar_one())


def origin_payload(seed: int, origin: SlotOrigin) -> dict:
    return {
        "seed": seed,
        "kind": origin.kind,
        "source_stage_id": origin.source_stage_id,
        "position": origin.position,
        "group_id": origin.group_id if origin.kind == GROUP_POSITION else None,
        "ordinal": origin.ordinal,
    }


def slot_errors_exception(errors: list[SlotError]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "invalid_slot_origins",
            "errors": [{"seed": error.seed, "code": error.code} for error in errors],
        },
    )


@dataclass(frozen=True)
class ResolutionPreview:
    origins: list[SlotOrigin]
    resolutions: list[SlotResolution]
    states: dict[UUID, SourceState]
    fingerprint: str

    @property
    def resolvable(self) -> bool:
        return all(item.reason is None for item in self.resolutions)


async def _load_source_state(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID, source: SourceStage
) -> SourceState:
    params = {"organization_id": str(organization_id), "tournament_id": str(tournament_id), "stage_id": str(source.id)}
    ranking = await StandingsService(db).rank_stage(organization_id, tournament_id, source.id)
    statuses = (await db.execute(
        text("""
            SELECT st.team_id, tt.status
            FROM stage_teams st
            JOIN tournament_teams tt
              ON tt.team_id = st.team_id
             AND tt.tournament_id = st.tournament_id
             AND tt.organization_id = st.organization_id
            WHERE st.organization_id = :organization_id
              AND st.tournament_id = :tournament_id
              AND st.stage_id = :stage_id
        """),
        params,
    )).all()
    matches = (await db.execute(
        text("""
            SELECT id, status, result_confirmed
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND stage_id = :stage_id
        """),
        params,
    )).all()
    return SourceState(
        stage=source,
        buckets=ranking.buckets,
        team_statuses={row.team_id: row.status for row in statuses},
        matches=[(str(row.id), row.status, bool(row.result_confirmed)) for row in matches],
        pipeline=ranking.pipeline,
        tie_seed=ranking.tie_seed,
        points_system=ranking.points_system,
    )


async def build_resolution_preview(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID, stage: Mapping
) -> ResolutionPreview:
    """Equipo o motivo por plaza con la clasificación vigente; solo lecturas (RF-004–RF-006)."""

    declared = await load_declared_origins(db, organization_id, stage["id"])
    if not declared:
        raise HTTPException(status_code=422, detail={"code": "no_slot_origins"})
    sources, _ = await load_source_stages(db, organization_id, stage)
    origins = [origin for _, origin in declared]
    states: dict[UUID, SourceState] = {}
    for source_id in sorted({origin.source_stage_id for origin in origins}, key=str):
        if source_id in sources:
            states[source_id] = await _load_source_state(db, organization_id, tournament_id, sources[source_id])
    resolutions = resolve_slots(origins, states)
    counts = Counter(item.team_id for item in resolutions if item.team_id is not None)
    resolutions = [
        replace(item, team_id=None, reason="duplicate_team")
        if item.reason is None and counts[item.team_id] > 1
        else item
        for item in resolutions
    ]
    return ResolutionPreview(
        origins=origins,
        resolutions=resolutions,
        states=states,
        fingerprint=standings_fingerprint(states.values()),
    )


async def preview_payload(db: AsyncSession, organization_id: UUID, stage: Mapping, preview: ResolutionPreview) -> dict:
    team_ids = [str(item.team_id) for item in preview.resolutions if item.team_id is not None]
    names = {}
    if team_ids:
        rows = (await db.execute(
            text("""
                SELECT id, name FROM teams
                WHERE organization_id = :organization_id AND id = ANY(CAST(:team_ids AS uuid[]))
            """),
            {"organization_id": str(organization_id), "team_ids": team_ids},
        )).all()
        names = {row.id: row.name for row in rows}
    return {
        "stage_id": stage["id"],
        "fingerprint": preview.fingerprint,
        "resolvable": preview.resolvable,
        "slots": [
            {
                **origin_payload(item.seed, item.origin),
                "team_id": item.team_id,
                "team_name": names.get(item.team_id),
                "reason": item.reason,
            }
            for item in preview.resolutions
        ],
        "source_stages": [
            {"id": source_id, "finished": state.finished} for source_id, state in preview.states.items()
        ],
    }
