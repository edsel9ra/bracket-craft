import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/sanctions.ts';

test('platform F9 API only reads authorized cases and decides, never submits or proposes', async () => {
  const calls: unknown[] = []; const exports: Record<string, () => Record<string, (...args: unknown[]) => unknown>> = {};
  const source = readFileSync(new URL('../app/composables/usePlatformSanctions.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, require: () => helpers, useApi: () => ({ request: (...args: unknown[]) => { calls.push(args); return Promise.resolve({}); } }),
  });
  const api = exports.usePlatformSanctions!();
  await api.list!({ limit: 25, offset: 25 }); await api.detail!('known'); await api.preview!('known'); await api.decide!('known', { decision: 'maintain' });
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [['/platform/sanction-cases?limit=25&offset=25'], ['/platform/sanction-cases/known'], ['/platform/sanction-cases/known/preview'], ['/platform/sanction-cases/known/decision', { method: 'POST', body: { decision: 'maintain' } }]]);
  assert.deepEqual(Object.keys(api).sort(), ['decide', 'detail', 'list', 'preview']);
});

test('platform confirmation works without organization membership and cancels on identity change', async () => {
  const organizationId = vue.ref(null); const auth = vue.reactive({ userId: 'platform' });
  let settle: (value: boolean) => void = () => {}; let writes = 0;
  const exports: Record<string, (options: { platform: boolean }) => { run: (options: unknown, operation: () => Promise<unknown>) => Promise<unknown> }> = {};
  const source = readFileSync(new URL('../app/composables/useSanctionAction.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, useApi: () => ({ organizationId }), useAuthStore: () => auth, onBeforeUnmount() {},
    useConfirm: (options: { singleFlight: boolean }) => { assert.equal(options.singleFlight, true); return { confirm: () => new Promise(resolve => { settle = resolve; }), cancelAll() {} }; },
  });
  const action = exports.useSanctionAction!({ platform: true });
  const first = action.run({}, async () => { writes++; }); settle(true); await first; assert.equal(writes, 1);
  const stale = action.run({}, async () => { writes++; }); auth.userId = 'other'; settle(true); await stale; assert.equal(writes, 1);
});
