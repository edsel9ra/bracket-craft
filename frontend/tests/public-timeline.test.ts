import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  canOpenTimeline,
  formatTimelineMinute,
  shouldReloadTimeline,
  timelineEventKey,
  timelineEventSide,
  timelineGroups,
  timelinePlayerName,
  type PublicTimelineEvent,
} from '../app/utils/publicTimeline.ts';

function event(overrides: Partial<PublicTimelineEvent> = {}): PublicTimelineEvent {
  return {
    event_type: 'goal',
    minute: 10,
    added_minute: 0,
    segment_number: 1,
    team_id: 'home',
    beneficiary_team_id: null,
    red_card_type: null,
    player: { player_id: 'p1', first_name: 'Ana', last_name: 'López' },
    player_in: null,
    ...overrides,
  };
}

const match = {
  status: 'finished',
  home_score: 1,
  away_score: 0,
  home_penalties: null,
  away_penalties: null,
  rectified_at: null,
};

test('solo los partidos finished abren la cronología', () => {
  assert.equal(canOpenTimeline({ status: 'finished' }), true);
  for (const status of ['scheduled', 'live', 'suspended', 'administrative_resolution', 'cancelled']) {
    assert.equal(canOpenTimeline({ status }), false, status);
  }
  assert.equal(canOpenTimeline(null), false);
});

test('formatea el minuto con y sin tiempo añadido', () => {
  assert.equal(formatTimelineMinute(37, 0), "37'");
  assert.equal(formatTimelineMinute(45, 2), "45+2'");
  assert.equal(formatTimelineMinute(90), "90'");
  assert.equal(formatTimelineMinute(-3, -1), "0'");
});

test('clave i18n por tipo y por clasificación de la roja', () => {
  assert.equal(timelineEventKey(event()), 'publicTimeline.event.goal');
  assert.equal(timelineEventKey(event({ event_type: 'penalty_goal' })), 'publicTimeline.event.penaltyGoal');
  assert.equal(timelineEventKey(event({ event_type: 'own_goal' })), 'publicTimeline.event.ownGoal');
  assert.equal(timelineEventKey(event({ event_type: 'yellow_card' })), 'publicTimeline.event.yellowCard');
  assert.equal(timelineEventKey(event({ event_type: 'substitution' })), 'publicTimeline.event.substitution');
  assert.equal(timelineEventKey(event({ event_type: 'red_card' })), 'publicTimeline.event.redCard');
  assert.equal(
    timelineEventKey(event({ event_type: 'red_card', red_card_type: 'direct_red' })),
    'publicTimeline.event.directRed',
  );
  assert.equal(
    timelineEventKey(event({ event_type: 'red_card', red_card_type: 'double_yellow_red' })),
    'publicTimeline.event.doubleYellowRed',
  );
});

test('nombre público solo con nombre y apellido', () => {
  assert.equal(timelinePlayerName({ player_id: 'p', first_name: ' Ana ', last_name: 'López' }), 'Ana López');
  assert.equal(timelinePlayerName(null), '');
});

test('lado del equipo del hecho', () => {
  const teams = { home_team_id: 'home', away_team_id: 'away' };
  assert.equal(timelineEventSide(event(), teams), 'home');
  assert.equal(timelineEventSide(event({ team_id: 'away' }), teams), 'away');
  assert.equal(timelineEventSide(event({ team_id: 'other' }), teams), null);
});

test('un solo segmento no muestra separador', () => {
  const groups = timelineGroups({ segment_numbers: [1], events: [event(), event({ minute: 30 })] });
  assert.equal(groups.length, 1);
  assert.equal(groups[0].showSeparator, false);
  assert.deepEqual(groups[0].events.map((e) => e.minute), [10, 30]);
});

test('varios segmentos muestran separador y omiten los vacíos', () => {
  const groups = timelineGroups({
    segment_numbers: [1, 2, 3],
    events: [event({ minute: 5 }), event({ segment_number: 3, minute: 95 })],
  });
  assert.deepEqual(groups.map((g) => [g.segmentNumber, g.showSeparator, g.events.length]), [
    [1, true, 1],
    [3, true, 1],
  ]);
});

test('sin hechos no hay grupos', () => {
  assert.deepEqual(timelineGroups({ segment_numbers: [1, 2], events: [] }), []);
});

test('recarga solo si cambia estado, marcador, penales o rectificación', () => {
  assert.equal(shouldReloadTimeline(match, { ...match }), false);
  assert.equal(shouldReloadTimeline(match, { ...match, home_score: 2 }), true);
  assert.equal(shouldReloadTimeline(match, { ...match, away_score: 1 }), true);
  assert.equal(shouldReloadTimeline(match, { ...match, home_penalties: 4 }), true);
  assert.equal(shouldReloadTimeline(match, { ...match, status: 'administrative_resolution' }), true);
  assert.equal(shouldReloadTimeline(match, { ...match, rectified_at: '2026-11-15T10:00:00Z' }), true);
  assert.equal(shouldReloadTimeline(match, null), true);
  assert.equal(shouldReloadTimeline(null, null), false);
});

const component = readFileSync(new URL('../app/components/public/PublicMatchTimeline.vue', import.meta.url), 'utf8');
const i18n = readFileSync(new URL('../app/composables/useI18n.ts', import.meta.url), 'utf8');
const TIMELINE_KEYS = [
  'public.viewTimeline',
  'publicTimeline.title',
  'publicTimeline.loading',
  'publicTimeline.error',
  'publicTimeline.retry',
  'publicTimeline.pending',
  'publicTimeline.notPlayed',
  'publicTimeline.empty',
  'publicTimeline.scoreMismatch',
  'publicTimeline.playerOut',
  'publicTimeline.playerIn',
  'publicTimeline.event.goal',
  'publicTimeline.event.penaltyGoal',
  'publicTimeline.event.ownGoal',
  'publicTimeline.event.yellowCard',
  'publicTimeline.event.redCard',
  'publicTimeline.event.directRed',
  'publicTimeline.event.doubleYellowRed',
  'publicTimeline.event.substitution',
];

test('el diálogo es modal accesible con título, cierre enfocado y foco devuelto', () => {
  assert.match(component, /<dialog[\s\S]*aria-modal="true"[\s\S]*:aria-labelledby="titleId"/);
  assert.match(component, /showModal\(\)/);
  assert.match(component, /@cancel="handleCancel"/);
  assert.match(component, /autofocus[\s\S]*:aria-label="t\('common\.close'\)"/);
  assert.match(component, /previousFocus\.value\?\.focus\?\.\(\)/);
  assert.match(component, /role="status"/);
  assert.match(component, /role="alert"/);
  assert.match(component, /aria-hidden="true"/);
});

test('el componente distingue carga, error, pendiente, sin juego, vacío y descuadre', () => {
  for (const key of ['loading', 'error', 'retry', 'pending', 'notPlayed', 'empty', 'scoreMismatch']) {
    assert.match(component, new RegExp(`publicTimeline\\.${key}`), key);
  }
  assert.match(component, /emit\('retry'\)/);
});

test('el componente nunca muestra dorsal, foto ni asistencia', () => {
  assert.doesNotMatch(component, /dorsal|photo|assist|metadata/);
});

test('cada clave de la cronología existe en ES y EN', () => {
  const [es, en] = i18n.split(/\n {2}en: \{/);
  for (const key of TIMELINE_KEYS) {
    assert.match(es!, new RegExp(`'${key.replace(/\./g, '\\.')}': '`), `es ${key}`);
    assert.match(en!, new RegExp(`'${key.replace(/\./g, '\\.')}': '`), `en ${key}`);
  }
});

const page = readFileSync(new URL('../app/pages/tournaments/[id].vue', import.meta.url), 'utf8');

test('la página ofrece la cronología solo en partidos finished, junto a la alineación', () => {
  const triggers = page.match(/v-if="canOpenTimeline\(match\)"/g) ?? [];
  const lineupTriggers = page.match(/v-if="matchLineup\(match\)"/g) ?? [];
  assert.equal(triggers.length, lineupTriggers.length);
  assert.ok(triggers.length > 0);
  assert.match(page, /aria-controls="public-timeline-dialog"/);
  assert.match(page, /if \(isSuspendedPublicMatch\(match\) \|\| !canOpenTimeline\(match\)\) return;/);
});

test('la página carga la cronología bajo demanda mediante useApi', () => {
  assert.match(page, /const \{ request \} = useApi\(\);/);
  assert.match(page, /request<PublicMatchTimelineData>\(`\/tournaments\/public\/\$\{tournamentId\}\/matches\/\$\{matchId\}\/timeline`\)/);
  assert.doesNotMatch(page, /\$fetch\(|fetch\(`/);
  assert.match(page, /<PublicMatchTimeline[\s\S]*@retry="loadTimeline"/);
});

test('el diálogo abierto se recarga con el refresco público, sin evento nuevo', () => {
  assert.match(page, /shouldReloadTimeline\(previous, next\)\) void loadTimeline\(\)/);
  for (const field of ['status', 'home_score', 'away_score', 'rectified_at']) {
    assert.match(page, new RegExp(`${field}: match\\.${field}`), field);
  }
  assert.match(page, /\['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'\]/);
  assert.doesNotMatch(page, /TIMELINE_UPDATED|MATCH_TIMELINE/);
});
