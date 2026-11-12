import { randomUUID } from 'node:crypto';
import { expect, test, type Page } from '@playwright/test';
import { demoApiBase, demoCredentials, discoverDemoData } from './demo.ts';
import { ensureWorkspaceSession, signIn, waitForHydration } from './workspaceSession.ts';

test.use({ actionTimeout: 15_000 });

interface PublicMatch {
  id: string;
  status: string;
  home_team_id: string;
  home_team_name: string;
  away_team_name: string;
  home_score: number;
  away_score: number;
  rectified_at: string | null;
}
interface Member { email: string; is_active: boolean; role_code: string }
interface ReportEvent { event_type: string; team_id: string; player_id: string; segment_id: string; minute: number }
interface ReportVersion { version_number: number; report: { events: ReportEvent[] } }
interface Rectification { id: string; reason: string; base_version_number: number; status: 'pending' | 'published' | 'withdrawn' | 'rejected' }
const ownedRequests = new WeakMap<Page, Rectification>();

async function read<T>(page: Page, path: string): Promise<T> {
  const organization = (await page.context().cookies()).find((cookie) => cookie.name === 'bc_organization_id');
  expect(organization, 'use the Workspace organization from its storageState').toBeDefined();
  const response = await page.request.get(`${demoApiBase()}${path}`, {
    headers: { 'X-Organization-ID': decodeURIComponent(organization!.value) },
  });
  expect(response.status(), path).toBe(200);
  return await response.json() as T;
}

async function requestCorrection(page: Page) {
  await ensureWorkspaceSession(page);
  const members = await read<Member[]>(page, '/organizations/members');
  const approver = members.find((member) => member.is_active && member.role_code === 'administrator');
  expect(approver, 'seed_demo must provide a second member with approval permission').toBeDefined();
  const { tournamentId } = await discoverDemoData();
  const matches = await read<PublicMatch[]>(page, `/tournaments/public/${tournamentId}/matches`);
  const match = matches.find((row) => row.status === 'finished' && row.home_score > row.away_score);
  expect(match, 'seed_demo must provide a finished home-winning quarterfinal').toBeDefined();
  const versions = await read<ReportVersion[]>(page, `/matches/${match!.id}/report-versions`);
  const current = versions.reduce((left, right) => left.version_number > right.version_number ? left : right);
  const scorer = current.report.events.find((event) => event.event_type === 'goal' && event.team_id === match!.home_team_id && event.player_id);
  expect(scorer).toBeDefined();
  const reason = `Corrección del acta demo ${randomUUID()}`;
  await page.goto(`/workspace/matches/${match!.id}`);
  await waitForHydration(page);
  await page.getByRole('button', { name: 'Solicitar rectificación', exact: true }).click();
  const editor = page.locator('form.rectification-editor');
  await editor.getByLabel('Goles locales reglamentarios', { exact: true }).fill(String(match!.home_score + 1));
  await editor.getByLabel('Goles locales finales', { exact: true }).fill(String(match!.home_score + 1));
  await editor.getByRole('button', { name: 'Añadir evento', exact: true }).click();
  const event = editor.locator('article').last();
  await event.getByRole('combobox', { name: 'Segmento', exact: true }).selectOption(scorer!.segment_id);
  await event.getByRole('combobox', { name: 'Equipo', exact: true }).selectOption(match!.home_team_id);
  await event.getByRole('combobox', { name: 'Jugador', exact: true }).selectOption(scorer!.player_id!);
  await event.getByLabel('Minuto', { exact: true }).fill(String(scorer!.minute));
  await editor.getByLabel('Motivo de la solicitud', { exact: true }).fill(reason);
  await editor.getByRole('textbox', { name: 'Evidencia', exact: false }).fill('Planilla demo: gol local omitido en el acta.');
  const created = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/matches/${match!.id}/rectifications`));
  await editor.getByRole('button', { name: 'Enviar solicitud', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Enviar solicitud', exact: true }).click();
  const response = await created;
  expect(response.status(), await response.text()).toBe(201);
  const request = await response.json() as Rectification;
  ownedRequests.set(page, request);
  expect(request.base_version_number).toBe(current.version_number);
  return { tournamentId, match: match!, current, versions, request, approver: approver! };
}

async function review(page: Page, reason: string) {
  await page.goto('/workspace/rectifications');
  await waitForHydration(page);
  await page.locator('li').filter({ has: page.getByRole('heading', { name: reason, exact: true }) }).getByRole('button', { name: 'Revisar solicitud', exact: true }).click();
}

async function withdraw(page: Page, request: Rectification) {
  await review(page, request.reason);
  const withdrawn = page.waitForResponse((response) => response.url().endsWith(`/rectifications/${request.id}/withdraw`));
  await page.getByRole('button', { name: 'Retirar solicitud', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Retirar solicitud', exact: true }).click();
  expect((await withdrawn).status()).toBe(200);
}

test.afterEach(async ({ page }) => {
  const request = ownedRequests.get(page);
  if (request && (await read<Rectification>(page, `/rectifications/${request.id}`)).status === 'pending') await withdraw(page, request);
});

test('solicitud real, preview de otro miembro, publicación y resultado público vigente', async ({ page, browser, baseURL }) => {
  const data = await requestCorrection(page);
  const before = await read<PublicMatch[]>(page, `/tournaments/public/${data.tournamentId}/matches`);
  expect(before.find((row) => row.id === data.match.id)).toEqual(data.match);
  const origin = baseURL ?? 'http://localhost:3000';
  const context = await browser.newContext({ baseURL: origin, storageState: { cookies: [], origins: [] } });
  try {
    await context.addCookies([{ name: 'bc_locale', value: 'es', url: origin }]);
    const approver = await context.newPage();
    await signIn(approver, { email: data.approver.email, password: demoCredentials().password });
    await review(approver, data.request.reason);
    const approve = approver.getByRole('button', { name: 'Aprobar y publicar', exact: true });
    await expect(approve).toBeDisabled();
    await approver.getByLabel('Motivo de la decisión (obligatorio)', { exact: true }).fill('Planilla revisada por otro miembro.');
    const previewed = approver.waitForResponse((response) => response.url().endsWith(`/rectifications/${data.request.id}/preview`));
    await approver.getByRole('button', { name: 'Calcular vista previa de efectos', exact: true }).click();
    const preview = await previewed;
    expect(preview.status(), await preview.text()).toBe(200);
    expect((await preview.json()).expected_base_version).toBe(data.current.version_number);
    expect(await read<ReportVersion[]>(page, `/matches/${data.match.id}/report-versions`)).toEqual(data.versions);
    const published = approver.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/rectifications/${data.request.id}/decision`));
    await approve.click();
    await approver.getByRole('dialog').getByRole('button', { name: 'Aprobar y publicar', exact: true }).click();
    const decision = await published;
    expect(decision.status()).toBe(200);
    expect(decision.request().postDataJSON().expected_base_version).toBe(data.current.version_number);
    expect((await decision.json()).status).toBe('published');
    const versions = await read<ReportVersion[]>(page, `/matches/${data.match.id}/report-versions`);
    for (const original of data.versions) expect(versions.find((version) => version.version_number === original.version_number)).toEqual(original);
    expect(versions).toHaveLength(data.versions.length + 1);
    await context.clearCookies();
    await approver.goto(`/tournaments/${data.tournamentId}`);
    await waitForHydration(approver);
    const card = approver.locator(`.bracket-match[data-match-id="${data.match.id}"]`);
    await expect(card.getByText('Resultado rectificado', { exact: false })).toBeVisible();
    const publicResponse = await context.request.get(`${demoApiBase()}/tournaments/public/${data.tournamentId}/matches`);
    expect(publicResponse.status()).toBe(200);
    const current = (await publicResponse.json() as PublicMatch[]).find((row) => row.id === data.match.id)!;
    expect(current.home_score).toBe(data.match.home_score + 1);
    expect(current.rectified_at).toBeTruthy();
    await expect(card.locator('time')).toHaveAttribute('datetime', current.rectified_at!);
    await expect(card.locator('.bracket-team').first().locator('strong')).toHaveText(String(current.home_score));
    await expect(card).not.toContainText(data.request.reason);
    await expect(card).not.toContainText('Planilla demo');
  } finally { await context.close(); }
});

test('el solicitante no ve las decisiones aunque sea owner y puede retirar', async ({ page }) => {
  const data = await requestCorrection(page);
  await review(page, data.request.reason);
  await expect(page.getByRole('button', { name: 'Retirar solicitud', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Aprobar y publicar', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Rechazar solicitud', exact: true })).toHaveCount(0);
  await withdraw(page, data.request);
  expect(await read<ReportVersion[]>(page, `/matches/${data.match.id}/report-versions`)).toEqual(data.versions);
});
