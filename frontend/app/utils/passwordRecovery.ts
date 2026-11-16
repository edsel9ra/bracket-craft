/**
 * Utilidades puras de la recuperación y el cambio de contraseña (spec 039).
 *
 * No leen el DOM, el reloj ni el entorno. El token llega en el fragmento de la
 * URL (`/password/reset#<token>`) para que no alcance el SSR, los logs del
 * proxy ni el `Referer`; aquí solo se valida su forma.
 */

/** Misma política que el registro y el backend (RF-009). */
export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;

/** Mismo tope que `ResetPasswordRequest.token`; `token_urlsafe` solo usa base64url. */
const RESET_TOKEN = /^[A-Za-z0-9_-]{1,128}$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Códigos de error del catálogo cerrado; el cliente nunca inventa otros. */
export const PASSWORD_ERROR_CODES = [
  'PASSWORD_RESET_INVALID',
  'PASSWORD_REUSED',
  'CURRENT_PASSWORD_INVALID',
  'PASSWORD_NOT_SET',
  'RATE_LIMITED',
  'UNAVAILABLE',
] as const;

export type PasswordErrorCode = (typeof PASSWORD_ERROR_CODES)[number];

export type ValidationMessage =
  | { key: 'validation.required' }
  | { key: 'validation.email' }
  | { key: 'validation.minLength'; params: { min: number } }
  | { key: 'validation.maxLength'; params: { max: number } }
  | { key: 'password.error.mismatch' };

/** Lee el token del fragmento (`#abc` o `abc`); `null` si falta o no es válido. */
export function resetTokenFromHash(hash: unknown): string | null {
  if (typeof hash !== 'string') return null;
  const value = hash.startsWith('#') ? hash.slice(1) : hash;
  return RESET_TOKEN.test(value) ? value : null;
}

/** URL sin fragmento, para retirarlo del historial en cuanto se lee el token. */
export function urlWithoutFragment(pathname: string, search: string): string {
  return `${pathname}${search}`;
}

export function emailError(value: string): ValidationMessage | null {
  const trimmed = value.trim();
  if (!trimmed) return { key: 'validation.required' };
  return EMAIL.test(trimmed) ? null : { key: 'validation.email' };
}

export function newPasswordError(value: string): ValidationMessage | null {
  if (!value) return { key: 'validation.required' };
  const length = [...value].length;
  if (length < PASSWORD_MIN_LENGTH) return { key: 'validation.minLength', params: { min: PASSWORD_MIN_LENGTH } };
  if (length > PASSWORD_MAX_LENGTH) return { key: 'validation.maxLength', params: { max: PASSWORD_MAX_LENGTH } };
  return null;
}

export function confirmationError(password: string, confirmation: string): ValidationMessage | null {
  if (!confirmation) return { key: 'validation.required' };
  return password === confirmation ? null : { key: 'password.error.mismatch' };
}

interface ApiFailure {
  status?: unknown;
  statusCode?: unknown;
  data?: { detail?: unknown };
}

/** Traduce un fallo de la API a un código del catálogo, o `null` si no tiene uno propio. */
export function passwordErrorCode(cause: unknown): PasswordErrorCode | null {
  const failure = (cause ?? {}) as ApiFailure;
  const status = Number(failure.statusCode ?? failure.status);
  if (status === 429) return 'RATE_LIMITED';
  if (status === 503) return 'UNAVAILABLE';
  const detail = failure.data?.detail;
  if (typeof detail === 'string' && (PASSWORD_ERROR_CODES as readonly string[]).includes(detail)) {
    return detail as PasswordErrorCode;
  }
  return null;
}

export function passwordErrorKey(cause: unknown): string {
  const code = passwordErrorCode(cause);
  return code ? `password.error.${code}` : 'password.error.unknown';
}
