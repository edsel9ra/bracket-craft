import assert from 'node:assert/strict';
import test from 'node:test';
import { matchScoreDisplay } from '../app/utils/matchScoreDisplay.ts';

test('unstarted matches have a neutral marker, including a live status without a segment', () => {
  for (const status of ['scheduled', 'live', 'interrupted']) {
    assert.deepEqual(matchScoreDisplay({ status, segments: [], score: { home: null, away: null } }), {
      kind: 'pending', home: null, away: null, labelKey: 'match.scorePending',
    });
  }
});

test('started segments display zeroes without goals and retain reported goals', () => {
  for (const status of ['scheduled', 'live', 'interrupted']) {
    const input = { status, segments: [{ minute_start: 0 }], score: { home: null, away: null } };
    assert.deepEqual(matchScoreDisplay(input), { kind: 'live', home: 0, away: 0, labelKey: 'match.scoreLive' });
    assert.equal(matchScoreDisplay({ ...input, score: { home: 3, away: 0 } }).home, 3);
    assert.equal(input.score.home, null);
  }
});

test('closed, walkover and administrative results retain the final score without requiring a segment', () => {
  for (const [status, resolution] of [['finished', 'regular'], ['finished', 'walkover'], ['administrative_resolution', 'administrative'], ['cancelled', null]]) {
    assert.deepEqual(matchScoreDisplay({ status: status!, resolution, segments: [], score: { home: 2, away: 1 } }), {
      kind: 'final', home: 2, away: 1, labelKey: 'match.scoreFinal',
    });
  }
});

test('cancelled matches with absent or incomplete scores never invent a final zero', () => {
  for (const segments of [[], [{ minute_start: 0 }]]) {
    for (const score of [{ home: null, away: null }, { home: 2, away: null }, { home: null, away: 1 }]) {
      assert.deepEqual(matchScoreDisplay({ status: 'cancelled', segments, score }), {
        kind: 'cancelled', home: null, away: null, labelKey: 'status.cancelled',
      });
    }
    assert.deepEqual(matchScoreDisplay({ status: 'cancelled', segments, score: { home: 0, away: 0 } }), {
      kind: 'final', home: 0, away: 0, labelKey: 'match.scoreFinal',
    });
  }
});
