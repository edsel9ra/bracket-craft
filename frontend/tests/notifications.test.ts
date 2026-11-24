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
const passthrough = vue.defineComponent({ setup(_, { slots }) { return () => vue.h('div', slots.default?.()); } });
const button = vue.defineComponent({ inheritAttrs: false, props: { disabled: Boolean }, setup(props, { slots, attrs }) { return () => vue.h('button', { ...attrs, disabled: props.disabled }, slots.default?.()); } });
const link = vue.defineComponent({ props: { to: { type: String, required: true } }, setup(props, { slots, attrs }) { return () => vue.h('a', { ...attrs, href: props.to }, slots.default?.()); } });

const item = (overrides: Partial<helpers.NotificationItem> = {}): helpers.NotificationItem => ({
  id: 'n1', type: 'result_confirmed', created_at: '2026-11-24T15:00:00Z', read_at: null,
  tournament_id: 't1', tournament_name: 'Copa Norte', match_id: 'm1', home_team_name: 'Leones', away_team_name: 'Tigres',
  match_count: null, sanction: null, ...overrides,
});

const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;

test('the catalog keeps the four types and two channels of the backend in a fixed order', () => {
  assert.deepEqual([...helpers.NOTIFICATION_TYPES], ['match_scheduled', 'result_confirmed', 'walkover_declared', 'sanction_generated']);
  assert.deepEqual([...helpers.NOTIFICATION_CHANNELS], ['inbox', 'email']);
  assert.equal(helpers.notificationTypeKey('walkover_declared'), 'notification.type.walkover_declared');
});

test('each notice links to its match, or to the tournament calendar when it has no match', () => {
  assert.equal(helpers.notificationLink(item()), '/workspace/matches/m1');
  assert.equal(helpers.notificationLink(item({ type: 'sanction_generated', match_id: 'origin' })), '/workspace/matches/origin');
  assert.equal(helpers.notificationLink(item({ type: 'match_scheduled', match_id: null, match_count: 3 })), '/workspace/tournaments/t1/calendar');
});

test('the summary names the match or the scheduled count, and the player only with the sanction detail', () => {
  assert.equal(helpers.notificationSummary(item(), t), 'notification.summary.match{"home":"Leones","away":"Tigres"}');
  assert.equal(helpers.notificationSummary(item({ home_team_name: null }), t), 'notification.summary.match{"home":"notification.tbd","away":"Tigres"}');
  assert.equal(helpers.notificationSummary(item({ type: 'match_scheduled', match_id: null, match_count: 3 }), t), 'notification.summary.scheduled{"count":3}');
  const sanction = item({ type: 'sanction_generated', sanction: { player_name: 'Ana Ruiz', team_name: 'Leones', matches_suspended: 2 } });
  assert.equal(helpers.sanctionSummary(sanction, t), 'notification.summary.sanction{"player":"Ana Ruiz","team":"Leones","count":2}');
  assert.equal(helpers.sanctionSummary(item({ type: 'sanction_generated' }), t), '');
  assert.equal(helpers.sanctionSummary(item({ type: 'sanction_generated', sanction: { player_name: null, team_name: null, matches_suspended: 1 } }), t), 'notification.summary.sanction{"player":"notification.unknownPlayer","team":"notification.tbd","count":1}');
});

test('the query is paginated and errors map to stable keys', () => {
  assert.equal(helpers.notificationQuery({ limit: 25, offset: 50 }), '?limit=25&offset=50');
  assert.equal(helpers.notificationErrorKey({ status: 403 }), 'notification.error.forbidden');
  assert.equal(helpers.notificationErrorKey({ statusCode: 404 }), 'notification.error.notFound');
  assert.equal(helpers.notificationErrorKey(new Error('x')), 'notification.error.generic');
});

test('preferences come back as the eight pairs in fixed order with inbox on and email off by default', () => {
  const ordered = helpers.orderedPreferences([{ type: 'sanction_generated', channel: 'email', enabled: true }, { type: 'match_scheduled', channel: 'inbox', enabled: false }, { type: 'unknown' as never, channel: 'inbox', enabled: true }]);
  assert.equal(ordered.length, 8);
  assert.deepEqual(ordered.map((pair) => `${pair.type}:${pair.channel}:${pair.enabled}`), [
    'match_scheduled:inbox:false', 'match_scheduled:email:false', 'result_confirmed:inbox:true', 'result_confirmed:email:false',
    'walkover_declared:inbox:true', 'walkover_declared:email:false', 'sanction_generated:inbox:true', 'sanction_generated:email:true',
  ]);
});

type Composable = {
  items: vue.Ref<helpers.NotificationItem[]>; unreadCount: vue.Ref<number | null>; total: vue.Ref<number>; offset: vue.Ref<number>;
  error: vue.Ref<string>; actionError: vue.Ref<string>; canNext: vue.Ref<boolean>;
  load: () => Promise<void>; page: (offset: number) => void; markRead: (id: string) => Promise<void>; markAllRead: () => Promise<void>;
};

function composable(request: (path: string, options?: { method?: string }) => Promise<unknown>) {
  const organizationId = vue.ref('one');
  const auth = vue.reactive({ userId: 'member', access: { organization_id: 'one', permissions: [] as string[] } });
  const states = new Map<string, vue.Ref<unknown>>();
  const exports: Record<string, () => Composable> = {};
  const source = read('composables/useNotifications.ts');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, onMounted() {}, onBeforeUnmount() {},
    useApi: () => ({ request, organizationId }), useAuthStore: () => auth,
    useState: (key: string, init: () => unknown) => { if (!states.has(key)) states.set(key, vue.ref(init())); return states.get(key); },
  });
  return { organizationId, auth, states, exports };
}

const page = (items: helpers.NotificationItem[], unread: number, total = items.length, offset = 0) => ({ items, unread_count: unread, total, limit: 25, offset });

test('the inbox paginates through useApi, exposes the unread count and ignores responses of a previous organization', async () => {
  const calls: string[] = []; let settle: (value: unknown) => void = () => {};
  const { organizationId, auth, exports } = composable((path) => { calls.push(path); return new Promise((resolve) => { settle = resolve; }); });
  const state = exports.useNotifications!();
  const pending = state.load(); organizationId.value = 'two'; settle(page([item({ id: 'private-old' })], 1)); await pending;
  assert.equal(state.items.value.length, 0);
  auth.access.organization_id = 'two'; await vue.nextTick();
  const loaded = state.load(); settle(page([item()], 4, 30)); await loaded;
  assert.equal(state.items.value.length, 1); assert.equal(state.unreadCount.value, 4); assert.equal(state.canNext.value, true);
  state.page(25); assert.equal(state.offset.value, 25); assert.equal(state.items.value.length, 0);
  assert.equal(calls.at(-1), '/notifications?limit=25&offset=25');
});

test('nothing is requested while the cookie organization differs from the active access', async () => {
  const calls: string[] = [];
  const { organizationId, exports } = composable(async (path) => { calls.push(path); return page([], 0); });
  organizationId.value = 'other';
  const state = exports.useNotifications!(); await state.load();
  assert.equal(calls.length, 0); assert.equal(state.unreadCount.value, null);
});

test('marking one or all as read posts the command and reloads the page and the shared counter', async () => {
  const calls: string[] = []; let unread = 2;
  const { exports } = composable(async (path, options) => {
    calls.push(`${options?.method ?? 'GET'} ${path}`);
    if (options?.method === 'POST') { unread = path.endsWith('read-all') ? 0 : unread - 1; return null; }
    return page([item({ read_at: unread < 2 ? '2026-11-24T16:00:00Z' : null })], unread);
  });
  const state = exports.useNotifications!(); const counter = exports.useNotificationUnread!() as unknown as { count: vue.Ref<number | null> };
  await state.load(); assert.equal(counter.count.value, 2);
  await state.markRead('n1'); assert.equal(state.unreadCount.value, 1); assert.equal(counter.count.value, 1);
  await state.markAllRead(); assert.equal(state.unreadCount.value, 0);
  assert.deepEqual(calls, ['GET /notifications?limit=25&offset=0', 'POST /notifications/n1/read', 'GET /notifications?limit=25&offset=0', 'POST /notifications/read-all', 'GET /notifications?limit=25&offset=0']);
});

test('a failed command keeps the page and shows a stable error key', async () => {
  const { exports } = composable(async (_path, options) => { if (options?.method === 'POST') throw { status: 404 }; return page([item()], 1); });
  const state = exports.useNotifications!(); await state.load();
  await state.markRead('n1');
  assert.equal(state.actionError.value, 'notification.error.notFound'); assert.equal(state.items.value.length, 1);
});

test('the shell counter refreshes with a one-item request and hides itself when it fails', async () => {
  const calls: string[] = []; let fail = false;
  const { exports } = composable(async (path) => { calls.push(path); if (fail) throw new Error('down'); return page([item()], 7); });
  const counter = exports.useNotificationUnread!() as unknown as { count: vue.Ref<number | null>; refresh: () => Promise<void> };
  await counter.refresh(); assert.equal(counter.count.value, 7); assert.equal(calls.at(-1), '/notifications?limit=1&offset=0');
  fail = true; await counter.refresh(); assert.equal(counter.count.value, null);
});

function compile(path: string, globals: Record<string, unknown>): vue.Component {
  const { descriptor } = parse(read(path));
  const javascript = ts.transpileModule(compileScript(descriptor, { id: path, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  runInNewContext(javascript, { exports, ...vue, ...globals, require: (spec: string) => {
    if (spec === 'vue') return vue;
    if (spec.endsWith('Button.vue')) return { __esModule: true, default: button };
    if (spec.endsWith('.vue')) return { __esModule: true, default: passthrough };
    if (spec.endsWith('notifications')) return helpers;
    throw new Error(`unexpected import ${spec}`);
  } });
  return exports.default!;
}

function inbox(state: Partial<{ items: helpers.NotificationItem[]; unread: number; loading: boolean; error: string; actionError: string; offset: number; canNext: boolean }>) {
  return compile('components/notification/NotificationInbox.vue', {
    useI18n: () => ({ t, formatDateTime: (value: string) => `fmt:${value}` }),
    useNotifications: () => ({
      items: vue.ref(state.items ?? []), unreadCount: vue.ref(state.unread ?? 0), total: vue.ref(state.items?.length ?? 0), offset: vue.ref(state.offset ?? 0),
      loading: vue.ref(state.loading ?? false), error: vue.ref(state.error ?? ''), actionError: vue.ref(state.actionError ?? ''), busy: vue.ref(false),
      canNext: vue.ref(state.canNext ?? false), load: async () => {}, page() {}, markRead: async () => {}, markAllRead: async () => {},
    }),
  });
}

async function render(component: vue.Component) {
  const app = vue.createSSRApp(component); app.component('NuxtLink', link);
  return (await renderToString(app)).replace(/<!--\[-->|<!--\]-->/g, '').replace(/&quot;/g, '"');
}

test('the inbox lists type, date, tournament, match link and marks unread notices accessibly', async () => {
  const html = await render(inbox({ unread: 1, items: [item(), item({ id: 'n2', type: 'match_scheduled', match_id: null, match_count: 3, read_at: '2026-11-24T16:00:00Z' })] }));
  assert.match(html, /notification\.type\.result_confirmed/); assert.match(html, /notification\.type\.match_scheduled/);
  assert.match(html, /fmt:2026-11-24T15:00:00Z/); assert.match(html, /Copa Norte/);
  assert.match(html, /href="\/workspace\/matches\/m1"/); assert.match(html, /href="\/workspace\/tournaments\/t1\/calendar"/);
  assert.match(html, /notification\.unreadCount\{"count":1\}/);
  assert.equal(html.match(/notification\.unreadBadge/g)?.length, 1);
  assert.equal(html.match(/notification\.markRead/g)?.length, 1);
  assert.match(html, /<time datetime="2026-11-24T15:00:00Z"/);
});

test('the sanction notice names the player only when the API sends the detail', async () => {
  const withDetail = await render(inbox({ items: [item({ type: 'sanction_generated', sanction: { player_name: 'Ana Ruiz', team_name: 'Leones', matches_suspended: 2 } })] }));
  assert.match(withDetail, /Ana Ruiz/);
  const without = await render(inbox({ items: [item({ type: 'sanction_generated' })] }));
  assert.doesNotMatch(without, /notification\.summary\.sanction/); assert.match(without, /notification\.summary\.match/);
});

test('mark all is disabled without unread notices and pagination follows the page state', async () => {
  const html = await render(inbox({ unread: 0, items: [item({ read_at: '2026-11-24T16:00:00Z' })], offset: 0, canNext: false }));
  assert.match(html, /<button[^>]*disabled[^>]*>notification\.markAllRead/);
  assert.match(html, /<button[^>]*disabled[^>]*>notification\.previous/); assert.match(html, /<button[^>]*disabled[^>]*>notification\.next/);
});

test('empty, loading, load error and command error states are explicit', async () => {
  assert.match(await render(inbox({})), /notification\.empty/);
  assert.match(await render(inbox({ loading: true })), /role="status"[^>]*>common\.loading/);
  const failed = await render(inbox({ error: 'notification.error.generic', items: [item()] }));
  assert.match(failed, /role="alert"[^>]*>notification\.error\.generic/); assert.match(failed, /common\.retry/); assert.doesNotMatch(failed, /Copa Norte/);
  assert.match(await render(inbox({ items: [item()], actionError: 'notification.error.notFound' })), /role="alert"[^>]*>notification\.error\.notFound/);
});

test('the page is a member-only Workspace route with the inbox', () => {
  const pageSource = read('pages/workspace/notifications.vue');
  assert.match(pageSource, /middleware: 'auth'/); assert.match(pageSource, /<NotificationInbox/); assert.match(pageSource, /notification\.title/);
  assert.doesNotMatch(pageSource, /hasPermission/);
});

test('the shell links every member to the inbox with the unread count as accessible text', () => {
  const shell = read('components/WorkspaceShell.vue');
  assert.match(shell, /key: 'notifications', label: t\('notification\.nav'\), to: '\/workspace\/notifications'/);
  assert.match(shell, /useNotificationUnread\(\)/);
  assert.match(shell, /notification\.unreadCount/); assert.match(shell, /visually-hidden/);
  const links = shell.slice(shell.indexOf('const primaryLinks'), shell.indexOf("key: 'sanction-notifications'"));
  assert.doesNotMatch(links, /hasPermission|canUse|canView/);
});

test('notices and the composable go through useApi only', () => {
  const source = read('composables/useNotifications.ts');
  assert.match(source, /useApi\(\)/); assert.doesNotMatch(source, /\$fetch|fetch\(/);
});
