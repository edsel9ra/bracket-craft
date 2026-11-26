import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/tournamentTeam.ts';

const PAGE = 'pages/workspace/tournaments/[id]/team.vue';
const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;
const button = vue.defineComponent({ inheritAttrs: false, props: { busy: Boolean, disabled: Boolean, type: { type: String, default: 'button' } }, setup(props, { attrs, slots }) {
  return () => vue.h('button', { ...attrs, type: props.type, disabled: props.busy || props.disabled, 'aria-busy': props.busy || undefined }, slots.default?.());
} });
const passthrough = vue.defineComponent({ inheritAttrs: false, setup(_props, { attrs, slots }) {
  return () => vue.h('div', { 'data-title': attrs.title }, [slots.context?.(), slots.default?.(), slots.actions?.()]);
} });

function compile(globals: Record<string, unknown>): vue.Component {
  const { descriptor } = parse(read(PAGE));
  const javascript = ts.transpileModule(compileScript(descriptor, { id: PAGE, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  runInNewContext(javascript, { exports, ...vue, ...globals, require: (spec: string) => {
    if (spec === 'vue') return vue;
    if (spec.endsWith('utils/tournamentTeam')) return helpers;
    if (spec.endsWith('Button.vue')) return { __esModule: true, default: button };
    if (spec.endsWith('.vue')) return { __esModule: true, default: passthrough };
    throw new Error(`unexpected import ${spec}`);
  } });
  return exports.default!;
}

const member = (overrides: Partial<helpers.TournamentTeamMember> = {}): helpers.TournamentTeamMember => ({
  organization_user_id: 'm1', full_name: 'Vera Vista', organization_role_code: 'viewer', role_code: 'tournament_operator',
  is_active: true, adds_permissions: true, assigned_at: '2026-11-26T10:00:00Z', ...overrides,
});

function teamState(overrides: Record<string, unknown> = {}) {
  return {
    canManage: vue.ref(true), loading: vue.ref(false), busy: vue.ref(false), error: vue.ref(''), actionError: vue.ref(''), notice: vue.ref(''),
    items: vue.ref([member(), member({ organization_user_id: 'm2', full_name: 'Oto Operador', organization_role_code: 'operator', adds_permissions: false })]),
    candidates: vue.ref([{ organization_user_id: 'm3', full_name: 'Rita Árbitra', is_active: true, role_code: 'referee' }]),
    load: async () => {}, assign: async () => true, remove: async () => true,
    ...overrides,
  };
}

async function render(state: Record<string, unknown>) {
  const component = compile({
    definePageMeta() {}, useHead() {}, useI18n: () => ({ t }), useRoute: () => ({ params: { id: 't1' } }),
    useTournamentsStore: () => ({ tournaments: [{ id: 't1', name: 'Copa Ñandú' }] }), useTournamentTeam: () => state,
  });
  const app = vue.createSSRApp(component); app.component('WorkspaceShell', passthrough);
  return (await renderToString(app)).replace(/<!--\[-->|<!--\]-->|<!---->/g, '').replace(/&quot;/g, '"');
}

test('a manager sees the team table, the DA-4 notice only where it applies, the native selector and remove buttons', async () => {
  const html = await render(teamState());
  assert.match(html, /tournamentTeam\.title/);
  assert.match(html, /<table/); assert.match(html, /<th[^>]*scope="col"[^>]*>tournamentTeam\.member<\/th>/);
  assert.match(html, /Vera Vista/); assert.match(html, /roles\.viewer/); assert.match(html, /tournamentTeam\.active/);
  assert.equal(html.match(/tournamentTeam\.noAddedPermissions/g)?.length, 1);
  assert.match(html, /<label for="tournament-team-member">tournamentTeam\.assignLabel<\/label>/);
  assert.match(html, /<select id="tournament-team-member"/);
  assert.match(html, /<option value="m3">Rita Árbitra · roles\.referee<\/option>/);
  assert.doesNotMatch(html, /<option value="m1"/);
  assert.match(html, /<button[^>]*type="submit"[^>]*disabled[^>]*>tournamentTeam\.assign<\/button>/);
  assert.equal(html.match(/>tournamentTeam\.remove</g)?.length, 2);
  assert.match(html, /aria-label="tournamentTeam\.remove: Vera Vista"/);
  assert.doesNotMatch(html, /tournamentTeam\.readOnly/);
});

test('any other member reads the team without the selector or remove buttons', async () => {
  const html = await render(teamState({ canManage: vue.ref(false), candidates: vue.ref([]) }));
  assert.match(html, /Vera Vista/); assert.match(html, /tournamentTeam\.readOnly/);
  assert.doesNotMatch(html, /<select/); assert.doesNotMatch(html, /tournamentTeam\.remove/);
});

test('loading, empty, no candidates, notice and errors are announced', async () => {
  assert.match(await render(teamState({ loading: vue.ref(true), items: vue.ref([]) })), /role="status"[^>]*>tournamentTeam\.loading/);
  const empty = await render(teamState({ items: vue.ref([]), candidates: vue.ref([]) }));
  assert.match(empty, /tournamentTeam\.empty/); assert.doesNotMatch(empty, /<table/);
  assert.match(empty, /tournamentTeam\.noCandidates/); assert.doesNotMatch(empty, /<select/);
  const messages = await render(teamState({ notice: vue.ref('tournamentTeam.assigned'), error: vue.ref('tournamentTeam.error.tournament'), actionError: vue.ref('tournamentTeam.error.member') }));
  assert.match(messages, /role="status"[^>]*>tournamentTeam\.assigned/);
  assert.match(messages, /role="alert"[^>]*>tournamentTeam\.error\.tournament/);
  assert.match(messages, /role="alert"[^>]*>tournamentTeam\.error\.member/);
});

test('the page delegates to useTournamentTeam: assign the selection, remove via the confirming composable', () => {
  const source = read(PAGE);
  assert.match(source, /useTournamentTeam\(\(\) => tournamentId\)/);
  assert.match(source, /await assign\(selected\.value\)/);
  assert.match(source, /remove\(item\)/);
  assert.doesNotMatch(source, /useApi|\$fetch|fetch\(|useConfirm|window\.confirm/);
  assert.match(source, /definePageMeta\(\{ middleware: 'auth' \}\)/);
});

test('the shell links the team section right after exports', () => {
  const shell = read('components/WorkspaceShell.vue');
  assert.match(shell, /\{ key: 'exports', label: t\('shell\.exports'\) \},\n\s*\{ key: 'team', label: t\('shell\.team'\) \}/);
});
