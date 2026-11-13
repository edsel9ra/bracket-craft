import assert from 'node:assert/strict';
import test from 'node:test';
import * as vue from 'vue';
import { renderToString } from 'vue/server-renderer';
import { sanctionComponent } from './sanction-harness.ts';
import { authorizationState } from '../app/utils/sanctions.ts';

test('authorization states distinguish revoked, consumed and live exact-case scopes', () => {
  assert.equal(authorizationState({ revoked_at: null, consumed_at: null }), 'sanction.authorization.active');
  assert.equal(authorizationState({ revoked_at: 'now', consumed_at: null }), 'sanction.authorization.revoked');
  assert.equal(authorizationState({ revoked_at: null, consumed_at: 'now' }), 'sanction.authorization.consumed');
});

test('owner management is separate from consultation and does not load for nonowners', async () => {
  let calls = 0;
  const component = sanctionComponent('SanctionAuthorizations', {
    useSanctionCases: () => ({ authorizations: async () => { calls++; return []; } }),
    useSanctionAction: () => ({ busy: vue.ref(false), error: vue.ref(''), run: async () => undefined }),
  });
  const owner = await renderToString(vue.createSSRApp(component, { owner: true, caseId: 'case', pending: true }));
  assert.match(owner, /sanction.grant/);
  const other = await renderToString(vue.createSSRApp(component, { owner: false, caseId: 'case', pending: true }));
  assert.equal(other.includes('sanction.grant'), false);
  assert.equal(calls, 0);
  const terminal = await renderToString(vue.createSSRApp(component, { owner: true, caseId: 'case', pending: false }));
  assert.equal(terminal.includes('<form'), false);
});
