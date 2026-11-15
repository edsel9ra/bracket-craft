import assert from 'node:assert/strict';
import test from 'node:test';

import {
  bracketEligibleMatches,
  formatSuspendedClock,
  isSuspendedPublicMatch,
  matchEntriesForGroup,
  matchEntriesForStage,
  mergeMatchEntries,
  normalizePublicMatchPage,
  normalizePublicMatchState,
  type PublicMatch,
  type SuspendedPublicMatch,
} from '../app/utils/publicTournament.ts';

const SUSPENDED: SuspendedPublicMatch = {
  id: 'm-susp',
  tournament_id: 't-1',
  home_team_id: 'h-1',
  home_team_name: 'Local',
  away_team_id: 'a-1',
  away_team_name: 'Visitante',
  status: 'suspended',
  home_score: 2,
  away_score: 1,
  is_provisional: true,
  clock_segment_number: 2,
  clock_elapsed_seconds: 2733,
  clock_state: 'paused',
  clock_observed_at: '2026-11-15T10:00:00Z',
};

function classic(overrides: Partial<PublicMatch> = {}): PublicMatch {
  return {
    rectified_at: null,
    id: 'm-1',
    stage_id: 'st-1',
    stage_name: 'Grupos',
    stage_order: 1,
    group_id: 'g-1',
    group_name: 'A',
    bracket_code: null,
    matchday: 1,
    match_date: '2026-11-10',
    home_team_id: 'h-1',
    home_team_name: 'Local',
    home_team_short_code: 'LOC',
    away_team_id: 'a-1',
    home_team_crest_url: null,
    away_team_name: 'Visitante',
    away_team_short_code: 'VIS',
    away_team_crest_url: null,
    home_score: 0,
    away_score: 0,
    home_penalties: null,
    away_penalties: null,
    status: 'scheduled',
    resolution_type: null,
    winner_team_id: null,
    lineup: null,
    ...overrides,
  };
}

test('el suspendido se valida con sus catorce claves, sin exigir stage/lineup/bracket', () => {
  const parsed = normalizePublicMatchState(SUSPENDED);
  assert.equal(parsed !== null && isSuspendedPublicMatch(parsed), true);
  assert.deepEqual(Object.keys(SUSPENDED).sort(), [
    'away_score', 'away_team_id', 'away_team_name', 'clock_elapsed_seconds',
    'clock_observed_at', 'clock_segment_number', 'clock_state', 'home_score',
    'home_team_id', 'home_team_name', 'id', 'is_provisional', 'status',
    'tournament_id',
  ].sort());
});

test('un suspendido malformado se descarta, nunca se rellena con nulos', () => {
  for (const raw of [
    null,
    'suspended',
    [],
    { ...SUSPENDED, home_score: '2' },
    { ...SUSPENDED, is_provisional: false },
    { ...SUSPENDED, clock_state: 'running' },
    { ...SUSPENDED, clock_observed_at: 123 },
    { status: 'suspended' },
  ]) {
    assert.equal(normalizePublicMatchState(raw), null);
  }
});

test('primera carga sin caché: página mixta válida, SSR-pura (sin estado global)', () => {
  const page = normalizePublicMatchPage([
    classic(),
    SUSPENDED,
    classic({ id: 'm-2', status: 'finished' }),
    { garbage: true },
  ]);
  assert.equal(page.length, 3);
  assert.equal(isSuspendedPublicMatch(page[1]), true);
});

test('consulta general renderiza el suspendido con el contexto de la consulta', () => {
  let entries = mergeMatchEntries([], [classic(), SUSPENDED], 'st-1', 'g-1');
  assert.deepEqual(matchEntriesForStage(entries, 'st-1').map((m) => m.id), ['m-1', 'm-susp']);
  assert.deepEqual(matchEntriesForGroup(entries, 'st-1', 'g-1').map((m) => m.id), ['m-1', 'm-susp']);
  // Otro grupo conserva el filtro de origen: el suspendido no se infiltra.
  assert.equal(matchEntriesForGroup(entries, 'st-1', 'g-2').length, 0);
});

test('un clásico cargado sin filtro de grupo conserva su grupo publicado', () => {
  // Sin `group_id` en la consulta, el contexto sale del objeto clásico:
  // si luego se filtra por su grupo, el partido sigue visible.
  const entries = mergeMatchEntries([], [classic()], 'st-1', null);
  assert.deepEqual(matchEntriesForGroup(entries, 'st-1', 'g-1').map((m) => m.id), ['m-1']);
  // Y una recarga bajo el grupo tampoco lo pierde.
  const refetched = mergeMatchEntries(entries, [classic()], 'st-1', 'g-1');
  assert.deepEqual(matchEntriesForGroup(refetched, 'st-1', 'g-1').map((m) => m.id), ['m-1']);
  assert.equal(matchEntriesForGroup(refetched, 'st-1', 'g-2').length, 0);
});

test('al cambiar de estado la tarjeta se reconstruye sin duplicados ni omisiones', () => {
  let entries = mergeMatchEntries([], [classic({ status: 'live' })], 'st-1', null);
  // El partido pasa a suspended y la página recargada lo trae con otro objeto.
  entries = mergeMatchEntries(entries, [SUSPENDED_WITH_SAME_ID()], 'st-1', null);
  assert.equal(entries.length, 1);
  assert.equal(entries[0]!.match.status, 'suspended');
  assert.deepEqual(matchEntriesForStage(entries, 'st-1').map((m) => m.id), ['m-1']);
  // Y al reanudar a live vuelve a la misma posición, sin segunda tarjeta.
  entries = mergeMatchEntries(entries, [classic({ status: 'live' })], 'st-1', null);
  assert.equal(entries.length, 1);
  assert.equal(entries[0]!.match.status, 'live');
});

function SUSPENDED_WITH_SAME_ID(): SuspendedPublicMatch {
  return { ...SUSPENDED, id: 'm-1' };
}

test('el suspendido nunca entra al bracket por carecer de llave', () => {
  const eligible = bracketEligibleMatches([classic({ bracket_code: 'QF1' }), SUSPENDED]);
  assert.deepEqual(eligible.map((m) => m.id), ['m-1']);
});

test('marcador provisional con reloj detenido y referencia nula', () => {
  assert.equal(formatSuspendedClock(SUSPENDED), '45:33');
  assert.equal(formatSuspendedClock({ ...SUSPENDED, clock_elapsed_seconds: null, clock_segment_number: null, clock_state: 'not_started' }), null);
  assert.equal(formatSuspendedClock({ ...SUSPENDED, clock_elapsed_seconds: -3 }), null);
});
