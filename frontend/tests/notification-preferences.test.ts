import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/notifications.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;
const defaults = () => helpers.orderedPreferences([]);

type Composable = {
  items: vue.Ref<helpers.NotificationPreference[]>; loading: vue.Ref<boolean>; saving: vue.Ref<boolean>; error: vue.Ref<string>;
  saved: vue.Ref<boolean>; dirty: vue.Ref<boolean>; load: () => Promise<void>; save: () => Promise<void>;
};

function composable(request: (path: string, options?: { method?: string; body?: unknown }) => Promise<unknown>) {
  const organizationId = vue.ref('one');
  const auth = vue.reactive({ userId: 'member', access: { organization_id: 'one', permissions: [] as string[] } });
  const exports: Record<string, () => Composable> = {};
  runInNewContext(ts.transpileModule(read('composables/useNotificationPreferences.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, onMounted() {}, onBeforeUnmount() {},
    useApi: () => ({ request, organizationId }), useAuthStore: () => auth,
  });
  return { organizationId, auth, state: exports.useNotificationPreferences!() };
}

test('preferences load through useApi as the eight ordered pairs and start clean', async () => {
  const calls: string[] = [];
  const { state } = composable(async (path) => { calls.push(path); return { items: [...defaults()].reverse() }; });
  await state.load();
  assert.deepEqual(calls, ['/notification-preferences']);
  assert.deepEqual(state.items.value, defaults()); assert.equal(state.dirty.value, false);
  state.items.value[1]!.enabled = true; assert.equal(state.dirty.value, true);
});

test('saving sends exactly the eight pairs with PUT and keeps the stored state', async () => {
  const bodies: unknown[] = [];
  const { state } = composable(async (_path, options) => {
    if (options?.method === 'PUT') { bodies.push(options.body); return options.body; }
    return { items: defaults() };
  });
  await state.load(); state.items.value[1]!.enabled = true; await state.save();
  assert.equal(bodies.length, 1);
  const sent = (bodies[0] as { items: helpers.NotificationPreference[] }).items;
  assert.equal(sent.length, 8); assert.deepEqual(Object.keys(bodies[0] as object), ['items']);
  assert.equal(sent[1]!.channel, 'email'); assert.equal(sent[1]!.enabled, true);
  assert.equal(state.saved.value, true); assert.equal(state.dirty.value, false);
});

test('a rejected save keeps the edits, reports a stable error and is not marked as saved', async () => {
  const { state } = composable(async (_path, options) => { if (options?.method === 'PUT') throw { status: 422 }; return { items: defaults() }; });
  await state.load(); state.items.value[0]!.enabled = false; await state.save();
  assert.equal(state.error.value, 'notification.error.invalid'); assert.equal(state.saved.value, false);
  assert.equal(state.items.value[0]!.enabled, false); assert.equal(state.dirty.value, true);
});

test('preferences of a previous organization are discarded and nothing loads without an active access', async () => {
  let settle: (value: unknown) => void = () => {}; const calls: string[] = [];
  const { organizationId, auth, state } = composable((path) => { calls.push(path); return new Promise((resolve) => { settle = resolve; }); });
  const pending = state.load(); organizationId.value = 'two';
  settle({ items: helpers.orderedPreferences([{ type: 'match_scheduled', channel: 'email', enabled: true }]) }); await pending;
  assert.equal(state.items.value.length, 0);
  const before = calls.length; await state.load(); assert.equal(calls.length, before);
  auth.access.organization_id = 'two'; await vue.nextTick(); assert.equal(calls.length, before + 1);
});

const button = vue.defineComponent({ inheritAttrs: false, props: { disabled: Boolean, type: { type: String, default: 'button' } }, setup(props, { slots, attrs }) { return () => vue.h('button', { ...attrs, type: props.type, disabled: props.disabled }, slots.default?.()); } });
const passthrough = vue.defineComponent({ setup(_, { slots, attrs }) { return () => vue.h('section', attrs, slots.default?.()); } });

function component(state: Partial<{ items: helpers.NotificationPreference[]; loading: boolean; saving: boolean; error: string; saved: boolean; dirty: boolean }>) {
  const { descriptor } = parse(read('components/notification/NotificationPreferences.vue'));
  const javascript = ts.transpileModule(compileScript(descriptor, { id: 'prefs', inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  runInNewContext(javascript, { exports, ...vue,
    require: (spec: string) => spec === 'vue' ? vue : spec.endsWith('Button.vue') ? { __esModule: true, default: button } : spec.endsWith('.vue') ? { __esModule: true, default: passthrough } : helpers,
    useI18n: () => ({ t }), useId: () => 'prefs',
    useNotificationPreferences: () => ({
      items: vue.ref(state.items ?? defaults()), loading: vue.ref(state.loading ?? false), saving: vue.ref(state.saving ?? false),
      error: vue.ref(state.error ?? ''), saved: vue.ref(state.saved ?? false), dirty: vue.ref(state.dirty ?? false), load: async () => {}, save: async () => {},
    }),
  });
  return exports.default!;
}

const render = async (value: vue.Component) => (await renderToString(vue.createSSRApp(value))).replace(/<!--\[-->|<!--\]-->/g, '').replace(/&quot;/g, '"');

test('the preferences table has one native checkbox per type and channel with an accessible name', async () => {
  const html = await render(component({}));
  assert.match(html, /<table/); assert.match(html, /<caption[^>]*>notification\.preferences/);
  assert.equal(html.match(/<th scope="col"/g)?.length, 3); assert.equal(html.match(/<th scope="row"/g)?.length, 4);
  assert.equal(html.match(/type="checkbox"/g)?.length, 8);
  assert.equal(html.match(/ checked/g)?.length, 4);
  assert.match(html, /aria-label="notification\.preferenceLabel\{"channel":"notification\.channel\.email","type":"notification\.type\.sanction_generated"\}"/);
  assert.match(html, /notification\.emailHint/);
});

test('save is a submit button disabled while saving or without changes, with status and error regions', async () => {
  assert.match(await render(component({ dirty: false })), /<button[^>]*type="submit"[^>]*disabled[^>]*>notification\.save/);
  assert.match(await render(component({ dirty: true, saving: true })), /<button[^>]*disabled[^>]*>notification\.save/);
  assert.doesNotMatch(await render(component({ dirty: true })), /<button[^>]*disabled[^>]*>notification\.save/);
  assert.match(await render(component({ saved: true })), /role="status"[^>]*>notification\.saved/);
  assert.match(await render(component({ error: 'notification.error.invalid', dirty: true })), /role="alert"[^>]*>notification\.error\.invalid/);
  assert.match(await render(component({ loading: true, items: [] })), /role="status"[^>]*>common\.loading/);
});

test('a 422 maps to the invalid-preferences message', () => {
  assert.equal(helpers.notificationErrorKey({ status: 422 }), 'notification.error.invalid');
});

test('the page shows the preferences next to the inbox', () => {
  assert.match(read('pages/workspace/notifications.vue'), /<NotificationPreferences/);
});

test('every notification key exists in Spanish and English, including each type and channel', () => {
  const source = read('composables/useI18n.ts');
  const english = source.indexOf('\n  en: {');
  const keys = (slice: string) => new Set(Array.from(slice.matchAll(/^\s*'(notification\.[^']+)':/gm), (match) => match[1]!));
  const es = keys(source.slice(0, english)); const en = keys(source.slice(english));
  assert.deepEqual([...es].sort(), [...en].sort());
  for (const type of helpers.NOTIFICATION_TYPES) assert.ok(es.has(`notification.type.${type}`), type);
  for (const channel of helpers.NOTIFICATION_CHANNELS) assert.ok(es.has(`notification.channel.${channel}`), channel);
  for (const key of ['preferences', 'preferenceLabel', 'emailHint', 'save', 'saved', 'error.invalid']) assert.ok(es.has(`notification.${key}`), key);
});
