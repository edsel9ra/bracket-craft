from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sanction_appeals.effective import DurationProjection, EffectiveResolution, project_duration


@dataclass(frozen=True, slots=True)
class EffectiveSanction:
    suspension_id: UUID
    player_id: UUID
    origin_match_id: UUID | None
    created_at: datetime
    projection: DurationProjection
    current_projection: DurationProjection
    resolution_id: UUID | None
    requires_review: bool


def _instant(value: datetime | str) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def project_fact(fact: Mapping[str, Any], *, as_of: datetime, started_at: datetime | None,
                 preview: bool = False, current: bool = False) -> tuple[DurationProjection, UUID | None, bool]:
    resolutions = [r for r in fact["resolutions"] if _instant(r["created_at"]) <= as_of]
    count = len(fact["serves"])
    status = fact["status"]
    original = fact["original_duration"]
    if not resolutions:
        return project_duration(original, count, status=status), None, False
    snapshot = None if current else fact["snapshot"]
    if snapshot:
        resolution = next((r for r in resolutions if str(r["id"]) == snapshot["resolution_id"]), None)
        projection = project_duration(original, count, status=snapshot["applicable_status"],
            resolution=EffectiveResolution(resolution["action"], resolution["new_duration"], applied=True)
            if resolution else None)
        return projection, UUID(resolution["id"]) if resolution else None, False
    eligible = [r for r in resolutions if not r["excluded"]]
    applications = {str(a["resolution_id"]): a for a in fact["applications"] if _instant(a["effective_at"]) <= as_of}
    boundary = as_of if current or started_at is None else started_at
    selected = [r for r in eligible if r["is_declarative"] or
        (str(r["id"]) in applications and _instant(applications[str(r["id"])]["effective_at"]) <= boundary)]
    pending = [r for r in eligible if not r["is_declarative"] and str(r["id"]) not in applications]
    anticipated = preview and started_at is None and bool(pending)
    resolution = (pending[-1] if anticipated else selected[-1] if selected else None)
    review = not current and started_at is not None and not snapshot and bool(eligible)
    if not current and started_at is not None:
        later = [a for a in fact["applications"] if _instant(a["effective_at"]) > started_at]
        if later:
            status = later[0].get("before_status", "active")
    if resolution:
        projection = project_duration(original, count, status=status,
            resolution=EffectiveResolution(resolution["action"], resolution["new_duration"], applied=True,
                declarative=resolution["is_declarative"]))
        return replace(projection, pending_effect=anticipated), UUID(resolution["id"]), review
    projection = project_duration(original, count, status=status)
    return replace(projection, pending_effect=bool(pending)), None, review


async def load_effective_sanctions(db: AsyncSession, match_id: UUID, *, as_of: datetime,
                                  preview: bool = False) -> list[EffectiveSanction]:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("A timezone-aware instant is required")
    facts = (await db.execute(text("SELECT * FROM sanction_operational_facts(:match_id)"),
        {"match_id": match_id})).mappings().all()
    started_at = (await db.execute(text("""SELECT min(created_at) FROM match_segments
        WHERE match_id=:match_id AND organization_id=NULLIF(current_setting('app.current_organization_id',true),'')::uuid"""),
        {"match_id": match_id})).scalar_one()
    result = []
    for fact in facts:
        projection, resolution_id, review = project_fact(fact, as_of=as_of, started_at=started_at, preview=preview)
        current_projection, _, _ = project_fact(fact, as_of=as_of, started_at=None, current=True)
        result.append(EffectiveSanction(fact["suspension_id"], fact["player_id"], fact["origin_match_id"],
            fact["created_at"], projection, current_projection, resolution_id, review))
    return result
