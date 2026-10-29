import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  assignmentOutcome,
  availableStageTeams,
  dedupeTeamIds,
  normalizeAssignmentResponse,
  normalizeStageTeamsResponse,
  pruneStageTeamSelection,
  sortStageTeams,
  stageTeamActionFromStatus,
} from '../app/utils/stageTeams.ts';
import {
  MAX_STAGE_TEAMS,
  buildStageBody,
  firstStageByOrder,
  nextStageOrder,
  openExistingStage,
  planStageCreation,
  planStageRetry,
  reviewStage,
  stageConfirmation,
  stageCreateFailure,
  stageSaveFailed,
  stageSaveSucceeded,
  stageWizardStatuses,
  validateStageValues,
} from '../app/utils/stageWizard.ts';
import {
  MAX_BULK_TEAMS,
  bulkTeamsPath,
  buildBulkTeamsBody,
  buildTeamBody,
  columnLabelKey,
  parseTeamCsv,
  phasesAssistantHref,
  planTeamCreation,
  restoreTeamValues,
  reviewTeams,
  showsEntryPathStep,
  teamConfirmation,
  teamDraftValues,
  teamWizardStatuses,
  teamWizardValues,
  teamsPath,
  validateTeamValues,
} from '../app/utils/teamsWizard.ts';

const alpha = { team_id: 'team-a', name: 'Alpha', short_code: 'ALP' };
const beta = { team_id: 'team-b', name: 'Beta', short_code: 'BET' };
const gamma = { team_id: 'team-c', name: 'Gamma', short_code: 'GAM' };

test('deduplicates ids preserving the first occurrence order', () => {
  assert.deepEqual(dedupeTeamIds(['b', 'a', 'b', 'c', 'a']), ['b', 'a', 'c']);
});

test('sorts teams by name and keeps a detached array', () => {
  const source = [gamma, alpha, beta];

  const sorted = sortStageTeams(source);

  assert.deepEqual(sorted.map((team) => team.team_id), ['team-a', 'team-b', 'team-c']);
  assert.deepEqual(source.map((team) => team.team_id), ['team-c', 'team-a', 'team-b']);
});

test('normalizes a GET response, deduplicates and moves overlaps to assigned', () => {
  const normalized = normalizeStageTeamsResponse({
    stage_id: 'stage-1',
    version_id: 'version-1',
    assigned: [beta, { ...beta, name: 'Beta duplicated' }, alpha, { team_id: 'broken' }],
    unassigned: [gamma, gamma, alpha, { name: 'No id', short_code: 'NID' }],
  });

  assert.ok(normalized);
  assert.equal(normalized.stage_id, 'stage-1');
  assert.equal(normalized.version_id, 'version-1');
  assert.deepEqual(normalized.assigned.map((team) => team.team_id), ['team-a', 'team-b']);
  assert.deepEqual(normalized.unassigned.map((team) => team.team_id), ['team-c']);
});

test('rejects malformed GET responses instead of returning partial data', () => {
  assert.equal(normalizeStageTeamsResponse(null), null);
  assert.equal(normalizeStageTeamsResponse({ assigned: [], unassigned: [] }), null);
  assert.equal(
    normalizeStageTeamsResponse({ stage_id: 's', version_id: 'v', assigned: {}, unassigned: [] }),
    null,
  );
});

test('returns the available teams of a missing response as an empty list', () => {
  assert.deepEqual(availableStageTeams(null), []);
  assert.deepEqual(
    availableStageTeams({ stage_id: 's', version_id: 'v', assigned: [alpha], unassigned: [gamma, beta] })
      .map((team) => team.team_id),
    ['team-b', 'team-c'],
  );
});

test('prunes a selection that no longer belongs to the available list', () => {
  assert.deepEqual(
    pruneStageTeamSelection(['team-c', 'team-a', 'team-c', 'team-z'], [alpha, gamma]),
    ['team-c', 'team-a'],
  );
});

test('maps the POST/DELETE status to a UI outcome', () => {
  assert.equal(stageTeamActionFromStatus(201), 'assigned');
  assert.equal(stageTeamActionFromStatus(200), 'already_assigned');
  assert.equal(stageTeamActionFromStatus(204), 'removed');
  assert.equal(stageTeamActionFromStatus(400), 'invalid');
  assert.equal(stageTeamActionFromStatus(422), 'invalid');
  assert.equal(stageTeamActionFromStatus(403), 'forbidden');
  assert.equal(stageTeamActionFromStatus(404), 'not_found');
  assert.equal(stageTeamActionFromStatus(409), 'conflict');
  assert.equal(stageTeamActionFromStatus(500), 'error');
});

test('normalizes the assignment response and deduplicates its arrays', () => {
  const normalized = normalizeAssignmentResponse({
    stage_id: 'stage-1',
    version_id: 'version-1',
    team_ids: ['team-a', 'team-b', 'team-a'],
    assigned: ['team-a', 'team-a'],
    already_assigned: ['team-b'],
  });

  assert.ok(normalized);
  assert.deepEqual(normalized.team_ids, ['team-a', 'team-b']);
  assert.deepEqual(normalized.assigned, ['team-a']);
  assert.deepEqual(normalized.already_assigned, ['team-b']);
  assert.equal(normalizeAssignmentResponse({ stage_id: 's' }), null);
});

test('distinguishes a new assignment from an idempotent one', () => {
  assert.equal(assignmentOutcome({ assigned: ['team-a'], already_assigned: [] } as never), 'assigned');
  assert.equal(assignmentOutcome({ assigned: [], already_assigned: ['team-a'] } as never), 'already_assigned');
  assert.equal(assignmentOutcome(null), 'already_assigned');
});

// ---------------------------------------------------------------------------
// Asistente de fases (spec 012, RF-002, RF-006, RF-010; AT-1)
// ---------------------------------------------------------------------------

const t = (key: string) => `t:${key}`;
const identity = { name: 'Grupo A', stageOrder: 1, stageType: 'round_robin' } as const;

test('requires the name, the order and the format to identify the phase', () => {
  assert.deepEqual(validateStageValues({}), [
    { stepId: 'phases.identity', field: 'name', messageKey: 'stage.wizard.error.name' },
    { stepId: 'phases.identity', field: 'stageOrder', messageKey: 'stage.wizard.error.stageOrder' },
    { stepId: 'phases.identity', field: 'stageType', messageKey: 'stage.wizard.error.stageType' },
  ]);
  assert.deepEqual(validateStageValues(identity), []);
  assert.deepEqual(validateStageValues({ name: '  A  ', stageOrder: 2, stageType: 'swiss' }), [
    { stepId: 'phases.identity', field: 'name', messageKey: 'stage.wizard.error.name' },
  ]);
  assert.deepEqual(validateStageValues({ ...identity, stageOrder: 0 }), [
    { stepId: 'phases.identity', field: 'stageOrder', messageKey: 'stage.wizard.error.stageOrder' },
  ]);
  assert.deepEqual(validateStageValues({ ...identity, stageOrder: 'dos' }), [
    { stepId: 'phases.identity', field: 'stageOrder', messageKey: 'stage.wizard.error.stageOrder' },
  ]);
  assert.deepEqual(validateStageValues({ ...identity, stageType: 'league' }), [
    { stepId: 'phases.identity', field: 'stageType', messageKey: 'stage.wizard.error.stageType' },
  ]);
  assert.deepEqual(validateStageValues({ ...identity, name: 'x'.repeat(51) }), [
    { stepId: 'phases.identity', field: 'name', messageKey: 'stage.wizard.error.name' },
  ]);
});

test('accepts an empty composition and caps the stage at 64 teams', () => {
  const teamIds = Array.from({ length: MAX_STAGE_TEAMS }, (_, index) => `team-${index}`);

  assert.equal(MAX_STAGE_TEAMS, 64);
  assert.deepEqual(validateStageValues({ ...identity, teamIds: [] }), []);
  assert.deepEqual(validateStageValues({ ...identity, teamIds }), []);
  assert.deepEqual(validateStageValues({ ...identity, teamIds: [...teamIds, 'team-0'] }), []);
  assert.deepEqual(validateStageValues({ ...identity, teamIds: [...teamIds, 'team-64'] }), [
    { stepId: 'phases.composition', field: 'teamIds', messageKey: 'stage.wizard.error.teamLimit' },
  ]);
});

test('the index marks the composition as omitted and keeps the confirmation available', () => {
  const statuses = stageWizardStatuses(identity, [], t);

  assert.deepEqual(
    statuses.map((status) => [status.id, status.state]),
    [
      ['phases.identity', 'complete'],
      ['phases.composition', 'omitted'],
      ['phases.review', 'complete'],
    ],
  );
  assert.deepEqual(stageConfirmation(identity, [], t), { ok: true, blockedBy: [] });
});

test('an invalid identification blocks the confirmation and marks the step with error', () => {
  const values = { name: '', stageOrder: 1, stageType: 'round_robin' };
  const issues = validateStageValues(values);
  const statuses = stageWizardStatuses(values, issues, t);

  assert.equal(statuses[0]?.state, 'error');
  assert.deepEqual(stageConfirmation(values, issues, t), { ok: false, blockedBy: ['phases.identity'] });
});

test('summarizes the phase in the review step', () => {
  const review = reviewStage({
    mode: 'create',
    values: { name: '  Grupo A ', stageOrder: '3', stageType: 'single_elimination', teamIds: ['team-a', 'team-a', 'team-b'] },
  });

  assert.equal(review.mode, 'create');
  assert.equal(review.stageId, null);
  assert.equal(review.name, 'Grupo A');
  assert.equal(review.stageOrder, 3);
  assert.equal(review.stageType, 'single_elimination');
  assert.equal(review.stageTypeLabelKey, 'stage.singleElimination');
  assert.equal(review.teamCount, 2);
  assert.deepEqual(review.teamIds, ['team-a', 'team-b']);
  assert.ok(review.warningKeys.includes('stage.wizard.calendarNotice'));
  assert.ok(!review.warningKeys.includes('stage.wizard.optionalComposition'));

  const empty = reviewStage({ mode: 'create', values: identity });
  assert.ok(empty.warningKeys.includes('stage.wizard.optionalComposition'));
  assert.equal(empty.teamCount, 0);
});

test('builds the creation body with the version and the normalized identity', () => {
  assert.deepEqual(buildStageBody({ versionId: 'version-1', values: { ...identity, name: ' Grupo A ' } }), {
    version_id: 'version-1',
    name: 'Grupo A',
    stage_type: 'round_robin',
    stage_order: 1,
  });
});

test('plans the stage creation and then the inscription in that order', () => {
  const plan = planStageCreation({
    versionId: 'version-1',
    values: { ...identity, teamIds: ['team-b', 'team-a', 'team-b'] },
  });

  assert.equal(plan.mode, 'create');
  assert.deepEqual(plan.steps.map((step) => step.kind), ['create_stage', 'assign_teams']);

  const createStep = plan.steps[0];
  assert.equal(createStep?.kind, 'create_stage');
  if (createStep?.kind !== 'create_stage') assert.fail('expected a create step');
  assert.deepEqual(createStep.body, {
    version_id: 'version-1',
    name: 'Grupo A',
    stage_type: 'round_robin',
    stage_order: 1,
  });

  const assignStep = plan.steps[1];
  assert.equal(assignStep?.kind, 'assign_teams');
  if (assignStep?.kind !== 'assign_teams') assert.fail('expected an assign step');
  // La fase todavía no existe: la aporta el paso anterior.
  assert.equal(assignStep.stageId, null);
  assert.deepEqual(assignStep.teamIds, ['team-b', 'team-a']);
});

test('a phase without composition is a single creation call', () => {
  const plan = planStageCreation({ versionId: 'version-1', values: { ...identity, teamIds: [] } });

  assert.deepEqual(plan.steps.map((step) => step.kind), ['create_stage']);
});

test('retrying the inscription reuses the created phase and never creates a second one', () => {
  const plan = planStageRetry({ stageId: 'stage-1', teamIds: ['team-a', 'team-a', 'team-b'] });

  assert.equal(plan.mode, 'retry');
  assert.equal(plan.steps.length, 1);
  assert.deepEqual(plan.steps.map((step) => step.kind), ['assign_teams']);

  const assignStep = plan.steps[0];
  assert.equal(assignStep?.kind, 'assign_teams');
  if (assignStep?.kind !== 'assign_teams') assert.fail('expected an assign step');
  assert.equal(assignStep.stageId, 'stage-1');
  assert.deepEqual(assignStep.teamIds, ['team-a', 'team-b']);
});

test('reports the created phase when the inscription succeeds', () => {
  const result = stageSaveSucceeded({
    mode: 'create',
    stageId: 'stage-1',
    requestedTeamIds: ['team-a', 'team-b'],
    response: {
      stage_id: 'stage-1',
      version_id: 'version-1',
      team_ids: ['team-a', 'team-b'],
      assigned: ['team-a'],
      already_assigned: ['team-b'],
    },
  });

  assert.equal(result.status, 'created');
  assert.equal(result.stageId, 'stage-1');
  assert.deepEqual(result.pendingTeamIds, []);
  assert.equal(result.messageKey, 'stage.wizard.createdAndAssigned');
  assert.equal(result.canRetry, false);

  const withoutTeams = stageSaveSucceeded({
    mode: 'create',
    stageId: 'stage-1',
    requestedTeamIds: [],
    response: null,
  });
  assert.equal(withoutTeams.status, 'created');
  assert.equal(withoutTeams.messageKey, 'stage.wizard.createdWithoutTeams');
});

test('a failed inscription leaves the created phase and keeps the selection for a retry', () => {
  const result = stageSaveFailed({
    stageId: 'stage-1',
    requestedTeamIds: ['team-a', 'team-b'],
    cause: { status: 409, data: { detail: 'Fuera de rango' } },
  });

  assert.equal(result.status, 'partial');
  assert.equal(result.stageId, 'stage-1');
  assert.deepEqual(result.pendingTeamIds, ['team-a', 'team-b']);
  assert.equal(result.messageKey, 'stage.wizard.partial');
  assert.equal(result.canRetry, true);
  assert.equal(result.verifyByReload, false);
});

test('an ambiguous creation never invites creating another phase', () => {
  const timeout = stageCreateFailure({ name: 'FetchError', message: 'request timeout' });

  assert.equal(timeout.kind, 'ambiguous');
  assert.equal(timeout.messageKey, 'stage.wizard.createAmbiguous');
  assert.equal(timeout.reloadStages, true);
  assert.equal(timeout.retryCreate, false);

  const lostResponse = stageCreateFailure({ name: 'TypeError', message: 'Failed to fetch' });
  assert.equal(lostResponse.kind, 'ambiguous');
  assert.equal(lostResponse.retryCreate, false);

  const rejected = stageCreateFailure({ status: 409, data: { detail: 'La versión publicada es inmutable' } });
  assert.equal(rejected.kind, 'rejected');
  assert.equal(rejected.messageKey, 'stage.wizard.createRejected');
  assert.equal(rejected.reloadStages, false);
  assert.equal(rejected.retryCreate, true);
});

test('an existing phase opens directly on the composition step in read-only identity', () => {
  const stages = [
    { id: 'stage-b', name: 'Fase B', stage_type: 'swiss', stage_order: 2 },
    { id: 'stage-a', name: 'Fase A', stage_type: 'round_robin', stage_order: 1 },
  ];

  assert.equal(firstStageByOrder(stages)?.id, 'stage-a');
  assert.equal(firstStageByOrder([]), null);
  assert.equal(nextStageOrder(stages), 3);
  assert.equal(nextStageOrder([]), 1);

  const context = openExistingStage(stages);
  assert.ok(context);
  assert.equal(context.stageId, 'stage-a');
  assert.equal(context.startStep, 'phases.composition');
  assert.equal(context.readOnly, true);
  assert.deepEqual(context.identity, { name: 'Fase A', stageOrder: 1, stageType: 'round_robin' });

  assert.equal(openExistingStage(stages, 'stage-b')?.stageId, 'stage-b');
  assert.equal(openExistingStage(stages, 'stage-missing')?.stageId, 'stage-a');
  assert.equal(openExistingStage([]), null);
});

const configurationPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
  'utf8',
);
const stageWizardComponent = readFileSync(
  new URL('../app/components/StageTeamsWizard.vue', import.meta.url),
  'utf8',
);

test('the phases wizard owns the creation and the retry and writes through useApi', () => {
  assert.match(configurationPage, /<StageTeamsWizard/);
  assert.doesNotMatch(configurationPage, /stageTeamSelection/);
  assert.match(stageWizardComponent, /useApi\(\)/);
  assert.match(stageWizardComponent, /planStageCreation\(/);
  // El reintento solo planifica la inscripción sobre la fase conocida (AT-1).
  assert.match(stageWizardComponent, /planStageRetry\(/);
  assert.doesNotMatch(stageWizardComponent, /localStorage/);
});

// ---------------------------------------------------------------------------
// Asistente de equipos (spec 012, RF-003, RF-011, RF-021; H1-T07)
// ---------------------------------------------------------------------------

const csvWithHeader = [
  'name,short_code,logo_url',
  'Club Norte,CN,https://cdn.test/norte.png',
  'Club Sur,CS,',
].join('\n');

test('parses the bulk CSV keeping the existing columns and header detection', () => {
  const parsed = parseTeamCsv(csvWithHeader);

  assert.equal(parsed.headerDetected, true);
  assert.equal(parsed.dataRowCount, 2);
  assert.deepEqual(parsed.issues, []);
  assert.deepEqual(parsed.rows, [
    { name: 'Club Norte', short_code: 'CN', logo_url: 'https://cdn.test/norte.png' },
    { name: 'Club Sur', short_code: 'CS', logo_url: null },
  ]);

  // Sin encabezado se aceptan las mismas columnas; BOM y comillas se respetan.
  const withoutHeader = parseTeamCsv('\uFEFF"Club, Este",CE\n');
  assert.equal(withoutHeader.headerDetected, false);
  assert.deepEqual(withoutHeader.rows, [{ name: 'Club, Este', short_code: 'CE', logo_url: null }]);
});

test('reports every invalid CSV row with its row and column', () => {
  const parsed = parseTeamCsv([
    'name,short_code,logo_url',
    'A,CN,',
    'Club Sur,CS,',
    'Club Este,C,',
    'Club Oeste,CO,ftp://logo.test/x.png',
    'Club Sur Repetido,cs,',
  ].join('\n'));

  assert.deepEqual(parsed.rows.map((row) => row.short_code), ['CS']);
  assert.deepEqual(
    parsed.issues.map((issue) => [issue.row, issue.column, issue.messageKey]),
    [
      [1, 'name', 'setup.csvName'],
      [3, 'short_code', 'setup.csvCode'],
      [4, 'logo_url', 'setup.csvLogo'],
      [5, 'short_code', 'setup.csvDuplicate'],
    ],
  );
  assert.equal(columnLabelKey('name'), 'teams.wizard.column.name');
  assert.equal(columnLabelKey('short_code'), 'teams.wizard.column.code');
  assert.equal(columnLabelKey('logo_url'), 'teams.wizard.column.logo');
  assert.equal(columnLabelKey('file'), 'teams.wizard.column.file');
});

test('keeps the existing CSV limits: empty, header only and 200 rows', () => {
  assert.equal(MAX_BULK_TEAMS, 200);
  assert.deepEqual(parseTeamCsv('  \n ').issues.map((issue) => issue.messageKey), ['setup.csvEmpty']);
  assert.deepEqual(
    parseTeamCsv('name,short_code,logo_url').issues.map((issue) => issue.messageKey),
    ['setup.csvHeaderOnly'],
  );

  const rows = Array.from({ length: MAX_BULK_TEAMS + 1 }, (_, index) => `Club ${index},C${index},`);
  const overLimit = parseTeamCsv(rows.join('\n'));
  assert.deepEqual(overLimit.issues.map((issue) => issue.messageKey), ['setup.csvLimit']);
  assert.deepEqual(overLimit.rows, []);
});

test('validates the team details with the current rules', () => {
  // Sin vía individual, name/shortCode no son obligatorios ni bloquean.
  assert.deepEqual(validateTeamValues({}), []);
  // En vía individual, son obligatorios.
  assert.deepEqual(validateTeamValues({ entryPath: 'individual' }), [
    { stepId: 'teams.details', field: 'name', messageKey: 'teams.wizard.error.name' },
    { stepId: 'teams.details', field: 'shortCode', messageKey: 'teams.wizard.error.code' },
  ]);
  assert.deepEqual(validateTeamValues({ entryPath: 'individual', name: ' Club Norte ', shortCode: 'CN' }), []);
  assert.deepEqual(
    validateTeamValues({ entryPath: 'individual', name: 'A', shortCode: 'CN' }).map((issue) => issue.field),
    ['name'],
  );
  assert.deepEqual(
    validateTeamValues({ entryPath: 'individual', name: 'Club Norte', shortCode: 'C' }).map((issue) => issue.field),
    ['shortCode'],
  );
  assert.deepEqual(
    validateTeamValues({ entryPath: 'individual', name: 'Club Norte', shortCode: 'C C' }).map((issue) => issue.field),
    ['shortCode'],
  );
  // El error de formato se reporta aunque la vía no sea individual.
  assert.deepEqual(validateTeamValues({ name: 'A', shortCode: 'CN' }).map((issue) => issue.field), ['name']);
  assert.deepEqual(validateTeamValues({ name: 'Club Norte', shortCode: 'C' }).map((issue) => issue.field), ['shortCode']);
});

test('requires exactly one entry path: individual or bulk', () => {
  const details = { name: 'Club Norte', shortCode: 'CN' };

  const none = teamConfirmation(details, [], t);
  assert.deepEqual(none, { ok: false, blockedBy: ['teams.entry', 'teams.individual', 'teams.bulk'] });

  const individual = teamConfirmation({ ...details, entryPath: 'individual' }, [], t);
  assert.deepEqual(individual, { ok: true, blockedBy: [] });

  const bulk = teamConfirmation({ ...details, entryPath: 'bulk', bulkCsv: csvWithHeader }, [], t);
  assert.deepEqual(bulk, { ok: true, blockedBy: [] });

  // Elegir una vía deja la otra como alternativa, aunque conserve lo escrito.
  const statuses = teamWizardStatuses(
    { ...details, entryPath: 'individual', bulkCsv: 'name,short_code\nClub Sur,CS' },
    [],
    t,
  );
  assert.deepEqual(
    statuses.map((status) => [status.id, status.state]),
    [
      ['teams.entry', 'complete'],
      ['teams.details', 'complete'],
      ['teams.individual', 'complete'],
      ['teams.bulk', 'alternative'],
      ['teams.review', 'complete'],
    ],
  );
});

test('an invalid CSV row in the chosen path marks the step with error and blocks', () => {
  const values = { name: 'Club Norte', shortCode: 'CN', entryPath: 'bulk', bulkCsv: 'name,short_code\nA,CN' };
  const issues = validateTeamValues(values);
  const statuses = teamWizardStatuses(values, issues, t);

  assert.equal(issues[0]?.stepId, 'teams.bulk');
  assert.equal(issues[0]?.row, 1);
  assert.equal(issues[0]?.column, 'name');
  assert.equal(statuses.find((status) => status.id === 'teams.bulk')?.state, 'error');
  assert.equal(teamConfirmation(values, issues, t).ok, false);

  // La misma carga inválida no bloquea si la vía elegida es la individual.
  const individual = { ...values, entryPath: 'individual' };
  assert.equal(teamConfirmation(individual, validateTeamValues(individual), t).ok, true);
});

test('conserves the CSV text, the parsed rows and its errors when changing step', () => {
  const values = {
    name: ' Club Norte ',
    shortCode: 'CN',
    entryPath: 'bulk',
    bulkCsv: csvWithHeader,
    bulkFileName: 'equipos.csv',
  };

  const firstRead = teamWizardValues(values);
  assert.equal(firstRead.bulkCsv, csvWithHeader);

  // Ida y vuelta por el paso individual: el texto del CSV no se pierde.
  const onIndividual = { ...values, entryPath: 'individual' };
  assert.equal(teamWizardValues(onIndividual).bulkCsv, undefined);
  const backToBulk = { ...onIndividual, entryPath: 'bulk' };
  assert.equal(teamWizardValues(backToBulk).bulkCsv, csvWithHeader);
  assert.deepEqual(parseTeamCsv(teamWizardValues(backToBulk).bulkCsv).rows, parseTeamCsv(csvWithHeader).rows);
  assert.deepEqual(validateTeamValues(backToBulk), validateTeamValues(values));
});

test('survives a reload through the tab draft, without persistent storage', () => {
  const values = {
    name: ' Club Norte ',
    shortCode: 'CN',
    entryPath: 'bulk',
    bulkCsv: 'name,short_code\nClub Sur,CS\nA,CE',
    bulkFileName: 'equipos.csv',
  };

  const stored = teamDraftValues(values);
  assert.equal(stored.bulkCsv, values.bulkCsv);
  assert.equal(stored.bulkFileName, 'equipos.csv');

  const restored = restoreTeamValues(stored);
  assert.deepEqual(restored, stored);
  assert.deepEqual(parseTeamCsv(restored.bulkCsv), parseTeamCsv(values.bulkCsv));
  assert.deepEqual(validateTeamValues(restored), validateTeamValues(values));

  // Un borrador ilegible no rompe el asistente: valores vacíos. La vía se
  // infiere por defecto como individual (normalización legacy, RF-006).
  assert.deepEqual(restoreTeamValues(null), {
    name: '',
    shortCode: '',
    entryPath: 'individual',
    bulkCsv: '',
    bulkFileName: '',
  });
});

test('summarizes the chosen path and the teams to register in the review', () => {
  const individual = reviewTeams({ name: ' Club Norte ', shortCode: 'CN', entryPath: 'individual' });
  assert.equal(individual.path, 'individual');
  assert.equal(individual.pathLabelKey, 'teams.wizard.pathIndividual');
  assert.deepEqual(individual.teams, [{ name: 'Club Norte', short_code: 'CN', logo_url: null }]);
  assert.ok(individual.warningKeys.includes('teams.wizard.noStage'));

  const bulk = reviewTeams({ entryPath: 'bulk', bulkCsv: csvWithHeader });
  assert.equal(bulk.path, 'bulk');
  assert.equal(bulk.count, 2);
  assert.deepEqual(bulk.teams.map((team) => team.short_code), ['CN', 'CS']);
});

test('builds the creation bodies without a stage and plans one call per path', () => {
  assert.equal(teamsPath('tournament-1'), '/tournaments/tournament-1/teams');
  assert.equal(bulkTeamsPath('tournament-1'), '/tournaments/tournament-1/teams/bulk');
  assert.equal(
    phasesAssistantHref('tournament-1'),
    // RF-013 (spec 025): el enlace cruzado apunta al ancla `#fases` y no
    // escribe ningún paso en la dirección; el asistente resuelve el suyo.
    '/workspace/tournaments/tournament-1#fases',
  );

  assert.deepEqual(buildTeamBody({ name: ' Club Norte ', shortCode: 'CN' }), {
    name: 'Club Norte',
    short_code: 'CN',
  });
  assert.equal(buildTeamBody({ name: 'A', shortCode: 'CN' }), null);
  assert.deepEqual(buildBulkTeamsBody({ bulkCsv: csvWithHeader }), {
    teams: [
      { name: 'Club Norte', short_code: 'CN', logo_url: 'https://cdn.test/norte.png' },
      { name: 'Club Sur', short_code: 'CS', logo_url: null },
    ],
  });
  assert.equal(buildBulkTeamsBody({ bulkCsv: 'name,short_code\nA,CN' }), null);

  const individual = planTeamCreation({
    tournamentId: 'tournament-1',
    values: { name: 'Club Norte', shortCode: 'CN', entryPath: 'individual' },
  });
  assert.equal(individual.mode, 'individual');
  assert.deepEqual(individual.steps, [{
    kind: 'create_team',
    path: '/tournaments/tournament-1/teams',
    body: { name: 'Club Norte', short_code: 'CN' },
  }]);

  const bulk = planTeamCreation({
    tournamentId: 'tournament-1',
    values: { entryPath: 'bulk', bulkCsv: csvWithHeader },
  });
  assert.equal(bulk.mode, 'bulk');
  assert.deepEqual(bulk.steps.map((step) => [step.kind, step.path]), [
    ['create_teams_bulk', '/tournaments/tournament-1/teams/bulk'],
  ]);

  // RF-003 / IN-1: el alta no inscribe en ninguna fase.
  assert.doesNotMatch(JSON.stringify([individual, bulk]), /stage_id/);

  const broken = planTeamCreation({
    tournamentId: 'tournament-1',
    values: { entryPath: 'bulk', bulkCsv: 'name,short_code\nA,CN' },
  });
  assert.deepEqual(broken.steps, []);
  assert.deepEqual(
    planTeamCreation({ tournamentId: 'tournament-1', values: { name: 'Club Norte', shortCode: 'CN' } }).steps,
    [],
  );
});

const teamsWizardComponent = readFileSync(
  new URL('../app/components/TeamsWizard.vue', import.meta.url),
  'utf8',
);

test('the teams wizard is the only team creation surface and never sends a stage', () => {
  assert.match(configurationPage, /<TeamsWizard/);
  // RF-021: la página ya no replica el alta ni la carga masiva de equipos.
  assert.doesNotMatch(configurationPage, /selectedStageId/);
  assert.doesNotMatch(configurationPage, /\/teams\/bulk/);
  assert.doesNotMatch(configurationPage, /parseBulkTeams/);

  assert.match(teamsWizardComponent, /useApi\(\)/);
  assert.match(teamsWizardComponent, /planTeamCreation\(/);
  assert.match(teamsWizardComponent, /useWizardDraft/);
  // RF-003 / IN-1: el asistente no pide ni envía fase destino.
  assert.doesNotMatch(teamsWizardComponent, /stage_id|selectedStage/);
  assert.doesNotMatch(teamsWizardComponent, /localStorage/);
});

// RF-011: al elegir una vía, la otra queda oculta y sus valores se conservan
// para cuando el usuario vuelva. Las dos direcciones se comprueban.
test('hides the entry path that was not chosen and keeps its values', () => {
  assert.equal(showsEntryPathStep('teams.individual', 'individual'), true);
  assert.equal(showsEntryPathStep('teams.individual', 'bulk'), false);
  assert.equal(showsEntryPathStep('teams.bulk', 'bulk'), true);
  assert.equal(showsEntryPathStep('teams.bulk', 'individual'), false);
  assert.equal(showsEntryPathStep('teams.individual', null), true);
  assert.equal(showsEntryPathStep('teams.bulk', null), true);
  assert.equal(showsEntryPathStep('teams.details', 'bulk'), true);

  // RF-011: volver a la otra vía recupera el texto pegado y el archivo.
  const draft = teamDraftValues({
    name: 'Club Norte',
    shortCode: 'CN',
    entryPath: 'individual',
    bulkCsv: 'name,short_code\nSur,SU',
    bulkFileName: 'alta.csv',
  });
  assert.equal(draft.entryPath, 'individual');
  assert.equal(draft.bulkCsv, 'name,short_code\nSur,SU');
  assert.equal(draft.bulkFileName, 'alta.csv');

  assert.match(teamsWizardComponent, /showsEntryPathStep\('teams\.individual'/);
  assert.match(teamsWizardComponent, /showsEntryPathStep\('teams\.bulk'/);
  assert.match(
    teamsWizardComponent,
    /goTo\(path === 'individual' \? 'teams\.individual' : 'teams\.bulk'\)/,
  );
});

// ---------------------------------------------------------------------------
// Flujo completo del asistente de equipos (spec 027, T010, RF-013)
// ---------------------------------------------------------------------------
test('flujo completo: selección de modo → formulario → validación → revisión → confirmación (individual)', () => {
  const values = { entryPath: 'individual', name: ' Club Norte ', shortCode: 'CN' };

  // 1. Selección de modo
  const statuses = teamWizardStatuses(values, [], t);
  assert.equal(statuses.find((s) => s.id === 'teams.entry')?.state, 'complete');

  // 2. Formulario + validación
  const issues = validateTeamValues(values);
  assert.deepEqual(issues, []);

  // 3. Revisión
  const review = reviewTeams(values);
  assert.equal(review.path, 'individual');
  assert.deepEqual(review.teams, [{ name: 'Club Norte', short_code: 'CN', logo_url: null }]);

  // 4. Confirmación
  const confirmation = teamConfirmation(values, issues, t);
  assert.deepEqual(confirmation, { ok: true, blockedBy: [] });

  // 5. Plan de creación
  const plan = planTeamCreation({ tournamentId: 'tournament-1', values });
  assert.equal(plan.mode, 'individual');
  assert.equal(plan.steps.length, 1);
});

test('flujo completo: selección de modo → formulario → validación → revisión → confirmación (bulk)', () => {
  const values = { entryPath: 'bulk', bulkCsv: csvWithHeader, bulkFileName: 'equipos.csv' };

  const statuses = teamWizardStatuses(values, [], t);
  assert.equal(statuses.find((s) => s.id === 'teams.entry')?.state, 'complete');
  assert.equal(statuses.find((s) => s.id === 'teams.bulk')?.state, 'complete');

  const issues = validateTeamValues(values);
  assert.deepEqual(issues, []);

  const review = reviewTeams(values);
  assert.equal(review.path, 'bulk');
  assert.equal(review.count, 2);

  const confirmation = teamConfirmation(values, issues, t);
  assert.deepEqual(confirmation, { ok: true, blockedBy: [] });

  const plan = planTeamCreation({ tournamentId: 'tournament-1', values });
  assert.equal(plan.mode, 'bulk');
});

test('flujo completo: sin modo elegido bloquea la confirmación en el paso de selección', () => {
  const values = { name: 'Club Norte', shortCode: 'CN' };
  const issues = validateTeamValues(values);
  const confirmation = teamConfirmation(values, issues, t);
  assert.equal(confirmation.ok, false);
  assert.ok(confirmation.blockedBy.includes('teams.entry'));
});

test('flujo completo: CSV inválido bloquea la confirmación en la vía bulk', () => {
  const values = { entryPath: 'bulk', bulkCsv: 'name,short_code\nA,CN' };
  const issues = validateTeamValues(values);
  assert.ok(issues.length > 0);
  const confirmation = teamConfirmation(values, issues, t);
  assert.equal(confirmation.ok, false);
  assert.ok(confirmation.blockedBy.includes('teams.bulk'));
});

test('flujo completo: datos inválidos en vía individual bloquean en teams.details', () => {
  const values = { entryPath: 'individual', name: 'A', shortCode: 'CN' };
  const issues = validateTeamValues(values);
  assert.ok(issues.length > 0);
  const confirmation = teamConfirmation(values, issues, t);
  assert.equal(confirmation.ok, false);
  assert.ok(confirmation.blockedBy.includes('teams.details'));
});

test('flujo completo: cambio de modo conserva valores y revalida', () => {
  const individual = { entryPath: 'individual', name: ' Club Norte ', shortCode: 'CN', bulkCsv: csvWithHeader };
  assert.deepEqual(validateTeamValues(individual), []);

  // Cambio a bulk: los valores individuales se conservan en el borrador.
  const switched = { ...individual, entryPath: 'bulk' };
  assert.equal(teamWizardValues(switched).bulkCsv, csvWithHeader);
  // Validación de la vía bulk no requiere nombre/código.
  assert.deepEqual(validateTeamValues(switched), []);
  const confirmation = teamConfirmation(switched, validateTeamValues(switched), t);
  assert.deepEqual(confirmation, { ok: true, blockedBy: [] });
});
