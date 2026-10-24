/**
 * Límites de plantilla y estado por equipo (spec 012, RF-044, RF-045, RF-046,
 * RF-051, RL-1, RA-1).
 *
 * **Espejo declarado de las funciones puras del servidor.** El cálculo de los
 * límites efectivos y de los tres estados replica `effective_roster_limits` y
 * `roster_size_state` de `backend/app/modules/tournaments/roster_status.py`
 * para poder mostrar el estado y explicar el botón de inscribir antes de
 * escribir. La autoridad sigue siendo el servidor: el cliente nunca sustituye
 * ni relaja las tres superficies de bloqueo (inscribir en fase, alta con fase
 * destino y apertura del partido) ni la validación del retiro y la
 * reactivación; si esta descripción se equivoca, manda el 409 real.
 *
 * `0` (o la clave ausente) significa **sin límite**, de modo que una
 * configuración anterior a las claves conserva el comportamiento actual.
 *
 * El módulo es puro: no lee el reloj, el entorno, el almacenamiento ni la red.
 * La traducción entra como función (`t`), nunca como texto fijo.
 */

export const ROSTER_STATE_OK = 'ok';
export const ROSTER_STATE_BELOW = 'below';
export const ROSTER_STATE_ABOVE = 'above';

export type RosterSizeState =
  | typeof ROSTER_STATE_OK
  | typeof ROSTER_STATE_BELOW
  | typeof ROSTER_STATE_ABOVE;

export interface RosterLimits {
  /** Mínimo de jugadores activos; `0` significa sin límite. */
  readonly min: number;
  /** Máximo de jugadores activos; `0` significa sin límite. */
  readonly max: number;
}

/** Traducción con parámetros, como la que ofrece `useI18n()`. */
export type RosterTranslate = (
  key: string,
  values?: Record<string, string | number>,
) => string;

export interface RosterSizeDescription {
  readonly state: RosterSizeState;
  readonly count: number;
  readonly limits: RosterLimits;
  readonly labelKey: string;
  readonly label: string;
  readonly detailKey: string;
  readonly detail: string;
  readonly minLabel: string;
  readonly maxLabel: string;
}

export interface RosterEnrollmentInput {
  readonly teamId: string;
  readonly teamName: string;
  readonly count: number;
  readonly limits: RosterLimits;
  /**
   * Si el cierre de inscripción por jornada está activo (RL-1). Con la
   * plantilla por debajo del mínimo, añadir jugadores está cerrado y el mensaje
   * lo explica sin prometer una salida que no existe.
   */
  readonly lockActive?: boolean;
}

export interface RosterEnrollmentExplanation extends RosterEnrollmentInput {
  readonly blocked: boolean;
  readonly state: RosterSizeState;
  /** Jugadores que faltan para el mínimo; `0` cuando no aplica. */
  readonly missing: number;
  /** Jugadores que sobran sobre el máximo; `0` cuando no aplica. */
  readonly excess: number;
  readonly messageKey: string | null;
  readonly message: string;
}

export type RosterStatusAction = 'retire' | 'reactivate';

export interface RosterStatusGuidance {
  readonly action: RosterStatusAction;
  /** `true` cuando la acción suma un jugador activo y la jornada la alcanza. */
  readonly lockApplies: boolean;
  /** Aviso local que se muestra antes de intentar la acción, si procede. */
  readonly hintKey: string | null;
}

/** Claves de las tres etiquetas; el barrido i18n las detecta como tabla. */
export const ROSTER_SIZE_STATE_LABEL_KEYS = {
  ok: 'rosterLimits.state.ok',
  below: 'rosterLimits.state.below',
  above: 'rosterLimits.state.above',
} as const;

/** Claves de respaldo de las dos direcciones de la escritura de actividad. */
export const ROSTER_STATUS_FAILURE_LABEL_KEYS = {
  retire: 'tournament.rosters.retireFailed',
  reactivate: 'tournament.rosters.reactivateFailed',
} as const;

const ENROLLMENT_MESSAGE_LABEL_KEYS = {
  below: 'rosterLimits.enroll.below',
  belowLocked: 'rosterLimits.enroll.belowLocked',
  above: 'rosterLimits.enroll.above',
} as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Normaliza un límite configurado igual que el servidor: ausente, `null`, `0`,
 * negativo o no entero significa «sin límite». La validación de rango se hizo
 * al guardar las reglas (RF-044); esto solo protege a quien muestra el estado.
 */
export function rosterLimitValue(raw: unknown): number {
  if (raw === null || raw === undefined || typeof raw === 'boolean') return 0;
  if (typeof raw === 'number') {
    if (!Number.isFinite(raw)) return 0;
    const value = Math.trunc(raw);
    return value > 0 ? value : 0;
  }
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (!/^[+-]?\d+$/.test(trimmed)) return 0;
    const value = Number.parseInt(trimmed, 10);
    return value > 0 ? value : 0;
  }
  return 0;
}

/** Límites efectivos de una configuración de reglas; `0` = sin límite. */
export function effectiveRosterLimits(
  config: Record<string, unknown> | null | undefined,
): RosterLimits {
  if (!isRecord(config)) return { min: 0, max: 0 };
  return {
    min: rosterLimitValue(config.min_players_per_team),
    max: rosterLimitValue(config.max_players_per_team),
  };
}

/** `true` cuando al menos un lado del rango está configurado. */
export function hasRosterLimits(limits: RosterLimits): boolean {
  return limits.min > 0 || limits.max > 0;
}

/**
 * Estado de una plantilla: `below` por debajo del mínimo, `above` por encima
 * del máximo y `ok` en cualquier otro caso (RF-046).
 */
export function rosterSizeState(count: number, limits: RosterLimits): RosterSizeState {
  const total = Number.isFinite(count) ? Math.trunc(count) : 0;
  if (limits.min > 0 && total < limits.min) return ROSTER_STATE_BELOW;
  if (limits.max > 0 && total > limits.max) return ROSTER_STATE_ABOVE;
  return ROSTER_STATE_OK;
}

/** Etiqueta i18n del estado; nunca texto fijo. */
export function rosterSizeLabelKey(state: RosterSizeState): string {
  return ROSTER_SIZE_STATE_LABEL_KEYS[state];
}

/** Un límite en 0 se presenta como «sin límite» (RF-045). */
export function rosterLimitLabel(value: number, t: RosterTranslate): string {
  return value > 0 ? String(value) : t('rosterLimits.noLimit');
}

/** Descripción completa del estado de una plantilla para pintarlo. */
export function describeRosterSize(
  count: number,
  limits: RosterLimits,
  t: RosterTranslate,
): RosterSizeDescription {
  const state = rosterSizeState(count, limits);
  const minLabel = rosterLimitLabel(limits.min, t);
  const maxLabel = rosterLimitLabel(limits.max, t);
  return {
    state,
    count,
    limits,
    labelKey: ROSTER_SIZE_STATE_LABEL_KEYS[state],
    label: t(ROSTER_SIZE_STATE_LABEL_KEYS[state]),
    detailKey: 'rosterLimits.detail',
    detail: t('rosterLimits.detail', { count, min: minLabel, max: maxLabel }),
    minLabel,
    maxLabel,
  };
}

/**
 * Explicación del botón de inscribir bloqueado (RF-046): nombra el equipo, la
 * cantidad actual y el lado del rango que no se cumple, e indica cuántos
 * jugadores faltan o sobran. Un equipo dentro del rango no tiene explicación.
 */
export function explainRosterEnrollment(
  input: RosterEnrollmentInput,
  t: RosterTranslate,
): RosterEnrollmentExplanation {
  const state = rosterSizeState(input.count, input.limits);
  if (state === ROSTER_STATE_BELOW) {
    const missing = Math.max(0, input.limits.min - input.count);
    // RF-045/RL-1: con el cierre activo no se puede añadir a nadie; el mensaje
    // nombra la causa y la única vía disponible (el retiro lógico), sin
    // prometer altas que el servidor rechazará.
    const messageKey = input.lockActive
      ? ENROLLMENT_MESSAGE_LABEL_KEYS.belowLocked
      : ENROLLMENT_MESSAGE_LABEL_KEYS.below;
    return {
      ...input,
      blocked: true,
      state,
      missing,
      excess: 0,
      messageKey,
      message: t(messageKey, {
        team: input.teamName,
        count: input.count,
        min: input.limits.min,
        missing,
      }),
    };
  }
  if (state === ROSTER_STATE_ABOVE) {
    const excess = Math.max(0, input.count - input.limits.max);
    const messageKey = ENROLLMENT_MESSAGE_LABEL_KEYS.above;
    return {
      ...input,
      blocked: true,
      state,
      missing: 0,
      excess,
      messageKey,
      message: t(messageKey, {
        team: input.teamName,
        count: input.count,
        max: input.limits.max,
        excess,
      }),
    };
  }
  return {
    ...input,
    blocked: false,
    state,
    missing: 0,
    excess: 0,
    messageKey: null,
    message: '',
  };
}

/**
 * Qué se puede hacer con la actividad de una fila (RF-051):
 *
 * - **Retiro (RL-1):** exento del bloqueo por jornada, porque solo reduce la
 *   plantilla; no tiene aviso ni restricción adicional.
 * - **Reactivación (RA-1):** suma un jugador activo, así que se comporta como
 *   un alta. Con el cierre activo se muestra el aviso y el 409 real del alta
 *   sigue siendo la autoridad; sin cierre, el botón se ofrece normalmente.
 */
export function rosterStatusGuidance(
  action: RosterStatusAction,
  options: { readonly lockActive?: boolean } = {},
): RosterStatusGuidance {
  if (action === 'retire') {
    return { action, lockApplies: false, hintKey: null };
  }
  return {
    action,
    lockApplies: true,
    hintKey: options.lockActive ? 'tournament.rosters.reactivateLocked' : null,
  };
}

/** Clave de respaldo cuando el servidor responde un 409 sin detalle visible. */
export function rosterStatusFailureKey(action: RosterStatusAction): string {
  return ROSTER_STATUS_FAILURE_LABEL_KEYS[action];
}

// ---------------------------------------------------------------------------
// Apertura del partido bloqueada por tamaño (spec 012, H4-T09: RF-050, RF-046).
//
// El servidor rechaza el **primer** segmento con 409 `ROSTER_SIZE_OUT_OF_RANGE`
// cuando la plantilla de un participante está fuera de rango. El cliente no
// adelanta ese bloqueo: esta descripción se construye **solo** a partir de la
// respuesta y sirve para guiar (equipo, mínimo, máximo y cantidad, enlace a la
// plantilla y reintento). El `detail` del servidor se conserva literal como
// autoridad, de modo que la traducción nunca sustituye ni recorta el dato.
// ---------------------------------------------------------------------------

/** Claves i18n del aviso de apertura bloqueada; el barrido i18n las detecta. */
export const OPENING_BLOCKED_LABEL_KEYS = {
  title: 'rosterLimits.opening.title',
  reason: 'rosterLimits.opening.reason',
  team: 'rosterLimits.opening.team',
  serverDetail: 'rosterLimits.opening.serverDetail',
  retry: 'rosterLimits.opening.retry',
  retryAction: 'rosterLimits.opening.retryAction',
  openRoster: 'rosterLimits.opening.openRoster',
} as const;

/** Participante del partido con su plantilla activa tal como se cargó. */
export interface OpeningRosterParticipant {
  readonly teamId: string;
  readonly teamName: string;
  readonly count: number;
}

export interface OpeningBlockedTeam extends OpeningRosterParticipant {
  readonly state: RosterSizeState;
  readonly minLabel: string;
  readonly maxLabel: string;
  readonly messageKey: string;
  readonly message: string;
}

export interface OpeningBlockedInput {
  /** `detail` del 409; se muestra literal y manda sobre el recuento local. */
  readonly detail?: string | null;
  readonly limits: RosterLimits;
  /** Solo los participantes del partido, en el orden en que se muestran. */
  readonly participants: readonly OpeningRosterParticipant[];
}

export interface OpeningBlockedDescription {
  readonly detail: string;
  readonly limits: RosterLimits;
  /** Equipos implicados: los que se enlazan y se describen. */
  readonly teams: readonly OpeningBlockedTeam[];
}

function teamNamedInDetail(detail: string, teamName: string): boolean {
  const name = teamName.trim().toLocaleLowerCase();
  if (!name || !detail) return false;
  return detail.toLocaleLowerCase().includes(name);
}

/**
 * Equipos implicados en el rechazo de apertura (RF-050).
 *
 * Se unen las dos señales disponibles —fuera de rango según la plantilla
 * cargada y equipo nombrado en el `detail` del servidor— para no perder el
 * enlace cuando una de las dos está desactualizada. Sin ninguna señal se
 * ofrecen los dos participantes: es preferible un enlace de más a ninguno.
 * El estado y la cantidad son orientativos; el `detail` del servidor manda.
 */
export function describeOpeningBlocked(
  input: OpeningBlockedInput,
  t: RosterTranslate,
): OpeningBlockedDescription {
  const detail = typeof input.detail === 'string' ? input.detail : '';
  const participants = input.participants.filter((team) => Boolean(team.teamId && team.teamName));
  const implicated = participants.filter((team) => (
    rosterSizeState(team.count, input.limits) !== ROSTER_STATE_OK
    || teamNamedInDetail(detail, team.teamName)
  ));
  const selected = implicated.length ? implicated : participants;
  const minLabel = rosterLimitLabel(input.limits.min, t);
  const maxLabel = rosterLimitLabel(input.limits.max, t);

  return {
    detail,
    limits: input.limits,
    teams: selected.map((team) => ({
      ...team,
      state: rosterSizeState(team.count, input.limits),
      minLabel,
      maxLabel,
      messageKey: OPENING_BLOCKED_LABEL_KEYS.team,
      message: t(OPENING_BLOCKED_LABEL_KEYS.team, {
        team: team.teamName,
        count: team.count,
        min: minLabel,
        max: maxLabel,
      }),
    })),
  };
}
