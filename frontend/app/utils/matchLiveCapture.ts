/**
 * Captura de incidencias del editor compartido (spec 036, T63).
 *
 * Un hecho solo llega al borrador mediante `POST /live/commands` con su
 * `command_id` estable: el servidor deduplica por identidad, así que un
 * reintento tras timeout nunca duplica. El hecho queda `pending` tras el ack
 * y solo se presenta como aceptado cuando el snapshot autorizado lo devuelve.
 * Si algo falla, el formulario del operador se conserva intacto (esta
 * utilidad jamás muta el input).
 */

import { getApiStatus, isForbidden, isNotFound, isUnauthorized } from './api.ts';
import { isAcceptedEvent, isDraftEditable, markPendingEvent, type LiveEditorState } from './matchLiveEditor.ts';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const EVENT_TYPES = new Set([
  'goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card', 'substitution', 'foul',
]);

const RED_CARD_TYPES = new Set(['direct_red', 'double_yellow_red']);

const EVENT_KEYS = new Set([
  'client_event_id', 'event_type', 'team_id', 'beneficiary_team_id',
  'player_id', 'player_out_id', 'player_in_id', 'assist_player_id',
  'minute', 'added_minute', 'segment_id', 'metadata',
]);

export type LiveCaptureOutcome =
  | 'sent'        // comando enviado y ack válido; pendiente del snapshot
  | 'accepted'    // el hecho ya está aceptado en el borrador compartido
  | 'invalid'     // validación local: el formulario se conserva
  | 'conflict'    // 409: revisión obsoleta, borrador congelado, etc.
  | 'denied'      // 401/403/404
  | 'error'       // red, timeout o ack inválido
  | 'busy'        // captura en curso (single-flight)
  | 'unavailable'; // sin borrador compartido inicializado

export interface LiveEventFormInput {
  client_event_id: string;
  event_type: string;
  team_id: string;
  beneficiary_team_id: string | null;
  player_id: string | null;
  player_out_id: string | null;
  player_in_id: string | null;
  assist_player_id: string | null;
  minute: number;
  added_minute: number;
  segment_id: string;
  metadata: Record<string, unknown> | null;
}

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

function isMinute(value: unknown, max: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= max;
}

/**
 * Espejo cliente de `MatchEventPayload`/`LiveEventPayload`: rechaza campos
 * vacíos, tipos fuera del catálogo cerrado, rangos de minuto y las reglas
 * estructurales (pareja de sustitución, beneficiario de autogol, asistencia
 * solo en gol, metadata solo `red_card_type` en tarjeta roja).
 */
export function validateLiveEventForm(raw: unknown): LiveEventFormInput | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const candidate = raw as Record<string, unknown>;
  for (const key of Object.keys(candidate)) {
    if (!EVENT_KEYS.has(key)) return null;
  }
  if (!isUuid(candidate.client_event_id)) return null;
  if (typeof candidate.event_type !== 'string' || !EVENT_TYPES.has(candidate.event_type)) return null;
  if (!isUuid(candidate.team_id)) return null;
  const nullableIds = ['beneficiary_team_id', 'player_id', 'player_out_id', 'player_in_id', 'assist_player_id'] as const;
  for (const key of nullableIds) {
    const value = candidate[key];
    if (value !== null && !isUuid(value)) return null;
  }
  if (candidate.player_id === null) return null;
  if (!isMinute(candidate.minute, 180)) return null;
  if (!isMinute(candidate.added_minute, 30)) return null;
  if (!isUuid(candidate.segment_id)) return null;

  const eventType = candidate.event_type;
  if (eventType === 'substitution') {
    if (candidate.player_out_id === null || candidate.player_in_id === null) return null;
    if (candidate.player_out_id === candidate.player_in_id) return null;
    if (candidate.player_id !== candidate.player_out_id) return null;
  } else if (candidate.player_out_id !== null || candidate.player_in_id !== null) {
    return null;
  }
  if (eventType === 'own_goal') {
    if (candidate.beneficiary_team_id === null || candidate.beneficiary_team_id === candidate.team_id) return null;
  } else if (candidate.beneficiary_team_id !== null) {
    return null;
  }
  if (eventType === 'goal') {
    if (candidate.assist_player_id !== null && candidate.assist_player_id === candidate.player_id) return null;
  } else if (candidate.assist_player_id !== null) {
    return null;
  }

  const metadata = candidate.metadata;
  if (metadata !== null && metadata !== undefined) {
    if (typeof metadata !== 'object' || Array.isArray(metadata)) return null;
    const keys = Object.keys(metadata);
    if (eventType === 'red_card') {
      if (keys.length > 1 || (keys.length === 1 && keys[0] !== 'red_card_type')) return null;
      const redCardType = (metadata as Record<string, unknown>).red_card_type;
      if (typeof redCardType !== 'string' || !RED_CARD_TYPES.has(redCardType)) return null;
    } else if (keys.length > 0) {
      return null;
    }
  }

  return {
    client_event_id: candidate.client_event_id,
    event_type: eventType,
    team_id: candidate.team_id,
    beneficiary_team_id: candidate.beneficiary_team_id as string | null,
    player_id: candidate.player_id as string,
    player_out_id: candidate.player_out_id as string | null,
    player_in_id: candidate.player_in_id as string | null,
    assist_player_id: candidate.assist_player_id as string | null,
    minute: candidate.minute,
    added_minute: candidate.added_minute as number,
    segment_id: candidate.segment_id,
    metadata: (metadata ?? null) as Record<string, unknown> | null,
  };
}

/** Clasifica el fallo HTTP sin exponer el detalle del servidor. */
export function classifyCaptureFailure(cause: unknown): 'conflict' | 'denied' | 'error' {
  if (isUnauthorized(cause) || isForbidden(cause) || isNotFound(cause)) return 'denied';
  if (getApiStatus(cause) === 409) return 'conflict';
  return 'error';
}

export interface LiveCaptureOptions {
  /** POST `/matches/{id}/live/commands` vía useApi. */
  send(body: Record<string, unknown>): Promise<unknown>;
  /** Recarga del snapshot autorizado (liveContext.request()). */
  requestSnapshot(): Promise<void>;
  editor: LiveEditorState;
  /** Genera el `command_id` del comando (UUID nuevo por captura). */
  commandId(): string;
}

export interface LiveCapture {
  capture(payload: unknown): Promise<LiveCaptureOutcome>;
  readonly inFlight: boolean;
}

export function createLiveCapture(options: LiveCaptureOptions): LiveCapture {
  let inFlight = false;

  return {
    async capture(payload: unknown): Promise<LiveCaptureOutcome> {
      if (inFlight) return 'busy';
      const shared = options.editor.shared;
      // Suspendido/terminal: el borrador no admite capturas (T67).
      if (shared === null || !isDraftEditable(shared.status)) return 'unavailable';
      const event = validateLiveEventForm(payload);
      if (event === null) return 'invalid';
      // Nada local se considera aceptado sin HTTP; pero un hecho ya aceptado no
      // se reenvía, y uno pendiente solo dispara otra lectura del snapshot.
      if (isAcceptedEvent(shared, event.client_event_id)) return 'accepted';
      if (options.editor.pending.some((item) => item.clientEventId === event.client_event_id)) {
        await options.requestSnapshot();
        return 'sent';
      }
      inFlight = true;
      const commandId = options.commandId();
      try {
        const ack = await options.send({
          command_id: commandId,
          expected_revision: shared.revision,
          type: 'add_event',
          event,
        });
        const ackShape = ack as Record<string, unknown> | null;
        // Solo vale el recibo del comando enviado: uno ajeno o malformado no
        // acredita nada.
        if (
          typeof ackShape !== 'object' || ackShape === null
          || ackShape.command_id !== commandId
          || typeof ackShape.revision !== 'number'
          || !Number.isInteger(ackShape.revision)
          || ackShape.revision < 0
        ) {
          return 'error';
        }
        markPendingEvent(options.editor, event);
        // El hecho solo se presenta como aceptado cuando el snapshot
        // autorizado lo devuelve (T63: esperar ack Y lectura vigente).
        await options.requestSnapshot();
        return 'sent';
      } catch (cause) {
        return classifyCaptureFailure(cause);
      } finally {
        inFlight = false;
      }
    },
    get inFlight() {
      return inFlight;
    },
  };
}
