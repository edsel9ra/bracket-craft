import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { computed, reactive, ref, watch } from 'vue';
import * as connection from '../app/utils/realtimeConnection.ts';
import * as dedup from '../app/utils/realtimeDedup.ts';
import * as dispatch from '../app/utils/realtimeDispatch.ts';
import * as reload from '../app/utils/realtimeReload.ts';
import * as retry from '../app/utils/realtimeRetry.ts';
import * as validation from '../app/utils/validation.ts';
import * as api from '../app/utils/api.ts';
import type { useRealtime } from '../app/composables/useRealtime.ts';
import type { useMatchOperation } from '../app/composables/useMatchOperation.ts';
import type { useTournamentsStore } from '../app/stores/tournaments.ts';

function load<T>(file: string, modules: Record<string, unknown>, globals: Record<string, unknown>): T {
  const exports = {};
  const source = readFileSync(new URL(`../app/${file}`, import.meta.url), 'utf8')
    .replaceAll('import.meta.server', 'false').replaceAll('import.meta.client', 'true').replaceAll('import.meta.dev', 'true');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, require: (name: string) => { assert.ok(name in modules, name); return modules[name]; }, ...globals,
  });
  return exports as T;
}

const ORG = '51000000-0000-4000-8000-000000000001';
const OTHER = '52000000-0000-4000-8000-000000000001';
type Listener = (...args: unknown[]) => void;

function socketHarness() {
  const auth = reactive<{ userId: string | null; sessionVersion: number }>({ userId: ORG, sessionVersion: 1 });
  const organization = ref<string | null>(ORG);
  const timers: Array<() => void> = [];
  const sockets: Array<ReturnType<typeof newSocket>> = [];
  const cleanups: Array<() => void> = [];
  function newSocket() {
    const events = new Map<string, Listener>();
    const manager = new Map<string, Listener>();
    return { events, manager, any: (() => {}) as Listener,
      on: (name: string, handler: Listener) => events.set(name, handler),
      onAny(handler: Listener) { this.any = handler; },
      io: { on: (name: string, handler: Listener) => manager.set(name, handler) },
      disconnect: () => events.get('disconnect')?.('io client disconnect'),
    };
  }
  const { useRealtime: use } = load<{ useRealtime: typeof useRealtime }>('composables/useRealtime.ts', {
    'socket.io-client': { io: () => { const socket = newSocket(); sockets.push(socket); return socket; } },
    '~/utils/realtimeConnection': connection, '~/utils/realtimeDedup': dedup,
    '~/utils/realtimeDispatch': dispatch, '~/utils/realtimeReload': reload,
    '~/utils/realtimeRetry': retry, '~/utils/validation': validation,
  }, { ref, computed, watch, useRuntimeConfig: () => ({ public: { socketBase: 'http://socket.test' } }),
    useAuthStore: () => auth, useCookie: () => organization,
    onScopeDispose: (callback: () => void) => cleanups.push(callback),
    setTimeout: (callback: () => void) => { timers.push(callback); return timers.length; }, clearTimeout: () => {},
  });
  return { auth, organization, sockets, timers, realtime: use(), dispose: () => cleanups.forEach(fn => fn()) };
}

test('old socket callbacks, manager callbacks and timers cannot touch a new context; ABA invalidates HTTP', () => {
  const h = socketHarness();
  const received: unknown[] = [];
  h.realtime.connect({ onEvent: (...args) => received.push(args), onResync: value => received.push(value),
    onReconnect: () => received.push('reconnect'), onError: value => received.push(value) });
  const original = h.sockets[0]!;
  const isCurrent = h.realtime.captureContext();
  original.events.get('connect')!();
  h.organization.value = OTHER;
  assert.equal(h.sockets.length, 2);
  h.organization.value = ORG;
  assert.equal(h.sockets.length, 3);
  assert.equal(isCurrent(), false);
  for (const callback of original.events.values()) callback('obsolete');
  for (const callback of original.manager.values()) callback();
  original.any('RESYNC', { event_id: 'old', reason: 'RELAY_START' });
  original.any('MATCH_UPDATED', { event_id: 'old-domain' });
  for (const callback of [...h.timers]) callback();
  assert.equal(h.realtime.status.value, 'connecting');
  assert.equal(received.length, 0);
  const current = h.sockets.at(-1)!;
  current.events.get('connect')!();
  current.any('MATCH_UPDATED', { event_id: 'current', match_id: ORG, tournament_id: ORG });
  current.any('MATCH_UPDATED', { event_id: 'current', match_id: ORG, tournament_id: ORG });
  assert.equal(received.length, 1);
  h.dispose();
  current.any('RESYNC', { event_id: 'disposed', reason: 'RELAY_START' });
  assert.equal(received.length, 1);
});

test('identity changes replace private sockets, not public sockets or their callbacks', () => {
  const h = socketHarness();
  h.realtime.connect();
  h.auth.userId = OTHER;
  assert.equal(h.sockets.length, 2);
  h.realtime.connect({}, { tournamentId: ORG });
  const count = h.sockets.length;
  h.auth.sessionVersion++;
  h.auth.userId = ORG;
  assert.equal(h.sockets.length, count);
  h.sockets.at(-1)!.events.get('connect')!();
  assert.equal(h.realtime.status.value, 'connected');
  h.dispose();
});

test('empty identity cancels private context and rejects callbacks from the previous socket', () => {
  const h = socketHarness();
  const events: unknown[] = [];
  h.realtime.connect({ onEvent: event => events.push(event) });
  const previous = h.sockets[0]!;
  const isCurrent = h.realtime.captureContext();
  h.auth.userId = null;
  assert.equal(h.sockets.length, 1);
  assert.equal(h.realtime.status.value, 'idle');
  assert.equal(isCurrent(), false);
  previous.any('MATCH_UPDATED', { event_id: 'late' });
  assert.equal(events.length, 0);
  h.dispose();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

function operationHarness() {
  let version = 0;
  const requests: Array<ReturnType<typeof deferred<unknown>>> = [];
  const navigations: unknown[] = [];
  const state = {
    route: { fullPath: '/workspace/matches/m' }, auth: { userId: ORG, organizationId: ORG, sessionVersion: 1, logout: async () => {} },
    request: () => { const pending = deferred<unknown>(); requests.push(pending); return pending.promise; },
    t: (key: string) => key, errorMessage: (_cause: unknown, fallback: string) => fallback,
    realtime: { initialization: { initialized: true, initializedWithJoin: true }, contextKey: ref(ORG),
      captureContext: () => { const captured = version; return () => captured === version; },
      disconnect() { version++; }, connect() {},
    },
    matchId: 'm', operation: ref<unknown>(null), busyAction: ref<string | null>(null),
    isTerminal: ref(true), error: ref(null), actionError: ref(null), openingBlocked: ref(null),
    selectedSegmentId: ref(''), draftEvents: ref([{ local: 'preserved' }]), segmentForm: {}, interruptionForm: {}, officialForm: {},
    eventForm: {}, eventFieldIssues: ref({}), closeForm: {},
  };
  const modules: Record<string, unknown> = {
    '~/composables/useMatchOperationState': { useMatchOperationState: () => state },
    '~/composables/useMatchClose': { useMatchClose: () => ({}) },
    '~/composables/useMatchLineup': { useMatchLineup: () => ({ applyOperation: (value: unknown) => { state.operation.value = value; } }) },
    '~/composables/useMatchEventsDraft': { useMatchEventsDraft: () => ({}) },
    '~/composables/useMatchEvents': { useMatchEvents: () => ({ clearEventFieldIssues() {} }) },
    '~/utils/api': api, '~/utils/realtimeReload': reload,
  };
  for (const name of ['matchResolution', 'matchSegments', 'rosterLimits', 'matchDraft', 'navigation', 'requestBodies', 'substitutions']) modules[`~/utils/${name}`] = {};
  modules['~/utils/matchResolution'] = { classifyMatchConflict: () => null };
  modules['~/utils/navigation'] = { safeInternalRedirect: (path: string) => path };
  const exports = load<{ useMatchOperation: typeof useMatchOperation }>('composables/useMatchOperation.ts', modules,
    { watch, useHead: () => {}, onBeforeRouteLeave: () => {},
      navigateTo: async (target: unknown) => { navigations.push(target); }, window: { removeEventListener() {} } });
  return { operation: exports.useMatchOperation(), state, requests, navigations, changeContext: (key?: string) => {
    version++;
    if (key !== undefined) state.realtime.contextKey.value = key;
  } };
}

for (const failure of [false, true]) {
  test(`failed organization switch restores the mounted match with fresh HTTP, not stale responses (error=${failure})`, async () => {
    const h = operationHarness();
    h.state.operation.value = { original: true };
    h.operation.requestOperationReload('resync-gap');
    h.changeContext(OTHER);
    assert.equal(h.state.operation.value, null);
    h.operation.requestOperationReload('resync-gap');
    assert.equal(h.requests.length, 1);
    h.changeContext(ORG);
    if (failure) h.requests[0]!.reject({ statusCode: 403 });
    else h.requests[0]!.resolve({ stale: true });
    await settle();
    assert.equal(h.requests.length, 2);
    assert.equal(h.state.operation.value, null);
    assert.equal(h.navigations.length, 0);
    h.requests[1]!.resolve({ restored: true });
    await settle();
    assert.deepEqual(h.state.operation.value, { restored: true });
    h.operation.requestOperationReload('resync-gap');
    assert.equal(h.requests.length, 3);
    h.requests[2]!.resolve({ current: true });
    await settle();
    assert.deepEqual(h.state.operation.value, { current: true });
  });
}

test('terminal operations reload by HTTP from minimal invalidations, without discarding local draft', async () => {
  const h = operationHarness();
  h.operation.requestOperationReload('event', { event_id: 'e', match_id: 'other', tournament_id: ORG });
  assert.equal(h.requests.length, 0);
  h.operation.requestOperationReload('event', { event_id: 'e', match_id: 'm', tournament_id: ORG });
  assert.equal(h.requests.length, 1);
  h.requests[0]!.resolve({ terminal: 'fresh' });
  await settle();
  assert.deepEqual(h.state.operation.value, { terminal: 'fresh' });
  assert.deepEqual(h.state.draftEvents.value, [{ local: 'preserved' }]);
});

for (const failed of [false, true]) {
  test(`busy action consolidates invalidations/RESYNC into one trailing authorized read (failure=${failed})`, async () => {
    const h = operationHarness();
    const pending = deferred<undefined>();
    const action = h.operation.runAction('save', () => pending.promise);
    h.operation.requestOperationReload('resync-gap');
    h.operation.requestOperationReload('event');
    assert.equal(h.requests.length, 0);
    if (failed) pending.reject(new Error('conflict')); else pending.resolve(undefined);
    await action;
    assert.equal(h.requests.length, 1);
    h.requests[0]!.resolve({ fresh: true });
    await settle();
    assert.deepEqual(h.state.operation.value, { fresh: true });
    assert.deepEqual(h.state.draftEvents.value, [{ local: 'preserved' }]);
  });
}

for (const staleFailure of [false, true]) {
  test(`context change discards old HTTP result and error (error=${staleFailure})`, async () => {
    const h = operationHarness();
    h.operation.requestOperationReload('resync-gap');
    assert.equal(h.requests.length, 1);
    h.changeContext();
    if (staleFailure) h.requests[0]!.reject({ statusCode: 403 }); else h.requests[0]!.resolve({ secret: true });
    await settle();
    assert.equal(h.state.operation.value, null);
    assert.equal(h.state.actionError.value, null);
    assert.equal(h.navigations.length, 0);
  });
}

test('unmount cancels trailing intent and an active denial clears previously readable operation', async () => {
  const h = operationHarness();
  h.state.operation.value = { previous: true };
  h.operation.requestOperationReload('resync-gap');
  h.requests[0]!.reject({ statusCode: 403 });
  await settle();
  assert.equal(h.state.operation.value, null);
  const pending = deferred<undefined>();
  const action = h.operation.runAction('save', () => pending.promise);
  h.operation.requestOperationReload('resync-gap');
  h.operation.unmountOperation();
  pending.resolve(undefined);
  await action;
  assert.equal(h.requests.length, 1);
});

test('busy trailing intent cannot cross identity/organization context', async () => {
  const h = operationHarness();
  const pending = deferred<undefined>();
  const action = h.operation.runAction('save', () => pending.promise);
  h.operation.requestOperationReload('resync-gap');
  h.changeContext();
  pending.resolve(undefined);
  await action;
  assert.equal(h.requests.length, 0);
});

test('an older HTTP refresh or a response after unmount cannot overwrite current state', async () => {
  const h = operationHarness();
  const first = h.operation.refreshOperation();
  const second = h.operation.refreshOperation();
  h.requests[1]!.resolve({ latest: true });
  await second;
  h.requests[0]!.resolve({ obsolete: true });
  await first;
  assert.deepEqual(h.state.operation.value, { latest: true });
  const final = h.operation.refreshOperation();
  h.operation.unmountOperation();
  h.requests[2]!.resolve({ obsolete: true });
  await final;
  assert.deepEqual(h.state.operation.value, { latest: true });
});

function workspaceHarness() {
  const auth = reactive({ userId: ORG, sessionVersion: 1 });
  const organizationId = ref<string | null>(ORG);
  const requests: Array<ReturnType<typeof deferred<unknown>>> = [];
  const exports = load<{ useTournamentsStore: () => ReturnType<typeof useTournamentsStore> }>('stores/tournaments.ts', {
    pinia: { defineStore: (_name: string, setup: () => unknown) => setup }, '~/utils/api': api,
  }, { ref, watch, useAuthStore: () => auth,
    useApi: () => ({ organizationId, request: () => { const value = deferred<unknown>(); requests.push(value); return value.promise; } }),
    useI18n: () => ({ t: (key: string) => key, errorMessage: (_cause: unknown, fallback: string) => fallback }),
  });
  // El arnés conserva refs, a diferencia del desenvolvimiento automático de Pinia.
  const store = exports.useTournamentsStore() as unknown as {
    load: () => Promise<void>; loadPublic: () => Promise<void>;
    tournaments: { value: unknown[] }; publicTournaments: { value: unknown[] }; error: { value: unknown };
  };
  return { auth, organizationId, requests, store };
}

for (const statusCode of [401, 403, 404]) {
  test(`Workspace removes previously authorized list when HTTP rejects reloading (${statusCode})`, async () => {
    const h = workspaceHarness();
    const initial = h.store.load();
    h.requests[0]!.resolve([{ id: 'readable' }]);
    await initial;
    assert.equal(h.store.tournaments.value.length, 1);
    const refresh = h.store.load();
    const denied = { statusCode };
    h.requests[1]!.reject(denied);
    await assert.rejects(refresh, failure => failure === denied);
    assert.equal(h.store.tournaments.value.length, 0);
  });
}

for (const staleError of [false, true]) {
  test(`Workspace drops previous identity/organization responses and errors, including ABA (${staleError})`, async () => {
    const h = workspaceHarness();
    const old = h.store.load();
    h.organizationId.value = OTHER;
    h.organizationId.value = ORG;
    if (staleError) h.requests[0]!.reject({ statusCode: 401 }); else h.requests[0]!.resolve([{ secret: true }]);
    await old;
    assert.equal(h.store.tournaments.value.length, 0);
    assert.equal(h.store.error.value, null);
    const identityOld = h.store.load();
    h.auth.userId = OTHER;
    h.requests[1]!.resolve([{ secret: true }]);
    await identityOld;
    assert.equal(h.store.tournaments.value.length, 0);
  });
}

test('Workspace empty/error cases do not change public state or accept out-of-order results', async () => {
  const h = workspaceHarness();
  const publicLoad = h.store.loadPublic();
  h.requests[0]!.resolve([{ id: 'public' }]);
  await publicLoad;
  const old = h.store.load();
  const current = h.store.load();
  h.requests[2]!.resolve([]);
  await current;
  h.requests[1]!.resolve([{ secret: true }]);
  await old;
  assert.equal(h.store.tournaments.value.length, 0);
  h.auth.sessionVersion++;
  assert.equal(h.store.publicTournaments.value.length, 1);
  const offline = h.store.load();
  h.requests[3]!.reject({ statusCode: 503 });
  await offline;
  assert.equal(h.store.error.value, 'workspace.noLoad');
});
