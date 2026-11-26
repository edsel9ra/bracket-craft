import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import * as helpers from '../app/utils/exports.ts';
import { catalogParity } from '../app/utils/i18nCatalog.ts';

const read = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const backendCatalog = readFileSync(new URL('../../backend/app/modules/exports/catalog.py', import.meta.url), 'utf8');
const plain = (value: unknown) => JSON.parse(JSON.stringify(value)) as unknown;
const t = (key: string, values?: Record<string, unknown>) => values ? `${key}${JSON.stringify(values)}` : key;

test('the catalog mirrors the five tournament exports, the match report and the row limit of the backend', () => {
  const kinds = backendCatalog.match(/^EXPORT_KINDS[^=]*=\s*\(([\s\S]*?)\)/m)![1]!;
  assert.deepEqual([...helpers.TOURNAMENT_EXPORT_KINDS], [...kinds.matchAll(/"([a-z-]+)"/g)].map((match) => match[1]));
  assert.equal(helpers.MATCH_REPORT_KIND, backendCatalog.match(/^REPORT_KIND = "([a-z-]+)"/m)![1]);
  assert.equal(helpers.EXPORT_MAX_ROWS, Number(backendCatalog.match(/^MAX_ROWS = ([\d_]+)/m)![1]!.replace(/_/g, '')));
  assert.deepEqual(helpers.AUDITED_EXPORT_KINDS, ['rosters']);
});

test('paths are encoded and the language follows the interface', () => {
  assert.equal(helpers.tournamentExportPath('t/1', 'player-stats'), '/tournaments/t%2F1/exports/player-stats');
  assert.equal(helpers.matchReportPath('m 1'), '/matches/m%201/export');
  assert.equal(helpers.exportLang('en'), 'en');
  assert.equal(helpers.exportLang('es'), 'es');
  assert.equal(helpers.exportLang('fr'), 'es');
});

test('file names are ASCII, carry the tournament and the given date, and never read the clock', () => {
  const date = new Date('2026-11-25T23:30:00Z');
  assert.equal(helpers.exportFileName('standings', 'Copa Ñandú 2026 «Sub-17»', date), 'standings-copa-nandu-2026-sub-17-2026-11-25.csv');
  assert.equal(helpers.exportFileName('match-report', 'Halcones vs. Águilas', date), 'match-report-halcones-vs-aguilas-2026-11-25.csv');
  assert.equal(helpers.exportFileName('rosters', '¡¡!!', date), 'rosters-2026-11-25.csv');
  assert.equal(helpers.exportFileName('calendar', 'x'.repeat(200), date).length <= 'calendar-'.length + 60 + '-2026-11-25.csv'.length, true);
  assert.match(helpers.exportFileName('team-stats', 'Ñ'.repeat(80), date), /^[a-z0-9.-]+$/);
  assert.doesNotMatch(read('utils/exports.ts'), /new Date\(\)|Date\.now\(/);
});

test('label keys come from the kind', () => {
  assert.equal(helpers.exportTitleKey('team-stats'), 'export.kind.team-stats.title');
  assert.equal(helpers.exportDescriptionKey('rosters'), 'export.kind.rosters.description');
});

test('API failures map to stable keys, also when the error body arrives as a Blob', async () => {
  assert.equal(await helpers.exportErrorKey({ status: 404 }), 'export.error.notFound');
  assert.equal(await helpers.exportErrorKey({ statusCode: 409, data: { detail: 'MATCH_NOT_CLOSED' } }), 'export.error.notClosed');
  assert.equal(await helpers.exportErrorKey({ status: 422, data: { detail: 'EXPORT_TOO_LARGE' } }), 'export.error.tooLarge');
  const blob = new Blob([JSON.stringify({ detail: 'EXPORT_TOO_LARGE' })], { type: 'application/json' });
  assert.equal(await helpers.exportErrorKey({ status: 422, data: blob }), 'export.error.tooLarge');
  assert.equal(await helpers.exportErrorKey({ status: 409, data: new Blob(['not json']) }), 'export.error.generic');
  assert.equal(await helpers.exportErrorKey({ status: 422, data: { detail: [{ loc: ['query', 'lang'] }] } }), 'export.error.generic');
  assert.equal(await helpers.exportErrorKey(new Error('down')), 'export.error.generic');
});

type State = {
  busy: vue.Ref<string | null>; error: vue.Ref<string>; notice: vue.Ref<string>;
  downloadTournament: (tournamentId: string, kind: helpers.TournamentExportKind, tournamentName: string) => Promise<boolean>;
  downloadMatchReport: (matchId: string, matchName: string) => Promise<boolean>;
};
type Request = (path: string, options?: Record<string, unknown>) => Promise<unknown>;

function composable(request: Request, locale = 'es') {
  const organizationId = vue.ref('one');
  const saved: Array<{ name: string; size: number }> = [];
  const exports: { useExports?: () => State } = {};
  runInNewContext(ts.transpileModule(read('composables/useExports.ts'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, ...vue, require: () => helpers, onBeforeUnmount() {},
    useApi: () => ({ request, organizationId }),
    useI18n: () => ({ t, locale: vue.ref(locale) }),
    saveExportFile: (blob: Blob, name: string) => { saved.push({ name, size: blob.size }); },
  });
  return { organizationId, saved, state: exports.useExports!() };
}

test('a tournament export goes through useApi as a blob in the interface language and saves the file', async () => {
  const calls: Array<[string, unknown]> = [];
  const { state, saved } = composable(async (path, options) => { calls.push([path, options]); return new Blob(['\ufeffa,b\r\n']); }, 'en');
  assert.equal(await state.downloadTournament('t1', 'standings', 'Copa'), true);
  assert.deepEqual(plain(calls), [['/tournaments/t1/exports/standings', { query: { lang: 'en' }, responseType: 'blob' }]]);
  assert.equal(saved.length, 1);
  assert.match(saved[0]!.name, /^standings-copa-\d{4}-\d{2}-\d{2}\.csv$/);
  assert.equal(state.notice.value, `export.done${JSON.stringify({ file: saved[0]!.name })}`);
  assert.equal(state.busy.value, null);
});

test('only one download runs at a time, and a failure leaves a stable key without a file', async () => {
  let settle: (value: unknown) => void = () => {};
  const { state, saved } = composable(() => new Promise((resolve) => { settle = resolve; }));
  const first = state.downloadTournament('t1', 'rosters', 'Copa');
  assert.equal(state.busy.value, 'rosters');
  assert.equal(await state.downloadTournament('t1', 'calendar', 'Copa'), false);
  settle(new Blob(['x'])); assert.equal(await first, true);

  const failing = composable(async () => { throw { status: 409, data: new Blob([JSON.stringify({ detail: 'MATCH_NOT_CLOSED' })]) }; });
  assert.equal(await failing.state.downloadMatchReport('m1', 'A vs B'), false);
  assert.equal(failing.state.error.value, 'export.error.notClosed');
  assert.equal(failing.state.busy.value, null);
  assert.equal(failing.saved.length, 0);
  assert.equal(saved.length, 1);
});

test('the match report is requested from the match', async () => {
  const calls: string[] = [];
  const { state, saved } = composable(async (path) => { calls.push(path); return new Blob(['x']); });
  assert.equal(await state.downloadMatchReport('m1', 'Halcones vs Águilas'), true);
  assert.deepEqual(calls, ['/matches/m1/export']);
  assert.match(saved[0]!.name, /^match-report-halcones-vs-aguilas-/);
});

test('an answer that arrives after an organization change is discarded', async () => {
  let settle: (value: unknown) => void = () => {};
  const { state, saved, organizationId } = composable(() => new Promise((resolve) => { settle = resolve; }));
  const pending = state.downloadTournament('t1', 'rosters', 'Copa');
  organizationId.value = 'two'; await vue.nextTick();
  settle(new Blob(['x']));
  assert.equal(await pending, false);
  assert.equal(saved.length, 0);
  assert.equal(state.busy.value, null);
});

test('exports go through useApi only', () => {
  const source = read('composables/useExports.ts');
  assert.match(source, /useApi\(\)/); assert.doesNotMatch(source, /\$fetch|fetch\(/);
});

const translations = read('composables/useI18n.ts');
const englishStart = translations.indexOf('\n  en: {');
const keysOf = (slice: string) => new Set([...slice.matchAll(/^ {4}'([^']+)':\s*'/gm)].map((match) => match[1]!));
const spanishKeys = keysOf(translations.slice(0, englishStart));
const englishKeys = keysOf(translations.slice(englishStart));

test('the export.* catalogs have exact ES/EN parity', () => {
  const parity = catalogParity([...spanishKeys].filter((key) => key.startsWith('export.')), [...englishKeys].filter((key) => key.startsWith('export.')));
  assert.deepEqual(parity, { onlySpanish: [], onlyEnglish: [] });
});

test('every export key the helpers produce exists in both catalogs', async () => {
  const used = [
    ...[...helpers.TOURNAMENT_EXPORT_KINDS, helpers.MATCH_REPORT_KIND].flatMap((kind) => [helpers.exportTitleKey(kind), helpers.exportDescriptionKey(kind)]),
    await helpers.exportErrorKey({ status: 404 }), await helpers.exportErrorKey({ status: 409, data: { detail: 'MATCH_NOT_CLOSED' } }),
    await helpers.exportErrorKey({ status: 422, data: { detail: 'EXPORT_TOO_LARGE' } }), await helpers.exportErrorKey({ status: 500 }),
    'export.done', 'export.title', 'export.hint', 'export.download', 'export.downloading', 'export.auditNotice', 'export.format',
  ];
  assert.deepEqual(used.filter((key) => !spanishKeys.has(key)), []);
  assert.deepEqual(used.filter((key) => !englishKeys.has(key)), []);
});

test('a file is named after the tournament id when its name is not loaded', () => {
  assert.equal(helpers.exportSubject('Copa Ñandú', '1a2b3c4d-0000-4000-8000-000000000000'), 'Copa Ñandú');
  assert.equal(helpers.exportSubject('  ', '1a2b3c4d-0000-4000-8000-000000000000'), '1a2b3c4d');
  assert.equal(helpers.exportSubject(null, '1a2b3c4d-0000-4000-8000-000000000000'), '1a2b3c4d');
  assert.notEqual(
    helpers.exportFileName('standings', helpers.exportSubject('', '1a2b3c4d-0000'), new Date('2026-11-25T12:00:00Z')),
    helpers.exportFileName('standings', helpers.exportSubject('', '9f8e7d6c-0000'), new Date('2026-11-25T12:00:00Z')),
  );
});
