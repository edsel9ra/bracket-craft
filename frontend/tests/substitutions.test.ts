import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  DEFAULT_MATCH_LIMITS,
  normalizeMatchLimits,
  normalizeSubstitutionsState,
  previewCounters,
  previewTeamState,
  readDraftEvent,
  substitutionAvailability,
  substitutionFieldsFor,
  substitutionOptions,
  teamSubstitutionState,
  validateSubstitutionPair,
  type DraftEventLike,
  type TeamSubstitutionState,
} from '../app/utils/substitutions.ts';

const matchPageSource = readFileSync(
  new URL('../app/pages/workspace/matches/[id].vue', import.meta.url),
  'utf8',
);
const translationsSource = readFileSync(
  new URL('../app/composables/useI18n.ts', import.meta.url),
  'utf8',
);
const eventTypes = ['goal', 'own_goal', 'penalty_goal', 'yellow_card', 'red_card', 'substitution', 'foul'] as const;

function team(overrides: Partial<TeamSubstitutionState> = {}): TeamSubstitutionState {
  return {
    team_id: 'home',
    on_field: ['p1', 'p2', 'p3'],
    bench: ['p4', 'p5', 'p6'],
    substitutions_used: 0,
    substitutions_remaining: 5,
    windows_used: 0,
    windows_remaining: 3,
    max_per_team: 5,
    max_windows: 3,
    allow_reentry: false,
    can_register: true,
    reason: null,
    ...overrides,
  };
}

function substitution(playerOut: string, playerIn: string, extra: Partial<DraftEventLike> = {}): DraftEventLike {
  return {
    event_type: 'substitution',
    team_id: 'home',
    segment_id: 's1',
    minute: 60,
    added_minute: 0,
    player_out_id: playerOut,
    player_in_id: playerIn,
    ...extra,
  };
}

function catalogSlices(): { spanish: string; english: string } {
  const englishStart = translationsSource.indexOf('\n  en: {');
  assert.ok(englishStart > 0, 'the English catalog is missing');
  return {
    spanish: translationsSource.slice(0, englishStart),
    english: translationsSource.slice(englishStart),
  };
}

test('normalizes the operation substitutions block and tolerates legacy responses', () => {
  const normalized = normalizeSubstitutionsState({
    max_per_team: 3,
    max_windows: 2,
    allow_reentry: true,
    teams: [{
      team_id: 'home',
      on_field: ['p1', 'p1', 'p2', ''],
      bench: ['p3'],
      substitutions_used: 1,
      substitutions_remaining: 2,
      windows_used: 1,
      windows_remaining: 1,
      max_per_team: 3,
      max_windows: 2,
      allow_reentry: true,
      can_register: true,
      reason: null,
    }],
  });

  assert.ok(normalized);
  assert.equal(normalized.max_per_team, 3);
  assert.equal(normalized.allow_reentry, true);
  assert.deepEqual(normalized.teams[0]?.on_field, ['p1', 'p2']);
  assert.deepEqual(normalized.teams[0]?.bench, ['p3']);

  assert.equal(normalizeSubstitutionsState(null), null);
  assert.equal(normalizeSubstitutionsState({}), null);
  assert.equal(normalizeSubstitutionsState({ teams: 'nope' }), null);
});

test('keeps a team without lineup but marks it unavailable', () => {
  const normalized = normalizeSubstitutionsState({
    max_per_team: 5,
    max_windows: 3,
    allow_reentry: false,
    teams: [{
      team_id: 'away',
      on_field: [],
      bench: [],
      substitutions_used: 0,
      substitutions_remaining: 5,
      windows_used: 0,
      windows_remaining: 3,
      max_per_team: 5,
      max_windows: 3,
      allow_reentry: false,
      can_register: false,
      reason: 'No hay planilla para determinar el estado en campo',
    }],
  });

  assert.ok(normalized);
  const away = teamSubstitutionState(normalized, 'away');
  assert.ok(away);
  assert.deepEqual(substitutionAvailability(away), { disabled: true, reason: 'no_lineup' });
});

test('filters outgoing players from the field and incoming players from the bench', () => {
  const options = substitutionOptions(team(), []);

  assert.deepEqual(options.outgoing.map((option) => option.player_id), ['p1', 'p2', 'p3']);
  assert.deepEqual(options.incoming.map((option) => option.player_id), ['p4', 'p5', 'p6']);
  assert.ok(options.outgoing.every((option) => !option.disabled));
  assert.ok(options.incoming.every((option) => !option.disabled));
});

test('previews the draft state so a substituted player leaves the field', () => {
  const draft = [substitution('p1', 'p4')];

  const preview = previewTeamState(team(), draft);
  const options = substitutionOptions(team(), draft);

  assert.deepEqual(preview.on_field, ['p2', 'p3', 'p4']);
  assert.deepEqual(preview.bench, ['p1', 'p5', 'p6']);
  assert.deepEqual(options.outgoing.map((option) => option.player_id), ['p2', 'p3', 'p4']);
  assert.deepEqual(options.incoming.map((option) => option.player_id), ['p1', 'p5', 'p6']);
});

test('blocks substitutions with max_per_team = 0', () => {
  const disabled = team({ max_per_team: 0, substitutions_remaining: 0, can_register: false });

  assert.deepEqual(substitutionAvailability(disabled), { disabled: true, reason: 'disabled' });

  const options = substitutionOptions(disabled, []);
  assert.ok(options.outgoing.length > 0);
  assert.ok(options.outgoing.every((option) => option.disabled && option.reason === 'disabled'));
  assert.ok(options.incoming.every((option) => option.disabled && option.reason === 'disabled'));
  assert.equal(previewCounters(disabled, []).can_register, false);
});

test('blocks substitutions without a lineup or without server state', () => {
  assert.deepEqual(substitutionAvailability(null), { disabled: true, reason: 'no_state' });
  assert.deepEqual(
    substitutionAvailability(team({ on_field: [], bench: [] })),
    { disabled: true, reason: 'no_lineup' },
  );

  const counters = previewCounters(null, [substitution('p1', 'p4')]);
  assert.deepEqual(counters, {
    substitutions_used: 0,
    substitutions_remaining: 0,
    windows_used: 0,
    windows_remaining: 0,
    can_register: false,
  });
});

test('counts substitutions and distinct windows over the draft', () => {
  const base = team({ substitutions_used: 1, substitutions_remaining: 4, windows_used: 1, windows_remaining: 2 });

  const one = previewCounters(base, [substitution('p1', 'p4')]);
  assert.deepEqual(one, {
    substitutions_used: 2,
    substitutions_remaining: 3,
    windows_used: 2,
    windows_remaining: 1,
    can_register: true,
  });

  const sameWindow = previewCounters(base, [
    substitution('p1', 'p4', { minute: 60 }),
    substitution('p2', 'p5', { minute: 60 }),
  ]);
  assert.equal(sameWindow.substitutions_used, 3);
  assert.equal(sameWindow.windows_used, 2);

  const otherMinutes = previewCounters(base, [
    substitution('p1', 'p4', { minute: 60 }),
    substitution('p2', 'p5', { minute: 61 }),
  ]);
  assert.equal(otherMinutes.windows_used, 3);
  assert.equal(otherMinutes.windows_remaining, 0);
  assert.equal(otherMinutes.can_register, false);
});

test('never returns negative counters and disables registration when exhausted', () => {
  const exhausted = team({
    substitutions_used: 5,
    substitutions_remaining: 0,
    windows_used: 3,
    windows_remaining: 0,
    can_register: false,
  });

  const counters = previewCounters(exhausted, [substitution('p1', 'p4')]);
  assert.equal(counters.substitutions_remaining, 0);
  assert.equal(counters.windows_remaining, 0);
  assert.equal(counters.can_register, false);

  const options = substitutionOptions(exhausted, []);
  assert.ok(options.outgoing.every((option) => option.disabled && option.reason === 'exhausted'));
});

test('honours allow_reentry when a substituted player returns to the bench', () => {
  const draft = [substitution('p1', 'p4')];

  const blocked = substitutionOptions(team({ allow_reentry: false }), draft);
  const returning = blocked.incoming.find((option) => option.player_id === 'p1');
  assert.deepEqual(returning, { player_id: 'p1', disabled: true, reason: 'reentry_blocked' });

  const allowed = substitutionOptions(team({ allow_reentry: true }), draft);
  assert.equal(allowed.incoming.find((option) => option.player_id === 'p1')?.disabled, false);
});

test('validates the outgoing/incoming pair with stable reasons', () => {
  const current = team();

  assert.deepEqual(validateSubstitutionPair(current, [], '', 'p4'), { ok: false, reason: 'pair_required' });
  assert.deepEqual(validateSubstitutionPair(current, [], 'p1', 'p1'), { ok: false, reason: 'same_player' });
  assert.deepEqual(validateSubstitutionPair(current, [], 'p4', 'p5'), { ok: false, reason: 'not_on_field' });
  assert.deepEqual(validateSubstitutionPair(current, [], 'p1', 'p1x'), { ok: false, reason: 'not_on_bench' });
  assert.deepEqual(validateSubstitutionPair(current, [], 'p1', 'p4'), {
    ok: true,
    player_out_id: 'p1',
    player_in_id: 'p4',
  });
  assert.deepEqual(
    validateSubstitutionPair(current, [substitution('p1', 'p4')], 'p4', 'p1'),
    { ok: false, reason: 'reentry_blocked' },
  );
  assert.deepEqual(
    validateSubstitutionPair(team({ allow_reentry: true }), [substitution('p1', 'p4')], 'p4', 'p1'),
    { ok: true, player_out_id: 'p4', player_in_id: 'p1' },
  );
});

test('only substitutions carry the pair when the draft is serialized', () => {
  assert.deepEqual(substitutionFieldsFor('substitution', 'p1', 'p4'), {
    player_out_id: 'p1',
    player_in_id: 'p4',
  });
  assert.deepEqual(substitutionFieldsFor('goal', 'p1', 'p4'), {
    player_out_id: null,
    player_in_id: null,
  });
});

test('saves and restores the substitution pair of a draft event', () => {
  const draft = {
    client_event_id: 'event-1',
    event_type: 'substitution',
    team_id: 'home',
    beneficiary_team_id: null,
    player_id: 'p1',
    minute: 60,
    added_minute: 0,
    segment_id: 's1',
    player_out_id: 'p1',
    player_in_id: 'p4',
  };

  const restored = readDraftEvent(JSON.parse(JSON.stringify(draft)), eventTypes);
  assert.deepEqual(restored, draft);

  assert.equal(readDraftEvent({ ...draft, player_in_id: null }, eventTypes), null);
  assert.equal(readDraftEvent({ ...draft, player_id: 'p4' }, eventTypes), null);
  assert.equal(readDraftEvent({ ...draft, player_in_id: 'p1' }, eventTypes), null);

  const goal = {
    client_event_id: 'event-2',
    event_type: 'goal',
    team_id: 'home',
    beneficiary_team_id: null,
    player_id: 'p2',
    minute: 10,
    added_minute: 0,
    segment_id: 's1',
  };
  assert.deepEqual(readDraftEvent(goal, eventTypes), {
    ...goal,
    player_out_id: null,
    player_in_id: null,
  });
  assert.equal(readDraftEvent({ ...goal, player_out_id: 'p2' }, eventTypes), null);
  assert.equal(readDraftEvent({ ...goal, event_type: 'unknown' }, eventTypes), null);
});

test('validates draft minutes against the effective match limits', () => {
  const goal = {
    client_event_id: 'event-3',
    event_type: 'goal',
    team_id: 'home',
    beneficiary_team_id: null,
    player_id: 'p2',
    minute: 100,
    added_minute: 0,
    segment_id: 's1',
  };

  // 90/120 without extra time enabled: the cap is the regular time.
  const regular = normalizeMatchLimits({
    regular_time_minutes: 90,
    extra_time_minutes: 120,
    max_minute: 90,
    added_minute_max: 30,
  });
  assert.deepEqual(regular, {
    regular_time_minutes: 90,
    extra_time_minutes: 120,
    max_minute: 90,
    added_minute_max: 30,
  });
  assert.equal(readDraftEvent(goal, eventTypes, regular!), null);

  // 40/100 with extra time enabled accepts minute 100.
  const extended = normalizeMatchLimits({
    regular_time_minutes: 40,
    extra_time_minutes: 100,
    max_minute: 100,
    added_minute_max: 30,
  });
  assert.equal(readDraftEvent(goal, eventTypes, extended!)?.minute, 100);
  assert.equal(readDraftEvent({ ...goal, minute: 101 }, eventTypes, extended!), null);

  // The added minute uses its own limit from the same block.
  assert.equal(readDraftEvent({ ...goal, minute: 100, added_minute: 31 }, eventTypes, extended!), null);
  assert.equal(readDraftEvent({ ...goal, minute: 100, added_minute: 30 }, eventTypes, extended!)?.added_minute, 30);

  // Missing/malformed limits fall back to the structural form caps.
  assert.deepEqual(normalizeMatchLimits(undefined), null);
  assert.deepEqual(normalizeMatchLimits({ max_minute: 90 }), null);
  assert.equal(DEFAULT_MATCH_LIMITS.max_minute, 180);
  assert.equal(readDraftEvent({ ...goal, minute: 180 }, eventTypes)?.minute, 180);
  assert.equal(readDraftEvent({ ...goal, minute: 181 }, eventTypes), null);
});

test('the match report renders two substitution selectors and preview counters', () => {
  assert.match(matchPageSource, /eventForm\.player_out_id/);
  assert.match(matchPageSource, /eventForm\.player_in_id/);
  assert.match(matchPageSource, /normalizeSubstitutionsState/);
  assert.match(matchPageSource, /substitutionOptions\(/);
  assert.match(matchPageSource, /previewCounters\(/);
  assert.match(matchPageSource, /role="alert"/);
  assert.match(matchPageSource, /match\.playerOut/);
  assert.match(matchPageSource, /match\.playerIn/);
  assert.match(matchPageSource, /match\.substitutionPreview/);
  assert.match(matchPageSource, /limits\?: MatchLimits/);
  assert.match(matchPageSource, /normalizeMatchLimits\(operation\.value\?\.limits\)/);
  assert.match(matchPageSource, /:max="matchLimits\.max_minute"/);
  assert.match(matchPageSource, /:max="matchLimits\.added_minute_max"/);
});

test('keeps the substitution texts in Spanish and English parity', () => {
  const { spanish, english } = catalogSlices();
  const keys = [
    'match.playerOut',
    'match.playerIn',
    'match.substitutionPreview',
    'match.substitutionsRemaining',
    'match.windowsRemaining',
    'match.substitutionDisabled',
    'match.substitutionNoLineup',
    'match.substitutionExhausted',
    'match.substitutionPairRequired',
    'match.substitutionSamePlayer',
    'match.substitutionOutUnavailable',
    'match.substitutionInUnavailable',
    'match.substitutionReentryBlocked',
    'match.substitutionUnavailable',
    'match.minuteOutOfRange',
    'match.addedMinuteOutOfRange',
  ];

  for (const key of keys) {
    const pattern = new RegExp(`'${key.replace(/\./g, '\\.')}':`);
    assert.match(spanish, pattern, `${key} is missing in Spanish`);
    assert.match(english, pattern, `${key} is missing in English`);
  }
});
