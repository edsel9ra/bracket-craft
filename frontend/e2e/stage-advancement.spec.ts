import { expect, test, type Page, type Route } from '@playwright/test';
import { auditTheme, waitThemeHydration } from './themeChecks.ts';
import { assertNoDocumentOverflow } from './publicPolishChecks.ts';

// Spec 040 T10: editor de orígenes (borrador) y panel de resolución (publicado) con un contrato
// ficticio del torneo; la sesión real del Workspace solo autentica, no se escribe en la API.
const id = (n: number) => `04000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const TOURNAMENT = id(1);
const VERSION = id(2);
const GROUPS = id(3);
const BRACKET = id(4);
const GROUP_A = id(5);
const GROUP_B = id(6);
const FINGERPRINT = 'a'.repeat(64);

type Call = { method: string; path: string; body: unknown };

const template = [
  { seed: 1, kind: 'group_position', source_stage_id: GROUPS, position: 1, group_id: GROUP_A, ordinal: null },
  { seed: 2, kind: 'group_position', source_stage_id: GROUPS, position: 2, group_id: GROUP_B, ordinal: null },
  { seed: 3, kind: 'group_position', source_stage_id: GROUPS, position: 1, group_id: GROUP_B, ordinal: null },
  { seed: 4, kind: 'group_position', source_stage_id: GROUPS, position: 2, group_id: GROUP_A, ordinal: null },
];
const sourceStages = [{
  id: GROUPS, name: 'Grupos', stage_type: 'custom_group',
  groups: [{ id: GROUP_A, name: 'A', size: 4 }, { id: GROUP_B, name: 'B', size: 4 }],
}];

async function installContract(page: Page, status: 'draft' | 'published') {
  const calls: Call[] = [];
  const state = { origins: status === 'draft' ? [] as typeof template : template, put: [422, 200], post: [409, 201] };
  const stages = [
    { id: GROUPS, tournament_version_id: VERSION, name: 'Grupos', stage_type: 'custom_group', stage_order: 1, version_status: status },
    { id: BRACKET, tournament_version_id: VERSION, name: 'Eliminatoria', stage_type: 'single_elimination', stage_order: 2, version_status: status },
  ];
  const preview = () => ({
    stage_id: BRACKET, fingerprint: FINGERPRINT, resolvable: true,
    slots: template.map((slot) => ({ ...slot, team_id: id(100 + slot.seed), team_name: `Equipo ${slot.seed}`, reason: null })),
    source_stages: [{ id: GROUPS, finished: true }],
  });
  const fulfill = (route: Route, status: number, json?: unknown) => route.fulfill({
    status, ...(json === undefined ? {} : { json }),
    headers: {
      'Access-Control-Allow-Origin': route.request().headers()['origin'] ?? '*',
      'Access-Control-Allow-Credentials': 'true',
      'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE',
      'Access-Control-Allow-Headers': route.request().headers()['access-control-request-headers'] ?? '*',
    },
  });
  await page.route(`**/api/v1/tournaments/${TOURNAMENT}/**`, async (route) => {
    const request = route.request();
    if (request.method() === 'OPTIONS') return fulfill(route, 204);
    const path = new URL(request.url()).pathname.replace(`/api/v1/tournaments/${TOURNAMENT}`, '');
    if (path.includes('slot-origins') || path.includes('resolution')) calls.push({ method: request.method(), path, body: request.postDataJSON() ?? null });
    const originsState = () => ({ stage_id: BRACKET, stage_type: 'single_elimination', status: status === 'draft' ? 'editable' : 'frozen', origins: state.origins, source_stages: sourceStages });
    if (path === '/versions') return fulfill(route, 200, [{ id: VERSION, version_number: 1, status, rules_config: {} }]);
    if (path === '/stages') return fulfill(route, 200, stages);
    if (path === `/stages/${BRACKET}/slot-origins` && request.method() === 'GET') return fulfill(route, 200, originsState());
    if (path === `/stages/${BRACKET}/slot-origins/template`) return fulfill(route, 200, { source_stage_id: GROUPS, slots_count: 4, origins: template });
    if (path === `/stages/${BRACKET}/slot-origins` && request.method() === 'PUT') {
      if (state.put.shift() === 422) {
        return fulfill(route, 422, { detail: { code: 'invalid_slot_origins', errors: [{ seed: 2, code: 'group_not_found' }] } });
      }
      state.origins = template;
      return fulfill(route, 200, originsState());
    }
    if (path === `/stages/${BRACKET}/resolution/preview`) return fulfill(route, 200, preview());
    if (path === `/stages/${BRACKET}/resolution` && request.method() === 'POST') {
      return state.post.shift() === 409 ? fulfill(route, 409, { detail: { code: 'stale_fingerprint' } }) : fulfill(route, 201, preview());
    }
    if (request.method() === 'GET') return fulfill(route, 200, []);
    return fulfill(route, 404, { detail: 'Not Found' });
  });
  return calls;
}

async function openTournament(page: Page) {
  await page.goto('/workspace');
  await waitThemeHydration(page);
  await page.evaluate(async (path) => {
    const root = document.querySelector('#__nuxt') as HTMLElement & { __vue_app__: { config: { globalProperties: { $router: { push: (path: string) => Promise<unknown> } } } } };
    await root.__vue_app__.config.globalProperties.$router.push(path);
  }, `/workspace/tournaments/${TOURNAMENT}`);
}

test.use({ reducedMotion: 'reduce', trace: 'off', video: 'off' });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

for (const width of [1440, 390]) for (const theme of ['dark', 'light'] as const) test.describe(`avance entre fases ${width} ${theme}`, () => {
  test.use({ viewport: { width, height: width === 390 ? 844 : 900 } });
  test.beforeEach(async ({ context, baseURL }) => {
    await context.addCookies([
      { name: 'bc_locale', value: 'es', url: baseURL! },
      { name: 'bc_theme', value: theme, url: baseURL! },
    ]);
  });

  test('borrador: la plantilla no guarda nada, el 422 marca la plaza y guardar genera la llave', async ({ page }, info) => {
    const calls = await installContract(page, 'draft');
    await openTournament(page);
    const editor = page.locator('section.slot-origins');
    await expect(editor.getByRole('heading', { name: 'Orígenes de las plazas · Eliminatoria' })).toBeVisible();
    await editor.getByLabel('Número de plazas').fill('4');
    await editor.getByRole('button', { name: 'Proponer la plantilla clásica' }).click();
    await expect(editor.locator('.slot-origin-row')).toHaveCount(4);
    await expect(editor.getByText('Plantilla aplicada al borrador.')).toBeVisible();
    expect(calls.map((call) => call.method)).toEqual(['GET', 'GET']);
    await editor.getByLabel('Inicio de la primera ronda').fill('2026-12-01T10:00');
    await editor.getByRole('button', { name: 'Guardar orígenes y generar la llave' }).click();
    const slotError = editor.locator('.slot-origin-row').nth(1).getByText('El grupo no existe en esa fase.');
    await expect(slotError).toBeVisible();
    await expect(editor.locator('.slot-origin-row').nth(1).getByLabel('Tipo de origen')).toHaveAttribute('aria-invalid', 'true');
    await expect(editor.getByRole('alert')).toContainText('Hay plazas con un origen no válido');
    await assertNoDocumentOverflow(page);
    await auditTheme(page, info, `stage-origins-${width}-${theme}`);
    await editor.getByRole('button', { name: 'Guardar orígenes y generar la llave' }).click();
    await expect(editor.getByRole('status')).toContainText('Orígenes guardados');
    const puts = calls.filter((call) => call.method === 'PUT');
    expect(puts).toHaveLength(2);
    expect((puts[1]!.body as { origins: unknown[]; replace_existing: boolean }).origins).toHaveLength(4);
    expect((puts[1]!.body as { replace_existing: boolean }).replace_existing).toBe(false);
  });

  test('publicado: vista previa por plaza, 409 pide otra vista previa y confirmar llena la llave', async ({ page }, info) => {
    const calls = await installContract(page, 'published');
    await openTournament(page);
    const panel = page.locator('section.stage-resolution');
    await expect(panel.getByRole('heading', { name: 'Resolución de las plazas · Eliminatoria' })).toBeVisible();
    await expect(panel.locator('tbody tr')).toHaveCount(4);
    await expect(panel.locator('tbody tr').first()).toContainText('1.º del grupo A');
    await expect(panel.locator('tbody tr').first()).toContainText('Equipo 1');
    await assertNoDocumentOverflow(page);
    await auditTheme(page, info, `stage-resolution-${width}-${theme}`);
    await panel.getByRole('button', { name: 'Confirmar y llenar la llave' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Confirmar', exact: true }).click();
    await expect(panel.getByRole('alert')).toContainText('La clasificación cambió desde la vista previa');
    await expect.poll(() => calls.filter((call) => call.path.endsWith('/resolution/preview')).length).toBe(2);
    await panel.getByRole('button', { name: 'Confirmar y llenar la llave' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Confirmar', exact: true }).click();
    await expect(panel.getByRole('status').first()).toContainText('ya están llenas');
    const posts = calls.filter((call) => call.method === 'POST');
    expect(posts.map((call) => call.body)).toEqual([{ fingerprint: FINGERPRINT }, { fingerprint: FINGERPRINT }]);
  });
});
