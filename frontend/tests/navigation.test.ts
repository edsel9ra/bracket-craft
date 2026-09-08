import assert from 'node:assert/strict';
import test from 'node:test';

import { getApiStatus, isForbidden, isUnauthorized } from '../utils/api.ts';
import { safeInternalRedirect } from '../utils/navigation.ts';
import { isSafeCsrfToken, normalizeOrganizationId, normalizeUuid } from '../utils/validation.ts';

test('accepts a same-origin internal path', () => {
  assert.equal(safeInternalRedirect('/workspace?tab=matches'), '/workspace?tab=matches');
});

test('rejects external and protocol-relative redirects', () => {
  assert.equal(safeInternalRedirect('https://evil.example', '/workspace'), '/workspace');
  assert.equal(safeInternalRedirect('//evil.example/path', '/workspace'), '/workspace');
  assert.equal(safeInternalRedirect('/\\\\evil.example', '/workspace'), '/workspace');
});

test('accepts only valid organization UUIDs', () => {
  const organizationId = '123e4567-e89b-12d3-a456-426614174000';
  assert.equal(normalizeOrganizationId(` ${organizationId} `), organizationId);
  assert.equal(normalizeOrganizationId('not-an-organization'), null);
});

test('normalizes public tournament UUIDs', () => {
  const tournamentId = '123e4567-e89b-12d3-a456-426614174000';
  assert.equal(normalizeUuid(` ${tournamentId} `), tournamentId);
  assert.equal(normalizeUuid('not-a-uuid'), null);
});

test('classifies API failures and rejects unsafe CSRF values', () => {
  assert.equal(getApiStatus({ statusCode: 401 }), 401);
  assert.equal(isUnauthorized({ status: 401 }), true);
  assert.equal(isForbidden({ statusCode: 403 }), true);
  assert.equal(isSafeCsrfToken('token-value'), true);
  assert.equal(isSafeCsrfToken('token\nvalue'), false);
});
