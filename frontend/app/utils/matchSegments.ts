/**
 * Propuesta del siguiente segmento y mensajes del cierre (spec 017, RF-015,
 * RF-006).
 *
 * `GET /matches/{id}/operation` devuelve `next_segment`, que **calcula el
 * servidor** a partir de los segmentos y las interrupciones ya persistidos
 * (`next_segment_proposal`). Este módulo solo la **consume**: valida su forma,
 * decide qué campos del formulario se prerrellenan y no deriva nada por su
 * cuenta. El servidor sigue siendo la autoridad al crear el segmento (RF-013 y
 * RF-014): la propuesta se muestra, no se impone.
 *
 * Regla del minuto (D-5): el número del segmento es siempre el del servidor; el
 * minuto solo se escribe si la propuesta es derivada y el operador no lo ha
 * editado, o si el refresco lo fuerza (montaje y después de crear o interrumpir
 * un segmento). Un refresco normal —incluido el que provoca el socket— no pisa
 * lo que el operador está escribiendo.
 *
 * Todo es puro: no lee el reloj, la red, el almacenamiento ni el entorno, así
 * que las mismas entradas dan siempre el mismo resultado (RNF-008).
 */

import { classifyMatchConflict, type MatchConflictKind } from './matchResolution.ts';

/** Propuesta del siguiente segmento tal como la publica la operación (RF-015). */
export interface NextSegmentProposal {
  /** Siguiente número consecutivo; 1 si el partido no tiene segmentos. */
  readonly segment_number: number;
  /** Minuto de inicio derivado de lo persistido, o `null` si no hay base. */
  readonly minute_start: number | null;
  /** `true` si `minute_start` sale de lo persistido; `false` si lo indica el operador. */
  readonly derived: boolean;
}

/** Estado del formulario de segmento que la pantalla mantiene. */
export interface SegmentFormState {
  readonly segment_number: number;
  readonly minute_start: number;
  /** El operador ha escrito el minuto: un refresco normal no lo pisa. */
  readonly minuteDirty?: boolean;
}

/** Formulario resultante de aplicar la propuesta. */
export interface ResolvedSegmentForm {
  readonly segment_number: number;
  readonly minute_start: number;
  readonly minuteDirty: boolean;
}

/** Opciones de aplicación de la propuesta. */
export interface SegmentProposalOptions {
  /** Escribe el minuto propuesto aunque el operador lo haya editado. */
  readonly forceMinute?: boolean;
}

/** Origen del minuto propuesto (RF-015, RNF-007). */
export type SegmentProposalHintKind = 'derived' | 'manual';

/**
 * Claves i18n de la etiqueta accesible del origen del minuto. El nombre lleva
 * el sufijo `_LABEL_KEYS` y la tabla termina en `as const;` porque así la
 * resuelve el barrido de `utils/i18nCatalog` (`extractUsedKeys`); el tipo de
 * cada valor lo fija el uso tipado por `SegmentProposalHintKind`.
 */
export const SEGMENT_PROPOSAL_HINT_LABEL_KEYS = {
  derived: 'match.segmentProposalDerived',
  manual: 'match.segmentProposalManual',
} as const;

/**
 * Motivo del refresco de la operación:
 *
 * - `mount`: la primera carga de la pantalla.
 * - `refresh`: recarga manual o la que provoca el socket.
 * - `segment-changed`: el operador acaba de crear o interrumpir un segmento.
 */
export type SegmentRefreshCause = 'mount' | 'refresh' | 'segment-changed';

/**
 * `forceMinute` del refresco (D-5): solo al montar y tras crear o interrumpir
 * un segmento. Un refresco normal no pisa el minuto que se está escribiendo.
 */
export function forceMinuteOnRefresh(cause: SegmentRefreshCause): boolean {
  return cause === 'mount' || cause === 'segment-changed';
}

function integer(value: unknown, minimum: number): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= minimum ? value : null;
}

/**
 * Interpreta y valida la propuesta del servidor sin confiar en su forma.
 *
 * Devuelve `null` —el formulario no propone nada y sigue utilizable— cuando la
 * forma no es la declarada: número entero ≥ 1, `derived` booleano, minuto
 * entero ≥ 0 informado si es derivada y nulo si no lo es. La propuesta no
 * sustituye la validación del servidor al crear el segmento.
 */
export function parseSegmentProposal(value: unknown): NextSegmentProposal | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as { segment_number?: unknown; minute_start?: unknown; derived?: unknown };

  const segmentNumber = integer(raw.segment_number, 1);
  if (segmentNumber === null) return null;
  if (typeof raw.derived !== 'boolean') return null;

  if (raw.derived) {
    const minuteStart = integer(raw.minute_start, 0);
    if (minuteStart === null) return null;
    return { segment_number: segmentNumber, minute_start: minuteStart, derived: true };
  }

  // Sin base para derivarlo: el minuto debe venir nulo y lo indica el operador.
  if (raw.minute_start !== null && raw.minute_start !== undefined) return null;
  return { segment_number: segmentNumber, minute_start: null, derived: false };
}

/** Origen del minuto de una propuesta válida, o `null` si no hay propuesta. */
export function segmentProposalHint(proposal: unknown): SegmentProposalHintKind | null {
  const parsed = parseSegmentProposal(proposal);
  if (!parsed) return null;
  return parsed.derived ? 'derived' : 'manual';
}

/**
 * Si el minuto de la propuesta debe escribirse en el formulario: solo con una
 * propuesta válida y derivada, y solo si el refresco lo fuerza o el operador no
 * ha editado el campo.
 */
export function shouldPrefillMinute(
  current: SegmentFormState,
  proposal: unknown,
  options: SegmentProposalOptions = {},
): boolean {
  const parsed = parseSegmentProposal(proposal);
  if (!parsed || !parsed.derived || parsed.minute_start === null) return false;
  if (options.forceMinute === true) return true;
  return current.minuteDirty !== true;
}

/**
 * Resuelve el formulario efectivo a partir de la propuesta y del estado actual.
 *
 * - Sin propuesta válida (partido terminal, versión no publicada o forma
 *   inesperada): se conserva el formulario tal cual, sin bloquearlo.
 * - Con propuesta: el número es siempre el del servidor; el minuto se escribe
 *   solo cuando procede (ver `shouldPrefillMinute`) y, al escribirse, el campo
 *   deja de estar editado a mano. Si no se escribe, se conserva lo que había.
 */
export function applySegmentProposal(
  current: SegmentFormState,
  proposal: unknown,
  options: SegmentProposalOptions = {},
): ResolvedSegmentForm {
  const parsed = parseSegmentProposal(proposal);
  if (!parsed) {
    return {
      segment_number: current.segment_number,
      minute_start: current.minute_start,
      minuteDirty: current.minuteDirty === true,
    };
  }

  const prefill = shouldPrefillMinute(current, parsed, options);
  return {
    segment_number: parsed.segment_number,
    minute_start: prefill && parsed.minute_start !== null ? parsed.minute_start : current.minute_start,
    minuteDirty: prefill ? false : current.minuteDirty === true,
  };
}

/** Estado del minuto del formulario de interrupción que la pantalla mantiene. */
export interface InterruptionMinuteState {
  readonly minute: number;
  readonly dirty: boolean;
}

/** Minuto de interrupción resultante de aplicar la propuesta. */
export interface ResolvedInterruptionMinute {
  readonly minute: number;
  readonly dirty: boolean;
}

/**
 * Aplica el minuto del segmento activo al formulario de interrupción con la
 * misma regla que el del segmento (D-5): se escribe solo si hay propuesta y el
 * refresco lo fuerza (montaje y tras crear o interrumpir) o el operador no lo
 * ha editado. Al escribirse, el campo deja de estar editado a mano. Sin
 * propuesta (`nextActiveSegment.minute_start === null`) se conserva lo que haya.
 *
 * El refresco del socket llega como `refresh`, así que no pisa el minuto que el
 * operador está escribiendo. Es pura: no lee el reloj ni el estado global.
 */
export function applyInterruptionMinute(
  current: Readonly<InterruptionMinuteState>,
  proposal: number | null,
  options: Readonly<SegmentProposalOptions> = {},
): ResolvedInterruptionMinute {
  const proposedMinute =
    typeof proposal === 'number' && Number.isInteger(proposal) && proposal >= 0 ? proposal : null;
  if (proposedMinute === null) return { minute: current.minute, dirty: current.dirty === true };
  const prefill = options.forceMinute === true || current.dirty !== true;
  return prefill
    ? { minute: proposedMinute, dirty: false }
    : { minute: current.minute, dirty: true };
}

/**
 * Mensaje de producto de cada causa de un 409 de operación, por su `code`.
 *
 * `null` significa «muestra el `detail` del servidor»: el asistente inválido y
 * el tamaño de plantilla ya llegan con un detalle más específico que cualquier
 * texto genérico. La causa desconocida conserva el mensaje genérico del cierre.
 *
 * El nombre lleva el sufijo `_LABEL_KEYS` y la tabla termina en `as const;`
 * porque así la resuelve el barrido de `utils/i18nCatalog` (`extractUsedKeys`).
 * La cobertura de todos los `MatchConflictKind` la impone
 * `closeConflictMessageKey`: un tipo nuevo sin fila no compila.
 */
export const CLOSE_CONFLICT_MESSAGE_LABEL_KEYS = {
  double_yellow_inconsistent: 'match.doubleYellowInconsistent',
  resolution_not_enabled: 'match.resolutionNotEnabled',
  assist_player_invalid: null,
  roster_size_out_of_range: null,
  walkover_state_not_allowed: 'match.walkoverStateNotAllowed',
  walkover_score_mismatch: 'match.walkoverScoreMismatch',
  walkover_config_inconsistent: 'match.walkoverConfigInconsistent',
  other: 'match.noClose',
} as const;

/** Causa del rechazo del cierre por su `code` aditivo (RF-006, RF-010). */
export function classifyCloseConflict(cause: unknown): MatchConflictKind {
  return classifyMatchConflict(cause);
}

/** Clave i18n que la pantalla muestra para la causa; `null` usa el `detail`. */
export function closeConflictMessageKey(kind: MatchConflictKind): string | null {
  // `null` es un valor declarado (mostrar el detalle del servidor), así que no
  // se puede confundir con una causa ausente mediante `??`.
  return kind in CLOSE_CONFLICT_MESSAGE_LABEL_KEYS
    ? CLOSE_CONFLICT_MESSAGE_LABEL_KEYS[kind]
    : CLOSE_CONFLICT_MESSAGE_LABEL_KEYS.other;
}
