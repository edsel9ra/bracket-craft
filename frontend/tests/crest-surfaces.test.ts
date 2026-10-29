import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const PUBLIC_PAGE = readFileSync(
  new URL('../app/pages/tournaments/[id].vue', import.meta.url),
  'utf8',
);
const OPERATION_PAGE = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const LINEUP_MODAL = readFileSync(
  new URL('../app/components/public/PublicLineupModal.vue', import.meta.url),
  'utf8',
);
const PUBLIC_TYPES = readFileSync(
  new URL('../app/utils/publicTournament.ts', import.meta.url),
  'utf8',
);
const WORKSPACE_PAGE = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
  'utf8',
);

// RF-47/RF-48: the anonymous page shows the uploaded crest only; the legacy
// external URL is never requested from a third party there.
test('the public page never paints logo_url', () => {
  assert.doesNotMatch(PUBLIC_PAGE, /logo_url/);
  assert.doesNotMatch(LINEUP_MODAL, /logo_url/);
  for (const file of [PUBLIC_PAGE, LINEUP_MODAL]) {
    const crestUses = file.match(/surface="public"/g) ?? [];
    assert.ok(crestUses.length > 0, 'the public surfaces use TeamCrest in public mode');
    assert.ok(file.includes('TeamCrest'));
  }
});

test('the public page shows the crest on standings, match cards, lineup and teams', () => {
  // Standings rows bind the public row crest.
  assert.match(PUBLIC_PAGE, /standing\.crest_url/);
  // Match cards bind both sides.
  assert.match(PUBLIC_PAGE, /home_team_crest_url/);
  assert.match(PUBLIC_PAGE, /away_team_crest_url/);
  // The tournament team list comes from the additive detail field.
  assert.match(PUBLIC_PAGE, /tournament\.teams/);
  assert.match(PUBLIC_PAGE, /team\.crest_url/);
  // The lineup dialog uses the crest of each published side.
  assert.match(LINEUP_MODAL, /lineup\?\.home\?\.crest_url|lineup\.home\?\.crest_url/);
  assert.match(LINEUP_MODAL, /lineup\?\.away\?\.crest_url|lineup\.away\?\.crest_url/);
});

test('the public types declare the additive crest fields', () => {
  for (const field of [
    'crest_url',
    'home_team_crest_url',
    'away_team_crest_url',
    'PublicTournamentTeam',
  ]) {
    assert.ok(PUBLIC_TYPES.includes(field), `${field} is missing from publicTournament.ts`);
  }
});

// RF-16: the operation header shows both crests and has no write control.
test('the match operation shows the two crests without write controls', () => {
  assert.match(OPERATION_PAGE, /surface="workspace"/);
  assert.match(OPERATION_PAGE, /home_team_crest_url/);
  assert.match(OPERATION_PAGE, /away_team_crest_url/);
  // RF-4: the legacy external URL is the Workspace fallback while there is no crest.
  assert.match(OPERATION_PAGE, /home_team_logo_url/);
  assert.match(OPERATION_PAGE, /away_team_logo_url/);
  assert.match(OPERATION_PAGE, /:logo-url="match\.home_team_logo_url"/);
  const header = OPERATION_PAGE.slice(
    OPERATION_PAGE.indexOf('class="match-heading"'),
    OPERATION_PAGE.indexOf('</section>', OPERATION_PAGE.indexOf('class="match-heading"')),
  );
  assert.ok(header.includes('TeamCrest'), 'the header renders the crest component');
  assert.ok(!header.includes('type="file"'), 'no upload control in the header');
  assert.ok(!header.includes('crest.remove'), 'no delete action in the header');
});


// RF-55/RF-56/RNF-8: the write block is behind the management permission and
// the error is associated with the field and the buttons.
test('the workspace panel hides the write controls from a viewer and is accessible', () => {
  const start = WORKSPACE_PAGE.indexOf('class="crest-actions"');
  assert.ok(start > 0, 'the crest actions block is missing');
  const actions = WORKSPACE_PAGE.slice(start, WORKSPACE_PAGE.indexOf('</li>', start));

  assert.match(
    WORKSPACE_PAGE,
    /v-if="canManageTournaments"\s+class="crest-actions"/,
    'the whole block must be behind canManageTournaments',
  );
  assert.match(actions, /type="file"/);
  assert.match(actions, /photo-picker/);
  assert.match(actions, /crest\.remove/);
  assert.match(actions, /aria-invalid/);
  assert.match(actions, /aria-describedby/);
  assert.match(actions, /role="alert"/);
  assert.match(WORKSPACE_PAGE, /applyCrestResponse/);
});
