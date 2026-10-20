import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createRealtimeDispatcher,
  parseResyncPayload,
  RESYNC_EVENT,
  type RealtimeDispatchHandlers,
  type ResyncPayload,
} from '../app/utils/realtimeDispatch.ts';
import { needsNewSocketSession } from '../app/utils/realtimeConnection.ts';
import {
  createEventDeduplicator,
  DEDUPE_WINDOW_LIMIT,
  readDeliveryId,
} from '../app/utils/realtimeDedup.ts';

function delivery(eventId: unknown): Record<string, unknown> {
  return { event_id: eventId, match_id: 'match-1' };
}

function recordingHandlers() {
  const calls = {
    events: [] as Array<[string, unknown]>,
    matchClosed: [] as unknown[],
    matchUpdated: [] as unknown[],
    standingsUpdated: [] as unknown[],
    resync: [] as ResyncPayload[],
  };
  const handlers: RealtimeDispatchHandlers = {
    onEvent: (event, payload) => calls.events.push([event, payload]),
    onMatchClosed: (payload) => calls.matchClosed.push(payload),
    onMatchUpdated: (payload) => calls.matchUpdated.push(payload),
    onStandingsUpdated: (payload) => calls.standingsUpdated.push(payload),
    onResync: (payload) => calls.resync.push(payload),
  };
  return { calls, handlers };
}

test('exposes a 200-identifier window constant', () => {
  assert.equal(DEDUPE_WINDOW_LIMIT, 200);
});

test('reads only a non-empty top-level string event_id', () => {
  assert.equal(readDeliveryId({ event_id: 'evt-1' }), 'evt-1');
  assert.equal(readDeliveryId({ event_id: null }), null);
  assert.equal(readDeliveryId({ event_id: '' }), null);
  assert.equal(readDeliveryId({ event_id: 7 }), null);
  assert.equal(readDeliveryId({ event_id: { nested: 'evt-1' } }), null);
  assert.equal(readDeliveryId({ meta: { event_id: 'evt-1' } }), null);
  assert.equal(readDeliveryId(null), null);
  assert.equal(readDeliveryId('evt-1'), null);
  assert.equal(readDeliveryId([]), null);
});

test('accepts the first delivery and rejects a duplicate', () => {
  const dedupe = createEventDeduplicator();

  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), false);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-2')), true);
});

test('does not use the event name as part of the deduplication key', () => {
  const dedupe = createEventDeduplicator();

  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true);
  assert.equal(dedupe.accept('STANDINGS_UPDATED', delivery('evt-1')), false);
});

test('accepts deliveries without a usable top-level event_id every time', () => {
  const dedupe = createEventDeduplicator();
  const payloads: unknown[] = [
    undefined,
    null,
    'evt-1',
    42,
    {},
    { event_id: null },
    { event_id: '' },
    { event_id: 123 },
    { event_id: { nested: 'evt-1' } },
    { meta: { event_id: 'evt-1' } },
  ];

  for (const payload of payloads) {
    assert.equal(dedupe.accept('MATCH_UPDATED', payload), true, JSON.stringify(payload));
    assert.equal(dedupe.accept('MATCH_UPDATED', payload), true, JSON.stringify(payload));
  }
});

test('evicts the oldest identifier with FIFO order', () => {
  const dedupe = createEventDeduplicator(3);

  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-a')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-b')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-c')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-a')), false);

  // The fourth distinct identifier evicts "evt-a"; "evt-b" and "evt-c" remain.
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-d')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-a')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-c')), false);
});

test('keeps the window bounded at 200 identifiers', () => {
  const dedupe = createEventDeduplicator();
  for (let index = 0; index < DEDUPE_WINDOW_LIMIT; index += 1) {
    assert.equal(dedupe.accept('MATCH_UPDATED', delivery(`evt-${index}`)), true);
  }

  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-0')), false);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-200')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-0')), true);
});

test('an explicit reset accepts a redelivery', () => {
  const dedupe = createEventDeduplicator();

  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), false);

  dedupe.reset();

  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true);
});

test('a new socket or scope key requires a new deduplication window', () => {
  // useRealtime vacía la ventana cuando needsNewSocketSession es verdadero
  // (llama a disconnect(false) antes de crear io(...)). El composable no se
  // puede montar en node:test: se prueba la decisión pura que lo gobierna.
  assert.equal(
    needsNewSocketSession({
      hasSocket: false,
      previousScopeKey: null,
      nextScopeKey: 'organization:org-a',
      publicScope: false,
      previousSessionVersion: -1,
      sessionVersion: 1,
    }),
    true,
  );

  // Organización A → organización B.
  assert.equal(
    needsNewSocketSession({
      hasSocket: true,
      previousScopeKey: 'organization:org-a',
      nextScopeKey: 'organization:org-b',
      publicScope: false,
      previousSessionVersion: 1,
      sessionVersion: 1,
    }),
    true,
  );

  // Público A → público B.
  assert.equal(
    needsNewSocketSession({
      hasSocket: true,
      previousScopeKey: 'public:tournament-a',
      nextScopeKey: 'public:tournament-b',
      publicScope: true,
      previousSessionVersion: 1,
      sessionVersion: 1,
    }),
    true,
  );

  // Un cambio de sesión en la misma organización exige socket nuevo.
  assert.equal(
    needsNewSocketSession({
      hasSocket: true,
      previousScopeKey: 'organization:org-a',
      nextScopeKey: 'organization:org-a',
      publicScope: false,
      previousSessionVersion: 1,
      sessionVersion: 2,
    }),
    true,
  );
});

test('disconnect and destroy empty the window', () => {
  for (const scenario of ['disconnect', 'destroy']) {
    const dedupe = createEventDeduplicator();
    assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true);
    assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), false);

    // useRealtime llama a reset() en disconnect() y, por tanto, al destruirse.
    dedupe.reset();

    assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true, scenario);
  }
});

test('an auto-reconnect keeps the same socket session and the dedupe window', () => {
  // Un auto-reconnect de Socket.IO no crea un socket lógico nuevo: no llama a
  // disconnect() ni vacía la ventana. useRealtime se cubre con typecheck/build
  // y revisión; aquí se prueba la decisión pura y la política del deduplicador.
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
    needsNewSocketSession({
      hasSocket: true,
      previousScopeKey: 'public:tournament-a',
      nextScopeKey: 'public:tournament-a',
      publicScope: true,
      previousSessionVersion: 1,
      sessionVersion: 2,
    }),
    false,
  );

  const dedupe = createEventDeduplicator();
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), true);
  assert.equal(dedupe.accept('MATCH_UPDATED', delivery('evt-1')), false);
});

test('a unique domain event invokes onEvent and its specific handler once', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });
  const payload = delivery('evt-1');

  dispatch('MATCH_UPDATED', payload);

  assert.deepEqual(calls.events, [['MATCH_UPDATED', payload]]);
  assert.deepEqual(calls.matchUpdated, [payload]);
  assert.deepEqual(calls.matchClosed, []);
  assert.deepEqual(calls.standingsUpdated, []);
  assert.deepEqual(calls.resync, []);
});

test('a duplicate domain event invokes no handler', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });

  dispatch('MATCH_UPDATED', delivery('evt-1'));
  dispatch('MATCH_UPDATED', delivery('evt-1'));

  assert.equal(calls.events.length, 1);
  assert.equal(calls.matchUpdated.length, 1);
});

test('events with different identifiers are both delivered', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });

  dispatch('MATCH_CLOSED', delivery('evt-1'));
  dispatch('MATCH_CLOSED', delivery('evt-2'));

  assert.equal(calls.events.length, 2);
  assert.equal(calls.matchClosed.length, 2);
});

test('a valid RESYNC goes only to onResync', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });
  const payload = { event_id: 'resync:1', reason: 'STREAM_TRIMMED', extra: 'ignored' };

  dispatch(RESYNC_EVENT, payload);

  assert.deepEqual(calls.resync, [{ event_id: 'resync:1', reason: 'STREAM_TRIMMED' }]);
  assert.deepEqual(calls.events, []);
  assert.deepEqual(calls.matchClosed, []);
  assert.deepEqual(calls.matchUpdated, []);
  assert.deepEqual(calls.standingsUpdated, []);
});

test('a repeated RESYNC with the same event_id is discarded', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });
  const payload = { event_id: 'resync:1', reason: 'JOIN' };

  dispatch(RESYNC_EVENT, payload);
  dispatch(RESYNC_EVENT, payload);

  assert.equal(calls.resync.length, 1);
});

test('an invalid RESYNC is discarded without invoking any handler', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });
  const invalidPayloads: unknown[] = [
    undefined,
    null,
    'RESYNC',
    {},
    { event_id: '', reason: 'JOIN' },
    { event_id: 7, reason: 'JOIN' },
    { event_id: 'resync:1' },
    { event_id: 'resync:1', reason: null },
    { event_id: 'resync:1', reason: 'UNKNOWN' },
    { event_id: { nested: 'resync:1' }, reason: 'JOIN' },
  ];

  for (const payload of invalidPayloads) {
    dispatch(RESYNC_EVENT, payload);
  }

  assert.deepEqual(calls.resync, []);
  assert.deepEqual(calls.events, []);
  assert.deepEqual(calls.matchClosed, []);
  assert.deepEqual(calls.matchUpdated, []);
  assert.deepEqual(calls.standingsUpdated, []);
});

test('a nested or non-string domain event_id is not used to deduplicate', () => {
  const { calls, handlers } = recordingHandlers();
  const dispatch = createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });
  const payloads: unknown[] = [
    { match_id: 'match-1', meta: { event_id: 'domain-id' } },
    { match_id: 'match-1', event_id: 123 },
  ];

  for (const payload of payloads) {
    dispatch('MATCH_UPDATED', payload);
    dispatch('MATCH_UPDATED', payload);
  }

  assert.equal(calls.events.length, 4);
});

test('parseResyncPayload validates the reason and the identifier', () => {
  assert.deepEqual(parseResyncPayload({ event_id: 'resync:1', reason: 'JOIN' }), {
    event_id: 'resync:1',
    reason: 'JOIN',
  });
  assert.equal(parseResyncPayload({ event_id: 'resync:1', reason: 'OTHER' }), null);
  assert.equal(parseResyncPayload({ event_id: '', reason: 'JOIN' }), null);
  assert.equal(parseResyncPayload({ reason: 'JOIN' }), null);
  assert.equal(parseResyncPayload(null), null);
});
