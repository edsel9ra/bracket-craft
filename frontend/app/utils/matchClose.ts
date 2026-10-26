/**
 * Cierre del acta por resolución (spec 016, RF-012, RF-005, RNF-007).
 *
 * La pantalla de operación decide con tres piezas puras:
 *
 * - `closePreflight`: el primer problema del cierre, con su clave i18n. El
 *   walkover **no** exige segmento activo ni planilla completa (RF-003: un
 *   equipo puede no presentarse) y exige ganador participante y motivo de
 *   catálogo cerrado; el resto de resoluciones conserva sus exigencias.
 * - `buildCloseReportBody`: el cuerpo exacto de `POST /matches/{id}/close`. En
 *   `walkover` **no emite ninguna de las seis claves de marcador** (RF-005: el
 *   servidor lo deriva de las reglas de la fase).
 * - `walkoverScoreFrom`: la pareja efectiva que publica `limits` para mostrarla
 *   en solo lectura (tolerante a un servidor anterior).
 *
 * El catálogo de motivos tiene **una sola fuente** en el cliente y una prueba
 * que la contrasta con `WALKOVER_REASONS` del backend.
 *
 * Todo es puro: no lee el reloj, el entorno, el almacenamiento ni la red
 * (RNF-006). Los textos son claves i18n: aquí no hay literales de producto.
 */

import {
  normalizeResolution,
  type OperationLimits,
  type ResolutionType,
} from './matchResolution.ts';
import type { WalkoverScore } from './rulesConfig.ts';

/**
 * Motivos del walkover (RF-007). Catálogo cerrado: no hay texto libre ni
 * código «otra». Es la copia cliente de `WALKOVER_REASONS` del backend.
 */
export const WALKOVER_REASONS = [
  'no_show',
  'withdrawal',
  'insufficient_players',
  'sanction',
] as const;

export type WalkoverReason = (typeof WALKOVER_REASONS)[number];

/**
 * Claves i18n de los motivos. El nombre termina en `_LABEL_KEYS` y la tabla en
 * `as const;` porque así la resuelve el barrido de `utils/i18nCatalog`.
 */
export const WALKOVER_REASON_LABEL_KEYS = {
  no_show: 'match.walkoverReasonNoShow',
  withdrawal: 'match.walkoverReasonWithdrawal',
  insufficient_players: 'match.walkoverReasonInsufficientPlayers',
  sanction: 'match.walkoverReasonSanction',
} as const;

/** Si el valor es un código del catálogo cerrado de motivos (RF-007). */
export function isWalkoverReason(value: unknown): value is WalkoverReason {
  return typeof value === 'string' && (WALKOVER_REASONS as readonly string[]).includes(value);
}

/** Clave i18n del motivo; el texto vive solo en el catálogo. */
export function walkoverReasonLabelKey(reason: WalkoverReason): string {
  return WALKOVER_REASON_LABEL_KEYS[reason];
}

/** Entero ≥ 0, o `null` si el valor no tiene esa forma. */
function nonNegativeInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

/**
 * Marcador efectivo del walkover publicado en `limits` (RF-005). Devuelve
 * `null` si la clave no llega o no tiene la forma declarada, para que la
 * pantalla muestre «—» sin romper la operación.
 */
export function walkoverScoreFrom(
  limits: OperationLimits | null | undefined,
): WalkoverScore | null {
  const pair = limits?.walkover_score;
  if (!pair || typeof pair !== 'object') return null;
  const winner = nonNegativeInteger(pair.winner);
  const loser = nonNegativeInteger(pair.loser);
  if (winner === null || loser === null) return null;
  return { winner, loser };
}

// ---------------------------------------------------------------------------
// Validación previa (RF-012)
// ---------------------------------------------------------------------------

/** Los seis marcadores del formulario, tal como los mantiene la pantalla. */
export interface CloseScoreInput {
  readonly home_score_regular?: number | null;
  readonly away_score_regular?: number | null;
  readonly home_score?: number | null;
  readonly away_score?: number | null;
  readonly home_penalties?: number | null;
  readonly away_penalties?: number | null;
}

/** Evento del borrador que la validación previa necesita leer (RF-032). */
export interface CloseDraftEventInput {
  readonly event_type?: string | null;
  readonly team_id?: string | null;
  readonly beneficiary_team_id?: string | null;
}

/** Problema del cierre: una clave i18n y sus parámetros, nunca un texto. */
export interface ClosePreflightIssue {
  readonly key: string;
  readonly params?: Record<string, string | number>;
}

/** Entrada pura de la validación previa del cierre. */
export interface ClosePreflightInput {
  /** Resolución del único control; se normaliza con `limits`. */
  readonly resolution?: unknown;
  readonly limits?: OperationLimits | null;
  readonly homeTeamId?: string | null;
  readonly awayTeamId?: string | null;
  /** Hay un segmento activo del servidor. */
  readonly segmentActive?: boolean;
  /** Ambos equipos tienen planilla alineada. */
  readonly lineupComplete?: boolean;
  readonly scores?: CloseScoreInput | null;
  readonly winnerTeamId?: string | null;
  readonly reason?: string | null;
  readonly draftEvents?: readonly CloseDraftEventInput[] | null;
  /** Primer evento fuera del tope combinado, ya resuelto por la pantalla. */
  readonly minuteIssue?: ClosePreflightIssue | null;
}

function teamId(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function isOptionalScore(value: unknown): boolean {
  return value === null || value === undefined || nonNegativeInteger(value) !== null;
}

function goalsByTeam(
  events: readonly CloseDraftEventInput[],
  home: string,
  away: string,
): Record<string, number> {
  const goals: Record<string, number> = { [home]: 0, [away]: 0 };
  for (const event of events) {
    const type = event.event_type;
    if (type !== 'goal' && type !== 'own_goal' && type !== 'penalty_goal') continue;
    const team = type === 'own_goal' ? event.beneficiary_team_id : event.team_id;
    if (typeof team === 'string' && team in goals) {
      goals[team] = (goals[team] ?? 0) + 1;
    }
  }
  return goals;
}

const CLOSE_INVALID = 'match.closeValidation';

/**
 * Primer problema que impide cerrar el acta, o `null` si la petición puede
 * enviarse. El servidor sigue siendo la autoridad: esto evita un 422 evitable
 * y ordena los avisos.
 */
export function closePreflight(input: ClosePreflightInput): ClosePreflightIssue | null {
  const resolution: ResolutionType = normalizeResolution(input.limits, input.resolution);
  const scores = input.scores ?? {};
  const home = teamId(input.homeTeamId);
  const away = teamId(input.awayTeamId);
  const winner = teamId(input.winnerTeamId);
  const reason = typeof input.reason === 'string' ? input.reason.trim() : '';
  const events = input.draftEvents ?? [];
  const isWalkover = resolution === 'walkover';

  // RF-012/RF-003: el walkover no exige segmento activo ni planilla. El resto
  // conserva la exigencia de la spec 012.
  if (!isWalkover) {
    if (!home || !away || input.segmentActive !== true || input.lineupComplete !== true) {
      return { key: 'match.needSegmentLineup' };
    }
  }

  // RF-001: un ganador solo puede ser uno de los dos participantes.
  if (!home || !away) return { key: CLOSE_INVALID };

  const scoreNames = [
    'home_score_regular',
    'away_score_regular',
    'home_score',
    'away_score',
    'home_penalties',
    'away_penalties',
  ] as const;
  if (scoreNames.some((name) => !isOptionalScore(scores[name]))) return { key: CLOSE_INVALID };

  if (winner && winner !== home && winner !== away) return { key: CLOSE_INVALID };

  // RF-032 (spec 012): un evento fuera del tope combinado haría fallar el
  // cierre; el walkover no valida segmentos ni minutos.
  if (!isWalkover && input.minuteIssue) return input.minuteIssue;

  if (isWalkover) {
    // RF-006: ningún evento, ni siquiera informativo. Tiene su propia clave
    // porque D-13 exige un mensaje concreto para ese rechazo.
    if (events.length) return { key: 'match.walkoverEventsNotAllowed' };
    // RF-001: el ganador es obligatorio, con su propio error asociado al campo
    // (RNF-007); un ganador que no participa sigue siendo el error genérico.
    if (!winner) return { key: 'match.walkoverWinnerRequired' };
    // RF-007: motivo obligatorio y de catálogo cerrado.
    if (!isWalkoverReason(reason)) return { key: 'match.walkoverReasonRequired' };
    return null;
  }

  if (resolution === 'regular') {
    // El motivo solo aplica al walkover y a la administrativa.
    if (reason) return { key: CLOSE_INVALID };
    const regularHome = scores.home_score_regular ?? 0;
    const regularAway = scores.away_score_regular ?? 0;
    const goals = goalsByTeam(events, home, away);
    if (goals[home] !== regularHome || goals[away] !== regularAway) {
      return { key: CLOSE_INVALID };
    }
    return null;
  }

  // La administrativa tampoco admite eventos individuales.
  if (resolution === 'administrative' && events.length) return { key: CLOSE_INVALID };
  if (!winner) return { key: CLOSE_INVALID };

  if (resolution === 'extra_time') {
    if (
      nonNegativeInteger(scores.home_score) === null
      || nonNegativeInteger(scores.away_score) === null
    ) {
      return { key: CLOSE_INVALID };
    }
    if (
      (scores.home_score ?? 0) < (scores.home_score_regular ?? 0)
      || (scores.away_score ?? 0) < (scores.away_score_regular ?? 0)
    ) {
      return { key: CLOSE_INVALID };
    }
  }

  if (resolution === 'penalties') {
    if (
      nonNegativeInteger(scores.home_score) === null
      || nonNegativeInteger(scores.away_score) === null
      || scores.home_score !== scores.away_score
    ) {
      return { key: CLOSE_INVALID };
    }
    if (
      nonNegativeInteger(scores.home_penalties) === null
      || nonNegativeInteger(scores.away_penalties) === null
      || scores.home_penalties === scores.away_penalties
    ) {
      return { key: CLOSE_INVALID };
    }
  }

  if (resolution === 'administrative') {
    if (
      nonNegativeInteger(scores.home_score) === null
      || nonNegativeInteger(scores.away_score) === null
      || scores.home_score !== (scores.home_score_regular ?? 0)
      || scores.away_score !== (scores.away_score_regular ?? 0)
    ) {
      return { key: CLOSE_INVALID };
    }
    if (!reason) return { key: 'match.administrativeReasonRequired' };
  }

  if (resolution !== 'administrative' && reason) return { key: CLOSE_INVALID };
  return null;
}

// ---------------------------------------------------------------------------
// Cuerpo del cierre (RF-005, RF-012)
// ---------------------------------------------------------------------------

/** Entrada pura del cuerpo de `POST /matches/{id}/close`. */
export interface CloseReportBodyInput {
  readonly resolution?: unknown;
  readonly limits?: OperationLimits | null;
  readonly scores?: CloseScoreInput | null;
  readonly winnerTeamId?: string | null;
  readonly reason?: string | null;
  readonly events?: readonly unknown[] | null;
}

/**
 * Cuerpo exacto del cierre. `walkover` no envía **ninguna** de las seis claves
 * de marcador (RF-005); el resto de resoluciones conserva la forma vigente.
 */
export function buildCloseReportBody(
  input: CloseReportBodyInput,
): Record<string, unknown> {
  const resolution = normalizeResolution(input.limits, input.resolution);
  const scores = input.scores ?? {};
  const winner = teamId(input.winnerTeamId);
  const reason = typeof input.reason === 'string' ? input.reason.trim() : '';
  const events = [...(input.events ?? [])];

  if (resolution === 'walkover') {
    return {
      resolution_type: resolution,
      winner_team_id: winner,
      reason,
      events,
    };
  }

  return {
    resolution_type: resolution,
    home_score_regular: scores.home_score_regular ?? null,
    away_score_regular: scores.away_score_regular ?? null,
    home_score: resolution === 'regular' ? null : scores.home_score ?? null,
    away_score: resolution === 'regular' ? null : scores.away_score ?? null,
    home_penalties: resolution === 'penalties' ? scores.home_penalties ?? null : null,
    away_penalties: resolution === 'penalties' ? scores.away_penalties ?? null : null,
    winner_team_id: resolution === 'regular' ? null : winner,
    reason: resolution === 'administrative' ? reason : null,
    events,
  };
}
