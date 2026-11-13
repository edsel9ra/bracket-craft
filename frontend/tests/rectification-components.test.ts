import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/rectifications.ts';
import * as eventHelpers from '../app/utils/matchEvents.ts';
import * as apiErrors from '../app/utils/api.ts';

function component(name: string, globals: Record<string, unknown> = {}) {
  const source = readFileSync(new URL(`../app/components/match/${name}.vue`, import.meta.url), 'utf8');
  const { descriptor } = parse(source);
  const javascript = ts.transpileModule(compileScript(descriptor, { id: name, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  const passthrough = vue.defineComponent({ setup(_, { slots }) { return () => vue.h('div', slots.default?.()); } });
  runInNewContext(javascript, { exports, ...vue,
    require: (path: string) => path === 'vue' ? vue : path.endsWith('.vue') ? { __esModule: true, default: passthrough } : path.endsWith('/matchEvents') ? eventHelpers : path.endsWith('/api') ? apiErrors : helpers,
    useI18n: () => ({ t: (key: string) => key, formatDateTime: (value: string) => value }),
    useConfirm: () => ({ confirm: async () => true }), useAuthStore: () => ({ access: null }),
    useMatchRectifications: () => ({}), useCompetitiveImpacts: () => ({}),
    ...globals,
  });
  return exports.default!;
}

const request = { id: 'r', match_id: 'm', status: 'pending', base_version_number: 1, requested_by_member_id: 'author', reason: 'Correction', evidence: null, requested_at: 'now', proposed_report: { events: [] }, diff: { fields: [], events: { added: [], removed: [], changed: [] } } };

function versionsPanel() {
  const requests: Array<{ resolve: (value: unknown) => void; reject: (cause: unknown) => void }> = [];
  let mounted = async () => {};
  let unmount = () => {};
  const Versions = component('RectificationVersions', {
    onMounted: (fn: () => Promise<void>) => { mounted = fn; },
    onBeforeUnmount: (fn: () => void) => { unmount = fn; },
    useMatchRectifications: () => ({ versions: () => new Promise((resolve, reject) => { requests.push({ resolve, reject }); }) }),
  }) as { setup: (props: unknown, context: unknown) => (context: unknown, cache: unknown[]) => vue.VNode };
  const props = vue.reactive({ matchId: 'm', canRequest: true, refreshKey: {} });
  const render = Versions.setup(props, { expose() {}, emit() {} });
  function nodes(value: unknown): vue.VNode[] {
    if (Array.isArray(value)) return value.flatMap(nodes);
    if (typeof value === 'function') return nodes(value());
    if (!value || typeof value !== 'object') return [];
    if (vue.isVNode(value)) return [value, ...nodes(value.children)];
    return Object.values(value).flatMap(nodes);
  }
  const all = () => nodes(render({}, []));
  const button = (label: string) => all().find(node => node.props?.onClick && JSON.stringify(
    typeof node.children === 'object' && node.children && 'default' in node.children
      ? (node.children as { default: () => unknown }).default() : node.children,
  )?.includes(label))!;
  const options = () => all().filter(node => node.type === 'option').map(node => node.props!.value);
  return { props, requests, mounted: () => mounted(), unmount: () => unmount(), all, button, options };
}

const versionRow = (number: number) => ({ version_number: number, reason: `version ${number}`, report: { events: [] } });
const settleVersions = async () => { await new Promise(resolve => setImmediate(resolve)); await vue.nextTick(); };

test('accepted operation refresh reloads versions by HTTP, including an empty history', async () => {
  const h = versionsPanel();
  const mount = h.mounted();
  h.requests[0]!.resolve([versionRow(1)]);
  await mount;
  h.props.refreshKey = {};
  await vue.nextTick();
  assert.equal(h.requests.length, 2);
  h.requests[1]!.resolve([versionRow(1), versionRow(2)]);
  await settleVersions();
  assert.deepEqual(h.options(), [1, 2]);
  h.props.refreshKey = {};
  await vue.nextTick();
  h.requests[2]!.resolve([]);
  await settleVersions();
  assert.deepEqual(h.options(), []);
});

test('automatic version refresh is deferred and coalesced until the existing editor closes', async () => {
  const h = versionsPanel();
  const mount = h.mounted();
  h.requests[0]!.resolve([versionRow(1)]);
  await mount;
  h.button('rectification.request').props!.onClick();
  const editor = () => h.all().find(node => node.props?.version)!;
  const original = editor().props!.version;
  for (let i = 0; i < 3; i++) { h.props.refreshKey = {}; await vue.nextTick(); }
  assert.equal(h.requests.length, 1);
  assert.equal(editor().props!.version, original);
  editor().props!.onCancel();
  await vue.nextTick();
  assert.equal(h.requests.length, 2);
  h.requests[1]!.resolve([versionRow(1), versionRow(2)]);
  await settleVersions();
  assert.deepEqual(h.options(), [1, 2]);
});

test('opening the editor invalidates an already pending history read until it closes', async () => {
  const h = versionsPanel();
  const mount = h.mounted();
  h.requests[0]!.resolve([versionRow(1)]);
  await mount;
  h.props.refreshKey = {};
  await vue.nextTick();
  h.button('rectification.request').props!.onClick();
  h.requests[1]!.resolve([versionRow(1), versionRow(2)]);
  await settleVersions();
  assert.deepEqual(h.options(), [1]);
  const editor = h.all().find(node => node.props?.version)!;
  assert.equal(editor.props!.version.version_number, 1);
  editor.props!.onCancel();
  await vue.nextTick();
  assert.equal(h.requests.length, 3);
  h.requests[2]!.resolve([versionRow(1), versionRow(2)]);
  await settleVersions();
  assert.deepEqual(h.options(), [1, 2]);
});

test('a different match clears history and drops the previous match response', async () => {
  const h = versionsPanel();
  const mount = h.mounted();
  h.requests[0]!.resolve([versionRow(1)]);
  await mount;
  h.props.refreshKey = {};
  await vue.nextTick();
  h.props.matchId = 'other';
  await vue.nextTick();
  assert.deepEqual(h.options(), []);
  h.requests[2]!.resolve([versionRow(3)]);
  await settleVersions();
  h.requests[1]!.resolve([versionRow(99)]);
  await settleVersions();
  assert.deepEqual(h.options(), [3]);
});

for (const statusCode of [401, 403, 404]) {
  test(`a current history denial clears previously readable versions (${statusCode})`, async () => {
    const h = versionsPanel();
    const mount = h.mounted();
    h.requests[0]!.resolve([versionRow(1)]);
    await mount;
    h.props.refreshKey = {};
    await vue.nextTick();
    assert.equal(h.requests.length, 2);
    h.requests[1]!.reject({ statusCode });
    await settleVersions();
    assert.deepEqual(h.options(), []);
    assert.equal(h.all().some(node => node.props?.version), false);
  });
}

test('stale history results and denials, and responses after unmount, are ignored', async () => {
  const h = versionsPanel();
  const mount = h.mounted();
  h.requests[0]!.resolve([versionRow(1)]);
  await mount;
  h.props.refreshKey = {};
  await vue.nextTick();
  h.props.refreshKey = {};
  await vue.nextTick();
  assert.equal(h.requests.length, 3);
  h.requests[2]!.resolve([versionRow(2)]);
  await settleVersions();
  h.requests[1]!.reject({ statusCode: 403 });
  await settleVersions();
  assert.deepEqual(h.options(), [2]);
  h.props.refreshKey = {};
  await vue.nextTick();
  h.unmount();
  h.requests[3]!.resolve([versionRow(99)]);
  await settleVersions();
  assert.deepEqual(h.options(), [2]);
});

async function editorFor(events: Record<string, unknown>[]) {
  const requests: { proposed_report: helpers.ReportProposal }[] = [];
  let mounted = async () => {};
  const Editor = component('RectificationEditor', {
    useId: () => 'editor', onMounted: (fn: () => Promise<void>) => { mounted = fn; },
    useMatchRectifications: () => ({ operation: async () => ({ match: {}, rosters: [], segments: [] }), create: async (_id: string, body: { proposed_report: helpers.ReportProposal }) => { requests.push(body); } }),
  }) as { setup: (props: unknown, context: unknown) => (context: unknown, cache: unknown[]) => vue.VNode };
  const render = Editor.setup({ matchId: 'm', version: { report: { resolution_type: 'regular', events } } }, { expose() {}, emit() {} });
  await mounted();
  function nodes(value: unknown): vue.VNode[] {
    if (Array.isArray(value)) return value.flatMap(nodes);
    if (typeof value === 'function') return nodes(value());
    if (!value || typeof value !== 'object') return [];
    if (vue.isVNode(value)) return [value, ...nodes(value.children)];
    return Object.values(value).flatMap(nodes);
  }
  const all = () => nodes(render({}, []));
  for (const id of ['editor-reason', 'editor-evidence']) all().find((node) => node.props?.id === id)!.props!['onUpdate:modelValue']('Verified');
  return { requests, all, submit: () => all().find((node) => node.type === 'form')!.props!.onSubmit({ preventDefault() {} }) };
}

const assistedGoal = { client_event_id: 'aaaaaaaa-0000-4000-8000-000000000001', event_type: 'goal', team_id: 'home', player_id: 'scorer', assist_player_id: 'assistant', segment_id: 'segment', minute: 10, added_minute: 0 };

test('editor clears hidden type-specific fields before validating and sending a changed goal', async () => {
  for (const type of ['yellow_card', 'red_card', 'penalty_goal', 'foul']) {
  const editor = await editorFor([assistedGoal]);
  editor.all().find((node) => node.type === 'select' && node.props?.['onUpdate:modelValue'] && JSON.stringify(node.children).includes('event.goal'))!.props!['onUpdate:modelValue'](type);
  await editor.submit();
  assert.equal(editor.requests.length, 1);
  assert.equal(editor.requests[0]!.proposed_report.events[0]!.assist_player_id, null);
  assert.equal(editor.requests[0]!.proposed_report.events[0]!.event_type, type);
  }
});

test('editor preserves an applicable assist but still rejects a missing required player', async () => {
  const valid = await editorFor([assistedGoal]);
  await valid.submit();
  assert.equal(valid.requests[0]!.proposed_report.events[0]!.assist_player_id, 'assistant');
  const invalid = await editorFor([{ ...assistedGoal, player_id: null }]);
  await invalid.submit();
  assert.equal(invalid.requests.length, 0);
});

test('editor accepts stored non-UUID identities exactly as read', async () => {
  const editor = await editorFor([{ ...assistedGoal, client_event_id: 'Legacy-GOAL ' }]);
  await editor.submit();
  assert.equal(editor.requests.length, 1);
  assert.equal(editor.requests[0]!.proposed_report.events[0]!.client_event_id, 'Legacy-GOAL ');
  assert.equal(eventHelpers.buildDraftEvent(assistedGoal, 'segment', 'new-legacy-id'), null);
});

test('review never renders decision controls to requester, unauthorized member or finished request', async () => {
  const Review = component('RectificationReview');
  for (const [memberId, canApprove, status, visible] of [['author', true, 'pending', false], ['reviewer', false, 'pending', false], ['reviewer', true, 'published', false], ['reviewer', true, 'pending', true]] as const) {
    const html = await renderToString(vue.createSSRApp(Review, { detail: { ...request, status }, memberId, canApprove, owner: false }));
    assert.equal(html.includes('rectification.approve'), visible);
    assert.equal(html.includes('rectification.reject'), visible);
    if (visible) assert.match(html, /disabled/);
    if (memberId === 'author') assert.ok(html.includes('rectification.withdraw'));
  }
});

test('approval needs preview, sends its exact base once, and invalidates it on stale', async () => {
  const decisions: unknown[] = [];
  let confirm: (() => void) | undefined;
  let reject = false;
  const Review = component('RectificationReview', {
    useId: () => 'review', onMounted: () => {}, onBeforeUnmount: () => {},
    useConfirm: () => ({ confirm: () => new Promise<boolean>((resolve) => { confirm = () => resolve(true); }) }),
    useMatchRectifications: () => ({ preview: async () => ({ expected_base_version: 7, effects: [] }),
      decide: async (_id: string, body: unknown) => { decisions.push(body); if (reject) throw { statusCode: 409, data: { code: 'RECTIFICATION_STALE' } }; } }),
  }) as { setup: (props: unknown, context: unknown) => (context: unknown, cache: unknown[]) => vue.VNode };
  const render = Review.setup(vue.reactive({ detail: request, memberId: 'reviewer', canApprove: true, owner: false }), { expose() {}, emit() {} });
  function nodes(value: unknown): vue.VNode[] {
    if (Array.isArray(value)) return value.flatMap(nodes);
    if (typeof value === 'function') return nodes(value());
    if (!value || typeof value !== 'object') return [];
    if (vue.isVNode(value)) return [value, ...nodes(value.children)];
    return Object.values(value).flatMap(nodes);
  }
  const all = () => nodes(render({}, []));
  const text = (node: vue.VNode) => JSON.stringify(typeof node.children === 'object' && node.children && 'default' in node.children ? (node.children as { default: () => unknown }).default() : node.children);
  const button = (key: string) => all().find((node) => node.props?.onClick && text(node)?.includes(key))!;
  const reason = all().find((node) => node.type === 'textarea' && node.props?.id === 'review-decision')!;
  reason.props!['onUpdate:modelValue']('Reviewed');
  assert.equal(button('rectification.approve').props!.disabled, true);
  await button('rectification.preview').props!.onClick();
  assert.equal(button('rectification.approve').props!.disabled, false);
  const first = button('rectification.approve').props!.onClick();
  await button('rectification.approve').props!.onClick();
  assert.equal(decisions.length, 0);
  confirm!(); await first;
  assert.deepEqual(JSON.parse(JSON.stringify(decisions)), [{ decision: 'approve', reason: 'Reviewed', expected_base_version: 7 }]);
  await button('rectification.preview').props!.onClick();
  reject = true;
  const stale = button('rectification.approve').props!.onClick(); confirm!(); await stale;
  assert.equal(button('rectification.approve').props!.disabled, true);
  assert.ok(all().some((node) => node.props?.role === 'alert' && text(node)?.includes('rectification.error.STALE')));
});

test('empty versions and impacts are accessible and retries are explicit', async () => {
  for (const name of ['RectificationVersions', 'CompetitiveImpacts']) {
    const html = await renderToString(vue.createSSRApp(component(name), { matchId: 'm', tournamentId: 't', canApprove: false }));
    assert.match(html, /role="status"/);
  }
});

test('platform review uses user identity, scoped preview and decision, never tenant reads', async () => {
  const calls: unknown[] = [];
  let mounted: () => Promise<void> = async () => {};
  const Review = component('RectificationReview', {
    useId: () => 'platform-review', onMounted: (fn: () => Promise<void>) => { mounted = fn; }, onBeforeUnmount: () => {},
    usePlatformRectifications: () => ({ preview: async (id: string) => { calls.push(id); return { expected_base_version: 9, effects: [] }; },
      decide: async (id: string, body: unknown) => { calls.push([id, body]); } }),
    useMatchRectifications: () => ({ versions: () => { throw Error('tenant read'); } }),
  }) as { setup: (props: unknown, context: unknown) => (context: unknown, cache: unknown[]) => vue.VNode };
  const props = vue.reactive({ detail: { ...request, requested_by_user_id: 'author-user', current_version: { version_number: 9, report: { events: [] } } }, platform: true, memberId: 'platform-user', canApprove: true, owner: false });
  const render = Review.setup(props, { expose() {}, emit() {} });
  await mounted();
  function nodes(value: unknown): vue.VNode[] {
    if (Array.isArray(value)) return value.flatMap(nodes);
    if (typeof value === 'function') return nodes(value());
    if (!value || typeof value !== 'object') return [];
    if (vue.isVNode(value)) return [value, ...nodes(value.children)];
    return Object.values(value).flatMap(nodes);
  }
  const all = () => nodes(render({}, []));
  const button = (key: string) => all().find((node) => node.props?.onClick && JSON.stringify(typeof node.children === 'object' && node.children && 'default' in node.children ? (node.children as { default: () => unknown }).default() : node.children)?.includes(key))!;
  assert.equal(button('rectification.approve').props!.disabled, true);
  const reason = all().find((node) => node.type === 'textarea')!;
  reason.props!['onUpdate:modelValue']('Verified');
  await button('rectification.preview').props!.onClick();
  await button('rectification.approve').props!.onClick();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), ['r', ['r', { decision: 'approve', reason: 'Verified', expected_base_version: 9 }]]);
  assert.equal(button('rectification.approve').props!.disabled, true);
  props.memberId = 'author-user';
  assert.equal(button('rectification.approve'), undefined);
  assert.equal(button('rectification.reject'), undefined);
  assert.equal(button('rectification.withdraw'), undefined);
});

test('editor and review use shared confirmation, and approval requires a fresh preview base', () => {
  const read = (name: string) => readFileSync(new URL(`../app/components/match/${name}.vue`, import.meta.url), 'utf8');
  for (const name of ['RectificationEditor', 'RectificationReview', 'CompetitiveImpacts']) assert.match(read(name), /useConfirm\(\{ singleFlight: true \}\)/);
  assert.match(read('RectificationReview'), /expected_base_version:/);
  assert.match(read('RectificationReview'), /api\.preview\(/);
  assert.match(read('RectificationEditor'), /api\.create\(/);
  assert.match(read('RectificationEditor'), /buildDraftEvent/);
});

test('review renders a server-provided order difference once, including after loading the current version', async () => {
  const order = { field: 'event_order', before: ['a', 'b'], after: ['b', 'a'] };
  let mounted = async () => {};
  const Review = component('RectificationReview', {
    useId: () => 'order-review', onMounted: (fn: () => Promise<void>) => { mounted = fn; }, onBeforeUnmount: () => {},
    useMatchRectifications: () => ({ versions: async () => [{ version_number: 1, report: { events: [{ client_event_id: 'a' }, { client_event_id: 'b' }] } }] }),
  }) as { setup: (props: unknown, context: unknown) => (context: unknown, cache: unknown[]) => vue.VNode };
  const render = Review.setup({ detail: { ...request, proposed_report: { events: [{ client_event_id: 'b' }, { client_event_id: 'a' }] }, diff: { ...request.diff, fields: [order] } }, memberId: 'reviewer', canApprove: true, owner: false }, { expose() {}, emit() {} });
  await mounted();
  function nodes(value: unknown): vue.VNode[] {
    if (Array.isArray(value)) return value.flatMap(nodes);
    if (typeof value === 'function') return nodes(value());
    if (!value || typeof value !== 'object') return [];
    if (vue.isVNode(value)) return [value, ...nodes(value.children)];
    return Object.values(value).flatMap(nodes);
  }
  const diff = nodes(render({}, [])).find((node) => node.props?.diff)!.props!.diff;
  assert.deepEqual(JSON.parse(JSON.stringify(diff.fields)), [order]);
});
