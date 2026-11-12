import assert from 'node:assert/strict';
import test from 'node:test';
import { groupPublicRounds, inferPublicAdvances, publicRoundLabel } from '../app/utils/publicBracket.ts';
import type { PublicMatch } from '../app/utils/publicTournament.ts';

function match(id: string, overrides: Partial<PublicMatch> = {}): PublicMatch {
  return {
    rectified_at: null,
    id, stage_id: 'stage', stage_name: 'Stage', stage_order: 1,
    group_id: null, group_name: null, bracket_code: null, matchday: 1, match_date: null,
    home_team_id: 'a', home_team_name: 'Same name', home_team_short_code: null, home_team_crest_url: null,
    away_team_id: 'b', away_team_name: 'Same name', away_team_short_code: null, away_team_crest_url: null,
    home_score: null, away_score: null, home_penalties: null, away_penalties: null,
    status: 'scheduled', resolution_type: null, winner_team_id: null, lineup: null, ...overrides,
  };
}

const source = match('source', { winner_team_id: 'a' });
const target = match('target', { matchday: 2, away_team_id: 'c' });

test('explicit winner yields one unique adjacent advance, also for penalties and walkover', () => {
  for (const resolution_type of ['regular', 'penalties', 'walkover']) {
    const a = { ...source, status: 'finished', resolution_type };
    const input = Object.freeze([Object.freeze(a), Object.freeze(target)]);
    assert.deepEqual(inferPublicAdvances(input), [{ sourceId: 'source', targetId: 'target', teamId: 'a', side: 'home' }]);
    assert.equal(input[0], a);
  }
  assert.equal(inferPublicAdvances([source, { ...target, home_team_id: 'c', away_team_id: 'a' }])[0]?.side, 'away');
});

test('never deduces winners from scores, status, code, names or placeholders', () => {
  for (const a of [
    match('source'), match('source', { status: 'finished', home_score: 5, away_score: 0 }),
    { ...source, winner_team_id: 'stranger' }, { ...source, away_team_id: 'a' },
  ]) assert.deepEqual(inferPublicAdvances([a, target]), []);
  assert.deepEqual(inferPublicAdvances([source, { ...target, home_team_id: null }]), []);
  assert.deepEqual(inferPublicAdvances([source, { ...target, home_team_id: 'other' }]), []);
});

test('ambiguous repeated winners, destinations and sides do not draw a line', () => {
  for (const rows of [
    [source, { ...source, id: 'other-source' }, target],
    [source, target, { ...target, id: 'other-target' }],
    [source, { ...target, away_team_id: 'a' }],
    [source, { ...source, id: 'corrupt', home_team_id: 'stranger' }, target],
  ]) assert.deepEqual(inferPublicAdvances(rows), []);
});

test('only same scope and numeric r/r+1; no invented bye or skipped round', () => {
  for (const b of [
    { ...target, stage_id: 'other' }, { ...target, group_id: 'other' },
    { ...target, matchday: 3 }, { ...target, matchday: null },
    { ...target, matchday: 1 }, { ...target, matchday: 1.5 },
  ]) assert.deepEqual(inferPublicAdvances([source, b]), []);
  assert.deepEqual(inferPublicAdvances([]), []);
  assert.deepEqual(inferPublicAdvances([target]), []);
});

test('duplicate identical records deduplicate, conflicting IDs never infer a relation', () => {
  assert.equal(inferPublicAdvances([source, { ...source }, target]).length, 1);
  assert.deepEqual(inferPublicAdvances([source, { ...source, winner_team_id: 'b' }, target]), []);
  assert.deepEqual(inferPublicAdvances([source, target, { ...target, home_team_id: 'other' }]), []);
});

test('rounds retain API order and scope, unknown rounds and conflicting cards remain visible', () => {
  const rows = [target, source, match('first', { bracket_code: 'QF9' }), match('unknown', { matchday: null }), match('elsewhere', { stage_id: 'other' })];
  const snapshot = JSON.stringify(rows);
  const rounds = groupPublicRounds(rows);
  assert.deepEqual(rounds[0]?.matches.map(m => m.id), ['source', 'first']);
  assert.deepEqual(rounds.flatMap(r => r.matches).map(m => m.id).sort(), rows.map(m => m.id).sort());
  assert.equal(new Set(rounds.map(r => r.key)).size, rounds.length);
  assert.equal(JSON.stringify(rows), snapshot);
  assert.equal(groupPublicRounds([source, { ...source }]).flatMap(r => r.matches).length, 1);
});

test('round names use only exact existing code families, never the last visible column', () => {
  for (const [codes, key] of [
    [['FINAL'], 'public.final'], [['SF1', 'SF2'], 'public.semifinals'],
    [['QF1', 'QF4'], 'public.quarterfinals'], [['R16-1', 'R16-8'], 'public.roundOf16'],
  ] as const) {
    const round = groupPublicRounds(codes.map((bracket_code, i) => match(String(i), { bracket_code })))[0]!;
    assert.deepEqual(publicRoundLabel(round), { key });
  }
  for (const codes of [[null], ['SF1', 'QF1'], ['FINAL', null], ['R32-1'], ['SF0'], ['SF3'], ['QF5'], ['R16-9'], ['final'], ['FINAL-extra']]) {
    const round = groupPublicRounds(codes.map((bracket_code, i) => match(String(i), { bracket_code, matchday: 3 })))[0]!;
    assert.deepEqual(publicRoundLabel(round), { key: 'public.round', value: 3 });
  }
  assert.deepEqual(publicRoundLabel(groupPublicRounds([match('unknown', { matchday: null })])[0]!), { key: 'public.bracket' });
});
