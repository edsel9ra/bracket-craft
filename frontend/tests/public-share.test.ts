import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { runShare, shareStrategy, type ShareNavigator } from '../app/utils/publicShare.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const payload = { title: 'Copa', url: 'https://torneos.example.org/tournaments/1' };

function navigator(options: { share?: () => Promise<void>; write?: (text: string) => Promise<void> }): ShareNavigator & { copied: string[] } {
  const copied: string[] = [];
  return {
    copied,
    share: options.share,
    clipboard: options.write ? { writeText: async (text: string) => { await options.write!(text); copied.push(text); } } : undefined,
  };
}

test('shareStrategy elige hoja nativa, portapapeles o copia manual (RF-011)', () => {
  assert.equal(shareStrategy({ share: async () => {}, clipboard: { writeText: async () => {} } }), 'native');
  assert.equal(shareStrategy({ clipboard: { writeText: async () => {} } }), 'clipboard');
  assert.equal(shareStrategy({}), 'manual');
  assert.equal(shareStrategy(undefined), 'manual');
});

test('runShare usa la hoja nativa con título y enlace', async () => {
  let received: unknown;
  const nav: ShareNavigator = { share: async (data) => { received = data; } };
  assert.equal(await runShare(payload, nav), 'shared');
  assert.deepEqual(received, payload);
});

test('cancelar la hoja nativa no es un error ni copia nada', async () => {
  const nav = navigator({
    share: async () => { throw new DOMException('cancel', 'AbortError'); },
    write: async () => {},
  });
  assert.equal(await runShare(payload, nav), 'cancelled');
  assert.deepEqual(nav.copied, []);
});

test('si la hoja nativa falla o no existe, copia el enlace', async () => {
  const failing = navigator({ share: async () => { throw new DOMException('denied', 'NotAllowedError'); }, write: async () => {} });
  assert.equal(await runShare(payload, failing), 'copied');
  assert.deepEqual(failing.copied, [payload.url]);
  const clipboardOnly = navigator({ write: async () => {} });
  assert.equal(await runShare(payload, clipboardOnly), 'copied');
});

test('si la copia también falla, ofrece la copia manual', async () => {
  assert.equal(await runShare(payload, navigator({ write: async () => { throw new Error('denied'); } })), 'manual');
  assert.equal(await runShare(payload, {}), 'manual');
  assert.equal(await runShare(payload, undefined), 'manual');
});

const button = read('components/public/PublicShareButton.vue');

test('PublicShareButton anuncia el resultado y ofrece copia manual accesible (RNF-005)', () => {
  assert.match(button, /import Button from '~\/components\/ui\/Button\.vue';/);
  assert.match(button, /runShare\(\{ title: props\.title, url: props\.url \}, import\.meta\.client \? window\.navigator : undefined\)/);
  assert.match(button, /aria-live="polite"/);
  assert.match(button, /<input[\s\S]*?readonly[\s\S]*?:value="url"/);
  assert.match(button, /<label :for="fieldId">\{\{ t\('share\.manualLabel'\) \}\}<\/label>/);
  assert.match(button, /field\.value\?\.select\(\)/);
  assert.match(button, /:busy="busy"/);
  assert.match(button, /\{\{ label \}\}/);
  assert.doesNotMatch(button, /aria-label=/);
});

test('el botón está en torneo, cronología y ficha con nombres propios (RF-011)', () => {
  const tournament = read('pages/tournaments/[id].vue');
  const player = read('pages/players/[id].vue');
  const timeline = read('components/public/PublicMatchTimeline.vue');
  assert.match(tournament, /<PublicShareButton[\s\S]*?:label="t\('share\.tournament'\)"[\s\S]*?:url="tournamentShareUrl"/);
  assert.match(tournament, /:share-url="timelineShareUrl"/);
  assert.match(tournament, /isShareableResult\(match\) \? absoluteUrl\(config\.public\.siteUrl, `\/tournaments\/\$\{tournamentId\}\?match=\$\{match\.id\}`\) : null/);
  assert.match(timeline, /<PublicShareButton[\s\S]*?v-if="shareUrl"[\s\S]*?:label="t\('share\.result'\)"/);
  assert.match(player, /<PublicShareButton[\s\S]*?:label="t\('share\.player'\)"[\s\S]*?:url="absoluteUrl\(config\.public\.siteUrl, `\/players\/\$\{playerId\}`\)"/);
});

test('los textos de compartir existen en español e inglés (RF-014)', () => {
  const [es, en] = read('composables/useI18n.ts').split(/\n {2}en: \{\n/);
  for (const key of ['share.tournament', 'share.result', 'share.player', 'share.shared', 'share.copied', 'share.manual', 'share.manualLabel']) {
    assert.match(es!, new RegExp(`'${key.replace(/\./g, '\\.')}': '`), `es ${key}`);
    assert.match(en!, new RegExp(`'${key.replace(/\./g, '\\.')}': '`), `en ${key}`);
  }
});
