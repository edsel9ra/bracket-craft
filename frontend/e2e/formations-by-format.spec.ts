import { expect, test, type Page, type Route } from '@playwright/test';
import { formationSlots, type FormationCode } from '../app/constants/formations.ts';
import { openPublicContract } from './publicPolishChecks.ts';
import { installPublicContract, leagueId, uuid as publicUuid } from './publicPolishFixtures.ts';
import { assertTheme, auditTheme, chooseTheme } from './themeChecks.ts';
import type { PublicMatch } from '../app/utils/publicTournament.ts';

// Spec 044 (F12): selector por modalidad en la operación y campo público de
// formaciones de 5, 7 y 9 titulares, con contratos ficticios y sin escribir en la API.

const uuid = (value: number) => `04400000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const now = '2026-11-24T12:00:00Z';

test.use({ actionTimeout: 15_000, reducedMotion: 'reduce', trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

class FormationFixture {
  readonly org = uuid(10); readonly matchId = uuid(30); readonly home = uuid(50); readonly away = uuid(51); readonly segment = uuid(60);
  readonly saves: Record<string, unknown>[] = []; rejectNextSave = false;
  readonly players = Array.from({ length: 7 }, (_, index) => ({ roster: uuid(700 + index), player: uuid(800 + index), name: `Jugador ${index + 1}` }));

  private operation() {
    const rosters = this.players.map((entry, index) => ({ roster_id: entry.roster, player_id: entry.player, team_id: this.home, team_name: 'Local 7v7', first_name: 'Jugador', last_name: String(index + 1), dorsal_number: index + 1, is_active: true, match_roster_id: null, role: null, entered_minute: null, left_minute: null, is_valid: true }));
    return {
      match: { id: this.matchId, tournament_id: uuid(40), tournament_name: 'Torneo 044', tournament_version_id: uuid(41), stage_id: uuid(42), stage_name: 'Fase 044', group_id: null, group_name: null, matchday: 1, match_date: now, status: 'live', result_confirmed: false, version_status: 'published', home_team_id: this.home, home_team_name: 'Local 7v7', home_team_short_code: 'LOC', home_team_crest_url: null, home_team_logo_url: null, away_team_id: this.away, away_team_name: 'Visitante 7v7', away_team_short_code: 'VIS', away_team_crest_url: null, away_team_logo_url: null, home_score_regular: null, away_score_regular: null, home_score: null, away_score: null, home_penalties: null, away_penalties: null, winner_team_id: null, resolution_type: null, rules_config: { game_format: '7v7' } },
      segments: [{ id: this.segment, segment_number: 1, minute_start: 0, minute_end: null, status: 'active' }], interruptions: [], officials: [], eligible_officials: [], events: [], next_segment: null,
      rosters, lineup: [],
      // Formación privada de un formato anterior (5v5): la 044 no bloquea el cambio de formato por ella.
      tactical_lineups: [{ segment_id: this.segment, segment_number: 1, team_id: this.home, formation_code: '2-2', is_public: false, published_at: null, player_id: this.players[0]!.player, is_starter: true, position_slot: 'GK', first_name: 'Jugador', last_name: '1' }],
    };
  }

  async handle(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' } });
    if (method === 'OPTIONS') return reply({});
    const summary = { id: this.org, name: 'Organización 044', slug: 'org-044', organization_user_id: uuid(80) };
    if (path === '/auth/csrf') return reply({ csrf_token: 'formation-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') return reply({ organization_id: this.org, organization_user_id: uuid(80), user_id: uuid(1), role_code: 'administrator', permissions: ['CLOSE_MATCH_REPORT'] });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/tournaments') return reply([]);
    if (path === `/tournaments/${uuid(40)}`) return reply({ id: uuid(40), name: 'Torneo 044' });
    if (path === `/matches/${this.matchId}/operation`) return reply(this.operation());
    if (path.endsWith('/lineup') && method === 'PUT') {
      if (this.rejectNextSave) { this.rejectNextSave = false; return reply({ detail: 'La operación no está soportada para el formato del torneo', code: 'FORMATION_NOT_SUPPORTED_FOR_FORMAT' }, 409); }
      this.saves.push(request.postDataJSON() as Record<string, unknown>); return reply({});
    }
    return reply([]);
  }
}

async function navigate(page: Page, path: string) {
  await page.evaluate(async (target) => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(target);
  }, path);
}

async function openOperation(page: Page, fixture: FormationFixture) {
  await page.context().addCookies([{ name: 'bc_user_id', value: uuid(1), url: 'http://localhost:3000' }, { name: 'bc_organization_id', value: fixture.org, url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', (route) => fixture.handle(route));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(() => document.fonts.ready);
  await navigate(page, `/workspace/matches/${fixture.matchId}`);
  await expect(page.locator('.formation-config')).toHaveCount(2);
}

const formationSelect = (page: Page, index: number) => page.locator('.formation-config').nth(index).getByRole('combobox', { name: 'Formación táctica', exact: true });

test('7v7: the selector offers only 7v7, a saved 5v5 formation is disabled and blocks saving until a 7v7 one is chosen', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new FormationFixture(); await openOperation(page, fixture);
  await expect(page.getByText('Formato 7v7 · formaciones de 7v7', { exact: true }).first()).toBeVisible();

  const home = formationSelect(page, 0);
  await expect(home).toHaveValue('2-2');
  const options = await home.locator('option').evaluateAll((nodes) => nodes.map((node) => [(node as HTMLOptionElement).value, (node as HTMLOptionElement).disabled, node.textContent?.trim()]));
  expect(options).toEqual([['', false, 'Solo titulares y suplentes'], ['2-2', true, '2-2 (otra modalidad)'], ['2-3-1', false, '2-3-1'], ['3-2-1', false, '3-2-1'], ['3-1-2', false, '3-1-2']]);
  const away = await formationSelect(page, 1).locator('option').evaluateAll((nodes) => nodes.map((node) => (node as HTMLOptionElement).value));
  expect(away).toEqual(['', '2-3-1', '3-2-1', '3-1-2']);
  await expect(page.locator('.formation-config').nth(0).getByRole('status')).toHaveText('La formación guardada es de otra modalidad. Elige una formación de 7v7 o la planilla clásica para guardar.');

  const save = page.locator('#seccion-planilla').getByRole('button', { name: 'Guardar planilla', exact: true });
  await save.click();
  await expect(page.getByRole('alert')).toContainText('Hay una formación de otra modalidad.');
  expect(fixture.saves).toEqual([]);

  await home.selectOption('3-2-1');
  await expect(page.locator('.formation-config').nth(0).getByRole('status')).toHaveCount(0);
  const slots = formationSlots('3-2-1');
  for (const [index, player] of fixture.players.entries()) {
    await page.getByLabel(`Rol Jugador ${index + 1}`, { exact: true }).selectOption('starter');
    await page.getByLabel(`Posición Jugador ${index + 1}`, { exact: true }).selectOption(slots[index]!);
    expect(player.roster).toBeTruthy();
  }

  fixture.rejectNextSave = true;
  await save.click();
  await expect(page.getByRole('alert')).toContainText('La formación no es del formato del partido o no tiene sus titulares.');
  expect(fixture.saves).toEqual([]);

  await save.click();
  await expect.poll(() => fixture.saves.length).toBe(1);
  const body = fixture.saves[0] as { team_lineups: unknown; entries: { roster_id: string; role: string; position_slot?: string | null }[] };
  expect(body.team_lineups).toEqual([{ team_id: fixture.home, formation_code: '3-2-1' }]);
  expect(body.entries.filter((entry) => entry.role === 'starter').map((entry) => entry.position_slot).sort()).toEqual([...slots].sort());
});

const reduced: [string, FormationCode][] = [['5v5', '2-2'], ['7v7', '3-2-1'], ['9v9', '3-3-2']];

async function installReducedLineups(page: Page) {
  const contract = await installPublicContract(page);
  const base = contract.data.matches[0]!;
  reduced.forEach(([format, code], index) => {
    const row: PublicMatch = JSON.parse(JSON.stringify(base));
    Object.assign(row, { id: publicUuid(4400 + index), stage_id: leagueId, home_team_name: `Equipo ${format}`, away_team_name: `Rival ${format}`, home_penalties: null, away_penalties: null, resolution_type: 'regular' });
    row.lineup = { home: {
      team_id: base.home_team_id!, team_name: `Equipo ${format}`, formation_code: code, segment_number: 1, crest_url: null,
      starters: formationSlots(code).map((slot, i) => ({ player_id: publicUuid(4500 + index * 20 + i), first_name: 'Titular', last_name: `${format} ${i + 1}`, dorsal_number: i + 1, role: 'starter', position_slot: slot, photo_url: null })), substitutes: [],
    }, away: null };
    contract.data.matches.push(row);
  });
  return contract;
}

function lineupTrigger(page: Page, format: string) {
  return page.locator('.match-card').filter({ hasText: `Equipo ${format}` }).locator('.lineup-trigger:not(.timeline-trigger)');
}

test('the public pitch shows 5v5, 7v7 and 9v9 formations with one player per slot', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installReducedLineups(page); await openPublicContract(page);
  for (const [format, code] of reduced) {
    const trigger = lineupTrigger(page, format);
    await trigger.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.locator('.team-pitch-formation')).toHaveText(code);
    await expect(dialog.locator('.pitch-player')).toHaveCount(formationSlots(code).length);
    await expect(dialog.locator('.player-position[title="Portero"]')).toHaveCount(1);
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(trigger).toBeFocused();
  }
});

// Axe mide colores calculados: espera al esquema del tema y a que terminen las transiciones.
async function settleTheme(page: Page, theme: 'dark' | 'light') {
  await assertTheme(page, theme, theme);
  await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
}

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme: 7v7 selector and 5v5/9v9 pitches`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new FormationFixture(); await openOperation(page, fixture);
    await chooseTheme(page, theme);
    const toggle = page.locator('.workspace-menu-toggle');
    if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
    await expect(page.locator('.formation-config').nth(0).getByRole('status')).toBeVisible();
    await settleTheme(page, theme);
    await auditTheme(page, info, `formations-operation-${theme}-${width}`);

    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await installReducedLineups(page); await openPublicContract(page);
    await chooseTheme(page, theme); await settleTheme(page, theme);
    for (const format of ['5v5', '9v9']) {
      await lineupTrigger(page, format).click();
      await expect(page.getByRole('dialog').locator('.pitch-player')).toHaveCount(format === '5v5' ? 5 : 9);
      await auditTheme(page, info, `formations-pitch-${format}-${theme}-${width}`);
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).not.toBeVisible();
    }
  });
}
