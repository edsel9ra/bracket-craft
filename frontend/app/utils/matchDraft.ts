/**
 * Borrador local del partido (spec 012, RF-022, RF-034, RNF-011).
 *
 * Guarda **solo** los eventos sin confirmar y los datos del formulario de
 * cierre por usuario, organización y partido. Es una pieza distinta de la
 * resolución prevista, que vive en el almacenamiento de sesión de la pestaña
 * (`utils/matchResolution.ts`): este borrador **nunca** la escribe.
 *
 * Un borrador anterior a la spec 012 podía contener `resolution_type` (en la
 * raíz o dentro de `result`). El saneado lo ignora, no lo devuelve y lo elimina
 * del guardado sin tocar los eventos ni el marcador; una forma inválida del
 * campo tampoco rompe la restauración.
 *
 * Las funciones de saneado son puras: no leen el reloj, el entorno ni la red.
 * El almacenamiento se inyecta en `createMatchDraftStore` (la página le pasa el
 * almacenamiento local del navegador; las pruebas, un doble en memoria).
 */

/** Versión del formato guardado. */
export const MATCH_DRAFT_VERSION = 1;

/** Contexto que identifica el borrador (el mismo que la pantalla de operación). */
export interface MatchDraftScope {
  readonly userId?: string | null;
  readonly organizationId?: string | null;
  readonly matchId?: string | null;
}

/** Parte de `Storage` que el borrador necesita. */
export type MatchDraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** Marcadores del formulario de cierre que el borrador conserva. */
export const MATCH_DRAFT_SCORE_FIELDS = [
  'home_score_regular',
  'away_score_regular',
  'home_score',
  'away_score',
  'home_penalties',
  'away_penalties',
] as const;

export type MatchDraftScoreField = (typeof MATCH_DRAFT_SCORE_FIELDS)[number];

/**
 * Datos del formulario de cierre que se restauran. Todos son opcionales: un
 * campo ausente o inválido conserva el valor por defecto de la pantalla.
 */
export interface MatchDraftResult {
  readonly home_score_regular?: number | null;
  readonly away_score_regular?: number | null;
  readonly home_score?: number | null;
  readonly away_score?: number | null;
  readonly home_penalties?: number | null;
  readonly away_penalties?: number | null;
  readonly winner_team_id?: string;
  readonly reason?: string;
}

/** Contenido saneado del borrador. */
export interface MatchDraft {
  readonly version: number;
  readonly match_id: string;
  readonly events: readonly unknown[];
  readonly result: MatchDraftResult;
  readonly saved_at: string | null;
}

/** Resultado de sanear un valor guardado. */
export interface SanitizedMatchDraft {
  readonly draft: MatchDraft;
  /** `true` si el guardado traía `resolution_type` y se ha descartado. */
  readonly strippedResolution: boolean;
}

/** Campos que la pantalla escribe al guardar. */
export interface MatchDraftInput {
  readonly events: readonly unknown[];
  readonly result: MatchDraftResult;
  readonly saved_at: string | null;
}

function scopePart(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Un identificador con separadores o espacios podría mezclar dos contextos.
  if (/[:\s]/.test(trimmed)) return null;
  return trimmed;
}

/**
 * Clave del borrador: `bc_match_draft:{userId}:{orgId}:{matchId}`. Sin partido
 * no hay clave; los identificadores ausentes conservan `anonymous` como antes
 * de la spec 012 para no perder borradores existentes.
 */
export function matchDraftKey(scope: MatchDraftScope): string | null {
  const matchId = scopePart(scope.matchId);
  if (!matchId) return null;
  const userId = scopePart(scope.userId) ?? 'anonymous';
  const organizationId = scopePart(scope.organizationId) ?? 'anonymous';
  return ['bc_match_draft', userId, organizationId, matchId].join(':');
}

function hasResolutionField(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  return Object.hasOwn(value, 'resolution_type');
}

/**
 * Saneado del formulario de cierre: se copian solo los campos conocidos y
 * válidos. Un campo inválido se omite (la pantalla conserva su default) y
 * `resolution_type` nunca forma parte del resultado.
 */
function sanitizeDraftResult(value: unknown): MatchDraftResult {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const raw = value as Record<string, unknown>;
  const result: Record<string, number | string | null> = {};

  for (const key of MATCH_DRAFT_SCORE_FIELDS) {
    if (!Object.hasOwn(raw, key)) continue;
    const field = raw[key];
    if (field === null || (typeof field === 'number' && Number.isInteger(field) && field >= 0)) {
      result[key] = field;
    }
  }
  if (typeof raw.winner_team_id === 'string') result.winner_team_id = raw.winner_team_id;
  if (typeof raw.reason === 'string' && raw.reason.length <= 1000) result.reason = raw.reason;

  return result as MatchDraftResult;
}

/**
 * Sanea un borrador ya parseado. Devuelve `null` si no es un objeto. Los
 * eventos se conservan tal cual (la pantalla los valida con `readDraftEvent`)
 * y se informa si se descartó la resolución prevista.
 */
export function sanitizeMatchDraft(value: unknown): SanitizedMatchDraft | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;

  return {
    draft: {
      version: MATCH_DRAFT_VERSION,
      match_id: typeof raw.match_id === 'string' ? raw.match_id : '',
      events: Array.isArray(raw.events) ? raw.events : [],
      result: sanitizeDraftResult(raw.result),
      saved_at: typeof raw.saved_at === 'string' ? raw.saved_at : null,
    },
    strippedResolution: hasResolutionField(raw) || hasResolutionField(raw.result),
  };
}

/** Parsea y sanea un guardado; texto ilegible o que no es un objeto → `null`. */
export function parseStoredMatchDraft(raw: string | null | undefined): SanitizedMatchDraft | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  return sanitizeMatchDraft(parsed);
}

/**
 * Serializa el borrador con el formato de siempre. El resultado se re-sanea,
 * así que ninguna ruta de escritura puede añadir `resolution_type` aunque el
 * objeto recibido lo traiga.
 */
export function serializeMatchDraft(draft: MatchDraft): string {
  return JSON.stringify({
    version: MATCH_DRAFT_VERSION,
    match_id: draft.match_id,
    events: Array.isArray(draft.events) ? draft.events : [],
    result: sanitizeDraftResult(draft.result),
    saved_at: typeof draft.saved_at === 'string' ? draft.saved_at : null,
  });
}

/** Resultado de leer el borrador guardado. */
export interface MatchDraftReadResult {
  /** Borrador saneado, o `null` si no hay, está ilegible o es de otro partido. */
  readonly draft: MatchDraft | null;
  /** `true` si lo guardado ya no vale y debe borrarse (JSON ilegible). */
  readonly discard: boolean;
  /**
   * `true` si se descartó `resolution_type`. Cuando se puede, el guardado se
   * reescribe ya limpio conservando eventos, marcador y `saved_at`.
   */
  readonly cleaned: boolean;
}

export interface MatchDraftStore {
  /** Clave efectiva, o `null` sin partido. */
  readonly key: string | null;
  readonly available: boolean;
  read(): MatchDraftReadResult;
  save(draft: MatchDraftInput): boolean;
  clear(): boolean;
}

/**
 * Acceso al borrador de un contexto sobre el almacenamiento recibido. Cualquier
 * fallo del almacenamiento se comporta como «no hay borrador» y nunca rompe la
 * operación.
 */
export function createMatchDraftStore(
  scope: MatchDraftScope,
  storage: MatchDraftStorage | null,
): MatchDraftStore {
  const key = matchDraftKey(scope);
  const available = Boolean(key && storage);

  return {
    key,
    available,
    read(): MatchDraftReadResult {
      if (!key || !storage) return { draft: null, discard: false, cleaned: false };

      let raw: string | null;
      try {
        raw = storage.getItem(key);
      } catch {
        return { draft: null, discard: false, cleaned: false };
      }
      // Sin guardado, o un guardado vacío, no es un error: no hay nada que borrar.
      if (raw === null || !raw.trim()) return { draft: null, discard: false, cleaned: false };

      const parsed = parseStoredMatchDraft(raw);
      if (!parsed) return { draft: null, discard: true, cleaned: false };

      // La clave ya incluye el partido; un `match_id` distinto es corrupción y
      // se ignora igual que antes de la spec 012, sin borrar el guardado.
      if (parsed.draft.match_id && parsed.draft.match_id !== scopePart(scope.matchId)) {
        return { draft: null, discard: false, cleaned: false };
      }

      if (!parsed.strippedResolution) {
        return { draft: parsed.draft, discard: false, cleaned: false };
      }

      try {
        storage.setItem(key, serializeMatchDraft(parsed.draft));
        return { draft: parsed.draft, discard: false, cleaned: true };
      } catch {
        // El campo se sigue ignorando aunque el almacenamiento no deje reescribir.
        return { draft: parsed.draft, discard: false, cleaned: false };
      }
    },
    save(draft: MatchDraftInput): boolean {
      if (!key || !storage) return false;
      const matchId = scopePart(scope.matchId);
      if (!matchId) return false;
      try {
        storage.setItem(key, serializeMatchDraft({
          version: MATCH_DRAFT_VERSION,
          match_id: matchId,
          events: draft.events,
          result: draft.result,
          saved_at: draft.saved_at,
        }));
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
