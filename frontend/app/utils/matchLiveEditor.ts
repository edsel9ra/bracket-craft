/**
 * Editor compartido F1 (spec 036, T61): separa el borrador aceptado por el
 * servidor del estado clásico local. Nada local se considera aceptado sin una
 * respuesta HTTP autorizada; los hechos capturados en la pestaña viven en
 * `pending` hasta que el snapshot del servidor los trae.
 */

const LIVE_STATUSES = new Set([
  'scheduled', 'live', 'finished', 'suspended', 'cancelled', 'administrative_resolution',
]);

const CLOCK_STATES = new Set(['not_started', 'running', 'paused']);

const EVENT_KEYS = new Set([
  'client_event_id', 'event_type', 'team_id', 'beneficiary_team_id',
  'player_id', 'player_out_id', 'player_in_id', 'assist_player_id',
  'minute', 'added_minute', 'segment_id', 'metadata',
]);

export interface LiveClock {
  state: 'not_started' | 'running' | 'paused';
  segmentId: string | null;
  segmentNumber: number | null;
  elapsedUs: number | null;
  anchorAt: string | null;
  observedAt: string;
}

export interface SharedLiveEvent {
  clientEventId: string;
  eventType: string;
  teamId: string;
  beneficiaryTeamId: string | null;
  playerId: string | null;
  playerOutId: string | null;
  playerInId: string | null;
  assistPlayerId: string | null;
  minute: number;
  addedMinute: number;
  segmentId: string;
  metadata: Record<string, unknown> | null;
}

export interface SharedLiveDraft {
  status: string;
  revision: number;
  contentRevision: number;
  homeScore: number;
  awayScore: number;
  clock: LiveClock;
  events: SharedLiveEvent[];
}

export interface LiveEditorState {
  /** Borrador compartido aceptado por HTTP; null = modo clásico o denegado. */
  shared: SharedLiveDraft | null;
  /** Hechos capturados localmente todavía no aceptados por el servidor. */
  pending: SharedLiveEvent[];
}

export type LiveEditorMode = 'classic' | 'live';

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isNullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function isNonNegativeInt(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isUtcInstant(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const millis = Date.parse(value);
  if (Number.isNaN(millis)) return false;
  // El contrato exige UTC aware: la forma textual debe terminar en Z o ±00:00.
  return /(?:Z|[+-]00:00)$/i.test(value);
}

function normalizeClock(raw: unknown): LiveClock | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const candidate = raw as Record<string, unknown>;
  if (typeof candidate.state !== 'string' || !CLOCK_STATES.has(candidate.state)) return null;
  if (!isNullableString(candidate.segment_id)) return null;
  if (candidate.segment_number !== null && !isNonNegativeInt(candidate.segment_number)) return null;
  if (candidate.elapsed_us !== null && !isNonNegativeInt(candidate.elapsed_us)) return null;
  if (!isNullableString(candidate.anchor_at)) return null;
  if (candidate.anchor_at !== null && !isUtcInstant(candidate.anchor_at)) return null;
  if (!isUtcInstant(candidate.observed_at)) return null;

  const state = candidate.state as LiveClock['state'];
  const reference = [candidate.segment_id, candidate.segment_number, candidate.elapsed_us];
  if (state === 'not_started') {
    if (reference.some((v) => v !== null) || candidate.anchor_at !== null) return null;
  } else if (reference.some((v) => v === null) || (state === 'running') !== (candidate.anchor_at !== null)) {
    return null;
  }
  return {
    state,
    segmentId: candidate.segment_id as string | null,
    segmentNumber: candidate.segment_number as number | null,
    elapsedUs: candidate.elapsed_us as number | null,
    anchorAt: candidate.anchor_at as string | null,
    observedAt: candidate.observed_at as string,
  };
}

function normalizeEvent(raw: unknown): SharedLiveEvent | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const candidate = raw as Record<string, unknown>;
  // extra=forbid en el wire: ninguna clave no declarada viaja al editor.
  for (const key of Object.keys(candidate)) {
    if (!EVENT_KEYS.has(key)) return null;
  }
  if (!isNonEmptyString(candidate.client_event_id)) return null;
  if (!isNonEmptyString(candidate.event_type)) return null;
  if (!isNonEmptyString(candidate.team_id)) return null;
  for (const key of ['beneficiary_team_id', 'player_id', 'player_out_id', 'player_in_id', 'assist_player_id'] as const) {
    if (!isNullableString(candidate[key])) return null;
  }
  if (!isNonNegativeInt(candidate.minute) || (candidate.minute as number) > 180) return null;
  if (!isNonNegativeInt(candidate.added_minute) || (candidate.added_minute as number) > 30) return null;
  if (!isNonEmptyString(candidate.segment_id)) return null;
  if (candidate.metadata !== null && (typeof candidate.metadata !== 'object' || Array.isArray(candidate.metadata))) return null;

  return {
    clientEventId: candidate.client_event_id,
    eventType: candidate.event_type as string,
    teamId: candidate.team_id,
    beneficiaryTeamId: candidate.beneficiary_team_id as string | null,
    playerId: candidate.player_id as string | null,
    playerOutId: candidate.player_out_id as string | null,
    playerInId: candidate.player_in_id as string | null,
    assistPlayerId: candidate.assist_player_id as string | null,
    minute: candidate.minute,
    addedMinute: candidate.added_minute as number,
    segmentId: candidate.segment_id,
    metadata: candidate.metadata as Record<string, unknown> | null,
  };
}

/**
 * Normaliza el wire `LiveSnapshotResponse`. `initialized: false` es modo
 * clásico (sin borrador compartido) y se devuelve como `null`; cualquier forma
 * incoherente con el contrato se descarta completa.
 */
export function normalizeLiveSnapshot(raw: unknown): SharedLiveDraft | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const candidate = raw as Record<string, unknown>;
  // extra=forbid en el wire: ninguna clave de primer nivel no declarada.
  const SNAPSHOT_KEYS = new Set([
    'initialized', 'status', 'revision', 'content_revision', 'events',
    'home_score', 'away_score', 'clock',
  ]);
  for (const key of Object.keys(candidate)) {
    if (!SNAPSHOT_KEYS.has(key)) return null;
  }
  if (candidate.initialized !== true && candidate.initialized !== false) return null;
  // `initialized: false` es modo clásico: sin borrador compartido, con o sin
  // restos inválidos el resultado es el mismo `null`.
  if (candidate.initialized === false) return null;
  if (typeof candidate.status !== 'string' || !LIVE_STATUSES.has(candidate.status)) return null;
  if (!isNonNegativeInt(candidate.revision)) return null;
  if (!isNonNegativeInt(candidate.content_revision)) return null;
  if (!isNonNegativeInt(candidate.home_score)) return null;
  if (!isNonNegativeInt(candidate.away_score)) return null;
  const clock = normalizeClock(candidate.clock);
  if (clock === null) return null;
  if (candidate.status !== 'live' && clock.state === 'running') return null;
  if (!Array.isArray(candidate.events) || candidate.events.length > 500) return null;
  const events: SharedLiveEvent[] = [];
  for (const item of candidate.events) {
    const event = normalizeEvent(item);
    if (event === null) return null;
    events.push(event);
  }
  return {
    status: candidate.status,
    revision: candidate.revision,
    contentRevision: candidate.content_revision,
    homeScore: candidate.home_score,
    awayScore: candidate.away_score,
    clock,
    events,
  };
}

/** `classic` sin snapshot autorizado; `live` con borrador compartido vigente. */
export function liveEditorMode(shared: SharedLiveDraft | null): LiveEditorMode {
  return shared === null ? 'classic' : 'live';
}

export function createLiveEditorState(): LiveEditorState {
  return { shared: null, pending: [] };
}

/**
 * Aplica el snapshot autorizado: reemplaza el compartido y reconoce como
 * aceptados los pendientes que el servidor ya devuelve. Una respuesta inválida
 * limpia lo compartido pero conserva los pendientes locales.
 */
export function applySharedSnapshot(state: LiveEditorState, raw: unknown): boolean {
  const shared = normalizeLiveSnapshot(raw);
  if (shared === null) {
    state.shared = null;
    return false;
  }
  state.shared = shared;
  const acceptedIds = new Set(shared.events.map((event) => event.clientEventId));
  if (acceptedIds.size) {
    state.pending = state.pending.filter((event) => !acceptedIds.has(event.clientEventId));
  }
  return true;
}

/**
 * Un hecho local queda pendiente; jamás se presenta como aceptado. La entrada
 * se normaliza igual que un hecho del wire: una forma que no cumple el
 * contrato no entra al editor.
 */
export function markPendingEvent(state: LiveEditorState, raw: unknown): boolean {
  const event = normalizeEvent(raw);
  if (event === null) return false;
  state.pending.push(event);
  return true;
}

/** Retira pendientes por identificador (aceptados o descartados expresamente). */
export function ackPendingEvents(state: LiveEditorState, clientEventIds: readonly string[]): void {
  const ids = new Set(clientEventIds);
  state.pending = state.pending.filter((event) => !ids.has(event.clientEventId));
}

/** Un hecho es aceptado solo si el snapshot del servidor lo contiene. */
export function isAcceptedEvent(shared: SharedLiveDraft | null, clientEventId: string): boolean {
  return shared !== null && shared.events.some((event) => event.clientEventId === clientEventId);
}
