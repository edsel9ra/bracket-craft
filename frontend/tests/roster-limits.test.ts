import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  OPENING_BLOCKED_LABEL_KEYS,
  ROSTER_STATE_ABOVE,
  ROSTER_STATE_BELOW,
  ROSTER_STATE_OK,
  describeOpeningBlocked,
  describeRosterSize,
  effectiveRosterLimits,
  explainRosterEnrollment,
  hasRosterLimits,
  rosterLimitLabel,
  rosterSizeLabelKey,
  rosterSizeState,
  rosterStatusFailureKey,
  rosterStatusGuidance,
  type RosterLimits,
} from '../app/utils/rosterLimits.ts';

// RF-046 / RF-051 / RL-1 / RA-1 (H4-T08).
//
// El estado por equipo y el texto del botón de inscribir son funciones puras:
// no leen el reloj, el entorno, el almacenamiento ni la red. El servidor sigue
// siendo la autoridad de los tres bloqueos; estas funciones solo describen lo
// que el usuario ve antes de escribir, con los mismos límites efectivos
// (0 = sin límite) que resuelve `effective_roster_limits` en el backend.
//
// Editar la plantilla nunca se bloquea por tamaño (solo avisa) y el retiro
// lógico es la única escritura exenta del bloqueo por jornada (RL-1). La
// reactivación se comporta como un alta (RA-1) y conserva sus 409: el cierre
// de inscripción, el jugador con otra fila activa en el torneo y el dorsal ya
// ocupado.

const rostersPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/rosters.vue', import.meta.url),
  'utf8',
);
const configurationPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
  'utf8',
);
const stageWizard = readFileSync(
  new URL('../app/components/StageTeamsWizard.vue', import.meta.url),
  'utf8',
);
const matchPage = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translations.slice(0, englishStart),
    english: translations.slice(englishStart),
  };
}

function catalogMap(slice: string): Map<string, string> {
  const map = new Map<string, string>();
  const pattern = /'((?:[^'\\]|\\.)*)':\s*'((?:[^'\\]|\\.)*)'/g;
  for (const match of slice.matchAll(pattern)) {
    map.set(match[1]!, match[2]!.replaceAll("\\'", "'"));
  }
  return map;
}

function translator(slice: string) {
  const catalog = catalogMap(slice);
  return (key: string, values: Record<string, string | number> = {}): string => {
    const message = catalog.get(key) ?? key;
    return message.replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? `{${name}}`));
  };
}

const tEs = translator(catalogSlices().spanish);
const tEn = translator(catalogSlices().english);

const limits = (min: number, max: number): RosterLimits => ({ min, max });

// Un límite ausente, nulo, cero, negativo o de tipo inesperado significa «sin
// límite»; la cadena numérica se acepta igual que el entero que guarda el
// servidor (RF-044, RF-045).
test('resolves effective limits with 0 meaning no limit', () => {
  assert.deepEqual(effectiveRosterLimits(null), limits(0, 0));
  assert.deepEqual(effectiveRosterLimits(undefined), limits(0, 0));
  assert.deepEqual(effectiveRosterLimits({}), limits(0, 0));
  assert.deepEqual(
    effectiveRosterLimits({ min_players_per_team: 7, max_players_per_team: 10 }),
    limits(7, 10),
  );
  assert.deepEqual(
    effectiveRosterLimits({ min_players_per_team: '7', max_players_per_team: null }),
    limits(7, 0),
  );
  assert.deepEqual(
    effectiveRosterLimits({ min_players_per_team: -3, max_players_per_team: true }),
    limits(0, 0),
  );
  assert.deepEqual(effectiveRosterLimits({ min_players_per_team: 'siete' }), limits(0, 0));

  assert.equal(hasRosterLimits(limits(0, 0)), false);
  assert.equal(hasRosterLimits(limits(5, 0)), true);
  assert.equal(hasRosterLimits(limits(0, 10)), true);
});

// RF-046: los tres estados por equipo, con los bordes incluidos y con las
// mitades independientes del rango.
test('classifies each team as meets, below or above the effective limits', () => {
  const range = limits(7, 10);

  assert.equal(rosterSizeState(7, range), ROSTER_STATE_OK);
  assert.equal(rosterSizeState(8, range), ROSTER_STATE_OK);
  assert.equal(rosterSizeState(10, range), ROSTER_STATE_OK);
  assert.equal(rosterSizeState(6, range), ROSTER_STATE_BELOW);
  assert.equal(rosterSizeState(0, range), ROSTER_STATE_BELOW);
  assert.equal(rosterSizeState(11, range), ROSTER_STATE_ABOVE);

  assert.equal(rosterSizeState(4, limits(5, 0)), ROSTER_STATE_BELOW);
  assert.equal(rosterSizeState(50, limits(5, 0)), ROSTER_STATE_OK);
  assert.equal(rosterSizeState(6, limits(0, 5)), ROSTER_STATE_ABOVE);
  assert.equal(rosterSizeState(0, limits(0, 5)), ROSTER_STATE_OK);

  // Sin límite, cualquier tamaño cumple.
  for (const count of [0, 1, 30, 500]) {
    assert.equal(rosterSizeState(count, limits(0, 0)), ROSTER_STATE_OK);
  }
});

// RF-046: «cumple / por debajo / por encima» y «sin límite» salen del catálogo
// es/en; la descripción añade la cantidad actual y el rango vigente.
test('labels the three states and shows no limit in both languages', () => {
  assert.equal(rosterSizeLabelKey(ROSTER_STATE_OK), 'rosterLimits.state.ok');
  assert.equal(rosterSizeLabelKey(ROSTER_STATE_BELOW), 'rosterLimits.state.below');
  assert.equal(rosterSizeLabelKey(ROSTER_STATE_ABOVE), 'rosterLimits.state.above');

  assert.equal(tEs(rosterSizeLabelKey(ROSTER_STATE_OK)), 'Cumple');
  assert.equal(tEs(rosterSizeLabelKey(ROSTER_STATE_BELOW)), 'Por debajo');
  assert.equal(tEs(rosterSizeLabelKey(ROSTER_STATE_ABOVE)), 'Por encima');
  assert.equal(tEn(rosterSizeLabelKey(ROSTER_STATE_OK)), 'Meets');

  assert.equal(rosterLimitLabel(0, tEs), 'Sin límite');
  assert.equal(rosterLimitLabel(0, tEn), 'No limit');
  assert.equal(rosterLimitLabel(7, tEs), '7');

  const below = describeRosterSize(6, limits(7, 10), tEs);
  assert.equal(below.state, ROSTER_STATE_BELOW);
  assert.equal(below.label, 'Por debajo');
  assert.equal(below.minLabel, '7');
  assert.equal(below.maxLabel, '10');
  assert.match(below.detail, /6 jugadores activos/);
  assert.match(below.detail, /mínimo 7/);
  assert.match(below.detail, /máximo 10/);

  const noLimit = describeRosterSize(30, limits(0, 0), tEs);
  assert.equal(noLimit.state, ROSTER_STATE_OK);
  assert.equal(noLimit.minLabel, 'Sin límite');
  assert.equal(noLimit.maxLabel, 'Sin límite');
  assert.match(noLimit.detail, /Sin límite/);
});

// RF-046: el botón de inscribir explica qué falta —equipo, mínimo/máximo y
// cantidad actual— sin ocultar el motivo. Un equipo dentro del rango no tiene
// explicación y se ofrece normalmente.
test('explains the blocked enrolment with the team, range and current count', () => {
  const below = explainRosterEnrollment(
    { teamId: 't1', teamName: 'Tigres', count: 5, limits: limits(7, 10) },
    tEs,
  );
  assert.equal(below.blocked, true);
  assert.equal(below.state, ROSTER_STATE_BELOW);
  assert.equal(below.missing, 2);
  assert.equal(below.excess, 0);
  assert.equal(below.messageKey, 'rosterLimits.enroll.below');
  assert.match(below.message, /Tigres/);
  assert.match(below.message, /5 jugadores activos/);
  assert.match(below.message, /mínimo es 7/);
  assert.match(below.message, /faltan 2/);

  const above = explainRosterEnrollment(
    { teamId: 't2', teamName: 'Águilas', count: 12, limits: limits(7, 10) },
    tEs,
  );
  assert.equal(above.blocked, true);
  assert.equal(above.state, ROSTER_STATE_ABOVE);
  assert.equal(above.missing, 0);
  assert.equal(above.excess, 2);
  assert.equal(above.messageKey, 'rosterLimits.enroll.above');
  assert.match(above.message, /Águilas/);
  assert.match(above.message, /12 jugadores activos/);
  assert.match(above.message, /máximo es 10/);
  assert.match(above.message, /sobran 2/);

  const inside = explainRosterEnrollment(
    { teamId: 't3', teamName: 'Osos', count: 8, limits: limits(7, 10) },
    tEs,
  );
  assert.equal(inside.blocked, false);
  assert.equal(inside.messageKey, null);
  assert.equal(inside.message, '');

  const withoutLimits = explainRosterEnrollment(
    { teamId: 't4', teamName: 'Libres', count: 0, limits: limits(0, 0) },
    tEs,
  );
  assert.equal(withoutLimits.blocked, false);
  assert.equal(withoutLimits.message, '');
});

// RF-045: por debajo del mínimo con el cierre de inscripción activo la vía para
// añadir jugadores está cerrada; el mensaje lo dice y no promete una salida que
// no existe. Por encima del máximo el retiro lógico sigue disponible.
test('explains when the matchday lock blocks adding the missing players', () => {
  const locked = explainRosterEnrollment(
    { teamId: 't1', teamName: 'Tigres', count: 5, limits: limits(7, 10), lockActive: true },
    tEs,
  );
  assert.equal(locked.blocked, true);
  assert.equal(locked.state, ROSTER_STATE_BELOW);
  assert.equal(locked.messageKey, 'rosterLimits.enroll.belowLocked');
  assert.match(locked.message, /Tigres/);
  assert.match(locked.message, /faltan 2/);
  assert.match(locked.message, /cierre de inscripción/);
  assert.match(locked.message, /retiro lógico/);

  const lockedEnglish = explainRosterEnrollment(
    { teamId: 't1', teamName: 'Tigers', count: 5, limits: limits(7, 10), lockActive: true },
    tEn,
  );
  assert.equal(lockedEnglish.messageKey, 'rosterLimits.enroll.belowLocked');
  assert.match(lockedEnglish.message, /enrollment lock/);
  assert.match(lockedEnglish.message, /logical retirement/);

  const withoutLock = explainRosterEnrollment(
    { teamId: 't1', teamName: 'Tigres', count: 5, limits: limits(7, 10), lockActive: false },
    tEs,
  );
  assert.equal(withoutLock.messageKey, 'rosterLimits.enroll.below');
  assert.doesNotMatch(withoutLock.message, /cierre de inscripción/);

  const above = explainRosterEnrollment(
    { teamId: 't2', teamName: 'Águilas', count: 12, limits: limits(7, 10), lockActive: true },
    tEs,
  );
  assert.equal(above.messageKey, 'rosterLimits.enroll.above');
  assert.match(above.message, /sobran 2/);

  assert.match(stageWizard, /lockActive/);
  assert.match(stageWizard, /props\.lockActive/);
  assert.match(stageWizard, /stage\.wizard\.enrollmentLockedHint/);
  assert.match(configurationPage, /isRosterLockActive\(/);
  assert.match(configurationPage, /:lock-active="rosterLockActive"/);
});

// RF-046: la pantalla de plantillas y la composición de fases muestran el
// estado por equipo; la configuración entrega a su asistente los límites de la
// versión y el conteo activo por equipo que ya carga.
test('shows the state per team in rosters and in the phase composition', () => {
  assert.match(rostersPage, /describeRosterSize\(/);
  assert.match(rostersPage, /effectiveRosterLimits\(/);
  assert.match(stageWizard, /describeRosterSize\(/);
  assert.match(stageWizard, /explainRosterEnrollment\(/);
  assert.match(configurationPage, /effectiveRosterLimits\(/);
  assert.match(configurationPage, /:roster-limits="selectedVersionRosterLimits"/);
  assert.match(configurationPage, /:roster-counts="rosterCountsByTeam"/);
  assert.match(stageWizard, /props\.rosterLimits/);
  assert.match(stageWizard, /props\.rosterCounts/);
});

// RF-046: editar la plantilla nunca se bloquea por tamaño. Ningún control de
// alta, importación, foto o consentimiento condiciona su `disabled` al estado
// del equipo; el aviso existe y es solo informativo.
test('editing a roster is only warned, never blocked by size', () => {
  assert.match(rostersPage, /tournament\.rosters\.sizeOutOfRange/, 'the size warning is missing');

  for (const match of rostersPage.matchAll(/:disabled="([^"]*)"/g)) {
    assert.doesNotMatch(
      match[1]!,
      /sizeDescription|sizeWarning|rosterSizeState|enrollmentBlocked/,
      'a roster edit control is disabled by the team size',
    );
  }

  // El alta y la importación conservan su bloqueo propio (jornada/busy), no el
  // de tamaño: el servidor sigue siendo la autoridad y su 409 se muestra igual.
  assert.match(rostersPage, /@submit\.prevent="createPlayer"/);
  assert.match(rostersPage, /@submit\.prevent="importRoster"/);
  assert.doesNotMatch(rostersPage, /if \([^)]*rosterSizeState\([^)]*\)[^)]*\) return;/);
});

// RL-1 / RA-1: el retiro está exento del bloqueo por jornada; la reactivación
// se comporta como un alta y recibe el mismo 409.
test('retirement is exempt from the matchday lock and reactivation is subject to it', () => {
  const retire = rosterStatusGuidance('retire', { lockActive: true });
  assert.equal(retire.action, 'retire');
  assert.equal(retire.lockApplies, false);
  assert.equal(retire.hintKey, null);

  const lockedReactivation = rosterStatusGuidance('reactivate', { lockActive: true });
  assert.equal(lockedReactivation.action, 'reactivate');
  assert.equal(lockedReactivation.lockApplies, true);
  assert.equal(lockedReactivation.hintKey, 'tournament.rosters.reactivateLocked');
  assert.match(tEs(lockedReactivation.hintKey!), /409/);

  const openRegistration = rosterStatusGuidance('reactivate', { lockActive: false });
  assert.equal(openRegistration.lockApplies, true);
  assert.equal(openRegistration.hintKey, null);

  // La pantalla usa la guía pura y el endpoint nuevo con el cuerpo del contrato.
  assert.match(rostersPage, /rosterStatusGuidance\(/);
  assert.match(rostersPage, /rosters\/\$\{roster\.roster_id\}\/status/);
  assert.match(rostersPage, /is_active: !roster\.is_active/);
  for (const match of rostersPage.matchAll(/:disabled="([^"]*)"/g)) {
    assert.doesNotMatch(match[1]!, /lockMatchday/, 'the matchday lock disables a roster action');
  }
});

// RF-051 / RA-1: la reactivación conserva los tres 409 del alta —cierre de
// inscripción, jugador con otra fila activa en el torneo y dorsal ocupado— y el
// mensaje del servidor se muestra tal cual.
test('reactivation keeps the registration 409 and the player and dorsal conflicts', () => {
  assert.equal(rosterStatusFailureKey('retire'), 'tournament.rosters.retireFailed');
  assert.equal(rosterStatusFailureKey('reactivate'), 'tournament.rosters.reactivateFailed');

  const spanish = catalogMap(catalogSlices().spanish);
  const english = catalogMap(catalogSlices().english);
  const reactivateFailedEs = spanish.get('tournament.rosters.reactivateFailed') ?? '';
  const reactivateFailedEn = english.get('tournament.rosters.reactivateFailed') ?? '';
  assert.match(reactivateFailedEs, /cierre de inscripción/);
  assert.match(reactivateFailedEs, /fila activa/);
  assert.match(reactivateFailedEs, /dorsal/);
  assert.match(reactivateFailedEn, /registration/);
  assert.match(reactivateFailedEn, /active row/);
  assert.match(reactivateFailedEn, /dorsal/);

  // El detalle del servidor (cierre, duplicado o dorsal) llega a la alerta.
  assert.match(rostersPage, /failureMessage\(cause, t\(rosterStatusFailureKey\(/);
  assert.match(rostersPage, /role="alert"/);
});

// RF-046: la composición de fases explica el bloqueo de inscribir y conserva la
// selección; no se adelanta el bloqueo de la apertura del partido (H4-T09).
test('the blocked inscription keeps the team selection and explains the reason', () => {
  assert.match(stageWizard, /enrollmentExplanations/);
  assert.match(stageWizard, /enrollmentBlocked/);
  assert.match(stageWizard, /enrollmentBlocked\.value/);
  assert.match(stageWizard, /v-if="enrollmentExplanations\.length"/);
  assert.doesNotMatch(stageWizard, /if \(enrollmentBlocked\.value\)[^}]*form\.teamIds\s*=\s*\[\]/);
  assert.doesNotMatch(stageWizard, /ROSTER_SIZE_OUT_OF_RANGE|firstSegment|openingBlocked/);
});

// RNF-011: el estado y el retiro no viven en almacenamiento persistente; la
// pantalla no replica la escritura del servidor ni añade un cliente paralelo.
test('roster state and status use no persistent storage and only useApi', () => {
  for (const source of [rostersPage, stageWizard]) {
    assert.doesNotMatch(source, /localStorage/);
  }
  // La configuración solo **lee** el borrador local del partido para avisar de
  // los minutos (RF-035); no persiste estado de plantilla ni del retiro.
  assert.match(configurationPage, /createMatchDraftStore\(/);
  assert.doesNotMatch(configurationPage, /localStorage\.(setItem|removeItem)/);
  assert.match(rostersPage, /useApi\(\)/);
});

// ---------------------------------------------------------------------------
// Spec 012, H4-T09 (RF-050, RF-046).
//
// La apertura del partido la decide el servidor. El cliente solo traduce el
// 409 `ROSTER_SIZE_OUT_OF_RANGE` a un aviso que conserva **equipo, mínimo,
// máximo y cantidad**, recuerda que el partido no se ha abierto y enlaza a la
// plantilla del equipo para corregirla. La comprobación local es una guía no
// bloqueante: el intento siempre llega al servidor y su 409 manda.
// ---------------------------------------------------------------------------

const OPENING_PARTICIPANTS = [
  { teamId: 'team-1', teamName: 'Leones', count: 9 },
  { teamId: 'team-2', teamName: 'Águilas', count: 26 },
];

test('describes the blocked opening with each team, minimum, maximum and count', () => {
  const notice = describeOpeningBlocked(
    {
      detail: 'Plantilla fuera de rango: Leones: 9 jugadores activos (mínimo 11, máximo 25).',
      limits: limits(11, 25),
      participants: OPENING_PARTICIPANTS,
    },
    tEs,
  );

  assert.deepEqual(notice.teams.map((team) => team.teamId), ['team-1', 'team-2']);
  for (const team of notice.teams) {
    assert.equal(team.messageKey, OPENING_BLOCKED_LABEL_KEYS.team);
    assert.match(team.message, new RegExp(team.teamName));
    assert.match(team.message, new RegExp(`${team.count} jugadores activos`));
    assert.equal(team.minLabel, '11');
    assert.equal(team.maxLabel, '25');
    assert.match(team.message, /mínimo 11/);
    assert.match(team.message, /máximo 25/);
  }
  assert.equal(notice.teams[0]!.state, ROSTER_STATE_BELOW);
  assert.equal(notice.teams[1]!.state, ROSTER_STATE_ABOVE);
  assert.equal(
    notice.detail,
    'Plantilla fuera de rango: Leones: 9 jugadores activos (mínimo 11, máximo 25).',
    'the server detail is preserved verbatim as the authority',
  );
});

test('keeps the server detail as authority when the local counts are stale', () => {
  // Los recuentos locales parecen correctos, pero el servidor nombra a un
  // equipo: se ofrece el enlace de ese equipo sin inventar otros.
  const stale = describeOpeningBlocked(
    {
      detail: 'Plantilla fuera de rango: Águilas: 3 jugadores activos (mínimo 7, máximo 10).',
      limits: limits(7, 10),
      participants: [
        { teamId: 'team-1', teamName: 'Leones', count: 8 },
        { teamId: 'team-2', teamName: 'Águilas', count: 8 },
      ],
    },
    tEn,
  );
  assert.deepEqual(stale.teams.map((team) => team.teamId), ['team-2']);
  assert.match(stale.teams[0]!.message, /Roster of/);
  assert.match(stale.teams[0]!.message, /8 active players/);

  // Sin señal local ni equipo nombrado, se ofrecen ambos enlaces para que el
  // operador llegue a la plantilla correcta; «sin límite» se presenta como tal.
  const unknown = describeOpeningBlocked(
    { detail: '', limits: limits(0, 0), participants: OPENING_PARTICIPANTS },
    tEs,
  );
  assert.deepEqual(unknown.teams.map((team) => team.teamId), ['team-1', 'team-2']);
  assert.equal(unknown.teams[0]!.minLabel, 'Sin límite');
  assert.equal(unknown.teams[0]!.maxLabel, 'Sin límite');
  assert.match(unknown.teams[0]!.message, /Sin límite/);

  // La descripción es pura: no altera los participantes recibidos.
  assert.equal(OPENING_PARTICIPANTS[0]!.count, 9);
});

test('the operation shows the opening 409 and only guides, never blocks before the server', () => {
  assert.match(matchPage, /describeOpeningBlocked\(/);
  assert.match(matchPage, /effectiveRosterLimits\(/);
  assert.match(matchPage, /classifyMatchConflict\(cause\) === 'roster_size_out_of_range'/);
  assert.match(matchPage, /openingBlocked\.value = describeOpeningBlocked\(/);
  assert.match(matchPage, /teamRosterLink\(team\.teamId\)/);
  assert.match(matchPage, /OPENING_BLOCKED_LABEL_KEYS\.retryAction/);
  assert.match(matchPage, /@click="createSegment"/);

  const start = matchPage.indexOf('async function createSegment(');
  const end = matchPage.indexOf('async function interruptSegment(');
  assert.ok(start > 0 && end > start, 'the segment creation handler is missing');
  const body = matchPage.slice(start, end);
  const requestAt = body.indexOf('/matches/${matchId}/segments`');
  assert.ok(requestAt > 0, 'the creation request is missing');
  assert.doesNotMatch(
    body.slice(0, requestAt),
    /openingBlocked|rosterSizeState|hasRosterLimits|effectiveRosterLimits/,
    'nothing in the client blocks the attempt before the server answers',
  );
  assert.ok(
    body.indexOf('showOpeningBlocked(cause)') > requestAt,
    'the opening notice is built only from the server response',
  );

  // El aviso es puramente descriptivo: no llama a la API ni escribe el
  // formulario del segmento.
  const noticeStart = matchPage.indexOf('function showOpeningBlocked(');
  const noticeEnd = matchPage.indexOf('async function createSegment(');
  assert.ok(noticeStart > 0 && noticeEnd > noticeStart, 'the opening notice builder is missing');
  const notice = matchPage.slice(noticeStart, noticeEnd);
  assert.match(notice, /describeOpeningBlocked\(/);
  assert.doesNotMatch(notice, /request\(|\$fetch|refreshOperation\(|segmentForm\./);
});
