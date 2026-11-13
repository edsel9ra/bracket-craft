import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import * as vue from 'vue';
import { renderToString } from 'vue/server-renderer';
import { sanctionComponent } from './sanction-harness.ts';

test('minimal private warning renders remaining matches but cannot disable save or publish', async () => {
  const component = sanctionComponent('SanctionLineupWarning', { useSuspensionWarnings: () => ({ rows: vue.ref([{ player_id: 'p', remaining: 2, reason: 'NEVER EXPOSE', evidence_text: 'PRIVATE' }]), error: vue.ref(''), loading: vue.ref(false), load() {} }) });
  const html = await renderToString(vue.createSSRApp(component, { enabled: true, matchId: 'm', refreshKey: '', players: [{ id: 'p', label: 'Player' }] }));
  assert.match(html, /sanction.warningHint/); assert.match(html, /Player/); assert.match(html, /2/);
  assert.equal(/NEVER EXPOSE|PRIVATE|disabled=|<form/.test(html), false);
  const hidden = await renderToString(vue.createSSRApp(component, { enabled: false, matchId: 'm', refreshKey: '' }));
  assert.equal(hidden.includes('Player'), false);
  const section = readFileSync(new URL('../app/components/match/MatchLineupSection.vue', import.meta.url), 'utf8');
  assert.match(section, /SanctionLineupWarning/);
  assert.match(section, /@click="saveLineup"/); assert.match(section, /@click="toggleLineupPublication\(team.team_id\)"/);
  const publicModal = readFileSync(new URL('../app/components/public/PublicLineupModal.vue', import.meta.url), 'utf8');
  assert.equal(/suspension|sanction/i.test(publicModal), false);
});

test('warning is GET-only through the central adapter and keeps errors local', () => {
  const adapter = readFileSync(new URL('../app/composables/useSanctionCases.ts', import.meta.url), 'utf8');
  assert.match(adapter, /request<SuspensionWarning\[\]>\(`\/matches\/\$\{id\}\/suspension-warnings`\)/);
  const source = readFileSync(new URL('../app/composables/useSuspensionWarnings.ts', import.meta.url), 'utf8');
  assert.match(source, /token === generation/);
  assert.equal(/saveLineup|toggleLineupPublication|Socket|\$fetch|localStorage/.test(source), false);
});
