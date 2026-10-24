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

test('operación y cierre: reglas, avisos, bloqueos y retiro lógico', async ({ page }) => {
  const { tournamentId } = await discoverDemoData();
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
