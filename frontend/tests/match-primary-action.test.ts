import assert from 'node:assert/strict';
import test from 'node:test';
import { primaryAction, type PrimaryActionInput } from '../app/utils/matchPrimaryAction.ts';

const base: PrimaryActionInput = { status: 'live', canOperate: true, canManage: false, activeSegment: true, lineupDirty: false, draftEvents: 0, closeReady: false, isTerminal: false };

test('terminal and unauthorized roles never receive editing actions, including a tournament manager without operation rights', () => {
  for (const canManage of [false, true]) {
    assert.equal(primaryAction({ ...base, canManage, canOperate: false }), null);
    assert.equal(primaryAction({ ...base, canManage, isTerminal: true }), null);
  }
});

test('scheduled and interrupted matches focus the existing segment form before other actions', () => {
  for (const status of ['scheduled', 'interrupted']) {
    assert.deepEqual(primaryAction({ ...base, status, activeSegment: false, lineupDirty: true, draftEvents: 3 }), {
      id: 'startSegment', labelKey: 'match.startNextSegment', mode: 'focus', target: '#seccion-campo',
    });
  }
});

test('dirty lineups run the same save handler, before reviewing pending events', () => {
  assert.deepEqual(primaryAction({ ...base, lineupDirty: true, draftEvents: 2, closeReady: true }), {
    id: 'saveLineup', labelKey: 'match.saveLineup', mode: 'run', target: '#seccion-planilla',
  });
});

test('pending events only focus report closing; they never run an independent save or close', () => {
  for (const input of [{ draftEvents: 2 }, { closeReady: true }, { draftEvents: 2, closeReady: true }]) {
    assert.deepEqual(primaryAction({ ...base, ...input }), {
      id: 'closeReport', labelKey: 'match.reviewClosing', mode: 'focus', target: '#seccion-cierre',
    });
  }
});

test('empty drafts fall back to the event form; zeroes do not imply a pending save', () => {
  assert.deepEqual(primaryAction(base), { id: 'addEvent', labelKey: 'match.addEvent', mode: 'focus', target: '#seccion-eventos' });
});
