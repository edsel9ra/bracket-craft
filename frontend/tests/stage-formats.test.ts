import assert from 'node:assert/strict';
import test from 'node:test';

import { STAGE_FORMATS, getStageFormatOptions } from '../constants/stageFormats.ts';

test('keeps one catalog with the backend stage format values', () => {
  assert.deepEqual(
    STAGE_FORMATS.map((format) => format.value),
    ['round_robin', 'single_elimination', 'custom_group', 'swiss', 'double_elimination'],
  );
});

test('localizes stage labels and descriptions without changing internal values', () => {
  const options = getStageFormatOptions((key) => `translated:${key}`);

  assert.equal(options.length, STAGE_FORMATS.length);
  assert.deepEqual(options[0], {
    value: 'round_robin',
    label: 'translated:stage.roundRobin',
    description: 'translated:stage.roundRobinDescription',
  });
});
