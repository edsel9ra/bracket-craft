import assert from 'node:assert/strict';
import test from 'node:test';

import {
  TEAM_ENTRY_GROUP,
  canConfirm,
  firstStepId,
  nextStepId,
  obligationLabelKey,
  previousStepId,
  stepState,
  stepStateLabelKey,
  wizardStepStates,
  wizardSteps,
  type WizardErrors,
  type WizardKind,
  type WizardStepId,
  type WizardStepStatus,
  type WizardValues,
} from '../app/utils/wizardModel.ts';

const t = (key: string) => `t:${key}`;

function statuses(
  wizard: WizardKind,
  values: WizardValues = {},
  errors: WizardErrors = {},
): WizardStepStatus[] {
  return wizardStepStates(wizard, t, values, errors);
}

function stateOf(
  wizard: WizardKind,
  id: WizardStepId,
  values: WizardValues = {},
  errors: WizardErrors = {},
): string {
  const entry = statuses(wizard, values, errors).find((candidate) => candidate.id === id);
  assert.ok(entry, `missing step ${id}`);
  return entry.state;
}

test('declares the rules assistant with required, optional and format steps', () => {
  const steps = wizardSteps('rules', t);

  assert.deepEqual(
    steps.map((step) => step.id),
    [
      'rules.scoring',
      'rules.tiebreakers',
      'rules.discipline',
      'rules.resolution',
      'rules.format',
      'rules.substitutions',
      'rules.registration',
      'rules.overrides',
    ],
  );
  assert.deepEqual(
    steps.map((step) => step.obligation),
    ['required', 'required', 'required', 'required', 'required', 'optional', 'optional', 'optional'],
  );
  assert.equal(steps[0]?.label, 't:wizard.rules.scoring');
  assert.equal(steps[0]?.labelKey, 'wizard.rules.scoring');
  assert.equal(steps[5]?.label, 't:wizard.rules.substitutions');
});

test('the format step keeps the format required and the limits optional', () => {
  const format = wizardSteps('rules', t).find((step) => step.id === 'rules.format');

  assert.ok(format);
  assert.deepEqual(
    format.fields.map((field) => [field.id, field.obligation]),
    [
      ['gameFormat', 'required'],
      ['minPlayers', 'optional'],
      ['maxPlayers', 'optional'],
    ],
  );
});

test('declares the phases assistant with the composition as the only optional step', () => {
  const steps = wizardSteps('phases', t);

  assert.deepEqual(
    steps.map((step) => [step.id, step.obligation]),
    [
      ['phases.identity', 'required'],
      ['phases.composition', 'optional'],
      ['phases.review', 'required'],
    ],
  );
  assert.equal(steps[2]?.label, 't:wizard.phases.review');
});

test('declares the teams assistant with two exclusive alternative entry paths', () => {
  const steps = wizardSteps('teams', t);
  const individual = steps.find((step) => step.id === 'teams.individual');
  const bulk = steps.find((step) => step.id === 'teams.bulk');

  assert.deepEqual(
    steps.map((step) => [step.id, step.obligation]),
    [
      ['teams.details', 'required'],
      ['teams.individual', 'alternative'],
      ['teams.bulk', 'alternative'],
      ['teams.review', 'required'],
    ],
  );
  assert.ok(individual?.group);
  assert.equal(individual?.group, TEAM_ENTRY_GROUP);
  assert.equal(bulk?.group, TEAM_ENTRY_GROUP);
  assert.equal(steps[0]?.group, undefined);
});

test('keeps a stable step order between calls', () => {
  assert.deepEqual(
    wizardSteps('rules', t).map((step) => step.id),
    wizardSteps('rules', t).map((step) => step.id),
  );
});

test('marks a required step as incomplete until its fields are filled', () => {
  assert.equal(stateOf('teams', 'teams.details'), 'incomplete');
  assert.equal(stateOf('teams', 'teams.details', { name: 'Alpha' }), 'incomplete');
  assert.equal(stateOf('teams', 'teams.details', { name: 'Alpha', code: 'ALP' }), 'complete');
});

test('treats blank strings as a missing value', () => {
  assert.equal(stateOf('teams', 'teams.details', { name: '   ', code: 'ALP' }), 'incomplete');
  assert.equal(stateOf('rules', 'rules.scoring', { scoring: '' }), 'incomplete');
});

test('treats an empty array as omitted and a filled array as configured', () => {
  assert.equal(stateOf('phases', 'phases.composition', { teamIds: [] }), 'omitted');
  assert.equal(stateOf('phases', 'phases.composition', { teamIds: ['team-a'] }), 'complete');
  assert.equal(stateOf('phases', 'phases.composition', { teamIds: [] }), 'omitted');
});

test('maximizes a recorded error over the other states of the step', () => {
  const errors: WizardErrors = { 'teams.details': ['name'] };

  assert.equal(stateOf('teams', 'teams.details', { name: 'Alpha', code: 'ALP' }, errors), 'error');
  assert.equal(stateOf('teams', 'teams.details', {}, { 'teams.details': ['name'] }), 'error');
  assert.equal(stateOf('teams', 'teams.details', { name: 'Alpha', code: 'ALP' }, { 'teams.details': [] }), 'complete');
});

test('an optional step without values is omitted, never incomplete nor error', () => {
  assert.equal(stateOf('rules', 'rules.substitutions'), 'omitted');
  assert.equal(stateOf('rules', 'rules.registration'), 'omitted');
  assert.equal(stateOf('rules', 'rules.overrides'), 'omitted');
});

test('an optional step with values is complete and with a missing required field is incomplete', () => {
  assert.equal(stateOf('rules', 'rules.substitutions', { substitutions: { maxPerTeam: 5 } }), 'complete');
  assert.equal(
    stateOf('rules', 'rules.substitutions', { substitutions: {} }),
    'complete',
  );
  assert.equal(
    stateOf('rules', 'rules.substitutions', {}, { 'rules.substitutions': ['maxWindows'] }),
    'error',
  );
});

test('an alternative step is alternative until a path is filled and validated', () => {
  assert.equal(stateOf('teams', 'teams.individual'), 'alternative');
  assert.equal(stateOf('teams', 'teams.bulk'), 'alternative');
  assert.equal(
    stateOf('teams', 'teams.individual', { individualRows: [{ first_name: 'Ana', last_name: 'Díaz' }] }),
    'complete',
  );
  assert.equal(
    stateOf('teams', 'teams.bulk', { individualRows: [{ first_name: 'Ana' }] }),
    'alternative',
  );
  assert.equal(
    stateOf(
      'teams',
      'teams.individual',
      { individualRows: [{ first_name: 'Ana' }] },
      { 'teams.individual': ['last_name'] },
    ),
    'error',
  );
});

test('the format step is complete with the format present and the limits empty', () => {
  assert.equal(stateOf('rules', 'rules.format', { gameFormat: '11v11' }), 'complete');
  assert.equal(stateOf('rules', 'rules.format', { gameFormat: '7v7', minPlayers: 0, maxPlayers: 0 }), 'complete');
  assert.equal(stateOf('rules', 'rules.format', { minPlayers: 5 }), 'incomplete');
  assert.equal(stateOf('rules', 'rules.format', {}), 'incomplete');
  assert.equal(
    stateOf('rules', 'rules.format', { gameFormat: '11v11' }, { 'rules.format': ['minPlayers'] }),
    'error',
  );
});

test('a review step without fields is complete unless it records an error', () => {
  assert.equal(stateOf('phases', 'phases.review'), 'complete');
  assert.equal(stateOf('teams', 'teams.review'), 'complete');
  assert.equal(stateOf('teams', 'teams.review', {}, { 'teams.review': ['unexpected'] }), 'error');
});

test('blocked steps keep the declaration order and ignore optional steps', () => {
  const result = canConfirm('rules', statuses('rules', {}));

  assert.equal(result.ok, false);
  assert.deepEqual(result.blockedBy, [
    'rules.scoring',
    'rules.tiebreakers',
    'rules.discipline',
    'rules.resolution',
    'rules.format',
  ]);
});

test('confirms the rules assistant with the required steps complete and the optional ones omitted', () => {
  const result = canConfirm('rules', statuses('rules', {
    scoring: { win: 3 },
    tiebreakers: ['goal_difference'],
    discipline: { yellow: 1 },
    resolution: { allow_extra_time: true },
    gameFormat: '11v11',
  }));

  assert.deepEqual(result, { ok: true, blockedBy: [] });
});

test('an error in an optional step blocks the confirmation', () => {
  const result = canConfirm('rules', statuses('rules', {
    scoring: {},
    tiebreakers: ['goal_difference'],
    discipline: {},
    resolution: {},
    gameFormat: '11v11',
  }, { 'rules.substitutions': ['max_per_team'] }));

  assert.equal(result.ok, false);
  assert.deepEqual(result.blockedBy, ['rules.substitutions']);
});

test('confirms the phases assistant without the optional composition', () => {
  const identity = { name: 'Grupo A', stageOrder: 1, stageType: 'round_robin' };

  assert.deepEqual(canConfirm('phases', statuses('phases', identity)), { ok: true, blockedBy: [] });
  assert.equal(
    canConfirm('phases', statuses('phases', { name: 'Grupo A' })).ok,
    false,
  );
});

test('requires exactly one alternative path in the teams assistant', () => {
  const base = { name: 'Alpha', code: 'ALP' };

  const none = canConfirm('teams', statuses('teams', base));
  assert.equal(none.ok, false);
  assert.deepEqual(none.blockedBy, ['teams.individual', 'teams.bulk']);

  const individual = canConfirm('teams', statuses('teams', {
    ...base,
    individualRows: [{ first_name: 'Ana', last_name: 'Díaz' }],
  }));
  assert.deepEqual(individual, { ok: true, blockedBy: [] });

  const bulk = canConfirm('teams', statuses('teams', { ...base, bulkCsv: 'name;code' }));
  assert.deepEqual(bulk, { ok: true, blockedBy: [] });
});

test('rejects two alternative paths chosen at once', () => {
  const result = canConfirm('teams', statuses('teams', {
    name: 'Alpha',
    code: 'ALP',
    individualRows: [{ first_name: 'Ana', last_name: 'Díaz' }],
    bulkCsv: 'name;code',
  }));

  assert.equal(result.ok, false);
  assert.deepEqual(result.blockedBy, ['teams.individual', 'teams.bulk']);
});

test('requires the details and a path for the teams assistant', () => {
  const result = canConfirm('teams', statuses('teams', {
    individualRows: [{ first_name: 'Ana', last_name: 'Díaz' }],
  }));

  assert.equal(result.ok, false);
  assert.deepEqual(result.blockedBy, ['teams.details']);
});

test('computes the first, previous and next step and stops at both extremes', () => {
  assert.equal(firstStepId('rules'), 'rules.scoring');
  assert.equal(firstStepId('phases'), 'phases.identity');
  assert.equal(firstStepId('teams'), 'teams.details');

  assert.equal(previousStepId('rules', 'rules.scoring'), null);
  assert.equal(nextStepId('rules', 'rules.scoring'), 'rules.tiebreakers');
  assert.equal(previousStepId('rules', 'rules.overrides'), 'rules.registration');
  assert.equal(nextStepId('rules', 'rules.overrides'), null);

  assert.equal(nextStepId('teams', 'teams.individual'), 'teams.bulk');
  assert.equal(previousStepId('teams', 'teams.review'), 'teams.bulk');
  assert.equal(nextStepId('phases', 'phases.unknown' as WizardStepId), null);
  assert.equal(previousStepId('phases', 'phases.unknown' as WizardStepId), null);
});

test('exposes the i18n keys of every state and obligation', () => {
  assert.equal(stepStateLabelKey('complete'), 'wizard.state.complete');
  assert.equal(stepStateLabelKey('incomplete'), 'wizard.state.incomplete');
  assert.equal(stepStateLabelKey('error'), 'wizard.state.error');
  assert.equal(stepStateLabelKey('omitted'), 'wizard.state.omitted');
  assert.equal(stepStateLabelKey('alternative'), 'wizard.state.alternative');

  assert.equal(obligationLabelKey('required'), 'wizard.obligation.required');
  assert.equal(obligationLabelKey('optional'), 'wizard.obligation.optional');
  assert.equal(obligationLabelKey('alternative'), 'wizard.obligation.alternative');
});

test('stepState only depends on the received values and errors', () => {
  const step = wizardSteps('rules', t).find((candidate) => candidate.id === 'rules.scoring');
  assert.ok(step);

  assert.equal(stepState(step, {}), 'incomplete');
  assert.equal(stepState(step, { scoring: { win: 3 } }), 'complete');
  assert.equal(stepState(step, {}), 'incomplete');
});
