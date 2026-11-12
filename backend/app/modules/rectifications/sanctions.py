from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import AuthContext
from app.modules.rules_engine.engine import discipline_history_order_key, evaluate_suspensions


@dataclass(frozen=True)
class AccumulationImpactCandidate:
    match_id: UUID
    player_id: UUID
    before_event_ids: tuple[str, ...]
    after_event_ids: tuple[str, ...]
    matches_suspended: int


@dataclass
class SanctionChanges:
    effects: list[dict]
    impact_candidates: list[AccumulationImpactCandidate]


def reconcile_sanctions(existing: list[dict], desired: list[dict]) -> tuple[list[dict], list[dict]]:
    def identity(row):
        return row["logical_event_id"], str(row["player_id"]), row["reason"]

    current = {identity(row): row for row in existing if row["status"] != "cancelled"}
    proposed = {identity(row): row for row in desired}
    return ([row for key, row in proposed.items() if key not in current],
        [row for key, row in current.items() if key not in proposed])


def accumulation_impacts(match_id: UUID, before: list[dict], after: list[dict], duration: int) -> list[AccumulationImpactCandidate]:
    def grouped(rows):
        groups = {}
        for row in rows:
            if row["reason"] == "yellow_card_accumulation":
                groups.setdefault(UUID(str(row["player_id"])), []).append(row["logical_event_id"])
        return {player: tuple(sorted(events)) for player, events in groups.items()}

    previous, proposed = grouped(before), grouped(after)
    return [AccumulationImpactCandidate(match_id, player, previous.get(player, ()), proposed.get(player, ()), duration)
        for player in sorted(previous.keys() | proposed.keys(), key=str)
        if previous.get(player, ()) != proposed.get(player, ())]


async def capture_discipline(db: AsyncSession, context: AuthContext, match: Mapping[str, Any]) -> dict:
    params = {"organization_id": context.organization_id, "tournament_id": match["tournament_id"]}
    rows = (await db.execute(text("""
        SELECT m.id AS match_id, m.match_date, m.stage_id, m.tournament_version_id, tv.rules_config,
               e.id, e.client_event_id, e.player_id, e.event_type, e.minute, e.added_minute, e.metadata
        FROM matches m JOIN tournament_versions tv
          ON tv.id = m.tournament_version_id AND tv.organization_id = m.organization_id
        LEFT JOIN v_match_current_events e
          ON e.match_id = m.id AND e.organization_id = m.organization_id
          AND NOT e.is_voided AND e.event_type IN ('yellow_card', 'red_card')
        WHERE m.organization_id = :organization_id AND m.tournament_id = :tournament_id
          AND m.result_confirmed
        ORDER BY m.match_date NULLS FIRST, m.id, e.minute, e.added_minute, e.client_event_id
    """), params)).mappings().all()
    matches, events = {}, []
    for row in rows:
        matches[row["match_id"]] = {"id": row["match_id"], **{key: row[key]
            for key in ("match_date", "stage_id", "tournament_version_id", "rules_config")}}
        if row["id"] is not None:
            events.append({key: row[key] for key in ("id", "client_event_id", "match_id", "player_id",
                "event_type", "minute", "added_minute", "metadata")})
    return {"matches": list(matches.values()), "events": events}


def _match_order(match):
    return discipline_history_order_key({"match_id": match["id"], "match_date": match["match_date"]})[:2]


def _derive(snapshot, match, events):
    by_id = {row["id"]: row for row in snapshot["matches"]}
    current = [event for event in events if event["match_id"] == match["id"]]
    history = []
    for event in events:
        origin = by_id[event["match_id"]]
        if _match_order(origin) >= _match_order(match):
            continue
        if match["rules_config"]["discipline"]["clear_yellows_on_stage_change"] and (
            origin["stage_id"] != match["stage_id"] or origin["tournament_version_id"] != match["tournament_version_id"]
        ):
            continue
        history.append({**event, "match_date": origin["match_date"]})
    logical_ids = {event["id"]: event["client_event_id"] for event in current}
    return [{**row, "logical_event_id": logical_ids[row["source_event_id"]]}
        for row in evaluate_suspensions(match["rules_config"], current, history)]


def _card_signature(events, match_id, player_id):
    return sorted((event["client_event_id"], str(event["player_id"]), event["event_type"],
        event["minute"], event["added_minute"], (event["metadata"] or {}).get("red_card_type", "direct_red"))
        for event in events if event["match_id"] == match_id and event["player_id"] == player_id)


async def recalculate_sanctions(
    db: AsyncSession, context: AuthContext, version: Mapping[str, Any], now: datetime,
) -> SanctionChanges:
    before = version["discipline_before"]
    match_id = version["match_id"]
    current = (await db.execute(text("""SELECT id, client_event_id, match_id, player_id,
        event_type, minute, added_minute, metadata FROM v_match_current_events
        WHERE organization_id = :organization_id AND match_id = :match_id AND NOT is_voided
          AND event_type IN ('yellow_card', 'red_card') ORDER BY minute, added_minute, client_event_id"""),
        {"organization_id": context.organization_id, "match_id": match_id})).mappings().all()
    after = {"matches": before["matches"], "events":
        [event for event in before["events"] if event["match_id"] != match_id] + [dict(row) for row in current]}
    players = {event["player_id"] for event in before["events"] + after["events"] if event["match_id"] == match_id}
    changed_players = {player for player in players
        if _card_signature(before["events"], match_id, player) != _card_signature(after["events"], match_id, player)}
    if not changed_players:
        return SanctionChanges([], [])
    target = next(match for match in before["matches"] if match["id"] == match_id)
    desired = [row for row in _derive(after, target, after["events"]) if row["player_id"] in changed_players]
    existing = [dict(row) for row in (await db.execute(text("""
        SELECT ps.*, COALESCE(e.client_event_id, ve.client_event_id) AS logical_event_id
        FROM player_suspensions ps
        LEFT JOIN match_events e ON e.id = ps.source_event_id AND e.organization_id = ps.organization_id
        LEFT JOIN match_report_version_events ve
          ON ve.id = ps.source_version_event_id AND ve.organization_id = ps.organization_id
        WHERE ps.organization_id = :organization_id AND ps.origin_match_id = :match_id
          AND ps.source_type = 'match_event'
          AND ps.player_id = ANY(CAST(:player_ids AS uuid[]))
        FOR UPDATE OF ps
    """), {"organization_id": context.organization_id, "match_id": match_id,
        "player_ids": sorted(changed_players, key=str)})).mappings().all()]
    created, annulled = reconcile_sanctions(existing, desired)
    effects = []
    for sanction in annulled:
        params = {"organization_id": context.organization_id, "suspension_id": sanction["id"],
            "version_id": version["id"], "now": now, "reason": "Sanción no derivada del acta rectificada"}
        await db.execute(text("""UPDATE player_suspensions SET status = 'cancelled'
            WHERE organization_id = :organization_id AND id = :suspension_id"""), params)
        await db.execute(text("""INSERT INTO player_suspension_annulments
            (organization_id, suspension_id, version_id, reason, created_at)
            VALUES (:organization_id, :suspension_id, :version_id, :reason, :now)"""), params)
        effects.append({"effect_type": "sanction_annulled", "entity_type": "player_suspension",
            "entity_id": str(sanction["id"]), "payload": {"before": sanction, "after_status": "cancelled"}})
    for sanction in created:
        params = {**sanction, "organization_id": context.organization_id, "tournament_id": version["tournament_id"],
            "match_id": match_id, "now": now,
            "dedupe_key": f"{version['id']}:{sanction['player_id']}:{sanction['source_event_id']}:{sanction['reason']}"}
        row = (await db.execute(text("""INSERT INTO player_suspensions
            (organization_id, source_tournament_id, player_id, origin_match_id, source_version_event_id,
             source_type, dedupe_key, scope_type, matches_suspended, reason, created_at)
            VALUES (:organization_id, :tournament_id, :player_id, :match_id, :source_event_id,
                    'match_event', :dedupe_key, :scope, :matches_suspended, :reason, :now)
            RETURNING *"""), params)).mappings().one()
        effects.append({"effect_type": "sanction_created", "entity_type": "player_suspension",
            "entity_id": str(row["id"]), "payload": {"sanction": dict(row), "logical_event_id": sanction["logical_event_id"]}})
    impacts = []
    for match in sorted(before["matches"], key=_match_order):
        if _match_order(match) > _match_order(target):
            impacts.extend(accumulation_impacts(match["id"], _derive(before, match, before["events"]),
                _derive(after, match, after["events"]), match["rules_config"]["discipline"]["yellow_card_suspension_matches"]))
    return SanctionChanges(effects, impacts)
