"""Single lock protocol for tournament structure and match operations.

The only valid order is::

    fase (stages) -> versión (tournament_versions) -> partido(s) (matches)
    -> segmentos -> jugadores

Every route that needs more than one level acquires them in that order. The
helpers below never set the RLS context: the caller does it inside its own
transaction before calling them.

Version-only exceptions (they have no existing stage to lock, or they only
change the version itself, and must never lock a stage after the version):

* ``update_version_rules``: only changes the draft version rules.
* ``_create_draft_version_record`` (clone): locks the tournament and reads the
  source version; the new stage rows are created inside the cloned version.
* ``publish_version``: only changes the version status.
* ``create_stage``: locks the version and then inserts a new stage; there is no
  pre-existing phase to lock first.

Reads (GET, lists, public projections) do not take these locks. Match-bound
operations that do not change structure (segments, lineups, officials) keep
their own match lock and do not cross the protocol.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_stage_and_version(
    db: AsyncSession,
    organization_id: UUID,
    tournament_id: UUID,
    stage_id: UUID,
) -> tuple[UUID, str]:
    """Lock the stage and then its version.

    Returns ``(tournament_version_id, version_status)``. Raises ``LookupError``
    when the stage or its version does not exist in the organization.
    """

    stage_result = await db.execute(
        text("""
            SELECT id, tournament_version_id
            FROM stages
            WHERE id = :stage_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
            FOR UPDATE
        """),
        {
            "stage_id": str(stage_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(organization_id),
        },
    )
    stage = stage_result.mappings().one_or_none()
    if stage is None:
        raise LookupError("Fase no encontrada")

    version_id = stage["tournament_version_id"]
    version_result = await db.execute(
        text("""
            SELECT status
            FROM tournament_versions
            WHERE id = :version_id
              AND tournament_id = :tournament_id
              AND organization_id = :organization_id
            FOR UPDATE
        """),
        {
            "version_id": str(version_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(organization_id),
        },
    )
    status = version_result.scalar_one_or_none()
    if status is None:
        raise LookupError("Versión no encontrada")

    return version_id, status


async def lock_version(
    db: AsyncSession,
    organization_id: UUID,
    version_id: UUID,
    *,
    tournament_id: UUID | None = None,
) -> str:
    """Lock a version row and return its status.

    Version-only helper used by the documented exceptions. When
    ``tournament_id`` is provided the version must also belong to that
    tournament.
    """

    result = await db.execute(
        text("""
            SELECT status
            FROM tournament_versions
            WHERE id = :version_id
              AND organization_id = :organization_id
              AND (
                  CAST(:tournament_id AS UUID) IS NULL
                  OR tournament_id = CAST(:tournament_id AS UUID)
              )
            FOR UPDATE
        """),
        {
            "version_id": str(version_id),
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id) if tournament_id else None,
        },
    )
    status = result.scalar_one_or_none()
    if status is None:
        raise LookupError("Versión no encontrada en el torneo")
    return status


async def lock_matches(
    db: AsyncSession,
    organization_id: UUID,
    match_ids,
) -> tuple[UUID, ...]:
    """Lock the given matches in ascending ``id`` order and return their ids.

    The ``ORDER BY id`` is what prevents two closures from taking the same set
    of matches in opposite orders. An unknown id aborts the operation.
    """

    unique_ids = tuple(dict.fromkeys(str(match_id) for match_id in match_ids))
    if not unique_ids:
        return ()

    result = await db.execute(
        text("""
            SELECT id
            FROM matches
            WHERE organization_id = :organization_id
              AND id = ANY(CAST(:match_ids AS uuid[]))
            ORDER BY id
            FOR UPDATE
        """),
        {
            "organization_id": str(organization_id),
            "match_ids": list(unique_ids),
        },
    )
    found = tuple(row["id"] for row in result.mappings().all())
    if len(found) != len(unique_ids):
        raise LookupError("Partido no encontrado")
    return found
