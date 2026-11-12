from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.locking import lock_matches
from app.core.tenancy import AuthContext
from app.modules.rule_contract import GRAND_FINAL_CODE, RESET_CODE


@dataclass(frozen=True)
class AdvancementImpactCandidate:
    source_match_id: UUID
    match_id: UUID | None
    side: str | None
    before_team_id: UUID | None
    after_team_id: UUID | None
    advancement_link_id: UUID | None
    reason: str
    stage_id: UUID | None = None


async def advancement_changes(db: AsyncSession, context: AuthContext, version: Mapping[str, Any], rows: list[dict]):
    before = version["advancement_before"]
    params = {"organization_id": context.organization_id, "source_id": version["match_id"],
        "version_id": version["id"], "tournament_version_id": before["tournament_version_id"],
        "stage_id": version["stage_id"]}
    links = [dict(row) for row in (await db.execute(text("""SELECT * FROM advancement_links
        WHERE organization_id=:organization_id AND source_match_id=:source_id
        ORDER BY target_match_id,target_side,id"""), params)).mappings().all()]
    reset = []
    if before["bracket_code"] == GRAND_FINAL_CODE and before["winner_team_id"] != version["winner_team_id"]:
        reset = (await db.execute(text("""SELECT id FROM matches WHERE organization_id=:organization_id
            AND tournament_version_id=:tournament_version_id AND stage_id=:stage_id AND bracket_code=:reset"""),
            {**params, "reset": RESET_CODE})).scalars().all()
    await lock_matches(db, context.organization_id, [row["target_match_id"] for row in links] + list(reset))
    effects, candidates, targets = [], [], {}
    if before["winner_team_id"] != version["winner_team_id"]:
        for link in links:
            team = version["winner_team_id"]
            if link["outcome"] == "loser":
                team = None if team is None else (before["away_team_id"] if team == before["home_team_id"] else before["home_team_id"])
            target = (await db.execute(text("""SELECT m.id,m.home_team_id,m.away_team_id,
                rectification_slot_rejection(m,CAST(:team AS uuid),:side,CAST(:version_id AS uuid)) AS rejection
                FROM matches m WHERE m.id=:target AND m.organization_id=:organization_id"""),
                {**params, "team": team, "side": link["target_side"], "target": link["target_match_id"]})).mappings().one()
            old_team = target[f"{link['target_side']}_team_id"]
            targets[target["id"]] = target
            rejection = target["rejection"] or ("bracket_reset" if target["id"] in reset else None)
            if rejection:
                candidates.append(AdvancementImpactCandidate(version["match_id"], target["id"], link["target_side"],
                    old_team, team, link["id"], rejection))
                continue
            if team == old_team:
                continue
            prior = (await db.execute(text("""SELECT id FROM match_slot_assignments
                WHERE organization_id=:organization_id AND match_id=:target AND side=:side
                ORDER BY assigned_at DESC,id DESC LIMIT 1"""),
                {**params, "target": target["id"], "side": link["target_side"]})).scalar_one()
            effects.append({"effect_type": "advancement", "entity_type": "match", "entity_id": str(target["id"]),
                "payload": {"original_match_id": str(version["match_id"]), "version_id": str(version["id"]),
                    "source_match_id": str(version["match_id"]), "target_match_id": str(target["id"]),
                    "side": link["target_side"], "advancement_link_id": str(link["id"]),
                    "before_assignment_id": str(prior), "before_team_id": str(old_team), "after_team_id": str(team)}})
    planned = {}
    for effect in effects:
        payload = effect["payload"]
        planned.setdefault(UUID(effect["entity_id"]), {})[payload["side"]] = UUID(payload["after_team_id"])
    conflicts = set()
    for match_id, teams in planned.items():
        home = teams.get("home", targets[match_id]["home_team_id"])
        away = teams.get("away", targets[match_id]["away_team_id"])
        if home is not None and home == away:
            conflicts.add(match_id)
    safe = []
    for effect in effects:
        payload = effect["payload"]
        if UUID(effect["entity_id"]) in conflicts:
            candidates.append(AdvancementImpactCandidate(version["match_id"], UUID(effect["entity_id"]), payload["side"],
                UUID(payload["before_team_id"]), UUID(payload["after_team_id"]), UUID(payload["advancement_link_id"]), "opponent_conflict"))
        else:
            safe.append(effect)
    effects = safe
    for match_id in reset:
        if not any(candidate.match_id == match_id for candidate in candidates):
            candidates.append(AdvancementImpactCandidate(version["match_id"], match_id, None, None, None, None, "bracket_reset"))
    def order(table):
        return sorted((str(row.get("group_id")), str(row["team_id"]), row["rank"]) for row in table)
    if order(version["standings_before"]["rows"]) != order(rows):
        stages = (await db.execute(text("""SELECT DISTINCT later.id FROM stages current_stage
            JOIN stages later ON later.organization_id=current_stage.organization_id
              AND later.tournament_version_id=current_stage.tournament_version_id
              AND later.tournament_id=current_stage.tournament_id AND later.stage_order>current_stage.stage_order
            JOIN stage_teams st ON st.stage_id=later.id AND st.organization_id=later.organization_id
            WHERE current_stage.id=:stage_id AND current_stage.organization_id=:organization_id ORDER BY later.id"""), params)).scalars().all()
        candidates.extend(AdvancementImpactCandidate(version["match_id"], None, None, None, None, None, "later_phase", stage)
            for stage in stages)
    return effects, candidates


async def substitute_slots(db, context, effects):
    targets = {}
    for effect in effects:
        payload = effect["payload"]
        targets.setdefault(UUID(payload["target_match_id"]), {})[payload["side"]] = UUID(payload["after_team_id"])
    for target, teams in targets.items():
        if "home" in teams and "away" in teams:
            statement = "UPDATE matches SET home_team_id=:home,away_team_id=:away,updated_at=CURRENT_TIMESTAMP WHERE id=:target AND organization_id=:organization_id"
        elif "home" in teams:
            statement = "UPDATE matches SET home_team_id=:home,updated_at=CURRENT_TIMESTAMP WHERE id=:target AND organization_id=:organization_id"
        else:
            statement = "UPDATE matches SET away_team_id=:away,updated_at=CURRENT_TIMESTAMP WHERE id=:target AND organization_id=:organization_id"
        await db.execute(text(statement), {**teams, "target": target, "organization_id": context.organization_id})
