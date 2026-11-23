import { expect, test, type Page, type Route } from '@playwright/test';
import { auditTheme, chooseTheme } from './themeChecks.ts';
import type { AuditEntry } from '../app/utils/organizationAudit.ts';

const uuid = (value: number) => `04100000-0000-4000-8000-${String(value).padStart(12, '0')}`;
const ana = uuid(1); const luis = uuid(2);
type Entry = AuditEntry;

test.use({ actionTimeout: 15_000, trace: 'off', video: 'off', timezoneId: 'America/Bogota', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

class AuditFixture {
  readonly org = uuid(10); readonly matchId = uuid(20); readonly caseId = uuid(21);
  readonly requests: URL[] = []; readonly writes: string[] = [];
  permissions = ['VIEW_ORGANIZATION_AUDIT'];
  readonly entries: Entry[] = Array.from({ length: 120 }, (_, index): Entry => {
    const performed_at = new Date(Date.UTC(2026, 10, 20, 12) - index * 3_600_000).toISOString();
    const base = { id: uuid(1000 + index), performed_at, cataloged: true, entity_available: true };
    if (index === 0) return { ...base, action: 'CLOSE_MATCH_REPORT', entity_type: 'matches', entity_id: this.matchId, actor: { kind: 'member', member_id: ana, name: 'Ana Ruiz' }, details: [{ key: 'home_score', value: 2 }, { key: 'away_score', value: 1 }, { key: 'notes', value: 'Partido con lluvia' }] };
    if (index === 1) return { ...base, action: 'DECIDE_SANCTION_CASE', entity_type: 'sanction_cases', entity_id: this.caseId, actor: { kind: 'platform', member_id: null, name: null }, details: [{ key: 'decision', value: 'annul' }] };
    if (index === 2) return { ...base, action: 'FUTURE_ACTION', cataloged: false, entity_type: 'matches', entity_id: uuid(22), entity_available: false, actor: { kind: 'member', member_id: luis, name: 'Luis Pardo' }, details: null };
    return { ...base, action: 'SAVE_MATCH_LINEUP', entity_type: 'matches', entity_id: uuid(23), actor: { kind: 'member', member_id: luis, name: 'Luis Pardo' }, details: [{ key: 'starters', value: 5 }] };
  });

  async handle(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' } });
    if (method === 'OPTIONS') return reply({});
    if (method !== 'GET' && path !== '/auth/csrf') this.writes.push(`${method} ${path}`);
    this.requests.push(url);
    const summary = { id: this.org, name: 'Organización 041', slug: 'org-041', organization_user_id: ana };
    if (path === '/auth/csrf') return reply({ csrf_token: 'audit-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') return reply({ organization_id: this.org, organization_user_id: ana, user_id: uuid(30), role_code: 'administrator', permissions: this.permissions });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/tournaments') return reply([]);
    if (path === '/organization-audit/actors') return reply([{ member_id: ana, name: 'Ana Ruiz' }, { member_id: luis, name: 'Luis Pardo' }]);
    if (path === '/organization-audit') {
      const actions = url.searchParams.getAll('action'); const actor = url.searchParams.get('actor_member_id');
      const from = url.searchParams.get('from'); const to = url.searchParams.get('to');
      const limit = Number(url.searchParams.get('limit')); const offset = Number(url.searchParams.get('offset'));
      const rows = this.entries.filter((entry) => (!actions.length || actions.includes(entry.action)) && (!actor || entry.actor.member_id === actor)
        && (!from || entry.performed_at >= from) && (!to || entry.performed_at <= to));
      return reply({ items: rows.slice(offset, offset + limit), total: rows.length, limit, offset });
    }
    return reply({ detail: 'Not found' }, 404);
  }
  audits() { return this.requests.filter((url) => url.pathname.endsWith('/organization-audit')); }
}

async function navigate(page: Page, path: string) {
  await page.evaluate(async (target) => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(target);
  }, path);
}

async function open(page: Page, fixture: AuditFixture, path = '/workspace/audit') {
  await page.context().addCookies([{ name: 'bc_user_id', value: uuid(30), url: 'http://localhost:3000' }, { name: 'bc_organization_id', value: fixture.org, url: 'http://localhost:3000' }]);
  await page.route('**/api/v1/**', (route) => fixture.handle(route));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await page.evaluate(() => document.fonts.ready);
  await navigate(page, path);
  await expect(page.getByRole('heading', { name: 'Auditoría de la organización', level: 1 })).toBeVisible();
}

const rows = (page: Page) => page.getByRole('table', { name: /Entradas de auditoría/ }).locator('tbody tr');

test('filters live in the URL, convert local days to inclusive UTC and paginate newest first', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new AuditFixture(); await open(page, fixture);
  await expect(page.getByRole('link', { name: 'Auditoría', exact: true })).toBeVisible();
  await expect(rows(page)).toHaveCount(50);
  await expect(rows(page).first()).toContainText('Acta cerrada');
  await expect(page.getByText('1–50 de 120', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Siguiente', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace\/audit\?page=2$/);
  await expect(page.getByText('51–100 de 120', { exact: true })).toBeVisible();
  expect(fixture.audits().at(-1)?.searchParams.get('offset')).toBe('50');

  await page.getByLabel('Acciones', { exact: true }).selectOption(['CLOSE_MATCH_REPORT', 'SAVE_MATCH_LINEUP']);
  await page.getByRole('combobox', { name: 'Responsable', exact: true }).selectOption(luis);
  await page.getByLabel('Desde', { exact: true }).fill('2026-11-19');
  await page.getByLabel('Hasta', { exact: true }).fill('2026-11-18');
  await page.getByRole('button', { name: 'Aplicar filtros', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('no puede ser posterior');
  await expect(page).toHaveURL(/\?page=2$/);

  await page.getByLabel('Hasta', { exact: true }).fill('2026-11-20');
  await page.getByRole('button', { name: 'Aplicar filtros', exact: true }).click();
  await expect(page).toHaveURL(/action=CLOSE_MATCH_REPORT&action=SAVE_MATCH_LINEUP&actor=.+&from=2026-11-19&to=2026-11-20$/);
  const last = fixture.audits().at(-1)!;
  expect(last.searchParams.getAll('action')).toEqual(['CLOSE_MATCH_REPORT', 'SAVE_MATCH_LINEUP']);
  expect([last.searchParams.get('actor_member_id'), last.searchParams.get('from'), last.searchParams.get('to'), last.searchParams.get('offset')])
    .toEqual([luis, '2026-11-19T05:00:00.000Z', '2026-11-21T04:59:59.999Z', '0']);
  await expect(rows(page).first()).toContainText('Alineación guardada');

  await navigate(page, '/workspace');
  await navigate(page, '/workspace/audit?action=DECIDE_SANCTION_CASE');
  await expect(page.getByLabel('Acciones', { exact: true })).toHaveValues(['DECIDE_SANCTION_CASE']);
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText('Administración de plataforma');
  await page.getByRole('combobox', { name: 'Responsable', exact: true }).selectOption(ana);
  await page.getByRole('button', { name: 'Aplicar filtros', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('No hay entradas que coincidan');
  await page.getByRole('button', { name: 'Limpiar filtros', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace\/audit$/);
  await page.getByLabel('Desde', { exact: true }).fill('2026-11-21');
  await page.getByLabel('Hasta', { exact: true }).fill('2026-11-20');
  await page.getByRole('button', { name: 'Aplicar filtros', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await page.getByRole('button', { name: 'Limpiar filtros', exact: true }).click();
  await expect(page.getByLabel('Desde', { exact: true })).toHaveValue('');
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(fixture.writes).toEqual([]);
});

test('the detail dialog is keyboard operable and links only to accessible entities', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new AuditFixture(); await open(page, fixture);
  const trigger = rows(page).nth(0).getByRole('button', { name: 'Acta cerrada', exact: true });
  await trigger.focus(); await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Detalle de la entrada' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Detalle de la entrada' })).toBeFocused();
  for (const text of ['Goles locales', 'Partido con lluvia', 'Ana Ruiz']) await expect(dialog.getByText(text, { exact: true })).toBeVisible();
  await expect(dialog.getByRole('link')).toHaveAttribute('href', `/workspace/matches/${fixture.matchId}`);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();

  await expect(rows(page).nth(0).getByRole('link')).toHaveAttribute('href', `/workspace/matches/${fixture.matchId}`);
  await expect(rows(page).nth(1).getByRole('link')).toHaveCount(0);
  await expect(rows(page).nth(1)).toContainText(fixture.caseId);
  const unknown = rows(page).nth(2).getByRole('button', { name: 'Acción no catalogada', exact: true });
  await unknown.focus(); await page.keyboard.press('Enter');
  await expect(dialog.getByText('Acción no catalogada: su contenido no se muestra.')).toBeVisible();
  await expect(dialog.getByRole('link')).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Cerrar', exact: true }).click();
  await expect(unknown).toBeFocused();
});

test('sanction cases link with VIEW_SANCTION_CASES; without the audit permission there is no menu entry nor request', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new AuditFixture(); fixture.permissions = ['VIEW_ORGANIZATION_AUDIT', 'VIEW_SANCTION_CASES'];
  await open(page, fixture);
  await expect(rows(page).nth(1).getByRole('link')).toHaveAttribute('href', `/workspace/sanctions?case=${fixture.caseId}`);
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const denied = new AuditFixture(); denied.permissions = ['VIEW_SANCTION_CASES'];
  await page.route('**/api/v1/**', (route) => denied.handle(route));
  await page.goto('/');
  await page.waitForFunction(() => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__?: { config: { globalProperties: { $nuxt: { isHydrating: boolean } } } } };
    return root?.__vue_app__?.config.globalProperties.$nuxt.isHydrating === false;
  });
  await navigate(page, '/workspace/audit');
  await expect(page.getByRole('alert')).toContainText('No tienes permiso para ver la auditoría');
  await expect(page.getByRole('link', { name: 'Auditoría', exact: true })).toHaveCount(0);
  expect(denied.audits()).toEqual([]);
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme, with and without the dialog`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new AuditFixture(); await open(page, fixture);
    await chooseTheme(page, theme);
    const toggle = page.locator('.workspace-menu-toggle');
    if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
    await expect(rows(page)).toHaveCount(50);
    await auditTheme(page, info, `audit-${theme}-${width}`);
    await rows(page).nth(0).getByRole('button', { name: 'Acta cerrada', exact: true }).click();
    await expect(page.getByRole('dialog', { name: 'Detalle de la entrada' })).toBeVisible();
    await auditTheme(page, info, `audit-dialog-${theme}-${width}`);
  });
}
