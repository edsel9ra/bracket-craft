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
