/**
 * Revisión expresa del cierre live (spec 036, T68).
 *
 * Antes de cerrar, el operador revisa el conjunto vigente completo del
 * borrador compartido — el servidor devuelve el acta consolidada (`report`)
 * con todos los hechos aceptados en su orden — y el resultado a cerrar. El
 * recibo (`live_review_id` + `content_revision` + `fingerprint`) solo sirve
 * para el conjunto revisado: un cambio real de hechos o resultado lo
 * invalida (RF-019); el mero avance del reloj (`revision` sin
 * `content_revision`) no. No existe selector de subconjunto: el `result` no
 * admite hechos del cliente.
 */

import { getApiStatus, isForbidden, isNotFound, isUnauthorized } from './api.ts';
import { isDraftEditable, type LiveEditorState, type SharedLiveDraft, type SharedLiveEvent } from './matchLiveEditor.ts';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RESOLUTIONS = new Set(['regular', 'extra_time', 'penalties', 'walkover', 'administrative']);
const RESULT_KEYS = new Set([
  'resolution_type', 'home_score_regular', 'away_score_regular',
  'home_score', 'away_score', 'home_penalties', 'away_penalties',
  'winner_team_id', 'reason',
]);
const SCORE_KEYS = [
  'home_score_regular', 'away_score_regular',
  'home_score', 'away_score', 'home_penalties', 'away_penalties',
] as const;

export interface LiveResultInput {
  resolution_type: string;
  home_score_regular: number | null;
  away_score_regular: number | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  winner_team_id: string | null;
  reason: string | null;
}

export interface LiveReviewReceipt {
  liveReviewId: string;
  /** `content_revision` del conjunto revisado; un avance real lo invalida. */
  contentRevision: number;
  fingerprint: string;
  /** Acta consolidada que devolvió la lectura autorizada. */
  report: { events: SharedLiveEvent[]; homeScore: number; awayScore: number };
  /** Resultado revisado tal como se envió. */
  result: LiveResultInput;
}

/** Conjunto vigente completo para la revisión, sin selector de subconjunto. */
export function reviewModel(shared: SharedLiveDraft): {
  events: SharedLiveEvent[];
  homeScore: number;
  awayScore: number;
  contentRevision: number;
  empty: boolean;
} {
  return {
    events: shared.events,
    homeScore: shared.homeScore,
    awayScore: shared.awayScore,
    contentRevision: shared.contentRevision,
    empty: shared.events.length === 0,
  };
}

export type LiveReviewOutcome =
  | 'reviewed'     // recibo emitido para el conjunto vigente
  | 'invalid'      // el resultado a cerrar no cumple el contrato
  | 'conflict'     // 409: content_revision obsoleto, etc.
  | 'denied'       // 401/403/404
  | 'error'
  | 'busy'
  | 'unavailable'; // sin borrador compartido o no editable

function validScore(value: unknown): boolean {
  return value === null || (typeof value === 'number' && Number.isInteger(value) && value >= 0);
}

/** Espejo cliente de `LiveResultDTO`: el resultado no admite hechos del cliente. */
export function validateLiveResult(raw: unknown): LiveResultInput | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const candidate = raw as Record<string, unknown>;
  for (const key of Object.keys(candidate)) {
    if (!RESULT_KEYS.has(key)) return null;
  }
  if (typeof candidate.resolution_type !== 'string' || !RESOLUTIONS.has(candidate.resolution_type)) return null;
  for (const key of SCORE_KEYS) {
    if (!validScore(candidate[key])) return null;
  }
  const winner = candidate.winner_team_id;
  if (winner !== null && !UUID_PATTERN.test(winner as string)) return null;
  const reason = candidate.reason;
  if (reason !== null && (typeof reason !== 'string' || reason.trim().length === 0 || reason.length > 1000)) return null;
  return {
    resolution_type: candidate.resolution_type,
    home_score_regular: (candidate.home_score_regular ?? null) as number | null,
    away_score_regular: (candidate.away_score_regular ?? null) as number | null,
    home_score: (candidate.home_score ?? null) as number | null,
    away_score: (candidate.away_score ?? null) as number | null,
    home_penalties: (candidate.home_penalties ?? null) as number | null,
    away_penalties: (candidate.away_penalties ?? null) as number | null,
    winner_team_id: (winner ?? null) as string | null,
    reason: typeof reason === 'string' ? reason.trim() : null,
  };
}

export interface LiveReviewOptions {
  /** POST `/matches/{id}/live/reviews` vía useApi. */
  sendReview(body: Record<string, unknown>): Promise<unknown>;
  editor: LiveEditorState;
}

export interface LiveReview {
  beginReview(result: unknown): Promise<LiveReviewOutcome>;
  currentReceipt(): LiveReviewReceipt | null;
  /** El recibo solo sirve para el `content_revision` revisado. */
  receiptValid(): boolean;
  clear(): void;
  readonly inFlight: boolean;
}

function isUuidOrNull(value: unknown): boolean {
  return value === null || (typeof value === 'string' && UUID_PATTERN.test(value));
}

function normalizeEvent(raw: unknown): SharedLiveEvent | null {
  const shape = raw as Record<string, unknown> | null;
  if (
    typeof shape !== 'object' || shape === null
    || typeof shape.client_event_id !== 'string' || !UUID_PATTERN.test(shape.client_event_id)
    || typeof shape.event_type !== 'string'
    || typeof shape.team_id !== 'string'
    || typeof shape.minute !== 'number' || !Number.isInteger(shape.minute)
    || typeof shape.added_minute !== 'number' || !Number.isInteger(shape.added_minute)
    || typeof shape.segment_id !== 'string'
    || !isUuidOrNull(shape.beneficiary_team_id)
    || !isUuidOrNull(shape.player_id)
    || !isUuidOrNull(shape.player_out_id)
    || !isUuidOrNull(shape.player_in_id)
    || !isUuidOrNull(shape.assist_player_id)
  ) {
    return null;
  }
  const metadata = shape.metadata;
  if (metadata !== null && (typeof metadata !== 'object' || Array.isArray(metadata))) return null;
  return {
    clientEventId: shape.client_event_id,
    eventType: shape.event_type,
    teamId: shape.team_id,
    beneficiaryTeamId: (shape.beneficiary_team_id ?? null) as string | null,
    playerId: (shape.player_id ?? null) as string | null,
    playerOutId: (shape.player_out_id ?? null) as string | null,
    playerInId: (shape.player_in_id ?? null) as string | null,
    assistPlayerId: (shape.assist_player_id ?? null) as string | null,
    minute: shape.minute,
    addedMinute: shape.added_minute,
    segmentId: shape.segment_id,
    metadata: (metadata ?? null) as Record<string, unknown> | null,
  };
}

function normalizeReport(raw: unknown): LiveReviewReceipt['report'] | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const report = raw as Record<string, unknown>;
  const events = Array.isArray(report.events) ? report.events : [];
  const normalized: SharedLiveEvent[] = [];
  for (const event of events) {
    const shape = normalizeEvent(event);
    if (shape === null) return null;
    normalized.push(shape);
  }
  const home = typeof report.home_score === 'number' ? report.home_score
    : typeof report.home_score_regular === 'number' ? report.home_score_regular : 0;
  const away = typeof report.away_score === 'number' ? report.away_score
    : typeof report.away_score_regular === 'number' ? report.away_score_regular : 0;
  return { events: normalized, homeScore: home, awayScore: away };
}

export function createLiveReview(options: LiveReviewOptions): LiveReview {
  let inFlight = false;
  let receipt: LiveReviewReceipt | null = null;

  return {
    async beginReview(rawResult: unknown): Promise<LiveReviewOutcome> {
      if (inFlight) return 'busy';
      const shared = options.editor.shared;
      if (shared === null || !isDraftEditable(shared.status)) return 'unavailable';
      const result = validateLiveResult(rawResult);
      if (result === null) return 'invalid';
      inFlight = true;
      try {
        const response = await options.sendReview({
          expected_content_revision: shared.contentRevision,
          result,
        });
        const shape = response as Record<string, unknown> | null;
        const report = shape ? normalizeReport(shape.report) : null;
        if (
          shape === null
          || typeof shape.live_review_id !== 'string'
          || !UUID_PATTERN.test(shape.live_review_id)
          || typeof shape.content_revision !== 'number'
          || !Number.isInteger(shape.content_revision)
          || typeof shape.fingerprint !== 'string'
          || report === null
        ) {
          return 'error';
        }
        receipt = {
          liveReviewId: shape.live_review_id,
          contentRevision: shape.content_revision,
          fingerprint: shape.fingerprint,
          report,
          result,
        };
        return 'reviewed';
      } catch (cause) {
        const status = getApiStatus(cause);
        if (status === 409) return 'conflict';
        if (isUnauthorized(cause) || isForbidden(cause) || isNotFound(cause)) return 'denied';
        return 'error';
      } finally {
        inFlight = false;
      }
    },
    currentReceipt() {
      return receipt;
    },
    receiptValid() {
      const shared = options.editor.shared;
      return receipt !== null && shared !== null && shared.contentRevision === receipt.contentRevision;
    },
    clear() {
      receipt = null;
    },
    get inFlight() {
      return inFlight;
    },
  };
}
