"""Límite de enfrentamientos manuales por formato de fase (RF-009, R26).

El desempate directo solo es calculable con uno o dos enfrentamientos por pareja;
con más, deja de aplicarse. Por eso las altas manuales de partidos en fases que
producen clasificación se limitan según el **formato persistido** de la fase
(``stages.schedule_legs``), nunca según la configuración de desempates:

- liga (``round_robin``) y grupos (``custom_group``): un enfrentamiento por
  pareja, o dos si el calendario se generó a ida y vuelta;
- suiza (``swiss``): siempre uno, porque el formato no tiene vueltas;
- eliminatorias (``single_elimination``/``double_elimination``): fuera de la
  regla, porque admiten repeticiones legítimas (por ejemplo, la repetición de la
  gran final).

Limitación histórica: la migración 023 añadió ``schedule_legs`` sin *backfill*,
así que una liga antigua de dos vueltas que aún no se haya regenerado conserva
el valor por defecto (uno) y su máximo efectivo es uno hasta que se regenere el
calendario. Los calendarios generados no se validan con esta regla: solo las
altas manuales.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ELIMINATION_STAGE_TYPES = frozenset({"single_elimination", "double_elimination"})
LEGGED_STAGE_TYPES = frozenset({"round_robin", "custom_group"})
SWISS_STAGE_TYPE = "swiss"


def max_meetings_per_pair(stage_type: str, schedule_legs: int | None) -> int | None:
    """Return the maximum meetings per pair for the stage format.

    ``None`` means the stage is out of the rule (elimination brackets). Any
    unknown format keeps the safest default: one meeting per pair.
    """

    if stage_type in ELIMINATION_STAGE_TYPES:
        return None
    if stage_type == SWISS_STAGE_TYPE:
        return 1
    if stage_type in LEGGED_STAGE_TYPES and schedule_legs == 2:
        return 2
    return 1


def pair_limit_detail(
    *,
    stage_name: str,
    home_team_name: str,
    away_team_name: str,
    max_meetings: int,
) -> str:
    """Compose the 409 message naming the stage, the pair and the limit."""

    noun = "enfrentamiento" if max_meetings == 1 else "enfrentamientos"
    return (
        f"La fase «{stage_name}» ya alcanzó el máximo de {max_meetings} "
        f"{noun} por pareja entre «{home_team_name}» y «{away_team_name}»"
    )


async def count_pair_meetings(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    group_id: UUID | None,
    home_team_id: UUID,
    away_team_id: UUID,
) -> int:
    """Count the existing meetings of a pair in the same stage and group.

    Only manual and generated matches of the same stage (and group, when the
    stage uses groups) count. Cancelled matches and matches with an empty side
    are not meetings of the pair. The pair is order-insensitive so a two-leg
    calendar with the home and away swapped is counted as the same pairing.
    """

    result = await db.execute(
        text("""
            SELECT count(*) AS meetings
            FROM matches
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND tournament_version_id = :version_id
              AND stage_id = :stage_id
              AND group_id IS NOT DISTINCT FROM CAST(:group_id AS UUID)
              AND status <> 'cancelled'
              AND home_team_id IS NOT NULL
              AND away_team_id IS NOT NULL
              AND (
                    (home_team_id = :home_team_id AND away_team_id = :away_team_id)
                 OR (home_team_id = :away_team_id AND away_team_id = :home_team_id)
              )
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "group_id": str(group_id) if group_id else None,
            "home_team_id": str(home_team_id),
            "away_team_id": str(away_team_id),
        },
    )
    return int(result.scalar_one())
