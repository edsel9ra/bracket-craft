import assert from 'node:assert/strict';
import test from 'node:test';

import {
  classifyLiveCloseConflict,
  isLiveInitialized,
  LIVE_CLOSE_CONFLICT_LABEL_KEYS,
} from '../app/utils/matchLiveClose.ts';

function apiFailure(status: number, data?: unknown) {
  return Object.assign(new Error(`HTTP ${status}`), { status, data });
}

test('un partido F1 inicializado se reconoce solo con initialized=true explícito', () => {
  assert.equal(isLiveInitialized({ initialized: true, status: 'live' }), true);
  for (const snapshot of [
    null,
    'x',
    {},
    { initialized: false, status: 'scheduled' },
    { initialized: 'true' },
    { initialized: 1 },
  ]) {
    assert.equal(isLiveInitialized(snapshot), false);
  }
});

test('cliente clásico contra F1 inicializado: 409 detail se clasifica, sin código aditivo', () => {
  assert.equal(
    classifyLiveCloseConflict(apiFailure(409, { detail: 'LIVE_REVIEW_REQUIRED' })),
    'live_review_required',
  );
  assert.equal(
    classifyLiveCloseConflict(apiFailure(409, { detail: 'LIVE_REVIEW_STALE' })),
    'live_review_stale',
  );
  // Sin el permiso de lectura ni recibo, la misma denegación también llega por detail.
  for (const cause of [
    apiFailure(409, { detail: 'WALKOVER_STATE_NOT_ALLOWED' }),
    apiFailure(409, { code: 'LIVE_REVIEW_REQUIRED' }),
    apiFailure(422, { detail: 'LIVE_REVIEW_REQUIRED' }),
    apiFailure(409, { detail: 7 }),
    apiFailure(409),
    apiFailure(409, 'plain'),
  ]) {
    assert.equal(classifyLiveCloseConflict(cause), null);
  }
});

test('las claves i18n del conflicto live son distintas del cierre clásico', () => {
  assert.equal(LIVE_CLOSE_CONFLICT_LABEL_KEYS.live_review_required, 'match.liveReviewRequired');
  assert.equal(LIVE_CLOSE_CONFLICT_LABEL_KEYS.live_review_stale, 'match.liveReviewStale');
});
