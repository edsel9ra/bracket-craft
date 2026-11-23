/**
 * Metadatos públicos para compartir y buscadores (spec 043). Funciones puras:
 * toda URL absoluta sale del origen configurado, nunca de la cabecera Host.
 */

export type SeoLocale = 'es' | 'en';

export interface SeoContext {
  siteUrl: string;
  apiBase: string;
  locale: SeoLocale;
}

export interface SeoTexts {
  title: string;
  description: string;
  imageAlt: string;
}

export type SeoMeta =
  | { name: string; property?: never; content: string }
  | { property: string; name?: never; content: string };

export interface SeoHead {
  title: string;
  meta: SeoMeta[];
  link: { rel: 'canonical'; href: string }[];
}

export interface ShareableResultFields {
  status: string;
  home_team_id: string | null;
  away_team_id: string | null;
  home_team_name?: string | null;
  away_team_name?: string | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties?: number | null;
  away_penalties?: number | null;
}

const SITE_NAME = 'Bracket Craft';
const OG_LOCALES: Record<SeoLocale, string> = { es: 'es_ES', en: 'en_US' };
const SHAREABLE_STATUSES = new Set(['finished', 'administrative_resolution']);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PUBLIC_API = '/tournaments/public';

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

export function absoluteUrl(siteUrl: string, path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${trimTrailingSlash(siteUrl)}${suffix}`;
}

/** RF-012: una base de API relativa se resuelve contra el origen público. */
export function apiAssetUrl(siteUrl: string, apiBase: string, path: string): string {
  const base = trimTrailingSlash(new URL(apiBase, `${trimTrailingSlash(siteUrl)}/`).toString());
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}

function shareImage(ctx: SeoContext, path: string): string {
  return apiAssetUrl(ctx.siteUrl, ctx.apiBase, `${PUBLIC_API}${path}/share-image?lang=${ctx.locale}`);
}

function pageHead(
  ctx: SeoContext,
  texts: SeoTexts,
  canonicalPath: string,
  image: string,
  robots?: string,
): SeoHead {
  const url = absoluteUrl(ctx.siteUrl, canonicalPath);
  const meta: SeoMeta[] = [
    { name: 'description', content: texts.description },
    { property: 'og:type', content: 'website' },
    { property: 'og:site_name', content: SITE_NAME },
    { property: 'og:locale', content: OG_LOCALES[ctx.locale] },
    { property: 'og:title', content: texts.title },
    { property: 'og:description', content: texts.description },
    { property: 'og:url', content: url },
    { property: 'og:image', content: image },
    { property: 'og:image:width', content: '1200' },
    { property: 'og:image:height', content: '630' },
    { property: 'og:image:alt', content: texts.imageAlt },
    { name: 'twitter:card', content: 'summary_large_image' },
    { name: 'twitter:title', content: texts.title },
    { name: 'twitter:description', content: texts.description },
    { name: 'twitter:image', content: image },
    { name: 'twitter:image:alt', content: texts.imageAlt },
  ];
  if (robots) meta.push({ name: 'robots', content: robots });
  return { title: texts.title, meta, link: [{ rel: 'canonical', href: url }] };
}

export function homeHead(ctx: SeoContext, texts: SeoTexts): SeoHead {
  return pageHead(ctx, texts, '/', shareImage(ctx, ''));
}

export function tournamentHead(ctx: SeoContext, tournamentId: string, texts: SeoTexts): SeoHead {
  return pageHead(ctx, texts, `/tournaments/${tournamentId}`, shareImage(ctx, `/${tournamentId}`));
}

export function resultHead(ctx: SeoContext, tournamentId: string, matchId: string, texts: SeoTexts): SeoHead {
  return pageHead(
    ctx,
    texts,
    `/tournaments/${tournamentId}?match=${matchId}`,
    shareImage(ctx, `/${tournamentId}/matches/${matchId}`),
  );
}

/** RF-008: imagen de marca, nunca la foto, y sin indexar. */
export function playerHead(ctx: SeoContext, playerId: string, texts: SeoTexts): SeoHead {
  return pageHead(ctx, texts, `/players/${playerId}`, shareImage(ctx, ''), 'noindex, nofollow');
}

/** Espejo de `share_policy.is_shareable_result` del backend. */
export function isShareableResult(match: ShareableResultFields | null | undefined): boolean {
  if (!match || !SHAREABLE_STATUSES.has(match.status)) return false;
  return [match.home_team_id, match.away_team_id, match.home_score, match.away_score]
    .every((value) => value !== null && value !== undefined);
}

export function resultTitle(match: ShareableResultFields, tournamentName: string): string {
  const penalties = match.home_penalties != null && match.away_penalties != null
    ? ` (${match.home_penalties}–${match.away_penalties})`
    : '';
  return `${match.home_team_name ?? ''} ${match.home_score}–${match.away_score} ${match.away_team_name ?? ''}${penalties} · ${tournamentName}`;
}

export function parseMatchQuery(value: unknown): string | null {
  return typeof value === 'string' && UUID_PATTERN.test(value) ? value : null;
}

export function seoContext(siteUrl: string, apiBase: string, locale: unknown): SeoContext {
  return { siteUrl, apiBase, locale: locale === 'en' ? 'en' : 'es' };
}

/** Cerrar la cronología compartida quita `match` y conserva fase y grupo. */
export function withoutMatchQuery<T extends Record<string, unknown>>(query: T): Omit<T, 'match'> {
  const rest: Record<string, unknown> = { ...query };
  delete rest.match;
  return rest as Omit<T, 'match'>;
}
