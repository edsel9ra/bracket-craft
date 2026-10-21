import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.locking import lock_stage_and_version
from app.core.permissions import require_administrative_resolution, require_permission
from app.core.tenancy import AuthContext
from app.modules.advancement.service import AdvancementService
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.rule_contract import requires_decisive_winner
from app.modules.rules_engine.defaults import DEFAULT_REGULAR_TIME_MINUTES
from app.modules.rules_engine.engine import (
    compute_match_outcome,
    effective_stage_rules,
    effective_substitutions,
    evaluate_suspensions,
)
from app.modules.rules_engine.substitutions import (
    RED_CARD,
    SUBSTITUTION,
    MatchEvent,
    OnFieldState,
    RosterEntry,
    Segment,
    SegmentBalance,
    SubstitutionError,
    SubstitutionErrorCode,
    SubstitutionLimits,
    TeamUsage,
    apply_red_card,
    apply_substitution,
    build_on_field,
    canonical_event_order,
    remaining_limits,
    segment_balances,
    team_usage,
    validate_player_on_field,
    validate_roster_minutes,
    validate_substitution,
)


# Structural request limits (RF-043): they are form limits, never a sporting
# rule, so they are not named in business errors nor used as the match maximum.
STRUCTURAL_MAX_ADDED_MINUTE = 30

RESOLUTIONS_WITH_EXTRA_TIME = frozenset({"extra_time", "penalties"})

NO_LINEUP_NOTICE = "No hay planilla para determinar el estado en campo"
NO_LIMITS_NOTICE = "El equipo no tiene sustituciones ni ventanas disponibles"


def effective_match_minutes(
    config: Mapping[str, Any] | None,
    stage_id: UUID | str | None,
) -> dict[str, Any]:
    """Effective minutes of a stage, resolved key by key (RF-040).

    ``stage_defaults`` is merged over the 90/120 read defaults and the stage
    override is then applied on top, so an old config without minutes and a
    partial override both resolve to a complete pair without rewriting it.
    """

    effective = effective_stage_rules(config or {}, stage_id)
    regular = int(effective["regular_time_minutes"])
    extra_raw = effective.get("extra_time_minutes")
    extra = int(extra_raw) if extra_raw is not None else None
    extra_time_enabled = bool(effective.get("extra_time_enabled"))
    return {
        "regular_time_minutes": regular,
        "extra_time_minutes": extra,
        "extra_time_enabled": extra_time_enabled,
        "max_minute": extra if extra_time_enabled and extra is not None else regular,
        "added_minute_max": STRUCTURAL_MAX_ADDED_MINUTE,
    }


def maximum_minute_for_resolution(
    minutes: Mapping[str, Any],
    resolution_type: str | None,
) -> int:
    """Effective maximum of a resolution (RF-042)."""

    if resolution_type in RESOLUTIONS_WITH_EXTRA_TIME and minutes.get("extra_time_enabled"):
        extra = minutes.get("extra_time_minutes")
        if extra is not None:
            return int(extra)
    return int(minutes["regular_time_minutes"])


def validate_event_minute(
    minute: int,
    added_minute: int,
    *,
    maximum: int,
) -> None:
    """Apply the single business cap over ``minute + added_minute`` (RF-042).

    The discount window is only opened on the final minute: before it, the sum
    of both values cannot pass the maximum. The structural ``added_minute``
    limit (30) is enforced by the request schema as a 422.
    """

    if minute > maximum:
        raise ValueError(
            f"El evento excede el máximo de {maximum} minutos de la resolución"
        )
    if minute < maximum and minute + added_minute > maximum:
        raise ValueError(
            f"El evento excede el máximo de {maximum} minutos de la resolución"
        )
    if added_minute > STRUCTURAL_MAX_ADDED_MINUTE:
        raise ValueError(
            "Los minutos añadidos superan el tope estructural de "
            f"{STRUCTURAL_MAX_ADDED_MINUTE}"
        )


@dataclass(frozen=True)
class ReportState:
    """Result of replaying a report with the pure substitution engine."""

    limits: SubstitutionLimits
    states: Mapping[UUID, OnFieldState]
    usage: Mapping[UUID, TeamUsage]


def roster_entries(rows: Iterable[Mapping[str, Any] | RosterEntry]) -> tuple[RosterEntry, ...]:
    """Normalise ``match_rosters`` rows into engine entries (single source)."""

    entries: list[RosterEntry] = []
    for row in rows:
        if isinstance(row, RosterEntry):
            entries.append(row)
            continue
        entries.append(
            RosterEntry(
                player_id=_as_uuid(row["player_id"]),
                team_id=_as_uuid(row["team_id"]),
                role=str(row.get("role") or "starter"),
                is_valid=bool(row.get("is_valid", True)),
                entered_minute=row.get("entered_minute"),
                left_minute=row.get("left_minute"),
            )
        )
    return tuple(entries)


def replay_report_state(
    rosters: Iterable[Mapping[str, Any] | RosterEntry],
    events: Sequence[MatchEvent],
    team_ids: Iterable[UUID],
    limits: SubstitutionLimits,
) -> ReportState:
    """Replay a report in canonical order, validating it before any write.

    The initial XI comes from ``match_rosters`` and every substitution and red
    card is applied in ``(minute, added_minute, acta index)`` order, so the
    derived state is deterministic and exactly the one ``build_on_field``
    produces for the same events. Every business violation raises
    :class:`SubstitutionError`, a ``ValueError`` the closing route maps to 409.

    Limits are per team and per match. Two changes of the same team in the same
    segment and minute share one window, so an already consumed window never
    counts twice.
    """

    entries = roster_entries(rosters)
    teams = tuple(dict.fromkeys(_as_uuid(team_id) for team_id in team_ids))
    states = {team_id: build_on_field(entries, [], team_id) for team_id in teams}
    usage = {team_id: TeamUsage() for team_id in teams}

    for event in canonical_event_order(events):
        state = states.get(event.team_id)
        if state is None:
            raise SubstitutionError(
                SubstitutionErrorCode.TEAM_MISMATCH,
                "El evento pertenece a un equipo que no participa en el partido",
            )
        current = usage[event.team_id]

        if event.event_type == SUBSTITUTION:
            if not event.is_substitution_with_pair:
                # Legacy event: informational, never changes the state.
                continue
            window = (event.segment_id, event.minute, event.added_minute)
            check = current
            if window in current.windows:
                # The window is already consumed: reuse it without counting it
                # again against ``max_windows``.
                check = TeamUsage(
                    substitutions=current.substitutions,
                    windows=tuple(item for item in current.windows if item != window),
                )
            validate_substitution(
                state,
                limits,
                check,
                event.player_out_id,
                event.player_in_id,
                team_id=event.team_id,
            )
            states[event.team_id] = apply_substitution(
                state,
                event.player_out_id,
                event.player_in_id,
                event.effective_minute,
            )
            usage[event.team_id] = current.merge(TeamUsage(1, (window,)))
            continue

        if event.player_id is None:
            continue
        if not state.is_in_roster(event.player_id):
            raise SubstitutionError(
                SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER,
                f"El jugador {event.player_id} no está en la plantilla del equipo",
            )
        validate_player_on_field(state, event.player_id, event.minute, event.added_minute)
        if event.event_type == RED_CARD:
            states[event.team_id] = apply_red_card(
                state, event.player_id, event.effective_minute
            )

    for entry in entries:
        state = states.get(entry.team_id)
        if state is None:
            continue
        validate_roster_minutes(
            state,
            entry.player_id,
            entered_minute=entry.entered_minute,
            left_minute=entry.left_minute,
        )

    return ReportState(limits=limits, states=states, usage=usage)


async def ensure_segment_team_state(
    db: AsyncSession,
    organization_id: UUID,
    match_id: UUID,
    segment_id: UUID,
    team_ids: Iterable[UUID],
    limits: SubstitutionLimits,
) -> None:
    """Create the projection row of a new segment for every present team."""

    statement = text("""
        INSERT INTO match_segment_team_state
            (organization_id, match_id, segment_id, team_id,
             substitutions_remaining, substitution_windows_remaining)
        VALUES
            (:organization_id, :match_id, :segment_id, :team_id,
             :substitutions_remaining, :substitution_windows_remaining)
        ON CONFLICT (segment_id, team_id) DO NOTHING
    """)
    for team_id in team_ids:
        await db.execute(
            statement,
            {
                "organization_id": str(organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "team_id": str(team_id),
                "substitutions_remaining": limits.max_per_team,
                "substitution_windows_remaining": limits.max_windows,
            },
        )


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class CloseMatchReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute(self, context: AuthContext, match_id: UUID, dto: CloseMatchReportDTO) -> dict[str, Any]:
        async with self.db.begin():
            await set_rls_context(self.db, context.organization_id, context.user_id)
            identity = await self._load_match_identity(context, match_id)
            await lock_stage_and_version(
                self.db,
                context.organization_id,
                identity["tournament_id"],
                identity["stage_id"],
            )
            # Pre-lock the source and every destination (including GF2 for a
            # GF1) in ascending id order before any segment or player write.
            advancement = AdvancementService(self.db)
            await advancement.lock_targets(context, match_id, identity)
            match = await self._lock_match(context, match_id)
            try:
                if dto.resolution_type == "administrative":
                    await require_administrative_resolution(
                        self.db,
                        context,
                        match_id,
                    )
                else:
                    await require_permission(
                        self.db,
                        context,
                        "CLOSE_MATCH_REPORT",
                        match_id,
                    )
            except PermissionError as exc:
                raise PermissionError(str(exc)) from exc

            if match["status"] in {"finished", "cancelled", "administrative_resolution", "suspended"}:
                raise ValueError(f"El estado {match['status']} no admite cierre normal")
            if match["version_status"] != "published":
                raise ValueError("La versión del torneo no está publicada")
            if match["home_team_id"] is None or match["away_team_id"] is None:
                raise ValueError("El partido debe tener dos equipos participantes")

            active_segment_result = await self.db.execute(
                text("""
                    SELECT id, minute_start
                    FROM match_segments
                    WHERE match_id = :match_id
                      AND organization_id = :organization_id
                      AND status = 'active'
                    FOR UPDATE
                """),
                {"match_id": str(match_id), "organization_id": str(context.organization_id)},
            )
            active_segment_row = active_segment_result.mappings().one_or_none()
            active_segment = active_segment_row["id"] if active_segment_row else None
            if active_segment is None:
                raise ValueError("El partido necesita un segmento activo antes de cerrar el acta")

            rosters = await self._load_match_rosters(context, match_id)
            player_ids = sorted({row["player_id"] for row in rosters}, key=str)
            for player_id in player_ids:
                await self._lock_player(match["tournament_id"], player_id)
            self._validate_rosters(match, rosters)
            segments = await self._load_match_segments(context, match_id)
            minutes = effective_match_minutes(match["rules_config"], match["stage_id"])
            self._validate_segments(dto, segments, minutes)
            limits = SubstitutionLimits.from_config(
                effective_substitutions(match["rules_config"])
            )
            self._validate_substitutions(dto, match, rosters, limits)
            self._validate_event_score_consistency(
                dto,
                match["home_team_id"],
                match["away_team_id"],
                regular_time_minutes=minutes["regular_time_minutes"],
            )
            await self._validate_suspensions(context, match["tournament_id"], player_ids)

            persisted_events = await self._persist_events(context, match, dto, rosters, segments)
            outcome = compute_match_outcome(
                match["rules_config"],
                persisted_events,
                dto.resolution_type,
                match["home_team_id"],
                match["away_team_id"],
                dto.home_score_regular,
                dto.away_score_regular,
                dto.home_score,
                dto.away_score,
                dto.home_penalties,
                dto.away_penalties,
                dto.winner_team_id,
            )
            if requires_decisive_winner(match.get("bracket_code")) and outcome.winner_team_id is None:
                raise ValueError("La gran final de doble eliminación debe tener un ganador")

            target_status = "administrative_resolution" if dto.resolution_type == "administrative" else "finished"
            await self.db.execute(
                text("""
                    UPDATE matches
                    SET home_score_regular = :home_score_regular,
                        away_score_regular = :away_score_regular,
                        home_score = :home_score,
                        away_score = :away_score,
                        home_penalties = :home_penalties,
                        away_penalties = :away_penalties,
                        winner_team_id = :winner_team_id,
                        status = :status,
                        resolution_type = :resolution_type,
                        resolution_reason = :resolution_reason,
                        result_confirmed = TRUE,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :match_id AND organization_id = :organization_id
                """),
                {
                    "home_score_regular": dto.home_score_regular,
                    "away_score_regular": dto.away_score_regular,
                    "home_score": outcome.home_score,
                    "away_score": outcome.away_score,
                    "home_penalties": outcome.home_penalties,
                    "away_penalties": outcome.away_penalties,
                    "winner_team_id": str(outcome.winner_team_id) if outcome.winner_team_id else None,
                    "status": target_status,
                    "resolution_type": dto.resolution_type,
                    "resolution_reason": dto.reason if dto.resolution_type == "administrative" else None,
                    "match_id": str(match_id),
                    "organization_id": str(context.organization_id),
                },
            )
            await self.db.execute(
                text("""
                    UPDATE match_segments
                    SET status = 'completed',
                        minute_end = COALESCE(minute_end, :minute_end)
                    WHERE id = :segment_id AND organization_id = :organization_id
                """),
                {
                    "segment_id": str(active_segment),
                    "organization_id": str(context.organization_id),
                    "minute_end": max(
                        [
                            active_segment_row["minute_start"],
                            *(event.minute for event in dto.events),
                        ]
                    ),
                },
            )
            await self._rewrite_segment_team_state(context, match, segments, limits)

            history = await self._load_discipline_history(context, match)
            suspensions = evaluate_suspensions(
                match["rules_config"], persisted_events, history
            )
            await self._serve_suspensions(context, match)
            await self._insert_suspensions(context, match, suspensions)
            await self._recalculate_standings(context, match)
            await self._advance_bracket(context, match_id, match, outcome)

            audit_payload = {
                "previous_status": match["status"],
                "final_status": target_status,
                "tournament_version_id": str(match["tournament_version_id"]),
                "outcome": outcome.__dict__,
                "event_ids": [str(event["id"]) for event in persisted_events],
                "suspensions": len(suspensions),
                "request": dto.model_dump(mode="json"),
            }
            audit_action = (
                "ADMINISTRATIVE_MATCH_RESOLUTION"
                if dto.resolution_type == "administrative"
                else "CLOSE_MATCH_REPORT"
            )
            await self.db.execute(
                text("""
                    INSERT INTO administrative_audit_logs
                        (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
                    VALUES (:organization_id, 'matches', :match_id, :action, CAST(:payload AS jsonb), :member_id)
                """),
                {
                    "organization_id": str(context.organization_id),
                    "match_id": str(match_id),
                    "action": audit_action,
                    "payload": json.dumps(audit_payload, default=str),
                    "member_id": str(context.organization_user_id),
                },
            )
            event_payload = json.dumps({"match_id": str(match_id), "tournament_id": str(match["tournament_id"])})
            for event_type in ("MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"):
                await self.db.execute(
                    text("""
                        INSERT INTO outbox_events (organization_id, event_type, payload)
                        VALUES (:organization_id, :event_type, CAST(:payload AS jsonb))
                    """),
                    {
                        "organization_id": str(context.organization_id),
                        "event_type": event_type,
                        "payload": event_payload,
                    },
                )

        return {
            "status": "success",
            "match_id": str(match_id),
            "home_score": outcome.home_score,
            "away_score": outcome.away_score,
            "winner_team_id": str(outcome.winner_team_id) if outcome.winner_team_id else None,
        }

    async def _load_match_identity(self, context: AuthContext, match_id: UUID) -> dict:
        """Read the match scope without locking, so the lock order can start at the stage."""

        result = await self.db.execute(
            text("""
                SELECT id, tournament_id, tournament_version_id, stage_id, bracket_code
                FROM matches
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise LookupError("Partido no encontrado")
        return dict(row)

    async def _lock_match(self, context: AuthContext, match_id: UUID):
        result = await self.db.execute(
            text("""
                SELECT m.id, m.tournament_id, m.tournament_version_id, m.matchday, m.match_date,
                       m.bracket_code,
                       m.status, m.stage_id, m.home_team_id, m.away_team_id,
                       tv.rules_config, tv.status AS version_status
                FROM matches m
                JOIN tournament_versions tv
                  ON tv.id = m.tournament_version_id
                 AND tv.organization_id = m.organization_id
                WHERE m.id = :match_id AND m.organization_id = :organization_id
                FOR UPDATE OF m
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise LookupError("Partido no encontrado")
        match = dict(row)
        rules_config = dict(match["rules_config"])
        stage_override = rules_config.get("stage_overrides", {}).get(str(match["stage_id"]), {})
        if stage_override:
            rules_config["stage_defaults"] = {
                **rules_config["stage_defaults"],
                **stage_override,
            }
            match["rules_config"] = rules_config
        return match

    async def _load_match_rosters(self, context: AuthContext, match_id: UUID):
        result = await self.db.execute(
            text("""
                SELECT mr.player_id, mr.team_id, mr.role, mr.is_valid,
                       mr.entered_minute, mr.left_minute,
                       r.valid_from, r.valid_to, r.eligible_from, r.is_active
                FROM match_rosters mr
                JOIN rosters r
                  ON r.id = mr.roster_id
                 AND r.organization_id = mr.organization_id
                WHERE mr.match_id = :match_id
                  AND mr.organization_id = :organization_id
                  AND mr.is_valid = TRUE
                ORDER BY mr.player_id
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        return result.mappings().all()

    def _validate_rosters(self, match, rosters) -> None:
        participants = {match["home_team_id"], match["away_team_id"]}
        roster_counts = {team_id: 0 for team_id in participants}
        for roster in rosters:
            if roster["team_id"] not in participants:
                raise ValueError("La planilla contiene un equipo que no participa en el partido")
            roster_counts[roster["team_id"]] += 1
            if not roster["is_active"]:
                raise ValueError(f"Roster inactivo para el jugador {roster['player_id']}")
            if match["match_date"] and roster["eligible_from"] > match["match_date"]:
                raise ValueError(f"Jugador {roster['player_id']} aún no es elegible")
            if match["match_date"] and roster["valid_to"] and roster["valid_to"] < match["match_date"]:
                raise ValueError(f"La inscripción del jugador {roster['player_id']} expiró")
        if any(count == 0 for count in roster_counts.values()):
            raise ValueError("La planilla debe incluir al menos un jugador de cada equipo")

    async def _load_match_segments(self, context: AuthContext, match_id: UUID):
        result = await self.db.execute(
            text("""
                SELECT id, segment_number, minute_start, minute_end, status
                FROM match_segments
                WHERE match_id = :match_id AND organization_id = :organization_id
                ORDER BY segment_number
            """),
            {"match_id": str(match_id), "organization_id": str(context.organization_id)},
        )
        return [dict(row) for row in result.mappings().all()]

    @staticmethod
    def _validate_segments(
        dto: CloseMatchReportDTO,
        segments: list[dict[str, Any]],
        minutes: Mapping[str, Any],
    ) -> None:
        if not segments:
            raise ValueError("El partido necesita al menos un segmento")

        maximum_minute = maximum_minute_for_resolution(minutes, dto.resolution_type)
        segments_by_id = {segment["id"]: segment for segment in segments}
        previous_end: int | None = None
        for segment in segments:
            minute_start = segment["minute_start"]
            minute_end = segment["minute_end"]
            if previous_end is not None and minute_start < previous_end:
                raise ValueError("Los segmentos del partido tienen tiempos incompatibles")
            if minute_start > maximum_minute or (minute_end is not None and minute_end > maximum_minute):
                raise ValueError(
                    f"Un segmento excede el máximo de {maximum_minute} minutos de la resolución"
                )
            if minute_end is not None:
                previous_end = minute_end
            else:
                previous_end = minute_start

        for event in dto.events:
            segment = segments_by_id.get(event.segment_id)
            if segment is None:
                raise ValueError("El evento pertenece a un segmento inexistente")
            if segment["status"] not in {"active", "completed"}:
                raise ValueError("No se pueden registrar eventos en un segmento interrumpido")
            if event.minute < segment["minute_start"]:
                raise ValueError("El evento no puede ocurrir antes del inicio de su segmento")
            if segment["minute_end"] is not None and event.minute > segment["minute_end"]:
                raise ValueError("El evento no puede ocurrir después del final de su segmento")
            validate_event_minute(
                event.minute,
                event.added_minute,
                maximum=maximum_minute,
            )

    @staticmethod
    def _validate_substitutions(
        dto: CloseMatchReportDTO,
        match: Mapping[str, Any],
        rosters: Iterable[Mapping[str, Any]],
        limits: SubstitutionLimits,
    ) -> None:
        """Validate the complete report with the pure engine before any write.

        No event, counter, score, standings or outbox row is touched when a
        substitution breaks a rule (RF-017). Walkover and administrative
        resolutions do not admit events, so they are not replayed.
        """

        if dto.resolution_type in {"walkover", "administrative"}:
            return
        replay_report_state(
            rosters,
            [
                MatchEvent.from_mapping(event.model_dump(), index=index)
                for index, event in enumerate(dto.events)
            ],
            (match["home_team_id"], match["away_team_id"]),
            limits,
        )

    async def _rewrite_segment_team_state(
        self,
        context: AuthContext,
        match: Mapping[str, Any],
        segments: Sequence[Mapping[str, Any]],
        limits: SubstitutionLimits,
    ) -> tuple[SegmentBalance, ...]:
        """Rewrite every segment/team row with the balance after that segment.

        The balance is always recalculated from the persisted substitution
        events, never decremented, and the rows are ordered by
        ``match_segments.segment_number`` (never by minute) so an earlier
        segment reflects only the consumption accumulated up to it (RF-016).
        """

        result = await self.db.execute(
            text("""
                SELECT id, event_type, team_id, minute, added_minute, player_id,
                       player_out_id, player_in_id, segment_id
                FROM match_events
                WHERE organization_id = :organization_id
                  AND match_id = :match_id
                  AND event_type = 'substitution'
                ORDER BY minute, added_minute, created_at, id
            """),
            {
                "organization_id": str(context.organization_id),
                "match_id": str(match["id"]),
            },
        )
        events = [
            MatchEvent.from_mapping(row, index=index)
            for index, row in enumerate(result.mappings().all())
        ]
        segment_rows = [
            Segment(id=_as_uuid(segment["id"]), segment_number=segment["segment_number"])
            for segment in segments
        ]
        balances = segment_balances(
            segment_rows,
            events,
            (match["home_team_id"], match["away_team_id"]),
            limits,
        )
        statement = text("""
            INSERT INTO match_segment_team_state
                (organization_id, match_id, segment_id, team_id,
                 substitutions_remaining, substitution_windows_remaining)
            VALUES
                (:organization_id, :match_id, :segment_id, :team_id,
                 :substitutions_remaining, :substitution_windows_remaining)
            ON CONFLICT (segment_id, team_id) DO UPDATE
            SET substitutions_remaining = EXCLUDED.substitutions_remaining,
                substitution_windows_remaining = EXCLUDED.substitution_windows_remaining
        """)
        for balance in balances:
            await self.db.execute(
                statement,
                {
                    "organization_id": str(context.organization_id),
                    "match_id": str(match["id"]),
                    "segment_id": str(balance.segment_id),
                    "team_id": str(balance.team_id),
                    "substitutions_remaining": balance.substitutions_remaining,
                    "substitution_windows_remaining": balance.substitution_windows_remaining,
                },
            )
        return balances

    @staticmethod
    def _validate_event_score_consistency(
        dto: CloseMatchReportDTO,
        home_team_id: UUID,
        away_team_id: UUID,
        regular_time_minutes: int = DEFAULT_REGULAR_TIME_MINUTES,
    ) -> None:
        if dto.resolution_type in {"walkover", "administrative"}:
            return

        goal_events = [
            event
            for event in dto.events
            if event.event_type in {"goal", "own_goal", "penalty_goal"}
        ]

        regular_goals: dict[UUID, int] = {}
        extra_time_goals: dict[UUID, int] = {}
        for event in goal_events:
            credited_team = event.beneficiary_team_id if event.event_type == "own_goal" else event.team_id
            if credited_team is None:
                continue
            target = regular_goals if event.minute <= regular_time_minutes else extra_time_goals
            target[credited_team] = target.get(credited_team, 0) + 1

        regular_home = regular_goals.get(home_team_id, 0)
        regular_away = regular_goals.get(away_team_id, 0)
        if (regular_home, regular_away) != (dto.home_score_regular, dto.away_score_regular):
            raise ValueError("El marcador reglamentario no coincide con los eventos de gol")

        if dto.resolution_type == "regular":
            if extra_time_goals:
                raise ValueError("Una resolución regular no permite goles después del minuto reglamentario")
            return

        if dto.resolution_type in {"extra_time", "penalties"}:
            final_home = regular_home + extra_time_goals.get(home_team_id, 0)
            final_away = regular_away + extra_time_goals.get(away_team_id, 0)
            if dto.home_score != final_home or dto.away_score != final_away:
                raise ValueError("El marcador final no coincide con los eventos de gol")

    async def _lock_player(self, tournament_id: UUID, player_id: UUID) -> None:
        raw = hashlib.sha256(f"{tournament_id}:{player_id}".encode("utf-8")).digest()[:8]
        lock_key = int.from_bytes(raw, byteorder="big", signed=True)
        await self.db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    async def _validate_suspensions(self, context: AuthContext, tournament_id: UUID, player_ids: list[UUID]) -> None:
        if not player_ids:
            return
        result = await self.db.execute(
            text("""
                SELECT ps.player_id
                FROM player_suspensions ps
                LEFT JOIN player_suspension_serves pss
                  ON pss.suspension_id = ps.id
                 AND pss.is_voided = FALSE
                WHERE ps.organization_id = :organization_id
                  AND ps.player_id = ANY(CAST(:player_ids AS uuid[]))
                  AND ps.status = 'active'
                  AND (ps.scope_type = 'organization' OR ps.source_tournament_id = :tournament_id)
                GROUP BY ps.id, ps.player_id, ps.matches_suspended
                HAVING COUNT(pss.id) < ps.matches_suspended
            """),
            {
                "organization_id": str(context.organization_id),
                "player_ids": player_ids,
                "tournament_id": str(tournament_id),
            },
        )
        if result.first() is not None:
            raise ValueError("La planilla contiene un jugador suspendido")

    async def _persist_events(self, context, match, dto, rosters, segments) -> list[dict[str, Any]]:
        match_id = match["id"]
        valid_player_ids = {row["player_id"] for row in rosters}
        participants = {match["home_team_id"], match["away_team_id"]}
        segment_statuses = {row["id"]: row["status"] for row in segments}
        segments_by_id = {row["id"]: row for row in segments}
        roster_teams = {row["player_id"]: row["team_id"] for row in rosters}
        roster_by_player = {row["player_id"]: row for row in rosters}
        persisted: list[dict[str, Any]] = []
        seen_client_event_ids: set[str] = set()
        for event in dto.events:
            if event.client_event_id in seen_client_event_ids:
                raise ValueError("No se permiten client_event_id duplicados en la misma acta")
            seen_client_event_ids.add(event.client_event_id)
            if dto.resolution_type in {"walkover", "administrative"}:
                raise ValueError("Esta resolución no permite eventos individuales")
            if event.player_id not in valid_player_ids:
                raise ValueError(f"El jugador {event.player_id} no está en la planilla")
            if segment_statuses.get(event.segment_id) not in {"active", "completed"}:
                raise ValueError("No se pueden registrar eventos en un segmento interrumpido")
            segment = segments_by_id[event.segment_id]
            if event.minute < segment["minute_start"] or (
                segment["minute_end"] is not None and event.minute > segment["minute_end"]
            ):
                raise ValueError("El evento está fuera del intervalo de su segmento")
            if event.team_id not in participants:
                raise ValueError("El evento pertenece a un equipo que no participa en el partido")
            if roster_teams[event.player_id] != event.team_id:
                raise ValueError("El jugador del evento no pertenece al equipo indicado")
            roster = roster_by_player[event.player_id]
            if roster["entered_minute"] is not None and event.minute < roster["entered_minute"]:
                raise ValueError("El evento ocurre antes de la entrada del jugador")
            if roster["left_minute"] is not None and event.minute > roster["left_minute"]:
                raise ValueError("El evento ocurre después de la salida del jugador")
            if event.beneficiary_team_id is not None and event.beneficiary_team_id not in participants:
                raise ValueError("El equipo beneficiario no participa en el partido")

            existing_result = await self.db.execute(
                text("""
                    SELECT id, event_type, team_id, beneficiary_team_id, player_id,
                           player_out_id, player_in_id, minute, added_minute, segment_id
                    FROM match_events
                    WHERE organization_id = :organization_id
                      AND match_id = :match_id
                      AND client_event_id = :client_event_id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "match_id": str(match_id),
                    "client_event_id": event.client_event_id,
                },
            )
            existing = existing_result.mappings().one_or_none()
            if existing:
                if any(existing[key] != event_value for key, event_value in {
                    "event_type": event.event_type,
                    "team_id": event.team_id,
                    "beneficiary_team_id": event.beneficiary_team_id,
                    "player_id": event.player_id,
                    "player_out_id": event.player_out_id,
                    "player_in_id": event.player_in_id,
                    "minute": event.minute,
                    "added_minute": event.added_minute,
                    "segment_id": event.segment_id,
                }.items()):
                    raise ValueError(f"El evento {event.client_event_id} es inmutable")
                persisted.append(dict(existing))
                continue

            result = await self.db.execute(
                text("""
                    INSERT INTO match_events
                        (organization_id, match_id, segment_id, team_id, beneficiary_team_id, player_id,
                         player_out_id, player_in_id,
                         event_type, minute, added_minute, client_event_id, metadata)
                    VALUES (:organization_id, :match_id, :segment_id, :team_id, :beneficiary_team_id, :player_id,
                            :player_out_id, :player_in_id,
                            :event_type, :minute, :added_minute, :client_event_id, CAST(:metadata AS jsonb))
                    RETURNING id, event_type, team_id, beneficiary_team_id, player_id,
                              player_out_id, player_in_id, minute, added_minute, segment_id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "match_id": str(match_id),
                    "segment_id": str(event.segment_id),
                    "team_id": str(event.team_id),
                    "beneficiary_team_id": str(event.beneficiary_team_id) if event.beneficiary_team_id else None,
                    "player_id": str(event.player_id),
                    "player_out_id": str(event.player_out_id) if event.player_out_id else None,
                    "player_in_id": str(event.player_in_id) if event.player_in_id else None,
                    "event_type": event.event_type,
                    "minute": event.minute,
                    "added_minute": event.added_minute,
                    "client_event_id": event.client_event_id,
                    "metadata": json.dumps(event.metadata or {}),
                },
            )
            persisted.append(dict(result.mappings().one()))
        return persisted

    async def _load_discipline_history(self, context, match):
        result = await self.db.execute(
            text("""
                SELECT me.id, me.player_id, me.event_type, me.metadata
                FROM match_events me
                JOIN matches m ON m.id = me.match_id AND m.organization_id = me.organization_id
                WHERE me.organization_id = :organization_id
                  AND m.tournament_id = :tournament_id
                  AND (
                      CAST(:clear_yellows_on_stage_change AS BOOLEAN) = FALSE
                      OR (m.stage_id = :stage_id AND m.tournament_version_id = :version_id)
                  )
                  AND m.id <> :match_id
                   AND me.is_voided = FALSE
                  AND me.event_type IN ('yellow_card', 'red_card')
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(match["tournament_id"]),
                "stage_id": str(match["stage_id"]),
                "version_id": str(match["tournament_version_id"]),
                "match_id": str(match["id"]),
                "clear_yellows_on_stage_change": match["rules_config"]["discipline"]["clear_yellows_on_stage_change"],
            },
        )
        return [dict(row) for row in result.mappings().all()]

    async def _serve_suspensions(self, context, match) -> None:
        await self.db.execute(
            text("""
                INSERT INTO player_suspension_serves (organization_id, suspension_id, match_id)
                SELECT ps.organization_id, ps.id, :match_id
                FROM player_suspensions ps
                JOIN rosters r
                  ON r.player_id = ps.player_id
                 AND r.tournament_id = :tournament_id
                 AND r.organization_id = ps.organization_id
                 AND r.is_active = TRUE
                WHERE ps.organization_id = :organization_id
                  AND ps.status = 'active'
                  AND (ps.scope_type = 'organization' OR ps.source_tournament_id = :tournament_id)
                  AND r.team_id IN (CAST(:home_team_id AS UUID), CAST(:away_team_id AS UUID))
                  AND NOT EXISTS (
                      SELECT 1
                      FROM match_rosters mr
                      WHERE mr.organization_id = :organization_id
                        AND mr.match_id = :match_id
                        AND mr.player_id = ps.player_id
                        AND mr.is_valid = TRUE
                  )
                ON CONFLICT (suspension_id, match_id) DO NOTHING
            """),
            {
                "organization_id": str(context.organization_id),
                "tournament_id": str(match["tournament_id"]),
                "match_id": str(match["id"]),
                "home_team_id": str(match["home_team_id"]),
                "away_team_id": str(match["away_team_id"]),
            },
        )
        await self.db.execute(
            text("""
                UPDATE player_suspensions ps
                SET status = 'served'
                WHERE ps.organization_id = :organization_id
                  AND ps.status = 'active'
                  AND (
                      SELECT COUNT(*)
                      FROM player_suspension_serves pss
                      WHERE pss.organization_id = ps.organization_id
                        AND pss.suspension_id = ps.id
                        AND pss.is_voided = FALSE
                  ) >= ps.matches_suspended
            """),
            {"organization_id": str(context.organization_id)},
        )

    async def _insert_suspensions(self, context, match, suspensions):
        for suspension in suspensions:
            dedupe_key = f"{match['tournament_id']}:{suspension['player_id']}:{suspension['source_event_id']}:{suspension['reason']}"
            await self.db.execute(
                text("""
                    INSERT INTO player_suspensions
                        (organization_id, source_tournament_id, player_id, origin_match_id, source_event_id,
                         source_type, dedupe_key, scope_type, matches_suspended, reason)
                    VALUES (:organization_id, :tournament_id, :player_id, :match_id, :source_event_id,
                            'match_event', :dedupe_key, :scope_type, :matches_suspended, :reason)
                    ON CONFLICT (dedupe_key) DO NOTHING
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(match["tournament_id"]),
                    "player_id": str(suspension["player_id"]),
                    "match_id": str(match["id"]),
                    "source_event_id": str(suspension["source_event_id"]),
                    "dedupe_key": dedupe_key,
                    "scope_type": suspension["scope"],
                    "matches_suspended": suspension["matches_suspended"],
                    "reason": suspension["reason"],
                },
            )

    async def _recalculate_standings(self, context, match):
        from app.modules.standings.service import StandingsService

        await StandingsService(self.db).recalculate(context, match["tournament_id"], match["stage_id"])

    async def _advance_bracket(self, context, match_id, match, outcome):
        advancement = AdvancementService(self.db)
        await advancement.advance_from_match(context, match_id, match, outcome)
        await advancement.activate_double_elimination_reset(context, match, outcome)
