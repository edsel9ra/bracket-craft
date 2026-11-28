import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import * as vue from 'vue';
import { compileScript, parse } from 'vue/compiler-sfc';
import { renderToString } from 'vue/server-renderer';

// Monta el SFC como hace rectification-components.test.ts: imports .vue se
// resuelven a un passthrough y los autoimports de Nuxt se dan como globals.
function component(globals: Record<string, unknown> = {}) {
  const source = readFileSync(new URL('../app/components/match/MatchLiveSection.vue', import.meta.url), 'utf8');
  const { descriptor } = parse(source);
  const javascript = ts.transpileModule(compileScript(descriptor, { id: 'MatchLiveSection', inlineTemplate: true }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: { default?: vue.Component } = {};
  const passthrough = vue.defineComponent({ props: ['forId', 'label'], setup(_, { slots }) { return () => vue.h('div', slots.default?.({ id: 'f', ariaDescribedby: 'd' })); } });
  runInNewContext(javascript, {
    exports, ...vue,
    ref: vue.ref, reactive: vue.reactive, computed: vue.computed, toRefs: vue.toRefs,
    onMounted: vue.onMounted, onBeforeUnmount: vue.onBeforeUnmount, crypto,
    require: (path: string) => path === 'vue' ? vue : path.endsWith('.vue') ? { __esModule: true, default: passthrough } : path.endsWith('/matchLiveClock') ? { clockPresentation: (clock: { state: string; elapsed_us: number | null }, connection: string) => ({ state: clock.state, elapsedUs: clock.elapsed_us ?? 0, acceptedElapsedUs: clock.elapsed_us ?? 0, computed: false, stale: connection !== 'connected' }), displayedClock: (clock: { state: string; elapsed_us: number | null }) => ({ state: clock.state, elapsedUs: clock.elapsed_us ?? 0, acceptedElapsedUs: clock.elapsed_us ?? 0, computed: false }) } : {},
    useI18n: () => ({ t: (key: string) => key }),
    ...globals,
  });
  return exports.default!;
}

const EVENT = {
  clientEventId: 'e1', eventType: 'goal', teamId: 't1', beneficiaryTeamId: null,
  playerId: 'p1', playerOutId: null, playerInId: null, playerInPosition: null, assistPlayerId: null,
  minute: 12, addedMinute: 0, segmentId: 's1', metadata: null,
};
const SHARED = {
  status: 'live', revision: 3, contentRevision: 2, homeScore: 1, awayScore: 0,
  clock: { state: 'running', segmentId: 's1', segmentNumber: 1, elapsedUs: 720_000_000, anchorAt: null, observedAt: 'now' },
  events: [EVENT],
};
const MATCH = { id: 'm', home_team_id: 't1', away_team_id: 't2', home_team_name: 'Local', away_team_name: 'Visita' };

function view(overrides: Partial<{ mode: string; detailVisible: boolean; controlsEnabled: boolean; closeEnabled: boolean }>) {
  return vue.ref({ mode: 'operator', detailVisible: true, controlsEnabled: false, closeEnabled: false, ...overrides });
}
function liveContext(overrides: Record<string, unknown> = {}) {
  return {
    t: (key: string) => key,
    liveView: view({}),
    liveEditor: vue.reactive({ shared: SHARED, pending: [] }),
    liveTransitions: { start: async () => 'sent', suspend: async () => 'sent', resume: async () => 'sent', inFlight: false },
    liveCapture: { capture: async () => 'sent', inFlight: false },
    liveEdit: { beginEdit: () => 'ok', editing: () => null, cancelEdit: () => {}, saveEdit: async () => 'sent', removeFact: async () => 'sent' },
    liveClock: { startClock: async () => 'sent', pauseClock: async () => 'sent', resumeClock: async () => 'sent', inFlight: false },
    liveReview: { beginReview: async () => 'reviewed', currentReceipt: () => null, receiptValid: () => false, inFlight: false },
    liveClose: { confirmClose: async () => 'closed', inFlight: false },
    activeSegment: vue.ref(null),
    realtime: { status: vue.ref('connected') },
    ...overrides,
  };
}

test('sin acceso (hidden) no renderiza nada', async () => {
  const ctx = liveContext({ liveView: view({ mode: 'hidden', detailVisible: false }) });
  const html = await renderToString(vue.createSSRApp(component(), { context: ctx, match: MATCH }));
  assert.equal(html.trim(), '<!--v-if-->');
});

test('lector ve estado y hechos sin controles', async () => {
  const ctx = liveContext({ liveView: view({ mode: 'reader' }) });
  const html = await renderToString(vue.createSSRApp(component(), { context: ctx, match: MATCH }));
  assert.match(html, /live\.section\.title/);
  assert.match(html, /live\.status\.live/);
  assert.match(html, /live\.eventType\.goal/);
  assert.doesNotMatch(html, /live\.capture\.title/);
  assert.doesNotMatch(html, /<button/);
});

test('operador ve captura, transición, reloj y corrección por hecho', async () => {
  const ctx = liveContext({ liveView: view({ controlsEnabled: true }) });
  const html = await renderToString(vue.createSSRApp(component(), { context: ctx, match: MATCH }));
  assert.match(html, /live\.transition\.suspend\.action/);
  assert.match(html, /live\.clock\.pause/);
  assert.match(html, /live\.capture\.title/);
  assert.match(html, /live\.editCorrect\.action/);
  assert.match(html, /live\.editRemove\.action/);
  // La revisión y el cierre no son del operador.
  assert.doesNotMatch(html, /live\.review\.title/);
});

test('closer ve revisión pero no captura', async () => {
  const ctx = liveContext({ liveView: view({ closeEnabled: true }) });
  const html = await renderToString(vue.createSSRApp(component(), { context: ctx, match: MATCH }));
  assert.match(html, /live\.review\.title/);
  assert.match(html, /live\.review\.submit/);
  assert.doesNotMatch(html, /live\.capture\.title/);
});

test('suspendido muestra reanudar y bloquea captura', async () => {
  const ctx = liveContext({ liveView: view({ controlsEnabled: true }), liveEditor: vue.reactive({ shared: { ...SHARED, status: 'suspended' }, pending: [] }) });
  const html = await renderToString(vue.createSSRApp(component(), { context: ctx, match: MATCH }));
  assert.match(html, /live\.status\.suspended/);
  assert.match(html, /live\.transition\.resume\.action/);
  assert.doesNotMatch(html, /live\.capture\.title/);
});
