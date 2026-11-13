import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as helpers from '../app/utils/sanctions.ts';

test('F9 adapter delegates strict bodies, pagination and errors to useApi without tenant cache', async () => {
  const calls: { path: string; options?: unknown }[] = [];
  let failure: unknown;
  const exports: Record<string, () => Record<string, (...args: unknown[]) => Promise<unknown>>> = {};
  const source = readFileSync(new URL('../app/composables/useSanctionCases.ts', import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, require: () => helpers,
    useApi: () => ({ request: async (path: string, options?: unknown) => { calls.push({ path, options: structuredClone(options) }); if (failure) throw failure; return { items: [], total: 0 }; } }),
  });
  const api = exports.useSanctionCases!();
  await api.list!({ status: 'pending', case_type: 'appeal', limit: 25, offset: 25 });
  assert.equal(calls.at(-1)!.path, '/sanction-cases?status=pending&case_type=appeal&limit=25&offset=25');
  await api.sanctions!({ status: 'served', player_id: 'p' });
  assert.equal(calls.at(-1)!.path, '/sanctions?status=served&player_id=p');
  const body = { represented_player_id: 'p', reason: 'Review', evidence_links: ['https://example.test'] };
  await api.appeal!('s', body);
  assert.deepEqual(calls.at(-1), { path: '/sanctions/s/appeals', options: { method: 'POST', body } });
  await api.propose!('s', { proposed_action: 'annul', reason: 'Review' });
  assert.equal(calls.at(-1)!.path, '/sanctions/s/administrative-proposals');
  await api.detail!('c'); await api.preview!('c');
  assert.equal(calls.at(-1)!.path, '/sanction-cases/c/preview');
  for (const action of ['decide', 'withdraw']) await api[action]!('c', { reason: 'Review' });
  assert.equal(calls.at(-1)!.path, '/sanction-cases/c/withdraw');
  await api.authorizations!('c'); await api.grant!('c', { platform_admin_email: 'admin@example.test', reason: 'Help' });
  await api.revoke!('c', 'a');
  assert.deepEqual(calls.at(-1), { path: '/sanction-cases/c/platform-authorizations/a', options: { method: 'DELETE' } });
  await api.notifications!({ limit: 25, offset: 25 });
  assert.equal(calls.at(-1)!.path, '/sanction-notifications?limit=25&offset=25');
  failure = { statusCode: 403 };
  await assert.rejects(api.detail!('c'), (cause) => cause === failure);
  assert.equal(/useState|localStorage|\$fetch/.test(source), false);
});

test('F9 permissions do not infer reading from submission, resolution or owner role', () => {
  assert.deepEqual(helpers.sanctionAccess(['SUBMIT_SANCTION_APPEALS'], 'operator'), { view: false, submit: true, resolve: false, owner: false });
  assert.equal(helpers.sanctionAccess(['RESOLVE_SANCTION_CASES'], 'administrator').view, false);
  assert.equal(helpers.sanctionAccess([], 'owner').owner, true);
  assert.equal(helpers.sanctionAccess([], 'owner').view, false);
  assert.equal(helpers.canDecideSanction('a', 'a', true, 'pending'), false);
  assert.equal(helpers.canDecideSanction('a', 'b', true, 'pending'), true);
  assert.equal(helpers.canDecideSanction('a', 'b', true, 'resolved'), false);
  assert.equal(helpers.canDecideSanction('a', null, true, 'pending'), false);
});

test('F9 query/error helpers never transport tenant selectors or expose server detail', () => {
  assert.equal(helpers.sanctionQuery({}), '');
  assert.equal(helpers.sanctionQuery({ status: undefined, offset: 0 }), '?offset=0');
  assert.equal(helpers.sanctionQuery({ organization_id: 'foreign' } as never), '');
  for (const [status, key] of [[403, 'forbidden'], [404, 'notFound'], [409, 'conflict'], [422, 'validation'], [500, 'generic']] as const) {
    assert.equal(helpers.sanctionErrorKey({ statusCode: status, data: { detail: 'Private evidence' } }), `sanction.error.${key}`);
  }
  assert.equal(helpers.sanctionErrorKey({ statusCode: 409, data: { code: 'SANCTION_STALE_BASE' } }), 'sanction.error.SANCTION_STALE_BASE');
});
