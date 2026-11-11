import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { placeFloatingTheme } from '../app/utils/floatingPreferences.ts';

const language = { x: 264, y: 791, width: 99, height: 41 };
const theme = { width: 142, height: 41 };
const viewport = { width: 375, height: 844 };

test('floating gaps pass pointer events through while both preference controls remain interactive', () => {
  const source = readFileSync(new URL('../app/components/PublicPreferences.vue', import.meta.url), 'utf8');
  assert.match(source, /\.public-preferences\s*\{[^}]*pointer-events:\s*none/);
  assert.match(source, /\.public-preferences\s*:deep\(\.theme-switcher\),\s*\.public-preferences\s*:deep\(\.language-switcher\)\s*\{[^}]*pointer-events:\s*auto/);
});

test('public placement resamples font and motion completion and cleans up motion listeners', () => {
  const source = readFileSync(new URL('../app/components/PublicPreferences.vue', import.meta.url), 'utf8');
  assert.match(source, /document.fonts.ready.then\(schedule\)/);
  assert.match(source, /animationend.*animationcancel.*transitionend.*transitioncancel/);
  assert.match(source, /pointerover.*pointerout/);
  assert.match(source, /removeEventListener\(event, schedule, true\)/);
  assert.match(source, /!root.isConnected/);
});

test('public preferences stay horizontal when unobstructed, otherwise stack upwards in free space', () => {
  assert.deepEqual(placeFloatingTheme(language, theme, viewport, [], 12), { direction: 'row', gap: 8 });
  const domSize = Object.create({ width: 142, height: 41 }) as typeof theme;
  assert.deepEqual(placeFloatingTheme(language, domSize, viewport, [], 12), { direction: 'row', gap: 8 });
  const rowBlocker = { x: 114, y: 791, width: 142, height: 41 };
  assert.deepEqual(placeFloatingTheme(language, theme, viewport, [rowBlocker], 12), { direction: 'column', gap: 8 });
  const stackedBlocker = { x: 221, y: 742, width: 142, height: 41 };
  assert.deepEqual(placeFloatingTheme(language, theme, viewport, [rowBlocker, stackedBlocker], 12), { direction: 'column', gap: 52 });
});

test('touching edges do not overlap, narrow viewports stack and fully obstructed viewports have no placement', () => {
  assert.deepEqual(placeFloatingTheme(language, theme, viewport, [{ x: 114, y: 750, width: 142, height: 41 }], 12), { direction: 'row', gap: 8 });
  assert.deepEqual(placeFloatingTheme({ ...language, x: 100 }, theme, viewport, [], 12), { direction: 'column', gap: 8 });
  assert.equal(placeFloatingTheme(language, theme, viewport, [{ x: 0, y: 0, width: 375, height: 844 }], 12), null);
  assert.equal(placeFloatingTheme(language, { width: 500, height: 41 }, viewport, [], 12), null);
});

test('compact centered desktop preferences clear card padding without covering detail text', () => {
  const desktopLanguage = { x: 1253.28125, y: 839, width: 151.71875, height: 41 };
  const compact = { width: 137.953125, height: 33 };
  const desktop = { width: 1425, height: 900 };
  const card = { x: 917.1640625, y: 876.890625, width: 385.3359375, height: 150 };
  assert.deepEqual(placeFloatingTheme(desktopLanguage, compact, desktop, [card], 20, true), { direction: 'row', gap: 8 });
  const label = { x: 1231.0859375, y: 855.359375, width: 37.4140625, height: 12 };
  assert.deepEqual(placeFloatingTheme(desktopLanguage, compact, desktop, [label], 20, true), { direction: 'column', gap: 8 });
});

test('dense tablet preferences stay above a card without increasing the floating group', () => {
  const language = { x: 613.28125, y: 839, width: 151.71875, height: 41 };
  const theme = { width: 137.953125, height: 25 };
  const card = { x: 524.6640625, y: 820.015625, width: 240.328125, height: 169.3984375 };
  assert.deepEqual(placeFloatingTheme(language, theme, { width: 785, height: 900 }, [card], 20), { direction: 'column', gap: 20 });
  const source = readFileSync(new URL('../app/components/PublicPreferences.vue', import.meta.url), 'utf8');
  assert.match(source, /@media \(min-width: 480px\) and \(max-width: 1280px\)/);
  assert.match(source, /padding: 0 var\(--space-2\)/);
});

test('placement rejects non-finite or non-positive dimensions without mutating inputs', () => {
  const snapshot = structuredClone(language);
  assert.throws(() => placeFloatingTheme(language, { width: 0, height: 41 }, viewport, [], 12), RangeError);
  assert.throws(() => placeFloatingTheme(language, theme, { width: NaN, height: 844 }, [], 12), RangeError);
  placeFloatingTheme(language, theme, viewport, [], 12);
  assert.deepEqual(language, snapshot);
});
