/**
 * Resolución prevista de la operación del partido (spec 012, RF-033, RF-034).
 *
 * El operador anuncia con un **único** control la resolución con la que va a
 * operar y cerrar el acta. Este módulo es puro: no lee el reloj, el entorno, el
 * almacenamiento ni la red. Recibe el bloque `limits` que resuelve el servidor
 * y devuelve el máximo aplicable, las opciones habilitadas y el cuerpo que se
 * envía; **nunca recalcula** la regla deportiva.
 *
 * La selección vive solo en el almacenamiento de sesión de la pestaña (P3), por
 * usuario, organización y partido. Las funciones de almacenamiento reciben el
 * `Storage` como parámetro (el composable le pasa el de la pestaña).
 */

import { getApiCode } from './api.ts';
import { DEFAULT_MATCH_LIMITS } from './substitutions.ts';

export type ResolutionType =
  | 'regular'
  | 'extra_time'
  | 'penalties'
  | 'walkover'
  | 'administrative';

/** Resoluciones conocidas, en el orden en que se ofrecen. */
export const RESOLUTION_TYPES: readonly ResolutionType[] = [
  'regular',
  'extra_time',
  'penalties',
  'walkover',
  'administrative',
];

/** Resolución por defecto: tiempo reglamentario (RF-033). */
export const DEFAULT_RESOLUTION: ResolutionType = 'regular';

/** Claves i18n de cada resolución; el texto solo vive en el catálogo. */
export const RESOLUTION_LABEL_KEYS = {
  regular: 'match.regularTime',
  extra_time: 'match.overtime',
  penalties: 'match.penaltyShootout',
  walkover: 'match.walkover',
  administrative: 'match.administrative',
} as const satisfies Record<ResolutionType, string>;

/** Origen del máximo aplicable: reglamentario o prórroga habilitada. */
export type MaximumSource = 'regular' | 'extra_time';

/** Claves i18n del origen del máximo (RF-033). */
export const MAXIMUM_SOURCE_LABEL_KEYS = {
  regular: 'match.maximumFromRegular',
  extra_time: 'match.maximumFromExtraTime',
} as const satisfies Record<MaximumSource, string>;

/**
 * Bloque `limits` de `GET /matches/{id}/operation` tal como lo consume la
 * pantalla. Los cuatro campos aditivos exponen la configuración efectiva de la
 * fase; los demás ya existían. Todo es opcional para tolerar un servidor
 * anterior o una respuesta incompleta sin romper la operación.
 */
export interface OperationLimits {
  readonly max_minute_regular?: number | null;
  readonly max_minute_extra?: number | null;
  readonly extra_time_enabled?: boolean;
  readonly penalties_enabled?: boolean;
  readonly max_minute?: number | null;
  readonly added_minute_max?: number | null;
}

/** Límites efectivos para la resolución prevista (RF-032, RF-033). */
export interface ResolutionLimits {
  readonly maxMinute: number;
  readonly addedMax: number;
}

function integer(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null;
}

function isResolutionType(value: unknown): value is ResolutionType {
  return typeof value === 'string' && (RESOLUTION_TYPES as readonly string[]).includes(value);
}

/**
 * Resoluciones habilitadas por la configuración efectiva de la fase (RF-033).
 *
 * La prórroga y los penales dependen de su propio indicador; el tiempo
 * reglamentario, el walkover y la resolución administrativa siguen el criterio
 * que ya aplica el servidor. Se derivan **solo** de `limits`: el cliente no
 * consulta la configuración de la versión.
 */
export function enabledResolutions(
  limits: OperationLimits | null | undefined,
): ResolutionType[] {
  const options: ResolutionType[] = [DEFAULT_RESOLUTION];
  if (limits?.extra_time_enabled === true) options.push('extra_time');
  if (limits?.penalties_enabled === true) options.push('penalties');
  options.push('walkover', 'administrative');
  return options;
}

/** Si la resolución está habilitada por la configuración efectiva (RF-033). */
export function resolutionEnabled(
  limits: OperationLimits | null | undefined,
  resolution: unknown,
): boolean {
  if (!isResolutionType(resolution)) return false;
  if (resolution === 'extra_time') return limits?.extra_time_enabled === true;
  if (resolution === 'penalties') return limits?.penalties_enabled === true;
  return true;
}

/**
 * Resolución efectiva: la pedida si está habilitada y, si no, tiempo
 * reglamentario. Sin `limits` también cae a regular sin romper (RF-034).
 */
export function normalizeResolution(
  limits: OperationLimits | null | undefined,
  requested: unknown,
): ResolutionType {
  if (isResolutionType(requested) && resolutionEnabled(limits, requested)) return requested;
  return DEFAULT_RESOLUTION;
}

/**
 * Máximo de minuto de la resolución, leído de `limits` del servidor.
 *
 * Con prórroga o penales usa `max_minute_extra` solo si la fase habilitó la
 * prórroga (el servidor ya lo envía resuelto); en cualquier otro caso usa
 * `max_minute_regular`. Si el bloque falta o está incompleto se conserva el
 * tope estructural que la pantalla ya usaba como último recurso.
 */
export function maximumMinuteFor(
  limits: OperationLimits | null | undefined,
  resolution: unknown,
): number {
  const effective = normalizeResolution(limits, resolution);
  if (effective === 'extra_time' || effective === 'penalties') {
    const extra = integer(limits?.max_minute_extra);
    if (extra !== null) return extra;
  }
  const regular = integer(limits?.max_minute_regular);
  if (regular !== null) return regular;
  const phaseMaximum = integer(limits?.max_minute);
  if (phaseMaximum !== null) return phaseMaximum;
  return DEFAULT_MATCH_LIMITS.max_minute;
}

/** Tope de minuto añadido, también resuelto por el servidor. */
export function addedMinuteMaximum(limits: OperationLimits | null | undefined): number {
  return integer(limits?.added_minute_max) ?? DEFAULT_MATCH_LIMITS.added_minute_max;
}

/** Si el máximo aplicable procede del reglamentario o de la prórroga (RF-033). */
export function maximumMinuteSource(
  limits: OperationLimits | null | undefined,
  resolution: unknown,
): MaximumSource {
  const effective = normalizeResolution(limits, resolution);
  if (
    (effective === 'extra_time' || effective === 'penalties')
    && integer(limits?.max_minute_extra) !== null
  ) {
    return 'extra_time';
  }
  return 'regular';
}

/** Límites que la pantalla muestra y aplica a eventos y segmentos (RF-032). */
export function matchLimitsFor(
  limits: OperationLimits | null | undefined,
  resolution: unknown,
): ResolutionLimits {
  return {
    maxMinute: maximumMinuteFor(limits, resolution),
    addedMax: addedMinuteMaximum(limits),
  };
}

// ---------------------------------------------------------------------------
// Tope combinado de minuto (RF-032, caso 20)
//
// Regla única del servidor en `validate_event_minute`
// (`backend/app/modules/matches/service.py`): el máximo se aplica sobre
// `minute + added_minute`. Antes del minuto final la suma no puede pasarlo; en
// el minuto final se admite el añadido dentro del tope estructural. El cliente
// usa esta función al añadir un evento y al juzgar un borrador restaurado, para
// que ningún registro aceptado al operar sea rechazado al cerrar.
// ---------------------------------------------------------------------------

/** Motivo del rechazo del tope combinado. */
export type EventMinuteReason = 'minute' | 'combined' | 'added';

/** Resultado puro de la validación de minuto y minuto añadido (RF-032). */
export interface EventMinuteValidation {
  readonly ok: boolean;
  readonly reason: EventMinuteReason | null;
  readonly minute: number;
  readonly added: number;
  readonly max: number;
  /** Tope estructural del minuto añadido, resuelto por el servidor. */
  readonly addedMax: number;
}

/**
 * Aplica el tope combinado del cierre (RF-032) sin duplicar la regla en cada
 * pantalla. Mismo orden que el servidor: primero el minuto, después la suma
 * cuando el evento ocurre antes del minuto final y, por último, el tope
 * estructural del añadido.
 */
export function validateEventMinute(
  minute: unknown,
  addedMinute: unknown,
  max: number,
  addedMax: number,
): EventMinuteValidation {
  const exactMinute = integer(minute);
  const exactAdded = integer(addedMinute ?? 0);
  const limit = integer(max) ?? 0;
  const structural = integer(addedMax) ?? 0;

  const result = (ok: boolean, reason: EventMinuteReason | null): EventMinuteValidation => ({
    ok,
    reason,
    minute: exactMinute ?? 0,
    added: exactAdded ?? 0,
    max: limit,
    addedMax: structural,
  });

  if (exactMinute === null || exactMinute > limit) return result(false, 'minute');
  if (exactAdded === null) return result(false, 'added');
  if (exactMinute < limit && exactMinute + exactAdded > limit) return result(false, 'combined');
  if (exactAdded > structural) return result(false, 'added');
  return result(true, null);
}

/** Evento del borrador que el cierre rechazaría por el tope combinado. */
export interface DraftMinuteViolation<T> {
  readonly index: number;
  readonly event: T;
  readonly validation: EventMinuteValidation;
}

/**
 * Eventos del borrador local que superan el tope combinado con los límites
 * vigentes (RF-032). No borra ni modifica la lista: el operador decide si
 * corrige el minuto o retira el evento, y el cierre queda bloqueado mientras
 * haya alguno. Se usa al restaurar el borrador y al pintar su aviso.
 */
export function findDraftMinuteViolations<T extends {
  readonly minute?: unknown;
  readonly added_minute?: unknown;
}>(
  events: readonly T[] | null | undefined,
  max: number,
  addedMax: number,
): DraftMinuteViolation<T>[] {
  const violations: DraftMinuteViolation<T>[] = [];
  (events ?? []).forEach((event, index) => {
    const validation = validateEventMinute(event.minute, event.added_minute, max, addedMax);
    if (!validation.ok) violations.push({ index, event, validation });
  });
  return violations;
}

/**
 * Cuerpo que se envía al crear o interrumpir un segmento y al cerrar (RF-033):
 * siempre la resolución mostrada, normalizada si la configuración cambió.
 */
export function resolutionPayload(
  limits: OperationLimits | null | undefined,
  resolution: unknown,
): { resolution_type: ResolutionType } {
  return { resolution_type: normalizeResolution(limits, resolution) };
}

// ---------------------------------------------------------------------------
// Cambio de resolución prevista (RF-033, RF-034, P2)
//
// Tres resultados puros:
//
// - `ok`:      nada queda fuera del nuevo máximo.
// - `confirm`: solo hay **eventos del borrador** fuera del máximo; se avisa y
//              no se borra ni se envía nada: el operador decide.
// - `blocked`: hay **segmentos ya persistidos** (datos del servidor) fuera del
//              máximo; el cambio no se permite y no hay contrato de corrección
//              de segmentos (P2).
//
// Los segmentos persistidos son datos del servidor; los eventos son del
// borrador local. Ninguna función toca la red, el reloj ni el almacenamiento.
// ---------------------------------------------------------------------------

/** Resultado del cambio de resolución (RF-033, P2). */
export type ResolutionChangeKind = 'ok' | 'confirm' | 'blocked';

/** Claves i18n del mensaje del cambio de resolución (RF-029). */
export const RESOLUTION_CHANGE_MESSAGE_KEYS = {
  ok: 'match.resolutionChangeOk',
  confirm: 'match.resolutionChangeNeedsConfirmation',
  blocked: 'match.resolutionChangeBlocked',
} as const;

/** Claves i18n del aviso del cierre con otra resolución (RF-034). */
export const CLOSE_RESOLUTION_MESSAGE_KEYS = {
  confirm: 'match.closeResolutionConfirm',
  confirmWithDraft: 'match.closeResolutionWithAffectedDraft',
} as const;

/**
 * Segmento tal como lo devuelve el servidor. Solo se leen el número, el inicio
 * y el fin; el estado no cambia el juicio (un segmento abierto cuenta por su
 * inicio, porque todavía no tiene fin).
 */
export interface ResolutionSegmentInput {
  readonly id?: string | null;
  readonly segment_number?: number | null;
  readonly minute_start?: number | null;
  readonly minute_end?: number | null;
  readonly status?: string | null;
}

/** Evento del borrador local tal como lo juzga el cambio de resolución. */
export interface ResolutionDraftEventInput {
  readonly client_event_id?: string | null;
  readonly event_type?: string | null;
  readonly minute?: number | null;
  readonly added_minute?: number | null;
  readonly segment_id?: string | null;
}

/** Segmento persistido que supera el nuevo máximo. */
export interface OutOfLimitSegment {
  readonly id: string | null;
  readonly segment_number: number | null;
  /** Minuto por el que se juzga: el fin o, si sigue abierto, el inicio. */
  readonly minute: number;
  readonly max: number;
}

/** Evento del borrador que supera el nuevo máximo. */
export interface OutOfLimitEvent {
  readonly index: number;
  readonly client_event_id: string | null;
  readonly event_type: string | null;
  readonly minute: number;
  readonly added_minute: number;
  /** Minutos que excede el máximo (nunca menor que 1). */
  readonly over: number;
  readonly max: number;
}

/** Resultado del cambio de resolución, con los datos del aviso. */
export interface ResolutionChangeResult {
  readonly outcome: ResolutionChangeKind;
  readonly maxMinute: number;
  /** Segmentos persistidos fuera de límite: bloquean el cambio (P2). */
  readonly segments: readonly OutOfLimitSegment[];
  /** Eventos del borrador fuera de límite: se avisan sin borrarse. */
  readonly events: readonly OutOfLimitEvent[];
  readonly messageKey: string;
  readonly messageParams: Record<string, string | number>;
}

function segmentMinute(segment: ResolutionSegmentInput): number {
  const end = integer(segment.minute_end);
  if (end !== null) return end;
  return integer(segment.minute_start) ?? 0;
}

/**
 * Minutos que un evento del borrador excede el máximo: más allá del minuto
 * final, o antes del final cuando la suma con el añadido lo pasa (RF-032).
 * En el minuto final se admite el añadido dentro del tope estructural.
 */
function eventExcess(event: ResolutionDraftEventInput, max: number): number {
  const minute = integer(event.minute) ?? 0;
  const added = integer(event.added_minute) ?? 0;
  if (minute > max) return minute - max;
  if (minute === max) return 0;
  return Math.max(0, minute + added - max);
}

/**
 * Juzga un cambio de resolución contra los segmentos persistidos y los eventos
 * del borrador (plan §3.5). No modifica ninguna de las dos listas.
 */
export function resolutionChangeOutcome(
  persistedSegments: readonly ResolutionSegmentInput[] | null | undefined,
  draftEvents: readonly ResolutionDraftEventInput[] | null | undefined,
  newMax: number,
): ResolutionChangeResult {
  const max = integer(newMax) ?? 0;

  const segments: OutOfLimitSegment[] = [];
  for (const segment of persistedSegments ?? []) {
    const minute = segmentMinute(segment);
    if (minute > max) {
      segments.push({
        id: typeof segment.id === 'string' ? segment.id : null,
        segment_number: integer(segment.segment_number),
        minute,
        max,
      });
    }
  }

  const events: OutOfLimitEvent[] = [];
  (draftEvents ?? []).forEach((event, index) => {
    const over = eventExcess(event, max);
    if (over <= 0) return;
    events.push({
      index,
      client_event_id: typeof event.client_event_id === 'string' ? event.client_event_id : null,
      event_type: typeof event.event_type === 'string' ? event.event_type : null,
      minute: integer(event.minute) ?? 0,
      added_minute: integer(event.added_minute) ?? 0,
      over,
      max,
    });
  });

  if (segments.length) {
    const first = segments[0]!;
    return {
      outcome: 'blocked',
      maxMinute: max,
      segments,
      events,
      messageKey: RESOLUTION_CHANGE_MESSAGE_KEYS.blocked,
      messageParams: {
        count: segments.length,
        segment: first.segment_number ?? first.id ?? '',
        minute: first.minute,
        max,
      },
    };
  }

  if (events.length) {
    const minute = events.reduce((highest, event) => Math.max(highest, event.minute), 0);
    return {
      outcome: 'confirm',
      maxMinute: max,
      segments,
      events,
      messageKey: RESOLUTION_CHANGE_MESSAGE_KEYS.confirm,
      messageParams: { count: events.length, minute, max },
    };
  }

  return {
    outcome: 'ok',
    maxMinute: max,
    segments,
    events,
    messageKey: RESOLUTION_CHANGE_MESSAGE_KEYS.ok,
    messageParams: { count: 0, max },
  };
}

/** Entrada del cierre con la resolución prevista (RF-034, RP-1). */
export interface CloseResolutionInput {
  /** Resolución anunciada al empezar la operación (la de la pestaña). */
  readonly planned?: unknown;
  /** Resolución con la que se intenta cerrar: la del único control. */
  readonly chosen?: unknown;
  readonly limits?: OperationLimits | null;
  readonly segments?: readonly ResolutionSegmentInput[] | null;
  readonly draftEvents?: readonly ResolutionDraftEventInput[] | null;
  /** Confirmación explícita ya obtenida del operador. */
  readonly confirmed?: boolean;
}

/** Decisión pura de cierre; `send` es lo único que habilita la petición. */
export interface CloseResolutionDecision {
  readonly outcome: ResolutionChangeKind;
  /** Resolución prevista con la que se anunció la operación. */
  readonly planned: ResolutionType;
  /** Resolución con la que se cerraría: la mostrada. */
  readonly chosen: ResolutionType;
  /** Si la resolución elegida difiere de la prevista y es compatible. */
  readonly changed: boolean;
  /** Hay que pedir confirmación explícita antes de enviar. */
  readonly needsConfirmation: boolean;
  /** `true` solo si se puede enviar el cierre (compatible y confirmado). */
  readonly send: boolean;
  readonly maxMinute: number;
  readonly segments: readonly OutOfLimitSegment[];
  readonly events: readonly OutOfLimitEvent[];
  readonly messageKey: string;
  readonly messageParams: Record<string, string | number>;
}

/**
 * Decide si el cierre puede enviarse (plan §3.5, RF-034).
 *
 * - Con segmentos persistidos fuera del máximo: `blocked`, no se envía y no hay
 *   confirmación posible para un cambio incompatible.
 * - Con la resolución prevista: se envía como hoy.
 * - Con otra resolución compatible: `confirm`; `send` solo es `true` cuando
 *   `confirmed` ya es `true`. Sin confirmación, el acta sigue abierta.
 */
export function closeResolutionDecision(input: CloseResolutionInput): CloseResolutionDecision {
  const chosen = normalizeResolution(input.limits, input.chosen);
  const planned = normalizeResolution(input.limits, input.planned);
  const maxMinute = maximumMinuteFor(input.limits, chosen);
  const result = resolutionChangeOutcome(input.segments, input.draftEvents, maxMinute);
  const changed = chosen !== planned;

  const base = {
    planned,
    chosen,
    changed,
    maxMinute,
    segments: result.segments,
    events: result.events,
  };

  if (result.outcome === 'blocked') {
    return {
      ...base,
      outcome: 'blocked',
      needsConfirmation: false,
      send: false,
      messageKey: result.messageKey,
      messageParams: result.messageParams,
    };
  }

  if (!changed) {
    return {
      ...base,
      outcome: 'ok',
      needsConfirmation: false,
      send: true,
      messageKey: RESOLUTION_CHANGE_MESSAGE_KEYS.ok,
      messageParams: result.messageParams,
    };
  }

  return {
    ...base,
    outcome: 'confirm',
    needsConfirmation: true,
    send: input.confirmed === true,
    messageKey: result.events.length
      ? CLOSE_RESOLUTION_MESSAGE_KEYS.confirmWithDraft
      : CLOSE_RESOLUTION_MESSAGE_KEYS.confirm,
    messageParams: { ...result.messageParams, resolution: chosen, planned },
  };
}

/** Versión del formato guardado; un valor de otra versión se ignora. */
export const RESOLUTION_STORAGE_VERSION = 1;

/** Contexto que identifica la resolución prevista (P3). */
export interface ResolutionScope {
  readonly userId?: string | null;
  readonly organizationId?: string | null;
  readonly matchId?: string | null;
}

/** Parte de `Storage` que la resolución necesita. */
export type ResolutionStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function scopePart(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Un identificador con separadores o espacios podría mezclar dos contextos.
  if (/[:\s]/.test(trimmed)) return null;
  return trimmed;
}

/**
 * Clave de la resolución prevista (plan §6):
 * `bc_match_resolution:{userId}:{orgId}:{matchId}`. Sin todos los
 * identificadores no se persiste nada.
 */
export function resolutionKey(scope: ResolutionScope): string | null {
  const userId = scopePart(scope.userId);
  const organizationId = scopePart(scope.organizationId);
  const matchId = scopePart(scope.matchId);
  if (!userId || !organizationId || !matchId) return null;
  return ['bc_match_resolution', userId, organizationId, matchId].join(':');
}

/** Formato guardado de la resolución prevista. */
export function serializeResolution(resolution: ResolutionType): string {
  return JSON.stringify({ version: RESOLUTION_STORAGE_VERSION, resolution_type: resolution });
}

/** Lee un valor guardado; ilegible, de otra versión o desconocido → `null`. */
export function parseStoredResolution(raw: string | null | undefined): ResolutionType | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const value = parsed as { version?: unknown; resolution_type?: unknown };
  if (value.version !== RESOLUTION_STORAGE_VERSION) return null;
  return isResolutionType(value.resolution_type) ? value.resolution_type : null;
}

export interface ResolutionStore {
  /** Clave efectiva, o `null` si falta un identificador y no se persiste. */
  readonly key: string | null;
  readonly available: boolean;
  read(): ResolutionType | null;
  save(resolution: ResolutionType): boolean;
  clear(): boolean;
}

/**
 * Acceso a la resolución de un contexto sobre el almacenamiento recibido (la
 * sesión de la pestaña en el composable, un doble en las pruebas). Cualquier
 * fallo del almacenamiento se comporta como «no hay valor» y nunca rompe la
 * operación.
 */
export function createResolutionStore(
  scope: ResolutionScope,
  storage: ResolutionStorage | null,
): ResolutionStore {
  const key = resolutionKey(scope);
  const available = Boolean(key && storage);

  return {
    key,
    available,
    read(): ResolutionType | null {
      if (!key || !storage) return null;
      try {
        return parseStoredResolution(storage.getItem(key));
      } catch {
        return null;
      }
    },
    save(resolution: ResolutionType): boolean {
      if (!key || !storage || !isResolutionType(resolution)) return false;
      try {
        storage.setItem(key, serializeResolution(resolution));
        return true;
      } catch {
        return false;
      }
    },
    clear(): boolean {
      if (!key || !storage) return false;
      try {
        storage.removeItem(key);
        return true;
      } catch {
        return false;
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Conflictos de la operación (spec 012, H4-T09: RF-050 y RF-046).
//
// Dos 409 de la misma ruta se distinguen por el campo **aditivo** `code`:
// `RESOLUTION_NOT_ENABLED` (resolución no habilitada en la fase) y
// `ROSTER_SIZE_OUT_OF_RANGE` (apertura bloqueada por tamaño de plantilla). El
// detalle no se interpreta para decidir: un 409 antiguo sin `code` cae en
// `other` y conserva el comportamiento previo, que muestra su `detail`.
// ---------------------------------------------------------------------------

export const RESOLUTION_NOT_ENABLED_CODE = 'RESOLUTION_NOT_ENABLED';
export const ROSTER_SIZE_OUT_OF_RANGE_CODE = 'ROSTER_SIZE_OUT_OF_RANGE';

export type MatchConflictKind =
  | 'resolution_not_enabled'
  | 'roster_size_out_of_range'
  | 'other';

/** Causa de un 409 de operación según su `code` aditivo, sin mirar el texto. */
export function classifyMatchConflict(cause: unknown): MatchConflictKind {
  const code = getApiCode(cause);
  if (code === ROSTER_SIZE_OUT_OF_RANGE_CODE) return 'roster_size_out_of_range';
  if (code === RESOLUTION_NOT_ENABLED_CODE) return 'resolution_not_enabled';
  return 'other';
}

/** `detail` del cuerpo del error, si es una cadena; nunca lo inventa. */
export function matchConflictDetail(cause: unknown): string | null {
  const failure = cause as { data?: unknown } | null | undefined;
  const data = failure?.data;
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const detail = (data as { detail?: unknown }).detail;
  return typeof detail === 'string' ? detail : null;
}
