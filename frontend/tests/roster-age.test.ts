import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tournamentsPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id].vue', import.meta.url),
  'utf8',
);
const matchPage = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function interfaceBody(source: string, name: string): string {
  const match = new RegExp(`interface ${name} \\{([\\s\\S]*?)\\n\\}`).exec(source);
  assert.ok(match, `interface ${name} is missing`);
  return match[1] ?? '';
}

function functionBody(source: string, name: string): string {
  const signature = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`).exec(source);
  assert.ok(signature, `function ${name} is missing`);
  const start = source.indexOf('{', signature.index + signature[0].length);
  assert.ok(start >= 0, `function ${name} has no body`);
  let depth = 0;
  for (let index = start; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  assert.fail(`function ${name} has an unbalanced body`);
}

test('adds the age label to the Spanish and English message catalogs', () => {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');

  const spanishMessages = translations.slice(0, englishStart);
  const englishMessages = translations.slice(englishStart);

  assert.match(spanishMessages, /'setup\.age': 'Edad: \{age\}'/);
  assert.match(englishMessages, /'setup\.age': 'Age: \{age\}'/);
});

test('keeps the Spanish and English message catalogs in parity', () => {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');

  const keyPattern = /^\s*'([^']+)':/gm;
  const keysOf = (source: string): Set<string> =>
    new Set(Array.from(source.matchAll(keyPattern), (match) => match[1] ?? ''));

  const spanishKeys = keysOf(translations.slice(0, englishStart));
  const englishKeys = keysOf(translations.slice(englishStart));

  assert.ok(spanishKeys.size > 0, 'the Spanish catalog has no keys');
  assert.ok(englishKeys.size > 0, 'the English catalog has no keys');
  assert.deepEqual(
    [...spanishKeys].sort(),
    [...englishKeys].sort(),
    'Spanish and English must define exactly the same translation keys',
  );
  assert.ok(spanishKeys.has('setup.age'));
  assert.ok(englishKeys.has('setup.age'));
});

test('renders age in the workspace roster card from the roster listing', () => {
  const rosterSummary = interfaceBody(tournamentsPage, 'RosterSummary');
  assert.match(rosterSummary, /^\s*age: number;?\s*$/m);

  assert.match(tournamentsPage, /t\('setup\.age', \{ age: roster\.age \}\)/);
  assert.match(
    tournamentsPage,
    /fetchPaged<RosterSummary>\(`\/tournaments\/\$\{tournamentId\}\/rosters`\)/,
  );
  assert.doesNotMatch(tournamentsPage, /birth_date|birthDate/);
});

test('refreshes the roster listing after importing and after creating a player', () => {
  const importBody = functionBody(tournamentsPage, 'importRoster');
  const importRequest = importBody.indexOf('/rosters/bulk');
  const importRefresh = importBody.indexOf('await loadConfiguration()');
  assert.ok(importRequest >= 0, 'importRoster must call the roster import endpoint');
  assert.ok(importRefresh > importRequest, 'importRoster must reload the configuration after importing');

  const createBody = functionBody(matchPage, 'addRosterPlayer');
  const createRequest = createBody.indexOf('/rosters');
  const createRefresh = createBody.indexOf('await refreshOperation()');
  assert.ok(createRequest >= 0, 'addRosterPlayer must call the roster creation endpoint');
  assert.ok(createRefresh > createRequest, 'addRosterPlayer must refresh the operation after creating a player');
});
