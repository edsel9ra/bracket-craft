import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  CREST_ERROR_CODES,
  applyCrestResponse,
  crestActionKey,
  crestErrorMessageKey,
  crestSource,
  teamInitials,
} from '../app/utils/teamCrest.ts';

const UTIL_SOURCE = readFileSync(
  new URL('../app/utils/teamCrest.ts', import.meta.url),
  'utf8',
);
const COMPONENT_SOURCE = readFileSync(
  new URL('../app/components/TeamCrest.vue', import.meta.url),
  'utf8',
);
const TRANSLATIONS_SOURCE = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = TRANSLATIONS_SOURCE.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: TRANSLATIONS_SOURCE.slice(0, englishStart),
    english: TRANSLATIONS_SOURCE.slice(englishStart),
  };
}

// RF-17: the fixed substitute rule. The short code wins with two or more
// characters; otherwise the name; one character is never broken and nothing
// throws on blank values.
test('team initials: two or more characters of the short code', () => {
  assert.equal(teamInitials('Club Atlético', 'CA'), 'CA');
  assert.equal(teamInitials('Club Atlético', 'ca'), 'CA');
  assert.equal(teamInitials('Club Atlético', '  ca  '), 'CA');
  assert.equal(teamInitials('Club Atlético', 'ARG'), 'AR');
});

test('team initials: a one-character short code falls back to the name', () => {
  assert.equal(teamInitials('Club Atlético', 'c'), 'CL');
  assert.equal(teamInitials('Racing', 'R'), 'RA');
});

test('team initials: a blank code uses the name, and a one-character name is kept', () => {
  assert.equal(teamInitials('  Club Atlético  ', ''), 'CL');
  assert.equal(teamInitials('  Club Atlético  ', null), 'CL');
  assert.equal(teamInitials('X', ''), 'X');
  assert.equal(teamInitials('  x  ', null), 'X');
});

test('team initials: never breaks on an empty code and name', () => {
  assert.equal(teamInitials('', ''), '');
  assert.equal(teamInitials('', null), '');
  assert.equal(teamInitials('   ', '  '), '');
});

test('team initials: counts code points, not UTF-16 units', () => {
  assert.equal(teamInitials('𝔸𝔹 Club', ''), '𝔸𝔹');
});

// RF-4: one precedence rule per surface. The public surface never shows the
// legacy external URL; the Workspace uses it only while there is no crest.
test('crest source: the crest wins on every surface', () => {
  assert.equal(
    crestSource({ crestUrl: 'https://signed/crest.png', logoUrl: 'https://old/logo.png', surface: 'workspace' }),
    'crest',
  );
  assert.equal(
    crestSource({ crestUrl: 'https://signed/crest.png', logoUrl: 'https://old/logo.png', surface: 'public' }),
    'crest',
  );
});

test('crest source: the workspace falls back to logo_url while there is no crest', () => {
  assert.equal(
    crestSource({ crestUrl: null, logoUrl: 'https://old/logo.png', surface: 'workspace' }),
    'logo',
  );
  assert.equal(
    crestSource({ crestUrl: '', logoUrl: 'https://old/logo.png', surface: 'workspace' }),
    'logo',
  );
});

test('crest source: the public surface never falls back to logo_url', () => {
  assert.equal(
    crestSource({ crestUrl: null, logoUrl: 'https://old/logo.png', surface: 'public' }),
    'initials',
  );
  assert.equal(
    crestSource({ crestUrl: '', logoUrl: 'https://old/logo.png', surface: 'public' }),
    'initials',
  );
});

test('crest source: without any image the substitute is used', () => {
  assert.equal(
    crestSource({ crestUrl: null, logoUrl: null, surface: 'workspace' }),
    'initials',
  );
  assert.equal(
    crestSource({ crestUrl: null, logoUrl: null, surface: 'public' }),
    'initials',
  );
  assert.equal(
    crestSource({ crestUrl: null, logoUrl: '', surface: 'workspace' }),
    'initials',
  );
});

// RF-19: the row is updated in place from the response; another team's
// response never touches it.
test('apply crest response: first upload retires the legacy logo', () => {
  const team = { team_id: 'team-1', name: 'Club', crest_url: null, logo_url: 'https://old/logo.png' };
  const updated = applyCrestResponse(team, {
    team_id: 'team-1',
    crest_url: 'https://signed/crest.png',
    logo_url: null,
  });
  assert.deepEqual(updated, {
    team_id: 'team-1',
    name: 'Club',
    crest_url: 'https://signed/crest.png',
    logo_url: null,
  });
  assert.equal(team.crest_url, null, 'the original row is not mutated');
});

test('apply crest response: replacement changes the single crest', () => {
  const team = { team_id: 'team-1', crest_url: 'https://signed/one.png', logo_url: null };
  const updated = applyCrestResponse(team, {
    team_id: 'team-1',
    crest_url: 'https://signed/two.png',
    logo_url: null,
  });
  assert.equal(updated?.crest_url, 'https://signed/two.png');
});

test('apply crest response: deletion leaves both fields null', () => {
  const team = { team_id: 'team-1', crest_url: 'https://signed/one.png', logo_url: null };
  const updated = applyCrestResponse(team, {
    team_id: 'team-1',
    crest_url: null,
    logo_url: null,
  });
  assert.equal(updated?.crest_url, null);
  assert.equal(updated?.logo_url, null);
});

test('apply crest response: a response for another team returns null', () => {
  const team = { team_id: 'team-1', crest_url: 'https://signed/one.png' };
  assert.equal(
    applyCrestResponse(team, {
      team_id: 'team-2',
      crest_url: 'https://signed/two.png',
      logo_url: null,
    }),
    null,
  );
});

// RF-55: the action offered by the panel depends on whether the team already
// has a crest; the row never guesses, it asks the shared rule.
test('crest action: load when there is no crest, replace when there is one', () => {
  assert.equal(crestActionKey(false), 'crest.load');
  assert.equal(crestActionKey(true), 'crest.replace');
});

// RF-57 / RNF-9: the eight stable codes map to one key each; anything else is
// unknown and the caller falls back to the generic message.
const EXPECTED_CODES: Record<string, string> = {
  CREST_FILE_EMPTY: 'crest.error.empty',
  CREST_FORMAT_UNSUPPORTED: 'crest.error.format',
  CREST_ANIMATION_UNSUPPORTED: 'crest.error.animation',
  CREST_TOO_LARGE: 'crest.error.tooLarge',
  CREST_NOT_FOUND: 'crest.error.notFound',
  CREST_FORBIDDEN: 'crest.error.forbidden',
  CREST_STORAGE_UNAVAILABLE: 'crest.error.storage',
  CREST_UPLOAD_FAILED: 'crest.error.failed',
};

test('crest error codes: the exact catalog of eight codes', () => {
  assert.deepEqual({ ...CREST_ERROR_CODES }, EXPECTED_CODES);
});

test('crest error codes: maps each known code to its key', () => {
  for (const [code, key] of Object.entries(EXPECTED_CODES)) {
    assert.equal(crestErrorMessageKey(code), key, code);
  }
});

test('crest error codes: an unknown or missing code is null', () => {
  assert.equal(crestErrorMessageKey('CREST_UNKNOWN'), null);
  assert.equal(crestErrorMessageKey(''), null);
  assert.equal(crestErrorMessageKey(null), null);
  assert.equal(crestErrorMessageKey(undefined), null);
  assert.equal(crestErrorMessageKey(42), null);
  assert.equal(crestErrorMessageKey({ code: 'CREST_NOT_FOUND' }), null);
});

// RNF-9: every new key exists exactly once in both catalogs, with parity.
test('crest messages exist in Spanish and English with parity', () => {
  const expectedKeys = [
    'crest.load',
    'crest.replace',
    'crest.remove',
    'crest.fileLabel',
    'crest.confirmRemove',
    'crest.removing',
    'crest.uploading',
    'crest.updated',
    'crest.removed',
    'crest.alt',
    'crest.error.generic',
    'crest.error.selectFile',
    ...Object.values(EXPECTED_CODES),
  ];
  const { spanish, english } = catalogSlices();
  for (const key of expectedKeys) {
    assert.equal(
      spanish.split(`'${key}':`).length - 1,
      1,
      `${key} is not declared exactly once in Spanish`,
    );
    assert.equal(
      english.split(`'${key}':`).length - 1,
      1,
      `${key} is not declared exactly once in English`,
    );
  }
  // The substitute and the image share the same accessible name.
  assert.ok(spanish.includes("'crest.alt': 'Escudo de {team}'"));
  assert.ok(english.includes("'crest.alt': '{team} crest'"));
});

// RNF-8: the component names the image with the team and falls back to the
// initials on error without requesting a new link.
test('the component uses the shared resolver and never retries the link', () => {
  assert.match(COMPONENT_SOURCE, /teamInitials/);
  assert.match(COMPONENT_SOURCE, /crestSource/);
  assert.match(COMPONENT_SOURCE, /t\(['"]crest\.alt['"]/);
  assert.match(COMPONENT_SOURCE, /@error=/);
  assert.doesNotMatch(COMPONENT_SOURCE, /\bfetch\s*\(/);
  assert.doesNotMatch(COMPONENT_SOURCE, /setTimeout|setInterval/);
  assert.doesNotMatch(COMPONENT_SOURCE, /logo_url\s*}/);
});

// The pure utility has no DOM, no clock and no network.
test('the pure utility does not touch the DOM, the clock or the network', () => {
  for (const forbidden of ['document', 'window', 'fetch(', 'Date.', 'performance', 'localStorage']) {
    assert.ok(!UTIL_SOURCE.includes(forbidden), `teamCrest.ts uses ${forbidden}`);
  }
});
