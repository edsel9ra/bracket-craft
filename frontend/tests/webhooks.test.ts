import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/webhooks.ts';
import { NOTIFICATION_TYPES } from '../app/utils/notifications.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const plain = (value: unknown) => JSON.parse(JSON.stringify(value)) as unknown;
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;

const hook = (overrides: Partial<helpers.WebhookItem> = {}): helpers.WebhookItem => ({
  id: 'w1', url: 'https://hooks.example.com/bc', event_types: ['result_confirmed'], is_active: true,
  created_at: '2026-11-25T10:00:00Z', updated_at: '2026-11-25T10:00:00Z', ...overrides,
});

test('the catalog mirrors the notification types of the backend, with ten webhooks at most', () => {
  assert.deepEqual([...helpers.WEBHOOK_EVENT_TYPES], [...NOTIFICATION_TYPES]);
  assert.equal(helpers.WEBHOOK_LIMIT, 10);
  assert.equal(helpers.webhookTypeKey('webhook_test'), 'webhook.type.webhook_test');
  assert.equal(helpers.webhookTypeKey('sanction_generated'), 'webhook.type.sanction_generated');
  assert.equal(helpers.deliveryStatusKey('rejected'), 'webhook.status.rejected');
});

test('the URL check mirrors the server: absolute HTTPS in ASCII, without credentials and bounded', () => {
  for (const url of ['https://hooks.example.com/bc?x=1', 'HTTPS://Hooks.Example.com/', 'https://[2001:db8::1]:8443/bc', '  https://a.example/  ']) {
    assert.equal(helpers.validateWebhookUrl(url), null, url);
  }
  for (const url of ['', 'http://hooks.example.com/', 'ftp://x', 'https://', 'https://user:pass@hooks.example.com/', 'https://user@hooks.example.com/',
    'https://hooks.example.com/a b', 'https://hóoks.example.com/', 'https://hooks.example.com/ruta-ñ', 'https://hooks.example.com:0/',
    'https://hooks.example.com:99999/', `https://hooks.example.com/${'a'.repeat(2030)}`, '/relative', 'https://hooks.example.com/\u0007']) {
    assert.equal(helpers.validateWebhookUrl(url), 'webhook.error.url', url);
  }
  assert.equal(helpers.normalizeWebhookUrl(' HTTPS://Hooks.Example.com/Bc '), 'https://Hooks.Example.com/Bc');
});

test('API failures map to stable keys, with the conflicts of the server', () => {
  assert.equal(helpers.webhookErrorKey({ status: 403 }), 'webhook.error.forbidden');
  assert.equal(helpers.webhookErrorKey({ statusCode: 404 }), 'webhook.error.notFound');
  assert.equal(helpers.webhookErrorKey({ status: 409, data: { detail: 'WEBHOOK_LIMIT_REACHED' } }), 'webhook.error.limit');
  assert.equal(helpers.webhookErrorKey({ status: 409, data: { detail: 'WEBHOOK_INACTIVE' } }), 'webhook.error.inactive');
  assert.equal(helpers.webhookErrorKey({ status: 422 }), 'webhook.error.url');
  assert.equal(helpers.webhookErrorKey(new Error('down')), 'webhook.error.generic');
});

type State = {
  canManage: vue.Ref<boolean>; items: vue.Ref<helpers.WebhookItem[]>; error: vue.Ref<string>; actionError: vue.Ref<string>;
  notice: vue.Ref<string>; secret: vue.Ref<string | null>; limitReached: vue.Ref<boolean>;
  deliveriesFor: vue.Ref<string | null>; deliveries: vue.Ref<helpers.WebhookDelivery[]>; deliveriesError: vue.Ref<string>;
  load: () => Promise<void>; create: (input: helpers.WebhookInput) => Promise<boolean>; update: (id: string, input: helpers.WebhookInput) => Promise<boolean>;
  setActive: (webhook: helpers.WebhookItem, active: boolean) => Promise<void>; remove: (webhook: helpers.WebhookItem) => Promise<void>;
  rotate: (webhook: helpers.WebhookItem) => Promise<void>; sendTest: (webhook: helpers.WebhookItem) => Promise<void>;
  showDeliveries: (webhook: helpers.WebhookItem) => Promise<void>; dismissSecret: () => void;
};

type Request = (path: string, options?: { method?: string; body?: unknown }) => Promise<unknown>;

function composable(request: Request, { permissions = ['MANAGE_WEBHOOKS'], accept = true } = {}) {
  const organizationId = vue.ref('one');
  const auth = vue.reactive({ userId: 'owner', access: { organization_id: 'one', permissions } });
  const confirms: Array<{ title: string; tone?: string }> = [];
  let singleFlight = false;
  const exports: { useWebhooks?: () => State } = {};
  runInNewContext(ts.transpileModule(read('composables/useWebhooks.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, onMounted() {}, onBeforeUnmount() {},
    useApi: () => ({ request, organizationId }),
    useAuthStore: () => ({ ...auth, get access() { return auth.access; }, hasPermission: (code: string) => auth.access.permissions.includes(code) }),
    useI18n: () => ({ t }),
    useConfirm: (options: { singleFlight?: boolean }) => { singleFlight = options?.singleFlight === true; return { confirm: async (value: { title: string; tone?: string }) => { confirms.push(value); return accept; } }; },
  });
  return { organizationId, auth, confirms, state: exports.useWebhooks!(), singleFlight: () => singleFlight };
}

test('nothing is requested without MANAGE_WEBHOOKS or while the cookie organization differs', async () => {
  const calls: string[] = [];
  const denied = composable(async (path) => { calls.push(path); return []; }, { permissions: [] });
  await denied.state.load();
  assert.equal(denied.state.canManage.value, false);
  const other = composable(async (path) => { calls.push(path); return []; });
  other.organizationId.value = 'two'; await other.state.load();
  assert.deepEqual(calls, []);
});

test('the list loads through useApi and ignores the answer of a previous organization', async () => {
  let settle: (value: unknown) => void = () => {};
  const { state, organizationId, auth } = composable(() => new Promise((resolve) => { settle = resolve; }));
  const pending = state.load(); organizationId.value = 'two'; settle([hook({ id: 'old' })]); await pending;
  assert.deepEqual(plain(state.items.value), []);
  auth.access.organization_id = 'two'; await vue.nextTick();
  const loaded = state.load(); settle(Array.from({ length: 10 }, (_, index) => hook({ id: `w${index}` }))); await loaded;
  assert.equal(state.items.value.length, 10); assert.equal(state.limitReached.value, true);
});

test('creating sends the normalized URL and types, shows the secret once and reloads the list', async () => {
  const calls: Array<[string, unknown]> = [];
  const { state } = composable(async (path, options) => {
    calls.push([`${options?.method ?? 'GET'} ${path}`, options?.body]);
    if (options?.method === 'POST') return { ...hook(), secret: 'whsec_once' };
    return [hook()];
  });
  assert.equal(await state.create({ url: 'http://insecure.example', event_types: ['result_confirmed'] }), false);
  assert.equal(state.actionError.value, 'webhook.error.url');
  assert.equal(await state.create({ url: 'https://ok.example', event_types: [] }), false);
  assert.equal(state.actionError.value, 'webhook.error.types');
  assert.equal(calls.length, 0);
  assert.equal(await state.create({ url: ' HTTPS://Hooks.Example.com/bc ', event_types: ['sanction_generated', 'match_scheduled'] }), true);
  assert.deepEqual(plain(calls), [
    ['POST /webhooks', { url: 'https://Hooks.Example.com/bc', event_types: ['match_scheduled', 'sanction_generated'] }],
    ['GET /webhooks', null],
  ]);
  assert.equal(state.secret.value, 'whsec_once'); assert.equal(state.items.value.length, 1);
  assert.equal(JSON.stringify(state.items.value).includes('whsec_once'), false);
  state.dismissSecret(); assert.equal(state.secret.value, null);
});

test('a server conflict on create keeps the form open with a stable key', async () => {
  const { state } = composable(async (_path, options) => { if (options?.method === 'POST') throw { status: 409, data: { detail: 'WEBHOOK_LIMIT_REACHED' } }; return []; });
  assert.equal(await state.create({ url: 'https://hooks.example.com/', event_types: ['result_confirmed'] }), false);
  assert.equal(state.actionError.value, 'webhook.error.limit'); assert.equal(state.secret.value, null);
});

test('editing patches the URL and types of the webhook', async () => {
  const calls: Array<[string, unknown]> = [];
  const { state } = composable(async (path, options) => { calls.push([`${options?.method ?? 'GET'} ${path}`, options?.body]); return options?.method ? hook() : [hook()]; });
  assert.equal(await state.update('w/1', { url: 'https://other.example/', event_types: ['walkover_declared'] }), true);
  assert.deepEqual(plain(calls[0]), ['PATCH /webhooks/w%2F1', { url: 'https://other.example/', event_types: ['walkover_declared'] }]);
});

test('disabling, deleting and rotating ask a single-flight danger confirmation; enabling does not', async () => {
  const calls: string[] = [];
  const declined = composable(async (path, options) => { calls.push(`${options?.method ?? 'GET'} ${path}`); return []; }, { accept: false });
  assert.equal(declined.singleFlight(), true);
  await declined.state.setActive(hook(), false); await declined.state.remove(hook()); await declined.state.rotate(hook());
  assert.deepEqual(calls, []);
  assert.deepEqual(declined.confirms.map((value) => [value.title, value.tone]), [
    ['webhook.confirm.disable.title', 'danger'], ['webhook.confirm.delete.title', 'danger'], ['webhook.confirm.rotate.title', 'danger'],
  ]);
  const bodies: unknown[] = [];
  const accepted = composable(async (path, options) => {
    calls.push(`${options?.method ?? 'GET'} ${path}`); bodies.push(options?.body);
    return path.endsWith('rotate-secret') ? { secret: 'whsec_new' } : options?.method ? hook() : [hook()];
  });
  await accepted.state.setActive(hook({ is_active: false }), true);
  assert.equal(accepted.confirms.length, 0);
  await accepted.state.setActive(hook(), false); await accepted.state.rotate(hook()); await accepted.state.remove(hook());
  assert.deepEqual(calls, [
    'PATCH /webhooks/w1', 'GET /webhooks', 'PATCH /webhooks/w1', 'GET /webhooks',
    'POST /webhooks/w1/rotate-secret', 'GET /webhooks', 'DELETE /webhooks/w1', 'GET /webhooks',
  ]);
  assert.deepEqual(plain(bodies[0]), { is_active: true }); assert.deepEqual(plain(bodies[2]), { is_active: false });
  assert.equal(accepted.state.secret.value, 'whsec_new');
});

test('a test delivery is queued with a status notice, and an inactive webhook maps to its key', async () => {
  let inactive = false;
  const { state } = composable(async (path, options) => {
    if (options?.method === 'POST') { if (inactive) throw { status: 409, data: { detail: 'WEBHOOK_INACTIVE' } }; return { delivery_id: 'd1' }; }
    return path.endsWith('/deliveries') ? [] : [hook()];
  });
  await state.sendTest(hook()); assert.equal(state.notice.value, 'webhook.testQueued'); assert.equal(state.actionError.value, '');
  inactive = true; await state.sendTest(hook()); assert.equal(state.actionError.value, 'webhook.error.inactive');
});

test('the delivery history of one webhook is requested on demand', async () => {
  const calls: string[] = [];
  const delivery: helpers.WebhookDelivery = { id: 'd1', event_type: 'webhook_test', created_at: '2026-11-25T10:00:00Z', attempts: 1, last_status_code: 204, status: 'delivered' };
  const { state } = composable(async (path) => { calls.push(path); if (path.endsWith('/deliveries')) return [delivery]; return [hook()]; });
  await state.showDeliveries(hook());
  assert.deepEqual(calls, ['/webhooks/w1/deliveries']);
  assert.equal(state.deliveriesFor.value, 'w1'); assert.deepEqual(plain(state.deliveries.value), [delivery]);
});

test('webhooks go through useApi only', () => {
  const source = read('composables/useWebhooks.ts');
  assert.match(source, /useApi\(\)/); assert.doesNotMatch(source, /\$fetch|fetch\(/);
});
