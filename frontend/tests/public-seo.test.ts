import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  absoluteUrl,
  apiAssetUrl,
  homeHead,
  isShareableResult,
  parseMatchQuery,
  playerHead,
  resultHead,
  resultTitle,
  tournamentHead,
  type SeoContext,
  type SeoHead,
} from '../app/utils/publicSeo.ts';

const TOURNAMENT_ID = '11111111-1111-4111-8111-111111111111';
const MATCH_ID = '22222222-2222-4222-8222-222222222222';
const PLAYER_ID = '33333333-3333-4333-8333-333333333333';
const ctx: SeoContext = { siteUrl: 'https://torneos.example.org/', apiBase: '/api/v1', locale: 'es' };
const texts = { title: 'Copa', description: 'Desc', imageAlt: 'Alt' };

function metaValue(head: SeoHead, key: string): string | undefined {
  return head.meta.find((entry) => entry.property === key || entry.name === key)?.content;
}

function canonical(head: SeoHead): string | undefined {
  return head.link.find((entry) => entry.rel === 'canonical')?.href;
}

test('absoluteUrl usa el origen configurado y no duplica barras', () => {
  assert.equal(absoluteUrl('https://a.example/', '/tournaments/x'), 'https://a.example/tournaments/x');
  assert.equal(absoluteUrl('https://a.example', '/'), 'https://a.example/');
  assert.equal(absoluteUrl('https://a.example', 'tournaments/x?match=1'), 'https://a.example/tournaments/x?match=1');
});

test('apiAssetUrl admite una base de API relativa o absoluta', () => {
  assert.equal(
    apiAssetUrl('https://a.example', '/api/v1', '/tournaments/public/share-image?lang=es'),
    'https://a.example/api/v1/tournaments/public/share-image?lang=es',
  );
  assert.equal(
    apiAssetUrl('https://a.example', 'https://api.example/api/v1/', '/tournaments/public/share-image?lang=en'),
    'https://api.example/api/v1/tournaments/public/share-image?lang=en',
  );
});

test('tournamentHead publica OpenGraph, X y canónica absolutos (RF-001, RF-012)', () => {
  const head = tournamentHead(ctx, TOURNAMENT_ID, texts);
  const url = `https://torneos.example.org/tournaments/${TOURNAMENT_ID}`;
  const image = `https://torneos.example.org/api/v1/tournaments/public/${TOURNAMENT_ID}/share-image?lang=es`;
  assert.equal(head.title, 'Copa');
  assert.equal(canonical(head), url);
  assert.deepEqual(
    Object.fromEntries(head.meta.map((entry) => [entry.property ?? entry.name, entry.content])),
    {
      description: 'Desc',
      'og:type': 'website',
      'og:site_name': 'Bracket Craft',
      'og:locale': 'es_ES',
      'og:title': 'Copa',
      'og:description': 'Desc',
      'og:url': url,
      'og:image': image,
      'og:image:width': '1200',
      'og:image:height': '630',
      'og:image:alt': 'Alt',
      'twitter:card': 'summary_large_image',
      'twitter:title': 'Copa',
      'twitter:description': 'Desc',
      'twitter:image': image,
      'twitter:image:alt': 'Alt',
    },
  );
  assert.equal(metaValue(head, 'robots'), undefined);
});

test('el idioma decide og:locale y el lang de la imagen (RF-014)', () => {
  const head = tournamentHead({ ...ctx, locale: 'en' }, TOURNAMENT_ID, texts);
  assert.equal(metaValue(head, 'og:locale'), 'en_US');
  assert.match(metaValue(head, 'og:image') ?? '', /share-image\?lang=en$/);
});

test('homeHead usa la imagen de marca y la canónica del inicio (RF-002)', () => {
  const head = homeHead(ctx, texts);
  assert.equal(canonical(head), 'https://torneos.example.org/');
  assert.equal(metaValue(head, 'og:image'), 'https://torneos.example.org/api/v1/tournaments/public/share-image?lang=es');
  assert.equal(metaValue(head, 'twitter:card'), 'summary_large_image');
});

test('resultHead usa el enlace de partido y su imagen (RF-006)', () => {
  const head = resultHead(ctx, TOURNAMENT_ID, MATCH_ID, texts);
  assert.equal(canonical(head), `https://torneos.example.org/tournaments/${TOURNAMENT_ID}?match=${MATCH_ID}`);
  assert.equal(metaValue(head, 'og:url'), canonical(head));
  assert.equal(
    metaValue(head, 'og:image'),
    `https://torneos.example.org/api/v1/tournaments/public/${TOURNAMENT_ID}/matches/${MATCH_ID}/share-image?lang=es`,
  );
});

test('playerHead no indexa y nunca usa la foto (RF-008)', () => {
  const head = playerHead(ctx, PLAYER_ID, texts);
  assert.equal(metaValue(head, 'robots'), 'noindex, nofollow');
  assert.equal(canonical(head), `https://torneos.example.org/players/${PLAYER_ID}`);
  assert.equal(metaValue(head, 'og:image'), 'https://torneos.example.org/api/v1/tournaments/public/share-image?lang=es');
  assert.ok(!JSON.stringify(head).includes('photo'));
});

const finished = {
  status: 'finished',
  home_team_id: 'a',
  away_team_id: 'b',
  home_team_name: 'Leones',
  away_team_name: 'Tigres',
  home_score: 2,
  away_score: 1,
  home_penalties: null,
  away_penalties: null,
};

test('isShareableResult replica la política del backend (RF-004, RF-007)', () => {
  assert.equal(isShareableResult(finished), true);
  assert.equal(isShareableResult({ ...finished, status: 'administrative_resolution' }), true);
  for (const status of ['scheduled', 'live', 'suspended', 'not_played', 'cancelled']) {
    assert.equal(isShareableResult({ ...finished, status }), false, status);
  }
  for (const field of ['home_team_id', 'away_team_id', 'home_score', 'away_score'] as const) {
    assert.equal(isShareableResult({ ...finished, [field]: null }), false, field);
  }
  assert.equal(isShareableResult(null), false);
});

test('resultTitle muestra equipos, marcador, penaltis y torneo', () => {
  assert.equal(resultTitle(finished, 'Copa'), 'Leones 2–1 Tigres · Copa');
  assert.equal(
    resultTitle({ ...finished, home_score: 1, away_score: 1, home_penalties: 4, away_penalties: 3 }, 'Copa'),
    'Leones 1–1 Tigres (4–3) · Copa',
  );
});

test('parseMatchQuery solo acepta un UUID único', () => {
  assert.equal(parseMatchQuery(MATCH_ID), MATCH_ID);
  assert.equal(parseMatchQuery(MATCH_ID.toUpperCase()), MATCH_ID.toUpperCase());
  for (const value of [undefined, null, '', 'abc', `${MATCH_ID}x`, [MATCH_ID], 42]) {
    assert.equal(parseMatchQuery(value), null, String(value));
  }
});

test('el origen público se configura en Nuxt, Compose y .env.example (RF-012)', () => {
  const config = readFileSync(new URL('../nuxt.config.ts', import.meta.url), 'utf8');
  assert.match(config, /siteUrl: process\.env\.NUXT_PUBLIC_SITE_URL \|\| 'http:\/\/localhost:3000'/);
  const dev = readFileSync(new URL('../../docker-compose.yml', import.meta.url), 'utf8');
  assert.match(dev, /NUXT_PUBLIC_SITE_URL: \$\{FRONTEND_BASE_URL:-http:\/\/localhost:3000\}/);
  const prod = readFileSync(new URL('../../docker-compose.production.yml', import.meta.url), 'utf8');
  assert.match(prod, /NUXT_PUBLIC_SITE_URL: \$\{FRONTEND_BASE_URL:\?FRONTEND_BASE_URL must be set\}/);
  const env = readFileSync(new URL('../../.env.example', import.meta.url), 'utf8');
  assert.match(env, /^NUXT_PUBLIC_SITE_URL=http:\/\/localhost:3000$/m);
});
