/**
 * Partes puras del runner E2E (T7, RF-004, RF-005, RF-006).
 *
 * Se verifica sin navegador ni pila: agregación de los artefactos por vista,
 * veredicto global, traducción a los códigos 0/1/2/3, reenvío de argumentos y
 * tiempos máximos. Ninguna función de `runModel.ts` lee el reloj: los instantes
 * y duraciones llegan por parámetro, igual que en `observations.ts`.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import type { ArtifactVerdict, ViewArtifact } from '../e2e/artifacts.ts';
import {
  shouldCaptureScreenshot,
  type ScenarioMarks,
  type ViewId,
} from '../e2e/observations.ts';
import {
  EXIT_CODES,
  SERVER_LOG_HEADER,
  SERVER_LOG_UNAVAILABLE,
  buildRunSummary,
  buildServerLog,
  composeServerLog,
  formatDuration,
  formatSummaryTable,
  parseRunnerArgs,
  serverLogIsAvailable,
  type PlaywrightProjectOutcome,
  type RunSummaryInput,
} from '../e2e/runModel.ts';

const MARKS: ScenarioMarks = {
  connectedOnceAt: 1_000,
  blockedAt: 2_000,
  closedAt: 2_050,
  errorVisibleAt: 2_400,
  cycles: [
    { clickedAt: 3_000, attemptStartedAt: 3_100, manualVisibleAt: 3_600, manualGoneAt: 4_400 },
    { clickedAt: 5_000, attemptStartedAt: 5_100, manualVisibleAt: 5_600, manualGoneAt: 6_400 },
  ],
  unblockedAt: 7_000,
  connectedAt: 7_800,
  settledAt: 10_800,
};

const ALL_VIEWS: ViewId[] = ['public', 'workspace', 'operation'];

interface ArtifactOptions {
  readonly cause?: string | null;
  readonly durationMs?: number;
  readonly retrying?: number;
  readonly attributable?: number;
}

function artifact(
  view: ViewId,
  verdict: ArtifactVerdict,
  options: ArtifactOptions = {},
): ViewArtifact {
  const retrying = options.retrying ?? 1;
  const states = [
    { status: 'connected' as const, at: 1_000, cycle: null, relativeToClickMs: null, relativeToAttemptMs: null },
    { status: 'error' as const, at: 2_400, cycle: null, relativeToClickMs: null, relativeToAttemptMs: null },
    ...Array.from({ length: retrying }, (_, index) => ({
      status: 'retrying' as const,
      at: 3_600 + index * 2_000,
      cycle: index,
      relativeToClickMs: 600,
      relativeToAttemptMs: 500,
    })),
  ];
  return {
    schemaVersion: 1,
    view,
    verdict,
    cause: options.cause ?? null,
    durationMs: options.durationMs ?? 12_000,
    states,
    marks: MARKS,
    connections: { established: 2 },
    attempts: 2,
    reloads: {
      attributable: options.attributable ?? 0,
      duplicates: 0,
      polling: 0,
      beforeConnected: 2,
      unclassified: 0,
      documentReloads: 0,
      byEndpoint: {},
    },
  };
}

function project(
  name: string,
  status: PlaywrightProjectOutcome['status'] = 'passed',
  durationMs = 12_000,
): PlaywrightProjectOutcome {
  return { project: name, status, durationMs };
}

function allPassedProjects(): PlaywrightProjectOutcome[] {
  return [project('setup', 'passed', 8_000), ...ALL_VIEWS.map((view) => project(view))];
}

function runInput(overrides: Partial<RunSummaryInput> = {}): RunSummaryInput {
  return {
    artifacts: ALL_VIEWS.map((view) => artifact(view, 'passed')),
    projects: allPassedProjects(),
    totalDurationMs: 40_000,
    stack: { mode: 'started', durationMs: 30_000 },
    ...overrides,
  };
}

test('los códigos de salida son 0 verde, 1 comportamiento, 2 infraestructura y 3 inválida', () => {
  assert.deepEqual(EXIT_CODES, { green: 0, behavioral: 1, infrastructure: 2, invalid: 3 });
});

test('agrega las tres vistas y sus duraciones en una corrida verde', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'passed', { durationMs: 10_000, attributable: 1 }),
        artifact('workspace', 'passed', { durationMs: 11_000 }),
        artifact('operation', 'passed', { durationMs: 12_000 }),
      ],
      projects: [
        project('setup', 'passed', 8_000),
        project('public', 'passed', 10_000),
        project('workspace', 'passed', 11_000),
        project('operation', 'passed', 12_000),
      ],
    }),
  );

  assert.equal(summary.status, 'green');
  assert.equal(summary.exitCode, EXIT_CODES.green);
  assert.equal(summary.cause, null);
  assert.deepEqual(summary.missing, []);
  assert.deepEqual(
    summary.views.map((view) => view.view),
    ['public', 'workspace', 'operation'],
  );
  assert.deepEqual(
    summary.views.map((view) => view.durationMs),
    [10_000, 11_000, 12_000],
  );
  assert.equal(summary.views[0]?.states.retrying, 1);
  assert.equal(summary.views[0]?.states.connected, 1);
  assert.equal(summary.views[0]?.reloads?.attributable, 1);
  assert.equal(summary.totalDurationMs, 40_000);
  assert.deepEqual(summary.stack, { mode: 'started', durationMs: 30_000 });

  const table = formatSummaryTable(summary).join('\n');
  assert.match(table, /MUESTRAS\s+TRANSICIONES/);
  assert.match(table, /public\s+passed/);
  assert.match(table, /workspace\s+passed/);
  assert.match(table, /operation\s+passed/);
  assert.match(table, /10\.0 s/);
  assert.match(table, /retrying=1/);
  assert.match(table, /total/i);
});

test('transitions cuenta cambios distintos y states sigue siendo muestras', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'passed', { retrying: 3 }),
        artifact('workspace', 'passed'),
        artifact('operation', 'passed'),
      ],
    }),
  );

  const publicView = summary.views[0];
  assert.ok(publicView);
  // connected, error y tres muestras retrying: states cuenta las cinco muestras.
  assert.equal(publicView.states.connected, 1);
  assert.equal(publicView.states.retrying, 3);
  assert.equal(publicView.states.error, 1);
  // Solo connected→error y error→retrying son transiciones.
  assert.equal(publicView.transitions, 2);
  assert.equal(summary.schemaVersion, 1);
  assert.equal(summary.exitCode, EXIT_CODES.green);
});

test('un artefacto ausente publica transitions null sin inventar cifras', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [artifact('public', 'passed'), artifact('workspace', 'passed')],
      projects: [project('setup'), project('public'), project('workspace'), project('operation')],
    }),
  );

  const operation = summary.views[2];
  assert.ok(operation);
  assert.equal(operation.verdict, 'infrastructure');
  assert.equal(operation.transitions, null);
  assert.deepEqual(operation.states, {});

  const table = formatSummaryTable(summary).join('\n');
  const row = table.split('\n').find((line) => line.startsWith('operation'));
  assert.ok(row, 'la fila de la vista debe existir');
  assert.match(row, /\s-\s+-\s/, 'MUESTRAS y TRANSICIONES se muestran como guion cuando faltan');
});

test('una corrida verde no activa ninguna captura', () => {
  const summary = buildRunSummary(runInput());

  assert.equal(summary.status, 'green');
  assert.deepEqual(
    summary.views.filter((view) => shouldCaptureScreenshot(view.verdict)).map((view) => view.view),
    [],
  );
});

test('un fallo de comportamiento sale con 1 y conserva la causa de la vista', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'passed'),
        artifact('workspace', 'behavioral', { cause: 'manual-not-visible' }),
        artifact('operation', 'passed'),
      ],
    }),
  );

  assert.equal(summary.status, 'behavioral');
  assert.equal(summary.exitCode, EXIT_CODES.behavioral);
  assert.match(summary.cause ?? '', /workspace/);
  assert.match(summary.cause ?? '', /manual-not-visible/);
});

test('un fallo de infraestructura en una vista sale con 2', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'passed'),
        artifact('workspace', 'infrastructure', { cause: 'demo-data-missing' }),
        artifact('operation', 'passed'),
      ],
    }),
  );

  assert.equal(summary.status, 'infrastructure');
  assert.equal(summary.exitCode, EXIT_CODES.infrastructure);
  assert.match(summary.cause ?? '', /demo-data-missing/);
});

test('una corrida inválida sale con 3 y declara su causa', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'invalid', { cause: 'channel-not-blocked' }),
        artifact('workspace', 'passed'),
        artifact('operation', 'passed'),
      ],
    }),
  );

  assert.equal(summary.status, 'invalid');
  assert.equal(summary.exitCode, EXIT_CODES.invalid);
  assert.match(summary.cause ?? '', /channel-not-blocked/);
});

test('una vista omitida o ausente del informe invalida la corrida con omitted-view', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [artifact('public', 'passed'), artifact('workspace', 'passed')],
      projects: [project('setup'), project('public'), project('workspace')],
    }),
  );

  assert.equal(summary.status, 'invalid');
  assert.equal(summary.exitCode, EXIT_CODES.invalid);
  assert.deepEqual(summary.missing, ['operation']);
  assert.match(summary.cause ?? '', /omitted-view/);
  assert.match(summary.cause ?? '', /operation/);
  const table = formatSummaryTable(summary).join('\n');
  assert.match(table, /operation\s+missing/);
});

test('una vista saltada también cuenta como omitida, nunca como verde', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [artifact('public', 'passed'), artifact('workspace', 'passed')],
      projects: [project('setup'), project('public'), project('workspace'), project('operation', 'skipped')],
    }),
  );

  assert.equal(summary.exitCode, EXIT_CODES.invalid);
  assert.deepEqual(summary.missing, ['operation']);
});

test('si la preparación falla, el veredicto es infraestructura (2)', () => {
  const summary = buildRunSummary(
    runInput({
      projects: [project('setup', 'failed', 3_000), ...ALL_VIEWS.map((view) => project(view))],
    }),
  );

  assert.equal(summary.status, 'infrastructure');
  assert.equal(summary.exitCode, EXIT_CODES.infrastructure);
  assert.match(summary.cause ?? '', /setup/);
  assert.doesNotMatch(summary.cause ?? '', /omitted-view/);
});

test('una causa de infraestructura del arranque prevalece sobre las vistas', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: ALL_VIEWS.map((view) => artifact(view, 'passed')),
      projects: [],
      infrastructureCause: 'stack-start-failed: puerto ocupado',
    }),
  );

  assert.equal(summary.exitCode, EXIT_CODES.infrastructure);
  assert.match(summary.cause ?? '', /stack-start-failed/);
});

test('un spec que falla con el artefacto en verde no puede quedar verde', () => {
  const summary = buildRunSummary(
    runInput({
      projects: [
        project('setup'),
        project('public'),
        project('workspace', 'failed'),
        project('operation'),
      ],
    }),
  );

  assert.equal(summary.status, 'behavioral');
  assert.equal(summary.exitCode, EXIT_CODES.behavioral);
  assert.match(summary.cause ?? '', /view-assertion-failed/);
  assert.equal(summary.views[1]?.verdict, 'behavioral');
});

test('un spec que agota su tiempo es un fallo de comportamiento declarado', () => {
  const summary = buildRunSummary(
    runInput({
      projects: [
        project('setup'),
        project('public', 'timedOut', 240_000),
        project('workspace'),
        project('operation'),
      ],
    }),
  );

  assert.equal(summary.exitCode, EXIT_CODES.behavioral);
  assert.match(summary.cause ?? '', /view-timeout/);
});

test('un spec que falla sin artefacto se declara infraestructura', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [artifact('public', 'passed'), artifact('operation', 'passed')],
      projects: [
        project('setup'),
        project('public'),
        project('workspace', 'failed'),
        project('operation'),
      ],
    }),
  );

  assert.equal(summary.status, 'infrastructure');
  assert.equal(summary.exitCode, EXIT_CODES.infrastructure);
  assert.match(summary.cause ?? '', /view-failed-without-artifact/);
});

test('superar el máximo por vista o el total es un fallo declarado (1)', () => {
  const overView = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'passed', { durationMs: 240_001 }),
        artifact('workspace', 'passed'),
        artifact('operation', 'passed'),
      ],
      projects: [
        project('setup'),
        project('public', 'passed', 240_001),
        project('workspace'),
        project('operation'),
      ],
    }),
  );
  assert.equal(overView.exitCode, EXIT_CODES.behavioral);
  assert.match(overView.cause ?? '', /view-time-exceeded/);

  const overRun = buildRunSummary(
    runInput({ totalDurationMs: 15 * 60_000 + 1 }),
  );
  assert.equal(overRun.exitCode, EXIT_CODES.behavioral);
  assert.match(overRun.cause ?? '', /run-time-exceeded/);
});

test('el resumen sanea la causa antes de escribirla', () => {
  const summary = buildRunSummary(
    runInput({
      artifacts: [
        artifact('public', 'behavioral', {
          cause: 'Cookie: session=abc123; Authorization: Bearer xyz',
        }),
        artifact('workspace', 'passed'),
        artifact('operation', 'passed'),
      ],
    }),
  );

  const serialized = JSON.stringify(summary);
  assert.doesNotMatch(serialized, /abc123/);
  assert.doesNotMatch(serialized, /Cookie/);
  assert.doesNotMatch(serialized, /Bearer xyz/);
  assert.match(serialized, /\[REDACTED\]/);
});

test('el veredicto no depende de un reloj leído dentro del runner', () => {
  const input = runInput();
  const first = JSON.stringify(buildRunSummary(input));
  const second = JSON.stringify(buildRunSummary(input));
  assert.equal(first, second);

  const source = readFileSync(new URL('../e2e/runModel.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /Date\.now|new Date|performance\.now|Math\.random/);
  assert.doesNotMatch(source, /@playwright\/test/);
});

test('el runner separa --no-stack y reenvía el resto a Playwright, con o sin --', () => {
  assert.deepEqual(parseRunnerArgs([]), { noStack: false, forwarded: [] });
  assert.deepEqual(parseRunnerArgs(['--no-stack']), { noStack: true, forwarded: [] });
  // `pnpm run e2e:test -- --grep ...` llega sin el separador: se reenvía igual.
  assert.deepEqual(parseRunnerArgs(['--no-stack', '--grep', 'vista pública']), {
    noStack: true,
    forwarded: ['--grep', 'vista pública'],
  });
  assert.deepEqual(parseRunnerArgs(['--no-stack', '--', '--project=public']), {
    noStack: true,
    forwarded: ['--project=public'],
  });
  assert.deepEqual(parseRunnerArgs(['--', '--grep=workspace']), {
    noStack: false,
    forwarded: ['--grep=workspace'],
  });
});

test('el registro del servidor local se sanea antes de escribirse', () => {
  const capture = buildServerLog({
    dockerAvailable: true,
    command: {
      code: 0,
      timedOut: false,
      output:
        'api-1  | Cookie: bc_access_token=secret\nweb-1  | GET /health.txt 200\napi-1  | Authorization: Bearer abc\n',
    },
  });

  assert.equal(capture.available, true);
  assert.equal(capture.note, null);
  assert.match(capture.content, /GET \/health\.txt 200/);
  assert.match(capture.content, /\[REDACTED\]/);
  assert.doesNotMatch(capture.content, /secret|Bearer abc|Cookie/);
});

test('sin docker el server.log lo declara en el propio artefacto, nunca en silencio', () => {
  const capture = buildServerLog({ dockerAvailable: false, command: null });

  assert.equal(capture.available, false);
  assert.equal(capture.note, SERVER_LOG_UNAVAILABLE);
  assert.match(capture.content, /server\.log/);
  assert.match(capture.content, /no disponible: docker CLI ausente/);
});

test('un fallo de docker compose logs se declara con su código y su salida saneada', () => {
  const capture = buildServerLog({
    dockerAvailable: true,
    command: { code: 1, timedOut: false, output: 'no such service: api token=abc123' },
  });

  assert.equal(capture.available, false);
  assert.match(capture.note ?? '', /código 1/);
  assert.match(capture.content, /no such service: api/);
  assert.doesNotMatch(capture.content, /abc123/);

  const timedOut = buildServerLog({
    dockerAvailable: true,
    command: { code: null, timedOut: true, output: '' },
  });
  assert.equal(timedOut.available, false);
  assert.match(timedOut.note ?? '', /tiempo agotado/);
});

test('la disponibilidad del server.log se decide sobre el contenido, no sobre el flag', () => {
  assert.equal(serverLogIsAvailable(`${SERVER_LOG_HEADER}\napi-1  | GET /health 200\n`), true);
  assert.equal(serverLogIsAvailable(`${SERVER_LOG_HEADER}\r\napi-1  | ok\r\n`), true);

  assert.equal(serverLogIsAvailable(null), false);
  assert.equal(serverLogIsAvailable(''), false);
  assert.equal(serverLogIsAvailable('api-1  | sin cabecera\n'), false);
  assert.equal(serverLogIsAvailable(`${SERVER_LOG_HEADER}\n`), false);
  assert.equal(serverLogIsAvailable(`${SERVER_LOG_HEADER}\n\n   \n`), false);

  assert.equal(
    serverLogIsAvailable(`${SERVER_LOG_HEADER}\n# no disponible: docker CLI ausente\n`),
    false,
  );
  assert.equal(
    serverLogIsAvailable(
      `${SERVER_LOG_HEADER}\n# no disponible: docker compose logs código 1\nno such service: api\n`,
    ),
    false,
  );
});

test('el volcado de CI sanea y encabeza el registro, y no se declara disponible si está vacío', () => {
  const content = composeServerLog(
    'api-1  | Cookie: bc_access_token=secret\nweb-1  | GET /health.txt 200\n\n',
  );

  assert.deepEqual(content.split('\n')[0], SERVER_LOG_HEADER);
  assert.match(content, /GET \/health\.txt 200/);
  assert.match(content, /\[REDACTED\]/);
  assert.doesNotMatch(content, /secret|Cookie/);
  assert.ok(content.endsWith('\n'));
  assert.equal(serverLogIsAvailable(content), true);

  assert.equal(serverLogIsAvailable(composeServerLog('')), false);
  assert.equal(serverLogIsAvailable(composeServerLog('\n  \n')), false);
});

test('el fallback de CI conserva un server.log disponible y solo escribe si falta o no está disponible', () => {
  const raw = 'api-1  | GET /health.txt 200\n';
  const available = `${SERVER_LOG_HEADER}\napi-1  | GET /health.txt 200\n`;
  const unavailable = `${SERVER_LOG_HEADER}\n# no disponible: docker CLI ausente\n`;

  const kept = composeServerLog({ existing: available, rawOutput: raw });
  assert.deepEqual(kept, { write: false, content: null });

  const missing = composeServerLog({ existing: null, rawOutput: raw });
  assert.equal(missing.write, true);
  assert.deepEqual(missing.content, composeServerLog(raw));
  assert.equal(serverLogIsAvailable(missing.content), true);

  const replaced = composeServerLog({ existing: unavailable, rawOutput: raw });
  assert.equal(replaced.write, true);
  assert.deepEqual(replaced.content, composeServerLog(raw));
  assert.doesNotMatch(replaced.content ?? '', /no disponible/);

  const headerOnly = composeServerLog({ existing: `${SERVER_LOG_HEADER}\n`, rawOutput: raw });
  assert.equal(headerOnly.write, true);
  assert.equal(serverLogIsAvailable(headerOnly.content), true);
});

test('un docker compose logs con código 0 y salida vacía no se declara disponible', () => {
  const capture = buildServerLog({
    dockerAvailable: true,
    command: { code: 0, timedOut: false, output: '\n\n' },
  });

  assert.equal(capture.available, false);
  assert.match(capture.note ?? '', /sin salida/);
  assert.equal(serverLogIsAvailable(capture.content), false);
  assert.match(capture.content, /# no disponible:/);
});

test('formatea duraciones en milisegundos y segundos', () => {
  assert.equal(formatDuration(0), '0 ms');
  assert.equal(formatDuration(999), '999 ms');
  assert.equal(formatDuration(1_500), '1.5 s');
  assert.equal(formatDuration(40_000), '40.0 s');
});
