import { expect, test, type Page, type Route } from '@playwright/test';
import { assertTheme, auditTheme, chooseTheme } from './themeChecks.ts';

// Spec 047: gestión de webhooks en el Workspace, con teclado y axe en ambos
// temas. Contratos ficticios, sin escribir en la API.

const uuid = (value: number) => `04700000-0000-4000-8000-${String(value).padStart(12, '0')}`;

test.use({ actionTimeout: 15_000, reducedMotion: 'reduce', trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

type Webhook = { id: string; url: string; event_types: string[]; is_active: boolean; created_at: string; updated_at: string };

class WebhookFixture {
  readonly org = uuid(10);
  readonly commands: string[] = [];
  readonly bodies: unknown[] = [];
  secrets = 0;
  items: Webhook[] = [
    { id: uuid(1), url: 'https://hooks.example.com/bracket', event_types: ['result_confirmed', 'sanction_generated'], is_active: true, created_at: '2026-11-25T10:00:00Z', updated_at: '2026-11-25T10:00:00Z' },
  ];
  deliveries = [
    { id: uuid(20), event_type: 'webhook_test', created_at: '2026-11-25T12:00:00Z', attempts: 1, last_status_code: 204, status: 'delivered' },
    { id: uuid(21), event_type: 'result_confirmed', created_at: '2026-11-25T11:00:00Z', attempts: 2, last_status_code: 503, status: 'pending' },
  ];

  async handle(route: Route) {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1', ''); const method = request.method();
    const headers = { 'Access-Control-Allow-Origin': request.headers()['origin'] || 'http://localhost:3000', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'Content-Type,X-Organization-ID,X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS' };
    const reply = (body: unknown, status = 200) => route.fulfill({ status, json: body, headers });
    if (method === 'OPTIONS') return reply({});
    const summary = { id: this.org, name: 'Organización 047', slug: 'org-047', organization_user_id: uuid(80) };
    if (path === '/auth/csrf') return reply({ csrf_token: 'webhook-fixture-csrf' });
    if (path === '/organizations') return reply([summary]);
    if (path === '/organizations/current') return reply(summary);
    if (path === '/organizations/current/access') return reply({ organization_id: this.org, organization_user_id: uuid(80), user_id: uuid(81), role_code: 'administrator', permissions: ['MANAGE_WEBHOOKS'] });
    if (path === '/platform/access') return reply({ allowed: false });
    if (path === '/webhooks' && method === 'POST') {
      const body = request.postDataJSON() as { url: string; event_types: string[] };
      this.commands.push('create'); this.bodies.push(body);
      const item = { id: uuid(2), url: body.url, event_types: body.event_types, is_active: true, created_at: '2026-11-25T13:00:00Z', updated_at: '2026-11-25T13:00:00Z' };
      this.items.push(item); this.secrets += 1;
      return reply({ ...item, secret: `whsec_created_${this.secrets}` }, 201);
    }
    if (path === '/webhooks') return reply(this.items);
    const match = path.match(/^\/webhooks\/([^/]+)(\/[a-z-]+)?$/);
    if (match) {
      const [, id, action] = match;
      if (action === '/rotate-secret' && method === 'POST') { this.commands.push(`rotate:${id}`); this.secrets += 1; return reply({ secret: `whsec_rotated_${this.secrets}` }); }
      if (action === '/test' && method === 'POST') { this.commands.push(`test:${id}`); return reply({ delivery_id: uuid(22) }, 202); }
      if (action === '/deliveries') return reply(this.deliveries);
      if (!action && method === 'PATCH') {
        const body = request.postDataJSON() as Partial<Webhook>; this.commands.push(`patch:${id}`); this.bodies.push(body);
        const item = this.items.find((entry) => entry.id === id)!; Object.assign(item, body); return reply(item);
      }
      if (!action && method === 'DELETE') { this.commands.push(`delete:${id}`); this.items = this.items.filter((entry) => entry.id !== id); return route.fulfill({ status: 204, body: '', headers }); }
    }
    if (path === '/notifications') return reply({ items: [], unread_count: 0, total: 0, limit: 1, offset: 0 });
    if (path === '/competitive-impacts' || path === '/rectifications') return reply({ items: [], total: 0, limit: 25, offset: 0 });
    return reply([]);
  }
}

async function openWebhooks(page: Page, fixture: WebhookFixture) {
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
    await root.__vue_app__.config.globalProperties.$router.push('/workspace/webhooks');
  });
  await expect(page.getByRole('heading', { level: 1, name: 'Webhooks' })).toBeVisible();
  await expect(page.locator('.webhook-item')).toHaveCount(fixture.items.length);
  await page.waitForLoadState('networkidle');
}

const secretDialog = (page: Page) => page.getByRole('dialog', { name: 'Secreto del webhook' });

test('a webhook is created with the keyboard and its secret is shown only once', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new WebhookFixture(); await openWebhooks(page, fixture);
  await expect(page.locator('.workspace-primary-nav').getByRole('link', { name: 'Webhooks' })).toHaveAttribute('aria-current', 'page');
  const url = page.getByRole('textbox', { name: 'URL de destino' });
  await url.focus(); await page.keyboard.type('http://insecure.example/hook');
  const scheduled = page.getByRole('checkbox', { name: 'Partido programado' });
  await scheduled.focus(); await page.keyboard.press('Space');
  await page.getByRole('button', { name: 'Crear webhook' }).focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: 'Escribe una URL HTTPS válida' })).toBeVisible();
  await expect(url).toHaveAttribute('aria-invalid', 'true');
  expect(fixture.commands).toEqual([]);
  await url.fill(''); await url.focus(); await page.keyboard.type('HTTPS://receiver.example.org/bc');
  await page.getByRole('button', { name: 'Crear webhook' }).focus(); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.commands).toEqual(['create']);
  expect(fixture.bodies[0]).toEqual({ url: 'https://receiver.example.org/bc', event_types: ['match_scheduled'] });
  await expect(secretDialog(page)).toBeVisible();
  await expect(secretDialog(page).locator('code')).toHaveText('whsec_created_1');
  await expect(secretDialog(page)).toContainText('no se volverá a mostrar');
  await expect(secretDialog(page).getByRole('heading', { name: 'Secreto del webhook' })).toBeFocused();
  await secretDialog(page).getByRole('button', { name: 'Ya lo he guardado' }).focus(); await page.keyboard.press('Enter');
  await expect(secretDialog(page)).toBeHidden();
  await expect(page.locator('body')).not.toContainText('whsec_created_1');
  await expect(page.locator('.webhook-item')).toHaveCount(2);
  await expect(page.locator('.webhook-item').nth(1)).toContainText('https://receiver.example.org/bc');
});

test('a test delivery is queued and the delivery history opens with the keyboard', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new WebhookFixture(); await openWebhooks(page, fixture);
  const item = page.locator('.webhook-item').first();
  await item.getByRole('button', { name: 'Enviar prueba' }).focus(); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.commands).toEqual([`test:${uuid(1)}`]);
  await expect(page.getByRole('status').filter({ hasText: 'Entrega de prueba en cola' })).toBeVisible();
  const toggle = item.getByRole('button', { name: 'Ver entregas' });
  await toggle.focus(); await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  const table = item.getByRole('table', { name: 'Últimas entregas (30 días)' });
  await expect(table.getByRole('row')).toHaveCount(3);
  await expect(table.getByRole('row').nth(1)).toContainText(/Prueba.*1.*204.*Entregada/);
  await expect(table.getByRole('row').nth(2)).toContainText(/Resultado confirmado.*2.*503.*Pendiente/);
});

test('rotating the secret asks for confirmation and shows the new secret once', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = new WebhookFixture(); await openWebhooks(page, fixture);
  await page.locator('.webhook-item').first().getByRole('button', { name: 'Rotar secreto' }).focus(); await page.keyboard.press('Enter');
  const confirm = page.getByRole('dialog', { name: '¿Rotar el secreto?' });
  await expect(confirm).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(confirm).toBeHidden();
  expect(fixture.commands).toEqual([]);
  await page.locator('.webhook-item').first().getByRole('button', { name: 'Rotar secreto' }).focus(); await page.keyboard.press('Enter');
  await confirm.getByRole('button', { name: 'Rotar secreto' }).focus(); await page.keyboard.press('Enter');
  await expect.poll(() => fixture.commands).toEqual([`rotate:${uuid(1)}`]);
  await expect(secretDialog(page).locator('code')).toHaveText('whsec_rotated_1');
  await page.keyboard.press('Escape');
  await expect(secretDialog(page)).toBeHidden();
  await expect(page.locator('body')).not.toContainText('whsec_rotated_1');
});

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) {
  test(`axe has no violations at ${width} px in the ${theme} theme on the webhooks page`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    const fixture = new WebhookFixture(); await openWebhooks(page, fixture);
    await chooseTheme(page, theme);
    const menu = page.locator('.workspace-menu-toggle');
    if (await menu.isVisible() && await menu.getAttribute('aria-expanded') === 'true') await menu.click();
    const toggle = page.locator('.webhook-item').first().getByRole('button', { name: 'Ver entregas' });
    await toggle.click();
    await expect(page.getByRole('table')).toBeVisible();
    await assertTheme(page, theme, theme);
    await page.evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => undefined))));
    await auditTheme(page, info, `webhooks-${theme}-${width}`);
  });
}
