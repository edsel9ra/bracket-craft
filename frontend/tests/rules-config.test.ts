import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_RULES_CONFIG,
  buildRulesRequest,
  cloneRulesConfig,
  effectiveStageRules,
  normalizeRulesConfig,
  parseRulesConfigJson,
  recalculatePipeline,
  serializeRulesConfig,
  validateRulesConfig,
} from '../app/utils/rulesConfig.ts';

const editorSource = readFileSync(
  new URL('../app/components/RulesEditor.vue', import.meta.url),
  'utf8',
);
const tournamentPageSource = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id].vue', import.meta.url),
  'utf8',
);
const translationsSource = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function legacyConfig(): Record<string, any> {
  const config: Record<string, any> = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.schema_version = '3.2.0';
  delete config.roster_lock_matchday;
  config.transfers = {
    allow_mid_season_transfers: true,
    same_matchday_participation_allowed: false,
    roster_lock_matchday: 4,
  };
  return config;
}

function legacyConfigWithoutMinutes(): Record<string, any> {
  const config = legacyConfig();
  delete config.stage_defaults.regular_time_minutes;
  delete config.stage_defaults.extra_time_minutes;
  return config;
}

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translationsSource.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translationsSource.slice(0, englishStart),
    english: translationsSource.slice(englishStart),
  };
}

test('normalizes incomplete rules while keeping a detached configuration', () => {
  const source = { points_system: { win: 5 } };
  const normalized = normalizeRulesConfig(source);

  assert.equal(normalized.points_system.win, 5);
  assert.equal(normalized.points_system.draw, DEFAULT_RULES_CONFIG.points_system.draw);
  assert.deepEqual(normalized.ranking_pipeline, DEFAULT_RULES_CONFIG.ranking_pipeline);
  assert.notEqual(normalized.ranking_pipeline, DEFAULT_RULES_CONFIG.ranking_pipeline);
});

test('keeps an optional roster lock unset when the source does not provide one', () => {
  const normalized = normalizeRulesConfig({});

  assert.equal(normalized.roster_lock_matchday, null);
  assert.equal('transfers' in normalized, false);
  assert.equal(normalized.schema_version, '3.3.0');
});

test('accepts 3.2.0 and 3.3.0 and always normalizes to 3.3.0', () => {
  const legacy = legacyConfig();
  assert.deepEqual(validateRulesConfig(legacy), []);

  const normalized = normalizeRulesConfig(legacy);

  assert.equal(normalized.schema_version, '3.3.0');
  assert.deepEqual(validateRulesConfig(normalized), []);
  assert.equal('transfers' in normalized, false);
});

test('promotes the inherited roster lock when the top-level key is missing', () => {
  const loaded = normalizeRulesConfig(legacyConfig());

  // The editor binds this normalized field, so it shows the promoted value.
  assert.equal(loaded.roster_lock_matchday, 4);
  assert.match(editorSource, /config\.roster_lock_matchday/);
});

test('saving emits 3.3.0 with the promoted key and without transfers', () => {
  const request = buildRulesRequest(normalizeRulesConfig(legacyConfig()));
  const emitted = request.rules_config as Record<string, any>;

  assert.equal(emitted.schema_version, '3.3.0');
  assert.equal(emitted.roster_lock_matchday, 4);
  assert.equal('transfers' in emitted, false);
  assert.deepEqual(emitted.substitutions, DEFAULT_RULES_CONFIG.substitutions);
  assert.deepEqual(validateRulesConfig(emitted), []);
});

test('the top-level roster lock prevails when both keys exist', () => {
  const legacy = legacyConfig();
  legacy.roster_lock_matchday = 6;

  const normalized = normalizeRulesConfig(legacy);

  assert.equal(normalized.roster_lock_matchday, 6);
  assert.equal((buildRulesRequest(normalized).rules_config as Record<string, any>).roster_lock_matchday, 6);
});

test('an empty or invalid matchday field becomes null', () => {
  assert.equal(normalizeRulesConfig({ roster_lock_matchday: '' }).roster_lock_matchday, null);
  assert.equal(normalizeRulesConfig({ roster_lock_matchday: 0 }).roster_lock_matchday, null);
  assert.equal(normalizeRulesConfig({ roster_lock_matchday: null }).roster_lock_matchday, null);
});

test('an emptied matchday field validates and saves as null', () => {
  const config: Record<string, any> = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.roster_lock_matchday = '';

  assert.deepEqual(validateRulesConfig(config), []);
  assert.equal(
    (buildRulesRequest(config as any).rules_config as Record<string, any>).roster_lock_matchday,
    null,
  );
  assert.match(tournamentPageSource, /roster_lock_matchday as unknown\) === ''/);
  assert.match(tournamentPageSource, /roster_lock_matchday = null/);
});

test('does not require the deprecated transfers or substitutions blocks', () => {
  const config: Record<string, any> = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  delete config.substitutions;
  delete config.transfers;

  assert.deepEqual(validateRulesConfig(config), []);
  const normalized = normalizeRulesConfig(config);
  assert.deepEqual(normalized.substitutions, DEFAULT_RULES_CONFIG.substitutions);
});

test('the editor has no transfers section and edits the registration matchday', () => {
  assert.doesNotMatch(editorSource, /config\.transfers/);
  assert.doesNotMatch(editorSource, /rules\.transfersSection/);
  assert.doesNotMatch(editorSource, /rules\.allowMidSeasonTransfers/);
  assert.match(editorSource, /rules\.registrationSection/);
  assert.match(editorSource, /config\.roster_lock_matchday/);
});

test('keeps the registration texts in Spanish and English parity', () => {
  const { spanish, english } = catalogSlices();

  for (const key of ['rules.registrationSection', 'rules.registrationDescription', 'rules.rosterLockMatchday', 'rules.noRosterLock']) {
    assert.match(spanish, new RegExp(`'${key.replace(/\./g, '\\.')}':`));
    assert.match(english, new RegExp(`'${key.replace(/\./g, '\\.')}':`));
  }
  assert.doesNotMatch(translationsSource, /rules\.transfersSection/);
  assert.doesNotMatch(translationsSource, /rules\.allowMidSeasonTransfers/);
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
  config.roster_lock_matchday = 3;
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

test('accepts 3.3.0 and rejects an unknown schema version', () => {
  const current = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  assert.deepEqual(validateRulesConfig(current), []);

  current.schema_version = '3.1.0';

  const errors = validateRulesConfig(current);
  assert.ok(errors.some((error) => error.code === 'schema_version' && error.path === 'schema_version'));
  assert.equal(normalizeRulesConfig(current).schema_version, '3.3.0');
});

test('reads the 90/120 minute defaults without rewriting the source', () => {
  const legacy = legacyConfigWithoutMinutes();
  const original = cloneRulesConfig(legacy);

  assert.deepEqual(validateRulesConfig(legacy), []);
  assert.equal(legacy.stage_defaults.regular_time_minutes, undefined);
  assert.equal(legacy.stage_defaults.extra_time_minutes, undefined);
  assert.deepEqual(legacy, original);

  const effective = effectiveStageRules(normalizeRulesConfig(legacy), null);
  assert.equal(effective.regular_time_minutes, 90);
  assert.equal(effective.extra_time_minutes, 120);

  const normalized = normalizeRulesConfig(legacy);
  assert.equal(normalized.stage_defaults.regular_time_minutes, 90);
  // Overtime is disabled: the extra-time default is read but not materialized.
  assert.equal('extra_time_minutes' in normalized.stage_defaults, false);

  legacy.stage_defaults.extra_time_enabled = true;
  const normalizedWithOvertime = normalizeRulesConfig(legacy);
  assert.equal(normalizedWithOvertime.stage_defaults.extra_time_minutes, 120);
});

test('validates the effective minute pair and reports errors with a path', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.extra_time_enabled = true;
  config.stage_defaults.regular_time_minutes = 179;
  config.stage_defaults.extra_time_minutes = 180;
  assert.deepEqual(validateRulesConfig(config), []);

  config.stage_defaults.regular_time_minutes = 180;
  assert.ok(validateRulesConfig(config).some(
    (error) => error.code === 'integer_field' && error.path === 'stage_defaults.regular_time_minutes',
  ));

  config.stage_defaults.regular_time_minutes = 0;
  assert.ok(validateRulesConfig(config).some(
    (error) => error.code === 'integer_field' && error.path === 'stage_defaults.regular_time_minutes',
  ));

  config.stage_defaults.regular_time_minutes = 90;
  config.stage_defaults.extra_time_minutes = 90;
  assert.ok(validateRulesConfig(config).some(
    (error) => error.code === 'minutes_pair' && error.path === 'stage_defaults.extra_time_minutes',
  ));

  config.stage_defaults.extra_time_minutes = 181;
  assert.ok(validateRulesConfig(config).some(
    (error) => error.code === 'minutes_pair' && error.path === 'stage_defaults.extra_time_minutes',
  ));
});

test('does not validate nor materialize extra time when overtime is disabled', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.extra_time_enabled = false;
  config.stage_defaults.regular_time_minutes = 150;
  config.stage_defaults.extra_time_minutes = 181;

  assert.deepEqual(validateRulesConfig(config), []);

  const normalized = normalizeRulesConfig(config);
  assert.equal(normalized.stage_defaults.regular_time_minutes, 150);
  assert.equal(normalized.stage_defaults.extra_time_minutes, 181);

  delete config.stage_defaults.extra_time_minutes;
  const withoutExtra = normalizeRulesConfig(config);
  assert.equal('extra_time_minutes' in withoutExtra.stage_defaults, false);
});

test('never materializes an extra-time default that breaks the pair', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.extra_time_enabled = true;
  config.stage_defaults.regular_time_minutes = 150;
  delete config.stage_defaults.extra_time_minutes;

  const errors = validateRulesConfig(config);
  assert.ok(errors.some((error) => error.code === 'minutes_pair' && error.path === 'stage_defaults.extra_time_minutes'));

  const normalized = normalizeRulesConfig(config);
  assert.equal(normalized.stage_defaults.regular_time_minutes, 150);
  assert.equal('extra_time_minutes' in normalized.stage_defaults, false);
});

test('resolves partial stage minute overrides key by key', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.extra_time_enabled = true;
  config.stage_overrides = {
    'stage-a': { extra_time_minutes: 180 },
    'stage-b': { regular_time_minutes: 40, extra_time_minutes: 100 },
  };

  assert.deepEqual(validateRulesConfig(config), []);

  const overridden = effectiveStageRules(config, 'stage-a');
  assert.equal(overridden.regular_time_minutes, 90);
  assert.equal(overridden.extra_time_minutes, 180);

  const replaced = effectiveStageRules(config, 'stage-b');
  assert.equal(replaced.regular_time_minutes, 40);
  assert.equal(replaced.extra_time_minutes, 100);

  assert.equal(effectiveStageRules(config, null).regular_time_minutes, 90);
  assert.equal(config.stage_defaults.extra_time_minutes, 120);
});

test('rejects invalid partial stage minute overrides with the stage path', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.extra_time_enabled = true;
  config.stage_overrides = { 'stage-a': { regular_time_minutes: 150 } };

  const errors = validateRulesConfig(config);
  assert.ok(errors.some(
    (error) => error.code === 'minutes_pair' && error.path === 'stage_overrides.stage-a.extra_time_minutes',
  ));

  config.stage_overrides = { 'stage-a': { extra_time_enabled: false, regular_time_minutes: 150 } };
  assert.deepEqual(validateRulesConfig(config), []);

  config.stage_overrides = { 'stage-a': { extra_time_enabled: true, extra_time_minutes: 181 } };
  assert.ok(validateRulesConfig(config).some(
    (error) => error.code === 'minutes_pair' && error.path === 'stage_overrides.stage-a.extra_time_minutes',
  ));
});

test('the editor edits minutes for stage defaults and per-stage overrides', () => {
  assert.match(editorSource, /config\.stage_defaults\.regular_time_minutes/);
  assert.match(editorSource, /config(?:\.value)?\.stage_defaults\.extra_time_minutes/);
  assert.match(editorSource, /setStageExtraMinutes/);
  assert.match(editorSource, /overrideMinutes/);
  assert.match(editorSource, /setOverrideMinutes/);
});

test('keeps the minute texts in Spanish and English parity', () => {
  const { spanish, english } = catalogSlices();

  for (const key of ['rules.regularTimeMinutes', 'rules.extraTimeMinutes', 'rules.error.minutesPair']) {
    assert.match(spanish, new RegExp(`'${key.replace(/\./g, '\\.')}':`));
    assert.match(english, new RegExp(`'${key.replace(/\./g, '\\.')}':`));
  }
});
