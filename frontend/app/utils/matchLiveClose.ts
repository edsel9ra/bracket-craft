import { getApiStatus } from './api.ts';
import { matchConflictDetail } from './matchResolution.ts';

/**
 * F1 (036): con `match_live_state` inicializado, `POST /matches/{id}/close`
 * exige `live_review_id` del recibo de revisión vigente; un cierre clásico con
 * la copia local del borrador se rechaza con 409 `LIVE_REVIEW_REQUIRED`. Si el
 * conjunto o el resultado cambiaron tras la revisión, `LIVE_REVIEW_STALE`.
 * Ambos códigos viajan en `detail` del cuerpo del error (HTTPException), no en
 * el `code` aditivo de los conflictos deportivos.
 */
export type LiveCloseConflict = 'live_review_required' | 'live_review_stale';

export function classifyLiveCloseConflict(cause: unknown): LiveCloseConflict | null {
  if (getApiStatus(cause) !== 409) return null;
  const detail = matchConflictDetail(cause);
  if (detail === 'LIVE_REVIEW_REQUIRED') return 'live_review_required';
  if (detail === 'LIVE_REVIEW_STALE') return 'live_review_stale';
  return null;
}

/**
 * La lectura autorizada `GET /live` declara `initialized` explícito; solo
 * `true` reconoce un partido F1. Sin VIEW no hay instantánea: `undefined`/otra
 * forma nunca se interpreta como inicializado.
 */
export function isLiveInitialized(snapshot: unknown): boolean {
  return (
    typeof snapshot === 'object'
    && snapshot !== null
    && (snapshot as { initialized?: unknown }).initialized === true
  );
}

export const LIVE_CLOSE_CONFLICT_LABEL_KEYS: Record<LiveCloseConflict, string> = {
  live_review_required: 'match.liveReviewRequired',
  live_review_stale: 'match.liveReviewStale',
};
