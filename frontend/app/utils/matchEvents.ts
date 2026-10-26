/**
 * Catálogo de eventos del acta y utilidades puras del formulario por tipo
 * (spec 015, RF-001, RF-004, RF-005, RF-006 y RF-015).
 *
 * La fuente de verdad del contrato es `backend/app/modules/matches/schemas.py`:
 * siete tipos cerrados, `extra="forbid"` en la raíz, `metadata` solo con
 * `red_card_type` en una roja, `beneficiary_team_id` solo en el autogol, el par
 * salida/entrada solo en la sustitución y `assist_player_id` solo en el gol.
 *
 * Este módulo es framework-free: no lee el reloj, el entorno, la red ni el
 * almacenamiento. La fuente de UUID entra por parámetro (`newClientEventId`) y
 * los nombres por un resolutor (`eventSummary`), de modo que todo es
 * determinista y se prueba con `node --test`.
 *
 * Qué **no** hace, porque es autoridad del servidor (RF-006, RF-008):
 * comprobar la plantilla del partido, las sanciones, el estado en campo del
 * asistente, los límites y ventanas de sustitución, la versión del torneo y la
 * coherencia con el marcador.
 */

import type { DraftEvent } from './substitutions.ts';

/** Los siete tipos del catálogo cerrado, en el orden en que se ofrecen. */
export const EVENT_TYPES = [
  'goal',
  'own_goal',
  'penalty_goal',
  'yellow_card',
  'red_card',
  'substitution',
  'foul',
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

/**
 * Campos compartidos por todos los tipos. Se muestran siempre y no forman parte
 * de la partición de campos propios (`required`/`optional`/`forbidden`).
 */
export const EVENT_FIELDS = ['event_type', 'team', 'segment', 'minute', 'added_minute'] as const;

export type SharedEventField = (typeof EVENT_FIELDS)[number];

/** Campo propio de un tipo de evento. */
export type EventField =
  | 'player'
  | 'player_out'
  | 'player_in'
  | 'assist'
  | 'beneficiary'
  | 'red_card_type';

/** Campos propios que un tipo exige, admite o prohíbe (RF-001). */
export interface EventFields {
  readonly type: EventType;
  readonly required: readonly EventField[];
  readonly optional: readonly EventField[];
  /** Informarlo en este tipo es **422** en el servidor. */
  readonly forbidden: readonly EventField[];
}

/**
 * Catálogo de campos por tipo (spec 015, apéndice A).
 *
 * Los campos prohibidos no se renderizan ni viajan con valor: el payload los
 * deja en `null` —el servidor admite el nulo de un campo declarado— o los omite
 * (`metadata`), porque una clave desconocida o un valor fuera de su tipo es
 * **422**. En `substitution` el campo `player` no existe: quién sale es
 * `player_out` y el cierre deriva `player_id` de él.
 */
export const EVENT_FIELD_CATALOG: Readonly<Record<EventType, EventFields>> = {
  goal: {
    type: 'goal',
    required: ['player'],
    // RF-007: la asistencia es opcional siempre y solo existe en el gol.
    optional: ['assist'],
    forbidden: ['beneficiary', 'player_out', 'player_in', 'red_card_type'],
  },
  own_goal: {
    type: 'own_goal',
    // El autor pertenece al equipo que concede y el beneficiario es el otro.
    required: ['player', 'beneficiary'],
    optional: [],
    forbidden: ['assist', 'player_out', 'player_in', 'red_card_type'],
  },
  penalty_goal: {
    type: 'penalty_goal',
    required: ['player'],
    optional: [],
    forbidden: ['assist', 'beneficiary', 'player_out', 'player_in', 'red_card_type'],
  },
  yellow_card: {
    type: 'yellow_card',
    required: ['player'],
    optional: [],
    forbidden: ['assist', 'beneficiary', 'player_out', 'player_in', 'red_card_type'],
  },
  red_card: {
    type: 'red_card',
    // La clase de roja viaja dentro de `metadata`, con `direct_red` por defecto.
    required: ['player', 'red_card_type'],
    optional: [],
    forbidden: ['assist', 'beneficiary', 'player_out', 'player_in'],
  },
  substitution: {
    type: 'substitution',
    required: ['player_out', 'player_in'],
    optional: [],
    forbidden: ['player', 'assist', 'beneficiary', 'red_card_type'],
  },
  foul: {
    type: 'foul',
    // RF-004: la falta es informativa y solo añade el jugador.
    required: ['player'],
    optional: [],
    forbidden: ['assist', 'beneficiary', 'player_out', 'player_in', 'red_card_type'],
  },
};

const MAX_MINUTE = 180;
const MAX_ADDED_MINUTE = 30;

/** Catálogo del tipo, o `null` si el tipo no pertenece al catálogo cerrado. */
export function eventFields(type: string): EventFields | null {
  return Object.prototype.hasOwnProperty.call(EVENT_FIELD_CATALOG, type)
    ? EVENT_FIELD_CATALOG[type as EventType]
    : null;
}

/**
 * Campos propios que el formulario debe **renderizar** para el tipo, en el
 * orden del catálogo: primero los obligatorios y después los opcionales.
 *
 * Los prohibidos no se devuelven porque no se muestran (RF-001: ausentes, no
 * deshabilitados); los compartidos (equipo, segmento, minuto y añadido) se
 * pintan siempre, fuera de esta lista. Un tipo desconocido no muestra ninguno.
 */
export function visibleEventFields(type: string): readonly EventField[] {
  const fields = eventFields(type);
  return fields ? [...fields.required, ...fields.optional] : [];
}

/**
 * Si el campo propio es obligatorio para el tipo (RF-001). Es la misma fuente
 * que pinta el formulario, así que la marca visual no puede desalinearse del
 * catálogo. La asistencia nunca es obligatoria (DU-2).
 */
export function isEventFieldRequired(type: string, field: EventField): boolean {
  return eventFields(type)?.required.includes(field) ?? false;
}

// ---------------------------------------------------------------------------
// Anuncio del cambio de tipo (RNF-007)
// ---------------------------------------------------------------------------

/** Etiqueta de cada campo propio en el anuncio; los textos son del catálogo. */
const EVENT_FIELD_LABEL_KEYS: Readonly<Record<EventField, string>> = {
  player: 'match.player',
  player_out: 'match.playerOut',
  player_in: 'match.playerIn',
  assist: 'match.assist',
  beneficiary: 'match.beneficiary',
  red_card_type: 'match.redCardType',
};

/** Traductor mínimo del anuncio: el `t` de la pantalla o un doble en la prueba. */
export type EventTypeTranslator = (
  key: string,
  params?: Record<string, string | number>,
) => string;

/**
 * Anuncio del cambio de tipo de evento (RNF-007). Un `<select>` nativo anuncia
 * su valor, pero no que el formulario cambie sus campos: al pasar a autogol
 * aparece el equipo beneficiario, al pasar a roja la clase y las tarjetas o el
 * penalti retiran la asistencia. Devuelve el tipo y **sus** campos en el orden
 * del catálogo, para que la pantalla lo escriba en una región `role="status"`
 * siempre presente (una región que se monta con el cambio no se anuncia). Un
 * tipo fuera del catálogo cerrado no tiene nada que anunciar.
 */
export function eventTypeAnnouncement(
  type: string,
  typeLabel: string,
  t: EventTypeTranslator,
): string | null {
  if (!eventFields(type)) return null;
  const fields = visibleEventFields(type).map((field) => t(EVENT_FIELD_LABEL_KEYS[field]));
  return t('match.eventTypeChanged', { type: typeLabel, fields: fields.join(', ') });
}

// ---------------------------------------------------------------------------
// Fuente de UUID (RF-015, D-5)
// ---------------------------------------------------------------------------

/** Parte de `crypto` que el identificador necesita; en las pruebas, un doble. */
export interface UuidSource {
  randomUUID?: () => unknown;
}

const UUID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

/**
 * Forma canónica de UUID que exige la API: 36 caracteres y guiones, mayúsculas
 * o minúsculas. La longitud se comprueba aparte porque `$` admitiría un salto
 * de línea final, que el servidor rechaza.
 */
export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && value.length === 36 && UUID_PATTERN.test(value);
}

/**
 * Identificador de cliente nuevo. Devuelve `null` —nunca un texto inventado—
 * cuando la fuente no ofrece `randomUUID`, cuando lanza o cuando no devuelve un
 * UUID: el evento no se añade y la pantalla lo explica (T9/T11).
 */
export function newClientEventId(source: UuidSource | null | undefined): string | null {
  if (!source || typeof source.randomUUID !== 'function') return null;
  let candidate: unknown;
  try {
    candidate = source.randomUUID();
  } catch {
    return null;
  }
  return isUuid(candidate) ? candidate : null;
}

/**
 * Descarta los eventos del borrador cuyo `client_event_id` no es un UUID (D-9):
 * los borradores anteriores a la spec guardaban `event-<marca>-<índice>`, que
 * el servidor ahora rechaza con 422. No se reescribe el identificador —cambiaría
 * la identidad de un evento que aún no existe en el servidor—: se descarta y se
 * informa de cuántos, para avisar al operador (T10/T11). El orden del resto se
 * conserva.
 */
export function dropLegacyClientEventIds<T extends { readonly client_event_id?: unknown }>(
  events: readonly T[] | null | undefined,
): { readonly events: T[]; readonly dropped: number } {
  const kept: T[] = [];
  let dropped = 0;
  for (const event of events ?? []) {
    if (isUuid(event.client_event_id)) {
      kept.push(event);
    } else {
      dropped += 1;
    }
  }
  return { events: kept, dropped };
}

// ---------------------------------------------------------------------------
// Validación de cliente (RF-006)
// ---------------------------------------------------------------------------

export type EventValidationCode =
  | 'unknown_event_type'
  | 'missing_player'
  | 'missing_beneficiary'
  | 'beneficiary_same_team'
  | 'missing_player_out'
  | 'missing_player_in'
  | 'same_substitution_player'
  | 'assist_same_as_scorer'
  | 'assist_not_in_goal';

/** Problema de estructura del formulario, junto al campo que lo causa. */
export interface EventValidationIssue {
  readonly field: EventField | 'event_type';
  readonly code: EventValidationCode;
}

export interface EventValidation {
  readonly ok: boolean;
  /** Orden estable: primero los campos del tipo, después la asistencia. */
  readonly issues: readonly EventValidationIssue[];
}

/** Valores del formulario que la validación de cliente necesita. */
export interface EventFormValues {
  readonly event_type?: unknown;
  readonly team_id?: unknown;
  readonly player_id?: unknown;
  readonly assist_player_id?: unknown;
  readonly beneficiary_team_id?: unknown;
  readonly player_out_id?: unknown;
  readonly player_in_id?: unknown;
  readonly red_card_type?: unknown;
  readonly minute?: unknown;
  readonly added_minute?: unknown;
}

function text(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const candidate = value.trim();
  return candidate.length > 0 ? candidate : null;
}

function integerBetween(value: unknown, min: number, max: number): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value)) return null;
  return value >= min && value <= max ? value : null;
}

/**
 * Subconjunto exacto de RF-006 que el cliente comprueba: campos obligatorios
 * por tipo, beneficiario distinto del equipo del autor, par de sustitución
 * completo y con jugadores distintos, y asistente solo en un gol y distinto del
 * goleador. No juzga plantilla, sanciones, versión ni marcador.
 */
export function validateEventValues(values: EventFormValues): EventValidation {
  const fields = typeof values.event_type === 'string' ? eventFields(values.event_type) : null;
  if (!fields) {
    return { ok: false, issues: [{ field: 'event_type', code: 'unknown_event_type' }] };
  }

  const issues: EventValidationIssue[] = [];
  const player = text(values.player_id);

  if (fields.type === 'substitution') {
    const playerOut = text(values.player_out_id);
    const playerIn = text(values.player_in_id);
    if (!playerOut) issues.push({ field: 'player_out', code: 'missing_player_out' });
    if (!playerIn) {
      issues.push({ field: 'player_in', code: 'missing_player_in' });
    } else if (playerOut && playerOut === playerIn) {
      issues.push({ field: 'player_in', code: 'same_substitution_player' });
    }
  } else {
    if (!player) issues.push({ field: 'player', code: 'missing_player' });
    if (fields.type === 'own_goal') {
      const beneficiary = text(values.beneficiary_team_id);
      if (!beneficiary) {
        issues.push({ field: 'beneficiary', code: 'missing_beneficiary' });
      } else if (beneficiary === text(values.team_id)) {
        issues.push({ field: 'beneficiary', code: 'beneficiary_same_team' });
      }
    }
  }

  const assist = text(values.assist_player_id);
  if (assist) {
    if (fields.type !== 'goal') {
      // RF-009: autogol, penalti, tarjetas, sustitución y falta no admiten
      // asistencia; el servidor responde 422.
      issues.push({ field: 'assist', code: 'assist_not_in_goal' });
    } else if (player && assist === player) {
      issues.push({ field: 'assist', code: 'assist_same_as_scorer' });
    }
  }

  return { ok: issues.length === 0, issues };
}

// ---------------------------------------------------------------------------
// Intervalo del segmento (RF-006, viñeta 2)
// ---------------------------------------------------------------------------

/** Ventana del segmento seleccionado que el formulario necesita. */
export interface SegmentWindowLike {
  readonly minute_start?: unknown;
  readonly minute_end?: unknown;
}

export type SegmentMinuteIssue = 'before_segment' | 'after_segment';

export interface SegmentMinuteValidation {
  readonly ok: boolean;
  readonly issue: SegmentMinuteIssue | null;
  readonly start: number | null;
  readonly end: number | null;
}

/**
 * Subconjunto de RF-006 que ata el minuto al **segmento seleccionado**: el
 * minuto no puede ser anterior a su inicio ni posterior a su fin cuando el
 * segmento ya tiene fin. Se aplica solo al minuto, como el servidor
 * (`service.py`, «fuera del intervalo de su segmento»); la autoridad sigue
 * siendo el cierre. Un segmento sin fin abierto no impone tope superior y un
 * minuto no entero lo juzga la validación de minutos.
 */
export function validateSegmentMinute(
  minute: unknown,
  segment: SegmentWindowLike | null | undefined,
): SegmentMinuteValidation {
  const start = integerBetween(segment?.minute_start, 0, MAX_MINUTE);
  const end = integerBetween(segment?.minute_end, 0, MAX_MINUTE);
  const exactMinute = integerBetween(minute, 0, MAX_MINUTE);
  if (exactMinute === null) {
    return { ok: true, issue: null, start, end };
  }
  if (start !== null && exactMinute < start) {
    return { ok: false, issue: 'before_segment', start, end };
  }
  if (end !== null && exactMinute > end) {
    return { ok: false, issue: 'after_segment', start, end };
  }
  return { ok: true, issue: null, start, end };
}

// ---------------------------------------------------------------------------
// Payload del evento (RF-002, RF-007, RF-015)
// ---------------------------------------------------------------------------

/**
 * Evento listo para el borrador local y para el cierre: la forma de
 * `DraftEvent` más el campo nuevo de la asistencia.
 */
export interface BuiltMatchEvent extends DraftEvent<EventType> {
  assist_player_id: string | null;
}

/**
 * Construye el payload del tipo a partir del formulario.
 *
 * Solo escribe los campos que el tipo declara: los prohibidos viajan en `null`
 * (nunca con valor) y `metadata` se omite salvo en una roja, porque el servidor
 * rechaza con 422 una clave desconocida y un `beneficiary_team_id` no nulo fuera
 * del autogol. Devuelve `null` si el formulario no es construible —estructura
 * incompleta, minuto fuera del tope estructural o identificador que no es
 * UUID—, de modo que ningún evento inválido llega al borrador.
 */
export function buildDraftEvent(
  form: EventFormValues,
  segmentId: unknown,
  clientEventId: unknown,
): BuiltMatchEvent | null {
  if (!validateEventValues(form).ok) return null;

  const type = form.event_type as EventType;
  const clientId = text(clientEventId);
  const segment = text(segmentId);
  const team = text(form.team_id);
  if (!clientId || !isUuid(clientId) || !segment || !team) return null;

  const minute = integerBetween(form.minute, 0, MAX_MINUTE);
  const rawAdded = form.added_minute;
  const added = rawAdded === undefined || rawAdded === null || rawAdded === ''
    ? 0
    : integerBetween(rawAdded, 0, MAX_ADDED_MINUTE);
  if (minute === null || added === null) return null;

  const playerOut = type === 'substitution' ? text(form.player_out_id) : null;
  const playerIn = type === 'substitution' ? text(form.player_in_id) : null;
  // El cierre exige `player_id === player_out_id` en una sustitución.
  const player = type === 'substitution' ? playerOut : text(form.player_id);
  if (!player) return null;

  const event: BuiltMatchEvent = {
    client_event_id: clientId,
    event_type: type,
    team_id: team,
    beneficiary_team_id: type === 'own_goal' ? text(form.beneficiary_team_id) : null,
    player_id: player,
    minute,
    added_minute: added,
    segment_id: segment,
    player_out_id: playerOut,
    player_in_id: playerIn,
    assist_player_id: type === 'goal' ? text(form.assist_player_id) : null,
  };

  if (type === 'red_card') {
    // `direct_red` es el valor por defecto que aplica el servidor (RF-001).
    event.metadata = {
      red_card_type: form.red_card_type === 'double_yellow_red'
        ? 'double_yellow_red'
        : 'direct_red',
    };
  }

  return event;
}

// ---------------------------------------------------------------------------
// Asistencia (RF-008, subconjunto del cliente)
// ---------------------------------------------------------------------------

/** Fila de la plantilla del partido que basta para juzgar al asistente. */
export interface AssistPlayerLike {
  readonly player_id?: unknown;
  readonly team_id?: unknown;
}

export type AssistIssue = 'missing_scorer' | 'same_as_scorer' | 'not_in_team';

export interface AssistValidation {
  readonly ok: boolean;
  readonly issue: AssistIssue | null;
  readonly assist_player_id: string | null;
}

function teamOf(playerId: string, players: readonly AssistPlayerLike[]): string | null {
  const row = players.find((player) => text(player.player_id) === playerId);
  return row ? text(row.team_id) : null;
}

/**
 * Candidatos a asistente: jugadores del **mismo equipo** que el goleador, sin
 * él. El estado en campo y la plantilla válida del partido son del servidor.
 */
export function assistCandidates<T extends AssistPlayerLike>(
  players: readonly T[],
  teamId: unknown,
  scorerId: unknown,
): T[] {
  const team = text(teamId);
  if (!team) return [];
  const scorer = text(scorerId);
  const seen = new Set<string>();
  const candidates: T[] = [];
  for (const player of players ?? []) {
    const playerId = text(player.player_id);
    if (!playerId || text(player.team_id) !== team) continue;
    if (playerId === scorer || seen.has(playerId)) continue;
    seen.add(playerId);
    candidates.push(player);
  }
  return candidates;
}

/**
 * Valida el asistente con el subconjunto de RF-006: distinto del goleador, del
 * mismo equipo y con jugador seleccionado. Que esté en la plantilla del
 * partido y en campo en ese minuto lo decide el servidor (**409**
 * `ASSIST_PLAYER_INVALID`).
 */
export function validateAssist(
  assistId: unknown,
  scorerId: unknown,
  players: readonly AssistPlayerLike[],
): AssistValidation {
  const assistant = text(assistId);
  if (!assistant) return { ok: true, issue: null, assist_player_id: null };

  const scorer = text(scorerId);
  if (!scorer) return { ok: false, issue: 'missing_scorer', assist_player_id: assistant };
  if (assistant === scorer) {
    return { ok: false, issue: 'same_as_scorer', assist_player_id: assistant };
  }

  const scorerTeam = teamOf(scorer, players);
  const assistTeam = teamOf(assistant, players);
  if (!scorerTeam || !assistTeam || scorerTeam !== assistTeam) {
    return { ok: false, issue: 'not_in_team', assist_player_id: assistant };
  }

  return { ok: true, issue: null, assist_player_id: assistant };
}

// ---------------------------------------------------------------------------
// Resumen del acta (RF-005)
// ---------------------------------------------------------------------------

/** Parte del evento que el resumen lee; sirve para el borrador y para el acta. */
export interface SummarizableEvent {
  readonly event_type?: unknown;
  readonly team_id?: unknown;
  readonly beneficiary_team_id?: unknown;
  readonly player_id?: unknown;
  readonly player_out_id?: unknown;
  readonly player_in_id?: unknown;
  readonly assist_player_id?: unknown;
  readonly metadata?: unknown;
}

/** Textos que el resumen necesita del catálogo; aquí no se escribe copia. */
export interface EventSummaryLabels {
  /** Forma corta del catálogo para «asistente» (`match.assistShort`): el
   * resumen la usa dentro de la frase y no como etiqueta de campo. */
  readonly assist?: string | null;
  /** «Beneficia a» del autogol (`match.ownGoalBeneficiaryShort`), junto al
   * equipo beneficiado (RF-005). */
  readonly ownGoal?: string | null;
  /** Clase de la roja directa (`match.redCardDirectShort`). */
  readonly redCardDirect?: string | null;
  /** Clase de la roja por doble amarilla (`match.redCardDoubleShort`). */
  readonly redCardDouble?: string | null;
}

const SUMMARY_ARROW = ' → ';

/** Clase declarada de la roja; el servidor aplica `direct_red` por defecto. */
function redCardClass(metadata: unknown): 'direct_red' | 'double_yellow_red' {
  if (metadata && typeof metadata === 'object' && !Array.isArray(metadata)) {
    const value = (metadata as Record<string, unknown>).red_card_type;
    if (value === 'double_yellow_red') return 'double_yellow_red';
  }
  return 'direct_red';
}

/**
 * Resumen legible de un evento. Los nombres y los equipos salen de los
 * resolutores recibidos (la operación ya trae la plantilla y los dos equipos),
 * nunca de este módulo. Un nombre o un equipo sin resolver no se inventa: se
 * omite.
 *
 * - Gol: goleador y, si hay asistencia, el asistente.
 * - Autogol: autor y equipo beneficiado, porque `team_id` es el equipo del
 *   autor y no el acreditado (RF-005).
 * - Roja: jugador y clase, para distinguir la directa de la doble amarilla.
 * - Sustitución: quién sale y quién entra.
 * - Resto: el jugador del evento.
 */
export function eventSummary(
  event: SummarizableEvent,
  resolveName: (playerId: string) => string | null,
  labels: EventSummaryLabels = {},
  resolveTeam?: (teamId: string) => string | null,
): string {
  const name = (value: unknown): string | null => {
    const playerId = text(value);
    if (!playerId) return null;
    const resolved = resolveName(playerId);
    return typeof resolved === 'string' ? text(resolved) : null;
  };
  const team = (value: unknown): string | null => {
    const teamId = text(value);
    if (!teamId || !resolveTeam) return null;
    const resolved = resolveTeam(teamId);
    return typeof resolved === 'string' ? text(resolved) : null;
  };

  if (event.event_type === 'substitution') {
    const parts = [name(event.player_out_id), name(event.player_in_id)]
      .filter((part): part is string => part !== null);
    return parts.join(SUMMARY_ARROW);
  }

  const scorer = name(event.player_id);
  if (event.event_type === 'goal') {
    const assistant = name(event.assist_player_id);
    if (assistant) {
      const label = text(labels.assist);
      if (scorer) {
        return label ? `${scorer} (${label} ${assistant})` : `${scorer}${SUMMARY_ARROW}${assistant}`;
      }
      return assistant;
    }
  }

  if (event.event_type === 'own_goal') {
    // El autor concede en su propio equipo; el equipo acreditado es el otro.
    const beneficiary = team(event.beneficiary_team_id);
    if (scorer && beneficiary) {
      const label = text(labels.ownGoal);
      return `${scorer} (${label ? `${label} ${beneficiary}` : beneficiary})`;
    }
    return scorer ?? beneficiary ?? '';
  }

  if (event.event_type === 'red_card') {
    const isDouble = redCardClass(event.metadata) === 'double_yellow_red';
    const label = text(isDouble ? labels.redCardDouble : labels.redCardDirect);
    if (scorer && label) return `${scorer} (${label})`;
    return scorer ?? label ?? '';
  }

  return scorer ?? '';
}
