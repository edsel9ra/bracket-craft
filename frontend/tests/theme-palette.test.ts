import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { PALETTE, PALETTE_DARK, PALETTE_LIGHT, PALETTES, CSS_TOKENS, COLOR_TOKENS_BY_THEME, ISLAND_PALETTES, contrastRatio } from '../app/utils/designTokens.ts';
import { LIGHT_CONTRAST_PAIRS, compositeColor } from '../app/utils/themeContrast.ts';

test('palettes preserve the legacy dark export and mirror each CSS scope', () => {
  assert.equal(PALETTE, PALETTE_DARK);
  assert.equal(PALETTES.dark, PALETTE);
  assert.deepEqual(Object.keys(PALETTE_LIGHT), Object.keys(PALETTE_DARK));
  const css = readFileSync(new URL('../app/assets/css/tokens.css', import.meta.url), 'utf8');
  const declarations = (source: string) => Object.fromEntries([...source.matchAll(/--([\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2]!.trim()]));
  const blocks = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
  assert.deepEqual(declarations(blocks[0]![2]!), CSS_TOKENS);
  for (const theme of ['dark', 'light'] as const) {
    const scope = blocks.find(block => block[1]!.trim().split(/,\s*/).includes(`:root[data-theme="${theme}"]`));
    assert.ok(scope, theme);
    assert.deepEqual(declarations(scope[2]!), COLOR_TOKENS_BY_THEME[theme]);
    if (theme === 'dark') assert.ok(scope[1]!.includes(':root[data-theme="system"]'));
  }
  const system = blocks.find(block => block[1]!.trim() === ':root[data-theme="system"]');
  assert.ok(system);
  assert.deepEqual(declarations(system[2]!), COLOR_TOKENS_BY_THEME.light);
  assert.equal(blocks.length, 4);
  assert.equal(ISLAND_PALETTES.dark.warning, PALETTE_DARK.warning);
  assert.equal(ISLAND_PALETTES.light.warning, '#ffd18a');
});

test('all 158 audited light pairs are calculated and meet their original thresholds', () => {
  assert.equal(LIGHT_CONTRAST_PAIRS.length, 158);
  assert.deepEqual(LIGHT_CONTRAST_PAIRS.map(pair => pair.id), Array.from({ length: 158 }, (_, i) => i + 1));
  assert.equal(LIGHT_CONTRAST_PAIRS.filter(pair => pair.minimum === 4.5).length, 140);
  assert.equal(LIGHT_CONTRAST_PAIRS.filter(pair => pair.minimum === 3).length, 18);
  for (const pair of LIGHT_CONTRAST_PAIRS) {
    assert.ok(contrastRatio(pair.foreground, pair.background) >= pair.minimum, `${pair.id}: ${pair.label}`);
  }
});

test('color composition validates inputs, boundaries and quantizes sRGB channels', () => {
  assert.equal(compositeColor('#ffffff', '#000000', 0), '#000000');
  assert.equal(compositeColor('#ffffff', '#000000', 1), '#ffffff');
  assert.equal(compositeColor('#ffffff', '#000000', 0.5), '#808080');
  assert.throws(() => compositeColor('bad', '#000000', 0.5), TypeError);
  for (const alpha of [-1, 2, NaN, Infinity]) assert.throws(() => compositeColor('#ffffff', '#000000', alpha), RangeError);
});
