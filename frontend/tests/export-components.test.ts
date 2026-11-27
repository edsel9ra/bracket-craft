import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';
import * as helpers from '../app/utils/exports.ts';
import * as downloads from '../app/utils/exportDownload.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;
const button = vue.defineComponent({ inheritAttrs: false, props: { busy: Boolean, disabled: Boolean }, setup(props, { attrs, slots }) {
  return () => vue.h('button', { ...attrs, type: 'button', disabled: props.busy || props.disabled, 'aria-busy': props.busy || undefined }, slots.default?.());
} });
const passthrough = vue.defineComponent({ inheritAttrs: false, setup(_props, { attrs, slots }) {
  return () => vue.h('div', { 'data-title': attrs.title }, [slots.context?.(), slots.default?.(), slots.actions?.()]);
} });

function compile(path: string, globals: Record<string, unknown>): vue.Component {
  const { descriptor } = parse(read(path));
  const javascript = ts.transpileModule(compileScript(descriptor, { id: path, inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  runInNewContext(javascript, { exports, ...vue, ...globals, require: (spec: string) => {
    if (spec === 'vue') return vue;
    if (spec.endsWith('utils/exports')) return helpers;
    if (spec.endsWith('utils/exportDownload')) return downloads;
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

function exportsState(overrides: Record<string, unknown> = {}) {
  const calls: unknown[][] = [];
  return {
    calls,
    state: {
      busy: vue.ref(null), error: vue.ref(''), notice: vue.ref(''),
      downloadTournament: async (...args: unknown[]) => { calls.push(args); return true; },
      downloadMatchReport: async (...args: unknown[]) => { calls.push(args); return true; },
      ...overrides,
    },
  };
}

function page(state: Record<string, unknown>) {
  return compile('pages/workspace/tournaments/[id]/exports.vue', {
    definePageMeta() {}, useHead() {}, useI18n: () => ({ t }), useRoute: () => ({ params: { id: 't1' } }),
    useTournamentsStore: () => ({ tournaments: [{ id: 't1', name: 'Copa Ñandú' }] }), useExports: () => state,
  });
}

test('the exports page lists the five tournament files with one native button each and the audit notice on rosters', async () => {
  const html = await render(page(exportsState().state));
  assert.match(html, /data-title="export\.title"/);
  assert.match(html, /export\.hint/); assert.match(html, /export\.format/);
  for (const kind of helpers.TOURNAMENT_EXPORT_KINDS) {
    assert.match(html, new RegExp(`<h2 id="export-${kind}-title"[^>]*>export\\.kind\\.${kind}\\.title</h2>`));
    assert.match(html, new RegExp(`export\\.kind\\.${kind}\\.description`));
    assert.match(html, new RegExp(`<button[^>]*aria-describedby="export-${kind}-title[^"]*"[^>]*>\\s*export\\.download`));
  }
  assert.equal(html.match(/<button/g)?.length, helpers.TOURNAMENT_EXPORT_KINDS.length + 1);
  assert.match(html, /export\.format\.pdf/);
  assert.equal(html.match(/export\.downloadPdf/g)?.length, 1);
  assert.match(html, /<button[^>]*aria-describedby="export-standings-title"[^>]*data-format="pdf"[^>]*>\s*export\.downloadPdf/);
  assert.equal(html.match(/export\.auditNotice/g)?.length, 1);
  assert.match(html, /id="export-rosters-audit"[^>]*>export\.auditNotice/);
  assert.match(html, /aria-describedby="export-rosters-title export-rosters-audit"/);
});

test('while one file downloads every button is disabled and the busy one says so', async () => {
  const html = await render(page(exportsState({ busy: vue.ref('calendar:csv') }).state));
  assert.equal(html.match(/<button[^>]*disabled/g)?.length, helpers.TOURNAMENT_EXPORT_KINDS.length + 1);
  assert.match(html, /aria-describedby="export-calendar-title"[^>]*aria-busy="true"[^>]*>\s*export\.downloading/);
  assert.equal(html.match(/export\.downloading/g)?.length, 1);
});

test('the standings PDF has its own busy state and leaves the CSV label alone', async () => {
  const html = await render(page(exportsState({ busy: vue.ref('standings:pdf') }).state));
  assert.equal(html.match(/<button[^>]*disabled/g)?.length, helpers.TOURNAMENT_EXPORT_KINDS.length + 1);
  assert.match(html, /data-format="pdf"[^>]*aria-busy="true"[^>]*>\s*export\.downloading/);
  assert.match(html, /aria-describedby="export-standings-title"[^>]*data-format="csv"[^>]*>\s*export\.download\s*</);
  assert.equal(html.match(/export\.downloading/g)?.length, 1);
});

test('the notice and the error are announced', async () => {
  const html = await render(page(exportsState({ notice: vue.ref('export.done{"file":"a.csv"}'), error: vue.ref('export.error.tooLarge') }).state));
  assert.match(html, /role="status"[^>]*>export\.done\{"file":"a\.csv"\}/);
  assert.match(html, /role="alert"[^>]*>export\.error\.tooLarge/);
});

test('a button downloads its file with the tournament id and name', async () => {
  const source = read('pages/workspace/tournaments/[id]/exports.vue');
  assert.match(source, /keepFocusDuring\(event\.currentTarget, \(\) => downloadTournament\(tournamentId, kind, exportSubject\(tournamentName\.value, tournamentId\), format\)\)/);
  assert.match(source, /hasPdf\(kind\)/);
  assert.doesNotMatch(source, /\$fetch|fetch\(|request\(/);
});

function reportButton(state: Record<string, unknown>) {
  return compile('components/match/MatchReportExport.vue', { useI18n: () => ({ t }), useExports: () => state });
}

test('the match report button only appears for a closed match and announces its result', async () => {
  const { state } = exportsState({ notice: vue.ref('export.done{"file":"m.csv"}') });
  const closed = { id: 'm1', status: 'finished', result_confirmed: true, home_team_name: 'A', away_team_name: 'B' };
  const html = await render(reportButton(state), { match: closed });
  assert.match(html, /<button[^>]*data-format="csv"[^>]*>\s*export\.kind\.match-report\.title/);
  assert.match(html, /<button[^>]*data-format="pdf"[^>]*>\s*export\.kind\.match-report\.pdfTitle/);
  assert.equal(html.match(/<button/g)?.length, 2);
  assert.match(html, /export\.kind\.match-report\.description/);
  assert.match(html, /role="status"[^>]*>export\.done/);
  for (const open of [{ ...closed, status: 'live' }, { ...closed, result_confirmed: false }, { ...closed, status: 'suspended' }]) {
    assert.doesNotMatch(await render(reportButton(state), { match: open }), /<button/);
  }
  const resolved = await render(reportButton(state), { match: { ...closed, status: 'administrative_resolution' } });
  assert.match(resolved, /<button/);
});

test('the match page shows the report button next to the rectification versions', () => {
  const source = read('pages/workspace/matches/[id].vue');
  assert.match(source, /import MatchReportExport from '~\/components\/match\/MatchReportExport\.vue'/);
  assert.match(source, /<MatchReportExport :match="match" \/>/);
  const component = read('components/match/MatchReportExport.vue');
  assert.match(component, /downloadMatchReport\(match\.id, `\$\{match\.home_team_name[^`]*`, format\)/);
});

test('the shell links the exports section of the tournament', () => {
  const shell = read('components/WorkspaceShell.vue');
  assert.match(shell, /\{ key: 'exports', label: t\('shell\.exports'\) \}/);
  const i18n = read('composables/useI18n.ts');
  assert.equal(i18n.match(/'shell\.exports':/g)?.length, 2);
});

test('while the match report PDF downloads both buttons are disabled and only the PDF one says so', async () => {
  const { state } = exportsState({ busy: vue.ref('match-report:pdf') });
  const closed = { id: 'm1', status: 'finished', result_confirmed: true, home_team_name: 'A', away_team_name: 'B' };
  const html = await render(reportButton(state), { match: closed });
  assert.equal(html.match(/<button[^>]*disabled/g)?.length, 2);
  assert.match(html, /data-format="pdf"[^>]*aria-busy="true"[^>]*>\s*export\.downloading/);
  assert.match(html, /data-format="csv"[^>]*>\s*export\.kind\.match-report\.title/);
});
