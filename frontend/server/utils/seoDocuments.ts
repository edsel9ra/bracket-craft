/**
 * Documentos para buscadores (spec 043 RF-009, RF-010, RF-012). Funciones puras:
 * las URL salen del origen público configurado, nunca de la cabecera Host.
 */

export const SEO_CACHE_CONTROL = 'public, max-age=600';
export const SITEMAP_PAGE_SIZE = 200;
export const SITEMAP_MAX_PAGES = 50;

export const PRIVATE_PATHS: readonly string[] = [
  '/workspace',
  '/admin',
  '/login',
  '/auth',
  '/account',
  '/organization',
  '/password',
  '/invitations',
  '/forbidden',
];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface SitemapTournament {
  id: string;
}

export type PublicTournamentPage = (limit: number, offset: number) => Promise<SitemapTournament[]>;

function origin(siteUrl: string): string {
  return siteUrl.replace(/\/+$/, '');
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/** Sin `<lastmod>`: la consulta pública no expone fecha de modificación (RF-013). */
export function buildSitemap(siteUrl: string, tournaments: readonly SitemapTournament[]): string {
  const base = origin(siteUrl);
  const ids = [...new Set(tournaments.map((tournament) => tournament.id).filter((id) => UUID_PATTERN.test(id)))];
  const urls = [`${base}/`, ...ids.map((id) => `${base}/tournaments/${id}`)];
  const entries = urls.map((url) => `  <url><loc>${escapeXml(url)}</loc></url>`).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${entries}\n</urlset>\n`;
}

export function buildRobots(siteUrl: string): string {
  const disallow = PRIVATE_PATHS.map((path) => `Disallow: ${path}`);
  return ['User-agent: *', 'Allow: /', ...disallow, '', `Sitemap: ${origin(siteUrl)}/sitemap.xml`, ''].join('\n');
}

export async function collectPublicTournaments(fetchPage: PublicTournamentPage): Promise<SitemapTournament[]> {
  const tournaments: SitemapTournament[] = [];
  for (let page = 0; page < SITEMAP_MAX_PAGES; page += 1) {
    const rows = await fetchPage(SITEMAP_PAGE_SIZE, page * SITEMAP_PAGE_SIZE);
    tournaments.push(...rows);
    if (rows.length < SITEMAP_PAGE_SIZE) break;
  }
  return tournaments;
}
