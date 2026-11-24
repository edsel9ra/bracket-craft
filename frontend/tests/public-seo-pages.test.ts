import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const home = read('pages/index.vue');
const tournament = read('pages/tournaments/[id].vue');
const player = read('pages/players/[id].vue');
const i18n = read('composables/useI18n.ts');

function contextFrom(page: string) {
  assert.match(page, /seoContext\(config\.public\.siteUrl, config\.public\.apiBase, locale\.value\)/);
  assert.doesNotMatch(page, /useRequestURL|useRequestHeaders|location\.origin|window\.location/);
}

test('inicio usa homeHead con el origen configurado (RF-002, RF-012)', () => {
  contextFrom(home);
  assert.match(home, /useHead\(\(\) => homeHead\(/);
  assert.match(home, /imageAlt: t\('seo\.brandImageAlt'\)/);
});

test('torneo usa tournamentHead y, con ?match= compartible, resultHead (RF-001, RF-006, RF-007)', () => {
  contextFrom(tournament);
  assert.match(tournament, /const sharedMatchId = parseMatchQuery\(route\.query\.match\);/);
  assert.match(tournament, /request<PublicMatchState>\(`\/tournaments\/public\/\$\{tournamentId\}\/matches\/\$\{sharedMatchId\}`\)\.catch\(\(\) => null\)/);
  assert.match(tournament, /isShareableResult\(match\)/);
  assert.match(tournament, /resultHead\(ctx, tournamentId, match\.id, \{/);
  assert.match(tournament, /tournamentHead\(ctx, tournamentId, \{/);
  assert.match(tournament, /title: resultTitle\(match, current\.name\)/);
  assert.doesNotMatch(tournament, /y resultados públicos de/);
});

test('el enlace de partido abre la cronología tras hidratar y cerrarla limpia la URL (RF-006)', () => {
  assert.match(tournament, /onMounted\(\(\) => \{[\s\S]*?openSharedTimeline\(\);/);
  assert.match(tournament, /function openSharedTimeline\(\) \{\n {2}const match = sharedMatch\.value;\n {2}if \(!match \|\| isSuspendedPublicMatch\(match\) \|\| !isShareableResult\(match\)\) return;\n {2}showTimeline\(match, null\);/);
  assert.match(tournament, /if \(route\.query\.match !== undefined\) \{\n {4}sharedMatchDismissed\.value = true;\n {4}void router\.replace\(\{ query: withoutMatchQuery\(route\.query\) \}\);/);
  assert.match(tournament, /\(trigger \?\? tournamentHeading\.value\)\?\.focus\(\)/);
  assert.match(tournament, /<h1 ref="tournamentHeading" tabindex="-1">\{\{ tournament\.name \}\}<\/h1>/);
});

test('la ficha usa playerHead sin foto y con el torneo más reciente (RF-008)', () => {
  contextFrom(player);
  assert.match(player, /playerHead\(ctx, playerId, \{/);
  assert.match(player, /profile\.value\?\.tournaments\[0\]\?\.tournament_name/);
  assert.match(player, /imageAlt: t\('seo\.brandImageAlt'\)/);
  assert.match(player, /meta: \[\{ name: 'robots', content: 'noindex, nofollow' \}\]/);
  const headBlock = player.slice(player.indexOf('useHead('));
  assert.doesNotMatch(headBlock.slice(0, headBlock.indexOf('</script>')), /photo/);
});

test('los textos SEO existen en español e inglés (RF-014)', () => {
  const [es, en] = i18n.split(/\n {2}en: \{\n/);
  for (const key of ['seo.brandImageAlt', 'seo.tournamentDescription', 'seo.tournamentImageAlt', 'seo.resultDescription', 'seo.resultImageAlt', 'seo.playerDescription', 'seo.playerDescriptionNoTournament']) {
    assert.match(es!, new RegExp(`'${key.replace(/\./g, '\\.')}': '`), `es ${key}`);
    assert.match(en!, new RegExp(`'${key.replace(/\./g, '\\.')}': '`), `en ${key}`);
  }
});
