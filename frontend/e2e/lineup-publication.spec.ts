import { expect, test, type Page, type Route } from '@playwright/test';
import { formationSlots } from '../app/constants/formations.ts';
import { assertTheme, auditTheme, chooseTheme } from './themeChecks.ts';

// Spec 045: guardar una planilla que retira una formación publicada pide antes
// una confirmación que nombra al equipo afectado. Contratos ficticios, sin
// escribir en la API.

const uuid = (value: number) => `04500000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const now = '2026-11-24T12:00:00Z';
const SLOTS = formationSlots('2-2');

test.use({ actionTimeout: 15_000, reducedMotion: 'reduce', trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

class PublishedFixture {
  readonly org = uuid(10); readonly matchId = uuid(30); readonly home = uuid(50); readonly away = uuid(51); readonly segment = uuid(60);
  readonly saves: Record<string, unknown>[] = [];
  readonly teams = [
    { id: this.home, label: 'Local', name: 'Local 5v5', offset: 700 },
    { id: this.away, label: 'Visita', name: 'Visitante 5v5', offset: 720 },
  ];

  private players() {
    return this.teams.flatMap((team) => Array.from({ length: 6 }, (_, index) => ({
      team, index, roster: uuid(team.offset + index), player: uuid(team.offset + 100 + index),
      starter: index < SLOTS.length, slot: SLOTS[index] ?? null,
    })));
  }

  private operation() {
    const players = this.players();
    return {
      match: { id: this.matchId, tournament_id: uuid(40), tournament_name: 'Torneo 045', tournament_version_id: uuid(41), stage_id: uuid(42), stage_name: 'Fase 045', group_id: null, group_name: null, matchday: 1, match_date: now, status: 'live', result_confirmed: false, version_status: 'published', home_team_id: this.home, home_team_name: 'Local 5v5', home_team_short_code: 'LOC', home_team_crest_url: null, home_team_logo_url: null, away_team_id: this.away, away_team_name: 'Visitante 5v5', away_team_short_code: 'VIS', away_team_crest_url: null, away_team_logo_url: null, home_score_regular: null, away_score_regular: null, home_score: null, away_score: null, home_penalties: null, away_penalties: null, winner_team_id: null, resolution_type: null, rules_config: { game_format: '5v5' } },
      segments: [{ id: this.segment, segment_number: 1, minute_start: 0, minute_end: null, status: 'active' }], interruptions: [], officials: [], eligible_officials: [], events: [], next_segment: null,
      rosters: players.map((entry) => ({ roster_id: entry.roster, player_id: entry.player, team_id: entry.team.id, team_name: entry.team.name, first_name: entry.team.label, last_name: String(entry.index + 1), dorsal_number: entry.index + 1, is_active: true, match_roster_id: null, role: null, entered_minute: null, left_minute: null, is_valid: true })),
      lineup: players.map((entry) => ({ team_id: entry.team.id, roster_id: entry.roster, player_id: entry.player, role: entry.starter ? 'starter' : 'substitute', position_slot: entry.starter ? entry.slot : null, entered_minute: null, left_minute: null })),
      tactical_lineups: players.map((entry) => ({ segment_id: this.segment, segment_number: 1, team_id: entry.team.id, formation_code: '2-2', is_public: true, published_at: now, player_id: entry.player, is_starter: entry.starter, position_slot: entry.starter ? entry.slot : null, first_name: entry.team.label, last_name: String(entry.index + 1) })),
    };
  }

  async handle(route: Route) {
    const request = route.request(); const path = new URL(request.url()).pathname.replace('/api/v1', ''); const method = request.method();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' } });
    if (method === 'OPTIONS') return reply({});
    const summary = { id: this.org, name: 'Organización 045', slug: 'org-045', organization_user_id: uuid(80) };
    if (path === '/auth/csrf') return reply({ csrf_token: 'publication-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') return reply({ organization_id: this.org, organization_user_id: uuid(80), user_id: uuid(1), role_code: 'administrator', permissions: ['CLOSE_MATCH_REPORT'] });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/tournaments') return reply([]);
    if (path === `/tournaments/${uuid(40)}`) return reply({ id: uuid(40), name: 'Torneo 045' });
    if (path === `/matches/${this.matchId}/operation`) return reply(this.operation());
    if (path.endsWith('/lineup') && method === 'PUT') { this.saves.push(request.postDataJSON() as Record<string, unknown>); return reply({}); }
    if (path === '/competitive-impacts' || path === '/rectifications') return reply({ items: [], total: 0, limit: 25, offset: 0 });
    return reply([]);
  }
}

async function openOperation(page: Page, fixture: PublishedFixture) {
  await page.context().addCookies([{ name: 'bc_user_id', value: uuid(1), url: 'http://localhost:3000' }, { name: 'bc_organization_id', value: fixture.org, url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', (route) => fixture.handle(route));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async (target) => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(target);
  }, `/workspace/matches/${fixture.matchId}`);
  await expect(page.locator('.formation-config')).toHaveCount(2);
  await expect(page.getByLabel('Posición Local 2', { exact: true })).toHaveValue(SLOTS[1]!);
}

async function swapHomePositions(page: Page) {
  await page.getByLabel('Posición Local 2', { exact: true }).selectOption(SLOTS[2]!);
  await page.getByLabel('Posición Local 3', { exact: true }).selectOption(SLOTS[1]!);
}

const saveButton = (page: Page) => page.locator('#seccion-planilla').getByRole('button', { name: 'Guardar planilla', exact: true });

test('saving without changes keeps the publications and asks nothing', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new PublishedFixture(); await openOperation(page, fixture);
  await saveButton(page).focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => fixture.saves.length).toBe(1);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('withdrawing the home formation asks first, names only that team and sends nothing on cancel', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new PublishedFixture(); await openOperation(page, fixture);
  await swapHomePositions(page);

  const save = saveButton(page);
  await save.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Retirar formaciones publicadas' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAccessibleDescription('Este cambio retira la formación publicada de Local 5v5: dejará de ser pública y habrá que volver a publicarla.');
  await expect(dialog.getByRole('button', { name: 'Cancelar', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(dialog).not.toBeVisible();
  await expect(save).toBeFocused();
  expect(fixture.saves).toEqual([]);
  await expect(page.getByLabel('Posición Local 2', { exact: true })).toHaveValue(SLOTS[2]!);

  await page.keyboard.press('Enter');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  expect(fixture.saves).toEqual([]);

  await page.keyboard.press('Enter');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Guardar y retirar', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect.poll(() => fixture.saves.length).toBe(1);
  const body = fixture.saves[0] as { team_lineups: unknown };
  expect(body.team_lineups).toEqual([{ team_id: fixture.home, formation_code: '2-2' }, { team_id: fixture.away, formation_code: '2-2' }]);
});

test('switching to the classic planilla names both teams', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new PublishedFixture(); await openOperation(page, fixture);
  for (const index of [0, 1]) await page.locator('.formation-config').nth(index).getByRole('combobox', { name: 'Formación táctica', exact: true }).selectOption('');
  await saveButton(page).click();
  const dialog = page.getByRole('dialog', { name: 'Retirar formaciones publicadas' });
  await expect(dialog).toHaveAccessibleDescription(/de Local 5v5, Visitante 5v5:/);
  await dialog.getByRole('button', { name: 'Guardar y retirar', exact: true }).click();
  await expect.poll(() => fixture.saves.length).toBe(1);
  expect((fixture.saves[0] as { team_lineups: unknown }).team_lineups).toEqual([]);
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme with the withdrawal confirmation open`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new PublishedFixture(); await openOperation(page, fixture);
    await chooseTheme(page, theme);
    const toggle = page.locator('.workspace-menu-toggle');
    if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
    await swapHomePositions(page);
    await saveButton(page).click();
    await expect(page.getByRole('dialog', { name: 'Retirar formaciones publicadas' })).toBeVisible();
    await assertTheme(page, theme, theme);
    await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    await auditTheme(page, info, `lineup-withdraw-${theme}-${width}`);
    await page.keyboard.press('Escape');
    expect(fixture.saves).toEqual([]);
  });
}
