/**
 * Vista pública del torneo: escenario determinista del reintento manual
 * (RF-001, RF-002, RF-006, RNF-001).
 *
 * El escenario compartido (`realtimeScenario.ts`) es el que bloquea el canal,
 * provoca el error sobre el transporte real, pulsa «Reintentar» con el canal
 * todavía bloqueado y observa el estado manual de producto, la vuelta a error,
 * el desbloqueo y la reconexión. Aquí solo se declara la vista y se comprueba
 * el artefacto que deja la corrida.
 *
 * Un estado manual ausente después del clic es un **fallo de comportamiento**;
 * una corrida sin error previo o con el canal sin bloquear es **inválida** y su
 * causa viaja en el artefacto (nunca se declara verde).
 */

import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import { reportPath, type ViewArtifact } from './artifacts.ts';
import { demoApiBase, discoverDemoData } from './demo.ts';
import { control, login, rectify, type Tenant } from './realtimeHarness.ts';
import { REALTIME_STATUS_TEXT, labelText } from './labels.ts';
import { VIEWS } from './observations.ts';
import { runRealtimeScenario } from './realtimeScenario.ts';

test('035 public matrix preserves anonymous HTTP and rooms while excluding private variants F1 F9 and probes', async ({ browser }) => {
  const tenants = await control<[Tenant, Tenant]>({ action: 'bootstrap' });
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const owner = await login(browser, tenants[0]);
  const reviewer = await login(browser, tenants[0], true);
  try {
    await rectify(owner, reviewer, tenants[0]);
    const views = await Promise.all([...tenants, tenants[0]].map(async (tenant, index) => {
      const page = await (index === 2 ? owner : context).newPage();
      const wire: Array<{ event: string; payload: Record<string, unknown> }> = [];
      page.on('websocket', socket => socket.on('framereceived', frame => {
        const packet = frame.payload.toString();
        if (packet.startsWith('42')) {
          const [event, payload] = JSON.parse(packet.slice(2)) as [string, Record<string, unknown>];
          wire.push({ event, payload });
        }
      }));
      await page.goto(index === 2 ? `/workspace/matches/${tenant.match_id}` : `/tournaments/${tenant.tournament_id}`);
      await expect.poll(() => wire.some(row => row.event === 'RESYNC')).toBe(true);
      if (index === 2) await expect(page.getByRole('heading', { name: 'Versiones del acta', exact: true }).locator('..').locator('select').first()).toHaveValue('2');
      return { page, wire };
    }));
    const paths = ['', '/standings', '/matches', '/player-stats', '/team-stats'];
    const snapshot = async () => await Promise.all(paths.map(async path => {
      const response = await context.request.get(`${demoApiBase()}/tournaments/public/${tenants[0].tournament_id}${path}`);
      expect(response.status()).toBe(200);
      return await response.json() as unknown;
    }));
    const before = await snapshot();
    const forbidden = /"(?:document_number|birth_date|birth_date_encrypted|age|public_age|evidence|reason|administrative_audit_logs|organization_id|user_id)"\s*:/;
    expect(JSON.stringify(before)).not.toMatch(forbidden);
    for (const event_type of ['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED']) {
      const event = await control<{ event_id: string }>({ action: 'publish', organization_id: tenants[0].organization_id, event_type });
      await expect.poll(() => views[0]!.wire.some(row => row.payload.event_id === event.event_id)).toBe(true);
      expect(views[0]!.wire.find(row => row.payload.event_id === event.event_id)).toEqual({ event: event_type,
        payload: { event_id: event.event_id, match_id: tenants[0].match_id, tournament_id: tenants[0].tournament_id } });
      expect(views[1]!.wire.some(row => row.payload.event_id === event.event_id)).toBe(false);
    }
    const excluded: string[] = [];
    for (const event_type of ['MATCH_UPDATED', 'STANDINGS_UPDATED', 'MATCH_REPORT_RECTIFIED']) {
      const event = await control<{ event_id: string }>({ action: 'publish', organization_id: tenants[0].organization_id,
        event_type, private: true });
      await expect.poll(() => views[2]!.wire.some(row => row.payload.event_id === event.event_id)).toBe(true);
      for (const view of views.slice(0, 2)) expect(view.wire.some(row => row.payload.event_id === event.event_id)).toBe(false);
    }
    for (const event_type of ['MATCH_DRAFT_UPDATED', 'SANCTION_CASE_NOTICE_INTERNAL', 'SANCTION_CASE_NOTICE_EMAIL',
      'RECTIFICATION_DECISION_EMAIL', 'UNKNOWN']) {
      excluded.push((await control<{ event_id: string }>({ action: 'inject', organization_id: tenants[0].organization_id,
        event_type, payload: { document_number: 'TEST_ONLY', birth_date: '2000-01-01', age: 26,
          evidence: 'TEST_ONLY', reason: 'TEST_ONLY', administrative_audit_logs: [] } })).event_id);
    }
    const probe = await control<{ event_id: string }>({ action: 'publish', organization_id: tenants[0].organization_id,
      event_type: 'VERIFICATION_OUTBOX_PROBE' });
    excluded.push(probe.event_id);
    await expect.poll(async () => (await control<{ delivered: string[] }>({ action: 'probe' })).delivered.includes(probe.event_id)).toBe(true);
    expect(await control({ action: 'outbox_status', organization_id: tenants[0].organization_id, event_id: probe.event_id })).toBe('processed');
    await Promise.all(views.map(view => view.page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))));
    for (const view of views) for (const id of excluded) expect(view.wire.some(row => row.payload.event_id === id)).toBe(false);
    expect(await snapshot()).toEqual(before);
    expect((await context.cookies()).some(cookie => ['bc_access_token', 'bc_refresh_token'].includes(cookie.name))).toBe(false);
  } finally {
    await context.close(); await owner.close(); await reviewer.close();
    await control({ action: 'archive' });
  }
});

test('vista pública: el reintento manual reconecta con el canal bloqueado', async ({
  page,
  context,
  baseURL,
}) => {
  const view = VIEWS.public;
  const ids = await discoverDemoData();

  const result = await runRealtimeScenario({ page, context, view, ids, baseURL });

  // El texto observado es el de producto en español y no el de reconexión
  // automática: el estado manual es distinguible sin mirar el color.
  expect(result.manualText).toBe(labelText(REALTIME_STATUS_TEXT.public.retrying));
  expect(result.manualText).not.toBe(labelText(REALTIME_STATUS_TEXT.public.reconnecting));

  // Dos ciclos de pulsación con su estado manual y su desaparición, en el
  // orden canónico: error < clic < intento < manual < fin del manual.
  expect(result.marks.cycles).toHaveLength(2);
  expect(result.marks.connectedOnceAt).toBeLessThan(result.marks.blockedAt);
  expect(result.marks.blockedAt).toBeLessThan(result.marks.errorVisibleAt);
  for (const cycle of result.marks.cycles) {
    expect(cycle.clickedAt).toBeGreaterThan(result.marks.errorVisibleAt);
    expect(cycle.attemptStartedAt).toBeGreaterThan(cycle.clickedAt);
    expect(cycle.manualVisibleAt).toBeGreaterThan(cycle.attemptStartedAt);
    expect(cycle.manualGoneAt).toBeGreaterThan(cycle.manualVisibleAt);
    expect(cycle.manualGoneAt).toBeLessThan(result.marks.unblockedAt);
  }
  expect(result.marks.unblockedAt).toBeLessThan(result.marks.connectedAt);
  expect(result.marks.connectedAt).toBeLessThan(result.marks.settledAt);

  // Cada ciclo dejó su estado manual en el artefacto, con instante posterior
  // al clic y anterior al desbloqueo.
  const manualCycles = result.states
    .filter((state) => state.status === 'retrying' && state.cycle !== null)
    .map((state) => state.cycle);
  expect([...new Set(manualCycles)].sort()).toEqual([0, 1]);
  for (const state of result.states.filter((sample) => sample.status === 'retrying')) {
    expect(state.at).toBeGreaterThan(result.marks.errorVisibleAt);
    expect(state.at).toBeLessThan(result.marks.unblockedAt);
  }

  // Orden canónico sin violaciones, transporte real y ninguna recarga del
  // documento; como máximo una recarga atribuible del consumidor público.
  expect(result.orderViolations).toEqual([]);
  expect(result.marks.settledAt).toBeGreaterThan(result.marks.connectedAt);
  expect(result.artifact.connections.established).toBe(2);
  // `connections.establishedDuringBlock` se retiró en la corrección de la
  // validación: el interceptor nunca acepta un handshake con el canal bloqueado,
  // así que era un contador estructural que nunca cambiaba. La evidencia real es
  // la ausencia de estado conectado durante el bloqueo, comprobada arriba con
  // las muestras observadas.
  expect(result.artifact.reloads.documentReloads).toBe(0);
  expect(result.artifact.reloads.attributable).toBeLessThanOrEqual(1);
  expect(result.artifact.reloads.duplicates).toBe(0);

  // El estado manual nunca se observó sin una pulsación previa.
  const clicks = result.marks.cycles.map((cycle) => cycle.clickedAt);
  const firstClick = Math.min(...clicks);
  expect(result.states.some((state) => state.status === 'retrying' && state.at < firstClick)).toBe(
    false,
  );
  // Ninguna muestra de conectado posterior al cierre del transporte y anterior
  // al desbloqueo: el canal bloqueado no se recupera solo.
  expect(
    result.states.some(
      (state) =>
        state.status === 'connected' &&
        state.at > result.marks.closedAt &&
        state.at <= result.marks.unblockedAt,
    ),
  ).toBe(false);

  // El artefacto queda en disco, en verde y sin cabeceras sensibles.
  const artifact = JSON.parse(readFileSync(reportPath('view-public.json'), 'utf8')) as ViewArtifact;
  expect(artifact.view).toBe('public');
  expect(artifact.verdict).toBe('passed');
  expect(artifact.cause).toBeNull();
  expect(artifact.reloads.byEndpoint[view.endpoint(ids)]?.origin).toBeDefined();
  expect(artifact.states.some((state) => state.status === 'retrying')).toBe(true);
  expect(JSON.stringify(artifact)).not.toContain('Cookie');
});
