import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  PRIVATE_PATHS,
  SEO_CACHE_CONTROL,
  SITEMAP_MAX_PAGES,
  SITEMAP_PAGE_SIZE,
  buildRobots,
  buildSitemap,
  collectPublicTournaments,
} from '../server/utils/seoDocuments.ts';

const SITE = 'https://torneos.example.org/';
const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';

test('buildSitemap lista inicio y torneos públicos con URL absolutas (RF-009, RF-012)', () => {
  const xml = buildSitemap(SITE, [{ id: A }, { id: B }]);
  assert.ok(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n'));
  assert.match(xml, /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
  const locs = [...xml.matchAll(/<loc>([^<]*)<\/loc>/g)].map((match) => match[1]);
  assert.deepEqual(locs, [
    'https://torneos.example.org/',
    `https://torneos.example.org/tournaments/${A}`,
    `https://torneos.example.org/tournaments/${B}`,
  ]);
  assert.doesNotMatch(xml, /lastmod|players/);
  assert.ok(locs.every((loc) => !loc?.includes('?')));
});

test('buildSitemap escapa el XML y deduplica', () => {
  const xml = buildSitemap('https://a.example/x&y<', [{ id: A }, { id: A }]);
  assert.match(xml, /<loc>https:\/\/a\.example\/x&amp;y&lt;\/<\/loc>/);
  assert.equal(xml.split(`/tournaments/${A}`).length - 1, 1);
});

test('buildSitemap descarta identificadores que no son UUID', () => {
  const xml = buildSitemap(SITE, [{ id: '../workspace' }, { id: `${A}?stage=1` }, { id: B }]);
  assert.doesNotMatch(xml, /workspace|stage/);
  assert.match(xml, new RegExp(`/tournaments/${B}<`));
});

test('buildRobots bloquea lo privado, permite lo público y anuncia el sitemap (RF-010)', () => {
  const robots = buildRobots(SITE);
  const lines = robots.trim().split('\n');
  assert.equal(lines[0], 'User-agent: *');
  assert.ok(lines.includes('Allow: /'));
  for (const path of ['/workspace', '/admin', '/login', '/auth', '/account', '/organization', '/password', '/invitations', '/forbidden']) {
    assert.ok(PRIVATE_PATHS.includes(path), path);
    assert.ok(lines.includes(`Disallow: ${path}`), path);
  }
  assert.ok(!lines.some((line) => /Disallow: \/(tournaments|players)?$/.test(line)));
  assert.equal(lines.at(-1), 'Sitemap: https://torneos.example.org/sitemap.xml');
});

test('collectPublicTournaments pagina hasta una página incompleta', async () => {
  const calls: Array<[number, number]> = [];
  const full = Array.from({ length: SITEMAP_PAGE_SIZE }, (_, index) => ({ id: `t${index}` }));
  const result = await collectPublicTournaments(async (limit, offset) => {
    calls.push([limit, offset]);
    return offset === 0 ? full : [{ id: 'last' }];
  });
  assert.deepEqual(calls, [[200, 0], [200, 200]]);
  assert.equal(result.length, SITEMAP_PAGE_SIZE + 1);
});

test('collectPublicTournaments respeta el tope de 50 páginas', async () => {
  let calls = 0;
  const result = await collectPublicTournaments(async (limit) => {
    calls += 1;
    return Array.from({ length: limit }, (_, index) => ({ id: `${calls}-${index}` }));
  });
  assert.equal(SITEMAP_MAX_PAGES, 50);
  assert.equal(calls, 50);
  assert.equal(result.length, 50 * SITEMAP_PAGE_SIZE);
});

test('collectPublicTournaments propaga el fallo de la API', async () => {
  await assert.rejects(collectPublicTournaments(async () => { throw new Error('down'); }), /down/);
});

test('las rutas Nitro usan el origen configurado, apiInternalBase y caché de 10 minutos (RNF-001)', () => {
  assert.equal(SEO_CACHE_CONTROL, 'public, max-age=600');
  const sitemap = readFileSync(new URL('../server/routes/sitemap.xml.ts', import.meta.url), 'utf8');
  const robots = readFileSync(new URL('../server/routes/robots.txt.ts', import.meta.url), 'utf8');
  for (const source of [sitemap, robots]) {
    assert.match(source, /siteUrl/);
    assert.match(source, /SEO_CACHE_CONTROL/);
    assert.doesNotMatch(source, /getRequestHost|getRequestURL|headers\.host|'host'/i);
  }
  assert.match(sitemap, /apiInternalBase/);
  assert.match(sitemap, /application\/xml/);
  assert.match(sitemap, /credentials: 'omit'/);
  assert.match(robots, /text\/plain/);
});
