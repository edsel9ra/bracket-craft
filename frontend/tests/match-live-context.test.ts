import assert from 'node:assert/strict';
import test from 'node:test';

import { createLiveContextCoordinator, normalizeLiveCapabilities } from '../app/utils/matchLiveContext.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';

function liveEvent() {
  return {
    client_event_id: 'cccccccc-0000-4000-8000-000000000003',
    event_type: 'goal',
    team_id: TEAM,
    beneficiary_team_id: null,
    player_id: 'eeeeeeee-0000-4000-8000-000000000010',
    player_out_id: null,
    player_in_id: null,
    assist_player_id: null,
    minute: 12,
    added_minute: 0,
    segment_id: SEGMENT,
    metadata: null,
  };
}

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    initialized: true,
    status: 'live',
    revision: 4,
    content_revision: 2,
    events: [liveEvent()],
    home_score: 1,
    away_score: 0,
    clock: { state: 'paused', segment_id: SEGMENT, segment_number: 1, elapsed_us: 60_000_000, anchor_at: null, observed_at: '2026-11-15T10:02:00Z' },
    ...overrides,
  };
}

function access(overrides: Record<string, unknown> = {}) {
  return { can_view: true, can_operate: true, can_close: true, available: true, ...overrides };
}

function failure(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

function harness(overrides: {
  fetchAccess?: () => Promise<unknown>;
  fetchLive?: () => Promise<unknown>;
  current?: () => boolean;
  busy?: () => boolean;
} = {}) {
  const editor = createLiveEditorState();
  const applied: unknown[] = [];
  let deniedAccess = 0;
  let deniedLive = 0;
  let busyMarks = 0;
  let accessCalls = 0;
  let liveCalls = 0;
  const coordinator = createLiveContextCoordinator({
    isCurrent: () => (overrides.current ? overrides.current() : true),
    isBusy: () => (overrides.busy ? overrides.busy() : false),
    onBusy: () => { busyMarks += 1; },
    source: {
      fetchAccess: async () => {
        accessCalls += 1;
        return overrides.fetchAccess ? overrides.fetchAccess() : access();
      },
      fetchLive: async () => {
        liveCalls += 1;
        return overrides.fetchLive ? overrides.fetchLive() : snapshot();
      },
    },
    callbacks: {
      applyAccess: (caps) => applied.push(caps),
      applyLive: (value) => { applySharedSnapshot(editor, value); },
      denyAccess: () => { deniedAccess += 1; editor.shared = null; },
      denyLive: () => { deniedLive += 1; editor.shared = null; },
    },
  });
  return {
    coordinator,
    editor,
    applied,
    stats: () => ({ deniedAccess, deniedLive, busyMarks, accessCalls, liveCalls }),
  };
}

test('aviso durante escritura: la lectura se aplaza, no descarta ni cierra el editor', async () => {
  let busy = true;
  const { coordinator, stats } = harness({ busy: () => busy });
  const first = coordinator.request();
  await first;
  assert.equal(stats().liveCalls, 0);
  assert.equal(stats().busyMarks >= 1, true);
  // Al terminar la escritura, una nueva corrida sí trae el borrador.
  busy = false;
  await coordinator.request();
  assert.equal(stats().liveCalls, 1);
});

test('ráfaga de avisos produce una corrida y a lo sumo una trailing', async () => {
  let liveCallsSeen = 0;
  const { coordinator, stats } = harness({
    fetchLive: () => {
      liveCallsSeen += 1;
      // La primera lectura se resuelve en un microtask: los avisos posteriores
      // ya marcaron la corrida trailing; la segunda resuelve de inmediato.
      if (liveCallsSeen === 1) return new Promise((r) => { queueMicrotask(() => r(snapshot())); });
      return Promise.resolve(snapshot());
    },
  });
  const p1 = coordinator.request();
  const p2 = coordinator.request();
  const p3 = coordinator.request();
  await Promise.all([p1, p2, p3]);
  assert.equal(stats().accessCalls <= 2, true);
  assert.equal(stats().liveCalls <= 2, true);
});

test('respuesta vieja o fuera de contexto nunca se aplica ni restaura lo revocado', async () => {
  let current = true;
  const { coordinator, editor, applied } = harness({
    current: () => current,
    fetchLive: async () => {
      // La organización/identidad cambió mientras la lectura viajaba.
      current = false;
      return snapshot();
    },
  });
  await coordinator.request();
  assert.equal(applied.length, 1);
  assert.equal(editor.shared, null);
});

test('denegación de acceso limpia ambos; denegación del borrador solo limpia live', async () => {
  const { coordinator, editor, stats } = harness({ fetchAccess: async () => { throw failure(403); } });
  await coordinator.request();
  assert.equal(stats().deniedAccess, 1);
  assert.equal(stats().liveCalls, 0);
  const { coordinator: c2, editor: e2, stats: s2 } = harness({ fetchLive: async () => { throw failure(404); } });
  await c2.request();
  assert.equal(s2().deniedLive, 1);
  assert.equal(e2.shared, null);
});

test('un fallo no denegación conserva el estado vigente y se recupera por HTTP autorizado', async () => {
  let fail = true;
  const { coordinator, editor } = harness({
    fetchLive: async () => {
      if (fail) throw failure(500);
      return snapshot();
    },
  });
  await coordinator.request();
  assert.equal(editor.shared, null);
  fail = false;
  await coordinator.request();
  assert.equal(editor.shared!.events.length, 1);
  assert.equal(editor.shared!.revision, 4);
});

test('capacidades sin can_view nunca traen el borrador ni lo restauran', async () => {
  const { coordinator, editor, stats } = harness({ fetchAccess: async () => access({ can_view: false, can_operate: true }) });
  await coordinator.request();
  assert.equal(stats().liveCalls, 0);
  assert.equal(editor.shared, null);
});

test('retirada de lectura con OPERATE vigente limpia el borrador pero conserva operar', async () => {
  let caps = access();
  const { coordinator, editor, applied, stats } = harness({ fetchAccess: async () => caps });
  await coordinator.request();
  assert.equal(editor.shared!.events.length, 1);
  // La lectura se retira mientras OPERATE sigue vigente: solo cae el borrador.
  caps = access({ can_view: false });
  await coordinator.request();
  assert.equal(editor.shared, null);
  assert.equal(stats().deniedAccess, 1);
  assert.equal(stats().deniedLive, 0);
  const last = applied.at(-1) as { can_view: boolean; can_operate: boolean };
  assert.equal(last.can_view, false);
  assert.equal(last.can_operate, true);
});

test('A→B→A: una respuesta vieja de A no se aplica en B y volver a A reautoriza de nuevo', async () => {
  let current = true;
  let flips = 0;
  const { coordinator, editor, applied, stats } = harness({
    current: () => current,
    fetchLive: async () => {
      // El contexto cambia mientras la primera respuesta viaja hacia el cliente.
      flips += 1;
      if (flips === 1) current = false;
      return snapshot();
    },
  });
  await coordinator.request();
  assert.equal(stats().liveCalls, 1);
  assert.equal(editor.shared, null); // la respuesta vieja de A no se aplica en B
  // Volver a A reautoriza de nuevo: una solicitud fresca sí aplica.
  current = true;
  await coordinator.request();
  assert.equal(editor.shared!.revision, 4);
  assert.equal(applied.length, 2);
  // Una respuesta vieja denegada tampoco restaura el estado revocado.
  const c2 = harness({
    current: () => current,
    fetchAccess: async () => { current = false; throw failure(403); },
  });
  await c2.coordinator.request();
  assert.equal(c2.stats().deniedAccess, 0);
});

test('respuesta de acceso inválida equivale a denegación limpia', async () => {
  const { coordinator, stats } = harness({ fetchAccess: async () => ({ garbage: true }) });
  await coordinator.request();
  assert.equal(stats().deniedAccess, 1);
  assert.equal(stats().liveCalls, 0);
});
