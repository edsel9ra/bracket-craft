import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileStyle } from 'vue/compiler-sfc';
import { ISLAND_PALETTES, PALETTE_LIGHT, contrastRatio } from '../app/utils/designTokens.ts';

const read = (name: string) => readFileSync(new URL(`../app/components/public/${name}.vue`, import.meta.url), 'utf8');

test('both pitches confine light foreground and player-surface overrides to the green island', () => {
  for (const name of ['MatchPitch', 'TeamPitch']) {
    const source = read(name);
    const css = compileStyle({ source: source.match(/<style[^>]*>([\s\S]*?)<\/style>/)![1]!, filename: name, id: 'data-v-theme', scoped: true }).code;
    assert.match(css, /:root\[data-theme="light"\] \.pitch\[data-v-theme\]/);
    assert.match(source, /:root\[data-theme="light"\] \.pitch/);
    assert.match(source, /@media \(prefers-color-scheme: light\)/);
    assert.match(source, /:root\[data-theme="system"\] \.pitch/);
    for (const role of ['ink', 'accent', 'warning']) assert.match(source, new RegExp(`--color-${role}: var\\(--color-island-${role}\\)`));
    assert.match(source, /--color-canvas: var\(--color-pitch-player\)/);
    assert.match(source, /--color-surface: var\(--color-pitch-player\)/);
    assert.match(source, /--color-accent-ink: var\(--color-pitch-player\)/);
    assert.match(source, /repeating-linear-gradient\(90deg, var\(--color-pitch-grass\)/);
    assert.doesNotMatch(source, /filter:\s*(?:invert|hue-rotate|grayscale)/);
  }
});

test('visitor light amber remains legible on both green stripes without changing dark or bracket currentColor', () => {
  assert.equal(ISLAND_PALETTES.light.warning, '#ffd18a');
  assert.equal(ISLAND_PALETTES.dark.warning, '#ffcb7a');
  for (const background of [PALETTE_LIGHT['pitch-grass'], PALETTE_LIGHT['pitch-stripe'], PALETTE_LIGHT['pitch-player']]) {
    for (const foreground of Object.values(ISLAND_PALETTES.light)) assert.ok(contrastRatio(foreground, background) >= 4.5);
  }
  assert.match(read('PublicBracketConnections'), /stroke:\s*currentColor/);
});
