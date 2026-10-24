import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const tournamentsPage = readFileSync(
  new URL('../app/pages/workspace/tournaments/[id]/index.vue', import.meta.url),
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

// RF-016/RF-017: la administración de plantillas deja la configuración y pasa a
// su dirección propia; la tarjeta con edad se traslada con ella (H1-T08).
test('no longer renders the roster card or the import form in the configuration', () => {
  assert.doesNotMatch(tournamentsPage, /t\('setup\.age', \{ age: roster\.age \}\)/);
  assert.doesNotMatch(tournamentsPage, /rosters\/bulk/);
  assert.doesNotMatch(tournamentsPage, /id="plantillas"/);
  assert.doesNotMatch(tournamentsPage, /birth_date|birthDate/);
});

// RF-017: la pantalla de plantillas conserva la tarjeta con la edad derivada
// que antes pintaba la configuración (cobertura perdida en H1-T08).
test('the roster screen paints the derived age on the player card', () => {
  const rostersPage = readFileSync(
    new URL('../app/pages/workspace/tournaments/[id]/rosters.vue', import.meta.url),
    'utf8',
  );
  assert.match(rostersPage, /class="roster-card"/);
  assert.match(rostersPage, /t\('setup\.age', \{ age: roster\.age \}\)/);
  // La edad se pinta sin documento ni fecha de nacimiento en la lista.
  const cardStart = rostersPage.indexOf('class="roster-card"');
  const cardEnd = rostersPage.indexOf('</div>', rostersPage.indexOf('roster-card-info'));
  const card = rostersPage.slice(cardStart, cardEnd);
  assert.doesNotMatch(card, /national_id|birth_date|birthDate/);
});

// RF-021: la operación ya no da de alta jugadores (spec 012, H1-T09); el alta
// vive solo en la administración de plantillas, que sigue refrescando su lista.
test('the roster screen is the only one that creates players', () => {
  assert.ok(!matchPage.includes('addRosterPlayer'), 'operation still creates players');

  const rostersPage = readFileSync(
    new URL('../app/pages/workspace/tournaments/[id]/rosters.vue', import.meta.url),
    'utf8',
  );
  const createBody = functionBody(rostersPage, 'createPlayer');
  const createRequest = createBody.indexOf('/rosters');
  const createRefresh = createBody.indexOf('await loadRoster()');
  assert.ok(createRequest >= 0, 'createPlayer must call the roster creation endpoint');
  assert.ok(createRefresh > createRequest, 'createPlayer must refresh the roster after creating a player');
});
