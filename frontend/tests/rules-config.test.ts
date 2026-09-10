import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_RULES_CONFIG,
  buildRulesRequest,
  cloneRulesConfig,
  normalizeRulesConfig,
  parseRulesConfigJson,
  recalculatePipeline,
  serializeRulesConfig,
  validateRulesConfig,
} from '../utils/rulesConfig.ts';

test('normalizes incomplete rules while keeping a detached configuration', () => {
  const source = { points_system: { win: 5 } };
  const normalized = normalizeRulesConfig(source);

  assert.equal(normalized.points_system.win, 5);
  assert.equal(normalized.points_system.draw, DEFAULT_RULES_CONFIG.points_system.draw);
  assert.deepEqual(normalized.ranking_pipeline, DEFAULT_RULES_CONFIG.ranking_pipeline);
  assert.notEqual(normalized.ranking_pipeline, DEFAULT_RULES_CONFIG.ranking_pipeline);
});

test('keeps an optional roster lock unset when the source does not provide one', () => {
  const normalized = normalizeRulesConfig({ transfers: {} });

  assert.equal(normalized.transfers.roster_lock_matchday, null);
});

test('recalculates pipeline steps and removes repeated criteria', () => {
  const pipeline = recalculatePipeline([
    { step: 10, criterion: 'points', params: {} },
    { step: 20, criterion: 'goal_difference', params: {} },
    { step: 30, criterion: 'goal_difference', params: { ignored: true } },
    { step: 40, criterion: 'random_draw', params: {} },
  ]);

  assert.deepEqual(pipeline, [
    { step: 1, criterion: 'points', params: {} },
    { step: 2, criterion: 'goal_difference', params: {} },
    { step: 3, criterion: 'random_draw', params: {} },
  ]);
});

test('converts a visual configuration to JSON and back without changing the contract', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.points_system.win = 4;
  config.stage_overrides = {
    'stage-a': {
      extra_time_enabled: true,
      penalties_enabled: true,
      walkover_score: { winner: 3, loser: 0 },
    },
  };

  const parsed = parseRulesConfigJson(serializeRulesConfig(config));

  assert.equal(parsed.errors.length, 0);
  assert.deepEqual(parsed.config, config);
  assert.deepEqual(buildRulesRequest(config), { rules_config: config });
});

test('reports known pipeline restrictions before sending rules', () => {
  const invalid = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  invalid.ranking_pipeline = [
    { step: 1, criterion: 'points', params: {} },
    { step: 2, criterion: 'points', params: {} },
  ];

  const errors = validateRulesConfig(invalid);

  assert.ok(errors.some((error) => error.code === 'pipeline_duplicate'));
});
