import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  effectiveRosterLockMatchday,
  isRosterLockActive,
  latestPublishedVersion,
  rosterLockMatchday,
  type RosterLockMatchLike,
  type RosterLockStageLike,
} from '../app/utils/rosterLock.ts';

// RF-017/RF-039 (P4): el aviso de cierre de inscripción replica en el cliente
// la regla del servidor y nunca impide guardar. La regla es la misma que
// `_active_roster_lock_matchday` del router de torneos:
//   - jornada de referencia = `roster_lock_matchday` de la versión publicada;
//   - primera fase por `stage_order` (el `id` desempata);
//   - al menos un partido no cancelado de esa jornada en esa fase y **todos**
//     confirmados (`finished` / `administrative_resolution`).

const rostersPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/rosters.vue', import.meta.url),
  'utf8',
);

const configWithLock = (matchday: unknown = 1) => ({ roster_lock_matchday: matchday });

const stage = (id: string, stageOrder: number, versionId = 'v1'): RosterLockStageLike => ({
  id,
  tournament_version_id: versionId,
  stage_order: stageOrder,
});

const match = (
  overrides: Partial<RosterLockMatchLike> & Pick<RosterLockMatchLike, 'id'>,
): RosterLockMatchLike => ({
  stage_id: 's1',
  tournament_version_id: 'v1',
  matchday: 1,
  status: 'scheduled',
  ...overrides,
});

test('never locks without a reference matchday or without a stage', () => {
  const stages = [stage('s1', 1)];
  const confirmed = [match({ id: 'm1', status: 'finished' })];

  assert.equal(isRosterLockActive({}, stages, confirmed), false);
  assert.equal(isRosterLockActive(configWithLock(null), stages, confirmed), false);
  assert.equal(isRosterLockActive(configWithLock(2), stages, confirmed), false, 'otra jornada no cierra la referencia');
  assert.equal(isRosterLockActive(configWithLock(1), [], confirmed), false);
  assert.equal(isRosterLockActive(configWithLock(1), stages, []), false);
});

test('locks when every non-cancelled match of the reference matchday is confirmed', () => {
  const stages = [stage('s1', 1)];
  const matches = [
    match({ id: 'm1', status: 'finished' }),
    match({ id: 'm2', status: 'administrative_resolution' }),
  ];

  assert.equal(isRosterLockActive(configWithLock(1), stages, matches), true);
  assert.equal(rosterLockMatchday(configWithLock(1), stages, matches), 1);
});

test('does not lock while any match of the reference matchday is unconfirmed', () => {
  const stages = [stage('s1', 1)];
  const matches = [
    match({ id: 'm1', status: 'finished' }),
    match({ id: 'm2', status: 'scheduled' }),
  ];

  assert.equal(isRosterLockActive(configWithLock(1), stages, matches), false);
  assert.equal(rosterLockMatchday(configWithLock(1), stages, matches), null);
});

test('ignores cancelled matches, another matchday and another stage', () => {
  const stages = [stage('s1', 1), stage('s2', 2)];
  const onlyCancelled = [match({ id: 'm1', status: 'cancelled' })];
  assert.equal(isRosterLockActive(configWithLock(1), stages, onlyCancelled), false);

  const withCancelled = [
    match({ id: 'm1', status: 'finished' }),
    match({ id: 'm2', status: 'cancelled' }),
  ];
  assert.equal(isRosterLockActive(configWithLock(1), stages, withCancelled), true);

  const otherMatchday = [match({ id: 'm1', matchday: 2, status: 'finished' })];
  assert.equal(isRosterLockActive(configWithLock(1), stages, otherMatchday), false);

  const otherStage = [match({ id: 'm1', stage_id: 's2', status: 'finished' })];
  assert.equal(isRosterLockActive(configWithLock(1), stages, otherStage), false);
});

test('uses the first stage by stage_order and breaks ties by id', () => {
  const stages = [stage('s-b', 1), stage('s-a', 1), stage('s-c', 2)];
  const matches = [
    match({ id: 'm1', stage_id: 's-a', status: 'scheduled' }),
    match({ id: 'm2', stage_id: 's-b', status: 'finished' }),
    match({ id: 'm3', stage_id: 's-c', status: 'finished' }),
  ];

  // s-a gana el empate por id: su partido no está confirmado, así que no hay cierre.
  assert.equal(isRosterLockActive(configWithLock(1), stages, matches), false);

  const confirmedFirst = matches.map((entry) => (
    entry.stage_id === 's-a' ? { ...entry, status: 'finished' } : entry
  ));
  assert.equal(isRosterLockActive(configWithLock(1), stages, confirmedFirst), true);
});

test('reads the deprecated transfers block only when the top-level key is missing', () => {
  assert.equal(effectiveRosterLockMatchday({ transfers: { roster_lock_matchday: 3 } }), 3);
  assert.equal(
    effectiveRosterLockMatchday({ roster_lock_matchday: 2, transfers: { roster_lock_matchday: 3 } }),
    2,
  );
  assert.equal(effectiveRosterLockMatchday({ roster_lock_matchday: null, transfers: { roster_lock_matchday: 3 } }), 3);
  assert.equal(effectiveRosterLockMatchday({ roster_lock_matchday: 0 }), null);
  assert.equal(effectiveRosterLockMatchday(null), null);
});

test('selects the most recent published version and ignores drafts and archives', () => {
  const versions = [
    { id: 'v3', version_number: 3, status: 'draft' },
    { id: 'v2', version_number: 2, status: 'published', published_at: '2026-10-01T00:00:00Z' },
    { id: 'v1', version_number: 1, status: 'published', published_at: '2026-09-01T00:00:00Z' },
    { id: 'v0', version_number: 0, status: 'archived' },
  ];

  assert.equal(latestPublishedVersion(versions)?.id, 'v2');
  assert.equal(latestPublishedVersion([versions[0], versions[3]]), null);
  assert.equal(latestPublishedVersion([]), null);
});

// RF-017/RF-021/RF-024/RF-039: la ruta es la única pantalla de plantillas, con
// formulario único (alta, importación, foto y consentimiento), el aviso de
// cierre y el enlace al asistente de fases; solo pide la plantilla del equipo
// seleccionado.
test('renders the single roster form on its own route', () => {
  assert.match(rostersPage, /@submit\.prevent="createPlayer"/, 'falta el alta individual');
  assert.match(rostersPage, /`\/tournaments\/\$\{tournamentId\}\/rosters`/, 'falta el alta individual');
  assert.match(rostersPage, /\/rosters\/bulk/, 'falta la importación CSV/ZIP');
  assert.match(rostersPage, /\/photo`/, 'falta la subida de foto');
  assert.match(rostersPage, /\/photo-consent`/, 'falta el consentimiento');
  assert.match(rostersPage, /rosterLockMatchday/, 'falta el aviso de cierre de inscripción');
  assert.match(rostersPage, /phasesAssistantHref/, 'falta el enlace al asistente de fases');
  assert.match(
    rostersPage,
    /\/rosters\?team_id=/,
    'la lista debe pedir solo la plantilla del equipo seleccionado (RF-024)',
  );
});

test('does not duplicate the stage inscription or the schedule generator', () => {
  assert.doesNotMatch(rostersPage, /stages\/\$?\{?[^`]*\/teams/);
  assert.doesNotMatch(rostersPage, /matches\/draw/);
  assert.doesNotMatch(rostersPage, /birth_date_ENCRYPTED|national_id\s*\}\}/);
});
