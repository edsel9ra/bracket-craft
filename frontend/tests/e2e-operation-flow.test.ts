/**
 * Modelo y artefacto del escenario E2E de operación y cierre (H4-T10).
 *
 * Se verifica sin navegador ni pila: muestras y transiciones del artefacto,
 * validación del fichero, integración aditiva en el resumen del runner y la
 * decisión de captura solo en fallo. El escenario de reintento conserva sus
 * pruebas y su veredicto; aquí solo se comprueba el escenario nuevo.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import type { ArtifactVerdict, ViewArtifact } from '../e2e/artifacts.ts';
import {
  OPERATION_FLOW_PROJECT,
  OPERATION_FLOW_VIEW,
  buildOperationFlowArtifact,
  countFlowSamples,
  countFlowTransitions,
  isOperationFlowArtifact,
  type OperationFlowSample,
} from '../e2e/operationFlowModel.ts';
import { shouldCaptureScreenshot, type ScenarioMarks, type ViewId } from '../e2e/observations.ts';
import {
  EXIT_CODES,
  buildRunSummary,
  formatSummaryTable,
  type PlaywrightProjectOutcome,
} from '../e2e/runModel.ts';

const MARKS: ScenarioMarks = {
  connectedOnceAt: 1_000,
  blockedAt: 2_000,
  closedAt: 2_050,
  errorVisibleAt: 2_400,
  cycles: [{ clickedAt: 3_000, attemptStartedAt: 3_100, manualVisibleAt: 3_600, manualGoneAt: 4_400 }],
  unblockedAt: 7_000,
  connectedAt: 7_800,
  settledAt: 10_800,
};

function viewArtifact(view: ViewId, verdict: ArtifactVerdict): ViewArtifact {
  return {
    schemaVersion: 1,
    view,
    verdict,
    cause: null,
    durationMs: 10_000,
    states: [{ status: 'connected', at: 1_000, cycle: null, relativeToClickMs: null, relativeToAttemptMs: null }],
    marks: MARKS,
    connections: { established: 2 },
    attempts: 1,
    reloads: {
      attributable: 0,
      duplicates: 0,
      polling: 0,
      beforeConnected: 0,
      unclassified: 0,
      documentReloads: 0,
      byEndpoint: {},
    },
  };
}

function project(name: string, status: PlaywrightProjectOutcome['status'] = 'passed'): PlaywrightProjectOutcome {
  return { project: name, status, durationMs: 8_000 };
}

function flowStates(): OperationFlowSample[] {
  return [
    { status: 'rules-read-only', at: 1_000 },
    { status: 'rules-format-default', at: 1_100 },
    { status: 'rules-format-warning', at: 1_200 },
    { status: 'rules-format-warning', at: 1_250 },
  ];
}

function retryRun() {
  return {
    artifacts: ['public', 'workspace', 'operation'].map((view) =>
      viewArtifact(view as ViewId, 'passed'),
    ),
    projects: [
      project('setup'),
      project('public'),
      project('workspace'),
      project('operation'),
      project(OPERATION_FLOW_PROJECT),
    ],
    totalDurationMs: 30_000,
    stack: { mode: 'skipped' as const, durationMs: null },
  };
}

test('el artefacto cuenta muestras y transiciones consecutivas distintas', () => {
  const states = flowStates();
  assert.deepEqual(countFlowSamples(states), {
    'rules-read-only': 1,
    'rules-format-default': 1,
    'rules-format-warning': 2,
  });
  assert.equal(countFlowTransitions(states), 2, 'la muestra repetida no es una transición');

  const artifact = buildOperationFlowArtifact({
    verdict: 'passed',
    durationMs: 12_345.6,
    states,
  });
  assert.equal(artifact.schemaVersion, 1);
  assert.equal(artifact.view, OPERATION_FLOW_VIEW);
  assert.equal(artifact.verdict, 'passed');
  assert.equal(artifact.cause, null);
  assert.equal(artifact.durationMs, 12_346);
  assert.equal(artifact.transitions, 2);
  assert.deepEqual(artifact.states, states);
});

test('el artefacto sanea la causa y no publica cabeceras ni tokens', () => {
  const artifact = buildOperationFlowArtifact({
    verdict: 'behavioral',
    cause: 'Cookie: bc_access_token=secret; Authorization: Bearer xyz',
    durationMs: 10,
    states: [{ status: 'rules-read-only', at: 1 }],
  });
  const serialized = JSON.stringify(artifact);
  assert.doesNotMatch(serialized, /secret|Bearer xyz|Cookie/);
  assert.match(serialized, /\[REDACTED\]/);
});

test('isOperationFlowArtifact acepta el contrato y rechaza deriva o corrupción', () => {
  const artifact = buildOperationFlowArtifact({
    verdict: 'passed',
    durationMs: 10,
    states: flowStates(),
  });
  assert.equal(isOperationFlowArtifact(artifact), true);

  assert.equal(isOperationFlowArtifact({ ...artifact, view: 'operation' }), false);
  assert.equal(isOperationFlowArtifact({ ...artifact, transitions: 99 }), false);
  assert.equal(
    isOperationFlowArtifact({
      ...artifact,
      states: [{ status: 'estado-desconocido', at: 1 }],
    }),
    false,
  );
  assert.equal(isOperationFlowArtifact(null), false);
});

test('el resumen incorpora el escenario nuevo sin cambiar el veredicto del reintento', () => {
  const passed = buildOperationFlowArtifact({
    verdict: 'passed',
    durationMs: 5_000,
    states: flowStates(),
  });
  const summary = buildRunSummary({
    ...retryRun(),
    operationFlowArtifact: passed,
    operationFlowProject: project(OPERATION_FLOW_PROJECT, 'passed', 5_000),
  });
  assert.equal(summary.status, 'green');
  assert.equal(summary.exitCode, EXIT_CODES.green);
  assert.deepEqual(summary.missing, []);
  assert.equal(summary.views.length, 3);
  assert.equal(summary.operationFlow?.scenario, OPERATION_FLOW_VIEW);
  assert.equal(summary.operationFlow?.verdict, 'passed');
  assert.equal(summary.operationFlow?.transitions, 2);
  assert.equal(summary.schemaVersion, 1);
  assert.match(formatSummaryTable(summary).join('\n'), /operation-flow\s+passed/);

  const behavioral = buildRunSummary({
    ...retryRun(),
    operationFlowArtifact: buildOperationFlowArtifact({
      verdict: 'behavioral',
      cause: 'opening-blocked-missing',
      durationMs: 5_000,
      states: flowStates(),
    }),
    operationFlowProject: project(OPERATION_FLOW_PROJECT, 'passed', 5_000),
  });
  assert.equal(behavioral.exitCode, EXIT_CODES.behavioral);
  assert.match(behavioral.cause ?? '', /operation-flow/);
  assert.equal(behavioral.views.every((view) => view.verdict === 'passed'), true);
});

test('un escenario nuevo omitido o fallido no puede quedar verde', () => {
  const omitted = buildRunSummary({
    ...retryRun(),
    operationFlowArtifact: null,
    operationFlowProject: project(OPERATION_FLOW_PROJECT, 'missing'),
  });
  assert.equal(omitted.exitCode, EXIT_CODES.invalid);
  assert.match(omitted.cause ?? '', /omitted-view/);

  const failedWithoutArtifact = buildRunSummary({
    ...retryRun(),
    operationFlowProject: project(OPERATION_FLOW_PROJECT, 'failed'),
  });
  assert.equal(failedWithoutArtifact.exitCode, EXIT_CODES.infrastructure);
  assert.match(failedWithoutArtifact.cause ?? '', /view-failed-without-artifact/);

  const missingArtifact = buildRunSummary({
    ...retryRun(),
    operationFlowProject: project(OPERATION_FLOW_PROJECT, 'passed'),
  });
  assert.equal(missingArtifact.exitCode, EXIT_CODES.infrastructure);
  assert.match(missingArtifact.cause ?? '', /view-artifact-missing/);
});

test('sin escenario nuevo el resumen conserva el comportamiento anterior', () => {
  const summary = buildRunSummary(retryRun());
  assert.equal(summary.status, 'green');
  assert.equal(summary.operationFlow, null);
  assert.equal(formatSummaryTable(summary).join('\n').includes('operation-flow'), false);
});

test('la captura es solo de fallo y el modelo no depende de Playwright ni del reloj', () => {
  assert.equal(shouldCaptureScreenshot('passed'), false);
  for (const verdict of ['behavioral', 'infrastructure', 'invalid', 'missing'] as const) {
    assert.equal(shouldCaptureScreenshot(verdict), true);
  }

  const source = readFileSync(new URL('../e2e/operationFlowModel.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /@playwright\/test/);
  assert.doesNotMatch(source, /Date\.now|performance\.now|new Date/);
  assert.doesNotMatch(source, /writeJsonReport|writeFile|reportPath/);
});

test('el proyecto y la vista del escenario nuevo no colisionan con las tres vistas', () => {
  assert.equal(OPERATION_FLOW_VIEW, 'operation-flow');
  assert.equal(OPERATION_FLOW_PROJECT, 'operation-flow');
});
