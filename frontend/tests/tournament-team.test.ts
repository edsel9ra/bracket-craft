import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/tournamentTeam.ts';
import { catalogParity } from '../app/utils/i18nCatalog.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;

const member = (overrides: Partial<helpers.TournamentTeamMember> = {}): helpers.TournamentTeamMember => ({
  organization_user_id: 'm1', full_name: 'Vera Vista', organization_role_code: 'viewer', role_code: 'tournament_operator',
  is_active: true, adds_permissions: true, assigned_at: '2026-11-26T10:00:00Z', ...overrides,
});
const access = (overrides: Partial<helpers.OperationAccess> = {}): helpers.OperationAccess => ({
  organization_user_id: 'me', role_code: 'viewer', permissions: [], operated_tournament_ids: [], ...overrides,
});

test('canOperateMatch keeps the organization and official rules and adds the operated tournament', () => {
  const match = { tournament_id: 'A' };
  const officials = [{ organization_user_id: 'me' }];
  assert.equal(helpers.canOperateMatch(null, match, []), false);
  assert.equal(helpers.canOperateMatch(access(), match, []), false);
  for (const role of ['owner', 'administrator', 'operator']) {
    assert.equal(helpers.canOperateMatch(access({ role_code: role, permissions: ['CLOSE_MATCH_REPORT'] }), match, []), true);
    assert.equal(helpers.canOperateMatch(access({ role_code: role }), match, []), false);
  }
  assert.equal(helpers.canOperateMatch(access({ role_code: 'referee', permissions: ['CLOSE_MATCH_REPORT'] }), match, []), false);
  assert.equal(helpers.canOperateMatch(access({ role_code: 'referee', permissions: ['CLOSE_MATCH_REPORT'] }), match, officials), true);
  assert.equal(helpers.canOperateMatch(access({ role_code: 'referee' }), match, officials), false);
  assert.equal(helpers.canOperateMatch(access({ operated_tournament_ids: ['A'] }), match, []), true);
  assert.equal(helpers.canOperateMatch(access({ operated_tournament_ids: ['B'] }), match, []), false);
  assert.equal(helpers.canOperateMatch(access({ operated_tournament_ids: ['A'] }), null, []), false);
  assert.equal(helpers.canOperateMatch(access({ operated_tournament_ids: undefined }), match, []), false);
});

test('the list is ordered by name and id, and the selector offers only active members not yet assigned', () => {
  const team = helpers.sortTeam([member({ organization_user_id: 'b', full_name: 'Ana' }), member({ organization_user_id: 'c', full_name: 'Zoe' }),
    member({ organization_user_id: 'a', full_name: 'Ana' }), member({ organization_user_id: 'd', full_name: 'Álvaro' })]);
  assert.deepEqual(team.map((item) => item.organization_user_id), ['d', 'a', 'b', 'c']);
  const candidates = helpers.assignableMembers([
    { organization_user_id: 'a', full_name: 'Ana', is_active: true, role_code: 'viewer' },
    { organization_user_id: 'x', full_name: 'Xavi', is_active: true, role_code: 'referee' },
    { organization_user_id: 'y', full_name: 'Yago', is_active: false, role_code: 'viewer' },
    { organization_user_id: 'e', full_name: 'Eva', is_active: true, role_code: 'owner' },
  ], team);
  assert.deepEqual(candidates.map((item) => item.organization_user_id), ['e', 'x']);
});

test('API failures map to stable keys', () => {
  assert.equal(helpers.tournamentTeamErrorKey({ status: 403 }), 'tournamentTeam.error.forbidden');
  assert.equal(helpers.tournamentTeamErrorKey({ statusCode: 404, data: { detail: 'Torneo no encontrado' } }), 'tournamentTeam.error.tournament');
  assert.equal(helpers.tournamentTeamErrorKey({ status: 404, data: { detail: 'Miembro no encontrado' } }), 'tournamentTeam.error.member');
  assert.equal(helpers.tournamentTeamErrorKey({ status: 404, data: { detail: 'Asignación no encontrada' } }), 'tournamentTeam.error.assignment');
  assert.equal(helpers.tournamentTeamErrorKey(new Error('down')), 'tournamentTeam.error.generic');
});

type State = {
  canManage: vue.Ref<boolean>; items: vue.Ref<helpers.TournamentTeamMember[]>; candidates: vue.ComputedRef<helpers.OrganizationMember[]>;
  error: vue.Ref<string>; actionError: vue.Ref<string>; notice: vue.Ref<string>; busy: vue.Ref<boolean>;
  load: () => Promise<void>; assign: (memberId: string) => Promise<boolean>; remove: (item: helpers.TournamentTeamMember) => Promise<boolean>;
};
type Request = (path: string, options?: { method?: string }) => Promise<unknown>;

function composable(request: Request, { permissions = ['MANAGE_MEMBERS'], accept = true, me = 'owner' } = {}) {
  const organizationId = vue.ref('one');
  const auth = vue.reactive({ userId: 'u', access: { organization_id: 'one', organization_user_id: me, permissions } });
  const confirms: Array<{ title: string; tone?: string }> = [];
  let singleFlight = false;
  let reloads = 0;
  const exports: { useTournamentTeam?: (id: () => string) => State } = {};
  runInNewContext(ts.transpileModule(read('composables/useTournamentTeam.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, onMounted() {}, onBeforeUnmount() {},
    useApi: () => ({ request, organizationId }),
    useAuthStore: () => ({
      get userId() { return auth.userId; }, get access() { return auth.access; },
      hasPermission: (code: string) => auth.access.permissions.includes(code),
      loadAccess: async () => { reloads += 1; },
    }),
    useI18n: () => ({ t }),
    useConfirm: (options: { singleFlight?: boolean }) => { singleFlight = options?.singleFlight === true; return { confirm: async (value: { title: string; tone?: string }) => { confirms.push(value); return accept; } }; },
  });
  return { organizationId, auth, confirms, reloads: () => reloads, state: exports.useTournamentTeam!(() => 'T 1'), singleFlight: () => singleFlight };
}

const routes = (calls: string[], team: helpers.TournamentTeamMember[] = [member()]) => async (path: string, options?: { method?: string }) => {
  calls.push(`${options?.method ?? 'GET'} ${path}`);
  if (path === '/organizations/members') return [{ organization_user_id: 'm2', full_name: 'Oto', is_active: true, role_code: 'operator', email: 'oto@example.test' }];
  if (options?.method) return null;
  return team;
};

test('any member reads the team; only MANAGE_MEMBERS loads the members for the selector', async () => {
  const calls: string[] = [];
  const reader = composable(routes(calls), { permissions: [] });
  await reader.state.load();
  assert.deepEqual(calls, ['GET /tournaments/T%201/team']);
  assert.equal(reader.state.canManage.value, false);
  assert.equal(await reader.state.assign('m2'), false);
  assert.equal(await reader.state.remove(member()), false);
  assert.deepEqual(calls, ['GET /tournaments/T%201/team']);

  const managerCalls: string[] = [];
  const manager = composable(routes(managerCalls));
  await manager.state.load();
  assert.deepEqual(managerCalls, ['GET /tournaments/T%201/team', 'GET /organizations/members']);
  assert.deepEqual(manager.state.candidates.value.map((item) => item.organization_user_id), ['m2']);
  assert.equal(JSON.stringify(manager.state.candidates.value).includes('@'), false);
});

test('assign and remove use useApi, confirm the removal single-flight and reload', async () => {
  const calls: string[] = [];
  const { state, confirms, singleFlight, reloads } = composable(routes(calls));
  assert.equal(await state.assign('m 2'), true);
  assert.ok(calls.includes('PUT /tournaments/T%201/team/m%202'));
  assert.equal(state.notice.value, 'tournamentTeam.assigned');
  assert.equal(await state.remove(member()), true);
  assert.ok(calls.includes('DELETE /tournaments/T%201/team/m1'));
  assert.equal(state.notice.value, 'tournamentTeam.removed');
  assert.equal(singleFlight(), true);
  assert.equal(confirms.length, 1);
  assert.equal(confirms[0]!.tone, 'danger');
  assert.equal(reloads(), 0);
});

test('declining the confirmation removes nothing; changing the own assignment reloads the access', async () => {
  const calls: string[] = [];
  const declined = composable(routes(calls), { accept: false });
  assert.equal(await declined.state.remove(member()), false);
  assert.equal(calls.some((call) => call.startsWith('DELETE')), false);

  const own = composable(routes([]), { me: 'm1' });
  await own.state.assign('m1');
  await own.state.remove(member());
  assert.equal(own.reloads(), 2);
});

test('a failure shows its key and a response after changing organization is discarded', async () => {
  const failing = composable(async (path, options) => { if (options?.method) throw { status: 404, data: { detail: 'Miembro no encontrado' } }; return path.endsWith('/team') ? [] : []; });
  assert.equal(await failing.state.assign('ghost'), false);
  assert.equal(failing.state.actionError.value, 'tournamentTeam.error.member');

  let settle: (value: unknown) => void = () => {};
  const pending = composable((path) => path.endsWith('/team') ? new Promise((resolve) => { settle = resolve; }) : Promise.resolve([]));
  const load = pending.state.load();
  const first = settle;
  pending.organizationId.value = 'two';
  await vue.nextTick();
  first([member({ organization_user_id: 'old' })]);
  await load;
  assert.equal(pending.state.items.value.some((item) => item.organization_user_id === 'old'), false);
});

test('the operation state delegates to canOperateMatch and the access exposes operated tournaments', () => {
  const state = read('composables/useMatchOperationState.ts');
  assert.match(state, /canOperateMatch\(auth\.access, match\.value, operation\.value\?\.officials/);
  assert.match(read('stores/auth.ts'), /operated_tournament_ids\?: string\[\]/);
  const source = read('composables/useTournamentTeam.ts');
  assert.match(source, /useApi\(\)/); assert.doesNotMatch(source, /\$fetch|fetch\(/);
});

const translations = read('composables/useI18n.ts');
const englishStart = translations.indexOf('\n  en: {');
const keysOf = (slice: string) => new Set([...slice.matchAll(/^ {4}'([^']+)':\s*'/gm)].map((match) => match[1]!));
const spanishKeys = keysOf(translations.slice(0, englishStart));
const englishKeys = keysOf(translations.slice(englishStart));

test('the tournamentTeam.* catalogs have exact ES/EN parity and every used key exists', () => {
  const scoped = (keys: Set<string>) => [...keys].filter((key) => key.startsWith('tournamentTeam.'));
  assert.deepEqual(catalogParity(scoped(spanishKeys), scoped(englishKeys)), { onlySpanish: [], onlyEnglish: [] });
  const used = [...read('composables/useTournamentTeam.ts').matchAll(/'(tournamentTeam\.[A-Za-z.]+)'/g), ...read('utils/tournamentTeam.ts').matchAll(/'(tournamentTeam\.[A-Za-z.]+)'/g)].map((match) => match[1]!);
  for (const key of [...used, 'shell.team', 'tournamentTeam.title', 'tournamentTeam.noAddedPermissions']) {
    assert.ok(spanishKeys.has(key) && englishKeys.has(key), key);
  }
});
