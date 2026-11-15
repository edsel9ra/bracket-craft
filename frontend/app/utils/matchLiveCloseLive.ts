/**
 * Confirmación del cierre live (spec 036, T69).
 *
 * El cierre envía únicamente el recibo revisado (`live_review_id`) y el
 * `result` de la revisión — jamás hechos del cliente ni un subconjunto del
 * conjunto. Un 409 (`LIVE_REVIEW_REQUIRED`/`LIVE_REVIEW_STALE`/reglas de
 * cierre) descarta el recibo y exige revisar de nuevo; el borrador
 * compartido y sus hechos se conservan en todo error, y el modo provisional
 * solo termina cuando el servidor acepta el cierre.
 */

import { getApiStatus, isForbidden, isNotFound, isUnauthorized } from './api.ts';
import type { LiveEditorState } from './matchLiveEditor.ts';
import type { LiveReview } from './matchLiveReview.ts';

export type LiveCloseOutcome =
  | 'closed'      // acta consolidada aceptada; modo provisional terminado
  | 'cancelled'   // confirmación rechazada; recibo y borrador intactos
  | 'stale'       // recibo ausente/vencido o 409: revisar de nuevo
  | 'unavailable' // sin borrador compartido editable
  | 'denied'      // 401/403/404 vigentes (p. ej. autorización de cierre retirada)
  | 'error'
  | 'busy';

export interface LiveCloseOptions {
  /** POST `/matches/{id}/close` vía useApi. */
  sendClose(body: Record<string, unknown>): Promise<unknown>;
  review: LiveReview;
  editor: LiveEditorState;
  confirm(): Promise<boolean>;
  /** Solo se invoca tras un cierre aceptado por el servidor. */
  onClosed(): void;
}

export interface LiveClose {
  confirmClose(): Promise<LiveCloseOutcome>;
  readonly inFlight: boolean;
}

export function createLiveClose(options: LiveCloseOptions): LiveClose {
  let inFlight = false;

  return {
    async confirmClose(): Promise<LiveCloseOutcome> {
      if (inFlight) return 'busy';
      if (options.editor.shared === null) return 'unavailable';
      const receipt = options.review.currentReceipt();
      if (receipt === null) return 'unavailable';
      if (!options.review.receiptValid()) return 'stale';
      inFlight = true;
      try {
        // La confirmación forma parte del vuelo: dos activaciones no se solapan.
        if (!(await options.confirm())) return 'cancelled';
        await options.sendClose({ ...receipt.result, live_review_id: receipt.liveReviewId });
        options.onClosed();
        return 'closed';
      } catch (cause) {
        const status = getApiStatus(cause);
        if (status === 409) {
          // Recibo vencido o rechazado: el borrador se conserva; revisar otra vez.
          options.review.clear();
          return 'stale';
        }
        if (isUnauthorized(cause) || isForbidden(cause) || isNotFound(cause)) return 'denied';
        return 'error';
      } finally {
        inFlight = false;
      }
    },
    get inFlight() {
      return inFlight;
    },
  };
}
