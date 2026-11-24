import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { computed, ref } from 'vue';
import * as formations from '../app/constants/formations.ts';
import * as navigation from '../app/utils/matchNavigation.ts';
import * as segments from '../app/utils/matchSegments.ts';
import * as source from '../app/utils/lineupSource.ts';
import * as publication from '../app/utils/lineupPublication.ts';
import type { MatchOperation, LineupRole } from '../app/components/match/types.ts';
import type { MatchOperationState } from '../app/composables/useMatchOperationState.ts';
import type { useMatchLineup } from '../app/composables/useMatchLineup.ts';

function operationFixture(): MatchOperation {
  const rosters = Array.from({ length: 24 }, (_, i) => ({
    roster_id: `r${i}`, player_id: `p${i}`, team_id: i < 12 ? 'home' : 'away',
  }));
  return {
    match: { home_team_id: 'home', away_team_id: 'away', status: 'scheduled', version_status: 'published' },
    segments: [{ id: 's1', segment_number: 1, status: 'active', minute_start: 0 }],
    rosters,
    lineup: rosters.map((r, i) => ({ ...r, role: i % 12 === 11 ? 'substitute' : 'starter', position_slot: null })),
    tactical_lineups: [], next_segment: null,
  } as unknown as MatchOperation;
}

function editor(gameFormat = '11v11', confirmAnswer = true) {
  const operation = ref<MatchOperation | null>(null);
  const requests: { path: string; options: unknown }[] = [];
  const confirmations: Record<string, unknown>[] = [];
  const selectedSegmentId = ref('');
  const lineupRoles = ref<Record<string, LineupRole | ''>>({});
  const lineupPositions = ref<Record<string, string>>({});
  const state = {
    operation, selectedSegmentId,
    request: async (path: string, options: unknown) => { requests.push({ path, options }); },
    confirm: async (options: Record<string, unknown>) => { confirmations.push(options); return confirmAnswer; },
    t: (key: string, values?: Record<string, unknown>) => values ? `${key}:${JSON.stringify(values)}` : key,
    matchId: 'm1',
    actionError: ref<string | null>(null),
    matchGameFormat: computed(() => gameFormat),
    selectedSegmentIsActive: computed(() => true),
    teamRosters: computed(() => [{ team_id: 'home', name: 'Local FC' }, { team_id: 'away', name: 'Visitante FC' }]),
    lineupEntries: computed(() => Object.entries(lineupRoles.value).filter(([, role]) => role).map(([roster_id, role]) => ({
      roster_id, role, position_slot: role === 'starter' ? lineupPositions.value[roster_id] || null : null,
    }))),
    match: computed(() => operation.value?.match),
    openingBlocked: ref(null),
    lineupRoles,
    lineupPositions,
    lineupFormations: ref<Record<string, string>>({}),
    segmentForm: { segment_number: 1, minute_start: 0, minuteDirty: false },
    interruptionForm: { minute: 0, minuteDirty: false },
    eventForm: { team_id: '' },
    selectedTacticalLineups: computed(() => operation.value?.tactical_lineups.filter(r => r.segment_id === selectedSegmentId.value) || []),
  };
  const exports: { useMatchLineup?: typeof useMatchLineup } = {};
  const code = readFileSync(new URL('../app/composables/useMatchLineup.ts', import.meta.url), 'utf8').replaceAll('import.meta.client', 'false');
  const modules: Record<string, unknown> = {
    '~/constants/formations': formations, '~/utils/matchNavigation': navigation,
    '~/utils/matchSegments': segments, '~/utils/lineupSource': source,
    '~/utils/lineupPublication': publication,
  };
  runInNewContext(ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, require: (name: string) => { assert.ok(name in modules, name); return modules[name]; },
  });
  const actions = exports.useMatchLineup!(state as unknown as MatchOperationState, {
    refreshOperation: async () => {}, runAction: async (_name, callback) => { await callback(); },
  });
  return { state, requests, confirmations, ...actions };
}

test('classic lineup: hydrate all 24 roles without a formation or position, including on refresh', () => {
  const { state, applyOperation, syncTacticalEditor } = editor();
  const value = operationFixture();
  const expected = Object.fromEntries(value.lineup.map(r => [r.roster_id, r.role]));
  applyOperation(value, 'mount');
  assert.deepEqual({ ...state.lineupRoles.value }, expected);
  assert.deepEqual({ ...state.lineupPositions.value }, {});
  assert.deepEqual({ ...state.lineupFormations.value }, {});
  syncTacticalEditor();
  applyOperation(structuredClone(value));
  assert.deepEqual({ ...state.lineupRoles.value }, expected);
});

test('classic lineup: an empty or reduced server lineup clears stale local roles', () => {
  const { state, applyOperation } = editor();
  const value = operationFixture();
  applyOperation(value);
  value.lineup = value.lineup.slice(1);
  applyOperation(value);
  assert.equal(state.lineupRoles.value.r0, '');
  assert.equal(state.lineupRoles.value.r1, 'starter');
  value.lineup = [];
  applyOperation(value);
  assert.equal(Object.keys(state.lineupRoles.value).length, 24);
  assert.ok(Object.values(state.lineupRoles.value).every(role => role === ''));
});

for (const selected of ['s1', 's2']) {
  test(`tactical snapshot has priority over classic roles, without leaking omitted players (${selected})`, () => {
    const { state, applyOperation, syncTacticalEditor } = editor();
    const value = operationFixture();
    value.tactical_lineups = [{
      segment_id: 's1', segment_number: 1, team_id: 'home', formation_code: '4-3-3',
      player_id: 'p0', is_starter: false, position_slot: null, is_public: false,
      published_at: null, first_name: null, last_name: null,
    }, {
      segment_id: 's1', segment_number: 1, team_id: 'home', formation_code: '4-3-3',
      player_id: 'p1', is_starter: true, position_slot: 'GK', is_public: false,
      published_at: null, first_name: null, last_name: null,
    }];
    applyOperation(value);
    state.selectedSegmentId.value = selected;
    syncTacticalEditor();
    assert.equal(state.lineupRoles.value.r0, 'substitute');
    assert.equal(state.lineupRoles.value.r1, 'starter');
    assert.equal(state.lineupPositions.value.r1, 'GK');
    assert.equal(state.lineupRoles.value.r2, '');
    assert.equal(state.lineupRoles.value.r12, 'starter');
    assert.equal(state.lineupFormations.value.home, '4-3-3');
  });
}

test('spec 044: la precarga entre segmentos (028) copia una formación de 5v5', () => {
  const { state, applyOperation, syncTacticalEditor } = editor('5v5');
  const value = operationFixture();
  value.segments = [
    { id: 's1', segment_number: 1, status: 'closed', minute_start: 0 },
    { id: 's2', segment_number: 2, status: 'active', minute_start: 20 },
  ] as MatchOperation['segments'];
  value.tactical_lineups = ['GK', 'LCB', 'RCB', 'ST_L', 'ST_R'].map((slot, index) => ({
    segment_id: 's1', segment_number: 1, team_id: 'home', formation_code: '2-2',
    player_id: `p${index}`, is_starter: true, position_slot: slot, is_public: false,
    published_at: null, first_name: null, last_name: null,
  })) as MatchOperation['tactical_lineups'];
  applyOperation(value);
  state.selectedSegmentId.value = 's2';
  syncTacticalEditor();
  assert.equal(state.lineupFormations.value.home, '2-2');
  assert.equal(state.lineupPositions.value.r0, 'GK');
  assert.equal(state.lineupPositions.value.r4, 'ST_R');
  assert.equal(state.lineupRoles.value.r4, 'starter');
});

test('spec 044: guardar con una formación de otra modalidad avisa y no llama a la API', async () => {
  const { state, requests, saveLineup } = editor('5v5');
  state.selectedSegmentId.value = 's1';
  state.lineupFormations.value = { home: '4-3-3' };
  await saveLineup();
  assert.equal(requests.length, 0);
  assert.equal(state.actionError.value, 'match.formationOtherFormat');
});

test('spec 044: guardar con la formación de la modalidad envía team_lineups', async () => {
  const { state, requests, saveLineup } = editor('5v5');
  state.selectedSegmentId.value = 's1';
  state.lineupFormations.value = { home: '2-2' };
  await saveLineup();
  assert.equal(requests.length, 1);
  const body = (requests[0]!.options as { body: { team_lineups: unknown } }).body;
  assert.equal(JSON.stringify(body.team_lineups), JSON.stringify([{ team_id: 'home', formation_code: '2-2' }]));
  assert.equal(state.actionError.value, null);
});

test('spec 044: el selector de la operación usa la modalidad del partido y deshabilita la formación ajena', () => {
  const source = readFileSync(new URL('../app/components/match/MatchLineupSection.vue', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /FORMATION_OPTIONS/);
  assert.match(source, /formationSelectOptions\(matchGameFormat/);
  assert.match(source, /<option v-if="[^"]*foreign[^"]*"[^>]*disabled/);
  assert.match(source, /match\.formationOtherFormatNotice/);
});

function publishedFiveASide(): MatchOperation {
  const value = operationFixture();
  value.tactical_lineups = (['home', 'away'] as const).flatMap((team) => {
    const offset = team === 'home' ? 0 : 12;
    return ['GK', 'LCB', 'RCB', 'ST_L', 'ST_R'].map((slot, index) => ({
      segment_id: 's1', segment_number: 1, team_id: team, formation_code: '2-2',
      player_id: `p${offset + index}`, is_starter: true, position_slot: slot, is_public: true,
      published_at: '2026-11-24T10:00:00Z', first_name: null, last_name: null,
    }));
  }) as MatchOperation['tactical_lineups'];
  return value;
}

function hydratedPublished(confirmAnswer = true) {
  const harness = editor('5v5', confirmAnswer);
  harness.state.selectedSegmentId.value = 's1';
  harness.applyOperation(publishedFiveASide(), 'mount');
  for (const rosterId of Object.keys(harness.state.lineupRoles.value)) {
    if (!(rosterId in harness.state.lineupPositions.value)) harness.state.lineupRoles.value[rosterId] = '';
  }
  return harness;
}

test('spec 045: guardar sin cambios en las formaciones publicadas no pide confirmación', async () => {
  const { requests, confirmations, saveLineup } = hydratedPublished();
  await saveLineup();
  assert.equal(confirmations.length, 0);
  assert.equal(requests.length, 1);
});

test('spec 045: retirar la formación publicada de un equipo pide confirmación con su nombre', async () => {
  const { state, requests, confirmations, saveLineup } = hydratedPublished();
  state.lineupPositions.value.r1 = 'RCB';
  state.lineupPositions.value.r2 = 'LCB';
  await saveLineup();
  assert.equal(confirmations.length, 1);
  const options = confirmations[0]!;
  assert.equal(options.title, 'confirm.lineupWithdraw.title');
  assert.equal(options.confirmLabel, 'confirm.lineupWithdraw.action');
  assert.equal(options.tone, 'danger');
  assert.match(String(options.message), /Local FC/);
  assert.doesNotMatch(String(options.message), /Visitante FC/);
  assert.equal(requests.length, 1);
});

test('spec 045: cancelar la confirmación no envía nada y conserva el editor', async () => {
  const { state, requests, confirmations, saveLineup } = hydratedPublished(false);
  state.lineupFormations.value = { home: '', away: '' };
  const before = JSON.stringify({ formations: state.lineupFormations.value, roles: state.lineupRoles.value, positions: state.lineupPositions.value });
  await saveLineup();
  assert.equal(confirmations.length, 1);
  assert.match(String(confirmations[0]!.message), /Local FC, Visitante FC/);
  assert.equal(requests.length, 0);
  assert.equal(JSON.stringify({ formations: state.lineupFormations.value, roles: state.lineupRoles.value, positions: state.lineupPositions.value }), before);
});
