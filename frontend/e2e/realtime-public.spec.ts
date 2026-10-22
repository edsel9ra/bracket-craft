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
import { discoverDemoData } from './demo.ts';
import { REALTIME_STATUS_TEXT, labelText } from './labels.ts';
import { VIEWS } from './observations.ts';
import { runRealtimeScenario } from './realtimeScenario.ts';

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
  expect(result.artifact.connections.establishedDuringBlock).toBe(0);
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
