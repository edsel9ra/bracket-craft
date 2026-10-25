/**
 * Utilidades puras del flujo de Google (RF-9, RF-31, RNF-10).
 *
 * No leen el DOM, el reloj ni el entorno: se pueden probar en Node. El destino
 * de retorno aplica el mismo criterio que el backend: solo rutas internas
 * relativas, sin host, sin esquema, sin barras invertidas ni caracteres de
 * control, y como máximo 512 caracteres. Un valor inválido se normaliza a
 * `null` (nunca lanza) y el llamador usa el destino por defecto.
 */

export type GoogleFlow = 'login' | 'link';

/** Códigos de error del catálogo cerrado (RF-31). El éxito no es un error. */
export const GOOGLE_ERROR_CODES = [
  'GOOGLE_UNAVAILABLE',
  'GOOGLE_CANCELLED',
  'GOOGLE_STATE_INVALID',
  'GOOGLE_IDENTITY_INVALID',
  'ACCOUNT_DISABLED',
  'ACCOUNT_EXISTS_PASSWORD',
  'ACCOUNT_EXISTS_GOOGLE_ONLY',
  'GOOGLE_ALREADY_LINKED',
  'LINK_EMAIL_MISMATCH',
  'LINK_IDENTITY_TAKEN',
  'RATE_LIMITED',
  'ORGANIZATION_SLUG_TAKEN',
] as const;

export type GoogleErrorCode = (typeof GOOGLE_ERROR_CODES)[number];

/** Avisos de éxito del catálogo (RF-33). */
export const GOOGLE_NOTICE_CODES = ['GOOGLE_LINK_SUCCESS'] as const;

export type GoogleNoticeCode = (typeof GOOGLE_NOTICE_CODES)[number];

/** Mismo límite que `validate_return_destination` en el backend. */
export const MAX_GOOGLE_REDIRECT_LENGTH = 512;

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/;
const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:/;

function isSafeInternalPath(value: string): boolean {
  if (!value.startsWith('/') || value.startsWith('//')) return false;
  if (value.includes('\\')) return false;
  if (CONTROL_CHARACTERS.test(value)) return false;

  // Un esquema solo es peligroso al inicio del componente de ruta; la consulta
  // puede contener URLs internas sin cambiar el origen.
  const [pathPart = ''] = value.split('?');
  const [path = ''] = pathPart.split('#');
  if (SCHEME.test(path.replace(/^\/+/, ''))) return false;

  return true;
}

/**
 * Devuelve la ruta interna segura o `null`. No recorta, no reescribe y no lanza;
 * además valida una decodificación percentual para que `/%2F%2Fhost` no pase.
 */
export function normalizeGoogleRedirect(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  if (value.length === 0 || value.length > MAX_GOOGLE_REDIRECT_LENGTH) return null;
  if (!isSafeInternalPath(value)) return null;

  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  if (decoded !== value && !isSafeInternalPath(decoded)) return null;

  return value;
}

/** Cuerpo del inicio del flujo; el destino inválido se envía como `null`. */
export function googleStartRequest(
  flow: GoogleFlow,
  redirect: unknown,
): { flow: GoogleFlow; redirect: string | null } {
  return { flow, redirect: normalizeGoogleRedirect(redirect) };
}

/** Clave i18n del error; un código desconocido cae en el mensaje genérico. */
export function googleErrorKey(code: unknown): string {
  return typeof code === 'string'
    && (GOOGLE_ERROR_CODES as readonly string[]).includes(code)
    ? `google.error.${code}`
    : 'google.error.unknown';
}

/** Clave i18n del aviso de éxito, o cadena vacía si no es un aviso admitido. */
export function googleNoticeKey(code: unknown): string {
  return typeof code === 'string'
    && (GOOGLE_NOTICE_CODES as readonly string[]).includes(code)
    ? `google.notice.${code}`
    : '';
}

/** Destino del puente de retorno: ruta interna validada o el destino por defecto. */
export function googleCallbackDestination(
  next: unknown,
  fallback = '/workspace',
): string {
  return normalizeGoogleRedirect(next) ?? fallback;
}

export interface GoogleLinkViewState {
  readonly enabled: boolean;
  readonly loading: boolean;
  readonly linked: boolean;
  readonly error: boolean;
}

/**
 * Decide si la pantalla de vinculación ofrece el botón: nunca con la identidad
 * ya vinculada (RF-14), con Google deshabilitado (RF-33), mientras carga o si
 * la consulta de estado falló.
 */
export function googleLinkActionVisible(state: GoogleLinkViewState): boolean {
  return state.enabled && !state.loading && !state.linked && !state.error;
}
