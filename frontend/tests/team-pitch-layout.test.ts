import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parse } from 'vue/compiler-sfc';

const source = readFileSync(new URL('../app/components/public/TeamPitch.vue', import.meta.url), 'utf8');
const { descriptor } = parse(source);
const css = descriptor.styles.map((style) => style.content).join('\n');

test('photos and fallback initials share the same container-relative square', () => {
  assert.match(css, /\.team-pitch\s*\{[^}]*container-type:\s*inline-size/);
  const avatar = css.match(/\.pitch-player img,\s*\.player-avatar\s*\{([^}]+)\}/)?.[1];
  assert.ok(avatar);
  const width = avatar.match(/\bwidth:\s*(clamp\([^;]+\))/)?.[1];
  const height = avatar.match(/\bheight:\s*(clamp\([^;]+\))/)?.[1];
  assert.ok(width?.includes('cqw'));
  assert.equal(width, height);
  assert.match(avatar, /place-items:\s*center/);
  assert.match(descriptor.template?.content ?? '', /:alt="playerName\(player\)"/);
});

test('player labels stay within their marker and the number does not overlap the photo', () => {
  assert.match(css, /grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.doesNotMatch(css, /margin-top:\s*-/);
  assert.match(css, /\.pitch-player \.player-name\s*\{[^}]*max-width:\s*100%/);
  assert.match(css, /\.player-position\s*\{[^}]*white-space:\s*nowrap/);
});
