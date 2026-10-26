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
from app.modules.matches.errors import (
    AssistPlayerInvalid,
    DoubleYellowInconsistent,
    ResolutionNotEnabled,
    WalkoverConfigInconsistent,
    WalkoverScoreMismatch,
    WalkoverStateNotAllowed,
)
from app.modules.matches.schemas import CloseMatchReportDTO
from app.modules.rule_contract import requires_decisive_winner
from app.modules.rules_engine.defaults import DEFAULT_REGULAR_TIME_MINUTES
from app.modules.rules_engine.engine import (
    compute_match_outcome,
    drop_recorded_red_sanctions,
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
    validate_assist_player,
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
        "penalties_enabled": bool(effective.get("penalties_enabled")),
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


def resolution_enabled(
    minutes: Mapping[str, Any],
    resolution_type: str | None,
) -> bool:
    """Whether the effective stage configuration admits this resolution (P5).

    Regular time is always admitted; extra time and penalties depend on their
    own flag, resolved with the effective stage configuration (including its
    override). Walkover and administrative resolutions keep today's behaviour:
    they are admitted here, and the administrative one keeps its own permission.
    No clock is involved: this is a configuration question, not a minute one.
    """

    if resolution_type == "extra_time":
        return bool(minutes.get("extra_time_enabled"))
    if resolution_type == "penalties":
        return bool(minutes.get("penalties_enabled"))
    return True


@dataclass(frozen=True)
class WalkoverScore:
    """Marcador de walkover ya orientado a local y visitante (RF-005).

    ``home_score``/``away_score`` son el resultado que se escribe en el partido;
    ``winner_score``/``loser_score`` son la pareja **configurada** por la fase
    (``{winner, loser}``), que es la que se nombra en los mensajes y la que
    decide la coherencia D-3/D-5. Se separan para que el mensaje del 409 hable
    de la configuración y no del lado del partido.
    """

    home_score: int
    away_score: int
    winner_score: int
    loser_score: int

    @property
    def is_coherent(self) -> bool:
        """D-3/D-5: el ganador declarado tiene que ir por delante."""

        return self.winner_score > self.loser_score


def derive_walkover_score(
    config: Mapping[str, Any] | None,
    stage_id: UUID | str | None,
    home_team_id: UUID | None,
    away_team_id: UUID | None,
    winner_team_id: UUID | None,
) -> WalkoverScore | None:
    """Derive the walkover pair from the effective stage configuration (RF-005).

    Pure and deterministic (RNF-006): it resolves ``walkover_score`` with the
    same :func:`effective_stage_rules` the operation screen publishes, so the
    value the client sees in ``limits`` is exactly the one the close applies.
    ``stage_defaults`` is merged over the read default 3-0 and the stage
    override is applied on top, key by key.

    The pair is oriented to the match: the declared winner gets ``winner`` and
    the opponent ``loser``. ``None`` means the winner is not a participant; the
    engine (:func:`compute_match_outcome`) remains the authority over the
    outcome, so this is a deliberate double check of participation (plan §5.1).
    """

    effective = effective_stage_rules(config or {}, stage_id)
    configured = effective.get("walkover_score") or {}
    winner_score = int(configured.get("winner", 3))
    loser_score = int(configured.get("loser", 0))

    if winner_team_id is not None and winner_team_id == home_team_id:
        return WalkoverScore(winner_score, loser_score, winner_score, loser_score)
    if winner_team_id is not None and winner_team_id == away_team_id:
        return WalkoverScore(loser_score, winner_score, winner_score, loser_score)
    return None


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

    **Prioridad de los dos pasos del cierre (RF-001).** El estado en campo y las
    sustituciones son el paso **8** y el asistente del gol el paso **9**: una
    asistencia inválida del minuto 10 no puede ganar a una sustitución inválida
    del minuto 50. Como el asistente solo se puede comprobar en su punto del
    orden canónico —necesita el estado en campo de ese minuto (D-7)—, su
    violación se **retiene** y se informa al final, después de que el paso 8
    haya tenido su oportunidad en todo el acta. Hay una sola pasada y una sola
    regla: el asistente se sigue validando con :func:`validate_assist_player` en
    el mismo bucle; lo único que cambia es **cuándo** se lanza el error. Así el
    cierre conserva la prioridad declarada sin duplicar el motor ni recorrer el
    acta dos veces.
    """

    entries = roster_entries(rosters)
    entries_by_player = {entry.player_id: entry for entry in entries}
    teams = tuple(dict.fromkeys(_as_uuid(team_id) for team_id in team_ids))
    states = {team_id: build_on_field(entries, [], team_id) for team_id in teams}
    usage = {team_id: TeamUsage() for team_id in teams}
    # Paso 9 retenido: se informa solo si el paso 8 no falló (ver docstring).
    deferred_assist_error: SubstitutionError | None = None

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
        if event.assist_player_id is not None:
            # Paso 9 (RF-001). El estado es el de los eventos anteriores en
            # orden canónico, la misma regla que la comprobación del goleador, y
            # solo el replay lo conoce (D-7). El defecto se retiene: el paso 8
            # (estado en campo y sustituciones) tiene prioridad aunque su
            # violación aparezca después en el acta.
            assist_entry = entries_by_player.get(event.assist_player_id)
            try:
                validate_assist_player(
                    state,
                    event.assist_player_id,
                    event.minute,
                    event.added_minute,
                    team_id=assist_entry.team_id if assist_entry is not None else None,
                )
            except SubstitutionError as error:
                if deferred_assist_error is None:
                    deferred_assist_error = error
        if event.event_type == RED_CARD:
            states[event.team_id] = apply_red_card(
                state, event.player_id, event.effective_minute
            )

    # Paso 8 completo: los minutos de plantilla también son estado en campo y
    # se informan antes que el asistente.
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

    if deferred_assist_error is not None:
        raise deferred_assist_error

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


def canonical_client_event_id(value: str) -> str:
    """Canonical form of the event's client identifier (RF-012).

    The API accepts the UUID in upper or lower case (RF-015), but the value that
    is written and the value used to look for an already persisted event are
    **the same**: the lowercase form of RFC 4122. Without this normalisation two
    retries of the same ``client_event_id`` in a different case would be two
    different rows for ``uq_event_client_id``.
    """

    return value.lower()


def normalize_event_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Comparable additional information (D-10): ``None`` and ``{}`` are equal."""

    return dict(value) if value else {}


# --- Coherencia disciplinaria del acta (RF-006) -----------------------------

YELLOW_CARD = "yellow_card"
DOUBLE_YELLOW_RED = "double_yellow_red"


def _acta_value(event: MatchEventPayload | Mapping[str, Any], key: str, default: Any = None) -> Any:
    """Lea un campo del evento sea un ``MatchEventPayload`` o un ``mapping``."""

    if isinstance(event, Mapping):
        return event.get(key, default)
    return getattr(event, key, default)


def double_yellow_violations(
    events: Sequence[MatchEventPayload | Mapping[str, Any]],
) -> tuple[int, ...]:
    """Índices del acta que incumplen la doble amarilla (RF-006, D-3).

    Una roja con ``metadata.red_card_type == "double_yellow_red"`` exige
    **exactamente dos** amarillas previas del mismo jugador en el mismo partido.
    Cero, una o tres o más son violación; la roja directa no se mira y una
    segunda amarilla nunca deriva en roja (DU-10).

    **«Previas»** se interpreta con el orden canónico del acta
    ``(minute, added_minute, índice del acta)`` —el mismo de RF-005, de la
    proyección por segmento y del replay del motor—: cuentan solo las amarillas
    **estrictamente anteriores** a la roja en ese orden. No hay ventana de
    «misma jugada» porque el acta no declara jugadas: el orden canónico es la
    única lectura determinista (RNF-006) y así una amarilla posterior a la roja,
    o del mismo minuto con índice mayor, no cuenta.

    La fuente es **solo** el acta recibida (los eventos de la petición, que son
    los del partido): las amarillas guardadas en otro partido no cuentan. La
    función es pura —sin base, sin reloj, sin entorno— y acepta tanto los
    ``MatchEventPayload`` de la petición como ``mappings`` para probarla con
    dicts (una misma llamada usa una sola forma: la comparación del jugador es
    exacta). Devuelve los índices del payload (posición en ``events``) en orden
    canónico; el servicio informa el primero (RF-001).

    El contador no se reinicia al aplicar una roja: es el número de amarillas
    del jugador en el acta. Una segunda roja del mismo jugador es, de todos
    modos, un defecto anterior del paso 8 (estado en campo) en un acta real.
    """

    ordered = sorted(
        enumerate(events),
        key=lambda item: (
            int(_acta_value(item[1], "minute") or 0),
            int(_acta_value(item[1], "added_minute") or 0),
            item[0],
        ),
    )
    yellows: dict[Any, int] = {}
    violations: list[int] = []
    for index, event in ordered:
        event_type = _acta_value(event, "event_type")
        player_id = _acta_value(event, "player_id")
        if player_id is None:
            continue
        if event_type == YELLOW_CARD:
            yellows[player_id] = yellows.get(player_id, 0) + 1
            continue
        if event_type != RED_CARD:
            continue
        metadata = _acta_value(event, "metadata") or {}
        if metadata.get("red_card_type") != DOUBLE_YELLOW_RED:
            continue
        if yellows.get(player_id, 0) != 2:
            violations.append(index)
    return tuple(violations)


# --- Propuesta del siguiente segmento (RF-015) ------------------------------

TERMINAL_MATCH_STATUSES = frozenset({"finished", "cancelled", "administrative_resolution"})
PUBLISHED_VERSION_STATUS = "published"
INTERRUPTED_SEGMENT = "interrupted"
COMPLETED_SEGMENT = "completed"


def _stored_value(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    """Lea un campo de una fila sea un ``Mapping`` o un objeto con atributos."""

    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _interruption_order(row: Mapping[str, Any] | Any) -> tuple[int, str, str]:
    """Clave determinista de una interrupción: ``(minute, created_at, id)``."""

    created_at = _stored_value(row, "created_at")
    interruption_id = _stored_value(row, "id")
    return (
        int(_stored_value(row, "minute") or 0),
        "" if created_at is None else str(created_at),
        "" if interruption_id is None else str(interruption_id),
    )


def next_segment_proposal(
    match_status: str | None,
    version_status: str | None,
    segments: Iterable[Mapping[str, Any] | Any],
    interruptions: Iterable[Mapping[str, Any] | Any],
) -> dict[str, Any] | None:
    """Propuesta del siguiente segmento derivada de lo persistido (RF-015, D-4).

    **No crea ni modifica nada**: es un cálculo de solo lectura sobre los
    segmentos y las interrupciones que la operación ya lee (RNF-008), sin
    consultas nuevas, sin reloj y sin automatismo (DU-9). El servidor sigue
    siendo la autoridad al crear un segmento (RF-013/RF-014), así que el
    operador siempre confirma.

    Devuelve ``None`` cuando no se podría crear ningún segmento: partido
    **terminal** (``finished``, ``cancelled`` o ``administrative_resolution``) o
    versión **no publicada** (D-7). ``suspended`` **sí** recibe propuesta,
    porque la ruta de creación de segmentos lo admite y negarla ofrecería menos
    de lo que el servidor permite.

    Si no hay segmentos, el primero del partido: ``{1, 0, derived: True}``. Con
    segmentos, ``segment_number`` es siempre el siguiente al último y
    ``minute_start``/``derived`` salen del último:

    * ``interrupted`` → el minuto de **su** interrupción más reciente, derivado;
    * ``completed`` con ``minute_end`` → ese fin, derivado;
    * ``active`` → ``minute_start`` nulo y ``derived`` falso: no hay nada de lo
      que derivarlo y lo indica el operador;
    * ``completed`` sin ``minute_end`` (posible en datos históricos) → igual,
      nulo y no derivado;
    * ``interrupted`` sin fila de interrupción (dato anómalo) → igual, nulo y no
      derivado, en vez de inventar el minuto.

    La función acepta ``mappings`` y objetos con atributos. Es determinista: el
    orden de entrada no importa (los segmentos se ordenan por
    ``segment_number`` y las interrupciones por ``(minute, created_at, id)``) y
    los desempates son estables (RNF-006).
    """

    if match_status in TERMINAL_MATCH_STATUSES:
        return None
    if version_status != PUBLISHED_VERSION_STATUS:
        return None

    ordered = sorted(
        segments,
        key=lambda row: int(_stored_value(row, "segment_number") or 0),
    )
    if not ordered:
        return {"segment_number": 1, "minute_start": 0, "derived": True}

    last = ordered[-1]
    segment_number = int(_stored_value(last, "segment_number") or 0) + 1
    status = _stored_value(last, "status")

    if status == INTERRUPTED_SEGMENT:
        last_id = _stored_value(last, "id")
        own = [
            row
            for row in interruptions
            if last_id is not None and _stored_value(row, "segment_id") == last_id
        ]
        if not own:
            return {"segment_number": segment_number, "minute_start": None, "derived": False}
        latest = max(own, key=_interruption_order)
        return {
            "segment_number": segment_number,
            "minute_start": int(_stored_value(latest, "minute") or 0),
            "derived": True,
        }

    if status == COMPLETED_SEGMENT:
        minute_end = _stored_value(last, "minute_end")
        if minute_end is None:
            return {"segment_number": segment_number, "minute_start": None, "derived": False}
        return {
            "segment_number": segment_number,
            "minute_start": int(minute_end),
            "derived": True,
        }

    # Activo (o cualquier otro estado sin base): lo indica el operador.
    return {"segment_number": segment_number, "minute_start": None, "derived": False}


class CloseMatchReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute(self, context: AuthContext, match_id: UUID, dto: CloseMatchReportDTO) -> dict[str, Any]:
        """Cierra el acta aplicando el **orden único** de validación (RF-001).

        Una petición con dos defectos de dominio informa el del paso anterior y
        no escribe nada; el orden no depende del orden del payload ni del orden
        en que las comprobaciones aparezcan escritas. Los **422 estructurales**
        del esquema se resuelven antes del handler y prevalecen sobre cualquier
        paso. La existencia y el aislamiento del partido se resuelven al
        cargarlo (**404** tanto si no existe como si es de otra organización),
        antes del permiso, y no cuentan como paso del orden de dominio. El
        walkover **sí tiene rama propia** desde la spec 016: se inserta después
        del paso 5 y omite los pasos 6 a 12 (ver :meth:`_execute_walkover`); la
        plantilla y los bloqueos de jugador se cargan después de ese punto, así
        que la rama no los consulta (D-6, RNF-008).
        """

        async with self.db.begin():
            # --- 1. Sesión, organización y aislamiento ----------------------
            await set_rls_context(self.db, context.organization_id, context.user_id)
            identity = await self._load_match_identity(context, match_id)
            # Orden de bloqueo declarado (RF-018): fase → versión → destinos de
            # avance → partido → segmento activo → jugadores. Los bloqueos no
            # son validación: el defecto se informa en su paso.
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

            # --- 2. Permiso (conjunción) ------------------------------------
            # `CLOSE_MATCH_REPORT` y, a la vez, rol operativo o asignación como
            # oficial del partido; la administrativa exige además dueño o
            # administrador (RF-002).
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

            # --- 3. Estado del partido y versión publicada -------------------
            if match["status"] in {"finished", "cancelled", "administrative_resolution", "suspended"}:
                if dto.resolution_type == "walkover":
                    # RF-001: el walkover se declara solo sobre los estados que
                    # hoy admiten cierre y los cuatro inadmisibles salen con su
                    # ``code`` aditivo, sin transición de estado nueva.
                    raise WalkoverStateNotAllowed(match["status"])
                raise ValueError(f"El estado {match['status']} no admite cierre normal")
            if match["version_status"] != "published":
                raise ValueError("La versión del torneo no está publicada")

            # --- 4. Dos equipos participantes -------------------------------
            if match["home_team_id"] is None or match["away_team_id"] is None:
                raise ValueError("El partido debe tener dos equipos participantes")

            # Bloqueo del segmento activo. Se lee aquí para respetar el orden de
            # bloqueo (fase → versión → destinos → partido → segmento →
            # jugadores); el defecto de «sin segmento activo» se informa en el
            # paso 6, y los bloqueos de jugador se toman después del paso 5.
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

            minutes = effective_match_minutes(match["rules_config"], match["stage_id"])

            # --- 5. Resolución habilitada por la configuración efectiva ------
            # El estado ya rechazó un acta cerrada, así que nada confirmado se
            # revalida (RF-035) y la configuración publicada solo se lee
            # (RF-036). Es el 409 unificado que comparten los tres puntos de
            # operación (P5, RF-032).
            if not resolution_enabled(minutes, dto.resolution_type):
                raise ResolutionNotEnabled()

            # --- 13′/14′. Rama del walkover (spec 016) ----------------------
            # Se **inserta** aquí: los pasos 1-5 son los de la 017 y no se
            # reordena nada. La rama omite los pasos 6 (segmento activo,
            # segmentos, tiempos e intervalo), 7 (participantes de los eventos
            # y plantilla), 8 (estado en campo y sustituciones), 9 (asistente),
            # 10 (doble amarilla), 11 (marcador contra eventos) y 12
            # (sanciones): un partido que no se juega no tiene acta que
            # validar (RF-003, RF-009). Las exenciones preexistentes de
            # `walkover` en `_validate_event_team_scope`,
            # `_validate_event_participants`, `_validate_substitutions` y
            # `_validate_event_score_consistency` quedan **inalcanzables** por
            # esta rama y se conservan como la exención de la resolución
            # administrativa y como defensa en profundidad.
            if dto.resolution_type == "walkover":
                return await self._execute_walkover(
                    context, match, dto, active_segment_row
                )

            # Plantilla, bloqueos de jugador y segmentos del camino normal. Van
            # **después** del paso 5 para que la rama no los consulte (D-6) y
            # el orden de bloqueo no cambia: partido → segmento → jugadores.
            rosters = await self._load_match_rosters(context, match_id)
            player_ids = sorted({row["player_id"] for row in rosters}, key=str)
            for player_id in player_ids:
                await self._lock_player(match["tournament_id"], player_id)
            segments = await self._load_match_segments(context, match_id)

            # --- 6. Estructura del acta: segmento activo, segmentos, tiempos,
            #        intervalo y máximo efectivo -----------------------------
            if active_segment is None:
                raise ValueError("El partido necesita un segmento activo antes de cerrar el acta")
            self._validate_segments(dto, segments, minutes)

            # --- 7. Participantes y plantilla -------------------------------
            # La regla de identificadores es única (RF-020): un equipo o
            # beneficiario de **otra organización** es 404 y se resuelve antes
            # del 409 de «no participa»; un jugador de otra organización sigue
            # siendo 409.
            await self._validate_event_team_scope(context, dto, match)
            self._validate_event_participants(dto, match, rosters)
            self._validate_rosters(match, rosters)

            # --- 8. Estado en campo y sustituciones --------------------------
            # El motor puro los valida antes de escribir (RF-005). Primero el
            # paso 8 —estado en campo, sustituciones, ventanas, reentrada y
            # minutos de plantilla—, que se informa aunque su defecto aparezca
            # después en el acta que un asistente inválido.
            limits = SubstitutionLimits.from_config(
                effective_substitutions(match["rules_config"])
            )
            # --- 9. Asistente del gol ---------------------------------------
            # La misma llamada informa después el asistente (409 con su código),
            # solo si el paso 8 no falló: el replay retiene ese error y lo lanza
            # al terminar su única pasada (RF-001).
            self._validate_substitutions(dto, match, rosters, limits)

            # --- 10. Coherencia disciplinaria (doble amarilla) --------------
            # Puro y sobre el acta de la **petición**: una roja marcada como
            # doble amarilla exige exactamente dos amarillas previas del mismo
            # jugador en el mismo partido (RF-006). No deriva rojas (DU-10) y no
            # escribe (el defecto es 409 con su código).
            self._validate_double_yellow(dto)

            # --- 11. Marcador frente a eventos ------------------------------
            self._validate_event_score_consistency(
                dto,
                match["home_team_id"],
                match["away_team_id"],
                regular_time_minutes=minutes["regular_time_minutes"],
            )

            # --- 12. Sanciones vigentes de la plantilla ---------------------
            await self._validate_suspensions(context, match["tournament_id"], player_ids)

            # --- 13. Coherencia de la resolución y del ganador --------------
            # El resultado se calcula **antes de escribir** (RF-007, RF-009) y
            # sobre los eventos de la **petición**, no sobre los persistidos.
            # Es equivalente por la reutilización idempotente (RF-008): el paso
            # 14 solo reutiliza una fila existente cuando es idéntica (tipo,
            # equipo, beneficiario, jugadores, minuto, segmento, `metadata` y
            # asistente) y responde **409** «inmutable» si difiere; para el
            # marcador solo cuentan `event_type`, `team_id` y
            # `beneficiary_team_id` (`_goal_credit`), que esa comparación
            # cubre. Un acta inválida no deja ninguna escritura.
            outcome = compute_match_outcome(
                match["rules_config"],
                self._request_events(dto),
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

            # --- 14. Escritura atómica, clasificación, avance, auditoría y
            #         outbox ---------------------------------------------------

            persisted_events = await self._persist_events(context, match, dto, rosters, segments)
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

            # Sanciones (spec 018): solo los eventos de este acta originan. La
            # absorción ocurre dentro de la función pura; **después** se aplica
            # la unicidad por evento de roja —una sola lectura acotada a las
            # rojas del acta, que no se ejecuta si no hay ninguna— y por último
            # se insertan las que quedan.
            history = await self._load_discipline_history(context, match)
            suspensions = evaluate_suspensions(
                match["rules_config"], persisted_events, history
            )
            red_event_ids = [
                event["id"] for event in persisted_events if event["event_type"] == "red_card"
            ]
            recorded_red_sanctions = await self._load_recorded_red_suspensions(
                context, red_event_ids
            )
            suspensions = drop_recorded_red_sanctions(suspensions, recorded_red_sanctions)
            await self._serve_suspensions(context, match)
            created_suspensions = await self._insert_suspensions(
                context, match, suspensions
            )
            await self._recalculate_standings(context, match)
            await self._advance_bracket(context, match_id, match, outcome)

            audit_payload = {
                "previous_status": match["status"],
                "final_status": target_status,
                "tournament_version_id": str(match["tournament_version_id"]),
                "outcome": outcome.__dict__,
                "event_ids": [str(event["id"]) for event in persisted_events],
                "suspensions": len(created_suspensions),
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

    async def _execute_walkover(
        self,
        context: AuthContext,
        match: Mapping[str, Any],
        dto: CloseMatchReportDTO,
        active_segment_row: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Rama del walkover: pasos 13′ y 14′ del orden único (spec 016).

        La llama :meth:`execute` **después** del paso 5 y antes de cargar la
        plantilla, así que los pasos 1-5 (sesión y aislamiento, autorización,
        estado y versión, dos equipos y resolución habilitada) ya se cumplieron
        y esta rama **omite** el resto del tronco:

        | Paso | Qué valida el tronco | Walkover |
        |---|---|---|
        | 6 | segmento activo, segmentos, tiempos e intervalo | **no se ejecuta** (RF-003) |
        | 7 | participantes de los eventos, plantilla (`_validate_rosters`) | **no se ejecuta** (RF-003) |
        | 8 | estado en campo y sustituciones | **no se ejecuta** (RF-003) |
        | 9 | asistente del gol | **no se ejecuta** |
        | 10 | doble amarilla | **no se ejecuta** (no hay eventos) |
        | 11 | marcador contra eventos | **no se ejecuta** (no hay eventos) |
        | 12 | sanciones vigentes de la plantilla | **no se ejecuta** (RF-009) |
        | 13′ | marcador derivado, pareja coherente, desajuste informado y motor | **sí** |
        | 14′ | escritura atómica, segmento activo, clasificación, avance, auditoría y outbox | **sí**, sin eventos, sin proyección por segmento y sin sanciones |

        No consulta plantilla, alineación, contadores ni sanciones y no toma
        bloqueos de jugador (D-6, RNF-008); el partido y el segmento activo ya
        están bloqueados por :meth:`execute`. El orden de los defectos es
        estable (RNF-006): participación del ganador → pareja incoherente
        (`WALKOVER_CONFIG_INCONSISTENT`, D-4) → marcador informado distinto
        (`WALKOVER_SCORE_MISMATCH`). Todo se calcula **antes de escribir**, así
        que un 409 no deja ninguna fila.
        """

        match_id = match["id"]
        pair = derive_walkover_score(
            match["rules_config"],
            match["stage_id"],
            match["home_team_id"],
            match["away_team_id"],
            dto.winner_team_id,
        )
        if pair is None:
            # Mismo mensaje que el motor: el defecto es de participantes y no
            # lleva ``code`` (plan §6.2).
            raise ValueError("El ganador informado no participa en el partido")
        # D-4: la guarda de la pareja va **antes** que la comprobación del
        # marcador informado. El motor aceptaría la pareja incoherente (solo la
        # compara con la configurada) y la clasificación daría la victoria al
        # otro equipo; al revés, el 409 del motor ganaría y se perdería el
        # ``code`` y la salida documentada (la resolución administrativa).
        if not pair.is_coherent:
            raise WalkoverConfigInconsistent(pair.winner_score, pair.loser_score)
        # D-10: un marcador informado que coincide se acepta (un cliente antiguo
        # sigue funcionando); uno distinto es el 409 aditivo y no se escribe.
        informed_pair = (
            ("home_score_regular", pair.home_score),
            ("away_score_regular", pair.away_score),
            ("home_score", pair.home_score),
            ("away_score", pair.away_score),
        )
        for field_name, expected in informed_pair:
            value = getattr(dto, field_name)
            if value is not None and value != expected:
                raise WalkoverScoreMismatch(pair.winner_score, pair.loser_score)

        # Paso 13′: el motor sigue siendo la autoridad del desenlace (D-3).
        # Revalida la participación del ganador, la pareja frente a la
        # configuración publicada y devuelve el resultado; sin eventos, el
        # marcador es exactamente el derivado.
        outcome = compute_match_outcome(
            match["rules_config"],
            [],
            "walkover",
            match["home_team_id"],
            match["away_team_id"],
            pair.home_score,
            pair.away_score,
            pair.home_score,
            pair.away_score,
            None,
            None,
            dto.winner_team_id,
        )
        if requires_decisive_winner(match.get("bracket_code")) and outcome.winner_team_id is None:
            raise ValueError("La gran final de doble eliminación debe tener un ganador")

        final_status = "finished"
        await self.db.execute(
            text("""
                UPDATE matches
                SET home_score_regular = :home_score_regular,
                    away_score_regular = :away_score_regular,
                    home_score = :home_score,
                    away_score = :away_score,
                    home_penalties = NULL,
                    away_penalties = NULL,
                    winner_team_id = :winner_team_id,
                    status = :status,
                    resolution_type = 'walkover',
                    resolution_reason = :resolution_reason,
                    result_confirmed = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :match_id AND organization_id = :organization_id
            """),
            {
                "home_score_regular": outcome.home_score,
                "away_score_regular": outcome.away_score,
                "home_score": outcome.home_score,
                "away_score": outcome.away_score,
                "winner_team_id": str(outcome.winner_team_id) if outcome.winner_team_id else None,
                "status": final_status,
                # RF-007: el motivo es el **código** del catálogo cerrado, que
                # la API ya validó; la migración 027 es la que lo admite en la
                # columna para una resolución que no es la administrativa.
                "resolution_reason": dto.reason,
                "match_id": str(match_id),
                "organization_id": str(context.organization_id),
            },
        )
        if active_segment_row is not None:
            # RF-004: el activo se cierra en **su** minuto de inicio, porque un
            # walkover no registra eventos de los que derivar un final. Los
            # completados y los interrumpidos no se tocan y no se crea ninguno.
            await self.db.execute(
                text("""
                    UPDATE match_segments
                    SET status = 'completed',
                        minute_end = COALESCE(minute_end, :minute_end)
                    WHERE id = :segment_id AND organization_id = :organization_id
                """),
                {
                    "segment_id": str(active_segment_row["id"]),
                    "organization_id": str(context.organization_id),
                    "minute_end": int(active_segment_row["minute_start"]),
                },
            )

        # RF-009 y RNF-008: no se llama a `_validate_suspensions`,
        # `_load_discipline_history`, `_load_recorded_red_suspensions`,
        # `_serve_suspensions`, `_insert_suspensions`,
        # `_rewrite_segment_team_state` ni `_persist_events`. Un partido que no
        # se juega no cumple sanciones, no tiene eventos y no aporta información
        # nueva a la proyección por segmento (RF-013 de la spec 018: la lectura
        # acotada a las rojas del acta tampoco se ejecuta en esta rama).
        await self._recalculate_standings(context, match)
        await self._advance_bracket(context, match_id, match, outcome)

        audit_payload = {
            "previous_status": match["status"],
            "final_status": final_status,
            "tournament_version_id": str(match["tournament_version_id"]),
            "resolution_type": "walkover",
            # RNF-010: el contenido incluye resolución, ganador, marcador y
            # motivo; el motivo va en la raíz (D-12) además de en la petición.
            "resolution_reason": dto.reason,
            "walkover_score": {
                "home": pair.home_score,
                "away": pair.away_score,
            },
            "outcome": outcome.__dict__,
            "event_ids": [],
            "suspensions": 0,
            "request": dto.model_dump(mode="json"),
        }
        await self.db.execute(
            text("""
                INSERT INTO administrative_audit_logs
                    (organization_id, entity_type, entity_id, action, payload, performed_by_member_id)
                VALUES (:organization_id, 'matches', :match_id, :action, CAST(:payload AS jsonb), :member_id)
            """),
            {
                "organization_id": str(context.organization_id),
                "match_id": str(match_id),
                "action": "CLOSE_MATCH_REPORT",
                "payload": json.dumps(audit_payload, default=str),
                "member_id": str(context.organization_user_id),
            },
        )
        event_payload = json.dumps(
            {"match_id": str(match_id), "tournament_id": str(match["tournament_id"])}
        )
        # RNF-011: exactamente los mismos tres eventos que un cierre normal.
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
                # Regla única de identificadores (RF-014): un segmento que no
                # existe en este partido y organización se resuelve con 404, sin
                # revelar existencia. El router lo mapea por ``LookupError``.
                raise LookupError("Segmento no encontrado en el partido")
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

    async def _validate_event_team_scope(
        self,
        context: AuthContext,
        dto: CloseMatchReportDTO,
        match: Mapping[str, Any],
    ) -> None:
        """Single identifier rule for the teams named by the events (RF-014).

        A team of another organization is **404** (existence is never revealed);
        a team of the organization that does not play this match keeps the
        **409** it already had. The lookup only runs when some event names a team
        that is not a participant, so a normal report adds no query. Walkover and
        administrative resolutions admit no events, and their own 409 keeps
        precedence.
        """

        if dto.resolution_type in {"walkover", "administrative"}:
            return
        participants = {match["home_team_id"], match["away_team_id"]}
        named = set()
        for event in dto.events:
            named.add(event.team_id)
            if event.beneficiary_team_id is not None:
                named.add(event.beneficiary_team_id)
        foreign = {team_id for team_id in named if team_id not in participants}
        if not foreign:
            return
        result = await self.db.execute(
            text("""
                SELECT id
                FROM teams
                WHERE organization_id = :organization_id
                  AND id = ANY(CAST(:team_ids AS uuid[]))
            """),
            {
                "organization_id": str(context.organization_id),
                "team_ids": [team_id for team_id in sorted(foreign, key=str)],
            },
        )
        known = {row["id"] for row in result.mappings().all()}
        if foreign - known:
            raise LookupError("Equipo no encontrado")

    @staticmethod
    def _validate_event_participants(
        dto: CloseMatchReportDTO,
        match: Mapping[str, Any],
        rosters: Iterable[Mapping[str, Any]],
    ) -> None:
        """Participantes y elegibilidad de cada evento del acta (RF-004).

        Puro: lee la plantilla que ya se cargó con sus bloqueos de jugador y no
        escribe nada. Un evento de un equipo que no juega, de un jugador fuera
        de la plantilla válida o del equipo indicado, antes de entrar o después
        de salir, y un beneficiario que no participa son el **409** de este
        paso. La **existencia** de un equipo de otra organización no se decide
        aquí: es el **404** de :meth:`_validate_event_team_scope`, que corre
        antes (regla única de identificadores, RF-020).
        """

        if dto.resolution_type in {"walkover", "administrative"}:
            return
        participants = {match["home_team_id"], match["away_team_id"]}
        roster_by_player = {row["player_id"]: row for row in rosters}
        for event in dto.events:
            if event.team_id not in participants:
                # Mismo código y mensaje que el replay del motor: el defecto es
                # de participantes, no una regla nueva de este paso.
                raise SubstitutionError(
                    SubstitutionErrorCode.TEAM_MISMATCH,
                    "El evento pertenece a un equipo que no participa en el partido",
                )
            if event.beneficiary_team_id is not None and event.beneficiary_team_id not in participants:
                raise ValueError("El equipo beneficiario no participa en el partido")
            roster = roster_by_player.get(event.player_id)
            if roster is None or roster["team_id"] != event.team_id:
                raise SubstitutionError(
                    SubstitutionErrorCode.PLAYER_NOT_IN_ROSTER,
                    f"El jugador {event.player_id} no está en la plantilla del equipo",
                )
            if roster["entered_minute"] is not None and event.minute < roster["entered_minute"]:
                raise ValueError("El evento ocurre antes de la entrada del jugador")
            if roster["left_minute"] is not None and event.minute > roster["left_minute"]:
                raise ValueError("El evento ocurre después de la salida del jugador")

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

        Cubre los pasos **8** (estado en campo y sustituciones) y **9**
        (asistente del gol) con una sola pasada del motor: el replay informa
        primero cualquier violación del paso 8, aunque el asistente inválido
        esté en un minuto anterior, y solo después la del asistente (RF-001).
        """

        if dto.resolution_type in {"walkover", "administrative"}:
            return
        try:
            replay_report_state(
                rosters,
                [
                    MatchEvent.from_mapping(event.model_dump(), index=index)
                    for index, event in enumerate(dto.events)
                ],
                (match["home_team_id"], match["away_team_id"]),
                limits,
            )
        except SubstitutionError as error:
            # D-8: el motor puro no importa HTTP. Solo el código del asistente
            # gana el ``code`` aditivo; el resto conserva su 409 de pertenencia.
            if error.code is SubstitutionErrorCode.ASSIST_PLAYER_INVALID:
                raise AssistPlayerInvalid(str(error)) from error
            raise

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
    def _validate_double_yellow(dto: CloseMatchReportDTO) -> None:
        """Coherencia de la doble amarilla del acta (paso 10, RF-006).

        La regla es :func:`double_yellow_violations`: exactamente dos amarillas
        previas del mismo jugador en el orden canónico del acta. Se informa la
        primera violación en ese orden (RF-001) con el minuto de la roja y sin
        nombres (RNF-002). El walkover y la administrativa no admiten eventos
        (422 del esquema), así que la función devuelve el acta vacía sin
        violaciones y no hace falta una rama propia.
        """

        violations = double_yellow_violations(dto.events)
        if not violations:
            return
        red_card = dto.events[violations[0]]
        raise DoubleYellowInconsistent(
            "La roja por doble amarilla del minuto "
            f"{red_card.minute} no tiene exactamente dos amarillas previas del "
            "mismo jugador"
        )

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

    @staticmethod
    def _request_events(dto: CloseMatchReportDTO) -> list[dict[str, Any]]:
        """Los eventos de la petición con la forma que consume el motor puro.

        `compute_match_outcome` solo lee `event_type`, `team_id` y
        `beneficiary_team_id` de cada gol (`_goal_credit`); el resto de campos
        del evento no interviene en el marcador.
        """

        return [
            {
                "event_type": event.event_type,
                "team_id": event.team_id,
                "beneficiary_team_id": event.beneficiary_team_id,
            }
            for event in dto.events
        ]

    async def _persist_events(self, context, match, dto, rosters, segments) -> list[dict[str, Any]]:
        """Write the report's events (step 14).

        Participants, roster eligibility, the segment interval and the
        beneficiary were already validated in steps 6 and 7: a persisted event
        can no longer break them. The defensive checks that remain are the ones
        the pure schema already answers before the handler.
        """

        match_id = match["id"]
        segment_statuses = {row["id"]: row["status"] for row in segments}
        segments_by_id = {row["id"]: row for row in segments}
        persisted: list[dict[str, Any]] = []
        seen_client_event_ids: set[str] = set()
        for event in dto.events:
            client_event_id = canonical_client_event_id(event.client_event_id)
            if client_event_id in seen_client_event_ids:
                raise ValueError("No se permiten client_event_id duplicados en la misma acta")
            seen_client_event_ids.add(client_event_id)
            if dto.resolution_type in {"walkover", "administrative"}:
                raise ValueError("Esta resolución no permite eventos individuales")
            if segment_statuses.get(event.segment_id) not in {"active", "completed"}:
                raise ValueError("No se pueden registrar eventos en un segmento interrumpido")
            segment = segments_by_id[event.segment_id]
            if event.minute < segment["minute_start"] or (
                segment["minute_end"] is not None and event.minute > segment["minute_end"]
            ):
                raise ValueError("El evento está fuera del intervalo de su segmento")

            existing_result = await self.db.execute(
                text("""
                    SELECT id, event_type, team_id, beneficiary_team_id, player_id,
                           player_out_id, player_in_id, minute, added_minute, segment_id,
                           assist_player_id, metadata
                    FROM match_events
                    WHERE organization_id = :organization_id
                      AND match_id = :match_id
                      AND client_event_id = :client_event_id
                """),
                {
                    "organization_id": str(context.organization_id),
                    "match_id": str(match_id),
                    "client_event_id": client_event_id,
                },
            )
            existing = existing_result.mappings().one_or_none()
            if existing:
                # La comparación cubre todo lo que el evento declara (RF-012):
                # `metadata` con `{}` ↔ `None` normalizado (D-10) y la
                # asistencia, que antes no existía.
                if any(
                    existing[key] != event_value
                    for key, event_value in {
                        "event_type": event.event_type,
                        "team_id": event.team_id,
                        "beneficiary_team_id": event.beneficiary_team_id,
                        "player_id": event.player_id,
                        "player_out_id": event.player_out_id,
                        "player_in_id": event.player_in_id,
                        "minute": event.minute,
                        "added_minute": event.added_minute,
                        "segment_id": event.segment_id,
                        "assist_player_id": event.assist_player_id,
                    }.items()
                ) or normalize_event_metadata(
                    existing["metadata"]
                ) != normalize_event_metadata(event.metadata):
                    raise ValueError(f"El evento {client_event_id} es inmutable")
                persisted.append(dict(existing))
                continue

            result = await self.db.execute(
                text("""
                    INSERT INTO match_events
                        (organization_id, match_id, segment_id, team_id, beneficiary_team_id, player_id,
                         player_out_id, player_in_id, assist_player_id,
                         event_type, minute, added_minute, client_event_id, metadata)
                    VALUES (:organization_id, :match_id, :segment_id, :team_id, :beneficiary_team_id, :player_id,
                            :player_out_id, :player_in_id, :assist_player_id,
                            :event_type, :minute, :added_minute, :client_event_id, CAST(:metadata AS jsonb))
                    RETURNING id, event_type, team_id, beneficiary_team_id, player_id,
                              player_out_id, player_in_id, assist_player_id,
                              minute, added_minute, segment_id, metadata
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
                    "assist_player_id": str(event.assist_player_id) if event.assist_player_id else None,
                    "event_type": event.event_type,
                    "minute": event.minute,
                    "added_minute": event.added_minute,
                    "client_event_id": client_event_id,
                    "metadata": json.dumps(event.metadata or {}),
                },
            )
            persisted.append(dict(result.mappings().one()))
        return persisted

    async def _load_discipline_history(self, context, match):
        """Historial disciplinario del ámbito que resuelve el `WHERE` (RF-008).

        Devuelve también `match_id`, `match_date`, `minute` y `added_minute`
        para que `order_discipline_history` (motor puro) sea total: la consulta
        no ordena (D-8). El filtro de ámbito —fase y versión con el reinicio
        activo— **no** cambia: el reinicio de fase se aplica aquí, antes de
        contar (RF-008).
        """

        result = await self.db.execute(
            text("""
                SELECT me.id, me.player_id, me.event_type, me.metadata,
                       me.match_id, m.match_date, me.minute, me.added_minute
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

    async def _load_recorded_red_suspensions(self, context, red_event_ids) -> set[str]:
        """Eventos de roja del acta que **ya** tienen una sanción registrada.

        Una sola lectura acotada al conjunto de rojas del acta en cierre
        (RNF-010): no depende del historial, del tamaño del torneo ni del número
        de jugadores, y **no se ejecuta** cuando el acta no tiene rojas. Sin
        filtro de `status`: una fila `served`, `cancelled` o `appealed` también
        cuenta, porque la unicidad es por evento de roja y no por motivo
        (RF-005, R-3). Corre dentro de la transacción del cierre, con RLS y
        `organization_id` explícito (RNF-001).
        """

        if not red_event_ids:
            return set()
        result = await self.db.execute(
            text("""
                SELECT DISTINCT source_event_id
                FROM player_suspensions
                WHERE organization_id = :organization_id
                  AND source_event_id = ANY(CAST(:red_event_ids AS uuid[]))
            """),
            {
                "organization_id": str(context.organization_id),
                "red_event_ids": [str(event_id) for event_id in red_event_ids],
            },
        )
        return {str(row["source_event_id"]) for row in result.mappings().all()}

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

    async def _insert_suspensions(self, context, match, suspensions) -> list[dict[str, Any]]:
        """Inserta las sanciones derivadas y devuelve las filas **creadas**.

        `ON CONFLICT (dedupe_key) DO NOTHING` sigue siendo la red de seguridad
        (D-4) y `RETURNING id` distingue lo insertado de lo omitido: la
        auditoría cuenta filas reales y no el tamaño de la lista derivada
        (RF-012, D-6).
        """

        created: list[dict[str, Any]] = []
        for suspension in suspensions:
            dedupe_key = f"{match['tournament_id']}:{suspension['player_id']}:{suspension['source_event_id']}:{suspension['reason']}"
            result = await self.db.execute(
                text("""
                    INSERT INTO player_suspensions
                        (organization_id, source_tournament_id, player_id, origin_match_id, source_event_id,
                         source_type, dedupe_key, scope_type, matches_suspended, reason)
                    VALUES (:organization_id, :tournament_id, :player_id, :match_id, :source_event_id,
                            'match_event', :dedupe_key, :scope_type, :matches_suspended, :reason)
                    ON CONFLICT (dedupe_key) DO NOTHING
                    RETURNING id
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
            created.extend(dict(row) for row in result.mappings().all())
        return created

    async def _recalculate_standings(self, context, match):
        from app.modules.standings.service import StandingsService

        await StandingsService(self.db).recalculate(context, match["tournament_id"], match["stage_id"])

    async def _advance_bracket(self, context, match_id, match, outcome):
        advancement = AdvancementService(self.db)
        await advancement.advance_from_match(context, match_id, match, outcome)
        await advancement.activate_double_elimination_reset(context, match, outcome)
