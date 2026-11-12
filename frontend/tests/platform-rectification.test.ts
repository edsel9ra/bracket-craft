import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as rectificationHelpers from '../app/utils/rectifications.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');

test('platform composable uses only its scoped GET endpoints and decision body', async () => {
  const calls: unknown[] = [];
  const exports: Record<string, (...args: unknown[]) => Record<string, (...args: unknown[]) => unknown>> = {};
  runInNewContext(ts.transpileModule(read('composables/usePlatformRectifications.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { exports, useApi: () => ({ request: (...args: unknown[]) => { calls.push(args); return Promise.resolve([]); } }) });
  const api = exports.usePlatformRectifications();
  await api.list(); await api.detail('r'); await api.preview('r');
  await api.decide('r', { decision: 'approve', reason: 'Reviewed', expected_base_version: 3 });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['/platform/rectifications'], ['/platform/rectifications/r'], ['/platform/rectifications/r/preview'], ['/platform/rectifications/r/decision', { method: 'POST', body: { decision: 'approve', reason: 'Reviewed', expected_base_version: 3 } }]]);
});

test('public mark renders only localized text and valid date; null or malformed date is empty', async () => {
  const { descriptor } = parse(read('components/public/PublicRectifiedMark.vue'));
  const exports: { default?: vue.Component } = {};
  runInNewContext(ts.transpileModule(compileScript(descriptor, { id: 'mark', inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { exports, ...vue, require: () => vue, useI18n: () => ({ t: () => 'Resultado rectificado', formatDateTime: (value: string) => value }) });
  for (const rectifiedAt of [null, '', 'invalid', '2026-11-12T10:00:00Z']) {
    const html = await renderToString(vue.createSSRApp(exports.default!, { rectifiedAt }));
    if (rectifiedAt === '2026-11-12T10:00:00Z') { assert.match(html, /Resultado rectificado/); assert.match(html, /<time datetime="2026-11-12T10:00:00Z"/); }
    else assert.doesNotMatch(html, /Resultado rectificado|<time/);
    assert.doesNotMatch(html, /reason|evidence|requested_by|published_by/);
  }
});

test('all public cards, modal and bracket use the mark without private fields', () => {
  const page = read('pages/tournaments/[id].vue');
  assert.equal((page.match(/<PublicRectifiedMark\b/g) || []).length, 4);
  for (const file of ['pages/tournaments/[id].vue', 'components/public/PublicBracket.vue', 'components/public/PublicLineupModal.vue']) {
    const source = read(file);
    assert.match(source, /<PublicRectifiedMark :rectified-at="match.rectified_at"/);
    assert.doesNotMatch(source, /requested_by|published_by|resolution_reason|\.evidence/);
  }
});

test('admin route is platform guarded and reuses scoped review without impacts', () => {
  const source = read('pages/admin/rectifications.vue');
  assert.match(source, /middleware: 'platform'/);
  assert.match(source, /usePlatformRectifications/);
  assert.match(source, /<RectificationReview[^>]*\bplatform\b/);
  assert.doesNotMatch(source, /CompetitiveImpacts|keep_as_played|\/competitive-impacts/);
});

test('admin list renders loaded, empty and failed states with accessible feedback', async () => {
  for (const state of ['loaded', 'empty', 'error']) {
    const { descriptor } = parse(read('pages/admin/rectifications.vue'));
    const exports: { default?: vue.Component } = {};
    const passthrough = vue.defineComponent({ setup(_, { slots }) { return () => vue.h('div', slots.default?.()); } });
    runInNewContext(ts.transpileModule(compileScript(descriptor, { id: 'platform-page', inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
      exports, ...vue,
      require: (path: string) => path === 'vue' ? vue : path.endsWith('.vue') ? { __esModule: true, default: passthrough } : path.endsWith('/api') ? { isForbidden: () => false, isUnauthorized: () => false } : rectificationHelpers,
      definePageMeta() {}, useHead() {}, useAuthStore: () => ({ userId: 'admin' }),
      useI18n: () => ({ t: (key: string) => key, formatDateTime: (value: string) => value }),
      onMounted: vue.onServerPrefetch,
      usePlatformRectifications: () => ({ list: async () => {
        if (state === 'error') throw Error('network');
        return state === 'empty' ? [] : [{ id: 'r', reason: 'Scoped request', status: 'pending', requested_at: 'now' }];
      } }),
    });
    const app = vue.createSSRApp(exports.default!);
    app.component('WorkspaceShell', passthrough);
    const html = await renderToString(app);
    if (state === 'loaded') assert.match(html, /Scoped request/);
    if (state === 'empty') assert.match(html, /role="status"[^>]*>rectification.noRequests/);
    if (state === 'error') assert.match(html, /role="alert"[^>]*>rectification.error.generic/);
  }
});
