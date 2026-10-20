import type { EventDeduplicator } from './realtimeDedup';

export const RESYNC_EVENT = 'RESYNC';

export const RESYNC_REASONS = ['JOIN', 'RELAY_START', 'STREAM_TRIMMED', 'REDIS_RESET'] as const;
export type ResyncReason = (typeof RESYNC_REASONS)[number];

export interface ResyncPayload {
  event_id: string;
  reason: ResyncReason;
}

export interface RealtimeDispatchHandlers {
  onEvent?: (event: string, payload: unknown) => void;
  onMatchClosed?: (payload: unknown) => void;
  onMatchUpdated?: (payload: unknown) => void;
  onStandingsUpdated?: (payload: unknown) => void;
  onResync?: (payload: ResyncPayload) => void;
}

export interface RealtimeDispatcherOptions {
  dedupe: EventDeduplicator;
  handlers: RealtimeDispatchHandlers;
}

export type RealtimeDispatcher = (event: string, payload: unknown) => void;

function isResyncReason(value: unknown): value is ResyncReason {
  return typeof value === 'string' && (RESYNC_REASONS as readonly string[]).includes(value);
}

/**
 * Valida el payload mínimo de `RESYNC` y descarta cualquier campo extra.
 */
export function parseResyncPayload(payload: unknown): ResyncPayload | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const candidate = payload as { event_id?: unknown; reason?: unknown };
  if (typeof candidate.event_id !== 'string' || candidate.event_id.length === 0) return null;
  if (!isResyncReason(candidate.reason)) return null;
  return { event_id: candidate.event_id, reason: candidate.reason };
}

/**
 * Único punto de despacho: deduplica antes de invocar handlers y separa
 * `RESYNC` de los eventos de dominio.
 */
export function createRealtimeDispatcher({
  dedupe,
  handlers,
}: RealtimeDispatcherOptions): RealtimeDispatcher {
  return (event, payload) => {
    if (!dedupe.accept(event, payload)) return;

    if (event === RESYNC_EVENT) {
      const resync = parseResyncPayload(payload);
      if (resync !== null) handlers.onResync?.(resync);
      return;
    }

    handlers.onEvent?.(event, payload);
    if (event === 'MATCH_CLOSED') handlers.onMatchClosed?.(payload);
    else if (event === 'MATCH_UPDATED') handlers.onMatchUpdated?.(payload);
    else if (event === 'STANDINGS_UPDATED') handlers.onStandingsUpdated?.(payload);
  };
}
