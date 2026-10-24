import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_GAME_FORMAT,
  DEFAULT_RULES_CONFIG,
  GAME_FORMAT_OPTIONS,
  buildRulesRequest,
  cloneRulesConfig,
  effectiveStageRules,
  isGameFormat,
  normalizeRulesConfig,
  parseRulesConfigJson,
  readRosterLimitInput,
  recalculatePipeline,
  serializeRulesConfig,
  validateRulesConfig,
} from '../app/utils/rulesConfig.ts';
import { wizardSteps } from '../app/utils/wizardModel.ts';
import {
  RULES_INLINE_FIELD_IDS,
  buildRulesPayload,
  checkRulesSave,
  describeRulesIssue,
  formatWarns,
  inlineFieldIssue,
  isInlineRulesField,
  rulesErrorsByStep,
  rulesFieldLabelKey,
  rulesIssues,
  rulesSectionForStep,
  rulesServerIssues,
  rulesStepForPath,
  rulesWizardStatuses,
  rulesWizardValues,
  serverValidationDetail,
  summaryFieldIssues,
} from '../app/utils/rulesWizard.ts';

const editorSource = readFileSync(
  new URL('../app/components/RulesEditor.vue', import.meta.url),
  'utf8',
);
const tournamentPageSource = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
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

// --- RF-031 (H3-T09): nomenclatura y estado del campo de prórroga -----------

/** Recorta el `<label>` de cada campo de minutos con prórroga del editor. */
function extraMinutesFields(): string[] {
  const marker = "t('rules.extraTimeMinutes')";
  const fields: string[] = [];
  let index = editorSource.indexOf(marker);
  while (index >= 0) {
    const end = editorSource.indexOf('</label>', index);
    assert.ok(end > index, 'the extra-time field is not wrapped in a label');
    fields.push(editorSource.slice(index, end));
    index = editorSource.indexOf(marker, end);
  }
  return fields;
}

test('the extra-time minute field is enabled with overtime and disabled without it', () => {
  const fields = extraMinutesFields();
  assert.equal(fields.length, 2, 'the editor has a defaults field and a per-stage override field');

  // Los dos interruptores que encienden la prórroga son la misma fuente que el
  // estado del campo: encendida, no está deshabilitado.
  assert.match(editorSource, /v-model="config\.stage_defaults\.extra_time_enabled"/);
  assert.match(editorSource, /:checked="overrideBoolean\(stage\.id, 'extra_time_enabled'\)"/);

  assert.match(
    fields[0],
    /:disabled="!config\.stage_defaults\.extra_time_enabled"/,
    'the defaults field is not disabled when overtime is off',
  );
  assert.match(
    fields[1],
    /:disabled="!overrideBoolean\(stage\.id, 'extra_time_enabled'\)"/,
    'the override field is not disabled when overtime is off for that stage',
  );
});

test('the extra-time field keeps its value and explains why it is disabled', () => {
  const fields = extraMinutesFields();

  assert.match(fields[0], /:value="stageExtraMinutes\(\)"/);
  assert.match(fields[1], /:value="overrideMinutes\(stage\.id, 'extra_time_minutes'\)"/);

  for (const field of fields) {
    assert.match(field, /@change=/, 'the field only writes on change, so disabling keeps the value');
    assert.match(
      field,
      /rules\.extraTimeMinutesDisabled/,
      'the field does not explain why it is disabled',
    );
  }

  assert.doesNotMatch(
    editorSource,
    /extra_time_enabled[^\n]*=[^\n]*false[\s\S]{0,120}extra_time_minutes[^\n]*=[^\n]*undefined/,
    'turning overtime off must not clear the extra-time value',
  );
});

test('turning overtime off keeps the extra-time value that would apply', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.extra_time_enabled = false;
  config.stage_defaults.extra_time_minutes = 125;

  assert.equal(effectiveStageRules(config, null).extra_time_enabled, false);
  assert.equal(effectiveStageRules(config, null).extra_time_minutes, 125);

  config.stage_overrides = { 'stage-a': { extra_time_enabled: false, extra_time_minutes: 130 } };

  assert.equal(effectiveStageRules(config, 'stage-a').extra_time_enabled, false);
  assert.equal(effectiveStageRules(config, 'stage-a').extra_time_minutes, 130);
});

test('the duration labels name the minute the match ends, in both languages', () => {
  const { spanish, english } = catalogSlices();

  assert.match(spanish, /'rules\.regularTimeMinutes': 'Minuto final reglamentario'/);
  assert.match(spanish, /'rules\.extraTimeMinutes': 'Minuto final con prórroga'/);
  assert.match(english, /'rules\.regularTimeMinutes': 'Regulation final minute'/);
  assert.match(english, /'rules\.extraTimeMinutes': 'Extra-time final minute'/);

  for (const key of ['rules.extraTimeMinutesDisabled']) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `missing Spanish key ${key}`);
    assert.match(english, pattern, `missing English key ${key}`);
  }

  for (const old of ['Minutos reglamentarios', 'Minutos con prórroga', 'Regulation minutes', 'Minutes with overtime']) {
    assert.ok(
      !translationsSource.includes(old) && !editorSource.includes(old),
      `the old duration label "${old}" is still present`,
    );
  }
});

// --- Asistente de reglas (H1-T05) -------------------------------------------

function rulesWizardSource(): string {
  return readFileSync(
    new URL('../app/components/rules/RulesWizard.vue', import.meta.url),
    'utf8',
  );
}

type FakeTranslate = (key: string, values?: Record<string, string | number>) => string;

/** Traducción falsa y determinista: devuelve la clave y sus parámetros. */
const fakeTranslate: FakeTranslate = (key, values = {}) => {
  const rendered = Object.entries(values).map(([name, value]) => `${name}=${value}`).join(',');
  return rendered ? `${key}(${rendered})` : key;
};

function stateOf(states: ReturnType<typeof rulesWizardStatuses>, stepId: string): string {
  return states.find((step) => step.id === stepId)?.state ?? 'missing';
}

test('the rules assistant declares the eight steps of RF-006 in a stable order', () => {
  const steps = wizardSteps('rules');

  assert.deepEqual(steps.map((step) => step.id), [
    'rules.scoring',
    'rules.tiebreakers',
    'rules.discipline',
    'rules.resolution',
    'rules.format',
    'rules.substitutions',
    'rules.registration',
    'rules.overrides',
  ]);
  assert.deepEqual(
    steps.map((step) => step.obligation),
    ['required', 'required', 'required', 'required', 'required', 'optional', 'optional', 'optional'],
  );

  const format = steps.find((step) => step.id === 'rules.format');
  assert.deepEqual(
    format?.fields.map((field) => [field.id, field.obligation]),
    [['gameFormat', 'required'], ['minPlayers', 'optional'], ['maxPlayers', 'optional']],
  );
});

test('a valid configuration can be confirmed and sends every required key, even empty', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_overrides = {};
  config.roster_lock_matchday = null;

  const check = checkRulesSave(config, rulesIssues(validateRulesConfig(config)), fakeTranslate);

  assert.equal(check.ok, true);
  assert.deepEqual(check.blockedBy, []);

  const payload = buildRulesPayload(config).rules_config;
  for (const key of [
    'schema_version',
    'engine_version',
    'points_system',
    'ranking_pipeline',
    'substitutions',
    'discipline',
    'roster_lock_matchday',
    'stage_defaults',
    'stage_overrides',
  ]) {
    assert.ok(key in payload, `the payload is missing the required key ${key}`);
  }
  assert.deepEqual(payload.stage_overrides, {});
  assert.equal(payload.roster_lock_matchday, null);
  assert.equal('transfers' in payload, false);
  // H4-T07 writes the declarative format and the two optional limits (RF-042, RF-044).
  assert.equal(payload.game_format, '11v11');
  assert.equal(payload.min_players_per_team, 0);
  assert.equal(payload.max_players_per_team, 0);
  assert.deepEqual(payload, buildRulesRequest(normalizeRulesConfig(config)).rules_config);
});

test('the format step is complete by default and writes the three new keys', () => {
  assert.equal(rulesWizardValues(DEFAULT_RULES_CONFIG).gameFormat, '11v11');

  const states = rulesWizardStatuses(DEFAULT_RULES_CONFIG, fakeTranslate, []);
  assert.equal(stateOf(states, 'rules.format'), 'complete');
  assert.equal(rulesSectionForStep('rules.format'), 'format');

  const payload = buildRulesPayload(DEFAULT_RULES_CONFIG).rules_config;
  assert.equal(payload.game_format, '11v11');
  assert.equal(payload.min_players_per_team, 0);
  assert.equal(payload.max_players_per_team, 0);
});

test('groups every error by field and step and keeps the invalid values', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.substitutions = {
    max_per_team: -2,
    max_windows: 'many' as unknown as number,
    allow_reentry: 'yes' as unknown as boolean,
  };
  config.stage_defaults.extra_time_enabled = true;
  config.stage_defaults.regular_time_minutes = 150;
  const before = cloneRulesConfig(config);

  const issues = rulesIssues(validateRulesConfig(config));

  assert.equal(issues.length, 4);
  assert.ok(issues.every((issue) => issue.stepId !== null));
  assert.ok(issues.every(
    (issue) => issue.fieldLabelKey.startsWith('rules.') && issue.messageKey.startsWith('rules.error.'),
  ));
  assert.ok(issues.every((issue) => rulesFieldLabelKey(issue.path) === issue.fieldLabelKey));

  const groups = rulesErrorsByStep(issues);
  assert.equal(groups.byStep['rules.substitutions'].length, 3);
  assert.equal(groups.byStep['rules.resolution'].length, 1);
  assert.deepEqual(groups.global, []);

  const states = rulesWizardStatuses(config, fakeTranslate, issues);
  assert.equal(stateOf(states, 'rules.substitutions'), 'error');
  assert.equal(stateOf(states, 'rules.resolution'), 'error');

  const check = checkRulesSave(config, issues, fakeTranslate);
  assert.equal(check.ok, false);
  assert.deepEqual([...check.blockedBy].sort(), ['rules.resolution', 'rules.substitutions']);

  // RF-004 / RF-005: nothing is normalized, discarded or rewritten.
  assert.deepEqual(config, before);
  assert.equal(rulesWizardValues(config).substitutions.max_per_team, -2);
});

test('shows every message of a step with its field and its step, never a raw key', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.discipline.yellow_card_limit = 0;
  config.discipline.fair_play_penalties.yellow_card = -1;

  const issues = rulesIssues(validateRulesConfig(config));
  const messages = issues.map((issue) => describeRulesIssue(issue, fakeTranslate));

  assert.equal(messages.length, 2);
  for (const message of messages) {
    assert.match(message, /^rules\.error\.fieldInStep\(/);
    assert.match(message, /step=wizard\.rules\.discipline/);
    assert.match(message, /field=rules\./);
    assert.match(message, /message=rules\.error\./);
  }
  assert.notEqual(messages[0], messages[1]);
});

test('an empty configuration blocks confirmation on the required steps only', () => {
  const check = checkRulesSave({}, [], fakeTranslate);

  assert.equal(check.ok, false);
  assert.deepEqual(check.blockedBy, [
    'rules.scoring',
    'rules.tiebreakers',
    'rules.discipline',
    'rules.resolution',
  ]);
});

test('walks every step back and forth without losing values or writing to the network', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.substitutions.max_per_team = -1;
  config.stage_overrides = { 'stage-a': { regular_time_minutes: 150 } };
  const before = cloneRulesConfig(config);
  const issues = rulesIssues(validateRulesConfig(config));

  for (const step of wizardSteps('rules')) {
    assert.ok(rulesSectionForStep(step.id));
    assert.equal(rulesWizardStatuses(config, fakeTranslate, issues).length, 8);
    checkRulesSave(config, issues, fakeTranslate);
  }

  assert.deepEqual(config, before);
  assert.equal(buildRulesPayload(config).rules_config.stage_overrides !== undefined, true);
  assert.doesNotMatch(rulesWizardSource(), /useApi|\$fetch/);
});

test('the advanced mode keeps its validation and blocks the save without losing content', () => {
  const invalid = parseRulesConfigJson('{"points_system":');
  const issues = rulesIssues(invalid.errors);

  assert.equal(issues.length, 1);
  assert.equal(issues[0]?.stepId, null);
  assert.equal(rulesErrorsByStep(issues).global.length, 1);

  const blocked = checkRulesSave(DEFAULT_RULES_CONFIG, issues, fakeTranslate);
  assert.equal(blocked.ok, false);
  assert.deepEqual(blocked.blockedBy, []);

  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.points_system.win = 4;
  const parsed = parseRulesConfigJson(serializeRulesConfig(config));
  assert.equal(parsed.errors.length, 0);
  assert.ok(parsed.config);

  const valid = checkRulesSave(parsed.config, rulesIssues(parsed.errors), fakeTranslate);
  assert.equal(valid.ok, true);
  assert.deepEqual(buildRulesPayload(parsed.config).rules_config, config);

  assert.match(editorSource, /rules\.jsonMode/);
  assert.match(editorSource, /applyJson/);
  assert.match(editorSource, /parseRulesConfigJson/);
});

test('maps the server field errors to their step without exposing the response body', () => {
  const detail = [
    { loc: ['body', 'rules_config', 'substitutions', 'max_per_team'], msg: 'Input should be >= 0', type: 'greater_than_equal' },
    { loc: ['body', 'rules_config', 'stage_defaults', 'extra_time_minutes'], msg: 'engine detail', type: 'value_error' },
    { loc: ['body', 'rules_config'], msg: 'body detail', type: 'value_error' },
    { loc: ['body', 'unknown_field'], msg: 'noise', type: 'value_error' },
  ];

  const issues = rulesServerIssues(detail);

  assert.deepEqual(
    issues.map((issue) => issue.stepId),
    ['rules.substitutions', 'rules.resolution', null, null],
  );
  assert.ok(issues.every((issue) => issue.messageKey === 'rules.error.serverField'));
  for (const issue of issues) {
    const message = describeRulesIssue(issue, fakeTranslate);
    assert.doesNotMatch(message, /Input should|engine detail|body detail|noise/);
  }

  const groups = rulesErrorsByStep(issues);
  assert.equal(groups.byStep['rules.substitutions'].length, 1);
  assert.equal(groups.global.length, 2);
  assert.equal(checkRulesSave(DEFAULT_RULES_CONFIG, issues, fakeTranslate).ok, false);

  assert.deepEqual(serverValidationDetail({ statusCode: 422, data: { detail } }), detail);
  assert.deepEqual(serverValidationDetail({ data: { detail: 'not a list' } }), null);
  assert.equal(serverValidationDetail({}), null);
});

test('maps the known configuration paths to their step', () => {
  assert.equal(rulesStepForPath('points_system.win'), 'rules.scoring');
  assert.equal(rulesStepForPath('ranking_pipeline.0.criterion'), 'rules.tiebreakers');
  assert.equal(rulesStepForPath('discipline.fair_play_penalties.yellow_card'), 'rules.discipline');
  assert.equal(rulesStepForPath('stage_defaults.extra_time_minutes'), 'rules.resolution');
  assert.equal(rulesStepForPath('substitutions.max_windows'), 'rules.substitutions');
  assert.equal(rulesStepForPath('roster_lock_matchday'), 'rules.registration');
  assert.equal(rulesStepForPath('transfers.roster_lock_matchday'), 'rules.registration');
  assert.equal(rulesStepForPath('stage_overrides.stage-a.regular_time_minutes'), 'rules.overrides');
  assert.equal(rulesStepForPath('game_format'), 'rules.format');
  assert.equal(rulesStepForPath('engine_version'), null);
  assert.equal(rulesStepForPath(undefined), null);
});

test('the rules assistant reuses the editor inside the steps', () => {
  const source = rulesWizardSource();

  assert.match(source, /<RulesEditor/);
  assert.match(source, /<WizardShell/);
  assert.match(source, /:sections=/);
  assert.doesNotMatch(source, /v-model\.number/);
  assert.doesNotMatch(source, /config\.points_system/);
  assert.doesNotMatch(source, /advancedJson/);

  assert.match(editorSource, /sections/);
  assert.match(tournamentPageSource, /<RulesWizard/);
  assert.doesNotMatch(tournamentPageSource, /<RulesEditor/);
});

test('keeps the assistant rules texts in Spanish and English parity', () => {
  const { spanish, english } = catalogSlices();

  for (const key of [
    'rules.wizardTitle',
    'rules.wizardDescription',
    'rules.error.fieldInStep',
    'rules.error.serverField',
    'rules.error.summary',
    'rules.field.rulesConfig',
    'rules.field.schemaVersion',
    'rules.field.engineVersion',
    'rules.field.criterionStep',
    'rules.field.stageOverride',
    'rules.field.gameFormat',
    'rules.field.minPlayers',
    'rules.field.maxPlayers',
    'rules.formatSection',
    'rules.formatDescription',
    'rules.gameFormatHint',
    'rules.limitsHelp',
    'rules.noLimit',
    'rules.error.gameFormat',
    'rules.error.rosterLimitsPair',
    'format.notice.rules',
    'format.notice.summary',
    'format.notice.operation',
  ]) {
    assert.match(spanish, new RegExp(`'${key.replace(/\./g, '\\.')}':`), `missing es ${key}`);
    assert.match(english, new RegExp(`'${key.replace(/\./g, '\\.')}':`), `missing en ${key}`);
  }
});

// --- Formato de juego y límites de plantilla (H4-T07) ----------------------

function configWithLimits(min: unknown, max: unknown): Record<string, any> {
  const config: Record<string, any> = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.min_players_per_team = min;
  config.max_players_per_team = max;
  return config;
}

test('the format step offers exactly the four declarative formats with 11v11 by default', () => {
  assert.deepEqual([...GAME_FORMAT_OPTIONS], ['5v5', '7v7', '9v9', '11v11']);
  assert.equal(DEFAULT_GAME_FORMAT, '11v11');

  for (const format of GAME_FORMAT_OPTIONS) assert.equal(isGameFormat(format), true);
  assert.equal(isGameFormat('3v3'), false);
  assert.equal(isGameFormat(''), false);
  assert.equal(isGameFormat(null), false);

  assert.equal(rulesWizardValues({}).gameFormat, '11v11');
  assert.equal(rulesWizardValues({ game_format: '7v7' }).gameFormat, '7v7');
  assert.equal(rulesWizardValues({ game_format: '3v3' }).gameFormat, '11v11');

  // El selector se alimenta del catálogo cerrado y escribe la clave del contrato.
  assert.match(editorSource, /GAME_FORMAT_OPTIONS/);
  assert.match(editorSource, /config\.game_format/);
  assert.match(editorSource, /<select[^>]*config\.game_format|v-model="config\.game_format"/);
});

test('saves the three new keys and keeps a configuration without them working', () => {
  const legacy: Record<string, any> = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  delete legacy.game_format;
  delete legacy.min_players_per_team;
  delete legacy.max_players_per_team;

  assert.deepEqual(validateRulesConfig(legacy), []);

  const normalized = normalizeRulesConfig(legacy);
  assert.equal(normalized.game_format, '11v11');
  assert.equal(normalized.min_players_per_team, 0);
  assert.equal(normalized.max_players_per_team, 0);

  const payload = buildRulesPayload(legacy as never).rules_config;
  assert.equal(payload.game_format, '11v11');
  assert.equal(payload.min_players_per_team, 0);
  assert.equal(payload.max_players_per_team, 0);
});

test('normalizes an emptied limit field to zero when leaving the field', () => {
  assert.equal(readRosterLimitInput(''), 0);
  assert.equal(readRosterLimitInput('   '), 0);
  assert.equal(readRosterLimitInput(null), 0);
  assert.equal(readRosterLimitInput(undefined), 0);

  assert.equal(readRosterLimitInput('0'), 0);
  assert.equal(readRosterLimitInput('12'), 12);
  assert.equal(readRosterLimitInput(12), 12);

  // Negativos, decimales y texto no se recortan en silencio: se conservan para
  // que la validación muestre el mensaje del campo.
  assert.equal(readRosterLimitInput('-1'), null);
  assert.equal(readRosterLimitInput('1.5'), null);
  assert.equal(readRosterLimitInput('many'), null);
  assert.equal(readRosterLimitInput(-1), null);

  assert.match(editorSource, /readRosterLimitInput/);
  assert.match(editorSource, /@change="setRosterLimit\('min_players_per_team', \$event\)"/);
  assert.match(editorSource, /@change="setRosterLimit\('max_players_per_team', \$event\)"/);
});

test('validates the roster limits as non-negative integers and the min ≤ max pair', () => {
  assert.deepEqual(validateRulesConfig(configWithLimits(0, 0)), []);
  assert.deepEqual(validateRulesConfig(configWithLimits(0, 11)), []);
  assert.deepEqual(validateRulesConfig(configWithLimits(11, 0)), []);
  assert.deepEqual(validateRulesConfig(configWithLimits(11, 11)), []);

  assert.ok(validateRulesConfig(configWithLimits(12, 11)).some(
    (error) => error.code === 'roster_limits_pair' && error.path === 'max_players_per_team',
  ));
  assert.ok(validateRulesConfig(configWithLimits(-1, 5)).some(
    (error) => error.code === 'integer_field' && error.path === 'min_players_per_team',
  ));
  assert.ok(validateRulesConfig(configWithLimits(5, -1)).some(
    (error) => error.code === 'integer_field' && error.path === 'max_players_per_team',
  ));
  assert.ok(validateRulesConfig(configWithLimits(1.5, 5)).some(
    (error) => error.code === 'integer_field' && error.path === 'min_players_per_team',
  ));
  assert.ok(validateRulesConfig(configWithLimits(5, 'five')).some(
    (error) => error.code === 'integer_field' && error.path === 'max_players_per_team',
  ));
  // El vacío se normaliza en la interfaz al salir del campo; si llegara al
  // contrato, se rechaza como entero inválido, igual que la API (422).
  assert.ok(validateRulesConfig(configWithLimits('', 5)).some(
    (error) => error.code === 'integer_field' && error.path === 'min_players_per_team',
  ));
});

test('marks the format step with an error and blocks the save without losing values', () => {
  const config = configWithLimits(12, 11);
  const before = cloneRulesConfig(config);

  const issues = rulesIssues(validateRulesConfig(config));
  assert.equal(issues.length, 1);
  assert.equal(issues[0]?.stepId, 'rules.format');
  assert.equal(issues[0]?.messageKey, 'rules.error.rosterLimitsPair');

  const states = rulesWizardStatuses(config, fakeTranslate, issues);
  assert.equal(stateOf(states, 'rules.format'), 'error');

  const check = checkRulesSave(config, issues, fakeTranslate);
  assert.equal(check.ok, false);
  assert.ok(check.blockedBy.includes('rules.format'));

  // RF-004 / RF-005: el rechazo no normaliza, no descarta ni reescribe valores.
  assert.deepEqual(config, before);
  assert.equal(rulesWizardValues(config).minPlayers, 12);
  assert.equal(rulesWizardValues(config).maxPlayers, 11);
});

// RF-005 / criterio 2: el mensaje del límite de plantilla se asocia a su campo
// con `aria-invalid`/`aria-describedby`, se anuncia al aparecer y sigue
// habiendo un resumen del paso para el resto de problemas.
test('associates each format and limit error with its field', () => {
  const config = configWithLimits(12, 11);
  const issues = rulesIssues(validateRulesConfig(config));

  const limitIssue = inlineFieldIssue(issues, 'max_players_per_team');
  assert.ok(limitIssue);
  assert.equal(limitIssue?.path, 'max_players_per_team');
  assert.equal(limitIssue?.messageKey, 'rules.error.rosterLimitsPair');
  assert.equal(isInlineRulesField('min_players_per_team'), true);
  assert.equal(isInlineRulesField('game_format'), true);
  assert.equal(isInlineRulesField('points_system.win'), false);
  assert.deepEqual(summaryFieldIssues(issues), []);

  // Un error de otro paso sigue en el resumen del paso, no se pierde.
  const mixed = rulesIssues(validateRulesConfig({
    ...config,
    points_system: { win: -1, draw: 1, loss: 0 },
  }));
  assert.equal(summaryFieldIssues(mixed).length, 1);
  assert.equal(summaryFieldIssues(mixed)[0]?.stepId, 'rules.scoring');

  const wizard = rulesWizardSource();
  assert.match(wizard, /summaryFieldIssues\(/);
  assert.match(wizard, /:field-issues="currentIssues"/);
  assert.match(wizard, /class="rules-errors"/);

  assert.match(editorSource, /fieldIssues/);
  assert.match(editorSource, /aria-invalid/);
  assert.match(editorSource, /aria-describedby/);
  assert.match(editorSource, /role="alert"/);
  assert.match(editorSource, new RegExp(`RULES_INLINE_FIELD_IDS\\.min_players_per_team`));
  assert.match(editorSource, new RegExp(`RULES_INLINE_FIELD_IDS\\.max_players_per_team`));
  assert.equal(RULES_INLINE_FIELD_IDS.min_players_per_team, 'rules-field-min-players-error');
  assert.equal(RULES_INLINE_FIELD_IDS.max_players_per_team, 'rules-field-max-players-error');
});

test('the declared format never derives or constrains the roster limits', () => {
  const payloads = GAME_FORMAT_OPTIONS.map((format) => {
    const config = configWithLimits(5, 30);
    config.game_format = format;

    // El mismo rango es válido con 5v5 y con 11v11 (RF-043, caso 55).
    assert.deepEqual(validateRulesConfig(config), []);

    const payload = buildRulesPayload(config as never).rules_config;
    assert.equal(payload.game_format, format);
    assert.equal(payload.min_players_per_team, 5);
    assert.equal(payload.max_players_per_team, 30);
    return payload;
  });

  for (const payload of payloads.slice(1)) {
    const { game_format: _format, ...rest } = payload;
    const { game_format: _first, ...firstRest } = payloads[0]!;
    assert.deepEqual(rest, firstRest);
  }
});

test('warns in the three surfaces only when the declared format is not 11v11', () => {
  assert.equal(formatWarns('5v5'), true);
  assert.equal(formatWarns('7v7'), true);
  assert.equal(formatWarns('9v9'), true);
  assert.equal(formatWarns('11v11'), false);
  assert.equal(formatWarns(''), false);
  assert.equal(formatWarns(undefined), false);
  assert.equal(formatWarns({ nope: true }), false);

  const warningSource = readFileSync(
    new URL('../app/components/FormatWarning.vue', import.meta.url),
    'utf8',
  );
  assert.match(warningSource, /formatWarns/);
  assert.match(warningSource, /t\(/);
  assert.doesNotMatch(warningSource, /disabled/, 'the format warning never blocks an action');

  const matchPageSource = readFileSync(
    new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
    'utf8',
  );

  // Tres lugares: paso de reglas, resumen de configuración y operación/planilla.
  assert.match(editorSource, /<FormatWarning/);
  assert.match(editorSource, /format\.notice\.rules/);
  assert.match(tournamentPageSource, /<FormatWarning/);
  assert.match(tournamentPageSource, /format\.notice\.summary/);
  assert.match(matchPageSource, /<FormatWarning/);
  assert.match(matchPageSource, /format\.notice\.operation/);

  // La advertencia no bloquea: 7v7 con límites válidos se puede guardar.
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.game_format = '7v7';
  config.min_players_per_team = 7;
  config.max_players_per_team = 12;
  const check = checkRulesSave(config, rulesIssues(validateRulesConfig(config)), fakeTranslate);
  assert.equal(check.ok, true);

  const { spanish, english } = catalogSlices();
  for (const key of ['format.notice.rules', 'format.notice.summary', 'format.notice.operation']) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `missing Spanish key ${key}`);
    assert.match(english, pattern, `missing English key ${key}`);
  }
});

test('the advanced mode keeps the format and the two limits', () => {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.game_format = '9v9';
  config.min_players_per_team = 7;
  config.max_players_per_team = 12;

  const parsed = parseRulesConfigJson(serializeRulesConfig(config));
  assert.equal(parsed.errors.length, 0);
  assert.equal(parsed.config?.game_format, '9v9');
  assert.equal(parsed.config?.min_players_per_team, 7);
  assert.equal(parsed.config?.max_players_per_team, 12);

  const payload = buildRulesPayload(parsed.config!).rules_config;
  assert.equal(payload.game_format, '9v9');
  assert.equal(payload.min_players_per_team, 7);
  assert.equal(payload.max_players_per_team, 12);

  // Una clave del catálogo desconocida se rechaza también en el modo avanzado.
  const invalid = cloneRulesConfig(DEFAULT_RULES_CONFIG) as Record<string, any>;
  invalid.game_format = '3v3';
  assert.ok(validateRulesConfig(invalid).some((error) => error.code === 'game_format'));
});
