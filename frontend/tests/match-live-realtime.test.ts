import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createRealtimeDispatcher,
  parseLiveInvalidationPayload,
  parseResyncPayload,
  RESYNC_EVENT,
  type LiveInvalidationPayload,
  type RealtimeDispatchHandlers,
  type ResyncPayload,
} from '../app/utils/realtimeDispatch.ts';
import { createEventDeduplicator } from '../app/utils/realtimeDedup.ts';

const LIVE_PRIVATE = 'MATCH_LIVE_UPDATED';
const LIVE_PUBLIC = 'MATCH_LIVE_PUBLIC_UPDATED';

function liveDelivery(eventId = 'evt-live-1') {
  return {
    event_id: eventId,
    match_id: '31000000-0000-4000-8000-000000000050',
    tournament_id: '31000000-0000-4000-8000-000000000010',
  };
}

function recording() {
  const calls = {
    events: [] as Array<[string, unknown]>,
    matchClosed: [] as unknown[],
    matchUpdated: [] as unknown[],
    standingsUpdated: [] as unknown[],
    liveUpdated: [] as LiveInvalidationPayload[],
    livePublicUpdated: [] as LiveInvalidationPayload[],
    resync: [] as ResyncPayload[],
  };
  const handlers: RealtimeDispatchHandlers = {
    onEvent: (event, payload) => calls.events.push([event, payload]),
    onMatchClosed: (payload) => calls.matchClosed.push(payload),
    onMatchUpdated: (payload) => calls.matchUpdated.push(payload),
    onStandingsUpdated: (payload) => calls.standingsUpdated.push(payload),
    onMatchLiveUpdated: (payload) => calls.liveUpdated.push(payload),
    onMatchLivePublicUpdated: (payload) => calls.livePublicUpdated.push(payload),
    onResync: (payload) => calls.resync.push(payload),
  };
  return { calls, handlers };
}

function dispatcherOf(handlers: RealtimeDispatchHandlers) {
  return createRealtimeDispatcher({ dedupe: createEventDeduplicator(), handlers });
}

test('parseLiveInvalidationPayload exige los tres identificadores de entrega', () => {
  const parsed = parseLiveInvalidationPayload(liveDelivery());
  assert.deepEqual(parsed, {
    event_id: 'evt-live-1',
    match_id: '31000000-0000-4000-8000-000000000050',
    tournament_id: '31000000-0000-4000-8000-000000000010',
  });
  // Campos extra descartados: la señal no filtra datos del borrador.
  const withExtras = parseLiveInvalidationPayload({
    ...liveDelivery(),
    home_score: 3,
    clock_state: 'running',
    scope: 'organization',
  });
  assert.deepEqual(withExtras, parsed);
  for (const payload of [
    null,
    'x',
    [],
    {},
    { event_id: 'e', match_id: 'm' },
    { event_id: 'e', tournament_id: 't' },
    { event_id: '', match_id: 'm', tournament_id: 't' },
    { event_id: 'e', match_id: 7, tournament_id: 't' },
    { event_id: 'e', match_id: 'm', tournament_id: null },
    { event_id: 9, match_id: 'm', tournament_id: 't' },
  ]) {
    assert.equal(parseLiveInvalidationPayload(payload), null);
  }
});

test('enruta MATCH_LIVE_UPDATED al handler organizativo sin clonar la suscripción', () => {
  const { calls, handlers } = recording();
  const dispatch = dispatcherOf(handlers);
  dispatch(LIVE_PRIVATE, liveDelivery());
  dispatch(LIVE_PRIVATE, liveDelivery('evt-live-2'));
  assert.deepEqual(calls.liveUpdated.map((p) => p.event_id), ['evt-live-1', 'evt-live-2']);
  assert.equal(calls.livePublicUpdated.length, 0);
  assert.equal(calls.events.length, 2);
});

test('enruta MATCH_LIVE_PUBLIC_UPDATED al handler público sin clonar la suscripción', () => {
  const { calls, handlers } = recording();
  const dispatch = dispatcherOf(handlers);
  dispatch(LIVE_PUBLIC, liveDelivery());
  assert.equal(calls.livePublicUpdated.length, 1);
  assert.equal(calls.liveUpdated.length, 0);
});

test('la deduplicación corta entregas repetidas de ambas señales nuevas', () => {
  const { calls, handlers } = recording();
  const dispatch = dispatcherOf(handlers);
  const publicPayload = liveDelivery('evt-pub-1');
  const privatePayload = liveDelivery('evt-org-1');
  dispatch(LIVE_PUBLIC, publicPayload);
  dispatch(LIVE_PUBLIC, { ...publicPayload });
  dispatch(LIVE_PRIVATE, privatePayload);
  dispatch(LIVE_PRIVATE, { ...privatePayload });
  assert.equal(calls.livePublicUpdated.length, 1);
  assert.equal(calls.liveUpdated.length, 1);
  assert.equal(calls.events.length, 2);
});

test('payload vacío o desconocido no invoca el handler tipado pero sí onEvent', () => {
  const { calls, handlers } = recording();
  const dispatch = dispatcherOf(handlers);
  for (const payload of [null, undefined, {}, 'x', [], { match_id: 'm' }, liveDelivery('')]) {
    dispatch(LIVE_PRIVATE, payload);
    dispatch(LIVE_PUBLIC, payload);
  }
  assert.equal(calls.liveUpdated.length, 0);
  assert.equal(calls.livePublicUpdated.length, 0);
  // onEvent sí registra la llegada: el consumidor genérico decide.
  assert.equal(calls.events.length, 14);
});

test('un nombre desconocido solo llega a onEvent, nunca a handlers tipados', () => {
  const { calls, handlers } = recording();
  const dispatch = dispatcherOf(handlers);
  dispatch('SOMETHING_NEW', liveDelivery());
  assert.equal(calls.events.length, 1);
  assert.equal(calls.liveUpdated.length, 0);
  assert.equal(calls.livePublicUpdated.length, 0);
});

test('el catálogo antiguo y RESYNC se conservan intactos', () => {
  const { calls, handlers } = recording();
  const dispatch = dispatcherOf(handlers);
  dispatch('MATCH_CLOSED', { event_id: 'c1' });
  dispatch('MATCH_UPDATED', { event_id: 'u1' });
  dispatch('STANDINGS_UPDATED', { event_id: 's1' });
  dispatch(RESYNC_EVENT, { event_id: 'r1', reason: 'JOIN' });
  assert.equal(calls.matchClosed.length, 1);
  assert.equal(calls.matchUpdated.length, 1);
  assert.equal(calls.standingsUpdated.length, 1);
  assert.deepEqual(calls.resync, [{ event_id: 'r1', reason: 'JOIN' }]);
});

test('dos dispatcher con dedupe propio no duplican suscripciones ni se contaminan', () => {
  const first = recording();
  const second = recording();
  const dispatchA = dispatcherOf(first.handlers);
  const dispatchB = dispatcherOf(second.handlers);
  dispatchA(LIVE_PUBLIC, liveDelivery());
  dispatchB(LIVE_PUBLIC, liveDelivery());
  assert.equal(first.calls.livePublicUpdated.length, 1);
  assert.equal(second.calls.livePublicUpdated.length, 1);
});
