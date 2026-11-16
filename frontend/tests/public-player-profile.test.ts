import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  PROFILE_STAT_FIELDS,
  isPlayerProfileId,
  playerProfileApiPath,
  playerProfileInitials,
  playerProfileName,
  playerProfilePath,
  profileLinkFor,
  profilePhotoVisible,
} from '../app/utils/publicPlayerProfile.ts';

const PAGE = readFileSync(new URL('../app/pages/players/[id].vue', import.meta.url), 'utf8');
const I18N = readFileSync(new URL('../app/composables/useI18n.ts', import.meta.url), 'utf8');
const ID = '0b6f4d0e-7a7c-4f5e-9a39-3b7a3c1e2d4f';

test('038 RF-001: ruta pública de la ficha y su lectura', () => {
  assert.equal(playerProfilePath(ID), `/players/${ID}`);
  assert.equal(playerProfileApiPath(ID), `/tournaments/public/players/${ID}`);
  assert.equal(isPlayerProfileId(ID), true);
  assert.equal(isPlayerProfileId(ID.toUpperCase()), true);
  for (const bad of ['', 'abc', `${ID}/x`, '../admin', null, undefined, 7]) {
    assert.equal(isPlayerProfileId(bad as never), false, String(bad));
  }
});

test('038 RF-009: solo enlaza con profile_available estrictamente true', () => {
  assert.equal(profileLinkFor({ player_id: ID, profile_available: true }), `/players/${ID}`);
  for (const value of [false, undefined, null, 'true', 1]) {
    assert.equal(profileLinkFor({ player_id: ID, profile_available: value as never }), null, String(value));
  }
  assert.equal(profileLinkFor({ player_id: 'nope', profile_available: true }), null);
  assert.equal(profileLinkFor(null), null);
});

test('038 RF-005/RF-007: nombre, iniciales y foto con caída a iniciales', () => {
  const profile = { first_name: ' Ana ', last_name: 'López', photo_url: 'https://x/p.jpg' };
  assert.equal(playerProfileName(profile), 'Ana López');
  assert.equal(playerProfileInitials(profile), 'AL');
  assert.equal(profilePhotoVisible(profile, null), true);
  assert.equal(profilePhotoVisible(profile, 'https://x/p.jpg'), false);
  assert.equal(profilePhotoVisible(profile, 'https://x/old.jpg'), true);
  assert.equal(profilePhotoVisible({ ...profile, photo_url: null }, null), false);
  assert.equal(profilePhotoVisible({ ...profile, photo_url: '  ' }, null), false);
});

test('038 RF-005: las cinco cifras en orden, sin dorsal ni posición', () => {
  assert.deepEqual(PROFILE_STAT_FIELDS.map((field) => field.key), ['matches_played', 'goals', 'yellow_cards', 'red_cards', 'clean_sheets']);
  assert.deepEqual(PROFILE_STAT_FIELDS.map((field) => field.label), ['public.played', 'public.goals', 'public.yellowCards', 'public.redCards', 'public.cleanSheets']);
  assert.doesNotMatch(PAGE, /dorsal|position_slot|photo_consent|birth|document/);
});

test('038 RF-001/RF-002: la página carga sin sesión vía useApi y distingue no encontrado y error', () => {
  assert.doesNotMatch(PAGE, /definePageMeta|middleware|useAuthStore/);
  assert.match(PAGE, /useApi\(\)/);
  assert.match(PAGE, /useAsyncData/);
  assert.match(PAGE, /playerProfileApiPath\(/);
  assert.match(PAGE, /isPlayerProfileId\(/);
  assert.match(PAGE, /isNotFound\(/);
  assert.match(PAGE, /publicPlayer\.notFound/);
  assert.match(PAGE, /publicPlayer\.error/);
  assert.match(PAGE, /role="alert"/);
  assert.match(PAGE, /role="status"/);
  assert.match(PAGE, /common\.retry/);
});

test('038 RF-005/RF-010: cabecera, totales y trayectoria enlazada al torneo en el orden del servidor', () => {
  assert.match(PAGE, /<h1[^>]*>\{\{ playerName \}\}<\/h1>/);
  assert.match(PAGE, /<dl class="profile-totals"/);
  assert.match(PAGE, /<caption class="visually-hidden">\{\{ t\('publicPlayer\.career'\) \}\}<\/caption>/);
  assert.match(PAGE, /scope="col"/);
  assert.match(PAGE, /v-for="row in profile\.tournaments"/);
  assert.doesNotMatch(PAGE, /\.sort\(/);
  assert.match(PAGE, /:to="`\/tournaments\/\$\{row\.tournament_id\}`"/);
  assert.match(PAGE, /@error="markPhotoFailed"/);
  assert.match(PAGE, /role="img"/);
});

test('038 RNF-002: foco visible y contraste por tokens', () => {
  assert.match(PAGE, /:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--color-accent\)/);
  assert.doesNotMatch(PAGE.slice(PAGE.indexOf('<style')), /#[0-9a-f]{3,8}\b|rgba?\(/i);
});

test('038 RNF-003: textos de la ficha en español e inglés', () => {
  const keys = ['publicPlayer.eyebrow', 'publicPlayer.totals', 'publicPlayer.career', 'publicPlayer.tournament', 'publicPlayer.scope', 'publicPlayer.loading', 'publicPlayer.notFound', 'publicPlayer.error', 'publicPlayer.backHome', 'publicPlayer.title'];
  for (const key of keys) {
    assert.equal([...I18N.matchAll(new RegExp(`'${key.replace('.', '\\.')}':`, 'g'))].length, 2, key);
    assert.match(PAGE, new RegExp(key.replace('.', '\\.')), key);
  }
});
