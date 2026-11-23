import { SEO_CACHE_CONTROL, buildSitemap, collectPublicTournaments, type SitemapTournament } from '../utils/seoDocuments';

// Excepción §3.3 aprobada en la spec 043: `useApi` no existe en rutas Nitro. Lectura
// anónima de torneos públicos, sin cookies, organización ni CSRF.
export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event);
  const apiBase = config.apiInternalBase || config.public.apiBase;
  try {
    const tournaments = await collectPublicTournaments((limit, offset) =>
      $fetch<SitemapTournament[]>('/tournaments/public', {
        baseURL: apiBase,
        query: { limit, offset },
        credentials: 'omit',
        timeout: Number(config.public.apiTimeoutMs) || 15000,
      }),
    );
    setResponseHeaders(event, { 'Content-Type': 'application/xml; charset=utf-8', 'Cache-Control': SEO_CACHE_CONTROL });
    return buildSitemap(config.public.siteUrl, tournaments);
  } catch {
    setResponseHeader(event, 'Cache-Control', 'no-store');
    throw createError({ statusCode: 503, statusMessage: 'Sitemap unavailable' });
  }
});
