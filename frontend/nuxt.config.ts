import { securityHeaders } from './app/utils/securityHeaders';

export default defineNuxtConfig({
  routeRules: {
    '/**': { headers: securityHeaders(process.env.NODE_ENV === 'production') },
  },
  compatibilityDate: '2025-07-15',
  devtools: { enabled: process.env.NODE_ENV !== 'production' },
  app: {
    head: {
      htmlAttrs: { lang: 'es' },
    },
  },
  modules: ['@pinia/nuxt', '@nuxt/eslint'],
  css: ['~/assets/css/main.css'],
  runtimeConfig: {
    apiInternalBase: process.env.NUXT_API_INTERNAL_BASE || process.env.API_INTERNAL_BASE || 'http://localhost:8000/api/v1',
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000/api/v1',
      socketBase: process.env.NUXT_PUBLIC_SOCKET_BASE || 'http://localhost:8000',
      apiTimeoutMs: Number(process.env.NUXT_PUBLIC_API_TIMEOUT_MS || 15000),
      csrfCookieName: process.env.NUXT_PUBLIC_CSRF_COOKIE_NAME || 'bc_csrf_token',
      csrfHeaderName: process.env.NUXT_PUBLIC_CSRF_HEADER_NAME || 'X-CSRF-Token',
      csrfResponseHeaderName: process.env.NUXT_PUBLIC_CSRF_RESPONSE_HEADER_NAME || 'X-CSRF-Token',
    },
  },
});
