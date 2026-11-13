import assert from 'node:assert/strict';
import test from 'node:test';
import * as vue from 'vue';
import { renderToString } from 'vue/server-renderer';
import { sanctionComponent } from './sanction-harness.ts';
import * as helpers from '../app/utils/sanctions.ts';

export const detail = {
  case: { id: 'c', status: 'pending', case_type: 'appeal', suspension_id: 's', submitted_by_user_id: 'author', submitted_at: 'now', reason: 'Case reason', evidence_text: 'Private case evidence', evidence_links: [], prior_case_id: null },
  source: { id: 's', player_id: 'p', source_type: 'competition_rule', scope_type: 'organization', source_tournament_id: 't', origin_match_id: null, reason: 'Original reason', created_at: 'before' },
  projection: { original_duration: 3, effective_duration: 3, remaining: 3, served_count: 0, status: 'active', pending_effect: true },
  resolutions: [{ id: 'r', case_id: 'c', action: 'annul', new_duration: null, is_declarative: false, excluded: false, created_at: 'now' }],
  applications: [], serves: [], events: [], decisions: [], prejudice: [],
};

test('authorized detail distinguishes original, effective, pending, declarative and rectified history', async () => {
  const Component = sanctionComponent('SanctionDetail');
  const render = (value: unknown) => renderToString(vue.createSSRApp(Component, { detail: value }));
  const pending = await render(detail);
  for (const key of ['sanction.original', 'sanction.effective', 'sanction.served', 'sanction.pendingEffect', 'Private case evidence', 'Original reason']) assert.ok(pending.includes(key), key);
  assert.equal(pending.includes('sanction.appliedAt'), false);
  const applied = await render({ ...detail, applications: [{ resolution_id: 'r', match_id: 'm', effective_at: 'later' }] });
  assert.match(applied, /sanction.appliedAt/);
  const declarative = await render({ ...detail, resolutions: [{ ...detail.resolutions[0], is_declarative: true }] });
  assert.match(declarative, /sanction.declarative/);
  const excluded = await render({ ...detail, resolutions: [{ ...detail.resolutions[0], excluded: true }], events: [{ id: 'e', event_type: 'affected_by_rectification', reason: 'Corrected', created_at: 'later', rectification_version_id: 'v' }] });
  assert.match(excluded, /sanction.excluded/);
  assert.match(excluded, /sanction.event.affected_by_rectification/);
  const empty = await render({ ...detail, resolutions: [] });
  assert.match(empty, /sanction.noResolutions/);
});

test('evidence links only permit safe web URLs', () => {
  assert.equal(helpers.safeEvidenceLink('https://example.test/evidence'), 'https://example.test/evidence');
  for (const value of ['javascript:alert(1)', 'data:text/html,unsafe', 'https://user:secret@example.test', '/private', 'invalid']) assert.equal(helpers.safeEvidenceLink(value), null);
});
