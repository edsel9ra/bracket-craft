import json
import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.config import get_settings
from app.core.storage import StorageError, get_object_storage
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.rules_engine.engine import (
    effective_roster_lock_matchday,
)
from app.modules.tournaments.schemas import (
    BulkRosterPlayerResponse,
    CreateRosterPlayerRequest,
    RosterPlayerListResponse,
    RosterPlayerResponse,
    UpdatePhotoConsentRequest,
    UpdateRosterStatusRequest,
)
from app.modules.tournaments.photos import sign_photo_rows
from app.modules.tournaments.roster_import import (
    RosterImportError,
    extract_zip_photos,
    parse_roster_csv,
    validate_photo_content,
)

from app.modules.tournaments.access import (
    _ensure_tournament,
    _require_tournament_management,
)

router = APIRouter()

# Conserva el nombre del logger tras dividir el router.
logger = logging.getLogger("app.modules.tournaments.router")


ROSTER_LOCK_DETAIL = (
    "La plantilla está cerrada desde la jornada {matchday}: "
    "no se pueden inscribir jugadores nuevos"
)

# The 409 detail the API already uses for a duplicated roster row (RF-051,
# RC-1); reactivating with another active row of the same player answers it.
ROSTER_DUPLICATE_DETAIL = (
    "El documento, dorsal o jugador ya está registrado en el torneo"
)
ROSTER_DORSAL_TAKEN_DETAIL = (
    "El dorsal {dorsal_number} ya está ocupado por otro jugador activo del equipo"
)


async def _published_version_rules(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID
) -> tuple[UUID, dict] | None:
    """Return the published version id and its rules config, if any (RF-022)."""

    result = await db.execute(
        text("""
            SELECT id AS version_id, rules_config
            FROM tournament_versions
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND status = 'published'
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    config = row["rules_config"]
    if isinstance(config, str):
        config = json.loads(config)
    return row["version_id"], config or {}


async def _active_roster_lock_matchday(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID
) -> int | None:
    """Return the reference matchday when the roster lock is active (RF-023).

    The value comes from the published version only: without one, with a null
    key or without a reference matchday the lock never applies. The lock is
    active when the first stage (``stage_order``, then ``id``) has at least one
    non-cancelled match for the reference matchday and every one of them is
    confirmed (``finished``/``administrative_resolution`` + ``result_confirmed``).
    No new locks are taken: this is a read of the confirmed state (RF-028).
    """

    published = await _published_version_rules(db, organization_id, tournament_id)
    if published is None:
        return None
    version_id, config = published
    matchday = effective_roster_lock_matchday(config)
    if matchday is None:
        return None

    result = await db.execute(
        text("""
            SELECT count(*) AS total,
                   count(*) FILTER (
                       WHERE m.status IN ('finished', 'administrative_resolution')
                         AND m.result_confirmed = TRUE
                   ) AS confirmed
            FROM matches m
            WHERE m.organization_id = :organization_id
              AND m.tournament_id = :tournament_id
              AND m.tournament_version_id = :version_id
              AND m.stage_id = (
                  SELECT s.id
                  FROM stages s
                  WHERE s.organization_id = :organization_id
                    AND s.tournament_id = :tournament_id
                    AND s.tournament_version_id = :version_id
                  ORDER BY s.stage_order, s.id
                  LIMIT 1
              )
              AND m.matchday = :matchday
              AND m.status <> 'cancelled'
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "matchday": matchday,
        },
    )
    counts = result.mappings().one()
    total = counts["total"] or 0
    confirmed = counts["confirmed"] or 0
    if total > 0 and confirmed == total:
        return matchday
    return None


async def _enforce_roster_lock(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID
) -> None:
    """Reject a new roster registration while the roster lock is active."""

    matchday = await _active_roster_lock_matchday(db, organization_id, tournament_id)
    if matchday is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ROSTER_LOCK_DETAIL.format(matchday=matchday),
        )


_PLAYER_DOCUMENT_HMAC_SQL = (
    "encode(hmac(CAST(:national_id AS TEXT), CAST(:player_data_key AS TEXT), 'sha256'), 'hex')"
)


async def _find_player_by_document(
    db: AsyncSession,
    organization_id: UUID,
    payload: CreateRosterPlayerRequest,
    settings,
) -> UUID | None:
    """Look up a player by document inside one organization only (RF-001/RF-003)."""

    result = await db.execute(
        text("""
            SELECT id
            FROM players
            WHERE organization_id = :organization_id
              AND document_type = :document_type
              AND issuing_country = :issuing_country
              AND national_id_hmac = {_PLAYER_DOCUMENT_HMAC_SQL}
        """  # nosec B608 # expresión HMAC constante con parámetros ligados.
        .format(_PLAYER_DOCUMENT_HMAC_SQL=_PLAYER_DOCUMENT_HMAC_SQL)),
        {
            "organization_id": str(organization_id),
            "document_type": payload.document_type,
            "issuing_country": payload.issuing_country,
            "national_id": payload.national_id,
            "player_data_key": settings.player_data_key,
        },
    )
    return result.scalar_one_or_none()


async def _find_or_create_player_record(
    db: AsyncSession,
    organization_id: UUID,
    payload: CreateRosterPlayerRequest,
    settings,
    reference_year: int,
) -> UUID:
    """Reuse or create the player for one organization, tolerating races.

    The per-organization unique index is the source of truth: if a concurrent
    transaction created the same document, the insert is a no-op and the winning
    row is reused instead of creating a duplicate or returning partial data.

    The birth date is stored write-only (encrypted with ``PLAYER_DATA_KEY``) and
    only the derived age is materialized. A reused player keeps the date and the
    age of its first registration: the application can neither decrypt nor
    compare the stored date, so a later payload never updates them (RF-007).
    """

    player_id = await _find_player_by_document(db, organization_id, payload, settings)
    if player_id is not None:
        return player_id

    player_result = await db.execute(
        text("""
            INSERT INTO players
                (organization_id, first_name, last_name, document_type, national_id_encrypted,
                 national_id_hmac, issuing_country, birth_date_encrypted,
                 age_at_reference, age_reference_year)
            VALUES (
                :organization_id,
                :first_name,
                :last_name,
                :document_type,
                pgp_sym_encrypt(CAST(:national_id AS TEXT), :player_data_key),
                {_PLAYER_DOCUMENT_HMAC_SQL},
                :issuing_country,
                pgp_sym_encrypt(CAST(:birth_date AS TEXT), :player_data_key),
                :age_at_reference,
                :age_reference_year
            )
            ON CONFLICT (organization_id, document_type, issuing_country, national_id_hmac)
            DO NOTHING
            RETURNING id
        """  # nosec B608 # expresión HMAC constante con parámetros ligados.
        .format(_PLAYER_DOCUMENT_HMAC_SQL=_PLAYER_DOCUMENT_HMAC_SQL)),
        {
            "organization_id": str(organization_id),
            "first_name": payload.first_name,
            "last_name": payload.last_name,
            "document_type": payload.document_type,
            "national_id": payload.national_id,
            "player_data_key": settings.player_data_key,
            "issuing_country": payload.issuing_country,
            "birth_date": payload.birth_date.isoformat(),
            "age_at_reference": reference_year - payload.birth_date.year,
            "age_reference_year": reference_year,
        },
    )
    player_id = player_result.scalar_one_or_none()
    if player_id is not None:
        return player_id

    player_id = await _find_player_by_document(db, organization_id, payload, settings)
    if player_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El documento ya está registrado en la organización",
        )
    return player_id


async def _create_roster_player_record(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    payload: CreateRosterPlayerRequest,
    settings,
    roster_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    team_result = await db.execute(
        text("""
            SELECT t.start_date
            FROM tournament_teams tt
            JOIN tournaments t
              ON t.id = tt.tournament_id
             AND t.organization_id = tt.organization_id
            WHERE tt.tournament_id = :tournament_id
              AND tt.team_id = :team_id
              AND tt.organization_id = :organization_id
        """),
        {
            "tournament_id": str(tournament_id),
            "team_id": str(payload.team_id),
            "organization_id": str(context.organization_id),
        },
    )
    tournament_start_date = team_result.scalar_one_or_none()
    if tournament_start_date is None:
        raise HTTPException(status_code=404, detail="El equipo no está registrado en el torneo")

    player_id = await _find_or_create_player_record(
        db,
        context.organization_id,
        payload,
        settings,
        tournament_start_date.year,
    )

    roster_id = roster_id or uuid4()
    roster_result = await db.execute(
        text("""
            INSERT INTO rosters
                (id, organization_id, tournament_id, team_id, player_id, dorsal_number, photo_consent,
                 valid_from, eligible_from)
            VALUES (
                :id, :organization_id, :tournament_id, :team_id, :player_id, :dorsal_number, :photo_consent,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id
        """),
        {
            "id": str(roster_id),
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(payload.team_id),
            "player_id": str(player_id),
            "dorsal_number": payload.dorsal_number,
            "photo_consent": payload.photo_consent,
        },
    )
    return roster_result.scalar_one(), player_id


async def _load_roster_player_rows(
    db: AsyncSession, organization_id: UUID, roster_ids: list[UUID]
) -> list[dict]:
    """Load the given roster rows in one query, preserving the requested order."""

    if not roster_ids:
        return []
    result = await db.execute(
        text("""
            SELECT r.id AS roster_id, r.player_id, r.team_id, p.first_name, p.last_name,
                   r.dorsal_number, r.photo_object_key, r.photo_consent, r.is_active
            FROM rosters r
            JOIN players p
              ON p.id = r.player_id
             AND p.organization_id = r.organization_id
            WHERE r.organization_id = :organization_id
              AND r.id = ANY(CAST(:roster_ids AS UUID[]))
        """),
        {
            "organization_id": str(organization_id),
            "roster_ids": [str(roster_id) for roster_id in roster_ids],
        },
    )
    rows_by_id = {str(row["roster_id"]): dict(row) for row in result.mappings().all()}
    return [
        rows_by_id[str(roster_id)]
        for roster_id in roster_ids
        if str(roster_id) in rows_by_id
    ]


async def _load_roster_player_row(
    db: AsyncSession, organization_id: UUID, roster_id: UUID
) -> dict:
    rows = await _load_roster_player_rows(db, organization_id, [roster_id])
    if not rows:
        raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
    return rows[0]


@router.get("/{tournament_id}/rosters", response_model=list[RosterPlayerListResponse])
async def list_tournament_rosters(
    tournament_id: UUID,
    team_id: UUID | None = None,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[RosterPlayerListResponse]:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        result = await db.execute(
            text("""
                SELECT r.id AS roster_id, r.player_id, r.team_id, p.first_name, p.last_name,
                       r.dorsal_number, r.photo_object_key, r.photo_consent, r.is_active,
                       (p.age_at_reference
                        + (EXTRACT(YEAR FROM t.start_date)::INT - p.age_reference_year))::INT AS age
                FROM rosters r
                JOIN players p
                  ON p.id = r.player_id
                 AND p.organization_id = r.organization_id
                JOIN tournaments t
                  ON t.id = r.tournament_id
                 AND t.organization_id = r.organization_id
                WHERE r.tournament_id = :tournament_id
                  AND r.organization_id = :organization_id
                  AND (CAST(:team_id AS UUID) IS NULL OR r.team_id = CAST(:team_id AS UUID))
                ORDER BY r.team_id, r.dorsal_number, p.last_name, p.first_name
                LIMIT :limit OFFSET :offset
            """),
            {
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
                "team_id": str(team_id) if team_id else None,
                "limit": limit,
                "offset": offset,
            },
        )
        players = [dict(row) for row in result.mappings().all()]
    return await sign_photo_rows(
        players, key_field="photo_object_key", policy="error"
    )


@router.post("/{tournament_id}/rosters", response_model=RosterPlayerResponse, status_code=status.HTTP_201_CREATED)
async def create_roster_player(
    tournament_id: UUID,
    payload: CreateRosterPlayerRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerResponse:
    settings = get_settings()
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        # Checked before creating the player or the roster row (RF-024).
        await _enforce_roster_lock(db, context.organization_id, tournament_id)
        try:
            roster_id, _ = await _create_roster_player_record(db, context, tournament_id, payload, settings)
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="El documento, dorsal o jugador ya está registrado en el torneo") from exc
        row = await _load_roster_player_row(db, context.organization_id, roster_id)
    return (await sign_photo_rows([row], key_field="photo_object_key", policy="error"))[0]


@router.post("/{tournament_id}/rosters/bulk", response_model=BulkRosterPlayerResponse, status_code=status.HTTP_201_CREATED)
async def create_roster_players_bulk(
    tournament_id: UUID,
    team_id: UUID = Form(...),
    csv_file: UploadFile = File(...),
    photos_zip: UploadFile | None = File(default=None),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BulkRosterPlayerResponse:
    settings = get_settings()
    filename = (csv_file.filename or "").lower()
    if not filename.endswith((".csv", ".txt")):
        raise HTTPException(status_code=422, detail="El archivo de plantilla debe ser CSV o TXT")
    csv_raw = await csv_file.read(settings.storage_max_archive_bytes + 1)
    if len(csv_raw) > settings.storage_max_archive_bytes:
        raise HTTPException(status_code=413, detail="El archivo de plantilla supera el tamaño máximo permitido")
    try:
        rows = parse_roster_csv(csv_raw, team_id)
        photos: dict = {}
        if photos_zip is not None:
            zip_raw = await photos_zip.read(settings.storage_max_archive_bytes + 1)
            if len(zip_raw) > settings.storage_max_archive_bytes:
                raise RosterImportError("El archivo ZIP supera el tamaño máximo permitido")
            photos = extract_zip_photos(zip_raw)
    except RosterImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    warnings: list[str] = []
    uploaded_keys: list[str] = []
    created_roster_ids: list[UUID] = []
    players: list[dict] = []
    storage = get_object_storage()
    prepared: list[tuple[UUID, str | None]] = []
    completed = False
    try:
        # Authorize before touching storage: a request that cannot manage this
        # tournament must not upload any object (read transaction, then close).
        async with db.begin():
            await set_rls_context(db, context.organization_id, context.user_id)
            await _ensure_tournament(db, context.organization_id, tournament_id)
            await _require_tournament_management(db, context)
            team_result = await db.execute(
                text("""
                    SELECT 1
                    FROM tournament_teams tt
                    WHERE tt.organization_id = :organization_id
                      AND tt.tournament_id = :tournament_id
                      AND tt.team_id = :team_id
                      AND tt.status = 'registered'
                """),
                {
                    "organization_id": str(context.organization_id),
                    "tournament_id": str(tournament_id),
                    "team_id": str(team_id),
                },
            )
            if team_result.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="El equipo no está registrado en el torneo")
            # First of the two checks: the lock is rejected before any photo is
            # uploaded (RF-025).
            await _enforce_roster_lock(db, context.organization_id, tournament_id)

        # N-2: upload every photo before opening the write transaction. The
        # roster id is generated here so the object key is final before the row
        # exists; a failed upload leaves no row and compensates earlier uploads.
        for row in rows:
            roster_id = uuid4()
            photo_key: str | None = None
            if row.photo_filename:
                photo = photos.get(row.photo_filename.casefold())
                if photo is None:
                    warnings.append(f"Fila {row.line_number}: no se encontró {row.photo_filename} en el ZIP")
                else:
                    photo_key = (
                        "private/organizations/"
                        f"{context.organization_id}/tournaments/{tournament_id}/rosters/"
                        f"{roster_id}/{uuid4()}{photo.extension}"
                    )
                    # Register the key before the upload: if the request is
                    # cancelled or fails after the object was written, the
                    # compensation below also deletes it.
                    uploaded_keys.append(photo_key)
                    try:
                        await storage.put_bytes(photo_key, photo.content, photo.content_type)
                    except StorageError as exc:
                        raise HTTPException(status_code=503, detail="El almacenamiento de fotos no está disponible") from exc
            prepared.append((roster_id, photo_key))

        async with db.begin():
            await set_rls_context(db, context.organization_id, context.user_id)
            await _ensure_tournament(db, context.organization_id, tournament_id)
            await _require_tournament_management(db, context)
            # Second check, inside the write transaction: if the lock turned
            # active after the uploads, the request fails without rows and the
            # `finally` below compensates the objects (RF-025).
            await _enforce_roster_lock(db, context.organization_id, tournament_id)
            for row, (roster_id, photo_key) in zip(rows, prepared, strict=True):
                try:
                    await _create_roster_player_record(
                        db,
                        context,
                        tournament_id,
                        row.payload,
                        settings,
                        roster_id=roster_id,
                    )
                except IntegrityError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Fila {row.line_number}: el documento, dorsal o jugador ya está registrado en el torneo",
                    ) from exc
                if photo_key is not None:
                    await db.execute(
                        text("SELECT set_roster_photo_object(:roster_id, :photo_object_key)"),
                        {"roster_id": str(roster_id), "photo_object_key": photo_key},
                    )
                created_roster_ids.append(roster_id)
            players = await _load_roster_player_rows(
                db, context.organization_id, created_roster_ids
            )
            # Mark success before leaving the transaction (implicit commit): a
            # failed commit and a cancellation while committing are ambiguous
            # (the rows may or may not be visible), so no object is deleted.
            # A failed commit can leave orphan objects (best-effort), which is
            # preferable to a broken reference.
            completed = True
    finally:
        if not completed:
            # Best-effort compensation in `finally` so a cancellation between
            # the uploads and the write also removes the objects. The original
            # exception (including CancelledError) is always re-raised.
            for key in uploaded_keys:
                try:
                    await storage.delete_key(key)
                except BaseException:
                    logger.warning("No se pudo eliminar una foto tras revertir la importación")

    # N-2: the rows are committed; signing happens outside the transaction so a
    # storage failure answers 503 without deleting uploaded keys or rolling back.
    players = await sign_photo_rows(
        players, key_field="photo_object_key", policy="error"
    )
    return {"count": len(players), "players": players, "warnings": warnings}


@router.post("/{tournament_id}/rosters/{roster_id}/photo", response_model=RosterPlayerResponse)
async def upload_roster_player_photo(
    tournament_id: UUID,
    roster_id: UUID,
    photo: UploadFile = File(...),
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerResponse:
    settings = get_settings()
    raw = await photo.read(settings.storage_max_image_bytes + 1)
    try:
        image = validate_photo_content(raw, photo.filename or "player.jpg")
    except RosterImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    storage = get_object_storage()
    old_key: str | None = None
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        roster_result = await db.execute(
            text("""
                SELECT r.id, r.photo_consent, r.photo_object_key
                FROM rosters r
                WHERE r.id = :roster_id
                  AND r.tournament_id = :tournament_id
                  AND r.organization_id = :organization_id
            """),
            {
                "roster_id": str(roster_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        roster = roster_result.mappings().one_or_none()
        if roster is None:
            raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
        if not roster["photo_consent"]:
            raise HTTPException(status_code=409, detail="No existe consentimiento para cargar la foto")
        old_key = roster["photo_object_key"]

    # N-2: the read transaction is closed; the upload and the compensation run
    # with no transaction open. A failed upload leaves the row untouched.
    key = (
        "private/organizations/"
        f"{context.organization_id}/tournaments/{tournament_id}/rosters/"
        f"{roster_id}/{uuid4()}{image.extension}"
    )
    completed = False
    committed = False
    old_key_to_delete: str | None = None
    try:
        try:
            await storage.put_bytes(key, image.content, image.content_type)
        except StorageError as exc:
            raise HTTPException(status_code=503, detail="El almacenamiento de fotos no está disponible") from exc
        async with db.begin():
            await set_rls_context(db, context.organization_id, context.user_id)
            await _require_tournament_management(db, context)
            replacement_result = await db.execute(
                text("SELECT set_roster_photo_object(:roster_id, :photo_object_key)"),
                {"roster_id": str(roster_id), "photo_object_key": key},
            )
            previous_key = replacement_result.scalar_one_or_none()
            if previous_key is not None:
                old_key = previous_key
            row = await _load_roster_player_row(db, context.organization_id, roster_id)
            old_key_to_delete = old_key if old_key and old_key != key else None
            # The write body finished. A failure from here on belongs to the
            # implicit commit and is ambiguous: the row may or may not be
            # visible, so nothing is deleted in that case.
            completed = True
        committed = True
    finally:
        if not completed:
            # Failure before the end of the write body: the transaction rolled
            # back, so the new object is safe to compensate.
            try:
                await storage.delete_key(key)
            except BaseException:
                logger.warning("No se pudo eliminar una foto tras revertir la carga")
        elif committed and old_key_to_delete:
            # The previous object is unreferenced only after a confirmed
            # commit. A cancellation during this cleanup is not swallowed.
            try:
                await storage.delete_key(old_key_to_delete)
            except Exception:
                logger.warning("No se pudo eliminar la foto anterior del roster %s", roster_id, exc_info=True)
    return (await sign_photo_rows([row], key_field="photo_object_key", policy="error"))[0]


@router.patch("/{tournament_id}/rosters/{roster_id}/photo-consent", response_model=RosterPlayerResponse)
async def update_roster_photo_consent(
    tournament_id: UUID,
    roster_id: UUID,
    payload: UpdatePhotoConsentRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerResponse:
    storage = get_object_storage()
    old_key: str | None = None
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        roster_result = await db.execute(
            text("""
                SELECT id
                FROM rosters
                WHERE id = :roster_id
                  AND tournament_id = :tournament_id
                  AND organization_id = :organization_id
            """),
            {
                "roster_id": str(roster_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        if roster_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
        old_key = (await db.execute(
            text("SELECT set_roster_photo_consent(:roster_id, :photo_consent)"),
            {"roster_id": str(roster_id), "photo_consent": payload.photo_consent},
        )).scalar_one_or_none()
        row = await _load_roster_player_row(db, context.organization_id, roster_id)

    if not payload.photo_consent and old_key:
        try:
            await storage.delete_key(old_key)
        except StorageError:
            logger.warning("No se pudo eliminar la foto sin consentimiento del roster %s", roster_id, exc_info=True)
    return (await sign_photo_rows([row], key_field="photo_object_key", policy="error"))[0]


async def _load_roster_list_row(
    db: AsyncSession, organization_id: UUID, tournament_id: UUID, roster_id: UUID
) -> dict:
    """Load one roster row with the **list** model, ``age`` included (RF-051).

    Mirrors the projection of ``GET /tournaments/{id}/rosters``: the status
    endpoint answers with the same shape, so a client can replace the row in
    place. The row is looked up by tournament and organization too: a roster of
    another tournament or another organization is not visible here (404).
    """

    result = await db.execute(
        text("""
            SELECT r.id AS roster_id, r.player_id, r.team_id, p.first_name, p.last_name,
                   r.dorsal_number, r.photo_object_key, r.photo_consent, r.is_active,
                   (p.age_at_reference
                    + (EXTRACT(YEAR FROM t.start_date)::INT - p.age_reference_year))::INT AS age
            FROM rosters r
            JOIN players p
              ON p.id = r.player_id
             AND p.organization_id = r.organization_id
            JOIN tournaments t
              ON t.id = r.tournament_id
             AND t.organization_id = r.organization_id
            WHERE r.id = :roster_id
              AND r.tournament_id = :tournament_id
              AND r.organization_id = :organization_id
        """),
        {
            "roster_id": str(roster_id),
            "tournament_id": str(tournament_id),
            "organization_id": str(organization_id),
        },
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")
    return dict(row)


async def _reject_roster_reactivation_conflicts(
    db: AsyncSession,
    context: AuthContext,
    tournament_id: UUID,
    roster: dict,
) -> None:
    """Reject a reactivation that a unique active index would refuse (RA-1).

    Reactivating behaves like a registration, so the current uniqueness of the
    active rows applies: one active row per player in the tournament and one
    active dorsal per team. Both are checked before writing, so the 409 names
    the cause and no row changes; a concurrent write that slips in between is
    caught by the ``IntegrityError`` mapping of the caller.
    """

    duplicate = await db.execute(
        text("""
            SELECT 1
            FROM rosters
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND player_id = :player_id
              AND is_active = TRUE
              AND id <> :roster_id
            LIMIT 1
        """),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "player_id": str(roster["player_id"]),
            "roster_id": str(roster["roster_id"]),
        },
    )
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ROSTER_DUPLICATE_DETAIL
        )

    busy_dorsal = await db.execute(
        text("""
            SELECT 1
            FROM rosters
            WHERE organization_id = :organization_id
              AND tournament_id = :tournament_id
              AND team_id = :team_id
              AND dorsal_number = :dorsal_number
              AND is_active = TRUE
              AND id <> :roster_id
            LIMIT 1
        """),
        {
            "organization_id": str(context.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(roster["team_id"]),
            "dorsal_number": roster["dorsal_number"],
            "roster_id": str(roster["roster_id"]),
        },
    )
    if busy_dorsal.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ROSTER_DORSAL_TAKEN_DETAIL.format(
                dorsal_number=roster["dorsal_number"]
            ),
        )


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    """Return the violated constraint of a unique/foreign violation, if known."""

    original = exc.orig
    candidates = (original, getattr(original, "__cause__", None))
    for candidate in candidates:
        name = getattr(candidate, "constraint_name", None)
        if name:
            return str(name)
    return None


def _roster_status_conflict(exc: IntegrityError, dorsal_number: int) -> HTTPException:
    """Map the unique active indexes to their 409, without leaking SQL."""

    if _integrity_constraint_name(exc) == "uq_active_roster_dorsal":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ROSTER_DORSAL_TAKEN_DETAIL.format(dorsal_number=dorsal_number),
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=ROSTER_DUPLICATE_DETAIL
    )


@router.patch(
    "/{tournament_id}/rosters/{roster_id}/status",
    response_model=RosterPlayerListResponse,
    summary="Retirar o reactivar lógicamente a un jugador de la plantilla",
    responses={
        200: {
            "description": (
                "Fila actualizada con el modelo de la lista de plantilla "
                "(`player_id` y `age` incluidos). Repetir el mismo valor es "
                "idempotente y devuelve 200 sin escribir."
            )
        },
        404: {"description": "El torneo o el roster no existen en la organización activa"},
        409: {
            "description": (
                "Reactivación con el bloqueo por jornada activo, con otra fila "
                "activa del mismo jugador en el torneo o con el dorsal ya "
                "ocupado. El retiro está exento del bloqueo por jornada."
            )
        },
        422: {"description": "Cuerpo inválido: `is_active` booleano obligatorio"},
    },
)
async def update_roster_player_status(
    tournament_id: UUID,
    roster_id: UUID,
    payload: UpdateRosterStatusRequest,
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> RosterPlayerListResponse:
    """Retire or reactivate a roster player, without deleting anything (RF-051).

    One endpoint and one model for both directions. The **retirement** is the
    single exception to the matchday lock (RL-1): it only removes players, so
    it works while the lock is active, with the team enrolled and with an open
    match, and it never rewrites the row, the lineups or the events. The
    **reactivation** adds an active player, so it behaves like a registration
    (RA-1): the same 409 of the matchday lock and the current uniqueness of the
    active player and dorsal. The same value is idempotent (200, no write) and
    the action writes no audit entry, because it is not one of the audited
    actions. Reads and writes run with ``set_rls_context`` in this transaction,
    so a roster of another organization is a 404.
    """

    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        await _ensure_tournament(db, context.organization_id, tournament_id)
        await _require_tournament_management(db, context)
        current = await db.execute(
            text("""
                SELECT r.id AS roster_id, r.is_active, r.player_id, r.team_id,
                       r.dorsal_number
                FROM rosters r
                WHERE r.id = :roster_id
                  AND r.tournament_id = :tournament_id
                  AND r.organization_id = :organization_id
            """),
            {
                "roster_id": str(roster_id),
                "tournament_id": str(tournament_id),
                "organization_id": str(context.organization_id),
            },
        )
        roster = current.mappings().one_or_none()
        if roster is None:
            raise HTTPException(status_code=404, detail="La plantilla no fue encontrada")

        if bool(roster["is_active"]) != payload.is_active:
            if payload.is_active:
                # RA-1: reactivating sums an active player, exactly like a
                # registration, so the published matchday lock applies.
                await _enforce_roster_lock(
                    db, context.organization_id, tournament_id
                )
                await _reject_roster_reactivation_conflicts(
                    db, context, tournament_id, dict(roster)
                )
            try:
                await db.execute(
                    text("""
                        UPDATE rosters
                        SET is_active = :is_active
                        WHERE id = :roster_id
                          AND tournament_id = :tournament_id
                          AND organization_id = :organization_id
                    """),
                    {
                        "is_active": payload.is_active,
                        "roster_id": str(roster_id),
                        "tournament_id": str(tournament_id),
                        "organization_id": str(context.organization_id),
                    },
                )
            except IntegrityError as exc:
                # Only a concurrent write can reach this: the pre-checks above
                # already rejected both conflicts. The transaction rolls back,
                # so no row changes.
                raise _roster_status_conflict(
                    exc, roster["dorsal_number"]
                ) from exc

        row = await _load_roster_list_row(
            db, context.organization_id, tournament_id, roster_id
        )
    return (await sign_photo_rows([row], key_field="photo_object_key", policy="error"))[0]
