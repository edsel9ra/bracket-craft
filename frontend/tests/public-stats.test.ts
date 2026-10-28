import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { playerPhotoSource } from '../app/utils/publicStats.ts';
import {
  resolvePublicStatsScope,
  type PublicStage,
} from '../app/utils/publicTournament.ts';

const PLAYER_TABLE = readFileSync(
  new URL('../app/components/public/PublicPlayerStatsTable.vue', import.meta.url),
  'utf8',
);
const TEAM_TABLE = readFileSync(
  new URL('../app/components/public/PublicTeamStatsTable.vue', import.meta.url),
  'utf8',
);
const TEAM_CREST = readFileSync(
  new URL('../app/components/TeamCrest.vue', import.meta.url),
  'utf8',
);
const I18N = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const PUBLIC_PAGE = readFileSync(
  new URL('../app/pages/tournaments/[id].vue', import.meta.url),
  'utf8',
);

function stage(id: string, stage_order: number): PublicStage {
  return { id, name: id, stage_order, stage_type: 'round_robin' };
}

const ES_DEFINITION =
  'Portería imbatida: equipo y portero. Equipo: partido disputado sin goles recibidos (prórroga incluida, penales excluidos). Portero: identificable, titular y al menos 60 minutos. Walkover y resolución administrativa no cuentan.';
const EN_DEFINITION =
  'Clean sheet: team and goalkeeper. Team: disputed match with no goals conceded (extra time included, penalties excluded). Goalkeeper: identifiable, starter and at least 60 minutes. Walkover and administrative resolution do not count.';
const ES_GOALS =
  'Goles: cada gol y gol de penalti acreditado al jugador por el acta. Un autogol no cuenta como gol de quien lo marca.';
const EN_GOALS =
  'Goals: every goal and penalty goal credited to the player in the match report. An own goal does not count as a goal for the player who scores it.';
const ES_GOALS_AGAINST =
  'Goles en contra: goles y penaltis del rival más los autogoles propios; en un walkover, los del marcador configurado.';
const EN_GOALS_AGAINST =
  'Goals against: goals and penalties by the opponent plus own goals; in a walkover, the goals of the configured score.';
const ES_FAIR_PLAY =
  'Puntos de juego limpio: se suman según la disciplina de cada partido, igual que en la clasificación.';
const EN_FAIR_PLAY =
  'Fair-play points: added from each match discipline, as in the standings.';
const ES_EXCLUSIONS =
  'Partidos resueltos fuera del campo (walkover y resolución administrativa): no cuentan para el portero ni para la portería imbatida del equipo, pero sí para el resto de estadísticas de equipo. Un partido incompleto con acta confirmada cuenta como disputado; el portero necesita al menos 60 minutos.';
const EN_EXCLUSIONS =
  'Matches decided off the pitch (walkover and administrative resolution): they do not count for the goalkeeper or the team clean sheet, but they do count for the rest of the team statistics. An incomplete match with a confirmed report counts as played; the goalkeeper still needs at least 60 minutes.';

const DEFINITION_KEYS = [
  'public.goalsDefinition',
  'public.goalsForDefinition',
  'public.goalsAgainstDefinition',
  'public.fairPlayDefinition',
  'public.cleanSheetDefinition',
  'public.statsExclusions',
] as const;

test('RF-031: both stats tables show the clean-sheet legend beside the figure', () => {
  for (const source of [PLAYER_TABLE, TEAM_TABLE]) {
    assert.match(source, /stats-definition/, 'legend paragraph missing');
    assert.match(source, /public\.cleanSheetDefinition/, 'definition key not rendered');
    assert.match(source, /public\.cleanSheets/, 'clean-sheets column missing');
  }
});

test('RF-031: empty states are distinct from load errors', () => {
  assert.match(PLAYER_TABLE, /public\.noPlayerStats/);
  assert.match(TEAM_TABLE, /public\.noTeamStats/);
});

test('RF-010/RF-031: the rule is declared in Spanish and English', () => {
  const occurrences = I18N.split("'public.cleanSheetDefinition':").length - 1;
  assert.equal(occurrences, 2, 'definition must be declared once per catalog');
  assert.ok(I18N.includes(ES_DEFINITION), 'Spanish definition missing or changed');
  assert.ok(I18N.includes(EN_DEFINITION), 'English definition missing or changed');
});

test('RF-031: the Spanish rule names team, goalkeeper, 60 min, extra time and exclusions', () => {
  assert.match(ES_DEFINITION, /equipo/i);
  assert.match(ES_DEFINITION, /portero/i);
  assert.match(ES_DEFINITION, /60/);
  assert.match(ES_DEFINITION, /prórroga/i);
  assert.match(ES_DEFINITION, /Walkover/i);
  assert.match(ES_DEFINITION, /administrativa/i);
});

test('RF-031: the English rule names team, goalkeeper, 60 min, extra time and exclusions', () => {
  assert.match(EN_DEFINITION, /team/i);
  assert.match(EN_DEFINITION, /goalkeeper/i);
  assert.match(EN_DEFINITION, /60/);
  assert.match(EN_DEFINITION, /extra time/i);
  assert.match(EN_DEFINITION, /Walkover/i);
  assert.match(EN_DEFINITION, /administrative/i);
});

// RF-010/RF-018/RF-020/RF-031: every non-obvious figure carries a short
// definition in both catalogs, and the four approved rules keep their exact
// wording so the public text cannot drift from the specification.
test('RF-010: goals, goals against, clean sheets and fair play are defined in Spanish and English', () => {
  assert.ok(I18N.includes(ES_GOALS), 'Spanish goals definition missing or changed');
  assert.ok(I18N.includes(EN_GOALS), 'English goals definition missing or changed');
  assert.ok(I18N.includes(ES_GOALS_AGAINST), 'Spanish goals-against definition missing or changed');
  assert.ok(I18N.includes(EN_GOALS_AGAINST), 'English goals-against definition missing or changed');
  assert.ok(I18N.includes(ES_FAIR_PLAY), 'Spanish fair-play definition missing or changed');
  assert.ok(I18N.includes(EN_FAIR_PLAY), 'English fair-play definition missing or changed');
  assert.ok(I18N.includes(ES_DEFINITION), 'Spanish clean-sheet definition missing or changed');
  assert.ok(I18N.includes(EN_DEFINITION), 'English clean-sheet definition missing or changed');
});

test('RF-010/RF-018/RF-020: each definition states what the figure counts', () => {
  assert.match(ES_GOALS, /gol de penalti/i);
  assert.match(ES_GOALS, /autogol no cuenta/i);
  assert.match(EN_GOALS, /penalty goal/i);
  assert.match(EN_GOALS, /own goal does not count/i);
  assert.match(ES_GOALS_AGAINST, /autogoles propios/i);
  assert.match(ES_GOALS_AGAINST, /walkover/i);
  assert.match(EN_GOALS_AGAINST, /own goals/i);
  assert.match(EN_GOALS_AGAINST, /walkover/i);
  assert.match(ES_FAIR_PLAY, /disciplina/i);
  assert.match(ES_FAIR_PLAY, /clasificación/i);
  assert.match(EN_FAIR_PLAY, /discipline/i);
  assert.match(EN_FAIR_PLAY, /standings/i);
});

// RF-023/RF-029: the legend names the off-the-pitch resolutions and the
// incomplete matches, and says how each one affects the clean sheet. The
// incomplete match counts as played (case 11); the goalkeeper still needs 60
// minutes, so the text never claims that incomplete matches are excluded.
test('RF-023/RF-029: the legend names walkover, administrative resolution and incomplete matches', () => {
  assert.ok(I18N.includes(ES_EXCLUSIONS), 'Spanish exclusions legend missing or changed');
  assert.ok(I18N.includes(EN_EXCLUSIONS), 'English exclusions legend missing or changed');
  for (const text of [ES_EXCLUSIONS, EN_EXCLUSIONS]) {
    assert.match(text, /walkover/i);
    assert.match(text, /administrativ/i);
    assert.match(text, /portero|goalkeeper/i);
    assert.match(text, /60/);
  }
  assert.match(ES_EXCLUSIONS, /partido incompleto/i);
  assert.match(ES_EXCLUSIONS, /cuenta como disputado/i);
  assert.match(EN_EXCLUSIONS, /incomplete match/i);
  assert.match(EN_EXCLUSIONS, /counts as played/i);
});

// RF-010/RF-023/RF-029/RF-031: the definitions live next to each table and are
// associated with it (aria-describedby), not only in a title or hidden text.
test('RF-010: the player table links its visible definitions with aria-describedby', () => {
  assert.match(PLAYER_TABLE, /<table aria-describedby="public-player-stats-definitions">/);
  assert.match(PLAYER_TABLE, /id="public-player-stats-definitions"/);
  assert.match(PLAYER_TABLE, /public\.goalsDefinition/);
  assert.match(PLAYER_TABLE, /public\.cleanSheetDefinition/);
  assert.match(PLAYER_TABLE, /public\.statsExclusions/);
  assert.doesNotMatch(PLAYER_TABLE, /public\.goalsForDefinition/);
});

test('RF-010: the team table links its visible definitions with aria-describedby', () => {
  assert.match(TEAM_TABLE, /<table aria-describedby="public-team-stats-definitions">/);
  assert.match(TEAM_TABLE, /id="public-team-stats-definitions"/);
  assert.match(TEAM_TABLE, /public\.goalsForDefinition/);
  assert.match(TEAM_TABLE, /public\.goalsAgainstDefinition/);
  assert.match(TEAM_TABLE, /public\.cleanSheetDefinition/);
  assert.match(TEAM_TABLE, /public\.fairPlayDefinition/);
  assert.match(TEAM_TABLE, /public\.statsExclusions/);
  assert.doesNotMatch(TEAM_TABLE, /t\('public\.goalsDefinition'\)/);
});

// The legend is real text in the document, not a tooltip or screen-reader-only
// string: the description wrapper is visible and the paragraphs carry the
// shared stats-definition style.
test('RF-010: the definitions are visible paragraphs, not a title attribute', () => {
  for (const source of [PLAYER_TABLE, TEAM_TABLE]) {
    assert.match(source, /class="stats-definitions muted" role="note"/);
    assert.match(source, /<p class="stats-definition">/);
    assert.doesNotMatch(source, /title="[^"]*Definition/);
    assert.doesNotMatch(source, /visually-hidden[^>]*>\{\{ t\('public\.(goals|fairPlay|statsExclusions)/);
  }
});

// No key is declared twice inside a catalog, and every definition exists once
// in each one, so Spanish and English cannot drift apart or shadow each other.
test('RF-010: definition keys are unique per catalog and declared in both', () => {
  const enStart = I18N.indexOf('\n  en: {');
  assert.ok(enStart > 0, 'English catalog not found');
  const catalogs = {
    es: I18N.slice(0, enStart),
    en: I18N.slice(enStart),
  };
  for (const [locale, catalog] of Object.entries(catalogs)) {
    const keys = [...catalog.matchAll(/^ {4}'([^']+)':/gm)].map((match) => match[1]);
    const duplicates = keys.filter((key, index) => keys.indexOf(key) !== index);
    assert.deepEqual(duplicates, [], `${locale} catalog declares duplicate keys`);
    for (const key of DEFINITION_KEYS) {
      assert.equal(
        keys.filter((value) => value === key).length,
        1,
        `${locale} catalog must declare ${key} exactly once`,
      );
    }
  }
});

// RF-007: the photo cell never leaves a hole. The substitute is decided by one
// pure rule: no photo URL means initials, a photo URL means the image, and a
// photo URL that failed to load in this row means the initials again.
test('RF-007: a row without photo_url shows the initials', () => {
  assert.equal(playerPhotoSource({ player_id: 'p1', photo_url: null }), 'initials');
  assert.equal(playerPhotoSource({ player_id: 'p1', photo_url: '' }), 'initials');
  assert.equal(playerPhotoSource({ player_id: 'p1', photo_url: '   ' }), 'initials');
  assert.equal(playerPhotoSource(null), 'initials');
  assert.equal(playerPhotoSource(undefined), 'initials');
});

test('RF-007: a photo that loads keeps the image', () => {
  assert.equal(
    playerPhotoSource({ player_id: 'p1', photo_url: 'https://signed/one.jpg' }, new Map()),
    'photo',
  );
});

test('RF-007: a photo that fails to load shows the initials of that row', () => {
  const row = { player_id: 'p1', photo_url: 'https://signed/one.jpg' };
  const failed = new Map([['p1', 'https://signed/one.jpg']]);
  assert.equal(playerPhotoSource(row, failed), 'initials');
});

test('RF-007: the failure is kept per row, not globally', () => {
  const failed = new Map([['p1', 'https://signed/one.jpg']]);
  assert.equal(
    playerPhotoSource({ player_id: 'p1', photo_url: 'https://signed/one.jpg' }, failed),
    'initials',
  );
  assert.equal(
    playerPhotoSource({ player_id: 'p2', photo_url: 'https://signed/two.jpg' }, failed),
    'photo',
  );
});

test('RF-007: a new photo URL restarts the load attempt', () => {
  const failed = new Map([['p1', 'https://signed/one.jpg']]);
  assert.equal(
    playerPhotoSource({ player_id: 'p1', photo_url: 'https://signed/two.jpg' }, failed),
    'photo',
  );
});

// RF-034: a logically retired player never publishes a photo, so the backend
// answers photo_url null and the row already renders the initials.
test('RF-034: a retired player (photo_url null) shows the initials', () => {
  assert.equal(playerPhotoSource({ player_id: 'retired', photo_url: null }), 'initials');
});

// The component asks the shared rule, records the failure per player and
// renders the initials substitute; it never hides a broken image.
test('RF-007: the player table renders the initials instead of hiding the image', () => {
  assert.match(PLAYER_TABLE, /playerPhotoSource/);
  assert.match(PLAYER_TABLE, /failedPhotoUrls/);
  assert.match(PLAYER_TABLE, /@error="markPhotoFailed\(row\)"/);
  assert.match(PLAYER_TABLE, /player-photo--initials/);
  assert.match(PLAYER_TABLE, /:alt="`\$\{row\.first_name\} \$\{row\.last_name\}`"/);
  assert.doesNotMatch(PLAYER_TABLE, /style\.display/);
  assert.doesNotMatch(PLAYER_TABLE, /hideBrokenImage/);
});

// The team table delegates the same substitute to TeamCrest, which flips to
// the initials on the image error event.
test('RF-007: the team table keeps the crest substitute on image error', () => {
  assert.match(TEAM_TABLE, /<TeamCrest/);
  assert.match(TEAM_CREST, /@error="imageFailed = true"/);
  assert.match(TEAM_CREST, /team-crest--initials/);
});

// RF-021: the default scope is the whole tournament. The resolver never falls
// back to the first stage, so the first request goes out without `stage_id`.
test('RF-021: the default scope is the whole tournament, not the first stage', () => {
  const stages = [stage('s2', 2), stage('s1', 1)];
  assert.deepEqual(resolvePublicStatsScope(stages, null), { stageId: null, groupId: null });
  assert.deepEqual(resolvePublicStatsScope(stages, undefined), { stageId: null, groupId: null });
  assert.deepEqual(resolvePublicStatsScope(stages, ''), { stageId: null, groupId: null });
});

test('RF-021: a tournament without stages has no scope to choose', () => {
  assert.deepEqual(resolvePublicStatsScope([], 's1'), { stageId: null, groupId: null });
  assert.deepEqual(resolvePublicStatsScope(null, 's1'), { stageId: null, groupId: null });
});

// RF-021: the phase filter is an explicit user action.
test('RF-021: choosing a phase sends the stage filter', () => {
  const stages = [stage('s2', 2), stage('s1', 1)];
  assert.deepEqual(resolvePublicStatsScope(stages, 's2'), { stageId: 's2', groupId: null });
});

test('RF-021: an unknown phase falls back to the whole tournament', () => {
  const stages = [stage('s1', 1)];
  assert.deepEqual(resolvePublicStatsScope(stages, 'missing'), { stageId: null, groupId: null });
});

// RF-021: the choice is reversible. Clearing it must produce the same value as
// the initial state, so the tables stop sending `stage_id` again.
test('RF-021: returning to the whole tournament drops the stage filter', () => {
  const stages = [stage('s1', 1)];
  const initial = resolvePublicStatsScope(stages, null);
  assert.deepEqual(resolvePublicStatsScope(stages, 's1'), { stageId: 's1', groupId: null });
  assert.deepEqual(resolvePublicStatsScope(stages, ''), initial);
  assert.deepEqual(resolvePublicStatsScope(stages, null), initial);
  assert.deepEqual(resolvePublicStatsScope(stages, undefined), initial);
});

// The group filter only means something inside a chosen phase.
test('RF-021: a group filter requires a chosen phase', () => {
  const stages = [stage('s1', 1)];
  const standings = [{
    stage_id: 's1',
    group_id: 'g1',
    group_name: 'Group 1',
  }] as any;
  assert.deepEqual(resolvePublicStatsScope(stages, null, 'g1', standings), { stageId: null, groupId: null });
  assert.deepEqual(resolvePublicStatsScope(stages, 's1', 'g1', standings), { stageId: 's1', groupId: 'g1' });
  assert.deepEqual(resolvePublicStatsScope(stages, 's1', 'missing-group', standings), { stageId: 's1', groupId: null });
});

// Source guards: the page starts with the whole tournament and only sends the
// phase the control resolves.
test('RF-021: the page starts with no phase selected and resolves the scope', () => {
  assert.match(PUBLIC_PAGE, /const statsStageId = ref<string \| null>\(null\)/);
  assert.match(PUBLIC_PAGE, /resolvePublicStatsScope\(/);
  assert.match(PUBLIC_PAGE, /function selectStatsStage\(/);
  assert.match(PUBLIC_PAGE, /if \(scope\.stageId\) params\.set\('stage_id', scope\.stageId\);/);
  assert.doesNotMatch(PUBLIC_PAGE, /params\.set\('stage_id', selectedStageId\.value\)/);
  assert.doesNotMatch(PUBLIC_PAGE, /params\.set\('group_id', selectedGroupId\.value\)/);
  assert.doesNotMatch(PUBLIC_PAGE, /loadPlayerStatsFirst|loadTeamStatsFirst/);
});

test('RF-021: the scope control is labelled and offers the whole tournament', () => {
  assert.match(PUBLIC_PAGE, /<label for="public-stats-scope">\{\{ t\('public\.statsScope'\) \}\}<\/label>/);
  assert.match(PUBLIC_PAGE, /<select id="public-stats-scope"/);
  assert.match(PUBLIC_PAGE, /<option value="">\{\{ t\('public\.statsWholeTournament'\) \}\}<\/option>/);
  assert.match(PUBLIC_PAGE, /<option v-for="stage in stages" :key="stage\.id" :value="stage\.id">/);
});

test('RF-021: the scope control is only offered when the tournament has phases', () => {
  assert.match(PUBLIC_PAGE, /<div v-if="stageAwareLayout" class="stats-scope">/);
});

test('RF-021: the scope is declared in Spanish and English', () => {
  assert.equal(I18N.split("'public.statsScope':").length - 1, 2);
  assert.equal(I18N.split("'public.statsWholeTournament':").length - 1, 2);
  assert.ok(I18N.includes("'public.statsWholeTournament': 'Torneo completo'"));
  assert.ok(I18N.includes("'public.statsWholeTournament': 'Whole tournament'"));
});

// RF-009/RF-021: changing the scope restarts the pagination and a slow answer
// from a previous scope cannot overwrite the current one.
test('RF-021: a scope change restarts the pagination and keeps one current answer', () => {
  assert.match(PUBLIC_PAGE, /const statsGeneration = createRequestGeneration\(\);/);
  assert.match(PUBLIC_PAGE, /function statsQuery\(scope: PublicStatsScope, offset: number\)/);
  assert.match(PUBLIC_PAGE, /statsQuery\(scope, 0\)/);
  assert.match(PUBLIC_PAGE, /watch\(statsScopeKey,/);
  assert.match(PUBLIC_PAGE, /if \(!statsGeneration\.isCurrent\(generation\)\) return;/);
});

// RF-006/RF-022: both tables show the position column and print the rank the
// server computed over the whole set (shared by ties, stable when paginating).
test('RF-022: both stats tables render the position column with the server rank', () => {
  for (const source of [PLAYER_TABLE, TEAM_TABLE]) {
    assert.match(source, /rank: number;/, 'rank missing from the row type');
    assert.match(
      source,
      /<th scope="col">\{\{ t\('public\.position'\) \}\}<\/th>/,
      'position heading missing',
    );
    assert.match(source, /<td>\{\{ row\.rank \}\}<\/td>/, 'rank value not rendered');
  }
});

// The position is the first column, before the player/team cell.
test('RF-022: the position is the first column of both tables', () => {
  for (const source of [PLAYER_TABLE, TEAM_TABLE]) {
    const position = source.indexOf("t('public.position')");
    const identity = source.indexOf("<th scope=\"col\">{{ t('public.player') }}</th>") >= 0
      ? source.indexOf("<th scope=\"col\">{{ t('public.player') }}</th>")
      : source.indexOf("<th scope=\"col\">{{ t('setup.teams') }}</th>");
    assert.ok(position > 0 && identity > 0, 'headers missing');
    assert.ok(position < identity, 'the position column must come first');
  }
});

test('RF-022: the position heading exists in Spanish and English', () => {
  assert.equal(I18N.split("'public.position':").length - 1, 2);
  assert.ok(I18N.includes("'public.position': 'Posición'"), 'Spanish heading missing');
  assert.ok(I18N.includes("'public.position': 'Position'"), 'English heading missing');
});
