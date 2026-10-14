import { normalizeOrganizationId, isSafeCsrfToken } from '~/utils/validation';

const SAFE_RETRY_STATUS_CODES = [408, 425, 429, ...Array.from({ length: 100 }, (_, index) => 500 + index)];
const CSRF_COOKIE_FALLBACKS = ['bc_csrf_token', 'csrf_token', 'XSRF-TOKEN'];

function readCookieValue(cookieHeader: string | undefined, name: string): string | null {
  if (!cookieHeader) return null;
  const encodedName = `${name}=`;
  const rawValue = cookieHeader.split(';').map((part) => part.trim()).find((part) => part.startsWith(encodedName));
  if (!rawValue) return null;
  try {
    const value = decodeURIComponent(rawValue.slice(encodedName.length));
    return isSafeCsrfToken(value) ? value : null;
  } catch {
    return null;
  }
}

export function useApi() {
  const config = useRuntimeConfig();
  const cookieOptions = { sameSite: 'lax' as const, secure: !import.meta.dev, maxAge: 60 * 60 * 24 * 30 };
  const organizationId = useCookie<string | null>('bc_organization_id', cookieOptions);
  if (organizationId.value && !normalizeOrganizationId(organizationId.value)) organizationId.value = null;

  const csrfCookieName = String(config.public.csrfCookieName || 'bc_csrf_token');
  const csrfHeaderName = String(config.public.csrfHeaderName || 'X-CSRF-Token');
  const csrfResponseHeaderName = String(config.public.csrfResponseHeaderName || csrfHeaderName);
  const csrfCookie = useCookie<string | null>(csrfCookieName, cookieOptions);
  if (csrfCookie.value && !isSafeCsrfToken(csrfCookie.value)) csrfCookie.value = null;
  let responseCsrfToken: string | null = isSafeCsrfToken(csrfCookie.value) ? csrfCookie.value : null;

  function csrfToken(): string | null {
    if (responseCsrfToken) return responseCsrfToken;
    if (isSafeCsrfToken(csrfCookie.value)) return csrfCookie.value;

    if (import.meta.server) {
      const requestHeaders = useRequestHeaders(['cookie']);
      for (const name of [csrfCookieName, ...CSRF_COOKIE_FALLBACKS]) {
        const value = readCookieValue(requestHeaders.cookie, name);
        if (value) return value;
      }
    } else if (typeof document !== 'undefined') {
      for (const name of [csrfCookieName, ...CSRF_COOKIE_FALLBACKS]) {
        const value = readCookieValue(document.cookie, name);
        if (value) return value;
      }
    }
    return null;
  }

  async function bootstrapCsrf(baseURL: string): Promise<string | null> {
    const forwardedHeaders = new Headers();
    if (import.meta.server) {
      const requestHeaders = useRequestHeaders(['cookie']);
      if (requestHeaders.cookie) forwardedHeaders.set('cookie', requestHeaders.cookie);
    }
    try {
      const result = await $fetch<{ csrf_token?: unknown }>('/auth/csrf', {
        baseURL,
        credentials: 'include',
        headers: forwardedHeaders,
        timeout: Number(config.public.apiTimeoutMs || 15000),
      });
      if (!isSafeCsrfToken(result.csrf_token)) return null;
      responseCsrfToken = result.csrf_token;
      csrfCookie.value = result.csrf_token;
      return result.csrf_token;
    } catch {
      return null;
    }
  }

  function forwardCsrfCookie(headers: Headers, token: string) {
    if (!import.meta.server) return;
    const cookies = (headers.get('cookie') || '')
      .split(';')
      .map((part) => part.trim())
      .filter((part) => part && !part.startsWith(`${csrfCookieName}=`));
    cookies.push(`${csrfCookieName}=${encodeURIComponent(token)}`);
    headers.set('cookie', cookies.join('; '));
  }

  async function request<T>(path: string, options: Parameters<typeof $fetch<T>>[1] = {}) {
    const headers = new Headers(options.headers as HeadersInit | undefined);
    const baseURL = import.meta.server ? (config.apiInternalBase || config.public.apiBase) : config.public.apiBase;
    const validOrganizationId = normalizeOrganizationId(organizationId.value);
    if (validOrganizationId) {
      if (organizationId.value !== validOrganizationId) organizationId.value = validOrganizationId;
      headers.set('X-Organization-ID', validOrganizationId);
    }
    if (import.meta.server) {
      const requestHeaders = useRequestHeaders(['cookie']);
      if (requestHeaders.cookie) headers.set('cookie', requestHeaders.cookie);
    }

    const method = String(options.method || 'GET').toUpperCase();
    const isSafeMethod = method === 'GET' || method === 'HEAD';
    if (!isSafeMethod) {
      const token = csrfToken() || await bootstrapCsrf(baseURL);
      if (token) {
        headers.set(csrfHeaderName, token);
        forwardCsrfCookie(headers, token);
      }
    }

    const requestOptions = {
      ...options,
      baseURL,
      credentials: 'include',
      headers,
      timeout: options.timeout ?? Number(config.public.apiTimeoutMs || 15000),
      retry: isSafeMethod ? (options.retry ?? 2) : 0,
      retryStatusCodes: SAFE_RETRY_STATUS_CODES,
      onResponse: async (context: { response: Response }) => {
        const token = context.response.headers.get(csrfResponseHeaderName);
        if (isSafeCsrfToken(token)) {
          responseCsrfToken = token;
          csrfCookie.value = token;
        }
        if (typeof options.onResponse === 'function') await options.onResponse(context as never);
      },
    } as Parameters<typeof $fetch<T>>[1];

    return await $fetch<T>(path, requestOptions);
  }

  return { request, organizationId };
}
