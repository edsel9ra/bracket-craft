import { expect, test, type Page, type Route } from '@playwright/test';
import { assertTheme, auditTheme, chooseTheme } from './themeChecks.ts';

// Spec 046: bandeja y preferencias de avisos en el Workspace, con teclado y
// axe en ambos temas. Contratos ficticios, sin escribir en la API.

const uuid = (value: number) => `04600000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const TYPES = ['match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated'] as const;

test.use({ actionTimeout: 15_000, reducedMotion: 'reduce', trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

class NotificationFixture {
  readonly org = uuid(10);
  readonly commands: string[] = [];
  readonly saves: { items: { type: string; channel: string; enabled: boolean }[] }[] = [];
  preferences: { type: string; channel: string; enabled: boolean }[] = TYPES.flatMap((type) => [{ type, channel: 'inbox', enabled: true }, { type, channel: 'email', enabled: false }]);
  items = [
    { id: uuid(1), type: 'sanction_generated', created_at: '2026-11-24T15:00:00Z', read_at: null, tournament_id: uuid(40), tournament_name: 'Torneo 046', match_id: uuid(30), home_team_name: 'Leones', away_team_name: 'Tigres', match_count: null, sanction: { player_name: 'Ana Ruiz', team_name: 'Leones', matches_suspended: 2 } },
    { id: uuid(2), type: 'result_confirmed', created_at: '2026-11-24T14:00:00Z', read_at: null, tournament_id: uuid(40), tournament_name: 'Torneo 046', match_id: uuid(30), home_team_name: 'Leones', away_team_name: 'Tigres', match_count: null, sanction: null },
    { id: uuid(3), type: 'match_scheduled', created_at: '2026-11-24T13:00:00Z', read_at: '2026-11-24T13:30:00Z', tournament_id: uuid(40), tournament_name: 'Torneo 046', match_id: null, home_team_name: null, away_team_name: null, match_count: 6, sanction: null },
  ];

  page(limit: number) {
    return { items: this.items.slice(0, limit), unread_count: this.items.filter((item) => !item.read_at).length, total: this.items.length, limit, offset: 0 };
  }

  async handle(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' } });
    if (method === 'OPTIONS') return reply({});
    const summary = { id: this.org, name: 'Organización 046', slug: 'org-046', organization_user_id: uuid(80) };
    if (path === '/auth/csrf') return reply({ csrf_token: 'notification-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') return reply({ organization_id: this.org, organization_user_id: uuid(80), user_id: uuid(81), role_code: 'observer', permissions: [] });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/notifications') return reply(this.page(Number(url.searchParams.get('limit') || 25)));
    if (path === '/notifications/read-all' && method === 'POST') { this.commands.push('read-all'); this.items.forEach((item) => { item.read_at ??= '2026-11-24T16:00:00Z'; }); return route.fulfill({ status: 204, body: '' , headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true' } }); }
    const read = path.match(/^\/notifications\/([^/]+)\/read$/);
    if (read && method === 'POST') { this.commands.push(read[1]!); const item = this.items.find((entry) => entry.id === read[1]); if (item) item.read_at = '2026-11-24T16:00:00Z'; return route.fulfill({ status: 204, body: '', headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true' } }); }
    if (path === '/notification-preferences' && method === 'PUT') { const body = request.postDataJSON() as NotificationFixture['saves'][number]; this.saves.push(body); this.preferences = body.items; return reply(body); }
    if (path === '/notification-preferences') return reply({ items: this.preferences });
    if (path === '/competitive-impacts' || path === '/rectifications') return reply({ items: [], total: 0, limit: 25, offset: 0 });
    return reply([]);
  }
}

async function openInbox(page: Page, fixture: NotificationFixture) {
  await page.context().addCookies([{ name: 'bc_user_id', value: uuid(81), url: 'http://localhost:3000' }, { name: 'bc_organization_id', value: fixture.org, url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', (route) => fixture.handle(route));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async () => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push('/workspace/notifications');
  });
  await expect(page.getByRole('heading', { level: 1, name: 'Notificaciones' })).toBeVisible();
  await expect(page.locator('.notification-item')).toHaveCount(3);
  // El Workspace puede recargar la bandeja al resolver la organización; se espera a que termine.
  await page.waitForLoadState('networkidle');
}

const inbox = (page: Page) => page.getByRole('region', { name: 'Bandeja' });

test('the inbox lists the notices, names the player for this response and links each notice', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new NotificationFixture(); await openInbox(page, fixture);
  await expect(inbox(page).getByText('2 sin leer', { exact: true })).toBeVisible();
  await expect(page.locator('.workspace-primary-nav').getByRole('link', { name: 'Notificaciones 2 sin leer' })).toHaveAttribute('aria-current', 'page');
  const sanction = page.locator('.notification-item').first();
  await expect(sanction.getByRole('heading', { level: 3 })).toHaveText(/Sin leer\s*Sanción generada/);
  await expect(sanction).toContainText('Ana Ruiz (Leones) · partidos de suspensión: 2');
  await expect(sanction.getByRole('link', { name: 'Ver partido' })).toHaveAttribute('href', `/workspace/matches/${uuid(30)}`);
  const scheduled = page.locator('.notification-item').nth(2);
  await expect(scheduled).toContainText('Torneo 046 · Partidos programados: 6');
  await expect(scheduled.getByRole('link', { name: 'Ver calendario' })).toHaveAttribute('href', `/workspace/tournaments/${uuid(40)}/calendar`);
  await expect(scheduled.getByRole('button', { name: 'Marcar como leído' })).toHaveCount(0);
});

test('marking one and then all as read works with the keyboard and updates the counter', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new NotificationFixture(); await openInbox(page, fixture);
  const first = page.locator('.notification-item').first().getByRole('button', { name: 'Marcar como leído' });
  await first.focus(); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.commands).toEqual([uuid(1)]);
  await expect(inbox(page).getByText('1 sin leer', { exact: true })).toBeVisible();
  await expect(page.locator('.workspace-primary-nav').getByRole('link', { name: 'Notificaciones 1 sin leer' })).toBeVisible();
  const all = inbox(page).getByRole('button', { name: 'Marcar todo como leído' });
  await all.focus(); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.commands).toEqual([uuid(1), 'read-all']);
  await expect(inbox(page).getByText('0 sin leer', { exact: true })).toBeVisible();
  await expect(all).toBeDisabled();
  await expect(page.locator('.workspace-primary-nav').getByRole('link', { name: 'Notificaciones', exact: true })).toBeVisible();
});

test('preferences are saved with the keyboard as the eight pairs', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new NotificationFixture(); await openInbox(page, fixture);
  const save = page.getByRole('button', { name: 'Guardar preferencias' });
  await expect(save).toBeDisabled();
  const email = page.getByRole('checkbox', { name: 'Correo: Sanción generada' });
  await expect(email).not.toBeChecked();
  await email.focus(); await page.keyboard.press('Space');
  await expect(email).toBeChecked(); await expect(save).toBeEnabled();
  await save.focus(); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.saves.length).toBe(1);
  expect(fixture.saves[0]!.items).toHaveLength(8);
  expect(fixture.saves[0]!.items.find((item) => item.type === 'sanction_generated' && item.channel === 'email')!.enabled).toBe(true);
  await expect(page.getByRole('status').filter({ hasText: 'Preferencias guardadas.' })).toBeVisible();
  await expect(save).toBeDisabled();
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme on the notifications page`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new NotificationFixture(); await openInbox(page, fixture);
    await chooseTheme(page, theme);
    const toggle = page.locator('.workspace-menu-toggle');
    if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
    await expect(page.getByRole('checkbox')).toHaveCount(8);
    await assertTheme(page, theme, theme);
    await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    await auditTheme(page, info, `notifications-${theme}-${width}`);
  });
}
