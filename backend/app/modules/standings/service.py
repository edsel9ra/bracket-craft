from collections import defaultdict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rules_engine.engine import deterministic_tie_value, validate_rules_config
from app.modules.standings.head_to_head import MatchRecord, calculate_head_to_head_stats


class StandingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def recalculate(self, context, tournament_id: UUID, stage_id: UUID) -> None:
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:lock_key AS TEXT), 0))"),
            {"lock_key": f"standings:{context.organization_id}:{tournament_id}:{stage_id}"},
        )
        config_result = await self.db.execute(
            text("""
                SELECT tv.rules_config
                FROM stages s
                JOIN tournament_versions tv
                  ON tv.id = s.tournament_version_id
                 AND tv.tournament_id = s.tournament_id
                 AND tv.organization_id = s.organization_id
                WHERE s.organization_id = :organization_id
                  AND s.tournament_id = :tournament_id
                  AND s.id = :stage_id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
            },
        )
        rules_config = config_result.scalar_one_or_none()
        if rules_config is None:
            raise ValueError("La fase no existe en el torneo indicado")
        validate_rules_config(rules_config)

        points_system = rules_config["points_system"]
        fair_play_penalties = rules_config["discipline"]["fair_play_penalties"]
        pipeline = rules_config["ranking_pipeline"]

        teams_result = await self.db.execute(
            text("""
                SELECT team_id, group_id
                FROM stage_teams
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND stage_id = :stage_id
                ORDER BY group_id NULLS FIRST, team_id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
            },
        )
        rows = teams_result.mappings().all()
        table: dict[tuple[UUID, UUID | None], dict[str, int | UUID | None]] = {}
        for row in rows:
            key = (row["team_id"], row["group_id"])
            table[key] = {
                "team_id": row["team_id"],
                "group_id": row["group_id"],
                "played": 0,
                "won": 0,
                "drawn": 0,
                "lost": 0,
                "goals_for": 0,
                "goals_against": 0,
                "points": 0,
                "fair_play_points": 0,
            }

        discipline_result = await self.db.execute(
            text("""
                SELECT me.team_id, me.event_type, me.metadata
                FROM match_events me
                JOIN matches m
                  ON m.id = me.match_id
                 AND m.organization_id = me.organization_id
                WHERE me.organization_id = :organization_id
                  AND m.tournament_id = :tournament_id
                  AND m.stage_id = :stage_id
                  AND m.status IN ('finished', 'administrative_resolution')
                  AND m.result_confirmed = TRUE
                  AND me.is_voided = FALSE
                 AND me.event_type IN ('yellow_card', 'red_card')
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
            },
        )
        for row in discipline_result.mappings().all():
            item = next(
                (
                    value
                    for value in table.values()
                    if value["team_id"] == row["team_id"]
                ),
                None,
            )
            if item is not None:
                metadata = row["metadata"] or {}
                penalty_key = "yellow_card"
                if row["event_type"] == "red_card":
                    penalty_key = (
                        "double_yellow_red"
                        if metadata.get("red_card_type") == "double_yellow_red"
                        else "direct_red"
                    )
                item["fair_play_points"] -= fair_play_penalties[penalty_key]

        matches_result = await self.db.execute(
            text("""
                SELECT group_id, home_team_id, away_team_id, home_score, away_score,
                       winner_team_id, resolution_type
                FROM matches
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND stage_id = :stage_id
                  AND status IN ('finished', 'administrative_resolution')
                  AND result_confirmed = TRUE
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
            },
        )
        matches = matches_result.mappings().all()
        match_records_by_group: defaultdict[UUID | None, list[MatchRecord]] = defaultdict(list)

        for match in matches:
            home = table.get((match["home_team_id"], match["group_id"]))
            away = table.get((match["away_team_id"], match["group_id"]))
            if home is None or away is None or match["home_score"] is None or match["away_score"] is None:
                continue
            match_records_by_group[match["group_id"]].append(
                MatchRecord(
                    home_team_id=match["home_team_id"],
                    away_team_id=match["away_team_id"],
                    home_score=match["home_score"],
                    away_score=match["away_score"],
                    is_finished=True,
                    winner_team_id=match["winner_team_id"],
                )
            )
            home["played"] += 1
            away["played"] += 1
            home["goals_for"] += match["home_score"]
            home["goals_against"] += match["away_score"]
            away["goals_for"] += match["away_score"]
            away["goals_against"] += match["home_score"]
            if match["home_score"] > match["away_score"]:
                home["won"] += 1
                away["lost"] += 1
                home["points"] += points_system["win"]
                away["points"] += points_system["loss"]
            elif match["home_score"] < match["away_score"]:
                away["won"] += 1
                home["lost"] += 1
                away["points"] += points_system["win"]
                home["points"] += points_system["loss"]
            elif match["winner_team_id"] == match["home_team_id"]:
                home["won"] += 1
                away["lost"] += 1
                home["points"] += points_system["win"]
                away["points"] += points_system["loss"]
            elif match["winner_team_id"] == match["away_team_id"]:
                away["won"] += 1
                home["lost"] += 1
                away["points"] += points_system["win"]
                home["points"] += points_system["loss"]
            else:
                home["drawn"] += 1
                away["drawn"] += 1
                home["points"] += points_system["draw"]
                away["points"] += points_system["draw"]

        for item in table.values():
            item["goal_difference"] = item["goals_for"] - item["goals_against"]

        def ranking_value(item, criterion):
            if criterion == "goals_against":
                return -int(item["goals_against"])
            if criterion == "random_draw":
                return deterministic_tie_value(f"{tournament_id}:{stage_id}", item["team_id"])
            return item.get(criterion, 0)

        def split_bucket(bucket, step):
            if len(bucket) < 2:
                return [bucket]

            criterion = step["criterion"]
            if criterion == "head_to_head":
                team_ids = {item["team_id"] for item in bucket}
                h2h_stats = calculate_head_to_head_stats(
                    team_ids,
                    match_records_by_group[bucket[0]["group_id"]],
                    step["params"]["total_rounds_expected"],
                    points_system,
                )
                if h2h_stats is None:
                    return [bucket]
                key_for = lambda item: (
                    h2h_stats[item["team_id"]].points,
                    h2h_stats[item["team_id"]].goal_diff,
                    h2h_stats[item["team_id"]].goals_for,
                )
            else:
                key_for = lambda item: ranking_value(item, criterion)

            buckets_by_key = defaultdict(list)
            for item in bucket:
                buckets_by_key[key_for(item)].append(item)
            return [buckets_by_key[key] for key in sorted(buckets_by_key, reverse=True)]

        await self.db.execute(
            text("""
                DELETE FROM standings
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND stage_id = :stage_id
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
            },
        )
        teams_by_group: defaultdict[UUID | None, list[dict]] = defaultdict(list)
        for item in table.values():
            teams_by_group[item["group_id"]].append(item)

        for group_id, group_items in teams_by_group.items():
            buckets = [group_items]
            for step in pipeline:
                next_buckets = []
                for bucket in buckets:
                    next_buckets.extend(split_bucket(bucket, step))
                buckets = next_buckets

            rank = 1
            for bucket in buckets:
                for item in bucket:
                    await self.db.execute(
                        text("""
                            INSERT INTO standings
                                (organization_id, tournament_id, stage_id, group_id, team_id, played, won, drawn, lost,
                                 goals_for, goals_against, goal_difference, points, fair_play_points, rank)
                            VALUES (:organization_id, :tournament_id, :stage_id, :group_id, :team_id, :played, :won,
                                    :drawn, :lost, :goals_for, :goals_against, :goal_difference, :points,
                                    :fair_play_points, :rank)
                        """),
                        {
                            "organization_id": str(context.organization_id),
                            "tournament_id": str(tournament_id),
                            "stage_id": str(stage_id),
                            "rank": rank,
                            **item,
                        },
                    )
                    rank += 1
