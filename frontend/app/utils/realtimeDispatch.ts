import type { EventDeduplicator } from './realtimeDedup';

export const RESYNC_EVENT = 'RESYNC';

export const RESYNC_REASONS = ['JOIN', 'RELAY_START', 'STREAM_TRIMMED', 'REDIS_RESET'] as const;
export type ResyncReason = (typeof RESYNC_REASONS)[number];

export interface ResyncPayload {
  event_id: string;
  reason: ResyncReason;
}

export interface LiveInvalidationPayload {
  event_id: string;
  match_id: string;
  tournament_id: string;
}

export interface RealtimeDispatchHandlers {
  onEvent?: (event: string, payload: unknown) => void;
  onMatchClosed?: (payload: unknown) => void;
  onMatchUpdated?: (payload: unknown) => void;
  onStandingsUpdated?: (payload: unknown) => void;
  onMatchLiveUpdated?: (payload: LiveInvalidationPayload) => void;
  onMatchLivePublicUpdated?: (payload: LiveInvalidationPayload) => void;
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

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

/**
 * Valida el wire de tres identificadores de las señales live y descarta
 * cualquier campo extra: la invalidación nunca transporta datos del borrador.
 */
export function parseLiveInvalidationPayload(
  payload: unknown,
): LiveInvalidationPayload | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const candidate = payload as {
    event_id?: unknown;
    match_id?: unknown;
    tournament_id?: unknown;
  };
  if (!isNonEmptyString(candidate.event_id)) return null;
  if (!isNonEmptyString(candidate.match_id)) return null;
  if (!isNonEmptyString(candidate.tournament_id)) return null;
  return {
    event_id: candidate.event_id,
    match_id: candidate.match_id,
    tournament_id: candidate.tournament_id,
  };
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
    else if (event === 'MATCH_LIVE_UPDATED' || event === 'MATCH_LIVE_PUBLIC_UPDATED') {
      const invalidation = parseLiveInvalidationPayload(payload);
      if (invalidation === null) return;
      if (event === 'MATCH_LIVE_UPDATED') handlers.onMatchLiveUpdated?.(invalidation);
      else handlers.onMatchLivePublicUpdated?.(invalidation);
    }
  };
}
