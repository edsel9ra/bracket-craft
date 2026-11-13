import { expect, test } from '@playwright/test';
import { SanctionPlatformFixture, openPlatformFixture } from './sanctionPlatformFixtures.ts';
import { demoApiBase, discoverDemoData } from './demo.ts';

test.use({ storageState: { cookies: [], origins: [] }, trace: 'off', video: 'off' });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

test('platform without membership only sees F9 scopes, previews and consumes authorization once', async ({ page }) => {
  const fixture = new SanctionPlatformFixture(); await openPlatformFixture(page, fixture);
  const id = fixture.cases[0]!.case.id;
  await expect(page.getByRole('button', { name: `Ver expediente ${fixture.cases[1]!.case.id}`, exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: `Ver expediente ${id}`, exact: true }).click();
  await expect(page.getByText('PRIVATE EVIDENCE F9', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Presentar apelación|Proponer resolución administrativa|Retirar expediente/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Previsualizar decisión', exact: true }).click();
  await page.locator('form').getByLabel('Motivo obligatorio', { exact: true }).fill('Decisión excepcional auditada');
  await page.getByRole('button', { name: 'Registrar decisión', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Registrar decisión', exact: true }).click();
  await expect(page.getByText('Estado actualizado.', { exact: true })).toBeVisible();
  await expect(page.locator('article')).toHaveCount(0);
  await expect(page.getByText('No hay expedientes con estos filtros.', { exact: true })).toBeVisible();
  expect(fixture.authorized.has(id)).toBe(false);
  expect(fixture.platformRequests.filter(row => row.method === 'POST')).toEqual([{ path: `/platform/sanction-cases/${id}/decision`, method: 'POST' }]);
});

test('revocation between preview and decision removes private detail and does not execute', async ({ page }) => {
  const fixture = new SanctionPlatformFixture(); await openPlatformFixture(page, fixture);
  await page.getByRole('button', { name: `Ver expediente ${fixture.cases[0]!.case.id}`, exact: true }).click();
  await page.getByRole('button', { name: 'Previsualizar decisión', exact: true }).click();
  fixture.authorized.clear();
  await page.locator('form').getByLabel('Motivo obligatorio', { exact: true }).fill('No autorizado');
  await page.getByRole('button', { name: 'Registrar decisión', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Registrar decisión', exact: true }).click();
  await expect(page.getByText('PRIVATE EVIDENCE F9', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Expediente no disponible.', { exact: true })).toBeVisible();
  expect(fixture.cases[0]!.case.status).toBe('pending');
});

test('self-decision is unavailable, empty scopes and list errors remain retryable', async ({ page }) => {
  const fixture = new SanctionPlatformFixture(); fixture.authorized.clear(); fixture.authorized.add(fixture.cases[2]!.case.id);
  await openPlatformFixture(page, fixture);
  await page.getByRole('button', { name: `Ver expediente ${fixture.cases[2]!.case.id}`, exact: true }).click();
  await expect(page.getByRole('button', { name: 'Previsualizar decisión', exact: true })).toHaveCount(0);
  fixture.failList = true; await page.getByRole('button', { name: 'Actualizar', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.locator('article')).toHaveCount(0);
  fixture.failList = false; fixture.authorized.clear(); await page.getByRole('button', { name: 'Reintentar', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(fixture.platformRequests.filter(row => row.method === 'POST')).toEqual([]);
});

test('anonymous live public projections contain no F9 data and reject private reads', async ({ request }) => {
  const { tournamentId } = await discoverDemoData();
  const forbidden = new Set(['sanctions', 'suspensions', 'sanction_cases', 'case_id', 'evidence_text', 'evidence_links', 'matches_suspended', 'resolution_reason', 'decided_by_user_id', 'prejudice']);
  function inspect(value: unknown) {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) { expect(forbidden.has(key), `private key ${key}`).toBe(false); inspect(child); }
  }
  for (const suffix of ['', '/matches', '/standings', '/player-stats', '/team-stats']) {
    const response = await request.get(`${demoApiBase()}/tournaments/public/${tournamentId}${suffix}`);
    expect(response.status()).toBe(200); inspect(await response.json());
  }
  for (const path of ['/sanction-cases', '/platform/sanction-cases', '/sanction-notifications']) {
    const response = await request.get(`${demoApiBase()}${path}`); expect([401, 403]).toContain(response.status());
  }
});
