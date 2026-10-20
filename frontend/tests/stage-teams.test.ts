import assert from 'node:assert/strict';
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
