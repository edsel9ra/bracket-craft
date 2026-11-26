import { expect, test, type Page, type Route } from '@playwright/test';
import { assertTheme, auditTheme, chooseTheme } from './themeChecks.ts';

// Spec 049: «Equipo del torneo» en el Workspace. Alta y retirada del operador
// del torneo con teclado y axe en ambos temas. Contratos ficticios, sin
// escribir en la API.

const uuid = (value: number) => `04900000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const now = '2026-11-26T15:00:00Z';

test.use({ actionTimeout: 15_000, reducedMotion: 'reduce', trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

interface Member { organization_user_id: string; full_name: string; email: string; role_code: string; is_active: boolean }

class TeamFixture {
  readonly org = uuid(10); readonly tournament = uuid(40); readonly self = uuid(80);
  readonly requests: string[] = [];
  readonly members: Member[] = [
    { organization_user_id: this.self, full_name: 'Ada Administradora', email: 'ada@example.test', role_code: 'administrator', is_active: true },
    { organization_user_id: uuid(82), full_name: 'Oto Operador', email: 'oto@example.test', role_code: 'operator', is_active: true },
    { organization_user_id: uuid(83), full_name: 'Vera Observadora', email: 'vera@example.test', role_code: 'viewer', is_active: true },
    { organization_user_id: uuid(84), full_name: 'Ivo Inactivo', email: 'ivo@example.test', role_code: 'viewer', is_active: false },
  ];
  readonly assigned = new Set<string>([uuid(82)]);

  readonly role: 'administrator' | 'viewer';
  constructor(role: 'administrator' | 'viewer' = 'administrator') { this.role = role; }

  private team() {
    return this.members.filter((member) => this.assigned.has(member.organization_user_id)).map((member) => ({
      organization_user_id: member.organization_user_id, full_name: member.full_name, organization_role_code: member.role_code,
      role_code: 'tournament_operator', is_active: member.is_active, adds_permissions: !['owner', 'administrator', 'operator'].includes(member.role_code), assigned_at: now,
    }));
  }

  async handle(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const headers = { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' };
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers });
    if (method === 'OPTIONS') return reply({});
    const summary = { id: this.org, name: 'Organización 049', slug: 'org-049', organization_user_id: this.self };
    if (path === '/auth/csrf') return reply({ csrf_token: 'team-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') {
      const permissions = this.role === 'administrator' ? ['MANAGE_MEMBERS', 'MANAGE_TOURNAMENTS', 'CLOSE_MATCH_REPORT'] : [];
      return reply({ organization_id: this.org, organization_user_id: this.self, user_id: uuid(81), role_code: this.role, permissions, operated_tournament_ids: this.assigned.has(this.self) ? [this.tournament] : [] });
    }
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/tournaments') return reply([{ id: this.tournament, name: 'Copa 049' }]);
    if (path === '/organizations/members') { this.requests.push('GET members'); return reply(this.members); }
    if (path === `/tournaments/${this.tournament}/team`) { this.requests.push('GET team'); return reply(this.team()); }
    const member = path.match(new RegExp(`^/tournaments/${this.tournament}/team/([^/]+)$`))?.[1];
    if (member && method === 'PUT') {
      this.requests.push(`PUT ${member}`);
      const created = !this.assigned.has(member); this.assigned.add(member);
      return reply(this.team().find((item) => item.organization_user_id === member), created ? 201 : 200);
    }
    if (member && method === 'DELETE') {
      this.requests.push(`DELETE ${member}`);
      if (!this.assigned.delete(member)) return reply({ detail: 'Asignación no encontrada' }, 404);
      return route.fulfill({ status: 204, headers });
    }
    if (path === '/notifications') return reply({ items: [], unread_count: 0, total: 0, limit: 1, offset: 0 });
    if (path === '/competitive-impacts' || path === '/rectifications') return reply({ items: [], total: 0, limit: 25, offset: 0 });
    return reply([]);
  }
}

async function openTeam(page: Page, fixture: TeamFixture) {
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
  }, `/workspace/tournaments/${fixture.tournament}/team`);
  await expect(page.getByRole('heading', { level: 1, name: 'Equipo del torneo' })).toBeVisible();
  await expect(page.getByRole('row', { name: /Oto Operador/ })).toBeVisible();
  await page.waitForLoadState('networkidle');
}

test('an administrator assigns and removes a tournament operator with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new TeamFixture(); await openTeam(page, fixture);
  await expect(page.locator('.workspace-tournament-nav').getByRole('link', { name: 'Equipo del torneo' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('row', { name: /Oto Operador/ })).toContainText('No añade permisos');
  await expect(page.getByText('@example.test')).toHaveCount(0);

  const select = page.getByLabel('Miembro que asignar');
  await expect(select.locator('option')).toHaveText(['Elige un miembro', 'Ada Administradora · Administrador', 'Vera Observadora · Observador']);
  const assign = page.getByRole('button', { name: 'Asignar', exact: true });
  await expect(assign).toBeDisabled();
  await select.focus(); await select.selectOption(uuid(83));
  await page.keyboard.press('Tab'); await expect(assign).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'Operador del torneo asignado.' })).toBeVisible();
  const vera = page.getByRole('row', { name: /Vera Observadora/ });
  await expect(vera).toBeVisible(); await expect(vera).not.toContainText('No añade permisos');
  await expect(select.locator('option')).toHaveText(['Elige un miembro', 'Ada Administradora · Administrador']);

  const remove = page.getByRole('button', { name: 'Retirar: Vera Observadora' });
  await remove.focus(); await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Retirar operador del torneo' });
  await expect(dialog).toContainText('Vera Observadora dejará de poder operar');
  await dialog.getByRole('button', { name: 'Retirar', exact: true }).focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('status').filter({ hasText: 'Operador del torneo retirado.' })).toBeVisible();
  await expect(vera).toHaveCount(0);
  expect(fixture.requests.filter((item) => !item.startsWith('GET'))).toEqual([`PUT ${uuid(83)}`, `DELETE ${uuid(83)}`]);
});

test('any other member reads the team without controls nor the member list', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new TeamFixture('viewer'); await openTeam(page, fixture);
  await expect(page.getByText('Solo el dueño y los administradores pueden cambiar el equipo del torneo.')).toBeVisible();
  await expect(page.getByLabel('Miembro que asignar')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Retirar/ })).toHaveCount(0);
  expect(fixture.requests).not.toContain('GET members');
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme on the tournament team page`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new TeamFixture(); await openTeam(page, fixture);
    await chooseTheme(page, theme);
    const menu = page.locator('.workspace-menu-toggle');
    if (await menu.isVisible() && await menu.getAttribute('aria-expanded') === 'true') await menu.click();
    await page.getByLabel('Miembro que asignar').selectOption(uuid(83));
    await page.getByRole('button', { name: 'Asignar', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Operador del torneo asignado.' })).toBeVisible();
    await assertTheme(page, theme, theme);
    await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    await auditTheme(page, info, `tournament-team-${theme}-${width}`);
  });
}
