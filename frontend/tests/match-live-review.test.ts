import assert from 'node:assert/strict';
import test from 'node:test';

import { createLiveReview, reviewModel } from '../app/utils/matchLiveReview.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const REVIEW_ID = 'bbbbbbbb-0000-4000-8000-000000000002';
const EVENT_A = 'cccccccc-0000-4000-8000-000000000003';
const EVENT_B = 'cccccccc-0000-4000-8000-000000000004';
const PLAYER = 'eeeeeeee-0000-4000-8000-000000000010';

function liveEvent(overrides: Record<string, unknown> = {}) {
  return {
    client_event_id: EVENT_A,
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

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    initialized: true,
    status: 'live',
    revision: 4,
    content_revision: 2,
    events: [liveEvent(), liveEvent({ client_event_id: EVENT_B, minute: 30 })],
    home_score: 1,
    away_score: 0,
    clock: { state: 'running', segment_id: SEGMENT, segment_number: 1, elapsed_us: 60_000_000, anchor_at: '2026-11-15T10:00:00Z', observed_at: '2026-11-15T10:02:00Z' },
    ...overrides,
  };
}

function resultForm() {
  return {
    resolution_type: 'regular',
    home_score_regular: 1,
    away_score_regular: 0,
    home_score: 1,
    away_score: 0,
    home_penalties: null,
    away_penalties: null,
    winner_team_id: null,
    reason: null,
  };
}

function reviewResponse(overrides: Record<string, unknown> = {}) {
  return {
    live_review_id: REVIEW_ID,
    content_revision: 2,
    report: {
      resolution_type: 'regular',
      home_score: 1,
      away_score: 0,
      events: [liveEvent(), liveEvent({ client_event_id: EVENT_B, minute: 30 })],
    },
    fingerprint: 'fp-2',
    ...overrides,
  };
}

test('la revisión muestra el conjunto vigente completo, orden del servidor', () => {
  const editor = createLiveEditorState();
  applySharedSnapshot(editor, snapshot());
  const model = reviewModel(editor.shared!);
  assert.equal(model.events.length, 2);
  assert.deepEqual(model.events.map((e) => e.clientEventId), [EVENT_A, EVENT_B]);
  assert.equal(model.homeScore, 1);
  assert.equal(model.empty, false);
});

test('borrador vacío se muestra vacío, sin inventar incidencias', () => {
  const editor = createLiveEditorState();
  applySharedSnapshot(editor, snapshot({ events: [], home_score: 0 }));
  const model = reviewModel(editor.shared!);
  assert.equal(model.events.length, 0);
  assert.equal(model.empty, true);
  assert.equal(model.homeScore, 0);
});

function harness(overrides: { send?: (body: unknown) => Promise<unknown>; contentRevision?: number } = {}) {
  const editor = createLiveEditorState();
  applySharedSnapshot(editor, snapshot(overrides.contentRevision !== undefined ? { content_revision: overrides.contentRevision } : {}));
  const sent: unknown[] = [];
  const review = createLiveReview({
    sendReview: async (body) => {
      sent.push(body);
      return overrides.send ? overrides.send(body) : reviewResponse();
    },
    editor,
  });
  return { review, editor, sent };
}

test('beginReview envía expected_content_revision y result sin hechos del cliente', async () => {
  const { review, sent } = harness();
  assert.equal(await review.beginReview(resultForm()), 'reviewed');
  const body = sent[0] as Record<string, unknown>;
  assert.equal(body.expected_content_revision, 2);
  const result = body.result as Record<string, unknown>;
  assert.equal(result.resolution_type, 'regular');
  assert.equal('events' in result, false);
  assert.equal('live_review_id' in result, false);
  assert.equal(review.currentReceipt()!.liveReviewId, REVIEW_ID);
});

test('receipt vigente solo con el content_revision revisado: un cambio real exige nuevo recibo', async () => {
  const { review, editor } = harness();
  await review.beginReview(resultForm());
  assert.equal(review.receiptValid(), true);
  // El reloj avanza (revision +1, content_revision igual): NO invalida.
  applySharedSnapshot(editor, snapshot({ revision: 5 }));
  assert.equal(review.receiptValid(), true);
  // Un cambio real de hechos/resultado (content_revision nuevo): inválida.
  applySharedSnapshot(editor, snapshot({ revision: 6, content_revision: 3 }));
  assert.equal(review.receiptValid(), false);
});

test('sin compartido o entradas inválidas no envía', async () => {
  const editor = createLiveEditorState();
  const sent: unknown[] = [];
  const review = createLiveReview({ sendReview: async (b) => { sent.push(b); return {}; }, editor });
  assert.equal(await review.beginReview(resultForm()), 'unavailable');
  const { review: r2 } = harness();
  for (const bad of [{ ...resultForm(), resolution_type: 'otro' }, { ...resultForm(), home_score: -1 }, { ...resultForm(), extra: 1 }]) {
    assert.equal(await r2.beginReview(bad as never), 'invalid');
  }
  assert.equal(sent.length, 0);
});

test('errores se clasifican y el recibo anterior no se sobrescribe por un fallo', async () => {
  const { review } = harness();
  await review.beginReview(resultForm());
  const first = review.currentReceipt();
  const { review: failing } = harness({ send: async () => { throw Object.assign(new Error('x'), { status: 409 }); } });
  assert.equal(await failing.beginReview(resultForm()), 'conflict');
  assert.equal(failing.currentReceipt(), null);
  assert.equal(first!.fingerprint, 'fp-2');
});

test('recibo ajeno (fingerprint/ids mal formados) se rechaza como error', async () => {
  const { review } = harness({ send: async () => ({ live_review_id: 'no-uuid', content_revision: 2, report: {}, fingerprint: 'fp' }) });
  assert.equal(await review.beginReview(resultForm()), 'error');
  assert.equal(review.currentReceipt(), null);
});
