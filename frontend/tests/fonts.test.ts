import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import test from 'node:test';
import { securityHeaders } from '../app/utils/securityHeaders.ts';

test('Archivo is pinned and serves just the normal Latin width-variable face locally', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(pkg.dependencies['@fontsource-variable/archivo'], '5.3.0');
  const css = readFileSync(new URL('../app/assets/css/fonts.css', import.meta.url), 'utf8');
  assert.equal([...css.matchAll(/url\(/g)].length, 1);
  assert.match(css, /archivo-latin-wdth-normal\.woff2/);
  assert.match(css, /font-display: swap/);
  assert.match(css, /local\('Arial'\)/);
  assert.match(css, /size-adjust:/);
  assert.match(css, /ascent-override:/);
  assert.doesNotMatch(css, /https?:\/\//);
  assert.equal(securityHeaders(true)['Content-Security-Policy'], "frame-ancestors 'none'; object-src 'none'; base-uri 'self'");
});

test('the build emits one Archivo woff2 within the 120 kB total budget', { skip: process.env.VERIFY_FONT_BUILD !== '1' }, () => {
  const root = new URL('../.output/public/', import.meta.url);
  const files = (readdirSync(root, { recursive: true }) as string[]).filter((file) => file.endsWith('.woff2'));
  assert.equal(files.length, 1);
  assert.match(files[0]!, /archivo-latin-wdth-normal/);
  const bytes = files.reduce((sum, file) => sum + statSync(new URL(file, root)).size, 0);
  assert.ok(bytes <= 120_000, `${bytes} bytes exceeds 120 kB`);
  console.log(`Archivo emitted: ${bytes} bytes`);
});
