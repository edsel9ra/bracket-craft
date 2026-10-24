import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  findMinutesOutside,
  minutesLimits,
  type MinutesChangeSubject,
} from '../app/utils/rulesMinutes.ts';
import {
  DEFAULT_RULES_CONFIG,
  cloneRulesConfig,
  type RulesConfig,
} from '../app/utils/rulesConfig.ts';
import type {
  ResolutionDraftEventInput,
  ResolutionSegmentInput,
} from '../app/utils/matchResolution.ts';

const configurationPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
  'utf8',
);
const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function rulesConfig(options: {
  regular?: number;
  extraEnabled?: boolean;
  extra?: number;
} = {}): RulesConfig {
  const config = cloneRulesConfig(DEFAULT_RULES_CONFIG);
  config.stage_defaults.regular_time_minutes = options.regular ?? 90;
  config.stage_defaults.extra_time_enabled = options.extraEnabled ?? true;
  config.stage_defaults.extra_time_minutes = options.extra ?? 120;
  return config;
}

function subject(input: {
  matchId?: string;
  previous: RulesConfig;
  next: RulesConfig;
  segments?: ResolutionSegmentInput[];
  draftEvents?: ResolutionDraftEventInput[];
}): MinutesChangeSubject {
  return {
    matchId: input.matchId ?? 'match-1',
    previous: minutesLimits(input.previous, 'stage-1'),
    next: minutesLimits(input.next, 'stage-1'),
    segments: input.segments ?? [],
    draftEvents: input.draftEvents ?? [],
  };
}

function catalogCount(key: string): number {
  return translations.split(`'${key}':`).length - 1;
}

// RF-035: un cambio de minutos en un borrador avisa si deja segmentos ya
// persistidos fuera del nuevo máximo. No los corrige, no los borra y no los
// reescribe: solo describe el impacto antes de guardar.
test('reports persisted segments that fall outside the new maximum before saving', () => {
  const segments: ResolutionSegmentInput[] = [
    { id: 'seg-1', segment_number: 1, minute_start: 0, minute_end: 45, status: 'completed' },
    { id: 'seg-2', segment_number: 2, minute_start: 45, minute_end: 85, status: 'active' },
  ];
  const before = JSON.parse(JSON.stringify(segments)) as ResolutionSegmentInput[];

  const impact = findMinutesOutside([
    subject({ previous: rulesConfig({ regular: 90 }), next: rulesConfig({ regular: 80 }), segments }),
  ]);

  assert.equal(impact.segments.length, 1);
  assert.equal(impact.events.length, 0);
  assert.deepEqual(impact.segments[0], {
    matchId: 'match-1',
    index: 1,
    minute: 85,
    addedMinute: 0,
    over: 5,
    max: 80,
    resolution: 'regular',
  });
  assert.equal(impact.maxMinute, 80);
  assert.deepEqual(impact.matchIds, ['match-1']);
  assert.deepEqual(segments, before, 'the persisted segments must not be rewritten');
});

// RF-035: los eventos del borrador solo se avisan. El guardado de reglas no se
// bloquea por ellos y la función no toca la lista.
test('reports draft events without deleting or rewriting them', () => {
  const draftEvents: ResolutionDraftEventInput[] = [
    { client_event_id: 'ev-1', event_type: 'goal', minute: 82, added_minute: 0 },
    { client_event_id: 'ev-2', event_type: 'yellow_card', minute: 60, added_minute: 0 },
  ];
  const before = JSON.parse(JSON.stringify(draftEvents)) as ResolutionDraftEventInput[];

  const impact = findMinutesOutside([
    subject({ previous: rulesConfig({ regular: 90 }), next: rulesConfig({ regular: 80 }), draftEvents }),
  ]);

  assert.equal(impact.segments.length, 0);
  assert.equal(impact.events.length, 1);
  assert.equal(impact.events[0]?.minute, 82);
  assert.equal(impact.events[0]?.over, 2);
  assert.deepEqual(draftEvents, before, 'the draft events must not be deleted');
});

// RF-035: sin reducción real del máximo no hay aviso, aunque haya registros
// por encima del reglamentario dentro de un máximo con prórroga vigente.
test('warns only when the effective maximum is reduced', () => {
  const segment: ResolutionSegmentInput = {
    id: 'seg-1',
    segment_number: 1,
    minute_start: 0,
    minute_end: 100,
    status: 'completed',
  };

  const same = findMinutesOutside([
    subject({ previous: rulesConfig({ regular: 90, extra: 120 }), next: rulesConfig({ regular: 90, extra: 120 }), segments: [segment] }),
  ]);
  assert.equal(same.segments.length, 0);

  const increased = findMinutesOutside([
    subject({ previous: rulesConfig({ regular: 90, extra: 120 }), next: rulesConfig({ regular: 95, extra: 120 }), segments: [segment] }),
  ]);
  assert.equal(increased.segments.length, 0);
});

// RF-035: deshabilitar la prórroga reduce el máximo efectivo y avisa de los
// registros que antes cabían en el máximo con prórroga.
test('warns when extra time is disabled and records exceed the regulation maximum', () => {
  const impact = findMinutesOutside([
    subject({
      previous: rulesConfig({ regular: 90, extraEnabled: true, extra: 120 }),
      next: rulesConfig({ regular: 90, extraEnabled: false, extra: 120 }),
      segments: [{ id: 'seg-1', segment_number: 1, minute_start: 90, minute_end: 110, status: 'completed' }],
      draftEvents: [{ client_event_id: 'ev-1', event_type: 'goal', minute: 109, added_minute: 1 }],
    }),
  ]);

  assert.equal(impact.segments.length, 1);
  assert.equal(impact.segments[0]?.max, 90);
  assert.equal(impact.segments[0]?.over, 20);
  assert.equal(impact.events.length, 1);
  assert.equal(impact.events[0]?.max, 90);
  assert.equal(impact.events[0]?.over, 19);
});

// RF-035: con la prórroga todavía habilitada, un registro por encima del nuevo
// máximo con prórroga se informa contra ese máximo, no contra el reglamentario.
test('reports the maximum of the resolution the record exceeds', () => {
  const impact = findMinutesOutside([
    subject({
      previous: rulesConfig({ regular: 90, extraEnabled: true, extra: 120 }),
      next: rulesConfig({ regular: 90, extraEnabled: true, extra: 100 }),
      segments: [{ id: 'seg-1', segment_number: 1, minute_start: 80, minute_end: 110, status: 'completed' }],
    }),
  ]);

  assert.equal(impact.segments.length, 1);
  assert.equal(impact.segments[0]?.max, 100);
  assert.equal(impact.segments[0]?.over, 10);
  assert.equal(impact.segments[0]?.resolution, 'extra_time');
  assert.equal(impact.maxMinute, 100);
});

// RF-035: el impacto se agrega por partido en el orden recibido y sin duplicar
// identificadores.
test('aggregates several matches with a deterministic order', () => {
  const impact = findMinutesOutside([
    subject({
      matchId: 'match-2',
      previous: rulesConfig({ regular: 90 }),
      next: rulesConfig({ regular: 80 }),
      segments: [{ id: 'seg-2', segment_number: 1, minute_start: 0, minute_end: 81 }],
      draftEvents: [{ client_event_id: 'ev-2', event_type: 'goal', minute: 81 }],
    }),
    subject({
      matchId: 'match-1',
      previous: rulesConfig({ regular: 90 }),
      next: rulesConfig({ regular: 75 }),
      segments: [{ id: 'seg-1', segment_number: 1, minute_start: 0, minute_end: 80 }],
    }),
  ]);

  assert.deepEqual(impact.matchIds, ['match-2', 'match-1']);
  assert.deepEqual(impact.segments.map((record) => [record.matchId, record.max]), [
    ['match-2', 80],
    ['match-1', 75],
  ]);
  assert.equal(impact.events.length, 1);
  assert.equal(impact.events[0]?.matchId, 'match-2');
});

// RF-035 / criterio 23: la página comprueba el impacto antes de enviar la
// escritura, avisa sin borrar nada y solo pide confirmación por los segmentos
// persistidos; los eventos del borrador dejan un aviso sin bloquear el guardado.
test('the configuration page warns before saving the new minutes', () => {
  assert.match(configurationPage, /minutesImpactBeforeSave/);
  assert.match(configurationPage, /await minutesImpactBeforeSave\(/);
  assert.match(configurationPage, /findMinutesOutside\(/);
  assert.match(configurationPage, /minutesLimits\(/);
  assert.match(configurationPage, /createMatchDraftStore\(/);
  assert.match(configurationPage, /\/matches\/\$\{match\.id\}\/operation/);
  assert.match(configurationPage, /rules\.minutesWarning\.confirm/);
  assert.match(configurationPage, /rules\.minutesWarning\.events/);
  assert.match(configurationPage, /minutesImpact\.segments\.length/);
  assert.match(configurationPage, /minutesImpact\.events\.length/);
  assert.doesNotMatch(configurationPage, /draftStore\.value\.clear\(\)/, 'the rules save never clears a match draft');
});

// RF-029/RNF-004: los avisos nuevos existen en español y en inglés.
test('declares the minute warnings once per language', () => {
  for (const key of ['rules.minutesWarning.confirm', 'rules.minutesWarning.events']) {
    assert.equal(catalogCount(key), 2, `${key} must exist in both catalogs`);
  }
});
