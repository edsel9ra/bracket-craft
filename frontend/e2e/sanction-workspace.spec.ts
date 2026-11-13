import { expect, test, type Page } from '@playwright/test';
import { SanctionFixture, openFixture, navigateFixture } from './sanctionFixtures.ts';

test.use({ actionTimeout: 15_000, trace: 'off', video: 'off', storageState: { cookies: [], origins: [] } });
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

function section(page: Page, title: string) { return page.locator('section').filter({ has: page.getByRole('heading', { name: title, exact: true }) }).last(); }
async function confirm(page: Page, verb: string) { await page.getByRole('dialog').getByRole('button', { name: verb, exact: true }).click(); }
async function review(page: Page, id: string) { await page.getByRole('button', { name: `Ver expediente ${id}`, exact: true }).click(); await expect(page.locator('article').filter({ hasText: id })).toBeVisible(); }
async function appeal(page: Page, source: string, player: string, reason: string) {
  const form = section(page, 'Presentar apelación');
  await form.getByLabel('Identificador de sanción', { exact: true }).fill(source);
  await form.getByLabel('Identificador del jugador o equipo representado', { exact: true }).fill(player);
  await form.getByLabel('Motivo obligatorio', { exact: true }).fill(reason);
  await form.getByLabel('Texto de evidencia (opcional)', { exact: true }).fill('PRIVATE EVIDENCE 034');
  await form.getByRole('button', { name: 'Presentar apelación', exact: true }).click(); await confirm(page, 'Presentar apelación');
}

test('two people: appeal, self-decision prohibition and pending versus applied effect', async ({ page, browser }) => {
  const fixture = new SanctionFixture();
  await openFixture(page, fixture, 'author');
  await appeal(page, fixture.sources[0]!.id, fixture.player, 'Revisar sanción 034');
  await expect.poll(() => fixture.cases.length).toBe(1);
  const id = fixture.cases[0]!.case.id;
  await review(page, id);
  await expect(page.getByRole('button', { name: 'Previsualizar decisión', exact: true })).toHaveCount(0);
  await expect(page.getByText('PRIVATE EVIDENCE 034', { exact: true })).toBeVisible();
  const second = await browser.newContext({ baseURL: new URL(page.url()).origin, storageState: { cookies: [], origins: [] } });
  try {
    const reviewer = await second.newPage(); await openFixture(reviewer, fixture, 'reviewer'); await review(reviewer, id);
    await expect(reviewer.getByRole('button', { name: 'Retirar expediente', exact: true })).toHaveCount(0);
    await reviewer.getByRole('button', { name: 'Previsualizar decisión', exact: true }).click();
    const decision = section(reviewer, 'Registrar decisión');
    await decision.getByRole('combobox', { name: 'Registrar decisión', exact: true }).selectOption('annul');
    await decision.getByLabel('Motivo obligatorio', { exact: true }).fill('Anulación auditada');
    await decision.getByRole('button', { name: 'Registrar decisión', exact: true }).click(); await confirm(reviewer, 'Registrar decisión');
    await expect(reviewer.getByText(/Resolución registrada, pendiente de aplicación/).first()).toBeVisible();
    expect(fixture.cases[0]!.projection.effective_duration).toBe(3);
    fixture.apply(id);
    await reviewer.getByRole('combobox', { name: 'Estado del expediente', exact: true }).selectOption('');
    await reviewer.getByRole('button', { name: 'Actualizar', exact: true }).click(); await review(reviewer, id);
    await expect(reviewer.getByText(/Aplicada en la apertura/)).toBeVisible();
    expect(fixture.cases[0]!.projection.effective_duration).toBe(0);
    await navigateFixture(reviewer, '/workspace/sanction-notifications');
    await expect(reviewer.getByText('Anulación auditada', { exact: true })).toBeVisible();
    await expect(reviewer.getByText('PRIVATE EVIDENCE 034', { exact: true })).toHaveCount(0);
  } finally { await second.close(); }
});

test('proposal without effect, author withdrawal and manual linked submission after rectification', async ({ page }) => {
  const fixture = new SanctionFixture(); await openFixture(page, fixture, 'author');
  const form = section(page, 'Proponer resolución administrativa');
  await form.getByLabel('Identificador de sanción', { exact: true }).fill(fixture.sources[1]!.id);
  await form.getByRole('combobox', { name: 'Medida propuesta', exact: true }).selectOption('reduce');
  await form.getByLabel('Nueva duración en partidos', { exact: true }).fill('1');
  await form.getByLabel('Motivo obligatorio', { exact: true }).fill('Propuesta pendiente');
  await form.getByRole('button', { name: 'Proponer resolución administrativa', exact: true }).click(); await confirm(page, 'Proponer resolución administrativa');
  await expect.poll(() => fixture.cases.length).toBe(1);
  const id = fixture.cases[0]!.case.id; expect(fixture.cases[0]!.projection.effective_duration).toBe(3);
  await review(page, id);
  const withdrawal = section(page, 'Retirar expediente'); await withdrawal.getByLabel('Motivo obligatorio', { exact: true }).fill('Retirada por autor');
  await withdrawal.getByRole('button', { name: 'Retirar expediente', exact: true }).click(); await confirm(page, 'Retirar expediente');
  await expect.poll(() => fixture.cases[0]!.case.status).toBe('withdrawn');
  await appeal(page, fixture.sources[0]!.id, fixture.player, 'Afectada por 033'); await expect.poll(() => fixture.cases.length).toBe(2);
  const corrected = fixture.cases[1]!.case.id; fixture.rectify(corrected);
  await page.getByRole('combobox', { name: 'Estado del expediente', exact: true }).selectOption('');
  await page.getByRole('button', { name: 'Actualizar', exact: true }).click(); await review(page, corrected);
  await page.getByRole('button', { name: 'Preparar nueva presentación vinculada', exact: true }).click();
  await expect(section(page, 'Presentar apelación').getByLabel('Expediente antecedente (opcional)', { exact: true })).toHaveValue(corrected);
  expect(fixture.cases.length).toBe(2);
});

test('tenant switch clears private detail; recipient-only notice does not confer consultation', async ({ page }) => {
  const fixture = new SanctionFixture(); await openFixture(page, fixture, 'author');
  await appeal(page, fixture.sources[0]!.id, fixture.player, 'Solo organización A'); await expect.poll(() => fixture.cases.length).toBe(1);
  const id = fixture.cases[0]!.case.id; await review(page, id);
  await page.getByRole('combobox', { name: 'Organización activa', exact: true }).first().selectOption(fixture.otherOrg);
  await expect(page).toHaveURL(/\/workspace$/); await navigateFixture(page, `/workspace/sanctions?case=${id}`);
  await expect(page.getByText('PRIVATE EVIDENCE 034', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Expediente no disponible.', { exact: false })).toBeVisible();
  await page.getByRole('combobox', { name: 'Organización activa', exact: true }).first().selectOption(fixture.org);
  await expect(page).toHaveURL(/\/workspace$/); fixture.authorCanView = false;
  fixture.notice('Notice for recipient without VIEW'); await navigateFixture(page, '/workspace/sanction-notifications');
  await expect(page.getByText('Notice for recipient without VIEW', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ver expediente', exact: true })).toHaveCount(0);
  expect(fixture.requests.filter((row) => row.path.startsWith('/sanction-cases/') && row.org === fixture.otherOrg).length).toBeGreaterThan(0);
});

test('private lineup warning, including failure, never blocks saving or publishing a formation', async ({ page }) => {
  const fixture = new SanctionFixture(); await openFixture(page, fixture, 'author');
  await navigateFixture(page, `/workspace/matches/${fixture.matchId}`);
  await expect(page.getByRole('heading', { name: 'Aviso privado de sanciones', exact: true })).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Jugador 034' })).toBeVisible();
  const save = page.locator('#seccion-planilla').getByRole('button', { name: 'Guardar planilla', exact: true });
  await expect(save).toBeEnabled(); await save.click(); await expect.poll(() => fixture.saves).toBe(1);
  const publish = page.getByRole('button', { name: 'Publicar formación', exact: true }).first();
  await expect(publish).toBeEnabled(); await publish.click(); await expect.poll(() => fixture.publications).toBe(1);
  fixture.warningFails = true; await navigateFixture(page, '/workspace/sanctions'); await navigateFixture(page, `/workspace/matches/${fixture.matchId}`);
  await expect(page.getByText(/No se pudo consultar el aviso/)).toBeVisible();
  await expect(save).toBeEnabled(); await save.click(); await expect.poll(() => fixture.saves).toBe(2);
  expect(fixture.lastLineup).not.toHaveProperty('sanctions'); expect(fixture.lastLineup).not.toHaveProperty('warnings');
});
