"""Crest operation context and object upload (RF-2, RF-3, RF-23, RF-27, RNF-4).

Two responsibilities live here, both outside the write path:

- ``resolve_enrolled_team`` opens a short read transaction (or joins the
  caller's write transaction with ``lock=True``), fixes the RLS context before
  any tenant read, checks the tournament and resolves the enrollment of the
  team in that tournament. A missing tournament keeps the existing 404
  (``Torneo no encontrado``); a team that does not exist, belongs to another
  organization or is not enrolled in the context tournament answers with the
  same ``CREST_NOT_FOUND`` (RF-23, RF-26).
- ``store_crest_object`` builds the private key from the detected extension and
  uploads the admitted content with its detected ``Content-Type``. It receives
  no session, so it cannot open a transaction (N-2); a storage failure becomes
  ``CREST_STORAGE_UNAVAILABLE`` (503) and the database is never touched.

The management permission is checked in ``require_crest_management`` with the
existing organization RBAC helper and translated to ``CREST_FORBIDDEN`` (403).
The read path (``GET``) only requires an active membership, so
``resolve_enrolled_team`` can skip that check.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.permissions import require_permission
from app.core.storage import ObjectStorage, StorageError
from app.core.tenancy import AuthContext
from app.modules.crests.audit import (
    REMOVE_TEAM_CREST,
    crest_audit_action,
    record_crest_audit,
)
from app.modules.crests.errors import (
    CREST_FORBIDDEN,
    CREST_NOT_FOUND,
    CREST_STORAGE_UNAVAILABLE,
    CrestError,
)
from app.modules.crests.resolver import sign_crest_rows
from app.modules.crests.validation import CrestFile, crest_object_key
from app.modules.tournaments.router import _ensure_tournament
from app.modules.tournaments.schemas import TeamCrestResponse

CREST_MANAGEMENT_PERMISSION = "MANAGE_TOURNAMENTS"

_LOGGER = logging.getLogger(__name__)

_TEAM_QUERY = """
    SELECT t.id AS team_id,
           t.crest_object_key,
           t.logo_url
    FROM public.teams t
    JOIN public.tournament_teams tt
      ON tt.team_id = t.id
     AND tt.organization_id = t.organization_id
     AND tt.tournament_id = :tournament_id
    WHERE t.id = :team_id
      AND t.organization_id = :organization_id
"""


@dataclass(frozen=True)
class EnrolledTeam:
    """Team of the organization enrolled in the context tournament."""

    team_id: UUID
    crest_object_key: str | None
    logo_url: str | None


async def require_crest_management(
    db: AsyncSession,
    context: AuthContext,
) -> None:
    """Require ``MANAGE_TOURNAMENTS``; a missing permission answers 403."""

    try:
        await require_permission(db, context, CREST_MANAGEMENT_PERMISSION)
    except PermissionError as exc:
        raise CrestError(CREST_FORBIDDEN) from exc


async def resolve_enrolled_team(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    team_id: UUID,
    *,
    lock: bool = False,
    require_management: bool = True,
) -> EnrolledTeam:
    """Resolve the team in the context tournament or answer 404.

    With ``lock=False`` the function opens its own short read transaction; with
    ``lock=True`` the caller owns the write transaction and the team row is
    locked with ``FOR UPDATE OF t``. ``require_management=False`` is the read
    path, where the endpoint only requires an active membership.
    """

    if lock:
        return await _resolve_enrolled_team(
            db,
            context,
            tournament_id,
            team_id,
            lock=True,
            require_management=require_management,
        )

    async with db.begin():
        return await _resolve_enrolled_team(
            db,
            context,
            tournament_id,
            team_id,
            lock=False,
            require_management=require_management,
        )


async def _resolve_enrolled_team(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    team_id: UUID,
    *,
    lock: bool,
    require_management: bool,
) -> EnrolledTeam:
    await set_rls_context(db, context.organization_id, context.user_id)
    await _ensure_tournament(db, context.organization_id, tournament_id)
    if require_management:
        await require_crest_management(db, context)

    query = _TEAM_QUERY
    if lock:
        query = f"{_TEAM_QUERY}\n    FOR UPDATE OF t"

    result = await db.execute(
        text(query),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    record = result.mappings().one_or_none()
    if record is None:
        raise CrestError(CREST_NOT_FOUND)

    return EnrolledTeam(
        team_id=record["team_id"],
        crest_object_key=record["crest_object_key"],
        logo_url=record["logo_url"],
    )


async def store_crest_object(
    storage: ObjectStorage,
    crest: CrestFile,
    *,
    organization_id: UUID,
    tournament_id: UUID,
    team_id: UUID,
) -> str:
    """Upload the admitted crest and return its private object key.

    The key comes from the detected extension (never from a file name) and the
    active transaction is expected to be closed by the caller. A storage failure
    answers ``CREST_STORAGE_UNAVAILABLE`` and leaves no database reference; the
    object is best-effort when the upload fails partially (nothing references it
    yet, so it can only become an orphan).
    """

    key = crest_object_key(
        organization_id,
        tournament_id,
        team_id,
        crest.extension,
    )
    try:
        await storage.put_bytes(key, crest.content, crest.content_type)
    except StorageError as exc:
        raise CrestError(CREST_STORAGE_UNAVAILABLE) from exc
    return key


async def load_crest(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    team_id: UUID,
    crest: CrestFile,
    *,
    storage: ObjectStorage,
    logger: logging.Logger | None = None,
    enrolled: EnrolledTeam | None = None,
) -> TeamCrestResponse:
    """Upload or replace the crest of a team enrolled in the tournament.

    The content arrives already admitted by ``validate_crest_content`` (T3), so
    no rejected file reaches the database or the storage. Order of operations:

    1. short read transaction: RLS, tournament, ``MANAGE_TOURNAMENTS`` and the
       enrollment (403/404 before touching the storage);
    2. upload outside any transaction (N-2) with the detected ``Content-Type``;
    3. write transaction: RLS, permission revalidated, the team row locked with
       ``FOR UPDATE OF t``, the new key written with ``logo_url = NULL`` (RF-5)
       and the ``SET_TEAM_CREST`` audit entry in the same transaction (RF-45);
    4. after the confirmed commit, delete the previous object if there was one
       (RF-40). A failed delete is logged once and the response stays successful;
    5. sign the new key and answer ``TeamCrestResponse``.

    Compensation: a failure before the end of the write body guarantees the
    rollback, so the freshly uploaded object is deleted best-effort (RF-41). A
    failure while committing is ambiguous: both objects are kept and nothing is
    deleted (T9).

    ``enrolled`` lets a caller that already authorized the operation (the router
    does it before reading the upload, so 403/404 win over 422) skip the
    duplicated read gate. The write transaction always revalidates the
    tournament, the permission, the enrollment and the locked row.
    """

    log = logger or _LOGGER

    # 1–2. Reject 403/404 before uploading; the read result is only the gate.
    if enrolled is None:
        await resolve_enrolled_team(db, context, tournament_id, team_id)

    key: str | None = None
    old_key_to_delete: str | None = None
    completed = False
    committed = False
    try:
        key = await store_crest_object(
            storage,
            crest,
            organization_id=context.organization_id,
            tournament_id=tournament_id,
            team_id=team_id,
        )

        async with db.begin():
            # 3. The locked read is the authority: last confirmed write wins.
            locked = await resolve_enrolled_team(
                db, context, tournament_id, team_id, lock=True
            )
            previous_key = locked.crest_object_key

            await db.execute(
                text("""
                    UPDATE public.teams
                    SET crest_object_key = :crest_object_key,
                        logo_url = NULL
                    WHERE id = :team_id
                      AND organization_id = :organization_id
                """),
                {
                    "crest_object_key": key,
                    "team_id": str(team_id),
                    "organization_id": str(context.organization_id),
                },
            )

            action = crest_audit_action(previous_key, key)
            if action is not None:
                await record_crest_audit(
                    db,
                    organization_id=context.organization_id,
                    member_id=context.organization_user_id,
                    tournament_id=tournament_id,
                    team_id=team_id,
                    action=action,
                )

            old_key_to_delete = (
                previous_key if previous_key and previous_key != key else None
            )
            # End of the write body: a failure from here belongs to the implicit
            # commit and is ambiguous, so the ``finally`` deletes nothing.
            completed = True

        committed = True
    finally:
        if not completed and key is not None:
            # The write transaction rolled back: the new object is safe to
            # compensate (best-effort, never masks the original error).
            try:
                await storage.delete_key(key)
            except BaseException:
                pass
        elif committed and old_key_to_delete:
            # Only a confirmed commit makes the previous object unreferenced.
            try:
                await storage.delete_key(old_key_to_delete)
            except Exception:
                log.warning(
                    "No se pudo eliminar el escudo anterior del equipo %s",
                    team_id,
                )

    # 5. The response is signed after the transaction closed (N-2).
    row = {"team_id": team_id, "crest_object_key": key, "logo_url": None}
    await sign_crest_rows([row], policy="error", storage=storage, logger=log)
    return TeamCrestResponse(
        team_id=row["team_id"],
        crest_url=row["crest_url"],
        logo_url=row["logo_url"],
    )


async def delete_crest(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    team_id: UUID,
    storage: ObjectStorage,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Remove the crest reference of a team, idempotently (RF-14, RF-46).

    A short read resolves the team (403/404). Without a crest the answer is
    successful and **nothing** happens: no write transaction, no storage call
    and no audit entry. With a crest, one write transaction fixes the RLS
    context, revalidates the permission, locks the team row, sets
    ``crest_object_key = NULL`` (``logo_url`` is never touched or restored) and
    writes the ``REMOVE_TEAM_CREST`` audit entry.

    The object is deleted only after the confirmed commit (RF-40): the reference
    is already gone, so a failed delete is not a 503, it is logged once and the
    answer stays successful, with the file left as an accepted orphan. A second
    deletion repeats the successful answer without a second entry.
    """

    log = logger or _LOGGER

    # Read gate: permission and enrollment are checked before any write.
    resolved = await resolve_enrolled_team(db, context, tournament_id, team_id)
    if resolved.crest_object_key is None:
        return

    removed_key: str | None = None
    async with db.begin():
        locked = await resolve_enrolled_team(
            db, context, tournament_id, team_id, lock=True
        )
        removed_key = locked.crest_object_key
        if removed_key is not None:
            await db.execute(
                text("""
                    UPDATE public.teams
                    SET crest_object_key = NULL
                    WHERE id = :team_id
                      AND organization_id = :organization_id
                """),
                {
                    "team_id": str(team_id),
                    "organization_id": str(context.organization_id),
                },
            )
            await record_crest_audit(
                db,
                organization_id=context.organization_id,
                member_id=context.organization_user_id,
                tournament_id=tournament_id,
                team_id=team_id,
                action=REMOVE_TEAM_CREST,
            )

    if removed_key is not None:
        # Only a confirmed commit reaches this point; a failure while committing
        # raises before deleting, so the reference and the object stay together.
        try:
            await storage.delete_key(removed_key)
        except Exception:
            log.warning("No se pudo eliminar el escudo del equipo %s", team_id)
