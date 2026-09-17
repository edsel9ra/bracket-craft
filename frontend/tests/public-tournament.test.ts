import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getPublicStagePresentation,
  sortPublicStages,
  usesCurrentDoubleEliminationFormat,
  type PublicStage,
} from '../utils/publicTournament.ts';

function stage(id: string, stage_order: number, stage_type: PublicStage['stage_type']): PublicStage {
  return { id, name: id, stage_order, stage_type };
}

test('orders custom tournament phases by stage order', () => {
  const ordered = sortPublicStages([
    stage('playoffs', 2, 'single_elimination'),
    stage('league', 1, 'round_robin'),
  ]);

  assert.deepEqual(ordered.map((item) => item.id), ['league', 'playoffs']);
});

test('maps league and elimination formats to their public presentation', () => {
  assert.equal(getPublicStagePresentation('round_robin'), 'standings');
  assert.equal(getPublicStagePresentation('custom_group'), 'standings');
  assert.equal(getPublicStagePresentation('swiss'), 'standings');
  assert.equal(getPublicStagePresentation('single_elimination'), 'bracket');
  assert.equal(getPublicStagePresentation('double_elimination'), 'current');
});

test('keeps the current layout only for an all-double-elimination tournament', () => {
  assert.equal(
    usesCurrentDoubleEliminationFormat([stage('main', 1, 'double_elimination')]),
    true,
  );
  assert.equal(
    usesCurrentDoubleEliminationFormat([
      stage('league', 1, 'swiss'),
      stage('finals', 2, 'single_elimination'),
    ]),
    false,
  );
  assert.equal(usesCurrentDoubleEliminationFormat([]), false);
});
