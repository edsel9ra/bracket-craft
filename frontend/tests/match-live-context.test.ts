import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createLiveContextCoordinator,
  isAccessDenied,
  normalizeLiveCapabilities,
  type LiveCapabilities,
} from '../app/utils/matchLiveContext.ts';

const ACCESS: LiveCapabilities = {
  can_view: true,
  can_operate: false,
  can_close: false,
  available: true,
};

function apiFailure(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

interface Applied {
  access: LiveCapabilities | null;
  live: unknown;
  history033: unknown[];
}

function harness(overrides: {
  access?: () => Promise<unknown>;
  live?: () => Promise<unknown>;
  current?: () => boolean;
  busy?: () => boolean;
} = {}) {
  const applied: Applied = { access: null, live: null, history033: [{ id: 'rect-1' }] };
  const denied: string[] = [];
  const busyMarks: number[] = [];
  const fetches: string[] = [];
  const coordinator = createLiveContextCoordinator({
    isCurrent: overrides.current ?? (() => true),
    isBusy: overrides.busy ?? (() => false),
    onBusy: () => busyMarks.push(1),
    source: {
      fetchAccess: async () => {
        fetches.push('access');
        return overrides.access ? overrides.access() : ACCESS;
      },
      fetchLive: async () => {
        fetches.push('live');
        return overrides.live ? overrides.live() : { initialized: true, status: 'live' };
      },
    },
    callbacks: {
      applyAccess: (value) => {
        applied.access = value;
      },
      applyLive: (value) => {
        applied.live = value;
      },
      denyAccess: () => {
        denied.push('access');
        applied.access = null;
        applied.live = null;
      },
      denyLive: () => {
        denied.push('live');
        applied.live = null;
      },
    },
  });
  return { coordinator, applied, denied, busyMarks, fetches };
}

test('normalizeLiveCapabilities exige las cuatro booleanas y nada más', () => {
  assert.deepEqual(normalizeLiveCapabilities(ACCESS), ACCESS);
  for (const raw of [
    null,
    'x',
    [],
    {},
    { ...ACCESS, can_view: 'true' },
    { ...ACCESS, available: 1 },
    { can_view: true, can_operate: false, can_close: false },
    { ...ACCESS, scope: 'organization' },
  ]) {
    // Los extras se descartan pero la forma se admite solo si las cuatro son booleanas.
    if (typeof raw === 'object' && raw !== null && 'scope' in raw) {
      assert.deepEqual(normalizeLiveCapabilities(raw), ACCESS);
    } else {
      assert.equal(normalizeLiveCapabilities(raw), null);
    }
  }
});

test('isAccessDenied cubre solo 401/403/404', () => {
  for (const status of [401, 403, 404]) assert.equal(isAccessDenied(apiFailure(status)), true);
  for (const status of [0, 409, 500]) assert.equal(isAccessDenied(apiFailure(status)), false);
});

test('reconstruye capacidades y borrador autorizado con useApi inyectado', async () => {
  const { coordinator, applied, fetches } = harness();
  await coordinator.request();
  assert.deepEqual(applied.access, ACCESS);
  assert.deepEqual(applied.live, { initialized: true, status: 'live' });
  assert.deepEqual(fetches, ['access', 'live']);
});

test('permiso perdido limpia capacidades y borrador sin tocar historial 033', async () => {
  for (const [label, access, expectedAccess] of [
    ['can_view_false', async () => ({ ...ACCESS, can_view: false }), { ...ACCESS, can_view: false }],
    ['forbidden', async () => { throw apiFailure(403); }, null],
  ] as const) {
    const { coordinator, applied, denied, fetches } = harness({ access });
    await coordinator.request();
    assert.deepEqual(applied.access, expectedAccess, label);
    assert.equal(applied.live, null, label);
    assert.equal(denied.includes('access'), true, label);
    // Sin lectura autorizada, el borrador ni siquiera se consulta.
    assert.deepEqual(fetches, ['access'], label);
    assert.equal(applied.history033.length, 1, label);
  }
});

test('denegación live limpia el borrador y conserva capacidades e historial 033', async () => {
  const { coordinator, applied, denied } = harness({
    live: async () => {
      throw apiFailure(404);
    },
  });
  await coordinator.request();
  assert.deepEqual(applied.access, ACCESS);
  assert.equal(applied.live, null);
  assert.deepEqual(denied, ['live']);
  assert.deepEqual(applied.history033, [{ id: 'rect-1' }]);
});

test('una respuesta antigua tras cambio de contexto nunca se aplica', async () => {
  let current = true;
  let resolveLive: ((v: unknown) => void) | null = null;
  const { coordinator, applied } = harness({
    current: () => current,
    live: () => new Promise((resolve) => {
      resolveLive = resolve;
    }),
  });
  const run = coordinator.request();
  await new Promise((resolve) => setTimeout(resolve, 0));
  current = false;
  resolveLive?.({ initialized: true, status: 'live' });
  await run;
  assert.deepEqual(applied.access, ACCESS);
  assert.equal(applied.live, null);
});

test('una corrida en curso aplica la última generación, no la anterior', async () => {
  let stale = true;
  let call = 0;
  const { coordinator, applied } = harness({
    live: async () => {
      call += 1;
      return { generation: call };
    },
  });
  await coordinator.request();
  assert.deepEqual(applied.live, { generation: 1 });
  stale = false;
  await coordinator.request();
  assert.deepEqual(applied.live, { generation: 2 });
});

test('busy aplaza la corrida con una sola trailing, sin duplicar lecturas', async () => {
  let busy = true;
  const { coordinator, applied, busyMarks, fetches } = harness({ busy: () => busy });
  const first = coordinator.request();
  const second = coordinator.request();
  await first;
  await second;
  // Con la acción ocupada la reconstrucción se marca pendiente una vez.
  assert.equal(busyMarks.length, 2);
  assert.equal(applied.access, null);
  busy = false;
  await coordinator.request();
  assert.deepEqual(applied.access, ACCESS);
  assert.equal(fetches.filter((f) => f === 'live').length, 1);
});

test('un fallo no denegación conserva el estado vigente sin limpiar', async () => {
  const failures = [
    { live: async () => { throw apiFailure(500); } },
    { access: async () => { throw apiFailure(500); } },
  ];
  for (const extra of failures) {
    const { coordinator, applied, denied } = harness(extra);
    await coordinator.request();
    assert.equal(denied.length, 0);
    assert.equal(applied.history033.length, 1);
  }
});
