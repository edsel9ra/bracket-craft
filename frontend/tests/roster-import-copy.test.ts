import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const app = new URL('../app/', import.meta.url);
const rosterPage = readFileSync(new URL('pages/workspace/tournaments/[id]/rosters.vue', app), 'utf8');
const messages = readFileSync(new URL('composables/useI18n.ts', app), 'utf8');
const teamsWizard = readFileSync(new URL('utils/teamsWizard.ts', app), 'utf8');

test('a missing roster CSV uses a dedicated player-file message', () => {
  assert.match(rosterPage, /v-if="!rosterCsvFile"[^>]*>\{\{ t\('tournament\.rosters\.csvEmpty'\) \}\}/);
  assert.doesNotMatch(rosterPage, /t\('setup\.csvEmpty'\)/);
});

test('Spanish and English request a player CSV, not teams', () => {
  assert.match(messages, /'tournament\.rosters\.csvEmpty': 'Selecciona un archivo CSV de jugadores para importar'/);
  assert.match(messages, /'tournament\.rosters\.csvEmpty': 'Select a player CSV file to import'/);
});

test('the team importer keeps its original empty-input message in both locales', () => {
  assert.match(teamsWizard, /fileIssue\(0, 'setup\.csvEmpty'\)/);
  assert.match(messages, /'setup\.csvEmpty': 'Pega al menos un equipo para importar'/);
  assert.match(messages, /'setup\.csvEmpty': 'Paste at least one team to import'/);
});
