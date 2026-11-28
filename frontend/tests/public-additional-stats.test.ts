// Spec 052 T7 (RF-001–RF-004, RNF-004): minutos, posición principal y penales atajados en el sitio público.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { MAIN_POSITION_LABEL_KEYS, PROFILE_STAT_FIELDS, mainPositionLabel } from '../app/utils/publicPlayerProfile.ts';

const source = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');

test('la ficha suma minutos y penales atajados a las cifras de la 022', () => {
  const keys = PROFILE_STAT_FIELDS.map((field) => field.key);
  assert.deepEqual(keys.slice(-2), ['minutes_played', 'penalties_saved']);
  assert.deepEqual(PROFILE_STAT_FIELDS.slice(-2).map((field) => field.label), ['public.minutesPlayed', 'public.penaltiesSaved']);
});

test('la posición principal se traduce por línea y una ausente se muestra como guion', () => {
  assert.deepEqual(MAIN_POSITION_LABEL_KEYS, {
    goalkeeper: 'public.mainLine.goalkeeper',
    defender: 'public.mainLine.defender',
    midfielder: 'public.mainLine.midfielder',
    forward: 'public.mainLine.forward',
  });
  const t = (key: string) => `T(${key})`;
  assert.equal(mainPositionLabel('defender', t), 'T(public.mainLine.defender)');
  assert.equal(mainPositionLabel(null, t), '—');
  assert.equal(mainPositionLabel(undefined, t), '—');
  assert.equal(mainPositionLabel('libero', t), '—');
});

test('la tabla y la ficha muestran los tres datos', () => {
  const table = source('components/public/PublicPlayerStatsTable.vue');
  for (const pattern of [/row\.minutes_played/, /row\.penalties_saved/, /mainPositionLabel\(row\.main_position/, /t\('public\.minutesPlayed'\)/, /t\('public\.mainPosition'\)/, /t\('public\.penaltiesSaved'\)/, /t\('public\.minutesDefinition'\)/]) {
    assert.match(table, pattern);
  }
  const page = source('pages/players/[id].vue');
  assert.match(page, /mainPositionLabel\(row\.main_position/);
  assert.match(page, /t\('public\.mainPosition'\)/);
});

test('los textos nuevos existen una vez en ES y otra en EN', () => {
  const i18n = source('composables/useI18n.ts');
  for (const key of ['public.minutesPlayed', 'public.mainPosition', 'public.penaltiesSaved', 'public.minutesDefinition', ...Object.values(MAIN_POSITION_LABEL_KEYS)]) {
    assert.equal(i18n.split(`'${key}':`).length - 1, 2, key);
  }
});
