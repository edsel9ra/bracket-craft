import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { computed, shallowRef } from 'vue';
import * as theme from '../app/utils/theme.ts';

function harness(raw?: unknown, client = false, blocked = false) {
  const source = readFileSync(new URL('../app/composables/useTheme.ts', import.meta.url), 'utf8');
  const javascript = ts.transpileModule(source.replaceAll('import.meta.client', String(client)).replaceAll('import.meta.dev', 'false'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const state = new Map();
  const writes: string[] = [];
  const reads: { name: string; options: Record<string, unknown> }[] = [];
  const exports: { useTheme?: () => { preference: { value: string }; setTheme: (value: unknown) => boolean } } = {};
  const document = Object.defineProperty({}, 'cookie', { set(value: string) { writes.push(value); if (blocked) throw new Error('Storage denied'); } });
  runInNewContext(javascript, {
    exports, require: () => theme, computed, document,
    useState(key: string, initialize: () => unknown) {
      if (!state.has(key)) state.set(key, shallowRef(initialize()));
      return state.get(key);
    },
    useCookie(name: string, options: Record<string, unknown>) { reads.push({ name, options }); return { value: raw }; },
  });
  return { useTheme: exports.useTheme!, writes, reads };
}

test('SSR theme reads never write or repair cookies and requests cannot share state', () => {
  for (const raw of [undefined, null, 'invalid', 'light', 'system']) {
    const h = harness(raw);
    const adapter = h.useTheme();
    assert.equal(adapter.preference.value, theme.normalizeTheme(raw));
    assert.deepEqual(h.writes, []);
    assert.equal(h.reads[0]?.name, 'bc_theme');
    assert.equal(h.reads[0]?.options.readonly, true);
    assert.equal(h.reads[0]?.options.default, undefined);
  }
  assert.equal(harness('light').useTheme().preference.value, 'light');
  assert.equal(harness('dark').useTheme().preference.value, 'dark');
});

test('explicit choices update all consumers and are the only cookie writes', () => {
  const h = harness(undefined, true);
  const first = h.useTheme();
  const second = h.useTheme();
  assert.equal(first.preference.value, 'dark');
  assert.equal(h.writes.length, 0);
  assert.equal(first.setTheme('light'), true);
  assert.equal(second.preference.value, 'light');
  assert.match(h.writes[0]!, /^bc_theme=light; Path=\/; Max-Age=31536000; SameSite=Lax; Secure$/);
  assert.equal(second.setTheme('system'), true);
  assert.equal(first.preference.value, 'system');
  assert.equal(first.setTheme('invalid'), false);
  assert.equal(h.writes.length, 2);
  assert.equal(first.preference.value, 'system');
});

test('blocked cookie storage keeps the in-memory choice and a fresh visit defaults dark', () => {
  const h = harness(undefined, true, true);
  const adapter = h.useTheme();
  assert.doesNotThrow(() => adapter.setTheme('light'));
  assert.equal(adapter.preference.value, 'light');
  assert.equal(h.useTheme().preference.value, 'light');
  assert.equal(harness().useTheme().preference.value, 'dark');
});

test('root installs reactive head before rendering, with no static theme-color or script', () => {
  const root = readFileSync(new URL('../app/app.vue', import.meta.url), 'utf8');
  const config = readFileSync(new URL('../nuxt.config.ts', import.meta.url), 'utf8');
  assert.match(root, /const \{ preference \} = useTheme\(\)/);
  assert.match(root, /useHead\(\(\) => describeTheme\(preference.value\)\)/);
  assert.doesNotMatch(config, /name: 'theme-color'/);
  assert.doesNotMatch(root, /localStorage|matchMedia|onMounted|location\.reload/);
});
