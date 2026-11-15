import assert from 'node:assert/strict';
import test from 'node:test';

import { createLiveTransitions, isDraftEditable } from '../app/utils/matchLiveTransitions.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const COMMAND_ID = 'dddddddd-0000-4000-8000-000000000004';

function eventForm() {
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

function snapshot(status: string, overrides: Record<string, unknown> = {}) {
  const running = status === 'live';
  return {
    initialized: true,
    status,
    revision: 4,
    content_revision: 2,
    events: [eventForm()],
    home_score: 1,
    away_score: 0,
    clock: {
      state: running ? 'running' : 'paused',
      segment_id: running ? SEGMENT : SEGMENT,
      segment_number: 1,
      elapsed_us: 60_000_000,
      anchor_at: running ? '2026-11-15T10:00:00Z' : null,
      observed_at: '2026-11-15T10:02:00Z',
    },
    ...overrides,
  };
}

function failure(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { status });
}

function harness(overrides: {
  send?: (body: unknown) => Promise<unknown>;
  confirm?: (kind: string) => Promise<boolean>;
  resolve?: () => Promise<'proceed' | 'cancelled'>;
  status?: string;
  matchStatus?: string;
} = {}) {
  const editor = createLiveEditorState();
  if (overrides.status) applySharedSnapshot(editor, snapshot(overrides.status));
  const sent: unknown[] = [];
  const confirms: string[] = [];
  let resolves = 0;
  const transitions = createLiveTransitions({
    send: async (body) => {
      sent.push(body);
      return overrides.send ? overrides.send(body) : { command_id: COMMAND_ID, revision: 5 };
    },
    requestSnapshot: async () => {},
    editor,
    commandId: () => COMMAND_ID,
    confirm: async (kind) => {
      confirms.push(kind);
      return overrides.confirm ? overrides.confirm(kind) : true;
    },
    resolveLocalDraft: async () => {
      resolves += 1;
      return overrides.resolve ? overrides.resolve() : 'proceed';
    },
    matchStatus: () => overrides.matchStatus ?? 'scheduled',
  });
  return { transitions, editor, sent, confirms, resolves: () => resolves };
}

test('start sobre programado resuelve el borrador local, confirma y envía', async () => {
  const { transitions, sent, confirms, resolves } = harness();
  assert.equal(await transitions.start(), 'sent');
  assert.equal(resolves(), 1);
  assert.deepEqual(confirms, ['start']);
  const command = sent[0] as Record<string, unknown>;
  assert.equal(command.type, 'start');
  assert.equal(command.expected_revision, 0);
  assert.equal(command.command_id, COMMAND_ID);
});

test('start sin borrador resuelto no inicia ni envía', async () => {
  const { transitions, sent } = harness({ resolve: async () => 'cancelled' });
  assert.equal(await transitions.start(), 'cancelled');
  assert.equal(sent.length, 0);
});

test('start se rechaza cuando el partido ya está live o es terminal', async () => {
  const { transitions, sent } = harness({ status: 'live' });
  assert.equal(await transitions.start(), 'invalid');
  for (const terminal of ['finished', 'cancelled', 'administrative_resolution']) {
    const { transitions: t2, sent: s2 } = harness({ matchStatus: terminal });
    assert.equal(await t2.start(), 'invalid');
    assert.equal(s2.length, 0);
  }
  assert.equal(sent.length, 0);
});

test('suspend solo desde live; confirma y envía suspend', async () => {
  const { transitions, sent, confirms } = harness({ status: 'live' });
  assert.equal(await transitions.suspend(), 'sent');
  assert.deepEqual(confirms, ['suspend']);
  assert.equal((sent[0] as Record<string, unknown>).type, 'suspend');
  const { transitions: scheduled } = harness();
  assert.equal(await scheduled.suspend(), 'invalid');
});

test('resume desde suspended: no arranca reloj ni crea segmento', async () => {
  const { transitions, sent } = harness({ status: 'suspended' });
  assert.equal(await transitions.resume(), 'sent');
  // Solo el comando resume: nada de start_clock ni segmento nuevo.
  assert.equal(sent.length, 1);
  const command = sent[0] as Record<string, unknown>;
  assert.equal(command.type, 'resume');
  assert.equal(command.segment_id, undefined);
});

test('cancelar la confirmación no envía nada', async () => {
  for (const [fn, status] of [['suspend', 'live'], ['resume', 'suspended']] as const) {
    const { transitions, sent } = harness({ status, confirm: async () => false });
    assert.equal(await transitions[fn](), 'cancelled');
    assert.equal(sent.length, 0);
  }
});

test('durante suspended el borrador no admite captura ni control', () => {
  assert.equal(isDraftEditable('live'), true);
  assert.equal(isDraftEditable('suspended'), false);
  assert.equal(isDraftEditable('finished'), false);
  assert.equal(isDraftEditable('scheduled'), false);
});

test('error HTTP y ocupado se clasifican sin cambiar estado', async () => {
  const { transitions } = harness({ send: async () => { throw failure(409); }, status: 'live' });
  assert.equal(await transitions.suspend(), 'conflict');
  let resolve: ((v: unknown) => void) | null = null;
  const { transitions: busy } = harness({ status: 'live', send: () => new Promise((r) => { resolve = r; }) });
  const first = busy.suspend();
  assert.equal(await busy.resume(), 'busy');
  resolve?.({ command_id: COMMAND_ID, revision: 5 });
  assert.equal(await first, 'sent');
});
