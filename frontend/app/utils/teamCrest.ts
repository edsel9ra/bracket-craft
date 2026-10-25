/**
 * Reglas puras del escudo de equipo (spec 014, T14).
 *
 * Sin DOM, sin reloj y sin red: reciben datos y devuelven un valor. La
 * precedencia `escudo > logo_url > iniciales` depende de la superficie (el
 * `logo_url` heredado solo se muestra en el Workspace) y el sustituto de
 * iniciales sigue la regla fija de RF-17.
 */
export type CrestSurface = 'workspace' | 'public';
export type CrestSource = 'crest' | 'logo' | 'initials';

export interface CrestSourceInput {
  readonly crestUrl?: string | null;
  readonly logoUrl?: string | null;
  readonly surface: CrestSurface;
}

/**
 * Catálogo estable de errores del escudo (RF-57): el código que devuelve la API
 * se traduce con esta tabla y un código desconocido deja que el llamador use el
 * mensaje genérico.
 */
export const CREST_ERROR_CODES = {
  CREST_FILE_EMPTY: 'crest.error.empty',
  CREST_FORMAT_UNSUPPORTED: 'crest.error.format',
  CREST_ANIMATION_UNSUPPORTED: 'crest.error.animation',
  CREST_TOO_LARGE: 'crest.error.tooLarge',
  CREST_NOT_FOUND: 'crest.error.notFound',
  CREST_FORBIDDEN: 'crest.error.forbidden',
  CREST_STORAGE_UNAVAILABLE: 'crest.error.storage',
  CREST_UPLOAD_FAILED: 'crest.error.failed',
} as const;

function asCharacters(value: unknown): string[] {
  return typeof value === 'string' ? Array.from(value.trim()) : [];
}

/**
 * Iniciales del sustituto (RF-17): los dos primeros caracteres del código
 * corto en mayúsculas; si el código tiene menos de dos, los del nombre; un
 * nombre de un carácter se conserva. Nunca lanza y devuelve una cadena vacía
 * solo si nombre y código están vacíos.
 */
export function teamInitials(name: unknown, shortCode?: unknown): string {
  const code = asCharacters(shortCode);
  const label = asCharacters(name);
  const source = code.length >= 2 ? code : label.length > 0 ? label : code;
  return source.slice(0, 2).join('').toUpperCase();
}

/**
 * Qué imagen mostrar (RF-4): el escudo siempre; el `logo_url` heredado solo en
 * el Workspace mientras no haya escudo; en público nunca el `logo_url`; sin
 * imagen, el sustituto de iniciales.
 */
export function crestSource(input: CrestSourceInput): CrestSource {
  if (input.crestUrl) {
    return 'crest';
  }
  if (input.surface === 'workspace' && input.logoUrl) {
    return 'logo';
  }
  return 'initials';
}

export interface CrestRow {
  readonly team_id: string;
  readonly crest_url?: string | null;
  readonly logo_url?: string | null;
}

/**
 * Aplica la respuesta del escudo a la fila del equipo (RF-19): devuelve una
 * fila nueva con `crest_url` y `logo_url` actualizados, o `null` si la
 * respuesta pertenece a otro equipo (la fila no se toca).
 */
export function applyCrestResponse<T extends CrestRow>(
  team: T,
  response: CrestRow,
): (T & { crest_url: string | null; logo_url: string | null }) | null {
  if (team.team_id !== response.team_id) {
    return null;
  }
  return {
    ...team,
    crest_url: response.crest_url ?? null,
    logo_url: response.logo_url ?? null,
  };
}

/** Clave de la acción principal del panel: cargar o reemplazar (RF-55). */
export function crestActionKey(hasCrest: boolean): 'crest.load' | 'crest.replace' {
  return hasCrest ? 'crest.replace' : 'crest.load';
}

/** Clave i18n del código de error, o `null` si es desconocido o falta. */
export function crestErrorMessageKey(code: unknown): string | null {
  if (typeof code !== 'string') {
    return null;
  }
  return (CREST_ERROR_CODES as Record<string, string>)[code] ?? null;
}
