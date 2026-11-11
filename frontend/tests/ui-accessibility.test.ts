import { featureSource } from './support/sources.ts';
import assert from 'node:assert/strict';
import { readdirSync } from 'node:fs';
import test from 'node:test';
import { checklistPresentation } from '../app/utils/operationChecklist.ts';

const source = (file: string) => featureSource(new URL(`../app/${file}`, import.meta.url));

test('every page declares a document title, including session and error destinations', () => {
  const pages = readdirSync(new URL('../app/pages/', import.meta.url), { recursive: true }) as string[];
  for (const page of pages.filter((file) => file.endsWith('.vue'))) {
    assert.match(source(`pages/${page}`), /useHead\([\s\S]*?title:/, page);
  }
});

test('member role selects and wizard landmarks have contextual names', () => {
  assert.match(source('pages/workspace/members.vue'), /<select :value="member.role_code" :aria-label="[^\n]*member.full_name/);
  assert.match(source('components/wizard/WizardSteps.vue'), /:aria-label="[^\n]*label/);
  assert.match(source('components/wizard/WizardShell.vue'), /<WizardSteps[^>]*:label="title"/);
  assert.match(source('app.vue'), /<nav[^>]*:aria-label="t\('common.languageNavigation'\)"[\s\S]*?<LanguageSwitcher/);
});

test('closed reports render missing live prerequisites neutrally without inventing an assignment', () => {
  assert.deepEqual(checklistPresentation(false, true, 'match.notRequired'), { valid: false, neutral: true, icon: '—', statusKey: 'match.notRequired' });
  assert.equal(checklistPresentation(false, true, 'match.unassigned').statusKey, 'match.unassigned');
  assert.equal(checklistPresentation(true, true, 'match.unassigned').statusKey, 'common.ready');
});

test('open, empty and invalid prerequisites retain their pending warning', () => {
  for (const key of [undefined, '', 'match.notRequired']) {
    assert.deepEqual(checklistPresentation(false, false, key), { valid: false, neutral: false, icon: '!', statusKey: 'common.incomplete' });
  }
  assert.equal(checklistPresentation(false, true).icon, '!');
  assert.equal(checklistPresentation(true, false).statusKey, 'common.ready');
});

test('pitch labels use catalog codes without wrapping and retain localized full names', () => {
  for (const pitch of ['TeamPitch', 'MatchPitch']) {
    const text = source(`components/public/${pitch}.vue`);
    assert.match(text, /class="player-position" :title="positionLabel\(player.position_slot, t\)"/);
    assert.match(text, /aria-hidden="true">\{\{ positionAbbreviation\(player.position_slot, t\) \}\}/);
    assert.match(text, /class="visually-hidden">\{\{ positionLabel\(player.position_slot, t\) \}\}/);
    assert.match(text, /\.player-position\s*\{[^}]*white-space: nowrap/);
  }
  assert.match(source('components/public/PublicLineupModal.vue'), /<TeamPitch :team="team"/);
});

test('public scroll regions are named, keyboard reachable, hinted and motion-safe', () => {
  const scroll = source('components/ui/HorizontalScroll.vue');
  assert.match(scroll, /role="region" :aria-label="label" :aria-describedby="hintId" tabindex="0"/);
  assert.match(scroll, /t\('common.horizontalScroll'\)/);
  assert.match(scroll, /class="scroll-hint">\{\{ t\('common.horizontalScrollHint'\) \}\}/);
  assert.match(scroll, /:id="hintId" class="visually-hidden"/);
  assert.match(scroll, /linear-gradient/);
  assert.match(scroll, /prefers-reduced-motion: reduce/);
  for (const name of ['PublicPlayerStatsTable', 'PublicTeamStatsTable', 'PublicBracket']) {
    const component = source(`components/public/${name}.vue`);
    assert.match(component, /<HorizontalScroll v-else :label=/);
    if (name !== 'PublicBracket') assert.match(component, /td:nth-child\(2\)[^}]*position: sticky; left: 0/);
  }
});

test('scroll hints follow measured overflow rather than the viewport breakpoint', () => {
  const scroll = source('components/ui/HorizontalScroll.vue');
  assert.match(scroll, /scrollWidth > .*clientWidth/);
  assert.match(scroll, /new ResizeObserver\(measure\)/);
  assert.match(scroll, /observer\?\.observe\(child\)/);
  assert.match(scroll, /onUpdated\(observe\)/);
  assert.match(scroll, /onBeforeUnmount\(\(\) => observer\?\.disconnect\(\)\)/);
  assert.match(scroll, /v-show="hasOverflow" class="scroll-hint"/);
  assert.match(scroll, /:class="\{ 'has-overflow': hasOverflow \}"/);
  assert.doesNotMatch(scroll, /@media\s*\(min-width:/);
});
