import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { securityHeaders } from '../app/utils/securityHeaders.ts';

for (const production of [false, true]) {
  test(`cabeceras SSR seguras sin bloquear scripts inline (producción=${production})`, () => {
    const headers = securityHeaders(production);
    assert.equal(headers['X-Content-Type-Options'], 'nosniff');
    assert.equal(headers['X-Frame-Options'], 'DENY');
    assert.equal(headers['Referrer-Policy'], 'strict-origin-when-cross-origin');
    assert.equal(headers['Content-Security-Policy'], "frame-ancestors 'none'; object-src 'none'; base-uri 'self'");
    assert.equal(headers['Strict-Transport-Security'], production ? 'max-age=31536000; includeSubDomains' : undefined);
  });
}

test('Nitro aplica las cabeceras a todas las rutas y activa HSTS solo en producción', () => {
  const config = readFileSync(new URL('../nuxt.config.ts', import.meta.url), 'utf8');
  assert.match(config, /'\/\*\*':\s*\{ headers: securityHeaders\(process\.env\.NODE_ENV === 'production'\)/);
});
