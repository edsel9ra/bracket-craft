const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function normalizeUuid(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const candidate = value.trim();
  return UUID_PATTERN.test(candidate) ? candidate : null;
}

export function normalizeOrganizationId(value: unknown): string | null {
  return normalizeUuid(value);
}

export function normalizeLocale(value: unknown): 'es' | 'en' {
  return value === 'en' ? 'en' : 'es';
}

export function isSafeCsrfToken(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= 512 && !/[\u0000-\u001f\u007f]/.test(value);
}
