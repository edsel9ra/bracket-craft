import assert from 'node:assert/strict';
import test from 'node:test';

import {
  formatDate,
  formatDateTime,
  formatNumber,
  localeTag,
} from '../app/utils/format.ts';

// RF-030: los datos no se traducen, pero las fechas y los números que los
// acompañan se formatean con `Intl` según el idioma activo. La función es pura
// (recibe el valor y el idioma) y es la única que elige la etiqueta regional,
// de modo que todas las pantallas formatean igual.

const MATCH_DATE = new Date(2026, 9, 23, 18, 30);

test('maps each supported language to its regional tag', () => {
  assert.equal(localeTag('es'), 'es-CO');
  assert.equal(localeTag('en'), 'en-US');
});

test('formats a match date and time according to the active language', () => {
  assert.equal(
    formatDateTime(MATCH_DATE, 'es'),
    new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium', timeStyle: 'short' }).format(MATCH_DATE),
  );
  assert.equal(
    formatDateTime(MATCH_DATE, 'en'),
    new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(MATCH_DATE),
  );
  assert.match(formatDateTime(MATCH_DATE, 'es'), /23\/10\/2026/);
  assert.match(formatDateTime(MATCH_DATE, 'en'), /Oct 23, 2026/);
  assert.notEqual(formatDateTime(MATCH_DATE, 'es'), formatDateTime(MATCH_DATE, 'en'));
});

test('formats a date without time according to the active language', () => {
  assert.equal(
    formatDate(MATCH_DATE, 'es'),
    new Intl.DateTimeFormat('es-CO', { dateStyle: 'medium' }).format(MATCH_DATE),
  );
  assert.equal(
    formatDate(MATCH_DATE, 'en'),
    new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(MATCH_DATE),
  );
  assert.match(formatDate(MATCH_DATE, 'es'), /23\/10\/2026/);
  assert.match(formatDate(MATCH_DATE, 'en'), /Oct 23, 2026/);
});

test('formats numbers according to the active language', () => {
  assert.equal(formatNumber(1234.5, 'es'), '1.234,5');
  assert.equal(formatNumber(1234.5, 'en'), '1,234.5');
  assert.equal(formatNumber(12345, 'es', { maximumFractionDigits: 0 }), '12.345');
  assert.equal(formatNumber(12345, 'en', { maximumFractionDigits: 0 }), '12,345');
});

test('falls back to Spanish for an unknown language and returns empty for missing values', () => {
  assert.equal(localeTag('fr'), 'es-CO');
  assert.equal(localeTag(null), 'es-CO');
  assert.equal(formatDateTime(null, 'en'), '');
  assert.equal(formatDateTime('not-a-date', 'en'), '');
  assert.equal(formatDate(undefined, 'es'), '');
  assert.equal(formatNumber(Number.NaN, 'en'), '');
  assert.equal(formatNumber(null, 'es'), '');
});
