<script setup lang="ts">
import { FORMATION_OPTIONS, formationSlots, type FormationCode } from '~/constants/formations';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';

definePageMeta({ middleware: 'auth' });

type EventType = 'goal' | 'own_goal' | 'penalty_goal' | 'yellow_card' | 'red_card' | 'substitution' | 'foul';
type RedCardType = 'direct_red' | 'double_yellow_red';
type OfficialRole = 'main_referee' | 'assistant_referee_1' | 'assistant_referee_2' | 'fourth_official' | 'match_commissioner';
type LineupRole = 'starter' | 'substitute';
type ResolutionType = 'regular' | 'extra_time' | 'penalties' | 'walkover' | 'administrative';
type SegmentStatus = 'active' | 'completed' | 'interrupted';
type InterruptionReason = 'lighting_failure' | 'weather' | 'pitch_invasion' | 'other';

interface MatchRecord {
  id: string;
  tournament_id: string;
  tournament_name: string;
  tournament_version_id: string;
  stage_id: string;
  stage_name: string;
  group_id: string | null;
  group_name: string | null;
  matchday: number | null;
  match_date: string | null;
  status: string;
  result_confirmed: boolean;
  version_status: string;
  home_team_id: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  away_team_id: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  home_score_regular: number | null;
  away_score_regular: number | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  winner_team_id: string | null;
  resolution_type: ResolutionType | null;
  rules_config?: {
    stage_defaults?: {
      extra_time_enabled?: boolean;
      penalties_enabled?: boolean;
      walkover_score?: { winner: number; loser: number };
    };
  };
}

interface Segment {
  id: string;
  segment_number: number;
  minute_start: number;
  minute_end: number | null;
  status: SegmentStatus;
}

interface SegmentInterruption {
  id: string;
  match_id: string;
  segment_id: string;
  reason: InterruptionReason;
  minute: number;
  notes: string | null;
  created_at: string;
}

interface Official {
  id: string;
  match_id: string;
  organization_user_id: string;
  official_role: OfficialRole;
  full_name: string;
  email: string;
}

interface EligibleOfficial {
  organization_user_id: string;
  full_name: string;
  email: string;
}

interface RosterEntry {
  roster_id: string;
  player_id: string;
  team_id: string;
  team_name: string;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  is_active: boolean;
  match_roster_id: string | null;
  role: LineupRole | null;
  entered_minute: number | null;
  left_minute: number | null;
  is_valid: boolean | null;
}

interface LineupEntry {
  match_roster_id: string;
  roster_id: string;
  player_id: string;
  team_id: string;
  role: LineupRole;
  entered_minute: number | null;
  left_minute: number | null;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  position_slot: string | null;
}

interface TacticalLineupRow {
  segment_id: string;
  segment_number: number;
  team_id: string;
  formation_code: FormationCode;
  is_public: boolean;
  published_at: string | null;
  player_id: string;
  is_starter: boolean;
  position_slot: string | null;
  first_name: string | null;
  last_name: string | null;
}

interface MatchEvent {
  id: string;
  client_event_id: string;
  event_type: EventType;
  team_id: string;
  team_name: string;
  beneficiary_team_id: string | null;
  player_id: string;
  first_name: string;
  last_name: string;
  minute: number;
  added_minute: number;
  segment_id: string;
  metadata: Record<string, unknown>;
  is_voided: boolean;
}

interface MatchOperation {
  match: MatchRecord;
  segments: Segment[];
  interruptions: SegmentInterruption[];
  officials: Official[];
  eligible_officials: EligibleOfficial[];
  rosters: RosterEntry[];
  lineup: LineupEntry[];
  tactical_lineups: TacticalLineupRow[];
  events: MatchEvent[];
}

interface DraftEvent {
  client_event_id: string;
  event_type: EventType;
  team_id: string;
  beneficiary_team_id: string | null;
  player_id: string;
  minute: number;
  added_minute: number;
  segment_id: string;
  metadata?: Record<string, unknown>;
}

const route = useRoute();
const auth = useAuthStore();
const { request } = useApi();
const { t, statusLabel, dateLocale, errorMessage } = useI18n();
const realtime = useRealtime();
const matchId = String(route.params.id);

const operation = ref<MatchOperation | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const actionError = ref<string | null>(null);
const busyAction = ref<string | null>(null);
const selectedSegmentId = ref('');
const lineupRoles = ref<Record<string, LineupRole | ''>>({});
const lineupPositions = ref<Record<string, string>>({});
const lineupFormations = ref<Record<string, FormationCode | ''>>({});
const draftEvents = ref<DraftEvent[]>([]);
const draftRestored = ref(false);
const draftSavedAt = ref<string | null>(null);
let hydratingDraft = false;
let realtimeRefreshPending = false;

const segmentForm = reactive({ segment_number: 1, minute_start: 0 });
const interruptionForm = reactive<{ reason: InterruptionReason; minute: number; notes: string }>({
  reason: 'other',
  minute: 0,
  notes: '',
});
const officialForm = reactive<{ organization_user_id: string; official_role: OfficialRole }>({
  organization_user_id: '',
  official_role: 'main_referee',
});
const rosterForm = reactive({
  team_id: '',
  first_name: '',
  last_name: '',
  national_id: '',
  birth_date: '',
  dorsal_number: 1,
  photo_consent: false,
});
const eventForm = reactive<{
  event_type: EventType;
  team_id: string;
  beneficiary_team_id: string;
  player_id: string;
  minute: number;
  added_minute: number;
  red_card_type: RedCardType;
}>({
  event_type: 'goal',
  team_id: '',
  beneficiary_team_id: '',
  player_id: '',
  minute: 1,
  added_minute: 0,
  red_card_type: 'direct_red',
});
const closeForm = reactive<{
  resolution_type: ResolutionType;
  home_score_regular: number;
  away_score_regular: number;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  winner_team_id: string;
  reason: string;
}>({
  resolution_type: 'regular',
  home_score_regular: 0,
  away_score_regular: 0,
  home_score: null,
  away_score: null,
  home_penalties: null,
  away_penalties: null,
  winner_team_id: '',
  reason: '',
});

const officialRoles: Array<{ value: OfficialRole; labelKey: string }> = [
  { value: 'main_referee', labelKey: 'match.mainReferee' },
  { value: 'assistant_referee_1', labelKey: 'match.assistantOne' },
  { value: 'assistant_referee_2', labelKey: 'match.assistantTwo' },
  { value: 'fourth_official', labelKey: 'match.fourthOfficial' },
  { value: 'match_commissioner', labelKey: 'match.commissioner' },
];
const eventTypes: Array<{ value: EventType; labelKey: string }> = [
  { value: 'goal', labelKey: 'event.goal' },
  { value: 'own_goal', labelKey: 'event.ownGoal' },
  { value: 'penalty_goal', labelKey: 'event.penaltyGoal' },
  { value: 'yellow_card', labelKey: 'event.yellowCard' },
  { value: 'red_card', labelKey: 'event.redCard' },
  { value: 'substitution', labelKey: 'event.substitution' },
  { value: 'foul', labelKey: 'event.foul' },
];

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

const match = computed(() => operation.value?.match || null);
const isTerminal = computed(() => ['finished', 'cancelled', 'administrative_resolution'].includes(match.value?.status || ''));
const selectedSegment = computed(() => operation.value?.segments.find((segment) => segment.id === selectedSegmentId.value));
const activeSegment = computed(() => operation.value?.segments.find((segment) => segment.status === 'active'));
const selectedSegmentIsActive = computed(() => selectedSegment.value?.status === 'active');
const selectedInterruption = computed(() => operation.value?.interruptions.find((item) => item.segment_id === selectedSegment.value?.id));
const homeRoster = computed(() => operation.value?.rosters.filter((entry) => entry.team_id === match.value?.home_team_id) || []);
const awayRoster = computed(() => operation.value?.rosters.filter((entry) => entry.team_id === match.value?.away_team_id) || []);
const eventPlayers = computed(() => {
  const lineupPlayerIds = new Set(operation.value?.lineup.map((entry) => entry.player_id) || []);
  return operation.value?.rosters.filter((entry) => (
    entry.team_id === eventForm.team_id
    && entry.is_active
    && lineupPlayerIds.has(entry.player_id)
  )) || [];
});
const teamRosters = computed(() => [
  { key: 'home', team_id: match.value?.home_team_id || '', name: match.value?.home_team_name || t('setup.home'), players: homeRoster.value },
  { key: 'away', team_id: match.value?.away_team_id || '', name: match.value?.away_team_name || t('setup.away'), players: awayRoster.value },
]);
const lineupEntries = computed(() => Object.entries(lineupRoles.value).filter(([, role]) => role).map(([roster_id, role]) => ({
  roster_id,
  role,
  position_slot: role === 'starter' ? lineupPositions.value[roster_id] || null : null,
})));
const selectedLineupTeams = computed(() => new Set(lineupEntries.value.map((entry) => {
  return operation.value?.rosters.find((roster) => roster.roster_id === entry.roster_id)?.team_id;
})));
const selectedTacticalLineups = computed(() => operation.value?.tactical_lineups.filter((entry) => entry.segment_id === selectedSegmentId.value) || []);
const hasCompleteLineup = computed(() => {
  const homeTeamId = match.value?.home_team_id;
  const awayTeamId = match.value?.away_team_id;
  return Boolean(homeTeamId && awayTeamId && selectedLineupTeams.value.has(homeTeamId) && selectedLineupTeams.value.has(awayTeamId));
});
const rulesDefaults = computed(() => match.value?.rules_config?.stage_defaults || {});
const operationChecklist = computed(() => [
  { label: t('status.published'), valid: match.value?.version_status === 'published' },
  { label: t('match.activeSegment'), valid: Boolean(activeSegment.value) },
  { label: t('match.roster'), valid: hasCompleteLineup.value || Boolean(operation.value?.lineup.length) },
  { label: t('match.mainReferee'), valid: Boolean(operation.value?.officials.some((official) => official.official_role === 'main_referee')) },
]);

const defaultCloseForm = {
  resolution_type: 'regular' as ResolutionType,
  home_score_regular: 0,
  away_score_regular: 0,
  home_score: null as number | null,
  away_score: null as number | null,
  home_penalties: null as number | null,
  away_penalties: null as number | null,
  winner_team_id: '',
  reason: '',
};

const hasUnsavedDraft = computed(() => draftEvents.value.length > 0 || JSON.stringify({
  ...closeForm,
}) !== JSON.stringify(defaultCloseForm));
const draftStorageKey = computed(() => `bc_match_draft:${auth.userId || 'anonymous'}:${auth.organizationId || 'anonymous'}:${matchId}`);

function closeFormSnapshot() {
  return { ...closeForm };
}

function removePersistedDraft() {
  if (!import.meta.client) return;
  try {
    localStorage.removeItem(draftStorageKey.value);
  } catch {
    // Storage can be unavailable in private browsing.
  }
}

function isDraftEvent(value: unknown): value is DraftEvent {
  if (!value || typeof value !== 'object') return false;
  const event = value as Partial<DraftEvent>;
  return Boolean(
    typeof event.client_event_id === 'string'
    && event.client_event_id.length <= 100
    && eventTypes.some((item) => item.value === event.event_type)
    && typeof event.team_id === 'string'
    && typeof event.player_id === 'string'
    && typeof event.segment_id === 'string'
    && Number.isInteger(event.minute)
    && Number(event.minute) >= 0
    && Number(event.minute) <= 180
    && Number.isInteger(event.added_minute)
    && Number(event.added_minute) >= 0
    && Number(event.added_minute) <= 30,
  );
}

function loadPersistedDraft() {
  if (!import.meta.client || !operation.value) return;
  try {
    const raw = localStorage.getItem(draftStorageKey.value);
    if (!raw) return;
    const saved = JSON.parse(raw) as { match_id?: string; events?: unknown[]; result?: Partial<typeof defaultCloseForm>; saved_at?: string };
    if (saved.match_id && saved.match_id !== matchId) return;
    if (isTerminal.value) {
      removePersistedDraft();
      return;
    }

    hydratingDraft = true;
    draftEvents.value = Array.isArray(saved.events) ? saved.events.filter(isDraftEvent) : [];
    if (saved.result && typeof saved.result === 'object') {
      const result = saved.result;
      if (['regular', 'extra_time', 'penalties', 'walkover', 'administrative'].includes(String(result.resolution_type))) {
        closeForm.resolution_type = result.resolution_type as ResolutionType;
      }
      for (const key of ['home_score_regular', 'away_score_regular', 'home_score', 'away_score', 'home_penalties', 'away_penalties'] as const) {
        const value = result[key];
        if (value === null || (typeof value === 'number' && Number.isInteger(value) && value >= 0)) Object.assign(closeForm, { [key]: value });
      }
      if (typeof result.winner_team_id === 'string') closeForm.winner_team_id = result.winner_team_id;
      if (typeof result.reason === 'string' && result.reason.length <= 1000) closeForm.reason = result.reason;
    }
    draftRestored.value = hasUnsavedDraft.value;
    draftSavedAt.value = typeof saved.saved_at === 'string' ? saved.saved_at : null;
  } catch {
    removePersistedDraft();
  } finally {
    hydratingDraft = false;
  }
}

function persistDraft() {
  if (!import.meta.client || hydratingDraft || !operation.value) return;
  if (isTerminal.value) {
    removePersistedDraft();
    return;
  }
  try {
    if (!hasUnsavedDraft.value) {
      removePersistedDraft();
      draftSavedAt.value = null;
      return;
    }
    const savedAt = new Date().toISOString();
    localStorage.setItem(draftStorageKey.value, JSON.stringify({
      version: 1,
      match_id: matchId,
      events: draftEvents.value,
      result: closeFormSnapshot(),
      saved_at: savedAt,
    }));
    draftSavedAt.value = savedAt;
  } catch {
    // Storage can be unavailable in private browsing; the in-memory draft remains usable.
  }
}

function discardDraft() {
  if (!import.meta.client || !window.confirm(t('match.discardDraft'))) return;
  draftEvents.value = [];
  Object.assign(closeForm, defaultCloseForm);
  draftRestored.value = false;
  persistDraft();
}

function closeValidationError(): string | null {
  const homeTeamId = match.value?.home_team_id;
  const awayTeamId = match.value?.away_team_id;
  if (!homeTeamId || !awayTeamId || !selectedSegmentIsActive.value || !hasCompleteLineup.value) {
    return t('match.needSegmentLineup');
  }
  const scoreFields = [closeForm.home_score_regular, closeForm.away_score_regular, closeForm.home_score, closeForm.away_score, closeForm.home_penalties, closeForm.away_penalties];
  if (scoreFields.some((value) => value !== null && (!Number.isInteger(value) || value < 0))) return t('match.closeValidation');
  const participants = new Set([homeTeamId, awayTeamId]);
  if (closeForm.winner_team_id && !participants.has(closeForm.winner_team_id)) return t('match.closeValidation');

  if (closeForm.resolution_type === 'regular') {
    const goals = { [homeTeamId]: 0, [awayTeamId]: 0 } as Record<string, number>;
    for (const event of draftEvents.value) {
      if (['goal', 'own_goal', 'penalty_goal'].includes(event.event_type)) {
        const beneficiary = event.event_type === 'own_goal' ? event.beneficiary_team_id : event.team_id;
        if (beneficiary && beneficiary in goals) goals[beneficiary] += 1;
      }
    }
    if (goals[homeTeamId] !== closeForm.home_score_regular || goals[awayTeamId] !== closeForm.away_score_regular) {
      return t('match.closeValidation');
    }
  }
  if (['walkover', 'administrative'].includes(closeForm.resolution_type) && draftEvents.value.length) return t('match.closeValidation');
  if (closeForm.resolution_type !== 'regular' && closeForm.winner_team_id === '') return t('match.closeValidation');
  if (closeForm.resolution_type === 'extra_time') {
    if (closeForm.home_score === null || closeForm.away_score === null) return t('match.closeValidation');
    if (closeForm.home_score < closeForm.home_score_regular || closeForm.away_score < closeForm.away_score_regular) return t('match.closeValidation');
  }
  if (closeForm.resolution_type === 'penalties') {
    if (closeForm.home_score === null || closeForm.away_score === null || closeForm.home_score !== closeForm.away_score) return t('match.closeValidation');
    if (closeForm.home_penalties === null || closeForm.away_penalties === null || closeForm.home_penalties === closeForm.away_penalties) return t('match.closeValidation');
  }
  if (closeForm.resolution_type === 'administrative' && (closeForm.home_score === null || closeForm.away_score === null || closeForm.home_score !== closeForm.home_score_regular || closeForm.away_score !== closeForm.away_score_regular)) return t('match.closeValidation');
  if (closeForm.resolution_type === 'administrative' && !closeForm.reason.trim()) return t('match.administrativeReasonRequired');
  if (closeForm.resolution_type !== 'administrative' && closeForm.reason.trim()) return t('match.closeValidation');
  return null;
}

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

async function redirectOnSessionFailure(cause: unknown): Promise<boolean> {
  if (isUnauthorized(cause) || isNotFound(cause)) {
    await auth.logout();
    await navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(route.fullPath, '/workspace') } });
    return true;
  }
  if (isForbidden(cause)) {
    await navigateTo({ path: '/forbidden', query: { returnTo: safeInternalRedirect(route.fullPath, '/workspace'), resource: 'match' } });
    return true;
  }
  return false;
}

function applyOperation(value: MatchOperation) {
  operation.value = value;
  const currentSegment = value.segments.find((segment) => segment.id === selectedSegmentId.value);
  const nextActiveSegment = value.segments.find((segment) => segment.status === 'active');
  if (!currentSegment || (currentSegment.status !== 'active' && nextActiveSegment)) {
    selectedSegmentId.value = nextActiveSegment?.id || value.segments.at(-1)?.id || '';
  }
  segmentForm.segment_number = Math.max(1, ...value.segments.map((segment) => segment.segment_number + 1));
  if (nextActiveSegment) interruptionForm.minute = nextActiveSegment.minute_start;
  if (!rosterForm.team_id) {
    rosterForm.team_id = value.match.home_team_id || value.match.away_team_id || '';
  }
  if (!eventForm.team_id) {
    eventForm.team_id = value.match.home_team_id || value.match.away_team_id || '';
  }
  lineupRoles.value = Object.fromEntries(value.lineup.map((entry) => [entry.roster_id, entry.role])) as Record<string, LineupRole>;
  syncTacticalEditor();
}

function syncTacticalEditor() {
  const rows = selectedTacticalLineups.value;
  const formations: Record<string, FormationCode | ''> = {};
  const positions: Record<string, string> = {};
  const roles: Record<string, LineupRole | ''> = {};
  for (const row of rows) {
    formations[row.team_id] = row.formation_code;
    if (row.player_id && row.position_slot) {
      const roster = operation.value?.rosters.find((entry) => entry.player_id === row.player_id && entry.team_id === row.team_id);
      if (roster) positions[roster.roster_id] = row.position_slot;
    }
    if (row.player_id) {
      const roster = operation.value?.rosters.find((entry) => entry.player_id === row.player_id && entry.team_id === row.team_id);
      if (roster) roles[roster.roster_id] = row.is_starter ? 'starter' : 'substitute';
    }
  }
  lineupFormations.value = formations;
  lineupPositions.value = positions;
  if (rows.length) {
    for (const roster of operation.value?.rosters || []) {
      if (roster.team_id === match.value?.home_team_id || roster.team_id === match.value?.away_team_id) {
        roles[roster.roster_id] ||= '';
      }
    }
    lineupRoles.value = roles;
  }
}

function setFormation(teamId: string, event: Event) {
  const formation = (event.target as HTMLSelectElement).value as FormationCode | '';
  lineupFormations.value[teamId] = formation;
  const allowed = new Set(formationSlots(formation));
  for (const roster of operation.value?.rosters.filter((entry) => entry.team_id === teamId) || []) {
    if (!allowed.has(lineupPositions.value[roster.roster_id])) delete lineupPositions.value[roster.roster_id];
  }
}

function availablePositions(teamId: string): string[] {
  return formationSlots(lineupFormations.value[teamId] || '');
}

function positionLabel(position: string): string {
  return position.replace('_', ' ');
}

function tacticalRowsForTeam(teamId: string): TacticalLineupRow[] {
  return selectedTacticalLineups.value.filter((entry) => entry.team_id === teamId);
}

function isTeamLineupPublic(teamId: string): boolean {
  return tacticalRowsForTeam(teamId).some((entry) => entry.is_public);
}

async function toggleLineupPublication(teamId: string) {
  if (!selectedSegmentId.value) return;
  await runAction(`lineup-publication-${teamId}`, async () => {
    await request(`/matches/${matchId}/lineup/publication`, {
      method: 'PATCH',
      body: {
        segment_id: selectedSegmentId.value,
        team_id: teamId,
        is_public: !isTeamLineupPublic(teamId),
      },
    });
    await refreshOperation();
  });
}

async function fetchOperation(): Promise<MatchOperation> {
  return await request<MatchOperation>(`/matches/${matchId}/operation`);
}

async function refreshOperation() {
  applyOperation(await fetchOperation());
}

async function retryOperation() {
  error.value = null;
  try {
    await refreshOperation();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) error.value = failureMessage(cause, t('match.noLoad'));
  }
}

function payloadTargetsMatch(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object') return true;
  const value = payload as { match_id?: unknown };
  return value.match_id === undefined || String(value.match_id) === matchId;
}

async function refreshFromRealtime(payload: unknown) {
  if (!payloadTargetsMatch(payload) || realtimeRefreshPending || busyAction.value || isTerminal.value) return;
  realtimeRefreshPending = true;
  try {
    await refreshOperation();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = failureMessage(cause, t('match.noLoad'));
  } finally {
    realtimeRefreshPending = false;
  }
}

async function runAction(action: string, callback: () => Promise<void>) {
  busyAction.value = action;
  actionError.value = null;
  try {
    await callback();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    actionError.value = failureMessage(cause, t('match.noOperation'));
  } finally {
    busyAction.value = null;
  }
}

async function createSegment() {
  await runAction('segment', async () => {
    await request(`/matches/${matchId}/segments`, { method: 'POST', body: { ...segmentForm } });
    segmentForm.segment_number += 1;
    segmentForm.minute_start = 0;
    await refreshOperation();
  });
}

async function interruptSegment() {
  if (!activeSegment.value) {
    actionError.value = t('match.noActiveSegment');
    return;
  }
  if (draftEvents.value.some((event) => event.segment_id === activeSegment.value!.id)) {
    actionError.value = t('match.pendingEventsBeforeInterruption');
    return;
  }
  await runAction('interrupt-segment', async () => {
    await request(`/matches/${matchId}/segments/${activeSegment.value!.id}/interrupt`, {
      method: 'POST',
      body: {
        reason: interruptionForm.reason,
        minute: interruptionForm.minute,
        notes: interruptionForm.notes || null,
      },
    });
    segmentForm.minute_start = interruptionForm.minute;
    interruptionForm.notes = '';
    await refreshOperation();
  });
}

async function assignOfficial() {
  if (!officialForm.organization_user_id) return;
  await runAction('official', async () => {
    await request(`/matches/${matchId}/officials`, { method: 'POST', body: { ...officialForm } });
    officialForm.organization_user_id = '';
    await refreshOperation();
  });
}

async function removeOfficial(official: Official) {
  await runAction(`remove-official-${official.id}`, async () => {
    await request(`/matches/${matchId}/officials/${official.organization_user_id}/${official.official_role}`, { method: 'DELETE' });
    await refreshOperation();
  });
}

async function addRosterPlayer() {
  if (!rosterForm.team_id) return;
  await runAction('roster', async () => {
    await request(`/tournaments/${match.value?.tournament_id}/rosters`, {
      method: 'POST',
      body: { ...rosterForm },
    });
    rosterForm.first_name = '';
    rosterForm.last_name = '';
    rosterForm.national_id = '';
    rosterForm.dorsal_number = 1;
    await refreshOperation();
  });
}

async function saveLineup() {
  if (!selectedSegmentId.value || !selectedSegmentIsActive.value) {
    actionError.value = t('match.createSegmentFirst');
    return;
  }
  await runAction('lineup', async () => {
    await request(`/matches/${matchId}/lineup`, {
      method: 'PUT',
      body: {
        segment_id: selectedSegmentId.value,
        entries: lineupEntries.value,
        team_lineups: teamRosters.value
          .filter((team) => team.team_id && lineupFormations.value[team.team_id])
          .map((team) => ({ team_id: team.team_id, formation_code: lineupFormations.value[team.team_id] })),
      },
    });
    await refreshOperation();
  });
}

watch(selectedSegmentId, () => {
  if (operation.value) syncTacticalEditor();
});

function addEvent() {
  if (!selectedSegmentId.value || !selectedSegmentIsActive.value || !eventForm.team_id || !eventForm.player_id) {
    actionError.value = t('match.needSegmentEvent');
    return;
  }
  if (eventForm.event_type === 'own_goal' && !eventForm.beneficiary_team_id) {
    actionError.value = t('match.ownGoalBeneficiary');
    return;
  }
  draftEvents.value.push({
    client_event_id: globalThis.crypto?.randomUUID?.() || `event-${Date.now()}-${draftEvents.value.length}`,
    event_type: eventForm.event_type,
    team_id: eventForm.team_id,
    beneficiary_team_id: eventForm.event_type === 'own_goal' ? eventForm.beneficiary_team_id : null,
    player_id: eventForm.player_id,
    minute: eventForm.minute,
    added_minute: eventForm.added_minute,
    segment_id: selectedSegmentId.value,
    metadata: eventForm.event_type === 'red_card'
      ? { red_card_type: eventForm.red_card_type }
      : undefined,
  });
  eventForm.player_id = '';
  eventForm.beneficiary_team_id = '';
  eventForm.red_card_type = 'direct_red';
  actionError.value = null;
}

function removeEvent(clientEventId: string) {
  draftEvents.value = draftEvents.value.filter((event) => event.client_event_id !== clientEventId);
}

watch([draftEvents, closeForm], persistDraft, { deep: true });

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedDraft.value || isTerminal.value) return;
  event.preventDefault();
  event.returnValue = '';
}

onBeforeRouteLeave(() => {
  if (!import.meta.client || !hasUnsavedDraft.value || isTerminal.value) return true;
  return window.confirm(t('match.unsavedLeave'));
});

async function closeMatch() {
  const validationError = closeValidationError();
  if (validationError) {
    actionError.value = validationError;
    return;
  }
  if (import.meta.client && !window.confirm(t('match.confirmClosePrompt'))) return;
  await runAction('close', async () => {
    await request(`/matches/${matchId}/close`, {
      method: 'POST',
      body: {
        resolution_type: closeForm.resolution_type,
        home_score_regular: closeForm.home_score_regular,
        away_score_regular: closeForm.away_score_regular,
        home_score: closeForm.resolution_type === 'regular' ? null : closeForm.home_score,
        away_score: closeForm.resolution_type === 'regular' ? null : closeForm.away_score,
        home_penalties: closeForm.resolution_type === 'penalties' ? closeForm.home_penalties : null,
        away_penalties: closeForm.resolution_type === 'penalties' ? closeForm.away_penalties : null,
        winner_team_id: ['regular'].includes(closeForm.resolution_type) ? null : closeForm.winner_team_id || null,
        reason: closeForm.resolution_type === 'administrative' ? closeForm.reason.trim() : null,
        events: draftEvents.value,
      },
    });
    draftEvents.value = [];
    draftRestored.value = false;
    await refreshOperation();
    removePersistedDraft();
  });
}

function playerName(roster: RosterEntry): string {
  return `${roster.first_name} ${roster.last_name}`;
}

function teamName(teamId: string | null): string {
  if (teamId === match.value?.home_team_id) return match.value?.home_team_name || t('setup.home');
  if (teamId === match.value?.away_team_id) return match.value?.away_team_name || t('setup.away');
  return t('setup.teams');
}

function eventLabel(eventType: EventType): string {
  const key = eventTypes.find((event) => event.value === eventType)?.labelKey;
  return key ? t(key) : eventType;
}

function officialLabel(role: OfficialRole): string {
  const key = officialRoles.find((item) => item.value === role)?.labelKey;
  return key ? t(key) : role;
}

function formatDate(value: string | null): string {
  if (!value) return t('public.dateToDefine');
  return new Intl.DateTimeFormat(dateLocale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

watch(() => eventForm.team_id, () => {
  if (!eventPlayers.value.some((player) => player.player_id === eventForm.player_id)) eventForm.player_id = '';
  if (eventForm.beneficiary_team_id === eventForm.team_id) eventForm.beneficiary_team_id = '';
});

watch(() => closeForm.resolution_type, (resolutionType) => {
  if (resolutionType !== 'administrative') closeForm.reason = '';
});

const { data: initialOperation, error: initialOperationError } = await useAsyncData<MatchOperation>(
  `workspace-match-${matchId}-${auth.userId || 'none'}-${auth.organizationId || 'none'}-${auth.sessionVersion}`,
  fetchOperation,
);

if (initialOperationError.value) {
  if (!(await redirectOnSessionFailure(initialOperationError.value))) {
    error.value = failureMessage(initialOperationError.value, t('match.noLoad'));
  }
} else if (initialOperation.value) {
  applyOperation(initialOperation.value);
}
loading.value = false;

if (operation.value) loadPersistedDraft();

const realtimeStatusLabel = computed(() => {
  if (realtime.status.value === 'connected') return t('match.realtimeConnected');
  if (realtime.status.value === 'reconnecting') return t('match.realtimeReconnecting');
  if (realtime.status.value === 'error') return t('match.realtimeError');
  return '';
});

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload);
  realtime.connect({
    onEvent: (event, payload) => {
      if (['MATCH_CLOSED', 'MATCH_UPDATED'].includes(event)) void refreshFromRealtime(payload);
    },
  });
});

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload);
  realtime.disconnect();
});
</script>

<template>
  <main id="main-content" class="operation-shell">
    <header class="container operation-topbar">
      <NuxtLink to="/workspace" class="brand-mark"><span class="brand-dot" aria-hidden="true" /> BRACKET CRAFT</NuxtLink>
      <div class="operation-actions">
        <span v-if="realtimeStatusLabel" class="realtime-status" :class="`realtime-${realtime.status.value}`" role="status">{{ realtimeStatusLabel }}</span>
        <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="realtime.connect()">{{ t('common.retry') }}</button>
        <NuxtLink v-if="match" :to="`/workspace/tournaments/${match.tournament_id}`" class="button-secondary">{{ t('common.back') }}</NuxtLink>
      </div>
    </header>

    <section class="container operation-hero">
      <div class="hero-line">
        <p class="eyebrow">{{ t('match.matchReport') }}</p>
        <span class="status-pill" :class="{ finished: isTerminal, interrupted: match?.status === 'interrupted' }">{{ statusLabel(match?.status) }}</span>
      </div>
      <div v-if="match" class="match-heading">
        <div>
          <p class="context-line">{{ match.tournament_name }} · {{ match.stage_name }} · {{ t('public.matchday', { value: match.matchday || '-' }) }}</p>
          <h1>{{ match.home_team_name || t('public.toDefine') }} <span>vs</span> {{ match.away_team_name || t('public.toDefine') }}</h1>
          <p class="workspace-copy">{{ formatDate(match.match_date) }}<span v-if="match.group_name"> · {{ match.group_name }}</span></p>
        </div>
        <div class="scoreboard" :aria-label="t('match.result')">
          <strong>{{ match.home_score ?? '—' }}</strong>
          <span>:</span>
          <strong>{{ match.away_score ?? '—' }}</strong>
        </div>
      </div>
    </section>

    <section class="container operation-content">
      <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('match.loadingOperation') }}</div>
       <div v-else-if="error" class="form-error" role="alert"><span>{{ error }}</span><button class="button-secondary" type="button" @click="retryOperation">{{ t('common.retry') }}</button></div>
      <template v-else-if="operation && match">
        <div class="checklist" :aria-label="t('match.matchReport')">
          <div v-for="item in operationChecklist" :key="item.label" class="check-item" :class="{ valid: item.valid }">
            <span aria-hidden="true">{{ item.valid ? '✓' : '!' }}</span><strong>{{ item.label }}</strong><small>{{ item.valid ? t('common.ready') : t('common.incomplete') }}</small>
          </div>
        </div>

        <div v-if="actionError" class="form-error" role="alert">{{ actionError }}</div>

        <div class="operation-grid">
          <section class="panel panel-wide">
            <div class="panel-heading">
              <div><p class="eyebrow">01 · {{ t('match.matchReport') }}</p><h2>{{ t('match.prepareField') }}</h2></div>
              <span class="muted-note">{{ t('match.segments', { count: operation.segments.length }) }}</span>
            </div>
            <div class="sub-grid">
              <div class="soft-panel">
                <h3>{{ t('match.gameSegments') }}</h3>
                <div class="field-row">
                  <label>{{ t('match.segmentNumber') }}<input v-model.number="segmentForm.segment_number" type="number" min="1" required /></label>
                  <label>{{ t('match.startMinute') }}<input v-model.number="segmentForm.minute_start" type="number" min="0" required /></label>
                </div>
                  <label>{{ t('match.activeSegment') }}
                   <select v-model="selectedSegmentId" required>
                     <option value="" disabled>{{ t('match.selectSegment') }}</option>
                     <option v-for="segment in operation.segments" :key="segment.id" :value="segment.id">{{ t('match.segmentOption', { number: segment.segment_number, minute: segment.minute_start }) }} · {{ statusLabel(segment.status) }}</option>
                   </select>
                 </label>
                 <div v-if="selectedSegment" class="segment-status">
                   <span class="muted-note">{{ t('match.segmentStatus') }}</span>
                   <strong>{{ statusLabel(selectedSegment.status) }}</strong>
                 </div>
                 <p v-if="!activeSegment" class="segment-warning">{{ t('match.noActiveSegment') }}</p>
                  <button class="button-primary" type="button" :disabled="Boolean(busyAction) || isTerminal" @click="createSegment">{{ activeSegment ? t('match.createSegment') : t('match.startNextSegment') }}</button>
                 <form v-if="activeSegment" class="interruption-form" @submit.prevent="interruptSegment">
                   <h3>{{ t('match.interruptSegment') }}</h3>
                   <p class="muted-note">{{ t('match.interruptionHint') }}</p>
                   <label>{{ t('match.interruptReason') }}<select v-model="interruptionForm.reason"><option value="lighting_failure">{{ t('match.reasonLightingFailure') }}</option><option value="weather">{{ t('match.reasonWeather') }}</option><option value="pitch_invasion">{{ t('match.reasonPitchInvasion') }}</option><option value="other">{{ t('match.reasonOther') }}</option></select></label>
                   <label>{{ t('match.interruptMinute') }}<input v-model.number="interruptionForm.minute" type="number" min="0" required /></label>
                   <label>{{ t('match.interruptNotes') }}<textarea v-model="interruptionForm.notes" maxlength="1000" :placeholder="t('match.interruptNotesPlaceholder')" /></label>
                   <button class="button-secondary" type="submit" :disabled="Boolean(busyAction) || isTerminal">{{ busyAction === 'interrupt-segment' ? t('common.processing') : t('match.interruptSegment') }}</button>
                 </form>
                 <div v-if="selectedInterruption" class="interruption-note">
                   <strong>{{ t('match.interruptionRegistered') }}</strong>
                   <span>{{ t(`match.reason${selectedInterruption.reason === 'lighting_failure' ? 'LightingFailure' : selectedInterruption.reason === 'pitch_invasion' ? 'PitchInvasion' : selectedInterruption.reason === 'weather' ? 'Weather' : 'Other'}`) }} · {{ selectedInterruption.minute }}'</span>
                   <small v-if="selectedInterruption.notes">{{ selectedInterruption.notes }}</small>
                  </div>
                </div>

              <div class="soft-panel">
                <h3>{{ t('match.officials') }}</h3>
                <form class="field-row official-row" @submit.prevent="assignOfficial">
                  <label>{{ t('match.person') }}<select v-model="officialForm.organization_user_id" required><option value="" disabled>{{ t('match.selectOfficial') }}</option><option v-for="official in operation.eligible_officials" :key="official.organization_user_id" :value="official.organization_user_id">{{ official.full_name }} · {{ official.email }}</option></select></label>
                  <label>{{ t('match.role') }}<select v-model="officialForm.official_role"><option v-for="role in officialRoles" :key="role.value" :value="role.value">{{ t(role.labelKey) }}</option></select></label>
                  <button class="button-secondary compact-button" type="submit" :disabled="Boolean(busyAction) || isTerminal">{{ t('match.assign') }}</button>
                 </form>
                <ul v-if="operation.officials.length" class="compact-list">
                  <li v-for="official in operation.officials" :key="official.id"><span><strong>{{ officialLabel(official.official_role) }}</strong> · {{ official.full_name }}</span><button type="button" class="text-button" :disabled="Boolean(busyAction) || isTerminal" @click="removeOfficial(official)">{{ t('match.remove') }}</button></li>
                </ul>
                <p v-else class="muted-note">{{ t('match.noOfficials') }}</p>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-heading"><div><p class="eyebrow">02 · {{ t('match.roster') }}</p><h2>{{ t('match.roster') }}</h2></div></div>
            <form class="roster-form" @submit.prevent="addRosterPlayer">
              <label>{{ t('setup.teams') }}<select v-model="rosterForm.team_id" required><option value="" disabled>{{ t('match.selectTeam') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></label>
              <div class="field-row"><label>{{ t('match.firstName') }}<input v-model="rosterForm.first_name" required maxlength="100" /></label><label>{{ t('match.lastName') }}<input v-model="rosterForm.last_name" required maxlength="100" /></label></div>
              <label>{{ t('match.document') }} <span class="field-hint">{{ t('match.encryptedOnServer') }}</span><input v-model="rosterForm.national_id" required maxlength="100" autocomplete="off" /></label>
              <div class="field-row"><label>{{ t('match.birthDate') }}<input v-model="rosterForm.birth_date" type="date" required /></label><label>{{ t('match.number') }}<input v-model.number="rosterForm.dorsal_number" type="number" min="1" max="999" required /></label></div>
              <label class="checkbox-label"><input v-model="rosterForm.photo_consent" type="checkbox" /> {{ t('match.imageConsent') }}</label>
              <button class="button-primary" type="submit" :disabled="Boolean(busyAction) || isTerminal || !rosterForm.team_id">{{ t('match.addPlayer') }}</button>
            </form>
          </section>

           <section class="panel panel-wide">
              <div class="panel-heading"><div><p class="eyebrow">03 · {{ t('match.roster') }}</p><h2>{{ t('match.definePlayers') }}</h2></div><button class="button-primary" type="button" :disabled="Boolean(busyAction) || isTerminal || !selectedSegmentIsActive" @click="saveLineup">{{ busyAction === 'lineup' ? t('match.savingLineup') : t('match.saveLineup') }}</button></div>
              <p class="panel-description">{{ t('match.selectRoles', { segment: selectedSegment?.segment_number || t('match.activeSegment') }) }}</p>
              <p v-if="!selectedSegmentIsActive" class="segment-warning">{{ t('match.noActiveSegment') }}</p>
             <div class="formation-config-grid">
               <div v-for="team in teamRosters" :key="`${team.key}-formation`" class="formation-config">
                 <div class="formation-config-heading">
                   <strong>{{ team.name }}</strong>
                   <span v-if="team.team_id && tacticalRowsForTeam(team.team_id).length" :class="['publication-state', { published: isTeamLineupPublic(team.team_id) }]">
                     {{ isTeamLineupPublic(team.team_id) ? t('match.lineupPublished') : t('match.lineupPrivate') }}
                   </span>
                 </div>
                 <label>{{ t('match.formation') }}
                   <select :value="lineupFormations[team.team_id] || ''" :disabled="!team.team_id || isTerminal || !selectedSegmentIsActive" @change="setFormation(team.team_id, $event)">
                     <option value="">{{ t('match.classicLineup') }}</option>
                     <option v-for="formation in FORMATION_OPTIONS" :key="formation" :value="formation">{{ formation }}</option>
                   </select>
                 </label>
                 <button v-if="team.team_id && lineupFormations[team.team_id]" class="text-button publication-button" type="button" :disabled="Boolean(busyAction) || isTerminal || !tacticalRowsForTeam(team.team_id).length" @click="toggleLineupPublication(team.team_id)">
                   {{ isTeamLineupPublic(team.team_id) ? t('match.unpublishLineup') : t('match.publishLineup') }}
                 </button>
               </div>
             </div>
             <div class="roster-columns">
               <div v-for="team in teamRosters" :key="team.key" class="roster-team">
                 <div class="team-heading"><strong>{{ team.name }}</strong><span>{{ t('match.eligible', { count: team.players.length }) }}</span></div>
                 <div v-if="team.players.length" class="player-list">
                   <label v-for="player in team.players" :key="player.roster_id" class="player-row">
                     <span class="player-number">{{ player.dorsal_number }}</span><span class="player-name">{{ playerName(player) }}</span>
                      <select v-model="lineupRoles[player.roster_id]" :disabled="!player.is_active || isTerminal || !selectedSegmentIsActive" :aria-label="`${t('match.role')} ${playerName(player)}`"><option value="">{{ t('match.notParticipating') }}</option><option value="starter">{{ t('match.starter') }}</option><option value="substitute">{{ t('match.substitute') }}</option></select>
                      <select v-if="lineupRoles[player.roster_id] === 'starter'" v-model="lineupPositions[player.roster_id]" :disabled="!player.is_active || isTerminal || !selectedSegmentIsActive || !lineupFormations[team.team_id]" :aria-label="`${t('match.position')} ${playerName(player)}`">
                        <option value="">{{ t('match.selectPosition') }}</option>
                        <option v-for="position in availablePositions(team.team_id)" :key="position" :value="position">{{ positionLabel(position) }}</option>
                      </select>
                      <span v-else class="position-placeholder">{{ t('match.noTacticalPosition') }}</span>
                   </label>
                 </div>
                <p v-else class="muted-note">{{ t('match.noPlayers') }}</p>
              </div>
            </div>
          </section>

           <section class="panel panel-wide">
             <div class="panel-heading">
               <div><p class="eyebrow">04 · {{ t('match.events') }}</p><h2>{{ t('match.buildReport') }}</h2></div>
               <div class="draft-status-group">
                 <span v-if="hasUnsavedDraft" class="draft-indicator" role="status">{{ draftRestored ? t('match.draftRestored') : t('match.unsavedDraft') }}</span>
                 <span class="muted-note">{{ t('match.pendingEvents', { count: draftEvents.length }) }}</span>
               </div>
             </div>
            <div class="event-form">
              <label>{{ t('match.eventType') }}<select v-model="eventForm.event_type"><option v-for="event in eventTypes" :key="event.value" :value="event.value">{{ t(event.labelKey) }}</option></select></label>
              <label>{{ t('setup.teams') }}<select v-model="eventForm.team_id"><option value="" disabled>{{ t('match.select') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></label>
               <label>{{ t('match.player') }}<select v-model="eventForm.player_id"><option value="" disabled>{{ t('match.select') }}</option><option v-for="player in eventPlayers" :key="player.roster_id" :value="player.player_id">#{{ player.dorsal_number }} · {{ playerName(player) }}</option></select></label>
               <label v-if="eventForm.event_type === 'red_card'">{{ t('match.redCardType') }}<select v-model="eventForm.red_card_type"><option value="direct_red">{{ t('match.directRed') }}</option><option value="double_yellow_red">{{ t('match.doubleYellowRed') }}</option></select></label>
               <label>{{ t('match.minute') }}<input v-model.number="eventForm.minute" type="number" min="0" max="180" required /></label>
              <label>{{ t('match.addedMinute') }}<input v-model.number="eventForm.added_minute" type="number" min="0" max="30" /></label>
              <label v-if="eventForm.event_type === 'own_goal'">{{ t('match.beneficiary') }}<select v-model="eventForm.beneficiary_team_id" required><option value="" disabled>{{ t('match.select') }}</option><option v-if="match.home_team_id && match.home_team_id !== eventForm.team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id && match.away_team_id !== eventForm.team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></label>
               <button class="button-secondary" type="button" :disabled="isTerminal || !selectedSegmentIsActive" @click="addEvent">{{ t('match.addEvent') }}</button>
            </div>
             <ul v-if="draftEvents.length" class="event-list">
               <li v-for="event in draftEvents" :key="event.client_event_id"><span><strong>{{ event.minute }}' · {{ eventLabel(event.event_type) }}</strong> · {{ teamName(event.team_id) }} · {{ operation.rosters.find((player) => player.player_id === event.player_id)?.first_name }} {{ operation.rosters.find((player) => player.player_id === event.player_id)?.last_name }}</span><button type="button" class="text-button" @click="removeEvent(event.client_event_id)">{{ t('match.remove') }}</button></li>
             </ul>
             <button v-if="hasUnsavedDraft" class="text-button draft-discard" type="button" @click="discardDraft">{{ t('match.discardDraft') }}</button>
             <ul v-if="!draftEvents.length && operation.events.length" class="event-list persisted-events">
               <li v-for="event in operation.events" :key="event.id"><span><strong>{{ event.minute }}' · {{ eventLabel(event.event_type) }}</strong> · {{ event.team_name }} · {{ event.first_name }} {{ event.last_name }}</span><small>{{ event.is_voided ? t('match.voided') : t('match.confirmed') }}</small></li>
            </ul>
              <p v-else-if="!draftEvents.length" class="muted-note">{{ t('match.eventsAtomic') }}</p>
          </section>

           <section class="panel close-panel panel-wide">
            <div class="panel-heading"><div><p class="eyebrow">05 · {{ t('match.result') }}</p><h2>{{ t('match.closeReport') }}</h2></div><span class="muted-note">{{ rulesDefaults.extra_time_enabled ? t('match.overtimeEnabled') : t('match.noOvertime') }}</span></div>
            <div class="score-form">
              <label>{{ t('match.resolution') }}<select v-model="closeForm.resolution_type" :disabled="isTerminal"><option value="regular">{{ t('match.regularTime') }}</option><option value="extra_time" :disabled="!rulesDefaults.extra_time_enabled">{{ t('match.overtime') }}</option><option value="penalties" :disabled="!rulesDefaults.penalties_enabled">{{ t('match.penaltyShootout') }}</option><option value="walkover">{{ t('match.walkover') }}</option><option value="administrative">{{ t('match.administrative') }}</option></select></label>
              <label>{{ match.home_team_name }} · {{ t('match.regularScore') }}<input v-model.number="closeForm.home_score_regular" type="number" min="0" required :disabled="isTerminal" /></label>
              <label>{{ match.away_team_name }} · {{ t('match.regularScore') }}<input v-model.number="closeForm.away_score_regular" type="number" min="0" required :disabled="isTerminal" /></label>
              <template v-if="closeForm.resolution_type !== 'regular'">
                 <label>{{ match.home_team_name }} · {{ t('match.finalScore') }}<input v-model.number="closeForm.home_score" type="number" min="0" :required="closeForm.resolution_type !== 'walkover'" :disabled="isTerminal" /></label>
                 <label>{{ match.away_team_name }} · {{ t('match.finalScore') }}<input v-model.number="closeForm.away_score" type="number" min="0" :required="closeForm.resolution_type !== 'walkover'" :disabled="isTerminal" /></label>
                 <label v-if="closeForm.resolution_type === 'penalties'">{{ t('match.homePenalties') }}<input v-model.number="closeForm.home_penalties" type="number" min="0" required :disabled="isTerminal" /></label>
                 <label v-if="closeForm.resolution_type === 'penalties'">{{ t('match.awayPenalties') }}<input v-model.number="closeForm.away_penalties" type="number" min="0" required :disabled="isTerminal" /></label>
                  <label>{{ t('match.winner') }}<select v-model="closeForm.winner_team_id" required :disabled="isTerminal"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></label>
               </template>
               <label v-if="closeForm.resolution_type === 'administrative'" class="full-width">{{ t('match.administrativeReason') }}<textarea v-model="closeForm.reason" maxlength="1000" required :disabled="isTerminal" /></label>
             </div>
               <div class="close-actions"><p class="muted-note">{{ t('match.backendValidation') }}</p><button class="button-primary close-button" type="button" :disabled="Boolean(busyAction) || isTerminal || !selectedSegmentIsActive" @click="closeMatch">{{ busyAction === 'close' ? t('match.closing') : isTerminal ? t('match.closed') : t('match.confirmReport') }}</button></div>
          </section>
        </div>
      </template>
    </section>
  </main>
</template>

<style scoped>
.operation-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, rgba(212, 243, 106, 0.09), transparent 30rem), #0c0f0c; }
.operation-topbar { display: flex; justify-content: space-between; align-items: center; padding: 24px 0; }
.operation-actions { display: flex; align-items: center; gap: 12px; }
.realtime-status { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; }
.realtime-error, .realtime-reconnecting { color: #ffcb7a; }
.realtime-retry { padding: 0; background: transparent; color: var(--accent); font-size: 0.68rem; text-decoration: underline; }
.brand-mark { display: inline-flex; align-items: center; gap: 9px; color: var(--ink); font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.brand-mark:hover { color: var(--accent); }
.brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); }
.operation-hero { padding: 7vh 0 5vh; animation: rise-in 700ms var(--ease-out) both; }
.hero-line, .panel-heading, .team-heading, .close-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.status-pill, .check-item { display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--line); border-radius: 999px; padding: 0.42rem 0.7rem; color: var(--muted); font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; }
.status-pill.finished { color: var(--accent); border-color: rgba(212, 243, 106, 0.4); }
.status-pill.interrupted { color: #ffcb7a; border-color: rgba(255, 203, 122, 0.4); }
.match-heading { display: flex; align-items: end; justify-content: space-between; gap: 30px; margin-top: 18px; }
.context-line, .workspace-copy, .panel-description { color: var(--muted); }
.context-line { margin: 0; font-size: 0.82rem; letter-spacing: 0.08em; text-transform: uppercase; }
.match-heading h1 { max-width: 880px; margin: 12px 0; font-size: clamp(2.4rem, 6vw, 5.4rem); line-height: 0.93; letter-spacing: -0.08em; }
.match-heading h1 span { color: var(--accent); font-weight: 400; }
.workspace-copy { line-height: 1.5; }
.scoreboard { display: flex; align-items: center; gap: 9px; color: var(--accent); font-size: clamp(2.8rem, 7vw, 6rem); font-weight: 800; letter-spacing: -0.09em; white-space: nowrap; }
.scoreboard span { color: var(--muted); font-weight: 300; }
.operation-content { padding-bottom: 90px; }
.checklist { display: flex; flex-wrap: wrap; gap: 9px; margin-bottom: 18px; }
.check-item { border-radius: 10px; text-transform: none; letter-spacing: 0; }
.check-item span { display: grid; width: 19px; height: 19px; place-items: center; border-radius: 50%; background: rgba(255, 176, 168, 0.12); color: var(--danger); font-weight: 900; }
.check-item small { color: var(--muted); font-size: 0.68rem; }
.check-item.valid { border-color: rgba(212, 243, 106, 0.28); color: var(--ink); }
.check-item.valid span { background: rgba(212, 243, 106, 0.18); color: var(--accent); }
.operation-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.panel { display: grid; align-content: start; gap: 18px; min-width: 0; padding: 23px; border: 1px solid var(--line); border-radius: 20px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.92), rgba(21, 24, 20, 0.96)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.14); }
.panel:hover { border-color: rgba(212, 243, 106, 0.3); }
.panel-wide { grid-column: 1 / -1; }
.panel h2 { margin: 0; font-size: 1.7rem; letter-spacing: -0.05em; }
.panel h3 { margin: 0 0 12px; font-size: 1rem; }
.eyebrow { margin: 0 0 7px; color: var(--accent); font-size: 0.7rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; }
.muted-note, .field-hint { color: var(--muted); font-size: 0.78rem; line-height: 1.5; }
.sub-grid, .roster-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.soft-panel { display: grid; align-content: start; gap: 13px; padding: 17px; border: 1px solid rgba(166, 170, 159, 0.16); border-radius: 14px; background: rgba(12, 15, 12, 0.32); }
.segment-status { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-radius: 10px; background: rgba(212, 243, 106, 0.08); }
.segment-status strong { color: var(--accent); font-size: 0.78rem; }
.segment-warning { margin: 0; padding: 10px 12px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 10px; color: #ffcb7a; font-size: 0.78rem; line-height: 1.45; }
.interruption-form { display: grid; gap: 11px; padding-top: 13px; border-top: 1px solid var(--line); }
.interruption-form h3 { margin: 0; }
.interruption-note { display: grid; gap: 4px; padding: 10px 12px; border-left: 2px solid #ffcb7a; background: rgba(255, 203, 122, 0.08); font-size: 0.78rem; }
.interruption-note strong { color: #ffcb7a; }
.interruption-note small { color: var(--muted); }
.formation-config-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.formation-config { display: grid; gap: 10px; padding: 14px; border: 1px solid rgba(212, 243, 106, 0.2); border-radius: 12px; background: rgba(212, 243, 106, 0.04); }
.formation-config-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.formation-config-heading strong { font-size: 0.88rem; }
.publication-state { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; }
.publication-state.published { color: var(--accent); }
.publication-button { justify-self: start; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.78rem; }
input, select, textarea { min-width: 0; padding: 0.75rem 0.8rem; border: 1px solid var(--line); border-radius: 9px; background: #0c0f0c; color: var(--ink); font: inherit; }
textarea { min-height: 74px; resize: vertical; }
input:hover, select:hover { border-color: var(--muted); }
input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.field-row, .event-form, .score-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.full-width { grid-column: 1 / -1; }
.event-form { grid-template-columns: repeat(6, minmax(0, 1fr)); align-items: end; }
.event-form button { min-height: 43px; }
.official-row { grid-template-columns: minmax(0, 1fr) minmax(150px, 0.7fr) auto; align-items: end; }
.roster-form { display: grid; gap: 11px; }
.checkbox-label { display: flex; align-items: center; gap: 8px; }
.checkbox-label input { width: auto; accent-color: var(--accent); }
.compact-button { min-height: 43px; }
.compact-list, .event-list { display: grid; gap: 8px; margin: 0; padding: 13px 0 0; border-top: 1px solid var(--line); list-style: none; }
.compact-list li, .event-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--ink); font-size: 0.82rem; }
.compact-list strong { color: var(--accent); font-size: 0.72rem; font-weight: 700; }
.draft-status-group { display: flex; align-items: center; gap: 10px; }
.draft-indicator { color: #ffcb7a; font-size: 0.72rem; font-weight: 800; }
.draft-discard { justify-self: start; color: #ffcb7a; }
.text-button { padding: 3px 0; background: transparent; color: var(--muted); font-size: 0.75rem; }
.text-button:hover:not(:disabled) { color: var(--danger); }
.roster-team { min-width: 0; padding: 15px; border: 1px solid rgba(166, 170, 159, 0.16); border-radius: 14px; background: rgba(12, 15, 12, 0.3); }
.team-heading { padding-bottom: 11px; border-bottom: 1px solid var(--line); }
.team-heading strong { font-size: 1rem; }
.team-heading span { color: var(--muted); font-size: 0.75rem; }
.player-list { display: grid; gap: 7px; padding-top: 10px; }
.player-row { display: grid; grid-template-columns: 27px minmax(0, 1fr) 125px 125px; align-items: center; gap: 8px; color: var(--ink); }
.player-row select { padding: 0.52rem; font-size: 0.75rem; }
.player-number { display: grid; width: 25px; height: 25px; place-items: center; border-radius: 7px; background: rgba(212, 243, 106, 0.12); color: var(--accent); font-size: 0.72rem; font-weight: 800; }
.player-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.8rem; }
.position-placeholder { color: var(--muted); font-size: 0.72rem; }
.close-panel { border-color: rgba(212, 243, 106, 0.3); }
.close-button { min-width: 190px; }
.empty-state, .form-error { padding: 20px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.form-error { border-style: solid; border-color: #a45b5b; color: var(--danger); }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
@media (max-width: 1000px) { .event-form { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .container { width: min(100% - 28px, 620px); } .match-heading, .close-actions { align-items: start; flex-direction: column; } .scoreboard { align-self: end; } .operation-grid, .sub-grid, .roster-columns, .formation-config-grid { grid-template-columns: 1fr; } .panel-wide { grid-column: auto; } .official-row, .event-form, .score-form { grid-template-columns: 1fr; } .close-button { width: 100%; } }
@media (max-width: 480px) { .operation-topbar { align-items: start; flex-direction: column; } .player-row { grid-template-columns: 27px minmax(0, 1fr); } .player-row select { grid-column: 2; } .position-placeholder { grid-column: 2; } }
@media (max-width: 375px) { .operation-actions, .draft-status-group { align-items: stretch; flex-direction: column; } .operation-actions > * { justify-content: center; text-align: center; } .panel { padding: 16px; } .scoreboard { align-self: stretch; justify-content: center; } }
</style>
