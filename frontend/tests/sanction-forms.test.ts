import assert from 'node:assert/strict';
import test from 'node:test';
import * as vue from 'vue';
import { renderToString } from 'vue/server-renderer';
import { sanctionComponent } from './sanction-harness.ts';
import * as helpers from '../app/utils/sanctions.ts';

const sanction = 'aaaaaaaa-0000-4000-8000-000000000001';
const represented = 'bbbbbbbb-0000-4000-8000-000000000002';
test('appeal payload requires exactly one representation, reason, UUID and safe optional links', () => {
  const input = { sanctionId: sanction, representation: 'player' as const, representedId: represented, reason: ' Review ', evidence: '', links: '', priorCaseId: '' };
  assert.deepEqual(helpers.appealSubmission(input), { id: sanction, body: { represented_player_id: represented, reason: 'Review', evidence_text: null, evidence_links: [] } });
  const team = helpers.appealSubmission({ ...input, representation: 'team', evidence: 'Private', links: 'https://example.test/proof', priorCaseId: sanction });
  assert.equal(team?.body.represented_team_id, represented);
  assert.equal(team?.body.represented_player_id, undefined);
  assert.equal(team?.body.prior_case_id, sanction);
  for (const invalid of [{ reason: ' ' }, { representedId: '' }, { sanctionId: 'foreign' }, { priorCaseId: 'not-a-case' }, { links: 'javascript:unsafe' }]) assert.equal(helpers.appealSubmission({ ...input, ...invalid }), null);
});

test('appeal form is private, exposes no upload or expiry and renders only when permitted', async () => {
  const Component = sanctionComponent('SanctionAppealForm', { useSanctionAction: () => ({ busy: vue.ref(false), error: vue.ref(''), receipt: vue.ref(null), run: async () => null }) });
  const html = await renderToString(vue.createSSRApp(Component, { allowed: true }));
  assert.ok(html.includes('sanction.appeal'));
  assert.ok(html.includes('sanction.noExpiry'));
  assert.equal(html.includes('type="file"'), false);
  const forbidden = await renderToString(vue.createSSRApp(Component, { allowed: false }));
  assert.equal(forbidden.includes('<form'), false);
});
