import json
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import AuthContext
from app.modules.rectifications.sanctions import AccumulationImpactCandidate, recalculate_sanctions
from app.modules.standings.service import StandingsService


def invalidated_draws(before: list[dict], after: list[dict]) -> list[dict]:
    invalidations = []
    for previous in before:
        members = set(previous["team_ids"])
        current = [group for group in after if group["group_id"] == previous["group_id"]]
        if any(set(group["team_ids"]) == members for group in current):
            continue
        invalidations.append({"group_id": previous["group_id"], "before_team_ids": sorted(members),
            "after_team_groups": sorted(sorted(group["team_ids"]) for group in current
                if members.intersection(group["team_ids"]))})
    return invalidations


async def capture_standings(db: AsyncSession, context: AuthContext, match: Mapping[str, Any]) -> dict:
    rows, draw_groups = await StandingsService(db).snapshot(context, match["tournament_id"], match["stage_id"])
    return {"rows": rows, "draw_groups": draw_groups}


async def record_effect(db, context, version_id, effect, now):
    await db.execute(text("""
        INSERT INTO match_report_rectification_effects
            (organization_id, version_id, effect_type, entity_type, entity_id, payload, created_at)
        VALUES (:organization_id, :version_id, :effect_type, :entity_type, :entity_id, CAST(:payload AS jsonb), :now)
    """), {**effect, "organization_id": context.organization_id, "version_id": version_id,
        "payload": json.dumps(effect["payload"], default=str), "now": now})


async def apply_competitive_impacts(
    db: AsyncSession, context: AuthContext, version: Mapping[str, Any],
    candidates: list[AccumulationImpactCandidate], now: datetime,
) -> list[dict]:
    return []


async def apply_effects(db: AsyncSession, context: AuthContext, version: Mapping[str, Any], now: datetime) -> list[dict]:
    before = version["standings_before"]
    rows, draw_groups = await StandingsService(db).recalculate(context, version["tournament_id"], version["stage_id"])
    entity = {"entity_type": "stage", "entity_id": str(version["stage_id"])}
    effects = [{**entity, "effect_type": "standings", "payload": {"before": before["rows"], "after": rows}}]
    effects.extend({**entity, "effect_type": "tiebreak_draw_invalidated", "payload": payload}
        for payload in invalidated_draws(before["draw_groups"], draw_groups))
    sanctions = await recalculate_sanctions(db, context, version, now)
    effects.extend(sanctions.effects)
    effects.extend(await apply_competitive_impacts(db, context, version, sanctions.impact_candidates, now))
    for effect in effects:
        await record_effect(db, context, version["id"], effect, now)
    return effects
