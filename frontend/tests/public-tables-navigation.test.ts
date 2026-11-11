import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (file: string) => readFileSync(new URL('../app/'+file, import.meta.url), 'utf8');
const page = read('pages/tournaments/[id].vue');

test('031 RF-017: every classification uses a named keyboard scroll region with sticky identity', () => {
  const table = read('components/public/PublicStandingsTable.vue');
  assert.match(table, /import HorizontalScroll from '~\/components\/ui\/HorizontalScroll.vue'/);
  assert.match(table, /<HorizontalScroll :label="caption \|\| t\('public\.standings'\)">/);
  assert.match(table, /<caption class="visually-hidden">\{\{ caption \|\| t\('public\.standings'\) \}\}<\/caption>/);
  assert.match(page, /\$\{group\.groupName \|\| selectedStage\.name\}/);
  assert.match(page, /:show-scope="false"/);
  assert.match(table, /position:\s*sticky/);
  assert.match(table, /table-layout:\s*fixed/);
  assert.match(table, /left:\s*0/);
  assert.match(table, /background:\s*var\(--color-surface\)/);
  assert.equal((page.match(/<PublicStandingsTable\b/g) ?? []).length, 3);
  assert.doesNotMatch(page, /table-scroll/);
  assert.match(page, /function standingsRows\(rows: PublicStanding\[\]\)/);
  assert.match(table, /v-for="standing in rows"/);
  for (const field of ['rank', 'team_name', 'short_code', 'stage_name', 'group_name', 'crest_url', 'played', 'won', 'drawn', 'lost', 'goals_for', 'goals_against', 'goal_difference', 'points', 'fair_play_points']) {
    assert.ok(table.includes(`standing.${field}`), field);
  }
  assert.match(table, /<caption class="visually-hidden">/);
  assert.equal((table.match(/scope="col"/g) ?? []).length, 11);
});

test('031 RF-002/004: native anchors reach public content before the complete team list', () => {
  const home = read('pages/index.vue');
  assert.match(home, /<a href="#public-tournaments" class="public-browse">/);
  assert.match(home, /id="public-tournaments"[^>]*tabindex="-1"/);
  assert.match(page, /<nav class="public-section-nav" :aria-label="t\('public\.sectionNavigation'\)">/);
  for (const id of ['public-results', 'public-stats', 'public-teams']) {
    assert.ok(page.includes(`href="#${id}"`), id);
    assert.ok(page.includes(`id="${id}"`), id);
  }
  assert.ok(page.indexOf('class="container phase-selector"') < page.indexOf('class="container public-teams"'));
  assert.match(home, /to="\/login\?mode=register"/);
  assert.match(home, /to="\/login\?mode=register" variant="secondary"/);
  assert.match(home, /:to="docsUrl"/);
});

test('031 RF-003/018: illustrated score is labelled as example and list text can reflow', () => {
  const home = read('pages/index.vue');
  assert.match(home, /class="example-score"/);
  assert.match(home, /home\.exampleScore/);
  assert.doesNotMatch(home, /t\('home\.live'\)/);
  assert.match(page, /minmax\(0, 1fr\) auto minmax\(0, 1fr\)/);
  assert.match(page, /\.match-team span[^}]*overflow-wrap:\s*anywhere/);
  assert.match(page, /\.match-context, \.match-footer[^}]*flex-wrap:\s*wrap/);
});

test('031 T8: named statistics tabs retain independent scope, server order and original load-more handlers', () => {
  assert.match(page, /class="stats-tabs" role="tablist" :aria-label="t\('public\.stats'\)"/);
  assert.match(page, /const statsStageId = ref<string \| null>\(null\)/);
  assert.match(page, /if \(!statsGeneration\.isCurrent\(generation\)\) return/);
  assert.match(page, /@load-more="loadMorePlayerStats"/);
  assert.match(page, /@load-more="loadMoreTeamStats"/);
  assert.match(page, /if \(!match\.lineup\) return/);
  assert.match(page, /void nextTick\(\(\) => trigger\?\.focus\(\)\)/);
  assert.match(page, /if \(match\.home_score === null \|\| match\.away_score === null\) return '-'/);
  for (const component of ['PublicPlayerStatsTable', 'PublicTeamStatsTable']) {
    const source = read(`components/public/${component}.vue`);
    assert.match(source, /v-for="row in rows"/);
    assert.match(source, /\{\{ row\.rank \}\}/);
    assert.doesNotMatch(source, /\.sort\(|\.filter\(|useApi\(|\$fetch\(|\bfetch\(/);
    assert.match(source, /v-if="!rows.length"/);
    assert.match(source, /v-if="hasMore"/);
    assert.match(source, /:disabled="loadingMore"/);
    assert.match(source, /emit\('load-more'\)/);
  }
});
