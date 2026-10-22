/**
 * Operación del partido: escenario determinista del reintento manual (RF-002,
 * RF-003).
 *
 * Reutiliza el escenario compartido (`realtimeScenario.ts`) y añade lo que solo
 * existe en esta vista: el consumidor que se recarga es
 * `/api/v1/matches/{id}/operation`, el partido es uno **abierto** descubierto
 * por la API pública y el panel tiene su propio trabajo en curso (una
 * sustitución a medio preparar) que el reintento no puede descartar.
 *
 * La vista previa de sustituciones y el indicador de borrador también publican
 * `role="status"`: el localizador del estado del tiempo real se acota por su
 * texto exacto, así que ninguno de ellos se confunde con el estado manual.
 */

import { readFileSync } from 'node:fs';

import { expect, test, type Page } from '@playwright/test';

import { reportPath, type ViewArtifact } from './artifacts.ts';
import type { ChannelGate } from './channel.ts';
import { discoverDemoData } from './demo.ts';
import { E2E_LABELS, REALTIME_STATUS_TEXT, labelText } from './labels.ts';
import { VIEWS, MAX_MS } from './observations.ts';
import { runRealtimeScenario, type ViewPageState } from './realtimeScenario.ts';

/** Métodos que no son una acción de la página sobre los datos. */
const READ_ONLY_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

test('operación del partido: el reintento manual reconecta con el canal bloqueado', async ({
  page,
  context,
  baseURL,
}) => {
  const view = VIEWS.operation;
  const ids = await discoverDemoData();

  // Acción en curso del operador: una sustitución a medio preparar. Se elige el
  // tipo y el minuto sin enviar nada, y el reintento no puede descartarla ni
  // provocar el envío del formulario. El `<label>` del formulario envuelve al
  // `select` con sus opciones, así que su texto no sirve como etiqueta: se usa
  // el rol accesible y el nombre exacto en el idioma fijado (RNF-005).
  const eventType = page.getByRole('combobox', {
    name: labelText(E2E_LABELS.operationEventType),
    exact: true,
  });
  const eventMinute = page.getByRole('spinbutton', {
    name: labelText(E2E_LABELS.operationEventMinute),
    exact: true,
  });
  const substitutionPreview = page
    .locator('[role="status"]')
    .filter({ hasText: labelText(E2E_LABELS.operationSubstitutionPreview) });

  const pageState: ViewPageState = {
    async prepare(): Promise<void> {
      await expect(
        page.getByRole('heading', {
          name: labelText(E2E_LABELS.operationReportHeading),
          exact: true,
        }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
      await eventType.selectOption('substitution', { timeout: MAX_MS.initialConnected });
      await eventMinute.fill('23', { timeout: MAX_MS.initialConnected });
      await expect(substitutionPreview).toBeVisible({ timeout: MAX_MS.initialConnected });
    },
    async assertDuringManual(): Promise<void> {
      // Con el estado manual visible, la acción en curso del operador sigue
      // disponible: ni se descarta ni se deshabilita.
      await expect(eventType).toHaveValue('substitution');
      await expect(eventType).toBeEnabled();
      await expect(eventMinute).toHaveValue('23');
      await expect(eventMinute).toBeEnabled();
      await expect(substitutionPreview).toBeVisible();
    },
    async assertPreserved(_page: Page, gate: ChannelGate): Promise<void> {
      await expect(eventType).toHaveValue('substitution');
      await expect(eventMinute).toHaveValue('23');
      await expect(substitutionPreview).toBeVisible();
      // Ninguna acción de la página durante el escenario: la pulsación del
      // reintento no envía formularios ni escribe datos.
      const writes = gate
        .requests()
        .filter((record) => !record.channel && !READ_ONLY_METHODS.has(record.method));
      if (writes.length > 0) {
        throw new Error(
          `el escenario envió ${writes.length} peticiones de escritura fuera del canal: ${writes
            .map((record) => `${record.method} ${record.path}`)
            .join(', ')}`,
        );
      }
    },
  };

  const result = await runRealtimeScenario({ page, context, view, ids, baseURL, pageState });

  expect(result.manualText).toBe(labelText(REALTIME_STATUS_TEXT.match.retrying));
  expect(result.manualText).not.toBe(labelText(REALTIME_STATUS_TEXT.match.reconnecting));

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

  const manualCycles = result.states
    .filter((state) => state.status === 'retrying' && state.cycle !== null)
    .map((state) => state.cycle);
  expect([...new Set(manualCycles)].sort()).toEqual([0, 1]);
  const firstClick = Math.min(...result.marks.cycles.map((cycle) => cycle.clickedAt));
  expect(result.states.some((state) => state.status === 'retrying' && state.at < firstClick)).toBe(
    false,
  );

  expect(
    result.states.some(
      (state) =>
        state.status === 'connected' &&
        state.at > result.marks.closedAt &&
        state.at <= result.marks.unblockedAt,
    ),
  ).toBe(false);
  expect(result.orderViolations).toEqual([]);
  expect(result.artifact.connections.established).toBe(2);
  expect(result.artifact.connections.establishedDuringBlock).toBe(0);

  // El consumidor de la operación es el único medido, y su recarga es una como
  // máximo, sin duplicado y sin recargar el documento.
  const endpoint = view.endpoint(ids);
  expect(Object.keys(result.artifact.reloads.byEndpoint)).toEqual([endpoint]);
  expect(result.artifact.reloads.documentReloads).toBe(0);
  expect(result.artifact.reloads.duplicates).toBe(0);
  expect(result.artifact.reloads.attributable).toBeLessThanOrEqual(1);
  expect(result.artifact.reloads.byEndpoint[endpoint]?.inWindow).toBeLessThanOrEqual(1);
  expect(['reconnect', 'none']).toContain(result.artifact.reloads.byEndpoint[endpoint]?.origin);

  const artifact = JSON.parse(
    readFileSync(reportPath('view-operation.json'), 'utf8'),
  ) as ViewArtifact;
  expect(artifact.view).toBe('operation');
  expect(artifact.verdict).toBe('passed');
  expect(artifact.cause).toBeNull();
  expect(artifact.states.some((state) => state.status === 'retrying')).toBe(true);
  expect(JSON.stringify(artifact)).not.toContain('Cookie');

  console.log(
    `[operation] recargas observadas: ${JSON.stringify(result.artifact.reloads.byEndpoint)}`,
  );
});
