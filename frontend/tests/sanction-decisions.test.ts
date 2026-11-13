import assert from 'node:assert/strict';
import test from 'node:test';
import * as vue from 'vue';
import { renderToString } from 'vue/server-renderer';
import { sanctionComponent } from './sanction-harness.ts';
import * as helpers from '../app/utils/sanctions.ts';

const source = 'aaaaaaaa-0000-4000-8000-000000000001';
const preview = { id: 'c', status: 'pending' as const, expected_base_duration: 3, allowed_decisions: ['maintain', 'annul', 'reduce'] as helpers.SanctionDecision[], can_decide: true, projection: {} as helpers.SanctionProjection };
test('proposal and decision catalogs reject invalid durations and self/stale previews', () => {
  const input = { sanctionId: source, action: 'annul' as const, duration: '', reason: 'Review', evidence: '', links: '', priorCaseId: '' };
  assert.equal(helpers.proposalSubmission(input)?.body.proposed_duration, undefined);
  assert.equal(helpers.proposalSubmission({ ...input, action: 'reduce', duration: '0' })?.body.proposed_duration, 0);
  assert.equal(helpers.proposalSubmission({ ...input, action: 'reduce', duration: '' }), null);
  const decision = { decision: 'reduce' as const, duration: '1', reason: 'Reviewed', evidence: '', links: '', prejudice: [] };
  assert.equal(helpers.decisionSubmission(preview, decision)?.expected_base_duration, 3);
  for (const duration of ['', '-1', '3', '1.5']) assert.equal(helpers.decisionSubmission(preview, { ...decision, duration }), null);
  assert.equal(helpers.decisionSubmission({ ...preview, can_decide: false }, decision), null);
  assert.equal(helpers.decisionSubmission({ ...preview, status: 'resolved' }, decision), null);
  assert.equal(helpers.decisionSubmission(preview, { ...decision, decision: 'approve' }), null);
  assert.equal(helpers.decisionSubmission(preview, { ...decision, prejudice: [{ match_id: source, reason: ' ' }] }), null);
});

test('withdrawal and decision controls require the appropriate current permission and distinct actors', async () => {
  const request = { id: 'c', status: 'pending' as const, case_type: 'appeal' as const, submitted_by_user_id: 'author' };
  assert.equal(helpers.canWithdrawSanction(request, 'author', true, false), true);
  assert.equal(helpers.canWithdrawSanction(request, 'author', false, true), false);
  assert.equal(helpers.canWithdrawSanction(request, 'other', true, true), false);
  const globals = { useSanctionAction: () => ({ busy: vue.ref(false), error: vue.ref(''), run: async () => undefined }) };
  const component = sanctionComponent('SanctionDecisionForm', globals);
  for (const [userId, canResolve, status, visible] of [['author', true, 'pending', false], ['reviewer', false, 'pending', false], ['reviewer', true, 'resolved', false], ['reviewer', true, 'pending', true]] as const) {
    const html = await renderToString(vue.createSSRApp(component, { case: { ...request, status }, userId, canResolve }));
    assert.equal(html.includes('sanction.preview'), visible);
  }
  const withdrawal = sanctionComponent('SanctionWithdrawalForm', globals);
  for (const [userId, submitPermission, visible] of [['author', true, true], ['author', false, false], ['other', true, false]] as const) {
    const html = await renderToString(vue.createSSRApp(withdrawal, { case: request, userId, submitPermission, resolvePermission: true }));
    assert.equal(html.includes('sanction.withdraw'), visible);
  }
});
