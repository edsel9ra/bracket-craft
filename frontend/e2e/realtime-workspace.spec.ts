/**
 * Panel del Workspace: escenario determinista del reintento manual (RF-002,
 * RF-003).
 *
 * Reutiliza el escenario compartido (`realtimeScenario.ts`) —bloqueo, error,
 * dos ciclos de pulsación, estado manual, desbloqueo, reconexión y recuentos—
 * y solo declara lo propio de esta vista: su URL, su namespace de etiquetas y
 * el endpoint del consumidor cuya recarga se mide (`/api/v1/tournaments`).
 *
 * Aquí se comprueba además lo que no aparece en la vista pública: que el
 * reintento no altera el trabajo en curso del panel (los torneos listados
 * siguen ahí) y que el localizador del control no se confunde con los otros
 * «Reintentar» de los bloques de error de datos ni con el resto de
 * `role="status"` de la página.
 */

import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import { reportPath, type ViewArtifact } from './artifacts.ts';
import { discoverDemoData } from './demo.ts';
import { E2E_LABELS, REALTIME_STATUS_TEXT, labelText } from './labels.ts';
import { MAX_MS, VIEWS } from './observations.ts';
import { runRealtimeScenario, type ViewPageState } from './realtimeScenario.ts';

test('vista del Workspace: el reintento manual reconecta con el canal bloqueado', async ({
  page,
  context,
  baseURL,
}) => {
  const view = VIEWS.workspace;
  const ids = await discoverDemoData();

  // Trabajo en curso del panel: los torneos ya listados. Su número no puede
  // cambiar por el reintento ni por la recarga posterior (que es de datos, no
  // del documento), y el localizador no depende de la maquetación.
  const tournamentsLink = page.getByRole('link', {
    name: labelText(E2E_LABELS.workspaceConfigure),
    exact: true,
  });
  let listedBefore = 0;

  const pageState: ViewPageState = {
    async prepare(): Promise<void> {
      const heading = page.getByRole('heading', {
        name: labelText(E2E_LABELS.workspaceTournaments),
        exact: true,
      });
      await expect(heading).toBeVisible({ timeout: MAX_MS.initialConnected });
      listedBefore = await tournamentsLink.count();
      if (listedBefore === 0) {
        throw new Error('el panel del Workspace no tiene torneos que preservar');
      }
    },
    async assertDuringManual(): Promise<void> {
      // Mientras se anuncia el estado manual, el panel sigue mostrando su
      // trabajo: el reintento no lo vacía ni lo sustituye por un error.
      await expect(tournamentsLink.first()).toBeVisible();
      const listedDuring = await tournamentsLink.count();
      if (listedDuring !== listedBefore) {
        throw new Error(
          `el estado manual alteró el trabajo en curso: ${listedBefore} torneos antes y ${listedDuring} durante`,
        );
      }
    },
    async assertPreserved(): Promise<void> {
      await expect(
        page.getByRole('heading', {
          name: labelText(E2E_LABELS.workspaceTournaments),
          exact: true,
        }),
      ).toBeVisible({ timeout: MAX_MS.initialConnected });
      const listedAfter = await tournamentsLink.count();
      if (listedAfter !== listedBefore) {
        throw new Error(
          `el reintento alteró el trabajo en curso: ${listedBefore} torneos antes y ${listedAfter} después`,
        );
      }
    },
  };

  const result = await runRealtimeScenario({ page, context, view, ids, baseURL, pageState });

  // Estado manual propio de la vista y distinto del automático.
  expect(result.manualText).toBe(labelText(REALTIME_STATUS_TEXT.workspace.retrying));
  expect(result.manualText).not.toBe(labelText(REALTIME_STATUS_TEXT.workspace.reconnecting));

  // Dos ciclos, cada uno con clic → intento → manual → vuelta a error, antes
  // del desbloqueo y de la reconexión.
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

  // Los dos ciclos dejaron su estado manual, posterior al error y anterior al
  // desbloqueo; ninguno se observó sin pulsación.
  const manualCycles = result.states
    .filter((state) => state.status === 'retrying' && state.cycle !== null)
    .map((state) => state.cycle);
  expect([...new Set(manualCycles)].sort()).toEqual([0, 1]);
  const firstClick = Math.min(...result.marks.cycles.map((cycle) => cycle.clickedAt));
  expect(result.states.some((state) => state.status === 'retrying' && state.at < firstClick)).toBe(
    false,
  );

  // Ninguna recuperación espontánea: conectado nunca se observó con el canal
  // bloqueado, ni se abrió otra secuencia de conexión tras el asentamiento.
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
  // Sin `establishedDuringBlock` (retirado por ser un contador estructural): la
  // prueba de que no hubo transporte durante el bloqueo es la ausencia de
  // estado conectado en la ventana, comprobada arriba.

  // Recargas: ninguna del documento, ninguna duplicada y como máximo una del
  // consumidor del panel, atribuida a la reconexión y no al sondeo.
  const endpoint = view.endpoint(ids);
  expect(Object.keys(result.artifact.reloads.byEndpoint)).toEqual([endpoint]);
  expect(result.artifact.reloads.documentReloads).toBe(0);
  expect(result.artifact.reloads.duplicates).toBe(0);
  expect(result.artifact.reloads.attributable).toBeLessThanOrEqual(1);
  expect(result.artifact.reloads.byEndpoint[endpoint]?.inWindow).toBeLessThanOrEqual(1);
  expect(['reconnect', 'none']).toContain(result.artifact.reloads.byEndpoint[endpoint]?.origin);

  // El artefacto queda en disco, en verde y sin cabeceras sensibles.
  const artifact = JSON.parse(
    readFileSync(reportPath('view-workspace.json'), 'utf8'),
  ) as ViewArtifact;
  expect(artifact.view).toBe('workspace');
  expect(artifact.verdict).toBe('passed');
  expect(artifact.cause).toBeNull();
  expect(artifact.states.some((state) => state.status === 'retrying')).toBe(true);
  expect(JSON.stringify(artifact)).not.toContain('Cookie');

  console.log(
    `[workspace] recargas observadas: ${JSON.stringify(result.artifact.reloads.byEndpoint)}`,
  );
});
