export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',
  devtools: { enabled: process.env.NODE_ENV !== 'production' },
  app: {
    head: {
      htmlAttrs: { lang: 'es' },
      meta: [{ name: 'theme-color', content: '#0c0f0c' }],
    },
  },
  modules: ['@pinia/nuxt'],
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
