/**
 * Pure substitution helpers for the match report screen (RF-019).
 *
 * The server owns the on-field truth (`GET /matches/{id}/operation` exposes
 * `on_field`, `bench` and the substitution counters). This module only:
 *
 * * normalizes that response defensively,
 * * applies the *local draft* on top of it to preview the next state,
 * * filters the outgoing (on field) and incoming (bench) options,
 * * recomputes the counters over the draft, and
 * * validates/persists the `player_out_id`/`player_in_id` pair.
 *
 * It is framework-free: no Nuxt, no DOM, no clock and no I/O.
 */

export const SUBSTITUTION_EVENT_TYPE = 'substitution';

export type SubstitutionUnavailableReason =
  | 'no_state'
  | 'no_lineup'
  | 'disabled'
  | 'exhausted'
  | 'not_on_field'
  | 'not_on_bench'
  | 'reentry_blocked'
  | 'same_player'
  | 'pair_required';

export interface MatchLimits {
  regular_time_minutes: number;
  extra_time_minutes: number | null;
  max_minute: number;
  added_minute_max: number;
}

export interface TeamSubstitutionState {
  team_id: string;
  on_field: string[];
  bench: string[];
  substitutions_used: number;
  substitutions_remaining: number;
  windows_used: number;
  windows_remaining: number;
  max_per_team: number;
  max_windows: number;
  allow_reentry: boolean;
  can_register: boolean;
  reason: string | null;
}

export interface SubstitutionsState {
  max_per_team: number;
  max_windows: number;
  allow_reentry: boolean;
  teams: TeamSubstitutionState[];
}

/** The subset of a draft event needed to preview substitutions. */
export interface DraftEventLike {
  event_type: string;
  team_id: string;
  segment_id: string;
  minute: number;
  added_minute?: number;
  player_out_id?: string | null;
  player_in_id?: string | null;
}

export interface SubstitutionOption {
  player_id: string;
  disabled: boolean;
  reason: SubstitutionUnavailableReason | null;
}

export interface SubstitutionOptions {
  outgoing: SubstitutionOption[];
  incoming: SubstitutionOption[];
}

export interface SubstitutionAvailability {
  disabled: boolean;
  reason: SubstitutionUnavailableReason | null;
}

export interface PreviewCounters {
  substitutions_used: number;
  substitutions_remaining: number;
  windows_used: number;
  windows_remaining: number;
  can_register: boolean;
}

export interface PreviewTeamState {
  on_field: string[];
  bench: string[];
  substitutions_added: number;
  windows_added: number;
}

export interface DraftEvent<T extends string = string> {
  client_event_id: string;
  event_type: T;
  team_id: string;
  beneficiary_team_id: string | null;
  player_id: string;
  minute: number;
  added_minute: number;
  segment_id: string;
  player_out_id: string | null;
  player_in_id: string | null;
  metadata?: Record<string, unknown>;
}

export type SubstitutionPairResult =
  | { ok: true; player_out_id: string; player_in_id: string }
  | { ok: false; reason: SubstitutionUnavailableReason };

const MAX_TEXT_LENGTH = 100;
const STRUCTURAL_MAX_MINUTE = 180;
const STRUCTURAL_MAX_ADDED_MINUTE = 30;

/** Form limits used only when the operation response has no `limits` block. */
export const DEFAULT_MATCH_LIMITS: MatchLimits = {
  regular_time_minutes: 90,
  extra_time_minutes: 120,
  max_minute: STRUCTURAL_MAX_MINUTE,
  added_minute_max: STRUCTURAL_MAX_ADDED_MINUTE,
};

/**
 * Reads the `limits` block of `GET /operation` (RF-043).
 *
 * The server already resolves the stage override and whether extra time is
 * enabled, so `max_minute` is the single cap the client must honour. Returns
 * `null` when the block is absent or malformed; callers fall back to
 * `DEFAULT_MATCH_LIMITS`.
 */
export function normalizeMatchLimits(raw: unknown): MatchLimits | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const regular = integerBetween(value.regular_time_minutes, 1, STRUCTURAL_MAX_MINUTE);
  const maxMinute = integerBetween(value.max_minute, 1, STRUCTURAL_MAX_MINUTE);
  const addedMinuteMax = integerBetween(value.added_minute_max, 0, STRUCTURAL_MAX_ADDED_MINUTE);
  if (regular === null || maxMinute === null || addedMinuteMax === null) return null;
  const extra = value.extra_time_minutes === null || value.extra_time_minutes === undefined
    ? null
    : integerBetween(value.extra_time_minutes, 1, STRUCTURAL_MAX_MINUTE);
  return {
    regular_time_minutes: regular,
    extra_time_minutes: extra,
    max_minute: maxMinute,
    added_minute_max: addedMinuteMax,
  };
}

function text(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const candidate = value.trim();
  if (candidate.length === 0 || candidate.length > MAX_TEXT_LENGTH) return null;
  return candidate;
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : 0;
}

function idList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const ids: string[] = [];
  for (const entry of value) {
    const id = text(entry);
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

function normalizeTeamState(raw: unknown): TeamSubstitutionState | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const teamId = text(value.team_id);
  if (!teamId) return null;
  const onField = idList(value.on_field);
  const maxPerTeam = count(value.max_per_team);
  const canRegister = typeof value.can_register === 'boolean'
    ? value.can_register
    : maxPerTeam > 0 && onField.length > 0;
  return {
    team_id: teamId,
    on_field: onField,
    bench: idList(value.bench),
    substitutions_used: count(value.substitutions_used),
    substitutions_remaining: count(value.substitutions_remaining),
    windows_used: count(value.windows_used),
    windows_remaining: count(value.windows_remaining),
    max_per_team: maxPerTeam,
    max_windows: count(value.max_windows),
    allow_reentry: value.allow_reentry === true,
    can_register: canRegister,
    reason: typeof value.reason === 'string' ? value.reason : null,
  };
}

/** Reads the `substitutions` block of `GET /operation`; `null` when absent. */
export function normalizeSubstitutionsState(raw: unknown): SubstitutionsState | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  if (!Array.isArray(value.teams)) return null;
  const teams = value.teams
    .map((entry) => normalizeTeamState(entry))
    .filter((entry): entry is TeamSubstitutionState => entry !== null);
  return {
    max_per_team: count(value.max_per_team),
    max_windows: count(value.max_windows),
    allow_reentry: value.allow_reentry === true,
    teams,
  };
}

export function teamSubstitutionState(
  state: SubstitutionsState | null,
  teamId: string | null | undefined,
): TeamSubstitutionState | null {
  if (!state || !teamId) return null;
  return state.teams.find((team) => team.team_id === teamId) ?? null;
}

/** Why the substitution form is disabled, if it is. */
export function substitutionAvailability(team: TeamSubstitutionState | null): SubstitutionAvailability {
  if (!team) return { disabled: true, reason: 'no_state' };
  if (team.on_field.length === 0) return { disabled: true, reason: 'no_lineup' };
  if (team.max_per_team <= 0) return { disabled: true, reason: 'disabled' };
  if (!team.can_register) return { disabled: true, reason: 'exhausted' };
  return { disabled: false, reason: null };
}

function draftSubstitutions(draft: readonly DraftEventLike[], teamId: string): DraftEventLike[] {
  return draft
    .map((event, index) => ({ event, index }))
    .filter(({ event }) => (
      event.event_type === SUBSTITUTION_EVENT_TYPE
      && event.team_id === teamId
      && text(event.player_out_id) !== null
      && text(event.player_in_id) !== null
      && event.player_out_id !== event.player_in_id
    ))
    .sort((left, right) => (
      left.event.minute - right.event.minute
      || (left.event.added_minute ?? 0) - (right.event.added_minute ?? 0)
      || left.index - right.index
    ))
    .map(({ event }) => event);
}

function windowKey(event: DraftEventLike): string {
  return `${event.segment_id}|${event.minute}|${event.added_minute ?? 0}`;
}

/** Applies the draft substitutions on top of the server state (preview only). */
export function previewTeamState(
  team: TeamSubstitutionState | null,
  draft: readonly DraftEventLike[],
): PreviewTeamState {
  if (!team) {
    return { on_field: [], bench: [], substitutions_added: 0, windows_added: 0 };
  }
  const onField = new Set(team.on_field);
  const bench = new Set(team.bench);
  const windows = new Set<string>();
  const substitutions = draftSubstitutions(draft, team.team_id);
  for (const event of substitutions) {
    const playerOut = event.player_out_id as string;
    const playerIn = event.player_in_id as string;
    onField.delete(playerOut);
    bench.add(playerOut);
    bench.delete(playerIn);
    onField.add(playerIn);
    windows.add(windowKey(event));
  }
  return {
    on_field: [...onField].sort(),
    bench: [...bench].sort(),
    substitutions_added: substitutions.length,
    windows_added: windows.size,
  };
}

/** Preview counters: server values as the base plus the draft. */
export function previewCounters(
  team: TeamSubstitutionState | null,
  draft: readonly DraftEventLike[],
): PreviewCounters {
  if (!team) {
    return {
      substitutions_used: 0,
      substitutions_remaining: 0,
      windows_used: 0,
      windows_remaining: 0,
      can_register: false,
    };
  }
  const preview = previewTeamState(team, draft);
  const substitutionsUsed = team.substitutions_used + preview.substitutions_added;
  const windowsUsed = team.windows_used + preview.windows_added;
  const substitutionsRemaining = Math.max(0, team.max_per_team - substitutionsUsed);
  const windowsRemaining = Math.max(0, team.max_windows - windowsUsed);
  const canRegister = team.can_register
    && team.max_per_team > 0
    && team.on_field.length > 0
    && substitutionsRemaining > 0
    && windowsRemaining > 0;
  return {
    substitutions_used: substitutionsUsed,
    substitutions_remaining: substitutionsRemaining,
    windows_used: windowsUsed,
    windows_remaining: windowsRemaining,
    can_register: canRegister,
  };
}

/**
 * Outgoing options are the players on the field; incoming options are the
 * players on the bench. Invalid options stay in the list but disabled, so the
 * operator understands why the server would reject them.
 */
export function substitutionOptions(
  team: TeamSubstitutionState | null,
  draft: readonly DraftEventLike[],
): SubstitutionOptions {
  if (!team) return { outgoing: [], incoming: [] };
  const availability = substitutionAvailability(team);
  const counters = previewCounters(team, draft);
  const blockedReason: SubstitutionUnavailableReason | null = availability.disabled
    ? availability.reason
    : counters.can_register
      ? null
      : 'exhausted';
  const preview = previewTeamState(team, draft);
  const played = new Set(draftSubstitutions(draft, team.team_id).map((event) => event.player_out_id as string));

  const outgoing = preview.on_field.map((playerId): SubstitutionOption => ({
    player_id: playerId,
    disabled: blockedReason !== null,
    reason: blockedReason,
  }));
  const incoming = preview.bench.map((playerId): SubstitutionOption => {
    let reason = blockedReason;
    if (reason === null && !team.allow_reentry && played.has(playerId)) {
      reason = 'reentry_blocked';
    }
    return { player_id: playerId, disabled: reason !== null, reason };
  });

  return { outgoing, incoming };
}

/** Validates the outgoing/incoming pair exactly as the UI will submit it. */
export function validateSubstitutionPair(
  team: TeamSubstitutionState | null,
  draft: readonly DraftEventLike[],
  playerOutId: string | null | undefined,
  playerInId: string | null | undefined,
): SubstitutionPairResult {
  if (!team) return { ok: false, reason: 'no_state' };
  const playerOut = text(playerOutId);
  const playerIn = text(playerInId);
  if (!playerOut || !playerIn) return { ok: false, reason: 'pair_required' };
  if (playerOut === playerIn) return { ok: false, reason: 'same_player' };

  const options = substitutionOptions(team, draft);
  const outgoing = options.outgoing.find((option) => option.player_id === playerOut);
  if (!outgoing) return { ok: false, reason: 'not_on_field' };
  if (outgoing.disabled) return { ok: false, reason: outgoing.reason ?? 'exhausted' };

  const incoming = options.incoming.find((option) => option.player_id === playerIn);
  if (!incoming) return { ok: false, reason: 'not_on_bench' };
  if (incoming.disabled) return { ok: false, reason: incoming.reason ?? 'exhausted' };

  return { ok: true, player_out_id: playerOut, player_in_id: playerIn };
}

/** `player_out_id`/`player_in_id` to persist; non-substitutions never carry them. */
export function substitutionFieldsFor(
  eventType: string,
  playerOutId: unknown,
  playerInId: unknown,
): { player_out_id: string | null; player_in_id: string | null } {
  if (eventType !== SUBSTITUTION_EVENT_TYPE) {
    return { player_out_id: null, player_in_id: null };
  }
  return {
    player_out_id: text(playerOutId),
    player_in_id: text(playerInId),
  };
}

function integerBetween(value: unknown, min: number, max: number): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value)) return null;
  return value >= min && value <= max ? value : null;
}

/**
 * Validates a persisted draft event, including the new substitution pair.
 *
 * A `substitution` needs both ids, different from each other and with
 * `player_id === player_out_id` (the payload contract of the closing API).
 * Any other type must not carry the pair. Returns a normalized copy so a
 * restored draft always has both keys.
 */
export function readDraftEvent<T extends string>(
  value: unknown,
  eventTypes: readonly T[],
  limits: MatchLimits = DEFAULT_MATCH_LIMITS,
): DraftEvent<T> | null {
  if (!value || typeof value !== 'object') return null;
  const event = value as Record<string, unknown>;
  const clientEventId = text(event.client_event_id);
  const eventType = typeof event.event_type === 'string' && (eventTypes as readonly string[]).includes(event.event_type)
    ? event.event_type as T
    : null;
  const teamId = text(event.team_id);
  const playerId = text(event.player_id);
  const segmentId = text(event.segment_id);
  const minute = integerBetween(event.minute, 0, limits.max_minute);
  const addedMinute = integerBetween(event.added_minute ?? 0, 0, limits.added_minute_max);
  if (!clientEventId || !eventType || !teamId || !playerId || !segmentId || minute === null || addedMinute === null) {
    return null;
  }

  const beneficiary = event.beneficiary_team_id === null || event.beneficiary_team_id === undefined
    ? null
    : text(event.beneficiary_team_id);
  const playerOut = event.player_out_id === null || event.player_out_id === undefined
    ? null
    : text(event.player_out_id);
  const playerIn = event.player_in_id === null || event.player_in_id === undefined
    ? null
    : text(event.player_in_id);

  if (eventType === SUBSTITUTION_EVENT_TYPE) {
    if (!playerOut || !playerIn || playerOut === playerIn || playerId !== playerOut) return null;
  } else if (playerOut !== null || playerIn !== null) {
    return null;
  }

  const result: DraftEvent<T> = {
    client_event_id: clientEventId,
    event_type: eventType,
    team_id: teamId,
    beneficiary_team_id: beneficiary,
    player_id: playerId,
    minute,
    added_minute: addedMinute,
    segment_id: segmentId,
    player_out_id: playerOut,
    player_in_id: playerIn,
  };
  if (event.metadata && typeof event.metadata === 'object' && !Array.isArray(event.metadata)) {
    result.metadata = event.metadata as Record<string, unknown>;
  }
  return result;
}
