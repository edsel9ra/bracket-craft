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

function editor() {
  const operation = ref<MatchOperation | null>(null);
  const selectedSegmentId = ref('');
  const state = {
    operation, selectedSegmentId,
    match: computed(() => operation.value?.match),
    openingBlocked: ref(null),
    lineupRoles: ref<Record<string, LineupRole | ''>>({}),
    lineupPositions: ref<Record<string, string>>({}),
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
  };
  runInNewContext(ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, require: (name: string) => { assert.ok(name in modules, name); return modules[name]; },
  });
  const actions = exports.useMatchLineup!(state as unknown as MatchOperationState, {
    refreshOperation: async () => {}, runAction: async (_name, callback) => { await callback(); },
  });
  return { state, ...actions };
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
