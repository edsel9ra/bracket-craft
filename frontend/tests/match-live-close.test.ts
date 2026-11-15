import assert from 'node:assert/strict';
import test from 'node:test';

import { createLiveClose } from '../app/utils/matchLiveCloseLive.ts';
import { createLiveReview } from '../app/utils/matchLiveReview.ts';
import { applySharedSnapshot, createLiveEditorState } from '../app/utils/matchLiveEditor.ts';

const SEGMENT = '11111111-2222-4333-8444-555566667777';
const TEAM = 'aaaaaaaa-0000-4000-8000-000000000001';
const REVIEW_ID = 'bbbbbbbb-0000-4000-8000-000000000002';

function liveEvent() {
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

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    initialized: true,
    status: 'live',
    revision: 4,
    content_revision: 2,
    events: [liveEvent()],
    home_score: 1,
    away_score: 0,
    clock: { state: 'paused', segment_id: SEGMENT, segment_number: 1, elapsed_us: 60_000_000, anchor_at: null, observed_at: '2026-11-15T10:02:00Z' },
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

function harness(overrides: {
  sendClose?: (body: unknown) => Promise<unknown>;
  confirm?: () => Promise<boolean>;
  staleReview?: boolean;
} = {}) {
  const editor = createLiveEditorState();
  applySharedSnapshot(editor, snapshot());
  const review = createLiveReview({
    sendReview: async () => ({
      live_review_id: REVIEW_ID,
      content_revision: overrides.staleReview ? 99 : 2,
      report: { events: [liveEvent()], home_score: 1, away_score: 0 },
      fingerprint: 'fp-2',
    }),
    editor,
  });
  const sent: unknown[] = [];
  let confirms = 0;
  let closed = 0;
  const close = createLiveClose({
    sendClose: async (body) => {
      sent.push(body);
      return overrides.sendClose ? overrides.sendClose(body) : { status: 'finished' };
    },
    review,
    editor,
    confirm: async () => { confirms += 1; return overrides.confirm ? overrides.confirm() : true; },
    onClosed: () => { closed += 1; },
  });
  return { close, review, editor, sent, confirms: () => confirms, closed: () => closed };
}

async function reviewed(review: ReturnType<typeof createLiveReview>) {
  assert.equal(await review.beginReview(resultForm()), 'reviewed');
}

test('cierre envía solo el recibo y el resultado revisados — nunca un subconjunto de eventos', async () => {
  const { close, review, sent } = harness();
  await reviewed(review);
  assert.equal(await close.confirmClose(), 'closed');
  const body = sent[0] as Record<string, unknown>;
  assert.equal(body.live_review_id, REVIEW_ID);
  assert.equal(body.resolution_type, 'regular');
  assert.equal(body.home_score, 1);
  assert.equal('events' in body, false);
  assert.equal('expected_content_revision' in body, false);
});

test('sin recibo o con recibo vencido no envía ni confirma', async () => {
  const { close, sent, confirms } = harness();
  assert.equal(await close.confirmClose(), 'unavailable');
  const { close: stale, review: staleReview, sent: s2, confirms: c2 } = harness({ staleReview: true });
  await staleReview.beginReview(resultForm());
  assert.equal(await stale.confirmClose(), 'stale');
  assert.equal(sent.length, 0);
  assert.equal(s2.length, 0);
  assert.equal(confirms(), 0);
  assert.equal(c2(), 0);
});

test('cancelar la confirmación conserva recibo y borrador', async () => {
  const { close, review, editor, sent } = harness({ confirm: async () => false });
  await reviewed(review);
  assert.equal(await close.confirmClose(), 'cancelled');
  assert.equal(sent.length, 0);
  assert.equal(review.receiptValid(), true);
  assert.equal(editor.shared!.events.length, 1);
});

test('409 del cierre marca el recibo obsoleto sin perder el borrador', async () => {
  const { close, review, editor } = harness({ sendClose: async () => { throw Object.assign(new Error('x'), { status: 409 }); } });
  await reviewed(review);
  assert.equal(await close.confirmClose(), 'stale');
  assert.equal(editor.shared!.events.length, 1);
  // El recibo queda inservible aunque content_revision no haya cambiado localmente.
  assert.equal(review.receiptValid(), false);
});

test('401/403/404 vigentes y fallo de red conservan el borrador', async () => {
  for (const [status, expected] of [[401, 'denied'], [403, 'denied'], [404, 'denied'], [500, 'error']] as const) {
    const { close, review, editor } = harness({ sendClose: async () => { throw Object.assign(new Error('x'), { status }); } });
    await reviewed(review);
    assert.equal(await close.confirmClose(), expected);
    assert.equal(editor.shared!.events.length, 1);
  }
});

test('el modo provisional solo termina tras un cierre aceptado', async () => {
  const { close, review, closed } = harness();
  await reviewed(review);
  assert.equal(closed(), 0);
  assert.equal(await close.confirmClose(), 'closed');
  assert.equal(closed(), 1);
});
