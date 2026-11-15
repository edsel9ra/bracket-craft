/**
 * Escenario de operación y cierre (spec 012, H4-T10; RF-043, RF-045, RF-050,
 * RF-051, RF-012, RNF-005, RNF-008).
 *
 * Proyecto y veredicto propios: no ejecuta ni modifica el escenario de reintento
 * (`realtime-*.spec.ts`), sus localizadores ni su traducción 0/1/2/3. El
 * escenario descubre el torneo demo por la API pública y recorre la interfaz con
 * localizadores accesibles; deja `view-operation-flow.json`, su traza y, solo en
 * fallo, una captura.
 */

import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import { reportPath } from './artifacts.ts';
import { discoverDemoData } from './demo.ts';
import { runOperationFlow } from './operationFlow.ts';
import { OPERATION_FLOW_VIEW, isOperationFlowArtifact } from './operationFlowModel.ts';

test('operación y cierre: reglas, avisos, bloqueos y retiro lógico', async ({ page, baseURL }) => {
  // Las corridas realtime siembran organizaciones completas con su «Copa
  // Demo»: el descubridor público puede elegir un torneo ajeno que el
  // Workspace nunca lista. Se filtra por los torneos del usuario autenticado.
  const organizationId = (await page.context().cookies(baseURL ?? 'http://localhost:3000'))
    .find(cookie => cookie.name === 'bc_organization_id')?.value;
  const owned = new Set<string>();
  for (let offset = 0; ; offset += 50) {
    const response = await page.context().request.get(
      `${demoApiBase()}/tournaments?limit=50&offset=${offset}`,
      { headers: { 'X-Organization-ID': organizationId ?? '' } },
    );
    if (!response.ok()) break;
    const rows = await response.json() as Array<{ id: string }>;
    for (const row of rows) owned.add(row.id);
    if (rows.length < 50) break;
  }
  const { tournamentId } = await discoverDemoData({ ownedTournamentIds: owned });
  const result = await runOperationFlow({ page, tournamentId });

  expect(result.artifact.schemaVersion).toBe(1);
  expect(result.artifact.view).toBe(OPERATION_FLOW_VIEW);
  expect(result.artifact.verdict).toBe('passed');
  expect(result.artifact.cause).toBeNull();
  expect(result.artifact.states.length).toBeGreaterThan(0);
  expect(result.artifact.transitions).toBe(result.artifact.states.length - 1);

  const raw = JSON.parse(
    readFileSync(reportPath(`view-${OPERATION_FLOW_VIEW}.json`), 'utf8'),
  ) as unknown;
  expect(isOperationFlowArtifact(raw)).toBe(true);
  expect(raw).toEqual(result.artifact);

  const serialized = JSON.stringify(result.artifact);
  expect(serialized).not.toContain('Cookie');
  expect(serialized).not.toContain('Authorization');

  console.log(
    `[operation-flow] hitos: ${result.artifact.states.map((state) => state.status).join(' → ')}`,
  );
});

/**
 * Recorrido F1 (spec 036, T73): provisional → suspensión → cierre con recibo.
 *
 * Cubre el recorrido real con la misma pila Compose: un operador gobierna el
 * borrador compartido por HTTP, dos lectores lo ven actualizarse sin refrescar
 * y un espectador anónimo recibe solo el contrato público (tarjeta suspendida,
 * nunca el borrador). Los comandos van por la API autenticada y las vistas se
 * verifican por realtime: no hay recarga manual ni efectos adelantados.
 *
 * Escenarios: (a) recorrido normal con hechos, corrección y rechazo 422 de un
 * hecho inválido; (b) borrador vacío válido: revisión y cierre sin hechos.
 */
import { randomUUID } from 'node:crypto';

import { demoApiBase } from './demo.ts';
import { control, http, login, type Tenant } from './realtimeHarness.ts';
import { waitForHydration } from './workspaceSession.ts';

const api = demoApiBase();
const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:3000';

interface LiveSnap {
  initialized: boolean; status: string;
  revision: number | null; content_revision: number | null;
  home_score: number | null; away_score: number | null;
  events: Array<Record<string, unknown>>;
}

async function liveSnapshot(context: Parameters<typeof http>[0], tenant: Tenant, matchId: string) {
  return await http<LiveSnap>(context, tenant, `/matches/${matchId}/live`);
}
async function liveCommand(context: Parameters<typeof http>[0], tenant: Tenant, matchId: string, body: Record<string, unknown>) {
  return await http<{ command_id: string; revision: number }>(context, tenant, `/matches/${matchId}/live/commands`, body);
}
async function rawPost(context: Parameters<typeof http>[0], tenant: Tenant, path: string, body: Record<string, unknown>) {
  const headers: Record<string, string> = { 'X-Organization-ID': tenant.organization_id, Origin: baseURL };
  await context.request.get(`${api}/auth/csrf`);
  const cookie = (await context.cookies()).find(row => row.name === 'bc_csrf_token');
  expect(cookie).toBeDefined();
  headers['X-CSRF-Token'] = decodeURIComponent(cookie!.value);
  return await context.request.post(`${api}${path}`, { headers, data: body });
}
async function liveReview(context: Parameters<typeof http>[0], tenant: Tenant, matchId: string, contentRevision: number, result: Record<string, unknown>) {
  const response = await rawPost(context, tenant, `/matches/${matchId}/live/reviews`, {
    expected_content_revision: contentRevision, result,
  });
  if (!response.ok()) console.log('[live-review]', response.status(), JSON.stringify(await response.json()));
  expect(response.ok(), `live review: ${await response.text()}`).toBe(true);
  return await response.json() as { live_review_id: string; content_revision: number };
}

async function openMatchView(context: Parameters<typeof login>[1] extends never ? never : import('@playwright/test').BrowserContext, tenant: Tenant, matchId: string, publicPage = false) {
  const page = await context.newPage();
  await page.goto(publicPage ? `/tournaments/${tenant.tournament_id}` : `/workspace/matches/${matchId}`);
  await waitForHydration(page);
  return page;
}

test('F1: provisional → suspensión → reanudación → revisión → cierre con recibo', async ({ browser }) => {
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  await control({ action: 'prepare_open', organization_id: tenant.organization_id });
  const matchId = tenant.open_match_id;
  const operator = await login(browser, tenant);
  const readerA = await login(browser, tenant, true);
  const readerB = await login(browser, tenant, true);
  const spectator = await browser.newContext();
  try {
    const operation = await http<{ match: { home_team_id: string; away_team_id: string }; segments: Array<{ id: string; status: string }>; rosters: Array<{ player_id: string; team_id: string }> }>(
      operator, tenant, `/matches/${matchId}/operation`);
    const segment = operation.segments.find(row => row.status === 'active');
    expect(segment).toBeDefined();
    const home = operation.match.home_team_id;
    const player = operation.rosters.find(row => row.team_id === home);
    expect(player).toBeDefined();

    const pages = await Promise.all([
      openMatchView(operator, tenant, matchId),
      openMatchView(readerA, tenant, matchId),
      openMatchView(readerB, tenant, matchId),
      openMatchView(spectator, tenant, matchId, true),
    ]);
    const [operatorPage, readerPageA, readerPageB, publicPage] = pages;
    await expect(operatorPage.getByRole('heading', { name: 'Partido en vivo', exact: true })).toBeVisible();

    // Inicio provisional: revision 0 → live.
    let snap = await liveSnapshot(operator, tenant, matchId);
    expect(snap.initialized).toBe(false);
    const started = await liveCommand(operator, tenant, matchId, {
      command_id: randomUUID(), type: 'start', expected_revision: 0,
    });
    expect(started.revision).toBeGreaterThan(0);
    for (const page of [operatorPage, readerPageA, readerPageB]) {
      await expect(page.getByText('En vivo', { exact: true })).toBeVisible();
    }

    // Reloj y hechos: gol válido, hecho inválido rechazado (422 sin escribir).
    let revision = started.revision;
    const clocked = await liveCommand(operator, tenant, matchId, {
      command_id: randomUUID(), type: 'start_clock', expected_revision: revision, segment_id: segment!.id,
    });
    revision = clocked.revision;
    const rejected = await rawPost(operator, tenant, `/matches/${matchId}/live/commands`, {
      command_id: randomUUID(), type: 'add_event', expected_revision: revision,
      event: { client_event_id: randomUUID(), event_type: 'goal', team_id: home, player_id: null, minute: 5, added_minute: 0, segment_id: segment!.id, metadata: null },
    });
    expect(rejected.status()).toBe(422);
    const afterReject = await liveSnapshot(operator, tenant, matchId);
    expect(afterReject.revision).toBe(revision);
    expect(afterReject.home_score).toBe(0);

    const goal = await liveCommand(operator, tenant, matchId, {
      command_id: randomUUID(), type: 'add_event', expected_revision: revision,
      event: { client_event_id: randomUUID(), event_type: 'goal', team_id: home, player_id: player!.player_id, minute: 5, added_minute: 0, segment_id: segment!.id, metadata: null },
    });
    revision = goal.revision;
    for (const page of [operatorPage, readerPageA, readerPageB]) {
      await expect(page.locator('.live-events li').getByText('Gol · 5\'', { exact: false }).first()).toBeVisible();
    }

    // Suspensión: el espectador ve solo la tarjeta mínima, nunca el borrador.
    const suspended = await liveCommand(operator, tenant, matchId, {
      command_id: randomUUID(), type: 'suspend', expected_revision: revision,
    });
    revision = suspended.revision;
    for (const page of [operatorPage, readerPageA, readerPageB]) {
      await expect(page.getByText('Suspendido', { exact: true })).toBeVisible();
    }
    await expect(publicPage.getByText('Suspendido', { exact: true }).first()).toBeVisible();
    await expect(publicPage.getByText('Partido en vivo', { exact: true })).toHaveCount(0);

    // Reanudación, revisión del conjunto y cierre con recibo.
    const resumed = await liveCommand(operator, tenant, matchId, {
      command_id: randomUUID(), type: 'resume', expected_revision: revision,
    });
    revision = resumed.revision;
    snap = await liveSnapshot(operator, tenant, matchId);
    const receipt = await liveReview(operator, tenant, matchId, snap.content_revision!, {
      resolution_type: 'regular', home_score_regular: 1, away_score_regular: 0,
      home_score: 1, away_score: 0, winner_team_id: home,
    });
    expect(receipt.content_revision).toBe(snap.content_revision!);
    // La respuesta 201 de la revisión puede llegar antes del commit de su
    // transacción: un cierre inmediato compite con ella y responde
    // LIVE_REVIEW_STALE. Reintentar con el mismo live_review_id es el
    // comportamiento idempotente esperado de un cliente real.
    await expect.poll(async () => {
      const closed = await rawPost(operator, tenant, `/matches/${matchId}/close`, {
        resolution_type: 'regular', home_score_regular: 1, away_score_regular: 0,
        home_score: 1, away_score: 0, winner_team_id: home, live_review_id: receipt.live_review_id,
      });
      return closed.status();
    }, { timeout: 10_000, message: 'close con recibo debe converger a 200' }).toBe(200);
    for (const page of [operatorPage, readerPageA, readerPageB]) {
      await expect(page.getByText('Finalizado', { exact: true }).first()).toBeVisible();
    }
    console.log('[operation-flow] F1 normal: start→clock→goal→suspend→resume→review→close con recibo');
  } finally {
    await Promise.all([operator.close(), readerA.close(), readerB.close(), spectator.close()]);
  }
});

test('F1: borrador vacío válido — revisión y cierre sin hechos', async ({ browser }) => {
  const [tenant] = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  await control({ action: 'prepare_open', organization_id: tenant.organization_id });
  const matchId = tenant.open_match_id;
  const operator = await login(browser, tenant);
  try {
    const operation = await http<{ match: { home_team_id: string; away_team_id: string } }>(operator, tenant, `/matches/${matchId}/operation`);
    const home = operation.match.home_team_id;
    const started = await liveCommand(operator, tenant, matchId, {
      command_id: randomUUID(), type: 'start', expected_revision: 0,
    });
    expect(started.revision).toBe(1);
    const snap = await liveSnapshot(operator, tenant, matchId);
    expect(snap.initialized).toBe(true);
    expect(snap.content_revision).toBe(0);
    const receipt = await liveReview(operator, tenant, matchId, 0, {
      resolution_type: 'walkover', winner_team_id: home, reason: 'no_show',
    });
    await expect.poll(async () => {
      const closed = await rawPost(operator, tenant, `/matches/${matchId}/close`, {
        resolution_type: 'walkover', winner_team_id: home, reason: 'no_show',
        live_review_id: receipt.live_review_id,
      });
      return closed.status();
    }, { timeout: 10_000, message: 'close con recibo debe converger a 200' }).toBe(200);
    console.log('[operation-flow] F1 vacío: revisión y cierre sin hechos');
  } finally { await operator.close(); }
});
