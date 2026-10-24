export interface ApiFailureShape {
  status?: number;
  statusCode?: number;
  data?: unknown;
  name?: string;
  message?: string;
}

export function getApiStatus(cause: unknown): number {
  const failure = cause as ApiFailureShape;
  return failure.status || failure.statusCode || 0;
}

export function isUnauthorized(cause: unknown): boolean {
  return getApiStatus(cause) === 401;
}

export function isForbidden(cause: unknown): boolean {
  return getApiStatus(cause) === 403;
}

export function isNotFound(cause: unknown): boolean {
  return getApiStatus(cause) === 404;
}

/**
 * Código aditivo del cuerpo del error (`data.code`), o `null` si no lo lleva.
 *
 * Los 409 de la spec 012 distinguen su causa por este campo; un cliente que
 * solo lee `detail` sigue funcionando porque el código nunca sustituye al
 * detalle. Un cuerpo que no sea un objeto o un `code` que no sea una cadena no
 * se interpretan.
 */
export function getApiCode(cause: unknown): string | null {
  const failure = cause as ApiFailureShape | null | undefined;
  const data = failure?.data;
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const code = (data as { code?: unknown }).code;
  return typeof code === 'string' && code.trim() ? code : null;
}
