import assert from 'node:assert/strict';
import test from 'node:test';

import { isReconnection, needsNewSocketSession } from '../app/utils/realtimeConnection.ts';
import { createEventDeduplicator } from '../app/utils/realtimeDedup.ts';
import {
  appendedPageSlice,
  createInitializationTracker,
  createInitializationWindow,
  createReconnectJoinController,
  createReloadCoordinator,
  createRequestGeneration,
  decideReload,
  firstPageSlice,
  INITIALIZATION_GRACE_MS,
  PUBLIC_FIRST_PAGE_OFFSET,
  RECONNECT_JOIN_GRACE_MS,
  resyncTrigger,
  shouldPollPublicRealtime,
  type ReloadConsumer,
} from '../app/utils/realtimeReload.ts';

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function fakeScheduler() {
  const scheduled: Array<{ callback: () => void; delay: number; cancelled: boolean }> = [];

  return {
    scheduled,
    schedule(callback: () => void, delay: number) {
      const entry = { callback, delay, cancelled: false };
      scheduled.push(entry);
      return entry;
    },
    cancel(handle: unknown) {
      (handle as { cancelled: boolean }).cancelled = true;
    },
    run(entry: { callback: () => void; cancelled: boolean }) {
      if (!entry.cancelled) entry.callback();
    },
  };
}

test('an initial connection is not a reconnection', () => {
  assert.equal(
    isReconnection({ hasConnectedOnce: false, previousStatus: 'connecting', nextStatus: 'connected' }),
    false,
  );
});

test('a successful connection after reconnecting or an error is a reconnection', () => {
  assert.equal(
    isReconnection({ hasConnectedOnce: true, previousStatus: 'reconnecting', nextStatus: 'connected' }),
    true,
  );
  assert.equal(
    isReconnection({ hasConnectedOnce: true, previousStatus: 'error', nextStatus: 'connected' }),
    true,
  );
});

test('a connected status without a previous connection or a loss is not a reconnection', () => {
  assert.equal(
    isReconnection({ hasConnectedOnce: true, previousStatus: 'connected', nextStatus: 'connected' }),
    false,
  );
  assert.equal(
    isReconnection({ hasConnectedOnce: false, previousStatus: 'reconnecting', nextStatus: 'connected' }),
    false,
  );
  assert.equal(
    isReconnection({ hasConnectedOnce: true, previousStatus: 'reconnecting', nextStatus: 'error' }),
    false,
  );
});

test('a reconnection keeps the socket session and the deduplication window', () => {
  // El auto-reconnect de Socket.IO no crea un socket lógico nuevo:
  // needsNewSocketSession es falso, useRealtime no llama a disconnect() y la
  // ventana de deduplicación sobrevive. useRealtime no se monta en node:test.
  assert.equal(
    needsNewSocketSession({
      hasSocket: true,
      previousScopeKey: 'organization:org-a',
      nextScopeKey: 'organization:org-a',
      publicScope: false,
      previousSessionVersion: 1,
      sessionVersion: 1,
    }),
    false,
  );
  assert.equal(
    isReconnection({
      hasConnectedOnce: true,
      previousStatus: 'reconnecting',
      nextStatus: 'connected',
    }),
    true,
  );

  const dedupe = createEventDeduplicator();
  assert.equal(dedupe.accept('MATCH_UPDATED', { event_id: 'evt-1' }), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', { event_id: 'evt-1' }), false);
});

test('domain events reload both consumers', () => {
  const consumers: ReloadConsumer[] = ['workspace', 'public'];

  for (const consumer of consumers) {
    assert.deepEqual(
      decideReload({
        consumer,
        trigger: 'event',
        initialized: true,
        initializedWithJoin: true,
      }),
      { action: 'reload', resetPagination: false },
    );
  }
});

test('a reconnection reloads only the workspace', () => {
  assert.deepEqual(
    decideReload({
      consumer: 'workspace',
      trigger: 'reconnect',
      initialized: true,
      initializedWithJoin: true,
    }),
    { action: 'reload', resetPagination: false },
  );
  assert.deepEqual(
    decideReload({
      consumer: 'public',
      trigger: 'reconnect',
      initialized: true,
      initializedWithJoin: true,
    }),
    { action: 'none', resetPagination: false },
  );
});

test('a JOIN during the initialization window completes the initial load', () => {
  for (const consumer of ['workspace', 'public'] as ReloadConsumer[]) {
    assert.deepEqual(
      decideReload({
        consumer,
        trigger: 'resync-join',
        initialized: false,
        initializedWithJoin: false,
      }),
      { action: 'initial', resetPagination: false },
    );
  }
});

test('a JOIN after initializing reloads the workspace and the public page ignores it', () => {
  assert.deepEqual(
    decideReload({
      consumer: 'workspace',
      trigger: 'resync-join',
      initialized: true,
      initializedWithJoin: true,
    }),
    { action: 'reload', resetPagination: false },
  );
  assert.deepEqual(
    decideReload({
      consumer: 'public',
      trigger: 'resync-join',
      initialized: true,
      initializedWithJoin: true,
    }),
    { action: 'none', resetPagination: false },
  );
});

test('a JOIN after the grace closes the initialization once for both consumers', () => {
  for (const consumer of ['workspace', 'public'] as ReloadConsumer[]) {
    assert.deepEqual(
      decideReload({
        consumer,
        trigger: 'resync-join',
        initialized: true,
        initializedWithJoin: false,
      }),
      { action: 'reload', resetPagination: false },
    );
  }
});

test('a gap resync reloads and resets pagination for both consumers', () => {
  for (const consumer of ['workspace', 'public'] as ReloadConsumer[]) {
    assert.deepEqual(
      decideReload({
        consumer,
        trigger: 'resync-gap',
        initialized: true,
        initializedWithJoin: true,
      }),
      { action: 'reload', resetPagination: true },
    );
  }
});

test('the initialization grace is 1500 ms and closes the window without a JOIN', () => {
  assert.equal(INITIALIZATION_GRACE_MS, 1500);

  const tracker = createInitializationTracker();
  assert.equal(tracker.initialized, false);
  assert.equal(tracker.initializedWithJoin, false);

  tracker.close();

  assert.equal(tracker.initialized, true);
  assert.equal(tracker.initializedWithJoin, false);
  // La carga HTTP ya se hizo: el primer JOIN posterior la completa una vez.
  assert.deepEqual(
    decideReload({
      consumer: 'workspace',
      trigger: 'resync-join',
      initialized: tracker.initialized,
      initializedWithJoin: tracker.initializedWithJoin,
    }),
    { action: 'reload', resetPagination: false },
  );
});

test('the first JOIN closes the window without a second initial load', () => {
  const tracker = createInitializationTracker();

  // El consumidor decide antes de marcar el JOIN: no hay recarga adicional.
  assert.deepEqual(
    decideReload({
      consumer: 'workspace',
      trigger: 'resync-join',
      initialized: tracker.initialized,
      initializedWithJoin: tracker.initializedWithJoin,
    }),
    { action: 'initial', resetPagination: false },
  );

  tracker.acceptJoin();

  assert.equal(tracker.initialized, true);
  assert.equal(tracker.initializedWithJoin, true);

  tracker.close();
  assert.equal(tracker.initializedWithJoin, true);

  tracker.reset();
  assert.equal(tracker.initialized, false);
  assert.equal(tracker.initializedWithJoin, false);
});

test('runs one reload at a time and keeps a single accumulated trailing reload', async () => {
  const calls: boolean[] = [];
  const gates = [deferred(), deferred()];
  const coordinator = createReloadCoordinator(({ resetPagination }) => {
    calls.push(resetPagination);
    return gates[calls.length - 1]!.promise;
  });

  const first = coordinator.request();
  const second = coordinator.request();
  const third = coordinator.request({ resetPagination: true });
  const fourth = coordinator.request({ resetPagination: false });

  assert.equal(calls.length, 1);
  assert.equal(coordinator.inFlight, true);
  assert.deepEqual(calls, [false]);

  gates[0]!.resolve();
  await settle();

  // Varias solicitudes dejan una sola trailing; el reset es acumulativo
  // aunque la última solicitud no lo pida.
  assert.deepEqual(calls, [false, true]);
  assert.equal(coordinator.inFlight, true);

  gates[1]!.resolve();
  await Promise.all([first, second, third, fourth]);

  assert.deepEqual(calls, [false, true]);
  assert.equal(coordinator.inFlight, false);
});

test('a trailing reset is accumulated when the trailing trigger changes', async () => {
  const calls: boolean[] = [];
  const gate = deferred();
  const coordinator = createReloadCoordinator(({ resetPagination }) => {
    calls.push(resetPagination);
    if (calls.length === 1) return gate.promise;
    return Promise.resolve();
  });

  const first = coordinator.request({ resetPagination: false });
  coordinator.request({ resetPagination: true });
  coordinator.request({ resetPagination: false });

  gate.resolve();
  await first;

  assert.deepEqual(calls, [false, true]);
});

test('a failed reload keeps the state and schedules no automatic retry', async () => {
  let calls = 0;
  const coordinator = createReloadCoordinator(async () => {
    calls += 1;
    throw new Error('reload failed');
  });

  await coordinator.request();
  await settle();

  assert.equal(calls, 1);
  assert.equal(coordinator.inFlight, false);
});

test('a reload after a failure is possible but never automatic', async () => {
  let calls = 0;
  let shouldFail = true;
  const coordinator = createReloadCoordinator(async () => {
    calls += 1;
    if (shouldFail) throw new Error('reload failed');
  });

  await coordinator.request();
  await settle();
  assert.equal(calls, 1);

  shouldFail = false;
  await coordinator.request();

  assert.equal(calls, 2);
});

test('a public JOIN inside the window never issues a second initial load', () => {
  const tracker = createInitializationTracker();

  assert.deepEqual(
    decideReload({
      consumer: 'public',
      trigger: resyncTrigger('JOIN'),
      initialized: tracker.initialized,
      initializedWithJoin: tracker.initializedWithJoin,
    }),
    { action: 'initial', resetPagination: false },
  );

  tracker.acceptJoin();

  // Un JOIN posterior a la inicialización se ignora en público.
  assert.deepEqual(
    decideReload({
      consumer: 'public',
      trigger: resyncTrigger('JOIN'),
      initialized: tracker.initialized,
      initializedWithJoin: tracker.initializedWithJoin,
    }),
    { action: 'none', resetPagination: false },
  );
});

test('each gap reason reloads the public page and resets pagination', () => {
  for (const reason of ['STREAM_TRIMMED', 'REDIS_RESET', 'RELAY_START']) {
    assert.equal(resyncTrigger(reason), 'resync-gap');
    assert.deepEqual(
      decideReload({
        consumer: 'public',
        trigger: resyncTrigger(reason),
        initialized: true,
        initializedWithJoin: true,
      }),
      { action: 'reload', resetPagination: true },
      reason,
    );
  }
});

test('the public first page starts at offset 0 and discards appended pages', () => {
  const pageSize = 2;
  const firstPage = [{ id: 'a' }, { id: 'b' }];
  const secondPage = [{ id: 'c' }, { id: 'd' }];

  const appended = appendedPageSlice(firstPage, secondPage, pageSize);
  assert.deepEqual(appended.items.map((item) => item.id), ['a', 'b', 'c', 'd']);
  assert.equal(appended.hasMore, true);

  assert.equal(PUBLIC_FIRST_PAGE_OFFSET, 0);
  const reset = firstPageSlice(firstPage, pageSize);
  assert.deepEqual(reset.items.map((item) => item.id), ['a', 'b']);
  assert.equal(reset.hasMore, true);

  const shortFirstPage = firstPageSlice(firstPage.slice(0, 1), pageSize);
  assert.deepEqual(shortFirstPage.items.map((item) => item.id), ['a']);
  assert.equal(shortFirstPage.hasMore, false);
});

test('a reset discards an in-flight page load and leaves a single trailing reload', async () => {
  const generation = createRequestGeneration();
  const pageLoad = generation.next();
  const reload = generation.next();

  // La recarga invalida la página que estaba en curso.
  assert.equal(generation.isCurrent(pageLoad), false);
  assert.equal(generation.isCurrent(reload), true);

  const calls: boolean[] = [];
  const gate = deferred();
  const coordinator = createReloadCoordinator(({ resetPagination }) => {
    calls.push(resetPagination);
    if (calls.length === 1) return gate.promise;
    return Promise.resolve();
  });

  const first = coordinator.request({ resetPagination: true });
  coordinator.request({ resetPagination: true });
  gate.resolve();
  await first;

  assert.deepEqual(calls, [true, true]);
});

test('the grace closes the public initialization and a later JOIN reloads once', () => {
  const tracker = createInitializationTracker();
  tracker.close();

  // La carga HTTP ya cerró la ventana; no se bloquea la página.
  assert.equal(tracker.initialized, true);
  assert.equal(tracker.initializedWithJoin, false);

  assert.deepEqual(
    decideReload({
      consumer: 'public',
      trigger: 'resync-join',
      initialized: tracker.initialized,
      initializedWithJoin: tracker.initializedWithJoin,
    }),
    { action: 'reload', resetPagination: false },
  );

  tracker.acceptJoin();

  assert.deepEqual(
    decideReload({
      consumer: 'public',
      trigger: 'resync-join',
      initialized: tracker.initialized,
      initializedWithJoin: tracker.initializedWithJoin,
    }),
    { action: 'none', resetPagination: false },
  );
});

test('public polling runs only while the socket is not connected', () => {
  assert.equal(shouldPollPublicRealtime('connected'), false);

  for (const status of ['idle', 'connecting', 'reconnecting', 'retrying', 'error']) {
    assert.equal(shouldPollPublicRealtime(status), true, status);
  }
});

test('the manual retry keeps the public polling while the attempt is in progress', () => {
  // Mientras dura el estado manual la vista sigue actualizándose por HTTP como
  // en error (RF-002): el estado manual no congela los datos ni duplica el
  // refresco. La reconexión posterior usa la política ya cubierta arriba.
  assert.equal(shouldPollPublicRealtime('retrying'), true);
});

test('a reconnection JOIN cancels the fallback and reloads exactly once', () => {
  const scheduler = fakeScheduler();
  let reloads = 0;
  const controller = createReconnectJoinController(
    () => {
      reloads += 1;
    },
    scheduler.schedule,
    scheduler.cancel,
  );

  controller.arm();
  controller.scheduleFallback();

  assert.equal(controller.waiting, true);
  const fallback = scheduler.scheduled[0]!;
  assert.equal(fallback.delay, RECONNECT_JOIN_GRACE_MS);

  // El JOIN posterior a la reconexión consume la espera y cancela el respaldo.
  assert.equal(controller.acceptJoin(), 'reconnect');
  assert.equal(fallback.cancelled, true);
  scheduler.run(fallback);

  assert.equal(reloads, 0);
  assert.equal(controller.waiting, false);

  // Una reentrega del JOIN no vuelve a recargar.
  assert.equal(controller.acceptJoin(), 'handled');
  assert.equal(reloads, 0);
});

test('without a JOIN the fallback reloads exactly once and a late JOIN is ignored', () => {
  const scheduler = fakeScheduler();
  let reloads = 0;
  const controller = createReconnectJoinController(
    () => {
      reloads += 1;
    },
    scheduler.schedule,
    scheduler.cancel,
  );

  controller.arm();
  assert.equal(scheduler.scheduled.length, 0);

  controller.scheduleFallback();
  scheduler.run(scheduler.scheduled[0]!);

  assert.equal(reloads, 1);
  assert.equal(controller.waiting, false);

  // El JOIN que llega tarde encuentra la recarga de respaldo ya hecha.
  assert.equal(controller.acceptJoin(), 'handled');
  assert.equal(reloads, 1);
});

test('the fallback is only scheduled after a reconnection is pending', () => {
  const scheduler = fakeScheduler();
  let reloads = 0;
  const controller = createReconnectJoinController(
    () => {
      reloads += 1;
    },
    scheduler.schedule,
    scheduler.cancel,
  );

  controller.scheduleFallback();

  assert.equal(scheduler.scheduled.length, 0);
  assert.equal(controller.waiting, false);
  assert.equal(reloads, 0);
});

test('arming again or resetting cancels the pending fallback', () => {
  const scheduler = fakeScheduler();
  let reloads = 0;
  const controller = createReconnectJoinController(
    () => {
      reloads += 1;
    },
    scheduler.schedule,
    scheduler.cancel,
  );

  controller.arm();
  controller.scheduleFallback();
  const first = scheduler.scheduled[0]!;

  controller.arm();
  assert.equal(first.cancelled, true);
  assert.equal(controller.waiting, true);

  controller.scheduleFallback();
  const second = scheduler.scheduled[1]!;

  controller.reset();
  assert.equal(second.cancelled, true);
  scheduler.run(first);
  scheduler.run(second);
  assert.equal(reloads, 0);
  assert.equal(controller.waiting, false);
});

test('a JOIN without a pending reconnection falls through to the normal policy', () => {
  const scheduler = fakeScheduler();
  let reloads = 0;
  const controller = createReconnectJoinController(
    () => {
      reloads += 1;
    },
    scheduler.schedule,
    scheduler.cancel,
  );

  assert.equal(controller.acceptJoin(), 'none');
  assert.equal(controller.waiting, false);
  assert.equal(reloads, 0);
  assert.equal(scheduler.scheduled.length, 0);
});

test('the initialization grace starts with the connection attempt and closes without a JOIN', () => {
  const scheduler = fakeScheduler();
  const initialization = createInitializationWindow(scheduler.schedule, scheduler.cancel);

  // Se inicia al intentar conectar, no al recibir `connected`.
  initialization.start();
  const timer = scheduler.scheduled[0]!;
  assert.equal(timer.delay, INITIALIZATION_GRACE_MS);
  assert.equal(initialization.initialized, false);

  scheduler.run(timer);

  assert.equal(initialization.initialized, true);
  assert.equal(initialization.initializedWithJoin, false);
});

test('a JOIN during initialization cancels the grace timer', () => {
  const scheduler = fakeScheduler();
  const initialization = createInitializationWindow(scheduler.schedule, scheduler.cancel);

  initialization.start();
  const timer = scheduler.scheduled[0]!;

  initialization.acceptJoin();

  assert.equal(timer.cancelled, true);
  scheduler.run(timer);
  assert.equal(initialization.initialized, true);
  assert.equal(initialization.initializedWithJoin, true);
});

test('the first JOIN after the grace produces exactly one workspace reload', async () => {
  const scheduler = fakeScheduler();
  const initialization = createInitializationWindow(scheduler.schedule, scheduler.cancel);
  initialization.start();
  scheduler.run(scheduler.scheduled[0]!);

  const decision = decideReload({
    consumer: 'workspace',
    trigger: 'resync-join',
    initialized: initialization.initialized,
    initializedWithJoin: initialization.initializedWithJoin,
  });

  let reloads = 0;
  const coordinator = createReloadCoordinator(async () => {
    reloads += 1;
  });
  if (decision.action === 'reload') {
    await coordinator.request({ resetPagination: decision.resetPagination });
  }

  assert.deepEqual(decision, { action: 'reload', resetPagination: false });
  assert.equal(reloads, 1);
});
