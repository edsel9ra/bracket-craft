import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  INVITATION_STATUS_LABEL_KEYS,
  MEMBER_STATUS_LABEL_KEYS,
  ROLE_LABEL_KEYS,
  invitationStatusLabelKey,
  memberStatusLabelKey,
  roleLabelKey,
} from '../app/utils/labels.ts';

const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const membersPage = readFileSync(
  new URL('../app/pages/workspace/members.vue', import.meta.url),
  'utf8',
);
const invitationPage = readFileSync(
  new URL('../app/pages/invitations/[token].vue', import.meta.url),
  'utf8',
);

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translations.slice(0, englishStart),
    english: translations.slice(englishStart),
  };
}

test('maps the five organization roles to translation keys', () => {
  assert.deepEqual(ROLE_LABEL_KEYS, {
    owner: 'role.owner',
    administrator: 'role.administrator',
    operator: 'role.operator',
    referee: 'role.referee',
    viewer: 'role.viewer',
  });
  assert.equal(roleLabelKey('owner'), 'role.owner');
  assert.equal(roleLabelKey('administrator'), 'role.administrator');
  assert.equal(roleLabelKey('operator'), 'role.operator');
  assert.equal(roleLabelKey('referee'), 'role.referee');
  assert.equal(roleLabelKey('viewer'), 'role.viewer');
});

test('maps the four invitation statuses to translation keys', () => {
  assert.deepEqual(INVITATION_STATUS_LABEL_KEYS, {
    pending: 'invitationStatus.pending',
    accepted: 'invitationStatus.accepted',
    expired: 'invitationStatus.expired',
    revoked: 'invitationStatus.revoked',
  });
  assert.equal(invitationStatusLabelKey('pending'), 'invitationStatus.pending');
  assert.equal(invitationStatusLabelKey('accepted'), 'invitationStatus.accepted');
  assert.equal(invitationStatusLabelKey('expired'), 'invitationStatus.expired');
  assert.equal(invitationStatusLabelKey('revoked'), 'invitationStatus.revoked');
});

test('maps the two member statuses to translation keys', () => {
  assert.deepEqual(MEMBER_STATUS_LABEL_KEYS, {
    active: 'memberStatus.active',
    inactive: 'memberStatus.inactive',
  });
  assert.equal(memberStatusLabelKey('active'), 'memberStatus.active');
  assert.equal(memberStatusLabelKey('inactive'), 'memberStatus.inactive');
});

test('an unknown or missing value is returned verbatim so it is shown as received', () => {
  // La función devuelve el valor crudo y `t()` lo devuelve tal cual cuando no
  // existe como clave: nunca se inventa una traducción (R29).
  assert.equal(roleLabelKey('steward'), 'steward');
  assert.equal(roleLabelKey(''), '');
  assert.equal(roleLabelKey(null), '');
  assert.equal(roleLabelKey(undefined), '');
  assert.equal(invitationStatusLabelKey('consumed'), 'consumed');
  assert.equal(invitationStatusLabelKey(''), '');
  assert.equal(invitationStatusLabelKey(null), '');
  assert.equal(memberStatusLabelKey('suspended'), 'suspended');
  assert.equal(memberStatusLabelKey(null), '');
});

test('every role and status key exists in both message catalogs', () => {
  const { spanish, english } = catalogSlices();
  const keys = [
    ...Object.values(ROLE_LABEL_KEYS),
    ...Object.values(INVITATION_STATUS_LABEL_KEYS),
    ...Object.values(MEMBER_STATUS_LABEL_KEYS),
    'members.generatedLinkAria',
  ];

  for (const key of keys) {
    assert.match(spanish, new RegExp(`'${key.replace(/\./g, '\\.')}':`), `missing Spanish key ${key}`);
    assert.match(english, new RegExp(`'${key.replace(/\./g, '\\.')}':`), `missing English key ${key}`);
  }
});

test('keeps the Spanish and English catalogs in parity for the new keys', () => {
  const { spanish, english } = catalogSlices();
  const keyPattern = /^\s*'([^']+)':/gm;
  const keysOf = (source: string): Set<string> =>
    new Set(Array.from(source.matchAll(keyPattern), (match) => match[1] ?? ''));

  const spanishKeys = keysOf(spanish);
  const englishKeys = keysOf(english);
  assert.ok(spanishKeys.size > 0, 'the Spanish catalog has no keys');
  assert.ok(englishKeys.size > 0, 'the English catalog has no keys');
  assert.deepEqual([...spanishKeys].sort(), [...englishKeys].sort());
});

test('the members and invitation screens render labels instead of raw codes', () => {
  assert.match(membersPage, /t\(roleLabelKey\(/);
  assert.match(membersPage, /t\(invitationStatusLabelKey\(/);
  assert.match(membersPage, /t\(memberStatusLabelKey\(/);
  assert.match(membersPage, /:aria-label="t\('members\.generatedLinkAria'\)"/);

  assert.match(invitationPage, /t\(roleLabelKey\(/);
  assert.doesNotMatch(invitationPage, /\{\{\s*preview\.role_code\s*\}\}/);
  assert.doesNotMatch(invitationPage, /\{\{\s*preview\.status\s*\}\}/);
});
