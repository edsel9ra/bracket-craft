import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/sanctions.ts';

function inbox() {
  const organizationId = vue.ref('one');
  const auth = vue.reactive({ userId: 'actor', access: { organization_id: 'one', permissions: ['VIEW_SANCTION_CASES'], role_code: 'operator' } });
  const pending: { resolve: (value: unknown) => void; reject: (value: unknown) => void }[] = [];
  const request = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
  const exports: Record<string, () => Record<string, unknown>> = {};
  const source = readFileSync(new URL('../app/composables/useSanctionInbox.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, useAuthStore: () => auth, useApi: () => ({ organizationId }),
    useSanctionCases: () => ({ list: request, sanctions: request }), onMounted() {}, onBeforeUnmount() {},
  });
  const state = exports.useSanctionInbox!() as { rows: vue.Ref<unknown[]>; sanctions: vue.Ref<unknown[]>; total: vue.Ref<number>; error: vue.Ref<string>; loading: vue.Ref<boolean>; load: () => Promise<void>; clear: () => void };
  return { state, auth, organizationId, pending };
}

test('private inbox clears immediately on organization change and ignores old responses', async () => {
  const f = inbox();
  const old = f.state.load();
  f.organizationId.value = 'two';
  assert.equal(f.state.rows.value.length, 0);
  f.pending[0]!.resolve({ items: [{ id: 'private-one' }], total: 1 });
  f.pending[1]!.resolve({ items: [{ source: { id: 'private-sanction' } }], total: 1 });
  await old;
  assert.equal(f.state.rows.value.length, 0);
  assert.equal(f.state.sanctions.value.length, 0);
  assert.equal(f.pending.length, 2);
});

test('inbox normal, empty and failed refresh never retains private stale records', async () => {
  const f = inbox();
  const load = f.state.load();
  f.pending[0]!.resolve({ items: [{ id: 'case' }], total: 1 });
  f.pending[1]!.resolve({ items: [], total: 0 });
  await load;
  assert.equal(f.state.rows.value.length, 1);
  const failed = f.state.load();
  assert.equal(f.state.rows.value.length, 0);
  f.pending[2]!.reject({ statusCode: 403 }); f.pending[3]!.resolve({ items: [], total: 0 });
  await failed;
  assert.equal(f.state.error.value, 'sanction.error.forbidden');
  assert.equal(f.state.loading.value, false);
  const empty = f.state.load();
  f.pending[4]!.resolve({ items: [], total: 0 }); f.pending[5]!.resolve({ items: [], total: 0 });
  await empty;
  assert.equal(f.state.total.value, 0);
});

test('submitting or owning without VIEW never loads the private inbox', async () => {
  const f = inbox();
  f.auth.access.permissions = ['SUBMIT_SANCTION_APPEALS'];
  f.auth.access.role_code = 'owner';
  await f.state.load();
  assert.equal(f.pending.length, 0);
  assert.equal(f.state.rows.value.length, 0);
});

test('workspace sanction navigation is conditional and does not create public routes', () => {
  const shell = readFileSync(new URL('../app/components/WorkspaceShell.vue', import.meta.url), 'utf8');
  assert.match(shell, /canUseSanctions.value \? \[\{ key: 'sanctions'/);
  assert.match(shell, /VIEW_SANCTION_CASES.*SUBMIT_SANCTION_APPEALS.*RESOLVE_SANCTION_CASES/);
  const page = readFileSync(new URL('../app/pages/workspace/sanctions.vue', import.meta.url), 'utf8');
  assert.match(page, /middleware: 'auth'/);
});
