import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { CSS_TOKENS, CONTRAST_PAIRS, PALETTE, contrastRatio, nearestStep, BREAKPOINTS, TEXT_SIZES, SPACING, RADII } from '../app/utils/designTokens.ts';

test('CSS and TypeScript declare the same tokens', () => {
  const css = readFileSync(new URL('../app/assets/css/tokens.css', import.meta.url), 'utf8');
  const declarations = Object.fromEntries([...css.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((match) => [match[1], match[2]!.trim()]));
  assert.deepEqual(declarations, CSS_TOKENS);
  assert.deepEqual(Object.values(BREAKPOINTS), [480, 760, 1000, 1280]);
  assert.deepEqual(Object.values(TEXT_SIZES), ['0.6875rem', '0.75rem', '0.8125rem', '0.875rem', '1rem', '1.25rem', 'clamp(1.75rem, 4vw, 2.75rem)', 'clamp(2.5rem, 7vw, 6.5rem)']);
  assert.deepEqual(Object.values(SPACING), [4, 8, 12, 16, 20, 24, 32, 48, 64, 80]);
  assert.deepEqual(Object.values(RADII), [8, 12, 20, 28, 999]);
});

test('semantic text and essential component pairs meet WCAG AA', () => {
  for (const { foreground, background, minimum } of CONTRAST_PAIRS) {
    assert.ok(contrastRatio(PALETTE[foreground], PALETTE[background]) >= minimum, `${foreground}/${background}`);
  }
});

test('contrast calculation validates inputs and uses relative luminance', () => {
  assert.equal(contrastRatio('#000000', '#ffffff'), 21);
  assert.equal(contrastRatio('#ffffff', '#ffffff'), 1);
  assert.equal(contrastRatio('#ffffff', '#000000'), 21);
  assert.throws(() => contrastRatio('invalid', '#ffffff'), TypeError);
});

test('nearestStep handles ties, boundaries and invalid or empty scales', () => {
  assert.equal(nearestStep(10, [4, 8, 12, 16]), 8);
  assert.equal(nearestStep(-1, [4, 8]), 4);
  assert.equal(nearestStep(100, [4, 8]), 8);
  assert.equal(nearestStep(12, [16, 4, 12]), 12);
  assert.throws(() => nearestStep(4, []), RangeError);
  assert.throws(() => nearestStep(NaN, [4]), RangeError);
  assert.throws(() => nearestStep(4, [Infinity]), RangeError);
});
