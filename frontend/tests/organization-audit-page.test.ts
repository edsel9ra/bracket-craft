import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/organizationAudit.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const passthrough = vue.defineComponent({ setup(_, { slots }) { return () => vue.h('div', slots.default?.()); } });
const link = vue.defineComponent({ props: { to: { type: String, required: true } }, setup(props, { slots, attrs }) { return () => vue.h('a', { ...attrs, href: props.to }, slots.default?.()); } });

function compile(path: string, globals: Record<string, unknown>): vue.Component {
  const { descriptor } = parse(read(path));
  const javascript = ts.transpileModule(compileScript(descriptor, { id: path, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  runInNewContext(javascript, { exports, ...vue, ...globals, require: (spec: string) => {
    if (spec === 'vue') return vue;
    if (spec.endsWith('WorkspaceShell.vue')) return { __esModule: true, default: passthrough };
    if (spec.endsWith('.vue')) return { __esModule: true, default: compile(normalize(spec.startsWith('~/') ? spec.slice(2) : join(dirname(path), spec)), globals) };
    if (spec.endsWith('organizationAudit')) return helpers;
    throw new Error(`unexpected import ${spec}`);
  } });
  return exports.default!;
}

const entry = (overrides: Partial<helpers.AuditEntry> = {}): helpers.AuditEntry => ({
  id: 'e1', performed_at: '2026-11-20T15:00:00Z', action: 'CLOSE_MATCH_REPORT', cataloged: true, entity_type: 'matches',
  entity_id: 'm1', entity_available: true, actor: { kind: 'member', member_id: 'u1', name: 'Ana Ruiz' },
  details: [{ key: 'home_score', value: 2 }, { key: 'is_public', value: true }, { key: 'notes', value: 'Lluvia' }], ...overrides,
});

function globals(state: Partial<{ canRead: boolean; loading: boolean; error: string; items: helpers.AuditEntry[]; total: number }>, query: Record<string, unknown> = {}, permissions: string[] = []) {
  return {
    definePageMeta() {}, useHead() {}, useId: () => 'audit',
    useI18n: () => ({
      t: (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key,
      formatDateTime: (value: string) => `fmt:${value}`, formatNumber: (value: number) => `n:${value}`,
    }),
    useAuthStore: () => ({ access: { permissions }, hasPermission: (permission: string) => permissions.includes(permission) }),
    useRoute: () => ({ query }), useRouter: () => ({ push() {} }),
    useOrganizationAudit: () => ({
      canRead: vue.ref(state.canRead ?? true), loading: vue.ref(state.loading ?? false), error: vue.ref(state.error ?? ''),
      items: vue.ref(state.items ?? []), total: vue.ref(state.total ?? state.items?.length ?? 0),
      actors: vue.ref([{ member_id: 'u1', name: 'Ana Ruiz' }]), load: async () => {},
    }),
  };
}

async function render(component: vue.Component, props: Record<string, unknown> = {}) {
  const app = vue.createSSRApp(component, props);
  app.component('NuxtLink', link);
  return (await renderToString(app)).replace(/<!--\[-->|<!--\]-->/g, '').replace(/&quot;/g, '"');
}

const page = (...args: Parameters<typeof globals>) => render(compile('pages/workspace/audit.vue', globals(...args)));

test('the page is auth-guarded, shows the forbidden state without permission and never renders private data', async () => {
  assert.match(read('pages/workspace/audit.vue'), /definePageMeta\(\{ middleware: 'auth' \}\)/);
  const html = await page({ canRead: false, items: [entry()] });
  assert.match(html, /role="alert"[^>]*><p>audit.error.forbidden/);
  assert.doesNotMatch(html, /Ana Ruiz|<table|<form/);
});

test('loading, empty and error are distinct states, and errors offer a retry', async () => {
  assert.match(await page({ loading: true }), /role="status"[^>]*><p>audit.loading/);
  const empty = await page({});
  assert.match(empty, /role="status"[^>]*><p>audit.empty/);
  assert.doesNotMatch(empty, /role="alert"/);
  const failed = await page({ error: 'audit.error.generic' });
  assert.match(failed, /role="alert"[^>]*><p>audit.error.generic<\/p><button[^>]*>common.retry/);
  assert.doesNotMatch(failed, /audit.empty/);
});

test('the table shows date, action, entity and actor, with links only to accessible entities', async () => {
  const html = await page({ items: [
    entry(),
    entry({ id: 'e2', action: 'DECIDE_SANCTION_CASE', entity_type: 'sanction_cases', entity_id: 's1', actor: { kind: 'platform', member_id: null, name: null } }),
    entry({ id: 'e3', action: 'FUTURE_ACTION', cataloged: false, entity_type: 'matches', entity_id: 'm2', entity_available: false, details: null }),
  ] });
  for (const text of ['audit.table.caption', 'audit.column.date', 'audit.column.action', 'audit.column.entity', 'audit.column.actor', 'fmt:2026-11-20T15:00:00Z', 'audit.action.CLOSE_MATCH_REPORT', 'audit.action.unknown', 'Ana Ruiz', 'audit.actor.platform', 's1', 'm2']) {
    assert.ok(html.includes(text), text);
  }
  assert.match(html, /href="\/workspace\/matches\/m1"/);
  assert.doesNotMatch(html, /href="\/workspace\/sanctions|href="\/workspace\/matches\/m2"/);
  assert.equal(html.match(/<button[^>]*aria-haspopup="dialog"/g)?.length, 3);
  const withPermission = await render(compile('pages/workspace/audit.vue', globals({ items: [entry({ entity_type: 'sanction_cases', entity_id: 's1' })] }, {}, ['VIEW_SANCTION_CASES'])));
  assert.match(withPermission, /href="\/workspace\/sanctions\?case=s1"/);
});

test('pagination reflects the page in the URL and disables the edges', async () => {
  const items = Array.from({ length: 50 }, (_, index) => entry({ id: `e${index}` }));
  const first = await page({ items, total: 120 });
  assert.match(first, /audit.range\{"from":1,"to":50,"total":120\}/);
  assert.match(first, /<button[^>]*disabled[^>]*>audit.previous/);
  const last = await page({ items: items.slice(0, 20), total: 120 }, { page: '3' });
  assert.match(last, /audit.range\{"from":101,"to":120,"total":120\}/);
  assert.match(last, /<button[^>]*disabled[^>]*>audit.next/);
  assert.doesNotMatch(await page({ items: items.slice(0, 3), total: 3 }), /audit.pagination/);
});

test('filters render the URL state and validate the date range before applying', async () => {
  const filters = helpers.filtersFromQuery({ action: ['CLOSE_MATCH_REPORT'], actor: 'u1', from: '2026-11-01', to: '2026-11-02' });
  const html = await render(compile('components/workspace/audit/AuditFilters.vue', globals({})), { filters, actors: [{ member_id: 'u1', name: 'Ana Ruiz' }] });
  assert.match(html, /<select[^>]*multiple/);
  assert.match(html, /<option value="CLOSE_MATCH_REPORT" selected/);
  assert.equal(html.match(/<option value="[A-Z_]+"/g)?.length, helpers.AUDIT_ACTIONS.length);
  assert.match(html, /<option value="u1" selected>Ana Ruiz/);
  assert.match(html, /type="date"[^>]*value="2026-11-01"/);
  const source = read('components/workspace/audit/AuditFilters.vue');
  assert.match(source, /@submit\.prevent/);
  assert.match(source, /audit\.filter\.invalidRange/);
  assert.match(source, /emit\('apply'/);
});

test('the detail dialog renders closed details, uncataloged and empty variants, and manages focus', async () => {
  const dialog = compile('components/workspace/audit/AuditEntryDialog.vue', globals({}));
  const html = await render(dialog, { entry: entry(), permissions: [] });
  for (const text of ['audit.detail.title', 'audit.field.home_score', 'n:2', 'audit.value.true', 'Lluvia', 'href="/workspace/matches/m1"']) assert.ok(html.includes(text), text);
  assert.match(html, /<dialog[^>]*aria-labelledby="audit-title"/);
  assert.match(html, /<h2 id="audit-title" tabindex="-1"/);
  assert.match(await render(dialog, { entry: entry({ action: 'FUTURE', cataloged: false, details: null }), permissions: [] }), /audit.detail.uncataloged/);
  assert.match(await render(dialog, { entry: entry({ details: [] }), permissions: [] }), /audit.detail.empty/);
  const source = read('components/workspace/audit/AuditEntryDialog.vue');
  for (const pattern of [/showModal\(\)/, /title\.value\?\.focus\(\)/, /@cancel\.prevent/, /opener\?\.isConnected\) opener\.focus\(\)/]) assert.match(source, pattern);
});

test('webhook entries show their action, entity and fields, with the subscribed types translated and no link', async () => {
  const webhook = entry({
    action: 'CREATE_WEBHOOK', entity_type: 'organization_webhooks', entity_id: 'w1',
    details: [{ key: 'host', value: 'hooks.example.com' }, { key: 'event_types', value: 'match_scheduled,walkover_declared' }, { key: 'is_active', value: true }],
  });
  const dialog = compile('components/workspace/audit/AuditEntryDialog.vue', globals({}));
  const html = await render(dialog, { entry: webhook, permissions: ['MANAGE_WEBHOOKS'] });
  for (const text of ['audit.action.CREATE_WEBHOOK', 'audit.entity.organization_webhooks', 'audit.field.host', 'hooks.example.com',
    'audit.field.event_types', 'webhook.type.match_scheduled, webhook.type.walkover_declared', 'audit.field.is_active', 'audit.value.true']) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /href=/);
  const list = await page({ items: [webhook] }, {}, ['VIEW_ORGANIZATION_AUDIT']);
  assert.match(list, /audit\.action\.CREATE_WEBHOOK/);
  for (const action of ['CREATE_WEBHOOK', 'UPDATE_WEBHOOK', 'SET_WEBHOOK_ACTIVE', 'ROTATE_WEBHOOK_SECRET', 'DELETE_WEBHOOK']) {
    assert.match(list, new RegExp(`<option value="${action}"[^>]*>audit\\.action\\.${action}</option>`));
  }
});

test('the Workspace menu shows Audit only with VIEW_ORGANIZATION_AUDIT', () => {
  const shell = read('components/WorkspaceShell.vue');
  assert.match(shell, /const canViewAudit = computed\(\(\) => auth\.hasPermission\('VIEW_ORGANIZATION_AUDIT'\)\);/);
  assert.match(shell, /canViewAudit\.value \? \[\{ key: 'audit', label: t\('audit\.nav'\), to: '\/workspace\/audit'/);
});
