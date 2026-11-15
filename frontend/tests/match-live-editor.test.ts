import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ackPendingEvents,
  applySharedSnapshot,
  createLiveEditorState,
  isAcceptedEvent,
  liveEditorMode,
  markPendingEvent,
  normalizeLiveSnapshot,
  type SharedLiveDraft,
} from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM_HOME = 'aaaaaaaa-0000-4000-8000-000000000001';
const TEAM_AWAY = 'bbbbbbbb-0000-4000-8000-000000000002';

function clock(overrides: Record<string, unknown> = {}) {
  return {
    state: 'running',
    segment_id: SEGMENT,
    segment_number: 1,
    elapsed_us: 120000000,
    anchor_at: '2026-11-15T10:00:00Z',
    observed_at: '2026-11-15T10:02:00Z',
    ...overrides,
  };
}

function liveEvent(overrides: Record<string, unknown> = {}) {
  return {
    client_event_id: 'cccccccc-0000-4000-8000-000000000003',
    event_type: 'goal',
    team_id: TEAM_HOME,
    beneficiary_team_id: null,
    player_id: null,
    player_out_id: null,
    player_in_id: null,
    assist_player_id: null,
    minute: 12,
    added_minute: 0,
    segment_id: SEGMENT,
    metadata: null,
    ...overrides,
  };
}

function initialized(overrides: Record<string, unknown> = {}) {
  return {
    initialized: true,
    status: 'live',
    revision: 4,
    content_revision: 2,
    events: [liveEvent()],
    home_score: 1,
    away_score: 0,
    clock: clock(),
    ...overrides,
  };
}

test('un snapshot F1 completo se normaliza como borrador compartido', () => {
  const shared = normalizeLiveSnapshot(initialized());
  assert.notEqual(shared, null);
  assert.equal(shared!.status, 'live');
  assert.equal(shared!.revision, 4);
  assert.equal(shared!.contentRevision, 2);
  assert.equal(shared!.homeScore, 1);
  assert.equal(shared!.awayScore, 0);
  assert.equal(shared!.clock.state, 'running');
  assert.equal(shared!.events.length, 1);
  assert.equal(shared!.events[0]!.clientEventId, 'cccccccc-0000-4000-8000-000000000003');
});

test('snapshot inicializado vacío se muestra vacío, no inventa incidencias', () => {
  const shared = normalizeLiveSnapshot(initialized({ events: [], home_score: 0, away_score: 0 }));
  assert.notEqual(shared, null);
  assert.equal(shared!.events.length, 0);
  assert.equal(liveEditorMode(shared), 'live');
});

test('snapshot sin inicializar es modo clásico y no admite borrador', () => {
  assert.equal(normalizeLiveSnapshot({ initialized: false, status: 'scheduled' }), null);
  assert.equal(liveEditorMode(null), 'classic');
  // Un sin-inicializar con restos es inválido, no un borrador clásico.
  assert.equal(normalizeLiveSnapshot({ initialized: false, status: 'scheduled', events: [liveEvent()], revision: 1 }), null);
});

test('respuestas malformadas o incoherentes se descartan completas', () => {
  for (const raw of [
    null,
    'live',
    [],
    {},
    { initialized: true, status: 'live' }, // sin revisiones/reloj/marcador
    initialized({ revision: -1 }),
    initialized({ content_revision: '2' }),
    initialized({ home_score: 1.5 }),
    initialized({ status: 'live', clock: clock({ state: 'paused', anchor_at: '2026-11-15T10:00:00Z' }) }),
    initialized({ clock: clock({ anchor_at: '2026-11-15T12:00:00+02:00' }) }), // no UTC
    initialized({ events: [{ garbage: true }] }),
    initialized({ events: [liveEvent({ minute: -3 })] }),
    initialized({ events: [liveEvent({ extra_field: 1 })] }),
    initialized({ extra_top_level: true }),
  ]) {
    assert.equal(normalizeLiveSnapshot(raw), null, JSON.stringify(raw).slice(0, 120));
  }
});

test('clock coherente por estado: running exige anchor_at; not_started lo prohíbe', () => {
  assert.notEqual(normalizeLiveSnapshot(initialized({ clock: clock({ state: 'paused', anchor_at: null }) })), null);
  assert.notEqual(normalizeLiveSnapshot(initialized({
    status: 'suspended',
    clock: clock({ state: 'not_started', segment_id: null, segment_number: null, elapsed_us: null, anchor_at: null }),
  })), null);
  assert.equal(normalizeLiveSnapshot(initialized({ clock: clock({ state: 'not_started', segment_id: null }) })), null);
});

test('el estado separa aceptados del servidor y pendientes locales', () => {
  const state = createLiveEditorState();
  // Modo clásico: sin snapshot ni pendientes.
  assert.equal(liveEditorMode(state.shared), 'classic');

  const accepted = liveEvent({ client_event_id: 'dddddddd-0000-4000-8000-000000000004' });
  assert.equal(applySharedSnapshot(state, initialized({ events: [accepted] })), true);
  assert.equal(isAcceptedEvent(state.shared, 'dddddddd-0000-4000-8000-000000000004'), true);

  // Un hecho local recién capturado no es aceptado hasta que llega por HTTP.
  const local = liveEvent({ client_event_id: 'eeeeeeee-0000-4000-8000-000000000005' });
  markPendingEvent(state, local);
  assert.equal(state.pending.length, 1);
  assert.equal(isAcceptedEvent(state.shared, 'eeeeeeee-0000-4000-8000-000000000005'), false);

  // Cuando el snapshot autorizado lo trae, sale de pendientes y pasa a aceptado.
  assert.equal(applySharedSnapshot(state, initialized({ revision: 5, events: [accepted, local] })), true);
  assert.equal(state.pending.length, 0);
  assert.equal(isAcceptedEvent(state.shared, 'eeeeeeee-0000-4000-8000-000000000005'), true);
});

test('una respuesta inválida conserva los pendientes y limpia lo compartido', () => {
  const state = createLiveEditorState();
  markPendingEvent(state, liveEvent());
  assert.equal(applySharedSnapshot(state, { garbage: true }), false);
  assert.equal(state.shared, null);
  assert.equal(state.pending.length, 1);
});

test('los pendientes se pueden reconocer por id y retirar explícitamente', () => {
  const state = createLiveEditorState();
  markPendingEvent(state, liveEvent({ client_event_id: 'f1f1f1f1-0000-4000-8000-000000000006' }));
  markPendingEvent(state, liveEvent({ client_event_id: 'f2f2f2f2-0000-4000-8000-000000000007' }));
  ackPendingEvents(state, ['f1f1f1f1-0000-4000-8000-000000000006']);
  assert.equal(state.pending.length, 1);
  assert.equal(state.pending[0]!.clientEventId, 'f2f2f2f2-0000-4000-8000-000000000007');
});
