export const DEDUPE_WINDOW_LIMIT = 200;

export interface EventDeduplicator {
  accept(eventName: string, payload: unknown): boolean;
  reset(): void;
}

/**
 * Solo un `event_id` de nivel superior y cadena no vacía identifica una
 * entrega. Un `event_id` anidado en el payload de dominio no se considera.
 */
export function readDeliveryId(payload: unknown): string | null {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return null;
  const eventId = (payload as { event_id?: unknown }).event_id;
  return typeof eventId === 'string' && eventId.length > 0 ? eventId : null;
}

export function createEventDeduplicator(limit = DEDUPE_WINDOW_LIMIT): EventDeduplicator {
  const seen = new Set<string>();

  return {
    accept(_eventName, payload) {
      const eventId = readDeliveryId(payload);
      if (eventId === null) return true;
      if (seen.has(eventId)) return false;

      seen.add(eventId);
      if (seen.size > limit) {
        const oldest = seen.values().next().value;
        if (oldest !== undefined) seen.delete(oldest);
      }
      return true;
    },
    reset() {
      seen.clear();
    },
  };
}
