import assert from 'node:assert/strict';
import test from 'node:test';

import {
  classifyCaptureFailure,
  createLiveCapture,
  validateLiveEventForm,
} from '../app/utils/matchLiveCapture.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const PLAYER = 'eeeeeeee-0000-4000-8000-000000000010';
const EVENT_ID = 'cccccccc-0000-4000-8000-000000000003';
const COMMAND_ID = 'dddddddd-0000-4000-8000-000000000004';

function eventForm(overrides: Record<string, unknown> = {}) {
  return {
    client_event_id: EVENT_ID,
    event_type: 'goal',
    team_id: TEAM,
    beneficiary_team_id: null,
    player_id: PLAYER,
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

function snapshotWithEvents(events: unknown[], revision = 4) {
  return {
    initialized: true,
    status: 'live',
    revision,
    content_revision: revision,
    events,
    home_score: 1,
    away_score: 0,
    clock: {
      state: 'running',
      segment_id: SEGMENT,
      segment_number: 1,
      elapsed_us: 120000000,
      anchor_at: '2026-11-15T10:00:00Z',
      observed_at: '2026-11-15T10:02:00Z',
    },
  };
}

function failure(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

function harness(overrides: {
  send?: (body: unknown) => Promise<unknown>;
  revision?: number;
} = {}) {
  const editor = createLiveEditorState();
  if (overrides.revision !== undefined) {
    applySharedSnapshot(editor, snapshotWithEvents([], overrides.revision));
  }
  const sent: unknown[] = [];
  let snapshots = 0;
  const capture = createLiveCapture({
    send: async (body) => {
      sent.push(body);
      return overrides.send ? overrides.send(body) : { command_id: COMMAND_ID, revision: 5 };
    },
    requestSnapshot: async () => { snapshots += 1; },
    editor,
    commandId: () => COMMAND_ID,
  });
  return { capture, editor, sent, snapshots: () => snapshots };
}

test('validateLiveEventForm acepta un hecho completo del catálogo', () => {
  assert.notEqual(validateLiveEventForm(eventForm()), null);
});

test('validateLiveEventForm rechaza campos vacíos, catálogo inválido y reglas estructurales', () => {
  const invalids = [
    eventForm({ client_event_id: '' }),
    eventForm({ client_event_id: 'no-es-uuid' }),
    eventForm({ event_type: 'corner' }),
    eventForm({ event_type: '' }),
    eventForm({ team_id: '' }),
    eventForm({ team_id: 'x' }),
    eventForm({ player_id: null }),
    eventForm({ minute: -1 }),
    eventForm({ minute: 181 }),
    eventForm({ minute: 3.5 }),
    eventForm({ added_minute: 31 }),
    eventForm({ segment_id: '' }),
    eventForm({ segment_id: 'x' }),
    // Sustitución sin pareja completa.
    eventForm({ event_type: 'substitution', player_out_id: null, player_in_id: PLAYER }),
    eventForm({ event_type: 'substitution', player_out_id: PLAYER, player_in_id: PLAYER }),
    // Pareja de sustitución en otro tipo.
    eventForm({ player_out_id: PLAYER, player_in_id: PLAYER }),
    // Autogol sin beneficiario distinto.
    eventForm({ event_type: 'own_goal', beneficiary_team_id: null }),
    eventForm({ event_type: 'own_goal', beneficiary_team_id: TEAM }),
    // beneficiario fuera de autogol.
    eventForm({ beneficiary_team_id: TEAM }),
    // Asistencia solo en gol y distinta del goleador.
    eventForm({ assist_player_id: PLAYER }),
    eventForm({ event_type: 'foul', assist_player_id: PLAYER }),
    // metadata solo con red_card_type y solo en tarjeta roja.
    eventForm({ metadata: { red_card_type: 'direct_red' } }),
    eventForm({ event_type: 'red_card', metadata: { red_card_type: 'otro' } }),
    eventForm({ metadata: { otra_clave: 1 } }),
    // Claves no declaradas (extra=forbid).
    (() => { const f = eventForm(); (f as Record<string, unknown>).extra = 1; return f; })(),
  ];
  for (const raw of invalids) {
    assert.equal(validateLiveEventForm(raw), null, JSON.stringify(raw));
  }
  // Válidos equivalentes.
  assert.notEqual(validateLiveEventForm(eventForm({ event_type: 'substitution', player_out_id: PLAYER, player_in_id: 'ffffffff-0000-4000-8000-000000000099', player_id: PLAYER })), null);
  assert.notEqual(validateLiveEventForm(eventForm({ event_type: 'red_card', metadata: { red_card_type: 'double_yellow_red' } })), null);
  assert.notEqual(validateLiveEventForm(eventForm({ event_type: 'own_goal', beneficiary_team_id: 'ffffffff-0000-4000-8000-000000000099' })), null);
});

test('captura válida envía add_event, guarda ack y espera snapshot autorizado', async () => {
  const { capture, editor, sent, snapshots } = harness({ revision: 4 });
  assert.equal(await capture.capture(eventForm()), 'sent');
  assert.equal(sent.length, 1);
  const command = sent[0] as Record<string, unknown>;
  assert.equal(command.command_id, COMMAND_ID);
  assert.equal(command.expected_revision, 4);
  assert.equal(command.type, 'add_event');
  // El hecho queda pendiente hasta que el snapshot lo devuelve aceptado.
  assert.equal(editor.pending.length, 1);
  assert.equal(snapshots(), 1);
});

test('el formulario se conserva ante fallo: nada sale de él', async () => {
  const { capture, editor } = harness({ revision: 4, send: async () => { throw failure(500); } });
  const form = eventForm();
  assert.equal(await capture.capture(form), 'error');
  // El util nunca toca el objeto del formulario: queda como estaba.
  assert.equal(form.minute, 12);
  assert.equal(editor.pending.length, 0);
});

test('409 y denegaciones se clasifican sin sanitizar contenido del servidor', async () => {
  for (const [status, expected] of [[409, 'conflict'], [401, 'denied'], [403, 'denied'], [404, 'denied'], [0, 'error'], [500, 'error']] as const) {
    const { capture } = harness({ revision: 4, send: async () => { throw failure(status); } });
    assert.equal(await capture.capture(eventForm()), expected, `status ${status}`);
  }
});

test('doble activación en paralelo solo envía una vez (single-flight)', async () => {
  let resolveSend: ((v: unknown) => void) | null = null;
  const { capture, sent } = harness({
    revision: 4,
    send: () => new Promise((resolve) => { resolveSend = resolve; }),
  });
  const first = capture.capture(eventForm());
  const second = capture.capture(eventForm({ client_event_id: 'abababab-0000-4000-8000-000000000005' }));
  assert.equal(await second, 'busy');
  resolveSend?.({ command_id: COMMAND_ID, revision: 5 });
  assert.equal(await first, 'sent');
  assert.equal(sent.length, 1);
});

test('un reintento del mismo hecho no lo duplica: pendiente ya registrado', async () => {
  const { capture, editor, sent, snapshots } = harness({ revision: 4 });
  assert.equal(await capture.capture(eventForm()), 'sent');
  // Reintento: mismo client_event_id pendiente → no repite el POST.
  assert.equal(await capture.capture(eventForm()), 'sent');
  assert.equal(sent.length, 1);
  assert.equal(snapshots(), 2);
  // Y si ya está aceptado en el compartido, tampoco.
  applySharedSnapshot(editor, snapshotWithEvents([eventForm()], 6));
  assert.equal(await capture.capture(eventForm()), 'accepted');
  assert.equal(sent.length, 1);
});

test('sin snapshot compartido no se captura nada', async () => {
  const { capture, sent } = harness();
  assert.equal(await capture.capture(eventForm()), 'unavailable');
  assert.equal(sent.length, 0);
});

test('un ack malformado o ajeno es error, no aceptación', async () => {
  for (const ack of [null, {}, { command_id: 'otro', revision: 5 }, { command_id: COMMAND_ID, revision: 'x' }]) {
    const { capture, editor } = harness({ revision: 4, send: async () => ack });
    assert.equal(await capture.capture(eventForm()), 'error');
    assert.equal(editor.pending.length, 0);
  }
});
