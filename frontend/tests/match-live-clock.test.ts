import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createLiveClock,
  displayedClock,
  clockPresentation,
} from '../app/utils/matchLiveClock.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const EVENT_ID = 'cccccccc-0000-4000-8000-000000000003';
const COMMAND_ID = 'dddddddd-0000-4000-8000-000000000004';

function liveEvent(overrides: Record<string, unknown> = {}) {
  return {
    client_event_id: EVENT_ID,
    event_type: 'goal',
    team_id: TEAM,
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

function snapshot(clock: Record<string, unknown>, overrides: Record<string, unknown> = {}) {
  return {
    initialized: true,
    status: 'live',
    revision: 4,
    content_revision: 2,
    events: [liveEvent()],
    home_score: 1,
    away_score: 0,
    clock,
    ...overrides,
  };
}

const NOW = new Date('2026-11-15T10:05:00Z');

test('sin iniciar muestra 0 sin inventar una referencia', () => {
  const clock = { state: 'not_started', segment_id: null, segment_number: null, elapsed_us: null, anchor_at: null, observed_at: '2026-11-15T10:00:00Z' };
  const view = displayedClock(clock, NOW);
  assert.equal(view.state, 'not_started');
  assert.equal(view.elapsedUs, 0);
  assert.equal(view.computed, false);
});

test('running acumula el anclaje aceptado más el tiempo transcurrido (cálculo visual)', () => {
  const clock = { state: 'running', segment_id: SEGMENT, segment_number: 1, elapsed_us: 60_000_000, anchor_at: '2026-11-15T10:00:00Z', observed_at: '2026-11-15T10:02:00Z' };
  const view = displayedClock(clock, NOW);
  // 60 s aceptados + 5 min desde anchor_at = 360_000_000 µs.
  assert.equal(view.elapsedUs, 360_000_000);
  assert.equal(view.computed, true);
  assert.equal(view.acceptedElapsedUs, 60_000_000);
});

test('paused muestra el acumulado aceptado sin avanzar', () => {
  const clock = { state: 'paused', segment_id: SEGMENT, segment_number: 1, elapsed_us: 90_000_000, anchor_at: null, observed_at: '2026-11-15T10:02:00Z' };
  const view = displayedClock(clock, NOW);
  assert.equal(view.elapsedUs, 90_000_000);
  assert.equal(view.computed, false);
});

test('la vista desactualizada se anuncia como stale, no como tiempo oficial', () => {
  const clock = { state: 'running', segment_id: SEGMENT, segment_number: 1, elapsed_us: 0, anchor_at: '2026-11-15T10:00:00Z', observed_at: '2026-11-15T10:02:00Z' };
  assert.equal(clockPresentation(clock, 'connected', NOW).stale, false);
  assert.equal(clockPresentation(clock, 'reconnecting', NOW).stale, true);
  assert.equal(clockPresentation(clock, 'error', NOW).stale, true);
});

function harness(overrides: { send?: (body: unknown) => Promise<unknown>; clock?: Record<string, unknown>; revision?: number } = {}) {
  const editor = createLiveEditorState();
  applySharedSnapshot(editor, snapshot(overrides.clock ?? { state: 'running', segment_id: SEGMENT, segment_number: 1, elapsed_us: 60_000_000, anchor_at: '2026-11-15T10:00:00Z', observed_at: '2026-11-15T10:02:00Z' }, overrides.revision !== undefined ? { revision: overrides.revision } : {}));
  const sent: unknown[] = [];
  let snapshots = 0;
  const clock = createLiveClock({
    send: async (body) => { sent.push(body); return overrides.send ? overrides.send(body) : { command_id: COMMAND_ID, revision: 5 }; },
    requestSnapshot: async () => { snapshots += 1; },
    editor,
    commandId: () => COMMAND_ID,
  });
  return { clock, editor, sent, snapshots: () => snapshots };
}

test('start_clock/pause_clock/resume_clock envían sus comandos con la revisión vigente', async () => {
  const { clock, sent } = harness();
  assert.equal(await clock.startClock(SEGMENT), 'sent');
  assert.equal(await clock.pauseClock(), 'sent');
  assert.equal(await clock.resumeClock(), 'sent');
  assert.deepEqual(sent.map((c) => (c as Record<string, unknown>).type), ['start_clock', 'pause_clock', 'resume_clock']);
  assert.equal((sent[0] as Record<string, unknown>).segment_id, SEGMENT);
  assert.equal((sent[0] as Record<string, unknown>).expected_revision, 4);
  assert.equal((sent[1] as Record<string, unknown>).expected_revision, 4);
});

test('correct_clock solo cambia la referencia; hechos y minutos se conservan', async () => {
  const { clock, editor, sent } = harness();
  const eventsBefore = editor.shared!.events.length;
  assert.equal(await clock.correctClock(SEGMENT, 95_000_000), 'sent');
  const command = sent[0] as Record<string, unknown>;
  assert.equal(command.type, 'correct_clock');
  assert.equal(command.segment_id, SEGMENT);
  assert.equal(command.elapsed_us, 95_000_000);
  // Nada del borrador cambia por corregir el reloj.
  assert.equal(editor.shared!.events.length, eventsBefore);
  assert.equal(editor.shared!.events[0]!.minute, 12);
});

test('correct_clock valida la entrada antes de enviar', async () => {
  const { clock, sent } = harness();
  for (const bad of [-1, 1.5, 'x', null] as const) {
    assert.equal(await clock.correctClock(SEGMENT, bad as never), 'invalid');
  }
  assert.equal(sent.length, 0);
});

test('errores se clasifican y el reloj mostrado no cambia ante fallo', async () => {
  const { clock, editor } = harness({ send: async () => { throw Object.assign(new Error('x'), { status: 409 }); } });
  assert.equal(await clock.pauseClock(), 'conflict');
  assert.equal(editor.shared!.clock.state, 'running');
});

test('sin compartido o en paralelo no envía', async () => {
  const editor = createLiveEditorState();
  const sent: unknown[] = [];
  const idle = createLiveClock({ send: async (b) => { sent.push(b); return {}; }, requestSnapshot: async () => {}, editor, commandId: () => COMMAND_ID });
  assert.equal(await idle.pauseClock(), 'unavailable');
  let resolve: ((v: unknown) => void) | null = null;
  const { clock } = harness({ send: () => new Promise((r) => { resolve = r; }) });
  const first = clock.pauseClock();
  assert.equal(await clock.resumeClock(), 'busy');
  resolve?.({ command_id: COMMAND_ID, revision: 5 });
  assert.equal(await first, 'sent');
});
