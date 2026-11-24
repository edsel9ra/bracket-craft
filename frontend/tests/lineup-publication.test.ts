import assert from 'node:assert/strict';
import test from 'node:test';
import { withdrawnPublicTeams, type PublicationRow } from '../app/utils/lineupPublication.ts';

// Spec 045, RF-003: el Workspace anticipa con el estado cargado qué formaciones
// publicadas retiraría el guardado, con la misma definición que el servidor
// (DA-2): formación y, por jugador convocado, rol y posición; sin minutos ni orden.

const rosters = [
  ...['p0', 'p1', 'p2', 'p3', 'p4', 'p5'].map((player_id, i) => ({ roster_id: `h${i}`, player_id, team_id: 'home' })),
  ...['q0', 'q1', 'q2', 'q3', 'q4', 'q5'].map((player_id, i) => ({ roster_id: `a${i}`, player_id, team_id: 'away' })),
];
const SLOTS = ['GK', 'LCB', 'RCB', 'ST_L', 'ST_R'];

function rows(team: 'home' | 'away', isPublic: boolean, formation = '2-2'): PublicationRow[] {
  const prefix = team === 'home' ? 'p' : 'q';
  return [
    ...SLOTS.map((slot, i) => ({ team_id: team, formation_code: formation, is_public: isPublic, player_id: `${prefix}${i}`, is_starter: true, position_slot: slot })),
    { team_id: team, formation_code: formation, is_public: isPublic, player_id: `${prefix}5`, is_starter: false, position_slot: null },
  ];
}

function entries(team: 'home' | 'away', slots = SLOTS) {
  const prefix = team === 'home' ? 'h' : 'a';
  return [
    ...slots.map((slot, i) => ({ roster_id: `${prefix}${i}`, role: 'starter' as const, position_slot: slot })),
    { roster_id: `${prefix}5`, role: 'substitute' as const, position_slot: null },
  ];
}

const stored = [...rows('home', true), ...rows('away', true)];
const both = { home: '2-2', away: '2-2' };

test('sin cambios no retira nada, aunque cambie el orden de la petición', () => {
  const request = [...entries('away'), ...entries('home')].reverse();
  assert.deepEqual(withdrawnPublicTeams(stored, both, request, rosters), []);
});

test('cambiar la posición de un jugador del local solo retira al local', () => {
  const swapped = ['GK', 'RCB', 'LCB', 'ST_L', 'ST_R'];
  assert.deepEqual(withdrawnPublicTeams(stored, both, [...entries('home', swapped), ...entries('away')], rosters), ['home']);
});

test('cambiar el rol o la convocatoria de un jugador retira a su equipo', () => {
  const promoted = entries('away').map((entry) => entry.roster_id === 'a5' ? { ...entry, role: 'starter' as const, position_slot: 'ST_R' } : entry)
    .map((entry) => entry.roster_id === 'a4' ? { ...entry, role: 'substitute' as const, position_slot: null } : entry);
  assert.deepEqual(withdrawnPublicTeams(stored, both, [...entries('home'), ...promoted], rosters), ['away']);
  const dropped = entries('home').filter((entry) => entry.roster_id !== 'h5');
  assert.deepEqual(withdrawnPublicTeams(stored, both, [...dropped, ...entries('away')], rosters), ['home']);
});

test('cambiar la formación de los dos equipos los retira a ambos', () => {
  const changed = { home: '1-2-1', away: '2-1-1' };
  assert.deepEqual(withdrawnPublicTeams(stored, changed, [...entries('home'), ...entries('away')], rosters), ['home', 'away']);
});

test('pasar a la planilla clásica retira cada formación publicada', () => {
  const classic = [...entries('home'), ...entries('away')].map((entry) => ({ ...entry, position_slot: null }));
  assert.deepEqual(withdrawnPublicTeams(stored, { home: '', away: '' }, classic, rosters), ['home', 'away']);
  assert.deepEqual(withdrawnPublicTeams(stored, {}, classic, rosters), ['home', 'away']);
});

test('un equipo privado que cambia no se retira', () => {
  const privateHome = [...rows('home', false), ...rows('away', true)];
  assert.deepEqual(withdrawnPublicTeams(privateHome, { home: '1-2-1', away: '2-2' }, [...entries('home'), ...entries('away')], rosters), []);
});

test('sin formaciones guardadas no hay nada que retirar', () => {
  assert.deepEqual(withdrawnPublicTeams([], both, [...entries('home'), ...entries('away')], rosters), []);
});
