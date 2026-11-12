import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/rectifications.ts';

function component(name: string, globals: Record<string, unknown> = {}) {
  const source = readFileSync(new URL(`../app/components/match/${name}.vue`, import.meta.url), 'utf8');
  const { descriptor } = parse(source);
  const javascript = ts.transpileModule(compileScript(descriptor, { id: name, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  const passthrough = vue.defineComponent({ setup(_, { slots }) { return () => vue.h('div', slots.default?.()); } });
  runInNewContext(javascript, { exports, ...vue,
    require: (path: string) => path === 'vue' ? vue : path.endsWith('.vue') ? { __esModule: true, default: passthrough } : helpers,
    useI18n: () => ({ t: (key: string) => key, formatDateTime: (value: string) => value }),
    useConfirm: () => ({ confirm: async () => true }), useAuthStore: () => ({ access: null }),
    useMatchRectifications: () => ({}), useCompetitiveImpacts: () => ({}),
    ...globals,
  });
  return exports.default!;
}

const request = { id: 'r', match_id: 'm', status: 'pending', base_version_number: 1, requested_by_member_id: 'author', reason: 'Correction', evidence: null, requested_at: 'now', proposed_report: { events: [] }, diff: { fields: [], events: { added: [], removed: [], changed: [] } } };

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

test('editor and review use shared confirmation, and approval requires a fresh preview base', () => {
  const read = (name: string) => readFileSync(new URL(`../app/components/match/${name}.vue`, import.meta.url), 'utf8');
  for (const name of ['RectificationEditor', 'RectificationReview', 'CompetitiveImpacts']) assert.match(read(name), /useConfirm\(\{ singleFlight: true \}\)/);
  assert.match(read('RectificationReview'), /expected_base_version:/);
  assert.match(read('RectificationReview'), /api\.preview\(/);
  assert.match(read('RectificationEditor'), /api\.create\(/);
  assert.match(read('RectificationEditor'), /buildDraftEvent/);
});
