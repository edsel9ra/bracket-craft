const INTERNAL_ORIGIN = 'https://bracket-craft.invalid';

export function safeInternalRedirect(value: unknown, fallback = '/workspace'): string {
  if (typeof value !== 'string') return fallback;

  const candidate = value.trim();
  if (
    !candidate
    || candidate.length > 2048
    || !candidate.startsWith('/')
    || candidate.startsWith('//')
    || candidate.includes('\\')
    || /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return fallback;
  }

  let decoded = candidate;
  try {
    decoded = decodeURIComponent(candidate);
  } catch {
    return fallback;
  }
  if (decoded.startsWith('//') || decoded.includes('\\') || /[\u0000-\u001f\u007f]/.test(decoded)) {
    return fallback;
  }

  try {
    const parsed = new URL(candidate, INTERNAL_ORIGIN);
    if (parsed.origin !== INTERNAL_ORIGIN) return fallback;
  } catch {
    return fallback;
  }

  return candidate;
}
