import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as helpers from '../app/utils/rectifications.ts';

function adapter(name: string) {
  const calls: Array<{ path: string; options?: { method?: string; body?: unknown } }> = [];
  const source = readFileSync(new URL(`../app/composables/${name}.ts`, import.meta.url), 'utf8');
  const exports: Record<string, () => Record<string, (...args: unknown[]) => Promise<unknown>>> = {};
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, require: () => helpers,
    useApi: () => ({ request: async (path: string, options?: { method?: string; body?: unknown }) => { calls.push({ path, options: options ? structuredClone(options) : undefined }); return []; } }),
  });
  return { api: exports[name]!(), calls };
}

test('rectification composable transports strict bodies and pagination exclusively through useApi', async () => {
  const { api, calls } = adapter('useMatchRectifications');
  await api.list!({ status: 'pending', tournament_id: 't', limit: 25, offset: 25 });
  assert.equal(calls[0]!.path, '/rectifications?status=pending&tournament_id=t&limit=25&offset=25');
  await api.versions!('m'); await api.version!('m', 2); await api.detail!('r'); await api.preview!('r');
  const decision = { decision: 'approve', reason: 'Reviewed', expected_base_version: 2 };
  await api.decide!('r', decision);
  assert.equal(calls.at(-1)!.path, '/rectifications/r/decision');
  assert.deepEqual(calls.at(-1)!.options, { method: 'POST', body: decision });
  await api.withdraw!('r'); assert.equal(calls.at(-1)!.path, '/rectifications/r/withdraw');
  await api.authorizations!('r'); assert.equal(calls.at(-1)!.path, '/rectifications/r/platform-authorizations');
  await api.revoke!('r', 'a'); assert.equal(calls.at(-1)!.options?.method, 'DELETE');
});

test('impacts use organization inbox and fixed keep-as-played close contract', async () => {
  const { api, calls } = adapter('useCompetitiveImpacts');
  await api.list!({ status: 'open' });
  assert.equal(calls[0]!.path, '/competitive-impacts?status=open');
  await api.close!('p', 'Reviewed');
  assert.deepEqual(calls[1], { path: '/competitive-impacts/p/close', options: { method: 'POST', body: { reason: 'Reviewed' } } });
});

test('proposal drops immutable response fields and voided events without changing source', () => {
  const report = { resolution_type: 'regular', resolution_reason: null, home_score_regular: 1, away_score_regular: 0,
    home_score: 1, away_score: 0, home_penalties: null, away_penalties: null, winner_team_id: 'h',
    events: [{ id: 'db', client_event_id: 'c', segment_id: 's', event_type: 'goal', team_id: 'h', player_id: 'p', minute: 2, added_minute: 0, is_voided: false, metadata: {} },
      { client_event_id: 'voided', is_voided: true }] };
  const before = JSON.stringify(report);
  const proposal = helpers.reportProposal(report);
  assert.equal(proposal.events.length, 1);
  assert.equal('id' in proposal.events[0]!, false);
  assert.equal('is_voided' in proposal.events[0]!, false);
  assert.equal(JSON.stringify(report), before);
  assert.deepEqual(helpers.reportProposal({ ...report, resolution_type: 'walkover', resolution_reason: 'no_show' }).home_score, undefined);
});

test('self approval, stale and open-impact failures have specific localized keys', () => {
  assert.equal(helpers.canDecide('requester', 'requester', true, 'pending'), false);
  assert.equal(helpers.canDecide('requester', 'approver', true, 'pending'), true);
  assert.equal(helpers.canDecide('requester', 'approver', false, 'pending'), false);
  assert.equal(helpers.canDecide('requester', 'approver', true, 'published'), false);
  for (const code of ['STALE', 'SELF_APPROVAL', 'COMPETITIVE_IMPACT_OPEN']) {
    assert.equal(helpers.rectificationErrorKey({ statusCode: code === 'SELF_APPROVAL' ? 403 : 409, data: { detail: { code } } }), `rectification.error.${code}`);
  }
  assert.equal(helpers.rectificationErrorKey({ statusCode: 403 }), 'rectification.error.forbidden');
  assert.equal(helpers.rectificationErrorKey({ statusCode: 409 }), 'rectification.error.conflict');
  assert.equal(helpers.rectificationErrorKey({ statusCode: 403, data: { code: 'RECTIFICATION_SELF_APPROVAL' } }), 'rectification.error.SELF_APPROVAL');
});

test('version comparisons cover empty, score, added, removed, edited and explicitly reordered events', () => {
  const empty = { resolution_type: 'regular', events: [] };
  assert.deepEqual(helpers.compareReports(empty, empty), { fields: [], events: { added: [], removed: [], changed: [] } });
  const first = { client_event_id: 'a', event_type: 'goal', player_id: 'p', minute: 2 };
  const second = { client_event_id: 'b', event_type: 'goal', player_id: 'q', minute: 3 };
  const before = { ...empty, home_score: 1, events: [first, second] };
  const after = { ...empty, home_score: 2, events: [{ ...second, minute: 4 }, first] };
  const diff = helpers.compareReports(before, after);
  assert.deepEqual(diff.fields.map((field) => field.field), ['home_score', 'event_order']);
  assert.equal(diff.events.changed[0]!.client_event_id, 'b');
  assert.equal(helpers.compareReports(empty, before).events.added.length, 2);
  assert.equal(helpers.compareReports(before, empty).events.removed.length, 2);
});

test('history compares effective walkover scores and canonical event identity', () => {
  const before = { resolution_type: 'walkover', home_score: 3, away_score: 0, events: [] };
  const after = { ...before, home_score: 0, away_score: 3 };
  assert.deepEqual(helpers.compareReports(before, after).fields.map((field) => field.field), ['home_score', 'away_score']);
  const event = { client_event_id: 'ABCDEFAB-1234-4123-8123-ABCDEFABCDEF', event_type: 'goal' };
  assert.deepEqual(helpers.compareReports({ events: [event] }, { events: [{ ...event, client_event_id: event.client_event_id.toLowerCase() }] }), { fields: [], events: { added: [], removed: [], changed: [] } });
  assert.equal(helpers.rectificationErrorKey({ data: { code: 1 } }), 'rectification.error.generic');
});
