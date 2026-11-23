import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/organizationAudit.ts';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');
const catalog = read('../../backend/app/modules/organization_audit/catalog.py');
const backendActions = [...catalog.matchAll(/^ {4}"([A-Z_]+)": ActionSpec\("([a-z_]+)"/gm)];
const backendFields = new Set([...catalog.matchAll(/_field\("([a-z_]+)"/g)].map((match) => match[1]!));
const i18n = read('../app/composables/useI18n.ts');
const [es, en] = i18n.split(/^ {2}en: \{$/m);

test('the frontend catalog mirrors every backend action, with ES/EN labels for actions, fields and entities', () => {
  assert.deepEqual([...helpers.AUDIT_ACTIONS].sort(), backendActions.map((match) => match[1]).sort());
  const keys = [
    ...backendActions.map((match) => `audit.action.${match[1]}`),
    ...[...backendFields].map((field) => `audit.field.${field}`),
    ...new Set(backendActions.map((match) => `audit.entity.${match[2]}`)),
    'audit.action.unknown', 'audit.actor.platform', 'audit.value.true', 'audit.value.false',
  ];
  for (const key of keys) {
    assert.ok(es!.includes(`'${key}':`), `es ${key}`);
    assert.ok(en!.includes(`'${key}':`), `en ${key}`);
  }
  assert.equal(helpers.auditActionLabelKey('CLOSE_MATCH_REPORT'), 'audit.action.CLOSE_MATCH_REPORT');
  assert.equal(helpers.auditActionLabelKey('FUTURE_ACTION'), 'audit.action.unknown');
  assert.equal(helpers.auditEntityLabelKey('teams'), 'audit.entity.teams');
  assert.equal(helpers.auditEntityLabelKey('future'), 'audit.entity.unknown');
});

test('local dates become inclusive UTC day bounds and invalid dates are dropped', () => {
  const previous = process.env.TZ;
  process.env.TZ = 'America/Bogota';
  try {
    assert.equal(helpers.dayBoundUtc('2026-11-01', 'start'), '2026-11-01T05:00:00.000Z');
    assert.equal(helpers.dayBoundUtc('2026-11-01', 'end'), '2026-11-02T04:59:59.999Z');
    for (const value of ['', '2026-13-01', '2026-02-30', 'ayer']) assert.equal(helpers.dayBoundUtc(value, 'start'), null);
  } finally {
    if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous;
  }
});

test('filters round-trip through the URL query and build the API query', () => {
  const previous = process.env.TZ;
  process.env.TZ = 'UTC';
  try {
    const filters = helpers.filtersFromQuery({
      action: ['SAVE_MATCH_LINEUP', 'FUTURE_ACTION', 'CLOSE_MATCH_REPORT'], actor: 'member-1',
      from: '2026-11-01', to: 'mañana', page: '3',
    });
    assert.deepEqual(filters, { actions: ['CLOSE_MATCH_REPORT', 'SAVE_MATCH_LINEUP'], actor: 'member-1', from: '2026-11-01', to: '', page: 3 });
    assert.deepEqual(helpers.filtersToQuery(filters), { action: ['CLOSE_MATCH_REPORT', 'SAVE_MATCH_LINEUP'], actor: 'member-1', from: '2026-11-01', page: '3' });
    assert.deepEqual(helpers.filtersToQuery(helpers.filtersFromQuery({})), {});
    assert.deepEqual(helpers.filtersFromQuery({ action: 'CLOSE_MATCH_REPORT', page: '-2' }).page, 1);
    assert.equal(
      helpers.auditQuery({ ...filters, to: '2026-11-02' }),
      '?action=CLOSE_MATCH_REPORT&action=SAVE_MATCH_LINEUP&actor_member_id=member-1'
        + '&from=2026-11-01T00%3A00%3A00.000Z&to=2026-11-02T23%3A59%3A59.999Z&limit=50&offset=100',
    );
    assert.equal(helpers.auditQuery(helpers.filtersFromQuery({})), '?limit=50&offset=0');
  } finally {
    if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous;
  }
});

test('entity links require availability and, for sanction cases, VIEW_SANCTION_CASES', () => {
  const entry = (entity_type: string, entity_available: boolean) => ({ entity_type, entity_id: 'id-1', entity_available });
  assert.equal(helpers.auditEntityLink(entry('matches', true), []), '/workspace/matches/id-1');
  assert.equal(helpers.auditEntityLink(entry('matches', false), []), null);
  assert.equal(helpers.auditEntityLink(entry('sanction_cases', true), ['VIEW_SANCTION_CASES']), '/workspace/sanctions?case=id-1');
  assert.equal(helpers.auditEntityLink(entry('sanction_cases', true), []), null);
  assert.equal(helpers.auditEntityLink(entry('teams', true), ['VIEW_SANCTION_CASES']), null);
});

test('detail values are formatted by type and errors map to forbidden or generic', () => {
  const t = (key: string) => `t:${key}`;
  const number = (value: number) => `n:${value}`;
  assert.equal(helpers.formatAuditValue(true, t, number), 't:audit.value.true');
  assert.equal(helpers.formatAuditValue(false, t, number), 't:audit.value.false');
  assert.equal(helpers.formatAuditValue(3, t, number), 'n:3');
  assert.equal(helpers.formatAuditValue('walkover', t, number), 'walkover');
  assert.equal(helpers.auditErrorKey({ statusCode: 403 }), 'audit.error.forbidden');
  assert.equal(helpers.auditErrorKey({ status: 500 }), 'audit.error.generic');
});

function audit(permissions = ['VIEW_ORGANIZATION_AUDIT']) {
  const organizationId = vue.ref('one');
  const auth = vue.reactive({
    userId: 'actor', access: { organization_id: 'one', permissions },
    hasPermission(permission: string) { return this.access.permissions.includes(permission); },
  });
  const calls: string[] = [];
  const pending: { resolve: (value: unknown) => void; reject: (value: unknown) => void }[] = [];
  const request = (path: string) => { calls.push(path); return new Promise((resolve, reject) => pending.push({ resolve, reject })); };
  const exports: Record<string, (filters: vue.Ref<helpers.AuditFilters>) => Record<string, unknown>> = {};
  const source = read('../app/composables/useOrganizationAudit.ts');
  runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, useAuthStore: () => auth, useApi: () => ({ request, organizationId }),
    onMounted() {}, onBeforeUnmount() {},
  });
  const filters = vue.ref(helpers.filtersFromQuery({}));
  const state = exports.useOrganizationAudit!(filters) as {
    items: vue.Ref<unknown[]>; total: vue.Ref<number>; actors: vue.Ref<unknown[]>; error: vue.Ref<string>;
    loading: vue.Ref<boolean>; canRead: vue.Ref<boolean>; load: () => Promise<void>; loadActors: () => Promise<void>;
  };
  return { state, auth, organizationId, pending, calls, filters, source };
}

test('the composable only calls useApi, loads pages and actors, and keeps empty distinct from error', async () => {
  const f = audit();
  assert.doesNotMatch(f.source, /\$fetch|\bfetch\(|useFetch/);
  const load = f.state.load();
  f.pending[0]!.resolve({ items: [], total: 0, limit: 50, offset: 0 });
  await load;
  assert.deepEqual([f.state.items.value.length, f.state.total.value, f.state.error.value], [0, 0, '']);
  const actors = f.state.loadActors();
  f.pending[1]!.resolve([{ member_id: 'm', name: 'Ana' }]);
  await actors;
  assert.deepEqual(f.calls, ['/organization-audit?limit=50&offset=0', '/organization-audit/actors']);
  assert.equal(f.state.actors.value.length, 1);
  const failed = f.state.load();
  f.pending[2]!.reject({ statusCode: 403 });
  await failed;
  assert.equal(f.state.error.value, 'audit.error.forbidden');
  assert.equal(f.state.loading.value, false);
});

test('organization or user changes clear immediately and ignore stale responses', async () => {
  for (const change of [(f: ReturnType<typeof audit>) => { f.organizationId.value = 'two'; }, (f: ReturnType<typeof audit>) => { f.auth.userId = 'other'; }]) {
    const f = audit();
    const old = f.state.load();
    const oldActors = f.state.loadActors();
    change(f);
    assert.deepEqual([f.state.items.value.length, f.state.actors.value.length], [0, 0]);
    f.pending[0]!.resolve({ items: [{ id: 'private' }], total: 1, limit: 50, offset: 0 });
    f.pending[1]!.resolve([{ member_id: 'm', name: 'Ana' }]);
    await Promise.all([old, oldActors]);
    assert.deepEqual([f.state.items.value.length, f.state.actors.value.length], [0, 0]);
  }
});

test('without the permission or with a mismatched organization the composable never requests', async () => {
  const f = audit(['VIEW_SANCTION_CASES']);
  await f.state.load(); await f.state.loadActors();
  assert.equal(f.state.canRead.value, false);
  const g = audit();
  g.organizationId.value = 'other';
  await g.state.load();
  assert.deepEqual([f.calls, g.calls.filter((path) => path.startsWith('/organization-audit?'))], [[], []]);
});
