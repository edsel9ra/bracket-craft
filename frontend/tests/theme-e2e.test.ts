import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('theme acceptance is selected by the existing CI projects without replacing realtime scenarios', () => {
  const config = readFileSync(new URL('../playwright.config.ts', import.meta.url), 'utf8');
  assert.match(config, /realtime-public\|public-polish\|theme-public/);
  assert.match(config, /realtime-workspace\|theme-workspace/);
  assert.match(config, /retries: 0/);
  const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(packageJson.devDependencies['axe-core'], '4.10.3');
  assert.equal(packageJson.dependencies['axe-core'], undefined);
  const checks = readFileSync(new URL('../e2e/themeChecks.ts', import.meta.url), 'utf8');
  assert.match(checks, /writeJsonReport\(`theme-\$\{name\}\.json`, value\)/);
});
