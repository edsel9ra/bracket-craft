import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  EXPECTED_VIEWS,
  VIEWS,
  assertScenarioOrder,
  classifyReloads,
  expectedConnectionCount,
  isDuplicateReload,
  maxMillis,
  type ScenarioMarks,
} from '../e2e/observations.ts';
import {
  E2E_LABELS,
  E2E_LOCALE,
  E2E_LOCALE_COOKIE,
  REALTIME_STATUS_TEXT,
  labelText,
  localeCookie,
  type VisibleRealtimeStatus,
} from '../e2e/labels.ts';
import {
  realtimeStatusLabelKey,
  type RealtimeLabelNamespace,
} from '../app/utils/realtimeStatusLabel.ts';

const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const observationsSource = readFileSync(
  new URL('../e2e/observations.ts', import.meta.url),
  'utf8',
);
const labelsSource = readFileSync(new URL('../e2e/labels.ts', import.meta.url), 'utf8');
const playwrightConfig = readFileSync(
  new URL('../playwright.config.ts', import.meta.url),
  'utf8',
);
const packageJson = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
) as {
  scripts: Record<string, string>;
  devDependencies: Record<string, string>;
  dependencies: Record<string, string>;
};

const NAMESPACES: RealtimeLabelNamespace[] = ['public', 'workspace', 'match'];
const VISIBLE_STATUSES: VisibleRealtimeStatus[] = [
  'connected',
  'reconnecting',
  'retrying',
  'error',
];

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translations.slice(0, englishStart),
    english: translations.slice(englishStart),
  };
}

function messageText(catalog: string, key: string): string {
  const escaped = key.replace(/\./g, '\\.');
  const match = catalog.match(new RegExp(`'${escaped}':\\s*'([^']*)'`));
  if (!match) assert.fail(`missing key ${key}`);
  return match[1] ?? '';
}

/**
 * Orden canónico de una corrida válida: conexión aceptada antes del bloqueo,
 * error visible, dos ciclos de pulsación con su estado manual, desbloqueo,
 * reconexión y asentamiento. Cada prueba rota altera un único tramo.
 */
function validMarks(): ScenarioMarks {
  return {
    connectedOnceAt: 1_000,
    blockedAt: 2_000,
    closedAt: 2_050,
    errorVisibleAt: 2_400,
    cycles: [
      {
        clickedAt: 3_000,
        attemptStartedAt: 3_100,
        manualVisibleAt: 3_600,
        manualGoneAt: 4_400,
      },
      {
        clickedAt: 5_000,
        attemptStartedAt: 5_100,
        manualVisibleAt: 5_600,
        manualGoneAt: 6_400,
      },
    ],
    unblockedAt: 7_000,
    connectedAt: 7_800,
    settledAt: 10_800,
  };
}

test('classifyReloads: el sondeo periódico de la página pública queda fuera de la ventana', () => {
  const result = classifyReloads({
    requests: [{ path: '/api/v1/tournaments/public/t1', at: 30_000 }],
    endpoints: ['/api/v1/tournaments/public/t1'],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
  });

  assert.equal(result.attributable, 0, 'polling must not count as a reload');
  assert.equal(result.polling, 1);
  assert.equal(result.duplicates, 0);
});

test('classifyReloads: una recarga dentro de la ventana posterior a connected es atribuible', () => {
  const result = classifyReloads({
    requests: [{ path: '/api/v1/tournaments/public/t1', at: 1_500 }],
    endpoints: ['/api/v1/tournaments/public/t1'],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
  });

  assert.equal(result.attributable, 1);
  assert.equal(result.duplicates, 0);
  assert.equal(result.polling, 0);
});

test('classifyReloads: dos recargas del mismo consumidor en la ventana son un duplicado', () => {
  const result = classifyReloads({
    requests: [
      { path: '/api/v1/tournaments/public/t1', at: 1_000 },
      { path: '/api/v1/tournaments/public/t1', at: 4_000 },
    ],
    endpoints: ['/api/v1/tournaments/public/t1'],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
  });

  assert.equal(result.attributable, 1, 'one consumer reloads at most once');
  assert.equal(result.duplicates, 1);
});

test('classifyReloads: una petición anterior a connected no es atribuible', () => {
  const result = classifyReloads({
    requests: [{ path: '/api/v1/tournaments/public/t1', at: -500 }],
    endpoints: ['/api/v1/tournaments/public/t1'],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
  });

  assert.equal(result.attributable, 0);
  assert.equal(result.beforeConnected, 1);
});

test('classifyReloads: cada consumidor se clasifica por su endpoint y el prefijo más largo gana', () => {
  const result = classifyReloads({
    requests: [
      { path: '/api/v1/tournaments/public/t1', at: 1_000 },
      { path: '/api/v1/tournaments?page=1', at: 1_200 },
      { path: '/api/v1/matches/m1/operation', at: 1_400 },
    ],
    endpoints: [
      '/api/v1/tournaments/public/t1',
      '/api/v1/tournaments',
      '/api/v1/matches/m1/operation',
    ],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
  });

  assert.equal(result.attributable, 3, 'one attributable reload per consumer');
  assert.equal(result.duplicates, 0);
  assert.equal(result.byEndpoint['/api/v1/tournaments/public/t1']?.inWindow, 1);
  assert.equal(
    result.byEndpoint['/api/v1/tournaments']?.inWindow,
    1,
    'the public request must not be attributed to the generic workspace endpoint',
  );
  assert.equal(result.byEndpoint['/api/v1/matches/m1/operation']?.inWindow, 1);
});

test('classifyReloads: peticiones ajenas a los consumidores no se cuentan', () => {
  const result = classifyReloads({
    requests: [
      { path: '/api/v1/tournaments/public/t1', at: 1_000 },
      { path: '/api/v1/users/me', at: 1_000 },
    ],
    endpoints: ['/api/v1/tournaments/public/t1'],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
  });

  assert.equal(result.attributable, 1);
  assert.equal(result.byEndpoint['/api/v1/users/me'], undefined);
});

test('classifyReloads: una navegación del documento nunca es una recarga válida', () => {
  const result = classifyReloads({
    requests: [{ path: '/api/v1/tournaments/public/t1', at: 1_000 }],
    endpoints: ['/api/v1/tournaments/public/t1'],
    connectedAt: 0,
    windowMs: 6_000,
    pollingIntervalMs: 30_000,
    documentNavigations: [1_200],
  });

  assert.equal(result.documentReloads, 1, 'the scenario expects zero document reloads');
  assert.equal(result.attributable, 1, 'a document navigation is not an attributable consumer reload');
});

test('isDuplicateReload: dos recargas del mismo consumidor en la misma ventana', () => {
  const group = {
    requests: [{ at: 1_000 }, { at: 2_000 }],
    connectedAt: 0,
    windowMs: 6_000,
  };
  assert.equal(isDuplicateReload(group), true);
  assert.equal(isDuplicateReload({ ...group, requests: [{ at: 1_000 }] }), false);
  assert.equal(
    isDuplicateReload({ ...group, requests: [{ at: 1_000 }, { at: 8_000 }] }),
    false,
    'outside the window the second request is not a duplicate',
  );
});

test('assertScenarioOrder: la secuencia canónica no tiene violaciones', () => {
  assert.deepEqual(assertScenarioOrder(validMarks()), []);
});

test('assertScenarioOrder: manual antes del clic se informa', () => {
  const marks = validMarks();
  const [first, ...rest] = marks.cycles;
  assert.ok(first);
  const broken: ScenarioMarks = {
    ...marks,
    cycles: [{ ...first, manualVisibleAt: 2_900 }, ...rest],
  };
  assert.ok(assertScenarioOrder(broken).includes('manual-before-click'));
});

test('assertScenarioOrder: conectado durante el bloqueo se informa', () => {
  const marks = validMarks();
  const broken: ScenarioMarks = {
    ...marks,
    connectedAt: marks.unblockedAt - 100,
  };
  assert.ok(assertScenarioOrder(broken).includes('connected-while-blocked'));
});

test('assertScenarioOrder: un estado manual que sobrevive al desbloqueo se informa', () => {
  const marks = validMarks();
  const last = marks.cycles.at(-1);
  assert.ok(last);
  const broken: ScenarioMarks = {
    ...marks,
    cycles: [...marks.cycles.slice(0, -1), { ...last, manualGoneAt: marks.unblockedAt + 1 }],
  };
  assert.ok(assertScenarioOrder(broken).includes('manual-survived'));
});

test('assertScenarioOrder: conectado sin estado manual previo se informa', () => {
  const broken: ScenarioMarks = { ...validMarks(), cycles: [] };
  assert.ok(assertScenarioOrder(broken).includes('connected-without-manual'));
});

test('assertScenarioOrder: una recarga anterior a la reconexión se informa', () => {
  const marks = validMarks();
  const broken: ScenarioMarks = { ...marks, firstReloadAt: marks.connectedAt - 10 };
  assert.ok(assertScenarioOrder(broken).includes('reload-before-reconnect'));
});

test('expectedConnectionCount: una conexión inicial y otra tras la última pulsación', () => {
  assert.deepEqual(expectedConnectionCount({ cycles: 2 }), {
    established: 2,
    establishedDuringBlock: 0,
  });
  assert.deepEqual(expectedConnectionCount({ cycles: 1 }), {
    established: 2,
    establishedDuringBlock: 0,
  });
  assert.deepEqual(expectedConnectionCount({ cycles: 0 }), {
    established: 1,
    establishedDuringBlock: 0,
  });
});

test('las tres vistas se seleccionan con su namespace, su URL y su endpoint', () => {
  assert.deepEqual([...EXPECTED_VIEWS], ['public', 'workspace', 'operation']);

  const ids = { tournamentId: 't1', matchId: 'm1' };

  for (const id of EXPECTED_VIEWS) {
    assert.equal(VIEWS[id].id, id, id);
    assert.equal(VIEWS[id].timeoutMs, maxMillis('view', id), id);
    assert.equal(maxMillis('view', id), 240_000, id);
  }

  assert.equal(VIEWS.public.namespace, 'public');
  assert.equal(VIEWS.workspace.namespace, 'workspace');
  assert.equal(VIEWS.operation.namespace, 'match');

  assert.equal(VIEWS.public.url(ids), '/tournaments/t1');
  assert.equal(VIEWS.workspace.url(ids), '/workspace');
  assert.equal(VIEWS.operation.url(ids), '/workspace/matches/m1');

  assert.equal(VIEWS.public.endpoint(ids), '/api/v1/tournaments/public/t1');
  assert.equal(VIEWS.workspace.endpoint(ids), '/api/v1/tournaments');
  assert.equal(VIEWS.operation.endpoint(ids), '/api/v1/matches/m1/operation');
});

test('los tiempos máximos por condición son los declarados en el plan', () => {
  assert.equal(maxMillis('warmup'), 120_000);
  assert.equal(maxMillis('initialConnected'), 45_000);
  assert.equal(maxMillis('errorVisible'), 15_000);
  assert.equal(maxMillis('manualVisible'), 3_000);
  assert.equal(maxMillis('attemptFailed'), 15_000);
  assert.equal(maxMillis('reconnect'), 30_000);
  assert.equal(maxMillis('settle'), 3_000);
  assert.equal(maxMillis('reloadWindow'), 6_000);
  assert.equal(maxMillis('run'), 15 * 60_000);
  assert.equal(maxMillis('stackStart'), 5 * 60_000);
  assert.equal(maxMillis('job'), 25 * 60_000);
});

test('el idioma de los localizadores es fijo y viaja en la cookie bc_locale', () => {
  assert.equal(E2E_LOCALE, 'es');
  assert.equal(E2E_LOCALE_COOKIE, 'bc_locale');
  assert.deepEqual(localeCookie(), { name: 'bc_locale', value: 'es', path: '/' });
  assert.equal(localeCookie('en').value, 'en');
});

test('labelText selecciona el texto del idioma fijado en el contexto', () => {
  assert.equal(labelText(E2E_LABELS.retry), 'Reintentar');
  assert.equal(labelText(E2E_LABELS.retry, 'en'), 'Retry');
});

test('los textos de labels.ts existen literalmente en el catálogo es y en el en', () => {
  const { spanish, english } = catalogSlices();

  for (const [name, label] of Object.entries(E2E_LABELS)) {
    assert.equal(messageText(spanish, label.key), label.es, `Spanish text drift for ${name}`);
    assert.equal(messageText(english, label.key), label.en, `English text drift for ${name}`);
    assert.equal(labelText(label), label.es, name);
  }
});

test('labels.ts cubre las cuatro etiquetas visibles de las tres vistas en es y en', () => {
  const { spanish, english } = catalogSlices();

  for (const namespace of NAMESPACES) {
    for (const status of VISIBLE_STATUSES) {
      const key = realtimeStatusLabelKey(status, namespace);
      assert.ok(key, `${namespace}/${status} must have a label key`);
      const label = REALTIME_STATUS_TEXT[namespace][status];
      assert.equal(label.key, key, `${namespace}/${status}`);
      assert.equal(messageText(spanish, key), label.es, `Spanish drift for ${key}`);
      assert.equal(messageText(english, key), label.en, `English drift for ${key}`);
    }

    assert.notEqual(
      REALTIME_STATUS_TEXT[namespace].retrying.es,
      REALTIME_STATUS_TEXT[namespace].reconnecting.es,
      `Spanish manual text equals the automatic one: ${namespace}`,
    );
    assert.notEqual(
      REALTIME_STATUS_TEXT[namespace].retrying.en,
      REALTIME_STATUS_TEXT[namespace].reconnecting.en,
      `English manual text equals the automatic one: ${namespace}`,
    );
  }
});

test('las funciones del arnés son puras: sin Playwright y sin leer el reloj', () => {
  for (const [name, source] of [
    ['observations.ts', observationsSource],
    ['labels.ts', labelsSource],
  ] as const) {
    assert.doesNotMatch(source, /@playwright\/test/, `${name} must not depend on Playwright`);
    assert.doesNotMatch(source, /\bDate\.now\b|\bperformance\.now\b/, `${name} must not read the clock`);
  }
});

test('la configuración de Playwright es Chromium headless, serial y sin reintentos ni traza', () => {
  assert.match(playwrightConfig, /testDir:\s*'\.\/e2e'/);
  assert.match(playwrightConfig, /workers:\s*1/);
  assert.match(playwrightConfig, /retries:\s*0/);
  assert.match(playwrightConfig, /timeout:\s*240_000/);
  assert.match(playwrightConfig, /trace:\s*'off'/);
  assert.match(playwrightConfig, /browserName:\s*'chromium'/);
  assert.match(playwrightConfig, /headless:\s*true/);
  assert.match(playwrightConfig, /testMatch:\s*\/session\\\.setup\\\.ts\//);
  assert.match(playwrightConfig, /storageState/);
  assert.match(playwrightConfig, /\.auth\/state\.json/);
  assert.match(playwrightConfig, /outputDir/);
  assert.doesNotMatch(playwrightConfig, /firefox|webkit/i, 'one engine only');
});

test('package.json fija Playwright como devDependency y expone los comandos del arnés', () => {
  assert.equal(packageJson.devDependencies['@playwright/test'], '1.64.1');
  assert.equal(packageJson.dependencies['@playwright/test'], undefined);
  for (const script of ['e2e', 'e2e:test', 'typecheck:e2e']) {
    assert.ok(packageJson.scripts[script], `missing script ${script}`);
  }
});
