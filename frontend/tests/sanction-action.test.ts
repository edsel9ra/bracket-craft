import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/sanctions.ts';

test('singleFlight confirmation suppresses duplicate writes and rejects confirmations from another tenant', async () => {
  const organizationId = vue.ref('one'); const auth = vue.reactive({ userId: 'actor' });
  let settle: (value: boolean) => void = () => {};
  let writes = 0;
  const exports: Record<string, () => { busy: vue.Ref<boolean>; error: vue.Ref<string>; run: (options: unknown, operation: () => Promise<unknown>) => Promise<unknown> }> = {};
  const source = readFileSync(new URL('../app/composables/useSanctionAction.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, useApi: () => ({ organizationId }), useAuthStore: () => auth,
    onBeforeUnmount() {}, useConfirm: (options: { singleFlight: boolean }) => { assert.equal(options.singleFlight, true); return { confirm: () => new Promise((resolve) => { settle = resolve; }), cancelAll() {} }; },
  });
  const action = exports.useSanctionAction!();
  const operation = async () => { writes++; return { id: 'case', status: 'pending' }; };
  const pending = action.run({}, operation);
  assert.equal(action.busy.value, true);
  await action.run({}, operation);
  organizationId.value = 'two'; settle(true); await pending;
  assert.equal(writes, 0);
  const normal = action.run({}, operation); settle(true); await normal;
  assert.equal(writes, 1);
  const rejected = action.run({}, async () => { throw { statusCode: 409 }; }); settle(true); await rejected;
  assert.equal(action.error.value, 'sanction.error.conflict');
  assert.equal(action.busy.value, false);
});
