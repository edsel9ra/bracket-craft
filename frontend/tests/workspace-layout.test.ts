import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { featureSource } from './support/sources.ts';
import { focusFormAnchor } from '../app/utils/formAnchor.ts';

const source = (file: string) => readFileSync(new URL(`../app/${file}`, import.meta.url), 'utf8');

test('LY-1 places lists before creation forms and scopes header shortcuts to usable forms', () => {
  for (const [file, list, id, permission] of [
    ['members.vue', 'class="member-table"', 'invite-member', '!loading && !pageError'],
    ['tournaments/[id]/calendar.vue', 'id="operacion"', 'match-entry', "!loading && !loadError && canManageTournaments && activeVersion?.status === 'draft' && selectedStageId"],
    ['tournaments/[id]/rosters.vue', 'class="roster-list"', 'player-entry', '!loading && !loadError && teams.length && canManageTournaments'],
  ]) {
    const page = source(`pages/workspace/${file}`);
    assert.ok(page.indexOf(list!) < page.indexOf(`<form id="${id}"`), file);
    assert.match(page, new RegExp(`href="#${id}" @click="focusFormAnchor"`));
    assert.ok(page.includes(permission!));
    assert.match(page, /scroll-margin-top: var\(--space-10\)/);
  }
});

test('form anchors focus the first usable field after native navigation, preserving modified clicks and empty targets', () => {
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const originalFrame = Object.getOwnPropertyDescriptor(globalThis, 'requestAnimationFrame');
  let callback: (() => void) | undefined;
  let focused = false;
  let formExists = true;
  let fieldExists = true;
  Object.defineProperty(globalThis, 'document', { configurable: true, value: {
    getElementById: (id: string) => {
      assert.equal(id, 'add-player');
      return formExists ? { querySelector: (selector: string) => {
        assert.match(selector, /:not\(\[disabled\]\)/);
        assert.match(selector, /:not\(\[type="hidden"\]\)/);
        return fieldExists ? { focus: (options: unknown) => { assert.deepEqual(options, { preventScroll: true }); focused = true; } } : null;
      } } : null;
    },
  } });
  Object.defineProperty(globalThis, 'requestAnimationFrame', { configurable: true, value: (fn: () => void) => { callback = fn; } });
  const event = { button: 0, currentTarget: { hash: '#add-player' } } as unknown as MouseEvent;
  try {
    focusFormAnchor(event);
    assert.equal(focused, false);
    callback!();
    assert.equal(focused, true);
    callback = undefined;
    for (const property of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey', 'defaultPrevented']) focusFormAnchor({ ...event, [property]: true });
    focusFormAnchor({ ...event, button: 1 });
    focusFormAnchor({ ...event, currentTarget: null });
    formExists = false;
    focusFormAnchor(event);
    formExists = true;
    fieldExists = false;
    focusFormAnchor(event);
    assert.equal(callback, undefined);
  } finally {
    for (const [key, descriptor] of [['document', originalDocument], ['requestAnimationFrame', originalFrame]] as const) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else Reflect.deleteProperty(globalThis, key);
    }
  }
});

test('PageHeader owns one condensed section-sized h1 and optional context, state and actions', () => {
  const header = source('components/ui/PageHeader.vue');
  assert.equal(header.match(/<h1\b/g)?.length, 1);
  assert.match(header, /<h1>\{\{ title \}\}<\/h1>/);
  assert.match(header, /font-size: var\(--text-xl\)/);
  assert.match(header, /font-stretch: condensed/);
  assert.doesNotMatch(header, /--text-display/);
  for (const slot of ['context', 'state', 'actions']) assert.match(header, new RegExp(`<slot name="${slot}"`));
});

test('the migrated Workspace pages delegate their only h1 to PageHeader', () => {
  for (const page of ['index.vue', 'members.vue', 'tournaments/[id]/index.vue', 'tournaments/[id]/calendar.vue', 'tournaments/[id]/rosters.vue']) {
    const feature = featureSource(`pages/workspace/${page}`);
    assert.equal(feature.match(/<PageHeader\b/g)?.length, 1, page);
    assert.doesNotMatch(feature, /<h1\b/, page);
  }
  // PR B conserva la cabecera y su h1 sin migrar la presentación de PR C.
  assert.equal(featureSource('pages/workspace/matches/[id].vue').match(/<h1\b/g)?.length, 1);
});

test('the setup orchestrator and extracted files respect their line budgets', () => {
  assert.ok(source('pages/workspace/tournaments/[id]/index.vue').split('\n').length <= 250);
  for (const file of [
    ...['useTournamentSetup', 'useTournamentSetupRules', 'useTournamentSetupCrests'].map((name) => `composables/${name}.ts`),
    ...['SetupHeader', 'SetupChecklist', 'SetupRules', 'SetupTeams', 'SetupStages'].map((name) => `components/workspace/setup/${name}.vue`),
    'components/workspace/setup/types.ts',
  ]) assert.ok(source(file).split('\n').length <= 600, file);
});

test('featureSource follows shared local dependencies once without absorbing UI, assistants or pure utils', () => {
  const feature = featureSource('pages/workspace/tournaments/[id]/index.vue');
  assert.equal(feature.match(/export function useTournamentSetup\(/g)?.length, 1);
  assert.equal(feature.match(/export function useTournamentSetupRules\(/g)?.length, 1);
  assert.equal(feature.match(/async function fetchConfiguration\(/g)?.length, 1);
  assert.match(feature, /<RulesWizard/);
  assert.doesNotMatch(feature, /class="page-header"/);
  assert.doesNotMatch(feature, /export function advanceAfterSave\(/);
  assert.doesNotMatch(feature, /class="rules-wizard"/);
});

test('the operation orchestrator and extracted files respect their line budgets', () => {
  const page = source('pages/workspace/matches/[id].vue');
  assert.ok(page.split('\n').length <= 250);
  assert.ok(page.indexOf('await useAsyncData') < page.indexOf('onMounted(context.mountOperation)'));
  assert.ok(page.indexOf('loadPersistedDraft();') < page.indexOf('onBeforeUnmount(context.unmountOperation)'));
  for (const file of [
    ...['useMatchOperation', 'useMatchOperationState', 'useMatchLineup', 'useMatchEvents', 'useMatchEventsDraft', 'useMatchClose'].map((name) => `composables/${name}.ts`),
    ...['MatchOperationHeader', 'MatchResolutionPanel', 'MatchFieldSection', 'MatchRosterLinks', 'MatchLineupSection', 'MatchEventsSection', 'MatchCloseSection'].map((name) => `components/match/${name}.vue`),
    'components/match/types.ts',
    'components/match/operation.css',
  ]) assert.ok(source(file).split('\n').length <= 600, file);
});

test('featureSource includes the shared operation stylesheet once and preserves section command bindings', () => {
  const feature = featureSource('pages/workspace/matches/[id].vue');
  assert.ok(feature.includes(source('components/match/operation.css')));
  assert.equal(feature.match(/\.realtime-retrying\b/g)?.length, 1);
  for (const command of ['createSegment', 'assignOfficial', 'saveLineup', 'addEvent', 'closeMatch']) {
    assert.ok(feature.includes(`${command === 'assignOfficial' ? '@submit.prevent' : '@click'}="${command}"`));
    assert.ok(feature.includes(`emit('${command}')`));
    assert.ok(feature.includes(`="context.${command}"`));
  }
  assert.doesNotMatch(feature, /provide\(|inject\(/);
  assert.ok(feature.includes('@retry-realtime="context.realtime.retry()"'));
  assert.ok(feature.includes("emit('retryRealtime')"));
});

test('featureSource handles empty source and reports invalid entries and missing local imports', () => {
  const directory = mkdtempSync(join(tmpdir(), 'bracket-feature-'));
  const entry = join(directory, 'empty.vue');
  try {
    writeFileSync(entry, '');
    assert.equal(featureSource(entry), '');
    assert.throws(() => featureSource(''), /entry is required/);
    assert.throws(() => featureSource(join(directory, 'absent.vue')), /ENOENT/);
    writeFileSync(entry, "import Missing from '~/components/workspace/absent-feature.vue';");
    assert.throws(() => featureSource(entry), /Missing local feature source/);
    writeFileSync(entry, '<style scoped src="~/components/match/absent-operation.css" />');
    assert.throws(() => featureSource(entry), /Missing local feature source/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
