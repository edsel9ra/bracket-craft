import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/webhooks.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;
const i18n = () => ({ t, formatDateTime: (value: string) => `fmt:${value}`, formatNumber: (value: number) => `n:${value}` });
const button = vue.defineComponent({ inheritAttrs: false, setup(_props, { attrs, slots }) {
  return () => vue.h('button', { ...attrs, type: attrs.type ?? 'button' }, slots.default?.());
} });
const passthrough = vue.defineComponent({ inheritAttrs: false, setup(_props, { attrs, slots }) {
  return () => vue.h('div', { 'data-title': attrs.title }, [slots.default?.(), slots.actions?.()]);
} });

function compile(path: string, globals: Record<string, unknown>, children: Record<string, vue.Component> = {}): vue.Component {
  const { descriptor } = parse(read(path));
  const javascript = ts.transpileModule(compileScript(descriptor, { id: path, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  runInNewContext(javascript, { exports, ...vue, ...globals, require: (spec: string) => {
    if (spec === 'vue') return vue;
    if (spec.endsWith('utils/webhooks')) return helpers;
    const child = Object.keys(children).find((name) => spec.endsWith(`/${name}.vue`));
    if (child) return { __esModule: true, default: children[child] };
    if (spec.endsWith('Button.vue')) return { __esModule: true, default: button };
    if (spec.endsWith('.vue')) return { __esModule: true, default: passthrough };
    throw new Error(`unexpected import ${spec}`);
  } });
  return exports.default!;
}

async function render(component: vue.Component, props: Record<string, unknown> = {}) {
  const app = vue.createSSRApp(component, props); app.component('WorkspaceShell', passthrough);
  return (await renderToString(app)).replace(/<!--\[-->|<!--\]-->|<!---->/g, '').replace(/&quot;/g, '"');
}

const hook = (overrides: Partial<helpers.WebhookItem> = {}): helpers.WebhookItem => ({
  id: 'w1', url: 'https://hooks.example.com/bc', event_types: ['result_confirmed', 'sanction_generated'], is_active: true,
  created_at: '2026-11-25T10:00:00Z', updated_at: '2026-11-25T10:00:00Z', ...overrides,
});

test('the form has a labelled HTTPS field and one native checkbox per type, with the error linked', async () => {
  const form = compile('components/webhooks/WebhookForm.vue', { useI18n: i18n, useId: () => 'f' });
  const html = await render(form, { initial: { url: 'https://a.example/', event_types: ['walkover_declared'] }, submitLabel: 'webhook.form.create', busy: false, error: 'webhook.error.url' });
  assert.match(html, /<label[^>]*for="f-url"[^>]*>webhook\.form\.url<\/label>/);
  assert.match(html, /<input[^>]*id="f-url"[^>]*type="url"[^>]*aria-invalid="true"[^>]*aria-describedby="f-hint f-error"/);
  assert.match(html, /<legend>webhook\.form\.types<\/legend>/);
  assert.equal(html.match(/type="checkbox"/g)?.length, helpers.WEBHOOK_EVENT_TYPES.length);
  for (const type of helpers.WEBHOOK_EVENT_TYPES) assert.match(html, new RegExp(`value="${type}"[^>]*>\\s*<span>webhook\\.type\\.${type}</span>`));
  assert.match(html, /value="walkover_declared" checked/);
  assert.match(html, /id="f-error" role="alert"[^>]*>webhook\.error\.url/);
  assert.match(html, /type="submit"[^>]*>webhook\.form\.create/);
});

test('the secret dialog shows the secret once, with copy and the warning that it will not be shown again', async () => {
  const dialog = compile('components/webhooks/WebhookSecretDialog.vue', { useI18n: i18n, useId: () => 's' });
  const html = await render(dialog, { secret: 'whsec_once' });
  assert.match(html, /<dialog[^>]*aria-labelledby="s-title"/);
  assert.match(html, /id="s-title"[^>]*>webhook\.secret\.title/);
  assert.match(html, /<code[^>]*>whsec_once<\/code>/);
  assert.match(html, /webhook\.secret\.warning/);
  assert.match(html, /<button[^>]*>webhook\.secret\.copy<\/button>/);
  assert.match(html, /<button[^>]*>webhook\.secret\.done<\/button>/);
  assert.doesNotMatch(await render(dialog, { secret: null }), /whsec_/);
});

test('the delivery table shows type, date, attempts, last code and status, or an empty state', async () => {
  const table = compile('components/webhooks/WebhookDeliveries.vue', { useI18n: i18n });
  const html = await render(table, { deliveries: [
    { id: 'd1', event_type: 'webhook_test', created_at: '2026-11-25T10:00:00Z', attempts: 2, last_status_code: 204, status: 'delivered' },
    { id: 'd2', event_type: 'match_scheduled', created_at: '2026-11-25T09:00:00Z', attempts: 0, last_status_code: null, status: 'rejected' },
  ], loading: false, error: '' });
  assert.match(html, /<caption[^>]*>webhook\.deliveries\.title/);
  for (const column of ['type', 'date', 'attempts', 'code', 'status']) assert.match(html, new RegExp(`<th scope="col"[^>]*>webhook\\.deliveries\\.${column}`));
  assert.match(html, /webhook\.type\.webhook_test[\s\S]*fmt:2026-11-25T10:00:00Z[\s\S]*n:2[\s\S]*204[\s\S]*webhook\.status\.delivered/);
  assert.match(html, /webhook\.type\.match_scheduled[\s\S]*n:0[\s\S]*—[\s\S]*webhook\.status\.rejected/);
  assert.match(await render(table, { deliveries: [], loading: false, error: '' }), /webhook\.deliveries\.empty/);
  assert.match(await render(table, { deliveries: [], loading: true, error: '' }), /role="status"[^>]*>common\.loading/);
  assert.match(await render(table, { deliveries: [], loading: false, error: 'webhook.error.generic' }), /role="alert"[^>]*>webhook\.error\.generic/);
});

function page(state: Partial<{ canManage: boolean; items: helpers.WebhookItem[]; error: string; actionError: string; notice: string; loading: boolean }>) {
  const items = state.items ?? [];
  const children = {
    WebhookForm: compile('components/webhooks/WebhookForm.vue', { useI18n: i18n, useId: () => 'f' }),
    WebhookDeliveries: compile('components/webhooks/WebhookDeliveries.vue', { useI18n: i18n }),
    WebhookSecretDialog: compile('components/webhooks/WebhookSecretDialog.vue', { useI18n: i18n, useId: () => 's' }),
  };
  return compile('pages/workspace/webhooks.vue', {
    useI18n: i18n, definePageMeta() {}, useHead() {},
    useWebhooks: () => ({
      canManage: vue.ref(state.canManage ?? true), items: vue.ref(items), loading: vue.ref(state.loading ?? false), busy: vue.ref(false),
      error: vue.ref(state.error ?? ''), actionError: vue.ref(state.actionError ?? ''), notice: vue.ref(state.notice ?? ''), secret: vue.ref(null),
      limitReached: vue.ref(items.length >= helpers.WEBHOOK_LIMIT), deliveriesFor: vue.ref(null), deliveries: vue.ref([]),
      deliveriesLoading: vue.ref(false), deliveriesError: vue.ref(''), load: async () => {}, create: async () => true, update: async () => true,
      setActive: async () => {}, remove: async () => {}, rotate: async () => {}, sendTest: async () => {}, showDeliveries: async () => {}, dismissSecret() {},
    }),
  }, children);
}

test('without MANAGE_WEBHOOKS the page shows a forbidden state and no webhook', async () => {
  const html = await render(page({ canManage: false, items: [hook()] }));
  assert.match(html, /webhook\.error\.forbidden/);
  assert.doesNotMatch(html, /hooks\.example\.com/);
  assert.doesNotMatch(html, /webhook\.form\.create/);
});

test('each webhook shows its URL, types, state and the management actions', async () => {
  const html = await render(page({ items: [hook(), hook({ id: 'w2', url: 'https://other.example/x', is_active: false, event_types: ['match_scheduled'] })], notice: 'webhook.testQueued' }));
  assert.match(html, /data-title="webhook\.title"/);
  assert.match(html, /webhook\.form\.create/);
  assert.match(html, /hooks\.example\.com\/bc[\s\S]*webhook\.type\.result_confirmed[\s\S]*webhook\.type\.sanction_generated[\s\S]*webhook\.state\.active/);
  assert.match(html, /other\.example\/x[\s\S]*webhook\.state\.inactive/);
  for (const action of ['edit', 'disable', 'rotate', 'test', 'deliveries', 'delete']) assert.match(html, new RegExp(`webhook\\.action\\.${action}`));
  assert.match(html, /webhook\.action\.enable/);
  assert.match(html, /role="status"[^>]*>webhook\.testQueued/);
});

test('the page announces the limit, errors and an empty list', async () => {
  const full = await render(page({ items: Array.from({ length: 10 }, (_, index) => hook({ id: `w${index}` })) }));
  assert.match(full, /webhook\.limitReached/);
  assert.doesNotMatch(full, /type="submit"[^>]*>webhook\.form\.create/);
  assert.match(await render(page({})), /webhook\.empty/);
  assert.match(await render(page({ error: 'webhook.error.generic' })), /role="alert"[^>]*>webhook\.error\.generic/);
  assert.match(await render(page({ items: [hook()], actionError: 'webhook.error.inactive' })), /role="alert"[^>]*>webhook\.error\.inactive/);
});

test('the page requires a session and the Workspace links it only with MANAGE_WEBHOOKS', () => {
  assert.match(read('pages/workspace/webhooks.vue'), /definePageMeta\(\{ middleware: 'auth' \}\)/);
  const shell = read('components/WorkspaceShell.vue');
  assert.match(shell, /const canManageWebhooks = computed\(\(\) => auth\.hasPermission\('MANAGE_WEBHOOKS'\)\)/);
  assert.match(shell, /canManageWebhooks\.value \? \[\{ key: 'webhooks', label: t\('webhook\.nav'\), to: '\/workspace\/webhooks'/);
});
