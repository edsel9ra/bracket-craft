import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createLiveEdit,
} from '../app/utils/matchLiveEdit.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const PLAYER = 'eeeeeeee-0000-4000-8000-000000000010';
const EVENT_ID = 'cccccccc-0000-4000-8000-000000000003';
const OTHER_EVENT_ID = 'abababab-0000-4000-8000-000000000005';
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

function snapshot(events: unknown[], revision = 4) {
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
  confirm?: (kind: string) => Promise<boolean>;
  revision?: number;
} = {}) {
  const editor = createLiveEditorState();
  applySharedSnapshot(editor, snapshot([eventForm()], overrides.revision ?? 4));
  const sent: unknown[] = [];
  const confirms: string[] = [];
  let snapshots = 0;
  const edit = createLiveEdit({
    send: async (body) => {
      sent.push(body);
      return overrides.send ? overrides.send(body) : { command_id: COMMAND_ID, revision: 5 };
    },
    requestSnapshot: async () => { snapshots += 1; },
    editor,
    confirm: async (kind) => {
      confirms.push(kind);
      return overrides.confirm ? overrides.confirm(kind) : true;
    },
    commandId: () => COMMAND_ID,
  });
  return { edit, editor, sent, confirms, snapshots: () => snapshots };
}

test('modificación válida pide confirmación y envía correct_event con la revisión vigente', async () => {
  const { edit, sent, confirms, snapshots } = harness();
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  const corrected = eventForm({ minute: 15 });
  assert.equal(await edit.saveEdit(corrected), 'sent');
  assert.deepEqual(confirms, ['correct']);
  const command = sent[0] as Record<string, unknown>;
  assert.equal(command.type, 'correct_event');
  assert.equal(command.event_id, EVENT_ID);
  assert.equal(command.expected_revision, 4);
  assert.equal((command.event as Record<string, unknown>).minute, 15);
  assert.equal(snapshots(), 1);
});

test('cancelar la confirmación no envía nada y conserva la edición abierta', async () => {
  const { edit, sent } = harness({ confirm: async () => false });
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  assert.equal(await edit.saveEdit(eventForm()), 'cancelled');
  assert.equal(sent.length, 0);
  // El texto de la edición no se pierde: la sesión sigue abierta.
  assert.notEqual(edit.editing(), null);
});

test('editar un hecho inexistente es missing; sin compartido es unavailable', async () => {
  const { edit } = harness();
  assert.equal(edit.beginEdit(OTHER_EVENT_ID), 'missing');
});

test('revisión obsoleta durante la edición exige revisar la base antes de guardar', async () => {
  const { edit, editor, sent } = harness();
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  // Otro operador avanzó la base mientras escribía: conflicto explícito.
  applySharedSnapshot(editor, snapshot([eventForm()], 5));
  edit.onSharedChanged();
  assert.equal(edit.editing()!.stale, true);
  assert.equal(await edit.saveEdit(eventForm({ minute: 20 })), 'stale');
  assert.equal(sent.length, 0);
  // Tras revisar la base vigente se puede guardar con la nueva revisión.
  assert.equal(edit.reviewBase(), true);
  assert.equal(edit.editing()!.stale, false);
  assert.equal(await edit.saveEdit(eventForm({ minute: 20 })), 'sent');
  assert.equal((sent[0] as Record<string, unknown>).expected_revision, 5);
});

test('un 409 del servidor marca la base obsoleta y conserva la edición', async () => {
  const { edit, sent } = harness({ send: async () => { throw failure(409); } });
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  assert.equal(await edit.saveEdit(eventForm()), 'conflict');
  assert.equal(edit.editing()!.stale, true);
  assert.equal(sent.length, 1);
});

test('hecho retirado por otro operador: la sesión lo señala sin perder el texto', async () => {
  const { edit, editor, sent } = harness();
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  applySharedSnapshot(editor, snapshot([eventForm({ client_event_id: OTHER_EVENT_ID })], 6));
  edit.onSharedChanged();
  assert.equal(edit.editing()!.removed, true);
  assert.equal(edit.editing()!.stale, true);
  assert.equal(await edit.saveEdit(eventForm()), 'stale');
  assert.equal(sent.length, 0);
});

test('retirar un hecho pide confirmación remove y envía remove_event', async () => {
  const { edit, sent, confirms } = harness();
  assert.equal(await edit.removeFact(EVENT_ID), 'sent');
  assert.deepEqual(confirms, ['remove']);
  const command = sent[0] as Record<string, unknown>;
  assert.equal(command.type, 'remove_event');
  assert.equal(command.event_id, EVENT_ID);
  assert.equal(command.expected_revision, 4);
});

test('retirar sin confirmar o un hecho ausente no envía', async () => {
  const { edit, sent } = harness({ confirm: async () => false });
  assert.equal(await edit.removeFact(EVENT_ID), 'cancelled');
  assert.equal(await edit.removeFact(OTHER_EVENT_ID), 'missing');
  assert.equal(sent.length, 0);
});

test('saveEdit valida la forma y clasifica errores como la captura', async () => {
  const { edit, sent } = harness();
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  assert.equal(await edit.saveEdit(eventForm({ minute: 400 })), 'invalid');
  assert.equal(sent.length, 0);
  const { edit: denied } = harness({ send: async () => { throw failure(403); } });
  assert.equal(denied.beginEdit(EVENT_ID), 'ok');
  assert.equal(await denied.saveEdit(eventForm()), 'denied');
});

test('un ack ajeno no acredita la corrección', async () => {
  const { edit, editor } = harness({ send: async () => ({ command_id: 'otro', revision: 5 }) });
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  assert.equal(await edit.saveEdit(eventForm()), 'error');
  assert.equal(editor.pending.length, 0);
});

test('single-flight: guardar en paralelo devuelve busy', async () => {
  let resolveSend: ((v: unknown) => void) | null = null;
  const { edit, sent } = harness({
    send: () => new Promise((resolve) => { resolveSend = resolve; }),
  });
  assert.equal(edit.beginEdit(EVENT_ID), 'ok');
  const first = edit.saveEdit(eventForm());
  assert.equal(await edit.saveEdit(eventForm()), 'busy');
  resolveSend?.({ command_id: COMMAND_ID, revision: 5 });
  assert.equal(await first, 'sent');
  assert.equal(sent.length, 1);
});
