import { expect, test, type Page } from '@playwright/test';
import { demoApiBase } from './demo.ts';
import { auditTheme, waitThemeHydration } from './themeChecks.ts';

// Spec 043 T8: metadatos del SSR, sitemap, robots y «Compartir» contra la pila con datos demo.
// Solo lee la API pública; nunca escribe ni usa la sesión del Workspace.

interface PublicMatch { id: string; status: string; home_team_name: string | null; away_team_name: string | null; home_score: number | null; away_score: number | null }
interface Scenario { tournamentId: string; tournamentName: string; finished: PublicMatch; scheduled: PublicMatch }

const API = demoApiBase();
let scenario: Scenario;

async function json<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`${path} respondió ${response.status}: ¿se ejecutó scripts.seed_demo?`);
  return await response.json() as T;
}

test.beforeAll(async () => {
  const tournaments = await json<{ id: string; name: string }[]>('/tournaments/public');
  for (const tournament of tournaments) {
    const matches = await json<PublicMatch[]>(`/tournaments/public/${tournament.id}/matches`);
    const finished = matches.find(match => match.status === 'finished' && match.home_team_name && match.away_team_name && match.home_score !== null);
    const scheduled = matches.find(match => match.status === 'scheduled');
    if (finished && scheduled) {
      scenario = { tournamentId: tournament.id, tournamentName: tournament.name, finished, scheduled };
      return;
    }
  }
  throw new Error('No hay un torneo público demo con un partido finalizado y otro programado');
});

test.use({ storageState: { cookies: [], origins: [] }, reducedMotion: 'reduce', trace: 'off', video: 'off' });

function head(html: string) {
  const attr = (pattern: RegExp) => html.match(pattern)?.[1] ?? null;
  return {
    title: attr(/<title>([^<]*)<\/title>/),
    ogTitle: attr(/<meta property="og:title" content="([^"]*)"/),
    ogUrl: attr(/<meta property="og:url" content="([^"]*)"/),
    ogImage: attr(/<meta property="og:image" content="([^"]*)"/),
    twitterCard: attr(/<meta name="twitter:card" content="([^"]*)"/),
    canonical: attr(/<link rel="canonical" href="([^"]*)"/),
    robots: attr(/<meta name="robots" content="([^"]*)"/),
  };
}

const tournamentPath = () => `/tournaments/${scenario.tournamentId}`;
const resultPath = () => `${tournamentPath()}?match=${scenario.finished.id}`;
const resultTitle = () => `${scenario.finished.home_team_name} ${scenario.finished.home_score}–${scenario.finished.away_score} ${scenario.finished.away_team_name} · ${scenario.tournamentName}`;

test.describe('HTML del servidor sin JavaScript', () => {
  test('inicio, torneo y resultado traen metadatos absolutos del origen configurado, no del Host', async ({ request, baseURL }) => {
    const origin = baseURL!.replace(/\/+$/, '');
    const get = async (path: string) => {
      const response = await request.get(path, { headers: { 'x-forwarded-host': 'evil.example', forwarded: 'host=evil.example;proto=https', cookie: 'bc_locale=es' } });
      expect(response.status(), path).toBe(200);
      const html = await response.text();
      expect(html, path).not.toContain('evil.example');
      return head(html);
    };

    const home = await get('/');
    expect(home.canonical).toBe(`${origin}/`);
    expect(home.ogUrl).toBe(`${origin}/`);
    expect(home.ogImage).toMatch(/\/tournaments\/public\/share-image\?lang=es$/);
    expect(home.twitterCard).toBe('summary_large_image');

    const tournament = await get(tournamentPath());
    expect(tournament.title).toBe(`${scenario.tournamentName} | Bracket Craft`);
    expect(tournament.canonical).toBe(`${origin}${tournamentPath()}`);
    expect(tournament.ogImage).toMatch(new RegExp(`/tournaments/public/${scenario.tournamentId}/share-image\\?lang=es$`));
    expect(tournament.robots).toBeNull();

    const result = await get(resultPath());
    expect(result.ogTitle).toBe(resultTitle());
    expect(result.canonical).toBe(`${origin}${resultPath()}`);
    expect(result.ogImage).toMatch(new RegExp(`/matches/${scenario.finished.id}/share-image\\?lang=es$`));

    for (const invalid of [`${tournamentPath()}?match=${scenario.scheduled.id}`, `${tournamentPath()}?match=00000000-0000-4000-8000-000000000043`, `${tournamentPath()}?match=nope`]) {
      const fallback = await get(invalid);
      expect(fallback.canonical, invalid).toBe(tournament.canonical);
      expect(fallback.ogImage, invalid).toBe(tournament.ogImage);
    }

    for (const image of [home.ogImage!, tournament.ogImage!, result.ogImage!]) {
      const response = await request.get(image);
      expect(response.status(), image).toBe(200);
      expect(response.headers()['content-type']).toBe('image/png');
      expect(response.headers()['cache-control']).toBe('public, max-age=600');
      expect(response.headers()['set-cookie']).toBeUndefined();
    }
  });

  test('sitemap lista inicio y torneos públicos sin parámetros ni fichas; robots bloquea lo privado', async ({ request, baseURL }) => {
    const origin = baseURL!.replace(/\/+$/, '');
    const sitemap = await request.get('/sitemap.xml', { headers: { 'x-forwarded-host': 'evil.example', forwarded: 'host=evil.example;proto=https' } });
    expect(sitemap.status()).toBe(200);
    expect(sitemap.headers()['content-type']).toContain('application/xml');
    expect(sitemap.headers()['cache-control']).toBe('public, max-age=600');
    const locs = [...(await sitemap.text()).matchAll(/<loc>([^<]*)<\/loc>/g)].map(match => match[1]!);
    expect(locs[0]).toBe(`${origin}/`);
    expect(locs).toContain(`${origin}${tournamentPath()}`);
    for (const loc of locs) {
      expect(loc.startsWith(`${origin}/`), loc).toBe(true);
      expect(loc, loc).not.toMatch(/[?#]|\/players\//);
    }

    const robots = await request.get('/robots.txt', { headers: { 'x-forwarded-host': 'evil.example', forwarded: 'host=evil.example;proto=https' } });
    expect(robots.status()).toBe(200);
    expect(robots.headers()['content-type']).toContain('text/plain');
    expect(robots.headers()['cache-control']).toBe('public, max-age=600');
    const text = await robots.text();
    for (const path of ['/workspace', '/admin', '/login', '/auth', '/account', '/organization', '/password', '/invitations']) {
      expect(text).toContain(`Disallow: ${path}`);
    }
    expect(text).toContain(`Sitemap: ${origin}/sitemap.xml`);
  });
});

type ShareMode = 'native' | 'cancel' | 'clipboard' | 'manual';

async function setup(page: Page, mode: ShareMode, theme: 'dark' | 'light' = 'dark') {
  const baseURL = test.info().project.use.baseURL ?? 'http://localhost:3000';
  await page.context().addCookies([
    { name: 'bc_locale', value: 'es', url: baseURL },
    { name: 'bc_theme', value: theme, url: baseURL },
  ]);
  if (mode === 'clipboard') await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseURL });
  await page.addInitScript((current: ShareMode) => {
    const shared: unknown[] = [];
    (window as unknown as { __shared: unknown[] }).__shared = shared;
    const share = current === 'native'
      ? async (data: unknown) => { shared.push(data); }
      : current === 'cancel'
        ? async () => { throw new DOMException('cancelled', 'AbortError'); }
        : undefined;
    Object.defineProperty(Navigator.prototype, 'share', { configurable: true, value: share });
    if (current === 'manual') {
      Object.defineProperty(Clipboard.prototype, 'writeText', { configurable: true, value: async () => { throw new DOMException('denied', 'NotAllowedError'); } });
    }
  }, mode);
}

async function openTournament(page: Page, path = tournamentPath()) {
  await page.goto(path);
  await waitThemeHydration(page);
  await expect(page.getByRole('heading', { level: 1, name: scenario.tournamentName })).toBeVisible();
}

async function pressShare(page: Page, name: string) {
  const button = page.getByRole('button', { name, exact: true });
  await button.focus();
  await page.keyboard.press('Enter');
  return button;
}

test.describe('Compartir', () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test('la hoja nativa recibe título y enlace absoluto; cancelarla no anuncia nada', async ({ page, baseURL }) => {
    await setup(page, 'native');
    await openTournament(page);
    await pressShare(page, 'Compartir torneo');
    await expect(page.locator('.share-status').first()).toHaveText('Enlace compartido.');
    expect(await page.evaluate(() => (window as unknown as { __shared: unknown[] }).__shared)).toEqual([
      { title: `${scenario.tournamentName} | Bracket Craft`, url: `${baseURL!.replace(/\/+$/, '')}${tournamentPath()}` },
    ]);

    const cancelled = await page.context().newPage();
    await setup(cancelled, 'cancel');
    await openTournament(cancelled);
    await pressShare(cancelled, 'Compartir torneo');
    await expect(cancelled.getByRole('button', { name: 'Compartir torneo', exact: true })).toBeEnabled();
    await expect(cancelled.locator('.share-status').first()).toHaveText('');
    await expect(cancelled.getByLabel('Enlace para compartir')).toHaveCount(0);
    await cancelled.close();
  });

  test('sin hoja nativa copia el enlace del resultado desde la cronología compartida', async ({ page, baseURL }) => {
    await setup(page, 'clipboard');
    await openTournament(page, resultPath());
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('heading', { level: 2 })).toContainText(String(scenario.finished.home_team_name));
    await pressShare(page, 'Compartir resultado');
    await expect(dialog.locator('.share-status')).toHaveText('Enlace copiado al portapapeles.');
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${baseURL!.replace(/\/+$/, '')}${resultPath()}`);

    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect.poll(() => new URL(page.url()).searchParams.has('match')).toBe(false);
    await expect(page.getByRole('heading', { level: 1, name: scenario.tournamentName })).toBeFocused();
  });

  test('un enlace de partido no compartible abre el torneo sin diálogo', async ({ page }) => {
    await setup(page, 'clipboard');
    await openTournament(page, `${tournamentPath()}?match=${scenario.scheduled.id}`);
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test('si la copia falla ofrece el enlace en un campo de solo lectura enfocado', async ({ page, baseURL }) => {
    await setup(page, 'manual');
    await openTournament(page);
    await pressShare(page, 'Compartir torneo');
    await expect(page.locator('.share-status').first()).toHaveText('No se pudo copiar automáticamente. Copia el enlace del campo.');
    const field = page.getByLabel('Enlace para compartir');
    await expect(field).toBeFocused();
    await expect(field).toHaveValue(`${baseURL!.replace(/\/+$/, '')}${tournamentPath()}`);
    await expect(field).toHaveAttribute('readonly', '');
    expect(await field.evaluate((input: HTMLInputElement) => (input.selectionEnd ?? 0) - (input.selectionStart ?? 0))).toBe(`${baseURL!.replace(/\/+$/, '')}${tournamentPath()}`.length);
  });
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe sin violaciones a ${width} px en tema ${theme}: compartir, copia manual y cronología`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await setup(page, 'manual', theme);
    await openTournament(page);
    await pressShare(page, 'Compartir torneo');
    await expect(page.getByLabel('Enlace para compartir')).toBeFocused();
    await auditTheme(page, info, `share-tournament-${width}-${theme}`);

    await openTournament(page, resultPath());
    await expect(page.getByRole('dialog')).toBeVisible();
    await pressShare(page, 'Compartir resultado');
    await expect(page.getByRole('dialog').getByLabel('Enlace para compartir')).toBeFocused();
    await auditTheme(page, info, `share-result-${width}-${theme}`);
  });
}
