import assert from 'node:assert/strict';
import test from 'node:test';

import {
  groupsOfStage,
  matchesForGroup,
  normalizePublicSelection,
  resolveMatchOutcomeLabel,
  sortPublicStages,
  standingsForGroup,
  type PublicMatch,
  type PublicStanding,
  type PublicStage,
} from '../app/utils/publicTournament.ts';

function stage(id: string, stage_order: number, stage_type: PublicStage['stage_type'] = 'round_robin'): PublicStage {
  return { id, name: id, stage_order, stage_type };
}

function standing(stage_id: string, group_id: string | null, group_name: string | null, team_id = 't'): PublicStanding {
  return {
    stage_id,
    stage_name: stage_id,
    stage_order: 1,
    group_id,
    group_name,
    team_id,
    team_name: team_id,
    short_code: team_id,
    played: 0,
    won: 0,
    drawn: 0,
    lost: 0,
    goals_for: 0,
    goals_against: 0,
    goal_difference: 0,
    points: 0,
    fair_play_points: 0,
    rank: 1,
    crest_url: null,
  };
}

function match(overrides: Partial<PublicMatch> = {}): PublicMatch {
  return {
    id: 'm1',
    stage_id: 's1',
    stage_name: 's1',
    stage_order: 1,
    group_id: null,
    group_name: null,
    bracket_code: null,
    matchday: 1,
    match_date: null,
    home_team_id: 'h',
    home_team_name: 'Home',
    home_team_short_code: 'H',
    away_team_id: 'a',
    home_team_crest_url: null,
    away_team_name: 'Away',
    away_team_short_code: 'A',
    away_team_crest_url: null,
    home_score: null,
    away_score: null,
    home_penalties: null,
    away_penalties: null,
    status: 'finished',
    resolution_type: null,
    winner_team_id: null,
    lineup: null,
    ...overrides,
  };
}

test('normalizes an unknown stage to the first published stage', () => {
  const stages = [stage('s2', 2), stage('s1', 1)];
  const result = normalizePublicSelection(stages, 'missing', 'g1');
  assert.deepEqual(result, { stageId: 's1', groupId: null });
});

test('normalizes an unknown group to null', () => {
  const stages = [stage('s1', 1)];
  const standings = [standing('s1', 'g1', 'Group 1')];
  const result = normalizePublicSelection(stages, standings, 's1', 'missing-group');
  assert.deepEqual(result, { stageId: 's1', groupId: null });
});

test('keeps a known group', () => {
  const stages = [stage('s1', 1)];
  const standings = [standing('s1', 'g1', 'Group 1')];
  const result = normalizePublicSelection(stages, standings, 's1', 'g1');
  assert.deepEqual(result, { stageId: 's1', groupId: 'g1' });
});

test('returns both null when there are no stages', () => {
  const result = normalizePublicSelection([], 's1', 'g1');
  assert.deepEqual(result, { stageId: null, groupId: null });
});

test('groups of a stage are stable and de-duplicated', () => {
  const standings = [
    standing('s1', 'g2', 'Group 2'),
    standing('s1', 'g1', 'Group 1'),
    standing('s1', 'g2', 'Group 2'),
    standing('s2', 'g3', 'Group 3'),
  ];
  const groups = groupsOfStage(standings, 's1');
  assert.deepEqual(groups, [
    { groupId: 'g2', groupName: 'Group 2' },
    { groupId: 'g1', groupName: 'Group 1' },
  ]);
});

test('standingsForGroup filters by group and returns all when null', () => {
  const standings = [
    standing('s1', 'g1', 'Group 1', 'a'),
    standing('s1', 'g2', 'Group 2', 'b'),
  ];
  assert.deepEqual(standingsForGroup(standings, 's1', 'g1').map((s) => s.team_id), ['a']);
  assert.deepEqual(standingsForGroup(standings, 's1', null).map((s) => s.team_id), ['a', 'b']);
});

test('matchesForGroup filters by group and returns all when null', () => {
  const matches = [
    match({ id: 'm1', group_id: 'g1' }),
    match({ id: 'm2', group_id: 'g2' }),
  ];
  assert.deepEqual(matchesForGroup(matches, 's1', 'g1').map((m) => m.id), ['m1']);
  assert.deepEqual(matchesForGroup(matches, 's1', null).map((m) => m.id), ['m1', 'm2']);
});

test('resolveMatchOutcomeLabel detects walkover', () => {
  assert.equal(resolveMatchOutcomeLabel(match({ resolution_type: 'walkover' })), 'walkover');
});

test('resolveMatchOutcomeLabel detects penalties', () => {
  assert.equal(resolveMatchOutcomeLabel(match({ home_penalties: 3, away_penalties: 1 })), 'penalties');
});

test('resolveMatchOutcomeLabel detects extra time', () => {
  assert.equal(resolveMatchOutcomeLabel(match({
    home_score_regular: 1,
    away_score_regular: 1,
    home_score: 2,
    away_score: 1,
  })), 'extra_time');
});

test('resolveMatchOutcomeLabel detects administrative resolution', () => {
  assert.equal(resolveMatchOutcomeLabel(match({ status: 'administrative_resolution' })), 'administrative');
});

test('resolveMatchOutcomeLabel returns null for a regular result', () => {
  assert.equal(resolveMatchOutcomeLabel(match({ home_score: 2, away_score: 1 })), null);
});

test('sortPublicStages is stable by stage order and id', () => {
  const ordered = sortPublicStages([stage('b', 2), stage('a', 1)]);
  assert.deepEqual(ordered.map((s) => s.id), ['a', 'b']);
});
