import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  GOOGLE_ERROR_CODES,
  googleCallbackDestination,
  googleErrorKey,
  googleLinkActionVisible,
  googleNoticeKey,
  googleStartRequest,
} from '../app/utils/googleAuth.ts';
import { catalogKeys } from '../app/utils/i18nCatalog.ts';

const TRANSLATIONS_SOURCE = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const ENGLISH_START = TRANSLATIONS_SOURCE.indexOf('\n  en: {');
assert.ok(ENGLISH_START > 0, 'the English catalog is missing');
const SPANISH_KEYS = new Set(catalogKeys(TRANSLATIONS_SOURCE.slice(0, ENGLISH_START)));
const ENGLISH_KEYS = new Set(catalogKeys(TRANSLATIONS_SOURCE.slice(ENGLISH_START)));

// RF-31 / RNF-10: el vocabulario de Google es un catálogo cerrado; cada código
// de error tiene su mensaje en español e inglés y el cliente nunca inventa uno.

test('the error catalog is closed and does not include the success notice', () => {
  assert.equal(GOOGLE_ERROR_CODES.length, 12);
  assert.equal(new Set(GOOGLE_ERROR_CODES).size, 12);
  assert.ok(!(GOOGLE_ERROR_CODES as readonly string[]).includes('GOOGLE_LINK_SUCCESS'));
  assert.deepEqual(new Set(GOOGLE_ERROR_CODES), new Set([
    'GOOGLE_UNAVAILABLE',
    'GOOGLE_CANCELLED',
    'GOOGLE_STATE_INVALID',
    'GOOGLE_IDENTITY_INVALID',
    'ACCOUNT_DISABLED',
    'ACCOUNT_EXISTS_PASSWORD',
    'ACCOUNT_EXISTS_GOOGLE_ONLY',
    'GOOGLE_ALREADY_LINKED',
    'LINK_EMAIL_MISMATCH',
    'LINK_IDENTITY_TAKEN',
    'RATE_LIMITED',
    'ORGANIZATION_SLUG_TAKEN',
  ]));
});

test('every error code has a message in both catalogs', () => {
  for (const code of GOOGLE_ERROR_CODES) {
    const key = googleErrorKey(code);
    assert.equal(key, `google.error.${code}`);
    assert.ok(SPANISH_KEYS.has(key), `missing Spanish key ${key}`);
    assert.ok(ENGLISH_KEYS.has(key), `missing English key ${key}`);
  }
  assert.ok(SPANISH_KEYS.has('google.error.unknown'));
  assert.ok(ENGLISH_KEYS.has('google.error.unknown'));

  const notice = googleNoticeKey('GOOGLE_LINK_SUCCESS');
  assert.equal(notice, 'google.notice.GOOGLE_LINK_SUCCESS');
  assert.ok(SPANISH_KEYS.has(notice));
  assert.ok(ENGLISH_KEYS.has(notice));
});

test('an unknown error code falls back to the generic key', () => {
  assert.equal(googleErrorKey('NOT_A_CODE'), 'google.error.unknown');
  assert.equal(googleErrorKey('account_disabled'), 'google.error.unknown');
  assert.equal(googleErrorKey(''), 'google.error.unknown');
  assert.equal(googleErrorKey(undefined), 'google.error.unknown');
  assert.equal(googleErrorKey(null), 'google.error.unknown');
  assert.equal(googleErrorKey(42), 'google.error.unknown');
  assert.equal(googleErrorKey('ACCOUNT_DISABLED'), 'google.error.ACCOUNT_DISABLED');
});

test('only admitted notices produce a key', () => {
  assert.equal(googleNoticeKey('GOOGLE_LINK_SUCCESS'), 'google.notice.GOOGLE_LINK_SUCCESS');
  assert.equal(googleNoticeKey('SOMETHING_ELSE'), '');
  assert.equal(googleNoticeKey(null), '');
  assert.equal(googleNoticeKey(7), '');
});

test('the start body keeps valid internal destinations untouched', () => {
  assert.deepEqual(googleStartRequest('login', '/workspace'), {
    flow: 'login',
    redirect: '/workspace',
  });
  assert.deepEqual(googleStartRequest('link', '/invitations/abc?token=xyz'), {
    flow: 'link',
    redirect: '/invitations/abc?token=xyz',
  });
  assert.deepEqual(googleStartRequest('login', '/workspace#resumen'), {
    flow: 'login',
    redirect: '/workspace#resumen',
  });
});

test('the start body normalizes every invalid destination to null', () => {
  for (const invalid of [
    undefined,
    null,
    42,
    {},
    '',
    '   ',
    'workspace',
    '//evil.test',
    'https://evil.test/workspace',
    'javascript:alert(1)',
    '/\\evil.test',
    '/workspace\n',
    '/workspace\u0000',
    '/workspace\u0085',
    '/%2F%2Fevil.test',
    '/%5Cevil.test',
  ]) {
    assert.deepEqual(googleStartRequest('login', invalid), {
      flow: 'login',
      redirect: null,
    });
  }
});

test('the redirect limit matches the backend (512 characters)', () => {
  const accepted = `/${'a'.repeat(511)}`;
  const rejected = `/${'a'.repeat(512)}`;

  assert.equal(accepted.length, 512);
  assert.equal(rejected.length, 513);
  assert.equal(googleStartRequest('login', accepted).redirect, accepted);
  assert.equal(googleStartRequest('login', rejected).redirect, null);
});

test('the callback destination accepts only validated internal paths', () => {
  assert.equal(googleCallbackDestination('/invitations/abc?token=xyz'), '/invitations/abc?token=xyz');
  assert.equal(googleCallbackDestination('/organization'), '/organization');
  assert.equal(googleCallbackDestination('/workspace#resumen'), '/workspace#resumen');
});

test('the callback destination rejects external or unsafe values', () => {
  for (const invalid of [
    undefined,
    null,
    42,
    '',
    '//evil.test',
    '///evil.test',
    'https://evil.test',
    'javascript:alert(1)',
    '/\\evil.test',
    '/workspace\u0000',
    '/workspace\n',
    '/%2F%2Fevil.test',
  ]) {
    assert.equal(googleCallbackDestination(invalid, '/login'), '/login');
  }
  assert.equal(googleCallbackDestination(null), '/workspace');
});

test('the Google screens and the optional organization have their texts in both catalogs', () => {
  const required = [
    'google.continue',
    'google.waiting',
    'google.link.title',
    'google.link.description',
    'google.link.linked',
    'google.link.notLinked',
    'google.link.action',
    'google.link.waiting',
    'organization.title',
    'organization.description',
    'organization.name',
    'organization.slug',
    'organization.slugHelp',
    'organization.create',
    'organization.creating',
    'organization.notNow',
    'organization.noActive',
    'organization.slugTaken',
    'organization.error',
  ] as const;

  for (const key of required) {
    assert.ok(SPANISH_KEYS.has(key), `missing Spanish key ${key}`);
    assert.ok(ENGLISH_KEYS.has(key), `missing English key ${key}`);
  }
});

test('the link action is hidden when the identity is already linked or Google is unavailable', () => {
  assert.equal(
    googleLinkActionVisible({ enabled: true, loading: false, linked: true, error: false }),
    false,
  );
  assert.equal(
    googleLinkActionVisible({ enabled: false, loading: false, linked: false, error: false }),
    false,
  );
  assert.equal(
    googleLinkActionVisible({ enabled: true, loading: true, linked: false, error: false }),
    false,
  );
  assert.equal(
    googleLinkActionVisible({ enabled: true, loading: false, linked: false, error: true }),
    false,
  );
  assert.equal(
    googleLinkActionVisible({ enabled: true, loading: false, linked: false, error: false }),
    true,
  );
});
