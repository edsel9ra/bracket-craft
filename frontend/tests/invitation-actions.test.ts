import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  beginInvitationOperation,
  invitationActionAriaKey,
  invitationActionConfirmKey,
  invitationActionErrorKey,
  invitationActionLabelKey,
  invitationActionsFor,
  invitationControlsDisabled,
  type InvitationOperation,
} from '../app/utils/invitationActions.ts';
import {
  INVITATION_CONFLICT_CODES,
  INVITATION_CONFLICT_MESSAGE_KEYS,
  invitationConflictCode,
  invitationConflictMessageKey,
  type InvitationConflictCode,
} from '../app/utils/invitationErrors.ts';

const translations = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const membersPage = readFileSync(
  new URL('../app/pages/workspace/members.vue', import.meta.url),
  'utf8',
);
const membersScript = membersPage.slice(0, membersPage.indexOf('</script>'));
const membersTemplate = membersPage.slice(membersPage.indexOf('<template>'));

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translations.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translations.slice(0, englishStart),
    english: translations.slice(englishStart),
  };
}

function hasKey(source: string, key: string): boolean {
  return new RegExp(`'${key.replace(/\./g, '\\.')}':`).test(source);
}

const OPERATIONS: InvitationOperation[] = ['creating', 'resending', 'reopening', 'revoking'];

test('offers one action set per invitation status (RF-005)', () => {
  assert.deepEqual(invitationActionsFor('pending'), ['resend', 'revoke']);
  assert.deepEqual(invitationActionsFor('expired'), ['resend']);
  assert.deepEqual(invitationActionsFor('revoked'), ['reopen']);
  assert.deepEqual(invitationActionsFor('accepted'), []);
});

test('an unknown or missing status offers no action (RF-005)', () => {
  assert.deepEqual(invitationActionsFor('consumed'), []);
  assert.deepEqual(invitationActionsFor(''), []);
  assert.deepEqual(invitationActionsFor(null), []);
  assert.deepEqual(invitationActionsFor(undefined), []);
});

test('each action has its own label, error and aria keys (RF-005, RF-007)', () => {
  const labelKeys = [
    invitationActionLabelKey('resend'),
    invitationActionLabelKey('reopen'),
    invitationActionLabelKey('revoke'),
  ];
  assert.deepEqual(labelKeys, ['members.resend', 'members.reopen', 'members.revoke']);
  assert.equal(new Set(labelKeys).size, labelKeys.length);
  assert.notEqual(invitationActionLabelKey('resend'), invitationActionLabelKey('reopen'));

  const errorKeys = [
    invitationActionErrorKey('resend'),
    invitationActionErrorKey('reopen'),
    invitationActionErrorKey('revoke'),
  ];
  assert.deepEqual(errorKeys, ['members.noResend', 'members.noReopen', 'members.noRevoke']);
  assert.equal(new Set(errorKeys).size, errorKeys.length);

  const ariaKeys = [
    invitationActionAriaKey('resend'),
    invitationActionAriaKey('reopen'),
    invitationActionAriaKey('revoke'),
  ];
  assert.deepEqual(ariaKeys, ['members.resendAria', 'members.reopenAria', 'members.revokeAria']);
  assert.equal(new Set(ariaKeys).size, ariaKeys.length);
});

test('only reopening adds a new confirmation step (RF-006)', () => {
  assert.equal(invitationActionConfirmKey('reopen'), 'members.confirmReopen');
  assert.equal(invitationActionConfirmKey('resend'), null);
  assert.equal(invitationActionConfirmKey('revoke'), null);
});

test('controls are enabled only while no invitation operation is running (RF-006)', () => {
  assert.equal(invitationControlsDisabled('idle'), false);
  for (const operation of OPERATIONS) {
    assert.equal(invitationControlsDisabled(operation), true, `${operation} must disable the controls`);
  }
});

test('a second activation while an operation runs starts no request (RF-006)', () => {
  assert.equal(beginInvitationOperation('idle', 'reopening'), 'reopening');
  assert.equal(beginInvitationOperation('idle', 'resending'), 'resending');
  assert.equal(beginInvitationOperation('reopening', 'resending'), null);
  assert.equal(beginInvitationOperation('revoking', 'revoking'), null);
  assert.equal(beginInvitationOperation('creating', 'reopening'), null);
});

test('maps the four stable 409 codes to four distinct translation keys (RF-007)', () => {
  assert.deepEqual([...INVITATION_CONFLICT_CODES].sort(), [
    'INVITATION_ALREADY_ACCEPTED',
    'INVITATION_NOT_REVOKED',
    'INVITATION_OTHER_PENDING',
    'INVITATION_REVOKED_RESEND',
  ]);

  const keys = INVITATION_CONFLICT_CODES.map((code) => INVITATION_CONFLICT_MESSAGE_KEYS[code]);
  assert.equal(new Set(keys).size, keys.length, 'each conflict code needs its own message');
  assert.deepEqual(keys, [
    'members.conflictNotRevoked',
    'members.conflictOtherPending',
    'members.conflictAccepted',
    'members.conflictRevokedResend',
  ]);
});

test('reads the conflict code from the error body, ignoring unknown shapes (RF-007)', () => {
  assert.equal(invitationConflictCode({ data: { detail: 'x', code: 'INVITATION_NOT_REVOKED' } }), 'INVITATION_NOT_REVOKED');
  assert.equal(invitationConflictCode({ data: { code: 'INVITATION_OTHER_PENDING' } }), 'INVITATION_OTHER_PENDING');
  assert.equal(invitationConflictCode({ data: { detail: 'solo texto' } }), null);
  assert.equal(invitationConflictCode({ data: { code: 42 } }), null);
  assert.equal(invitationConflictCode({ data: { code: 'INVITATION_UNKNOWN' } }), null);
  assert.equal(invitationConflictCode({ status: 409 }), null);
  assert.equal(invitationConflictCode(null), null);
  assert.equal(invitationConflictCode(new Error('boom')), null);
});

test('resolves a message key per code and falls back to null (RF-007)', () => {
  for (const code of INVITATION_CONFLICT_CODES) {
    const key = invitationConflictMessageKey(code);
    assert.ok(key, `${code} must resolve to a key`);
    assert.equal(key, INVITATION_CONFLICT_MESSAGE_KEYS[code]);
  }
  assert.equal(invitationConflictMessageKey(null), null);
  assert.equal(invitationConflictMessageKey(undefined), null);
  assert.equal(invitationConflictMessageKey(''), null);
  assert.equal(invitationConflictMessageKey('INVITATION_UNKNOWN'), null);
  assert.equal(invitationConflictMessageKey(409 as unknown as string), null);
});

test('every new key exists in both catalogs (RF-005, RF-006, RF-007)', () => {
  const { spanish, english } = catalogSlices();
  const keys = [
    'members.reopen',
    'members.confirmReopen',
    'members.reopenAria',
    'members.resendAria',
    'members.revokeAria',
    'members.noReopen',
    'members.conflictAccepted',
    'members.conflictRevokedResend',
    'members.conflictOtherPending',
    'members.conflictNotRevoked',
    ...INVITATION_CONFLICT_CODES.map((code: InvitationConflictCode) => INVITATION_CONFLICT_MESSAGE_KEYS[code]),
  ];

  for (const key of new Set(keys)) {
    assert.ok(hasKey(spanish, key), `missing Spanish key ${key}`);
    assert.ok(hasKey(english, key), `missing English key ${key}`);
  }
});

test('the invitation row renders the actions decided by invitationActionsFor (RF-005)', () => {
  assert.match(
    membersTemplate,
    /v-for="action in invitationActionsFor\(invitation\.status\)"/,
    'each row must render exactly the actions the pure helper returns',
  );
  assert.match(membersTemplate, /\{\{\s*t\(invitationActionLabelKey\(action\)\)\s*\}\}/);
  assert.doesNotMatch(
    membersPage,
    /status !== 'accepted'/,
    'resend must not be re-decided in the template: the helper owns the per-status choice',
  );
  assert.doesNotMatch(membersTemplate, /invitation\.status === 'revoked'/);
  assert.doesNotMatch(membersTemplate, /invitation\.status === 'expired'/);
  assert.doesNotMatch(
    membersTemplate,
    /Reabrir|Reopen/,
    'the reopen label must come from the active catalog, never a fixed literal',
  );
});

test('reopening asks for confirmation before the request and a second activation sends nothing (RF-006)', () => {
  assert.match(membersScript, /invitationActionConfirmKey\(action\)/);
  assert.match(membersScript, /window\.confirm\(t\(confirmKey\)\)/);
  assert.match(membersScript, /beginInvitationOperation\(invitationOperation\.value,/);
  assert.match(membersScript, /if \(operation === null\) return;/);
  assert.match(membersTemplate, /:disabled="invitationControlsDisabled\(invitationOperation\)"/);

  const confirmIndex = membersScript.indexOf('window.confirm(t(confirmKey))');
  const reopenRequestIndex = membersScript.indexOf('/organizations/invitations/${invitation.id}/reopen');
  assert.ok(confirmIndex > 0, 'reopening must ask for confirmation');
  assert.ok(reopenRequestIndex > 0, 'reopening must call the reopen endpoint');
  assert.ok(confirmIndex < reopenRequestIndex, 'the confirmation must run before the request');
});

test('reopening and resending go through useApi and show the link emitted by the server (RF-007)', () => {
  assert.match(membersScript, /const \{ request \} = useApi\(\)/);
  assert.doesNotMatch(membersScript, /\$fetch\s*\(/);
  assert.doesNotMatch(membersScript, /window\.fetch\s*\(/);
  assert.match(membersScript, /\/organizations\/invitations\/\$\{invitation\.id\}\/reopen/);
  assert.match(membersScript, /\/organizations\/invitations\/\$\{invitation\.id\}\/resend/);
  assert.match(
    membersScript,
    /generatedLink\.value = updated\.invite_url \|\| null;/,
    'the shown link must be the one returned by the operation',
  );
  assert.match(membersScript, /Object\.assign\(invitation, updated\)/);
});

test('the 409 is translated from its stable code with an error fallback (RF-007)', () => {
  assert.match(membersScript, /invitationConflictMessageKey\(invitationConflictCode\(cause\)\)/);
  assert.match(membersScript, /return t\(key\);/);
  assert.match(membersScript, /errorMessage\(cause, t\(fallbackKey\)\)/);
});

test('the invitation operation and the member directory keep separate busy states', () => {
  assert.match(membersScript, /const invitationOperation = ref<InvitationOperation>\('idle'\)/);
  assert.match(membersScript, /const saving = ref\(false\)/);

  const invitePanelStart = membersTemplate.indexOf("members.inviteEyebrow");
  const directoryPanelStart = membersTemplate.indexOf("members.directoryEyebrow");
  assert.ok(invitePanelStart > 0 && directoryPanelStart > invitePanelStart);
  const invitationPanels = membersTemplate.slice(invitePanelStart, directoryPanelStart);
  assert.doesNotMatch(
    invitationPanels,
    /saving/,
    'the invitation form and rows must be governed by invitationOperation, not by saving',
  );
  assert.match(invitationPanels, /invitationControlsDisabled\(invitationOperation\)/);
});

test('each invitation control names its role and expiry date, never the email (RF-005)', () => {
  assert.match(membersTemplate, /:aria-label="invitationAria\(action, invitation\)"/);
  assert.match(membersScript, /invitationActionAriaKey\(action\)/);
  assert.match(membersScript, /role: t\(roleLabelKey\(invitation\.role_code\)\)/);
  assert.match(membersScript, /date: formatDate\(invitation\.expires_at\)/);
  assert.doesNotMatch(membersPage, /aria-label[^\n]*invitation\.email/);
});
