import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('031 public regression is anonymous, measured and included without replacing realtime', () => {
  const suite = readFileSync(new URL('../e2e/public-polish.spec.ts', import.meta.url), 'utf8');
  const config = readFileSync(new URL('../playwright.config.ts', import.meta.url), 'utf8');
  assert.match(suite, /storageState: \{ cookies: \[\], origins: \[\] \}/);
  for (const width of ['1440', '390', '800']) assert.ok(suite.includes(width));
  for (const behavior of ['measureColumns', 'measureBracket', 'measureSticky', 'Escape', 'public-stats-scope', 'empty', 'error']) assert.ok(suite.includes(behavior), behavior);
  assert.match(config, /testMatch: .*realtime-public.*public-polish/);
  assert.doesNotMatch(suite, /test\.skip|test\.fixme|storageState.*\.auth/);
});
