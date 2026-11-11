import assert from 'node:assert/strict';
import test from 'node:test';
import { groupPublicRounds, inferPublicAdvances } from '../app/utils/publicBracket.ts';
import { layoutPublicBracket } from '../app/utils/publicBracketLayout.ts';
import type { PublicMatch } from '../app/utils/publicTournament.ts';

const make = (id: string, matchday: number, winner_team_id: string | null = null) => ({
  id, matchday, stage_id: 'stage', group_id: null, home_team_id: id, away_team_id: 'away-'+id, winner_team_id,
}) as PublicMatch;
const a = make('a', 1, 'a');
const b = make('b', 1, 'b');
const c = { ...make('c', 2), home_team_id: 'a', away_team_id: 'b' };
const rows = [a, b, c];
const rounds = groupPublicRounds(rows);
const edges = inferPublicAdvances(rows);
const measurements = {
  a: { height: 100, width: 230, left: 0, roundTop: 60 },
  b: { height: 140, width: 230, left: 0, roundTop: 60 },
  c: { height: 120, width: 230, left: 262, roundTop: 60 },
};

test('variable heights center a destination on its known origins, with local and SVG coordinates', () => {
  const before = JSON.stringify({ rounds, edges, measurements });
  const result = layoutPublicBracket(rounds, edges, measurements, 32)!;
  assert.equal(result.positions.a?.centerY, 110);
  assert.equal(result.positions.b?.centerY, 262);
  assert.equal(result.positions.c?.centerY, 186);
  assert.equal(result.positions.c?.top, 66);
  assert.equal(result.paths.length, 2);
  assert.deepEqual(result.paths[0], { sourceId: 'a', targetId: 'c', d: 'M 230 110 H 246 V 186 H 262' });
  assert.equal(result.width, 492);
  assert.equal(before, JSON.stringify({ rounds, edges, measurements }));
});

test('one origin is sufficient, no origins retain API order without overlap', () => {
  const single = layoutPublicBracket(rounds, edges.slice(1), measurements, 32)!;
  assert.equal(single.positions.c?.centerY, single.positions.b?.centerY);
  const plain = layoutPublicBracket(rounds, [], measurements, 32)!;
  assert.equal(plain.positions.b!.top - (plain.positions.a!.top + 100), 32);
  assert.equal(plain.positions.c?.top, 0);
});

test('collisions pack minimally, preserve API order and report deviation', () => {
  const before = { ...make('before', 2), home_team_id: 'other' };
  const rs = groupPublicRounds([a, before, c]);
  const ms = { ...measurements, before: { ...measurements.c, height: 200 } };
  const result = layoutPublicBracket(rs, edges.slice(0, 1), ms, 32)!;
  assert.equal(result.positions.before?.top, 0);
  assert.equal(result.positions.c?.top, 232);
  assert.equal(result.positions.c?.collision, true);
  assert.equal(result.positions.c?.nominalY, result.positions.a?.centerY);
  assert.equal(result.roundHeights[rs[1]!.key], 352);
});

test('no partial geometry, non-finite values, zero heights or negative gap', () => {
  const missing = { a: measurements.a, b: measurements.b };
  assert.equal(layoutPublicBracket(rounds, edges, missing, 32), null);
  for (const invalid of [0, -1, NaN, Infinity]) {
    assert.equal(layoutPublicBracket(rounds, edges, { ...measurements, c: { ...measurements.c, height: invalid } }, 32), null);
  }
  assert.equal(layoutPublicBracket(rounds, edges, measurements, -1), null);
  assert.equal(layoutPublicBracket(rounds, edges, { ...measurements, c: { ...measurements.c, left: NaN } }, 32), null);
  assert.equal(layoutPublicBracket([], [], {}, 32)?.paths.length, 0);
});
