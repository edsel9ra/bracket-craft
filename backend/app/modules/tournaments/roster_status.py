"""Effective roster limits, active roster counting and size violations (RF-045, RF-050).

Everything here is shared by the three blocking surfaces of the spec: enrolling
a team in a stage, creating a team with a target stage and opening a match (its
first segment). The functions are pure —no clock, no session and no network—
except :func:`count_active_roster_players_by_team`, which reads the active
roster rows of the given teams.

``0`` (or an absent key) means **no limit**, so a stored configuration written
before the keys existed keeps the previous behaviour. The 409 detail names the
team and shows the minimum, the maximum and the active count; it never includes
personal data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Aditive ``code`` of the 409 (plan §4.2 point 5); ``detail`` stays a string.
ROSTER_SIZE_OUT_OF_RANGE = "ROSTER_SIZE_OUT_OF_RANGE"


class RosterSizeOutOfRange(HTTPException):
    """409 de dominio con el ``code`` aditivo y el ``detail`` ya construido.

    El manejador único de ``app/main.py`` añade ``code`` al cuerpo; las rutas de
    las tres superficies de bloqueo solo lanzan esta excepción, de modo que el
    formato del error no se duplica.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)
        self.code = ROSTER_SIZE_OUT_OF_RANGE

STATE_OK = "ok"
STATE_BELOW = "below"
STATE_ABOVE = "above"

# At most ten teams are listed in the detail; the total is always reported.
DETAIL_LIMIT = 10
NO_LIMIT_LABEL = "sin límite"
DETAIL_HEADER = "Plantilla fuera de rango: "


@dataclass(frozen=True)
class RosterLimits:
    """Effective roster limits of a version; ``0`` means "no limit"."""

    min: int = 0
    max: int = 0

    @property
    def has_limits(self) -> bool:
        """Return whether any side of the range is configured."""

        return bool(self.min or self.max)


@dataclass(frozen=True)
class RosterTeamCount:
    """Active roster size of one team, with the name used in the detail."""

    team_id: UUID
    team_name: str
    count: int


def _limit_value(raw: Any) -> int:
    """Normalize one configured limit: absent, ``None`` or ``0`` mean no limit.

    The range is validated when the rules are saved (RF-044), so this only
    defends the callers against a negative or non-integer value.
    """

    if raw is None or isinstance(raw, bool):
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _read(config: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(config, Mapping):
        return config.get(key)
    return getattr(config, key, None)


def effective_roster_limits(config: Mapping[str, Any] | Any) -> RosterLimits:
    """Resolve the effective limits of a rules configuration (RF-044, RF-045)."""

    return RosterLimits(
        min=_limit_value(_read(config, "min_players_per_team")),
        max=_limit_value(_read(config, "max_players_per_team")),
    )


def roster_size_state(count: int, limits: RosterLimits) -> str:
    """Return ``ok``, ``below`` or ``above`` for one team's active roster (RF-046)."""

    if limits.min > 0 and count < limits.min:
        return STATE_BELOW
    if limits.max > 0 and count > limits.max:
        return STATE_ABOVE
    return STATE_OK


def roster_violations(
    rows: Sequence[RosterTeamCount], limits: RosterLimits
) -> list[RosterTeamCount]:
    """Return the rows out of range, sorted by team name and identifier."""

    return sorted(
        (row for row in rows if roster_size_state(row.count, limits) != STATE_OK),
        key=_detail_sort_key,
    )


def _detail_sort_key(row: RosterTeamCount) -> tuple[str, str]:
    return (row.team_name, str(row.team_id))


def roster_rows_for_new_teams(
    teams: Sequence[tuple[UUID, str]],
) -> list[RosterTeamCount]:
    """Rows for teams that do not exist yet: a new team has an empty roster.

    ``POST /teams`` and ``POST /teams/bulk`` with ``stage_id`` create the team
    and enrol it in the same transaction, so the size check runs before the
    insert with a count of zero (RF-045, BX-1). The caller passes the
    identifier it is about to write so the detail keeps its deterministic
    order by name and identifier.
    """

    return [
        RosterTeamCount(team_id=team_id, team_name=name, count=0)
        for team_id, name in teams
    ]


def _limit_label(value: int) -> str:
    return str(value) if value > 0 else NO_LIMIT_LABEL


def _describe_row(row: RosterTeamCount, limits: RosterLimits) -> str:
    players = "jugador activo" if row.count == 1 else "jugadores activos"
    return (
        f"«{row.team_name}»: {row.count} {players} "
        f"(mínimo: {_limit_label(limits.min)}, "
        f"máximo: {_limit_label(limits.max)})"
    )


def describe_roster_violations(
    rows: Sequence[RosterTeamCount], limits: RosterLimits
) -> str:
    """Render the deterministic ``detail`` of the 409 (RF-045, RF-050).

    Every team is listed when there are at most :data:`DETAIL_LIMIT` of them;
    otherwise the first ten by team name —the identifier breaks ties— plus the
    total. An empty string means no team is out of range.
    """

    violations = roster_violations(rows, limits)
    if not violations:
        return ""

    visible = violations[:DETAIL_LIMIT]
    detail = DETAIL_HEADER + "; ".join(
        _describe_row(row, limits) for row in visible
    ) + "."
    if len(violations) > DETAIL_LIMIT:
        detail += (
            f" Se muestran los {DETAIL_LIMIT} primeros; "
            f"{len(violations)} equipos fuera de rango en total."
        )
    return detail


async def count_active_roster_players_by_team(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    team_ids: Sequence[UUID],
) -> list[RosterTeamCount]:
    """Count the active roster rows of the given teams in one tournament.

    The caller must have opened the transaction and set ``set_rls_context`` with
    the organization and user before calling: the query also filters by
    ``organization_id`` and ``tournament_id``. Teams without active players come
    back with ``count = 0``; teams that do not belong to the organization (or are
    hidden by RLS) are simply absent.
    """

    if not team_ids:
        return []

    result = await db.execute(
        text("""
            SELECT t.id AS team_id, t.name AS team_name, count(r.id) AS active_count
            FROM teams t
            LEFT JOIN rosters r
              ON r.team_id = t.id
             AND r.organization_id = t.organization_id
             AND r.tournament_id = :tournament_id
             AND r.is_active = TRUE
            WHERE t.organization_id = :organization_id
              AND t.id = ANY(CAST(:team_ids AS UUID[]))
            GROUP BY t.id, t.name
            ORDER BY t.name, t.id
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "team_ids": [str(team_id) for team_id in team_ids],
        },
    )
    return [
        RosterTeamCount(
            team_id=row["team_id"],
            team_name=row["team_name"],
            count=int(row["active_count"]),
        )
        for row in result.mappings().all()
    ]
