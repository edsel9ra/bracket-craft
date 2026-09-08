from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def require_permission(
    db: AsyncSession,
    context,
    permission: str,
    tournament_id: UUID | None = None,
    match_id: UUID | None = None,
    role_codes: tuple[str, ...] | None = None,
) -> None:
    query = text("""
        SELECT 1
        FROM roles r
        JOIN role_definitions rd ON rd.id = r.role_definition_id
        JOIN organization_user_roles our
          ON our.role_id = r.id
         AND our.organization_id = :organization_id
        WHERE our.organization_user_id = :organization_user_id
         AND r.permissions @> CAST(:permission AS jsonb)
         AND (
             CAST(:role_codes AS TEXT[]) IS NULL
             OR rd.code = ANY(CAST(:role_codes AS TEXT[]))
         )
         AND (
               CAST(:match_id AS UUID) IS NULL
               OR rd.code IN ('owner', 'administrator', 'operator')
               OR EXISTS (
                  SELECT 1
                  FROM match_officials mo
                  WHERE mo.match_id = CAST(:match_id AS UUID)
                    AND mo.organization_id = :organization_id
                    AND mo.organization_user_id = :organization_user_id
              )
          )
        UNION ALL
        SELECT 1
        FROM roles r
        JOIN role_definitions rd ON rd.id = r.role_definition_id
        JOIN tournament_user_roles tur
          ON tur.role_id = r.id
         AND tur.organization_id = :organization_id
        WHERE tur.organization_user_id = :organization_user_id
          AND (CAST(:tournament_id AS UUID) IS NOT NULL AND tur.tournament_id = CAST(:tournament_id AS UUID))
           AND r.permissions @> CAST(:permission AS jsonb)
           AND (
               CAST(:role_codes AS TEXT[]) IS NULL
               OR rd.code = ANY(CAST(:role_codes AS TEXT[]))
           )
           AND (
               CAST(:match_id AS UUID) IS NULL
               OR rd.code IN ('owner', 'administrator', 'operator')
               OR EXISTS (
                  SELECT 1
                  FROM match_officials mo
                  WHERE mo.match_id = CAST(:match_id AS UUID)
                    AND mo.organization_id = :organization_id
                    AND mo.organization_user_id = :organization_user_id
              )
          )
        LIMIT 1
    """)
    result = await db.execute(
        query,
        {
            "organization_id": str(context.organization_id),
            "organization_user_id": str(context.organization_user_id),
            "permission": f'["{permission}"]',
            "tournament_id": str(tournament_id) if tournament_id else None,
            "match_id": str(match_id) if match_id else None,
            "role_codes": list(role_codes) if role_codes else None,
        },
    )
    if result.scalar_one_or_none() is None:
        raise PermissionError(f"Permiso requerido: {permission}")


async def require_administrative_resolution(
    db: AsyncSession,
    context,
    tournament_id: UUID,
    match_id: UUID,
) -> None:
    """Require an owner/administrator role for non-sporting resolutions."""

    await require_permission(
        db,
        context,
        "RESOLVE_MATCH_ADMINISTRATIVELY",
        tournament_id=tournament_id,
        match_id=match_id,
        role_codes=("owner", "administrator"),
    )
