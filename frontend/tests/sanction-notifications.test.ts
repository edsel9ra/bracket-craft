import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/sanctions.ts';
import { sanctionComponent } from './sanction-harness.ts';

test('notification inbox paginates HTTP, clears revoked recipient data and ignores old tenant responses', async () => {
  const organizationId = vue.ref('one'); const auth = vue.reactive({ userId: 'recipient', access: { organization_id: 'one', permissions: [] as string[] } });
  const calls: unknown[] = []; let settle: (result: unknown) => void = () => {};
  const exports: Record<string, () => { rows: vue.Ref<unknown[]>; error: vue.Ref<string>; offset: vue.Ref<number>; load: () => Promise<void>; page: (offset: number) => void }> = {};
  const source = readFileSync(new URL('../app/composables/useSanctionNotifications.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports, ...vue, require: () => helpers, onMounted() {}, onBeforeUnmount() {}, useApi: () => ({ organizationId }), useAuthStore: () => auth, useSanctionCases: () => ({ notifications: (filters: unknown) => { calls.push(filters); return new Promise((resolve) => { settle = resolve; }); } }) });
  const state = exports.useSanctionNotifications!();
  const pending = state.load(); organizationId.value = 'two'; settle({ items: [{ id: 'private-old' }] }); await pending;
  assert.equal(state.rows.value.length, 0);
  auth.access.organization_id = 'two'; settle({ items: [] }); await vue.nextTick();
  assert.equal(state.rows.value.length, 0);
  const loaded = state.load(); settle({ items: [{ id: 'notice' }] }); await loaded;
  assert.equal(state.rows.value.length, 1);
  state.page(25); assert.equal(state.offset.value, 25); assert.equal(state.rows.value.length, 0);
  assert.ok(calls.length >= 3);
});

test('notification presentation never displays evidence and links require independent VIEW permission', async () => {
  const rows = [{ id: 'notice', case_id: 'case', notification_type: 'decision', reason: 'Act reason', created_at: 'today', decision: 'maintain', evidence_text: 'NEVER RENDER' }];
  for (const canView of [true, false]) {
    const component = sanctionComponent('SanctionNotifications', { useSanctionNotifications: () => ({ rows: vue.ref(rows), offset: vue.ref(0), loading: vue.ref(false), error: vue.ref(''), canNext: vue.ref(false), load() {}, page() {} }) });
    const html = await renderToString(vue.createSSRApp(component, { canView }));
    assert.match(html, /Act reason/); assert.equal(html.includes('NEVER RENDER'), false);
    assert.equal(html.includes('/workspace/sanctions?case=case'), canView);
  }
});

test('notification empty, loading and error states are explicit without stale data', async () => {
  for (const [loading, error, expected] of [[false, '', 'sanction.noNotifications'], [true, '', 'common.loading'], [false, 'sanction.error.forbidden', 'common.retry']] as const) {
    const component = sanctionComponent('SanctionNotifications', { useSanctionNotifications: () => ({ rows: vue.ref([]), offset: vue.ref(0), loading: vue.ref(loading), error: vue.ref(error), canNext: vue.ref(false), load() {}, page() {} }) });
    assert.match(await renderToString(vue.createSSRApp(component, { canView: false })), new RegExp(expected));
  }
});
