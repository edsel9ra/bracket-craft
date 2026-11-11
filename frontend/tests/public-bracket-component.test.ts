import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path: string) => readFileSync(new URL('../app/'+path, import.meta.url), 'utf8');

test('bracket composes pure inference and measured layout, retains lineup and accessible winner', () => {
  const source = read('components/public/PublicBracket.vue');
  for (const symbol of ['groupPublicRounds', 'inferPublicAdvances', 'publicRoundLabel', 'usePublicBracketLayout', 'PublicBracketConnections', 'HorizontalScroll']) assert.ok(source.includes(symbol), symbol);
  assert.match(source, /public\.winner/);
  assert.match(source, /public\.fromMatch/);
  assert.match(source, /public\.connectionsHint/);
  assert.match(source, /emit\('openLineup', match, \$event\)/);
  assert.doesNotMatch(source, /translateY\(-2px\)/);
});

test('SVG is decorative, not a focus or pointer target; measures have cleanup and no HTTP', () => {
  const svg = read('components/public/PublicBracketConnections.vue');
  assert.match(svg, /aria-hidden="true"/);
  assert.match(svg, /focusable="false"/);
  assert.match(svg, /pointer-events:\s*none/);
  const adapter = read('composables/usePublicBracketLayout.ts');
  for (const symbol of ['ResizeObserver', 'onBeforeUnmount', 'disconnect', 'cancelAnimationFrame', 'layoutPublicBracket', 'fonts.ready']) assert.ok(adapter.includes(symbol), symbol);
  assert.doesNotMatch(svg+adapter, /\bfetch\(|\$fetch\(|useApi\(|Date\.now\(/);
});

test('new bracket text exists in both languages', () => {
  const i18n = read('composables/useI18n.ts');
  for (const key of ['public.final', 'public.semifinals', 'public.quarterfinals', 'public.roundOf16', 'public.fromMatch', 'public.connectionsHint', 'public.winner']) {
    assert.equal(i18n.split(`'${key}':`).length-1, 2, key);
  }
});
