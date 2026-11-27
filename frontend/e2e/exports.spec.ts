import { readFile } from 'node:fs/promises';
import { expect, test, type Page, type Route } from '@playwright/test';
import { assertTheme, auditTheme, chooseTheme } from './themeChecks.ts';

// Specs 048 y 050: descargas CSV y PDF del Workspace (página «Exportaciones»
// y acta del partido), con teclado y axe en ambos temas. Contratos ficticios,
// sin escribir en la API.

const uuid = (value: number) => `04800000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const now = '2026-11-25T20:00:00Z';
const BOM = '\uFEFF';
const PDF = '%PDF-1.4\n%fixture\n';

test.use({ actionTimeout: 15_000, reducedMotion: 'reduce', trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

class ExportFixture {
  readonly org = uuid(10); readonly tournament = uuid(40); readonly matchId = uuid(30);
  readonly requests: string[] = [];
  tooLarge = new Set<string>();

  private match() {
    return { id: this.matchId, tournament_id: this.tournament, tournament_name: 'Copa 048', tournament_version_id: uuid(41), stage_id: uuid(42), stage_name: 'Fase 048', group_id: null, group_name: null, matchday: 1, match_date: now, status: 'finished', result_confirmed: true, version_status: 'published', home_team_id: uuid(50), home_team_name: 'Local 048', home_team_short_code: 'LOC', home_team_crest_url: null, home_team_logo_url: null, away_team_id: uuid(51), away_team_name: 'Visita 048', away_team_short_code: 'VIS', away_team_crest_url: null, away_team_logo_url: null, home_score_regular: 2, away_score_regular: 1, home_score: 2, away_score: 1, home_penalties: null, away_penalties: null, winner_team_id: uuid(50), resolution_type: null, rules_config: { game_format: '11v11' } };
  }

  async handle(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const headers = { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' };
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers });
    const csv = (header: string) => route.fulfill({ status: 200, body: `${BOM}${header}\r\n`, contentType: 'text/csv; charset=utf-8', headers });
    const pdf = () => route.fulfill({ status: 200, body: PDF, contentType: 'application/pdf', headers });
    if (method === 'OPTIONS') return reply({});
    const summary = { id: this.org, name: 'Organización 048', slug: 'org-048', organization_user_id: uuid(80) };
    if (path === '/auth/csrf') return reply({ csrf_token: 'export-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') return reply({ organization_id: this.org, organization_user_id: uuid(80), user_id: uuid(81), role_code: 'observer', permissions: [] });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/tournaments') return reply([{ id: this.tournament, name: 'Copa 048' }]);
    if (path === `/tournaments/${this.tournament}/exports/standings/pdf`) { this.requests.push(`standings.pdf?lang=${url.searchParams.get('lang')}`); return pdf(); }
    if (path === `/matches/${this.matchId}/export/pdf`) { this.requests.push(`match-report.pdf?lang=${url.searchParams.get('lang')}`); return pdf(); }
    const exported = path.match(/^\/tournaments\/([^/]+)\/exports\/([a-z-]+)$/);
    if (exported) {
      this.requests.push(`${exported[2]}?lang=${url.searchParams.get('lang')}`);
      if (this.tooLarge.has(exported[2]!)) return reply({ detail: 'EXPORT_TOO_LARGE' }, 422);
      return csv('Posición,Equipo');
    }
    if (path === `/matches/${this.matchId}/export`) { this.requests.push(`match-report?lang=${url.searchParams.get('lang')}`); return csv('Sección,Equipo'); }
    if (path === `/matches/${this.matchId}/operation`) return reply({ match: this.match(), segments: [], interruptions: [], officials: [], eligible_officials: [], events: [], next_segment: null, rosters: [], lineup: [], tactical_lineups: [] });
    if (path === '/notifications') return reply({ items: [], unread_count: 0, total: 0, limit: 1, offset: 0 });
    if (path === '/competitive-impacts' || path === '/rectifications') return reply({ items: [], total: 0, limit: 25, offset: 0 });
    return reply([]);
  }
}

async function open(page: Page, fixture: ExportFixture, target: string) {
  await page.context().addCookies([{ name: 'bc_user_id', value: uuid(81), url: 'http://localhost:3000' }, { name: 'bc_organization_id', value: fixture.org, url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', (route) => fixture.handle(route));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async (path) => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(path);
  }, target);
}

async function openExports(page: Page, fixture: ExportFixture) {
  await open(page, fixture, `/workspace/tournaments/${fixture.tournament}/exports`);
  await expect(page.getByRole('heading', { level: 1, name: 'Exportaciones' })).toBeVisible();
  await expect(page.locator('.export-item')).toHaveCount(5);
  await page.waitForLoadState('networkidle');
}

const exportButton = (page: Page, title: string, label = 'Descargar CSV') => page.locator('.export-item')
  .filter({ has: page.getByRole('heading', { level: 2, name: title, exact: true }) }).getByRole('button', { name: label, exact: true });

test('a member downloads the standings with the keyboard and gets a CSV named after the tournament', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new ExportFixture(); await openExports(page, fixture);
  await expect(page.locator('.workspace-tournament-nav').getByRole('link', { name: 'Exportaciones' })).toHaveAttribute('aria-current', 'page');
  const button = exportButton(page, 'Clasificación');
  await expect(button).toHaveAccessibleName('Descargar CSV');
  await expect(button).toHaveAccessibleDescription('Clasificación');
  const downloading = page.waitForEvent('download');
  await button.focus(); await page.keyboard.press('Enter');
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^standings-copa-048-\d{4}-\d{2}-\d{2}\.csv$/);
  expect(await readFile((await download.path())!, 'utf8')).toBe(`${BOM}Posición,Equipo\r\n`);
  expect(fixture.requests).toEqual(['standings?lang=es']);
  await expect(page.getByRole('status').filter({ hasText: `Descarga lista: ${download.suggestedFilename()}` })).toBeVisible();
  await expect(button).toBeFocused();
});

test('a member downloads the standings PDF with the keyboard and only the standings offer a PDF', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new ExportFixture(); await openExports(page, fixture);
  await expect(page.getByRole('button', { name: 'Descargar PDF', exact: true })).toHaveCount(1);
  const button = exportButton(page, 'Clasificación', 'Descargar PDF');
  await expect(button).toHaveAccessibleDescription('Clasificación');
  const downloading = page.waitForEvent('download');
  await button.focus(); await page.keyboard.press('Enter');
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^standings-copa-048-\d{4}-\d{2}-\d{2}\.pdf$/);
  expect((await readFile((await download.path())!)).subarray(0, 5).toString('latin1')).toBe('%PDF-');
  expect(fixture.requests).toEqual(['standings.pdf?lang=es']);
  await expect(page.getByRole('status').filter({ hasText: `Descarga lista: ${download.suggestedFilename()}` })).toBeVisible();
  await expect(button).toBeFocused();
});

test('the rosters warn about the audit and a too large file shows an error without downloading', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new ExportFixture(); fixture.tooLarge.add('rosters'); await openExports(page, fixture);
  const button = exportButton(page, 'Plantillas');
  await expect(button).toHaveAccessibleDescription('Plantillas Cada descarga de las plantillas queda registrada en la auditoría de la organización.');
  await expect(page.getByText('queda registrada en la auditoría')).toHaveCount(1);
  let downloads = 0; page.on('download', () => { downloads += 1; });
  await button.focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: 'El archivo pasa de 10.000 filas y no se ha generado.' })).toBeVisible();
  expect(fixture.requests).toEqual(['rosters?lang=es']);
  expect(downloads).toBe(0);
  await expect(button).toBeEnabled();
  await expect(button).toBeFocused();
});

test('a closed match offers the report download from the operation page', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new ExportFixture(); await open(page, fixture, `/workspace/matches/${fixture.matchId}`);
  const button = page.getByRole('button', { name: 'Descargar acta (CSV)' });
  await expect(button).toBeVisible();
  const downloading = page.waitForEvent('download');
  await button.focus(); await page.keyboard.press('Enter');
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^match-report-local-048-vs-visita-048-\d{4}-\d{2}-\d{2}\.csv$/);
  expect(fixture.requests).toEqual(['match-report?lang=es']);
  await expect(page.getByRole('status').filter({ hasText: 'Descarga lista' })).toBeVisible();
  await expect(button).toBeFocused();
});

test('a closed match offers the report as PDF too', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new ExportFixture(); await open(page, fixture, `/workspace/matches/${fixture.matchId}`);
  const button = page.getByRole('button', { name: 'Descargar acta (PDF)' });
  await expect(button).toBeVisible();
  const downloading = page.waitForEvent('download');
  await button.focus(); await page.keyboard.press('Enter');
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^match-report-local-048-vs-visita-048-\d{4}-\d{2}-\d{2}\.pdf$/);
  expect((await readFile((await download.path())!)).subarray(0, 5).toString('latin1')).toBe('%PDF-');
  expect(fixture.requests).toEqual(['match-report.pdf?lang=es']);
  await expect(page.getByRole('status').filter({ hasText: 'Descarga lista' })).toBeVisible();
  await expect(button).toBeFocused();
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme on the exports page`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new ExportFixture(); fixture.tooLarge.add('rosters'); await openExports(page, fixture);
    await chooseTheme(page, theme);
    const menu = page.locator('.workspace-menu-toggle');
    if (await menu.isVisible() && await menu.getAttribute('aria-expanded') === 'true') await menu.click();
    await exportButton(page, 'Plantillas').click();
    await expect(page.getByRole('alert')).toBeVisible();
    await assertTheme(page, theme, theme);
    await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    await auditTheme(page, info, `exports-${theme}-${width}`);
  });
}

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme on the report downloads of a closed match`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new ExportFixture(); await open(page, fixture, `/workspace/matches/${fixture.matchId}`);
    await expect(page.getByRole('button', { name: 'Descargar acta (PDF)' })).toBeVisible();
    await page.waitForLoadState('networkidle');
    await chooseTheme(page, theme);
    await assertTheme(page, theme, theme);
    await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    await auditTheme(page, info, `match-report-export-${theme}-${width}`);
  });
}
