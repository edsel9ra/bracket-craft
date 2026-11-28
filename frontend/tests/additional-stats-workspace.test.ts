// Spec 052 T6 (RF-011, RF-012): posición de entrada y penal atajado en el Workspace.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { EVENT_TYPES, buildDraftEvent, eventFields, eventSummary } from '../app/utils/matchEvents.ts';
import { validateLiveEventForm } from '../app/utils/matchLiveCapture.ts';
import { positionsForGameFormat } from '../app/utils/positions.ts';
import { EVENT_LABEL_KEYS, reportProposal } from '../app/utils/rectifications.ts';

const SEGMENT = '11111111-1111-4111-8111-111111111111';
const TEAM = '22222222-2222-4222-8222-222222222222';
const OUT = '33333333-3333-4333-8333-333333333333';
const IN = '44444444-4444-4444-8444-444444444444';
const EVENT = '55555555-5555-4555-8555-555555555555';
const source = (path: string) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');

test('el catálogo ofrece el penal atajado con solo el portero que ataja', () => {
  assert.ok(EVENT_TYPES.includes('penalty_saved' as never));
  const fields = eventFields('penalty_saved');
  assert.deepEqual(fields?.required, ['player']);
  assert.deepEqual(fields?.optional, []);
  assert.ok(fields?.forbidden.includes('player_in_position'));
  assert.ok(eventFields('substitution')?.optional.includes('player_in_position'));
  assert.ok(eventFields('goal')?.forbidden.includes('player_in_position'));
});

test('la sustitución conserva la posición de entrada y los demás hechos no la llevan', () => {
  const base = { team_id: TEAM, minute: 60, added_minute: 0 };
  const sub = buildDraftEvent({ ...base, event_type: 'substitution', player_out_id: OUT, player_in_id: IN, player_in_position: 'LCB' }, SEGMENT, EVENT);
  assert.equal(sub?.player_in_position, 'LCB');
  const plain = buildDraftEvent({ ...base, event_type: 'substitution', player_out_id: OUT, player_in_id: IN, player_in_position: '' }, SEGMENT, EVENT);
  assert.equal(plain?.player_in_position, null);
  const saved = buildDraftEvent({ ...base, event_type: 'penalty_saved', player_id: OUT, player_in_position: 'GK' }, SEGMENT, EVENT);
  assert.equal(saved?.event_type, 'penalty_saved');
  assert.equal(saved?.player_id, OUT);
  assert.equal('player_in_position' in (saved ?? {}), false);
  assert.equal(eventSummary({ event_type: 'substitution', player_out_id: OUT, player_in_id: IN, player_in_position: 'LCB' }, (id) => (id === OUT ? 'A' : 'B'), { position: (code) => `pos ${code}` }), 'A → B (pos LCB)');
});

test('las posiciones de entrada son las de la modalidad', () => {
  assert.ok(positionsForGameFormat('11v11').includes('LWB'));
  assert.ok(!positionsForGameFormat('7v7').includes('LWB'));
  assert.ok(positionsForGameFormat('5v5').includes('GK'));
  assert.deepEqual(positionsForGameFormat(null), positionsForGameFormat('11v11'));
});

test('el partido en vivo acepta el penal atajado y la posición solo en la sustitución', () => {
  const base = { client_event_id: EVENT, team_id: TEAM, beneficiary_team_id: null, player_out_id: null, player_in_id: null, assist_player_id: null, minute: 30, added_minute: 0, segment_id: SEGMENT, metadata: null };
  assert.equal(validateLiveEventForm({ ...base, event_type: 'penalty_saved', player_id: OUT })?.event_type, 'penalty_saved');
  const sub = validateLiveEventForm({ ...base, event_type: 'substitution', player_id: OUT, player_out_id: OUT, player_in_id: IN, player_in_position: 'ST' });
  assert.equal(sub?.player_in_position, 'ST');
  assert.equal(validateLiveEventForm({ ...base, event_type: 'goal', player_id: OUT, player_in_position: 'ST' }), null);
  assert.equal(validateLiveEventForm({ ...base, event_type: 'substitution', player_id: OUT, player_out_id: OUT, player_in_id: IN, player_in_position: 'st' }), null);
});

test('la rectificación conserva la posición de entrada y nombra el penal atajado', () => {
  const proposal = reportProposal({ resolution_type: 'regular', events: [
    { client_event_id: EVENT, event_type: 'substitution', team_id: TEAM, player_id: OUT, player_out_id: OUT, player_in_id: IN, player_in_position: 'CB', minute: 60, added_minute: 0, segment_id: SEGMENT },
  ] });
  assert.equal((proposal.events[0] as { player_in_position?: string }).player_in_position, 'CB');
  assert.equal(EVENT_LABEL_KEYS.penalty_saved, 'event.penaltySaved');
});

test('los tres formularios ofrecen los dos campos, en ES y EN', () => {
  for (const path of ['components/match/MatchEventsSection.vue', 'components/match/MatchLiveSection.vue', 'components/match/RectificationEditor.vue']) {
    assert.match(source(path), /player_in_position/, path);
  }
  assert.match(source('components/match/MatchLiveSection.vue'), /'penalty_saved'/);
  assert.match(source('composables/useMatchOperationState.ts'), /'penalty_saved'/);
  const i18n = source('composables/useI18n.ts');
  for (const key of ['event.penaltySaved', 'live.eventType.penalty_saved', 'match.playerInPosition', 'match.positionNone', 'live.capture.playerInPosition', 'rectification.playerInPosition', 'match.positionShort']) {
    assert.equal(i18n.split(`'${key}':`).length - 1, 2, key);
  }
});

test('el borrador restaurado conserva la posición de entrada y descarta una inválida', async () => {
  const { readDraftEvent } = await import('../app/utils/substitutions.ts');
  const types = [...EVENT_TYPES];
  const sub = { client_event_id: EVENT, event_type: 'substitution', team_id: TEAM, beneficiary_team_id: null, player_id: OUT, player_out_id: OUT, player_in_id: IN, minute: 60, added_minute: 0, segment_id: SEGMENT };
  assert.equal(readDraftEvent({ ...sub, player_in_position: 'LCB' }, types)?.player_in_position, 'LCB');
  assert.equal(readDraftEvent({ ...sub, player_in_position: 'lcb' }, types), null);
  assert.equal(readDraftEvent({ ...sub, event_type: 'penalty_saved', player_out_id: null, player_in_id: null, player_in_position: 'GK' }, types), null);
  assert.equal(readDraftEvent({ ...sub, event_type: 'penalty_saved', player_out_id: null, player_in_id: null }, types)?.event_type, 'penalty_saved');
});
