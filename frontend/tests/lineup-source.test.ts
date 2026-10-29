import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  deriveLineupSource,
  type TacticalLineupRow,
  type RosterEntry,
  type LineupSource,
} from '../app/utils/lineupSource.ts';

const UTILS_SOURCE = readFileSync(
  new URL('../app/utils/lineupSource.ts', import.meta.url),
  'utf8',
);

function row(overrides: Partial<TacticalLineupRow> = {}): TacticalLineupRow {
  return {
    segment_id: overrides.segment_id ?? 'seg1',
    segment_number: overrides.segment_number ?? 1,
    team_id: overrides.team_id ?? 'teamA',
    formation_code: overrides.formation_code ?? '4-3-3',
    is_public: overrides.is_public,
    published_at: overrides.published_at ?? null,
    player_id: overrides.player_id ?? null,
    is_starter: overrides.is_starter ?? true,
    position_slot: overrides.position_slot ?? null,
    first_name: overrides.first_name ?? null,
    last_name: overrides.last_name ?? null,
  };
}

function roster(overrides: Partial<RosterEntry> = {}): RosterEntry {
  return {
    roster_id: overrides.roster_id ?? 'r1',
    player_id: overrides.player_id ?? 'p1',
    team_id: overrides.team_id ?? 'teamA',
  };
}

test('CL-001: precarga desde el primer segmento con formacion, por equipo', () => {
  const rosters = [
    roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' }),
    roster({ roster_id: 'ra2', player_id: 'pa2', team_id: 'teamA' }),
  ];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa2', is_starter: false, position_slot: null }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.ok(src);
  assert.equal(src.source_segment_id, 'seg1');
  assert.equal(src.formation_code, '4-3-3');
  assert.equal(src.roles['ra1'], 'starter');
  assert.equal(src.positions['ra1'], 'GK');
  assert.equal(src.roles['ra2'], 'substitute');
  assert.equal(src.positions['ra2'], null);
  assert.equal((src as any).is_public, undefined);
  assert.equal((src as any).published_at, undefined);
});

test('CL-007: independencia por equipo', () => {
  const rosters = [
    roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' }),
    roster({ roster_id: 'rb1', player_id: 'pb1', team_id: 'teamB' }),
  ];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-4-2', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
    row({ segment_id: 'seg2', segment_number: 2, team_id: 'teamB', formation_code: '3-5-2', player_id: 'pb1', is_starter: true, position_slot: 'ST' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg3');
  assert.equal(result['teamA']?.source_segment_id, 'seg1');
  assert.equal(result['teamA']?.formation_code, '4-4-2');
  assert.equal(result['teamB']?.source_segment_id, 'seg2');
  assert.equal(result['teamB']?.formation_code, '3-5-2');
});

test('CL-007: segmento con formacion solo para un equipo', () => {
  const rosters = [
    roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' }),
    roster({ roster_id: 'rb1', player_id: 'pb1', team_id: 'teamB' }),
  ];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg2');
  assert.ok(result['teamA']);
  assert.equal(result['teamB'], null);
});

test('RF-002: segmento seleccionado con formacion persistida no precarga', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg1');
  assert.equal(result['teamA'], null);
});

test('RF-006: sin fuente de precarga', () => {
  const rosters = [
    roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' }),
    roster({ roster_id: 'rb1', player_id: 'pb1', team_id: 'teamB' }),
  ];
  const result = deriveLineupSource([], rosters, 'seg1');
  assert.equal(result['teamA'], null);
  assert.equal(result['teamB'], null);
});

test('CL-002: varios segmentos sin formacion', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const result = deriveLineupSource([], rosters, 'seg1');
  assert.equal(result['teamA'], null);
});

test('CL-008: fuente sin snapshots', () => {
  const rosters = [
    roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' }),
    roster({ roster_id: 'ra2', player_id: 'pa2', team_id: 'teamA' }),
  ];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: null, position_slot: null }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.ok(src);
  assert.equal(src.formation_code, '4-3-3');
  assert.equal(src.roles['ra1'], '');
  assert.equal(src.roles['ra2'], '');
  assert.equal(src.positions['ra1'], null);
  assert.equal(src.positions['ra2'], null);
});

test('CL-011: jugador retirado se precarga igual', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.equal(src.roles['ra1'], 'starter');
  assert.equal(src.positions['ra1'], 'GK');
});

test('CL-009: precarga desde el segmento de menor numero con formacion', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [
    row({ segment_id: 'seg3', segment_number: 3, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-4-2', player_id: 'pa1', is_starter: true, position_slot: 'ST' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg5');
  const src = result['teamA'] as LineupSource;
  assert.equal(src.source_segment_id, 'seg1');
  assert.equal(src.formation_code, '4-4-2');
  assert.equal(src.positions['ra1'], 'ST');
});

test('roster del equipo no presente en la fuente se inicializa vacio', () => {
  const rosters = [
    roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' }),
    roster({ roster_id: 'ra2', player_id: 'pa2', team_id: 'teamA' }),
  ];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.equal(src.roles['ra1'], 'starter');
  assert.equal(src.positions['ra1'], 'GK');
  assert.equal(src.roles['ra2'], '');
  assert.equal(src.positions['ra2'], null);
});

test('snapshot cuyo jugador no esta en el roster se omite', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'ghost', is_starter: true, position_slot: 'GK' }),
  ];

  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.equal(src.roles['ra1'], '');
  assert.equal(src.positions['ra1'], null);
});

test('CL-005: partido con un unico segmento no precarga', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const withForm = [row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' })];
  assert.equal(deriveLineupSource(withForm, rosters, 'seg1')['teamA'], null);

  const without = deriveLineupSource([], rosters, 'seg1');
  assert.equal(without['teamA'], null);
});

test('no muta sus entradas', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' })];
  const rostersCopy = structuredClone(rosters);
  const lineupsCopy = structuredClone(lineups);
  deriveLineupSource(lineups, rosters, 'seg2');
  assert.deepEqual(rosters, rostersCopy);
  assert.deepEqual(lineups, lineupsCopy);
});

test('es determinista', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' })];
  const a = deriveLineupSource(lineups, rosters, 'seg2');
  const b = deriveLineupSource(lineups, rosters, 'seg2');
  assert.deepEqual(a, b);
});

test('no lee reloj, red ni almacenamiento', () => {
  for (const pattern of [
    /Date\.now/,
    /new Date\(/,
    /Math\.random/,
    /\$fetch/,
    /useApi/,
    /localStorage/,
    /sessionStorage/,
  ]) {
    assert.doesNotMatch(UTILS_SOURCE, pattern);
  }
  assert.match(UTILS_SOURCE, /export function deriveLineupSource\(/);
});

test('CL-001: is_public/published_at no se copian en la fuente', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', is_public: true, published_at: '2026-01-01', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
  ];
  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.ok(src);
  assert.equal(Object.prototype.hasOwnProperty.call(src, 'is_public'), false);
  assert.equal(Object.prototype.hasOwnProperty.call(src, 'published_at'), false);
});

test('RF-014: la fuente no expone segment_id del origen como identificador del destino', () => {
  const rosters = [roster({ roster_id: 'ra1', player_id: 'pa1', team_id: 'teamA' })];
  const lineups = [
    row({ segment_id: 'seg1', segment_number: 1, team_id: 'teamA', formation_code: '4-3-3', player_id: 'pa1', is_starter: true, position_slot: 'GK' }),
  ];
  const result = deriveLineupSource(lineups, rosters, 'seg2');
  const src = result['teamA'] as LineupSource;
  assert.equal(src.source_segment_id, 'seg1');
  assert.equal(Object.prototype.hasOwnProperty.call(src, 'segment_id'), false);
});
