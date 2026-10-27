<script setup lang="ts">
import { FORMATION_OPTIONS, formationSlots, type FormationCode } from '~/constants/formations';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import {
  matchSelectionKey,
  readMatchSelection,
  teamRosterHref,
  writeMatchSelection,
} from '~/utils/matchNavigation';
import {
  MAXIMUM_SOURCE_LABEL_KEYS,
  RESOLUTION_LABEL_KEYS,
  classifyMatchConflict,
  closeResolutionDecision,
  enabledResolutions,
  findDraftMinuteViolations,
  matchConflictDetail,
  matchLimitsFor,
  maximumMinuteFor,
  maximumMinuteSource,
  normalizeResolution,
  resolutionChangeOutcome,
  resolutionEnabled,
  resolutionPayload,
  validateEventMinute,
  type EventMinuteValidation,
  type MaximumSource,
  type OperationLimits,
  type ResolutionType,
} from '~/utils/matchResolution';
import {
  assistCandidates,
  buildDraftEvent,
  eventSummary,
  eventTypeAnnouncement,
  isEventFieldRequired,
  newClientEventId,
  validateAssist,
  validateEventValues,
  validateSegmentMinute,
  visibleEventFields,
  type EventFormValues,
} from '~/utils/matchEvents';
import {
  WALKOVER_REASON_LABEL_KEYS,
  WALKOVER_REASONS,
  buildCloseReportBody,
  closePreflight,
  walkoverScoreFrom,
  type ClosePreflightIssue,
} from '~/utils/matchClose';
import {
  SEGMENT_PROPOSAL_HINT_LABEL_KEYS,
  applyInterruptionMinute,
  applySegmentProposal,
  classifyCloseConflict,
  closeConflictMessageKey,
  forceMinuteOnRefresh,
  segmentProposalHint,
  type SegmentRefreshCause,
} from '~/utils/matchSegments';
import {
  OPENING_BLOCKED_LABEL_KEYS,
  describeOpeningBlocked,
  effectiveRosterLimits,
  type OpeningBlockedDescription,
} from '~/utils/rosterLimits';
import { gameFormatOf } from '~/utils/rulesWizard';
import {
  createMatchDraftStore,
  type MatchDraftStorage,
} from '~/utils/matchDraft';
import { safeInternalRedirect } from '~/utils/navigation';
import { positionLabel } from '~/utils/positions';
import { createReloadCoordinator, decideReload, resyncTrigger, type ReloadTrigger } from '~/utils/realtimeReload';
import { realtimeStatusLabelKey } from '~/utils/realtimeStatusLabel';
import { buildOfficialAssignmentBody } from '~/utils/requestBodies';
import {
  DEFAULT_MATCH_LIMITS,
  SUBSTITUTION_EVENT_TYPE,
  normalizeMatchLimits,
  normalizeSubstitutionsState,
  previewCounters,
  readDraftEvents,
  substitutionAvailability,
  substitutionOptions,
  teamSubstitutionState,
  validateSubstitutionPair,
  type DraftEvent as DraftEventRecord,
  type MatchLimits,
  type SubstitutionOption,
  type SubstitutionUnavailableReason,
} from '~/utils/substitutions';

definePageMeta({ middleware: 'auth' });

type EventType = 'goal' | 'own_goal' | 'penalty_goal' | 'yellow_card' | 'red_card' | 'substitution' | 'foul';
type RedCardType = 'direct_red' | 'double_yellow_red';
type OfficialRole = 'main_referee' | 'assistant_referee_1' | 'assistant_referee_2' | 'fourth_official' | 'match_commissioner';
type LineupRole = 'starter' | 'substitute';
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
  home_team_crest_url: string | null;
  home_team_logo_url: string | null;
  away_team_id: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  away_team_crest_url: string | null;
  away_team_logo_url: string | null;
  home_score_regular: number | null;
  away_score_regular: number | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  winner_team_id: string | null;
  resolution_type: ResolutionType | null;
  rules_config?: {
    game_format?: string;
    min_players_per_team?: number | null;
    max_players_per_team?: number | null;
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
  player_out_id?: string | null;
  player_in_id?: string | null;
  assist_player_id?: string | null;
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
  substitutions?: unknown;
  limits?: (MatchLimits & OperationLimits) | null;
  /**
   * Propuesta del siguiente segmento (spec 017, RF-015). Se declara como
   * `unknown` a propósito: la forma la valida `parseSegmentProposal` en la
   * frontera, así que una respuesta inesperada no rompe el formulario. Es
   * `null` en un partido terminal o con la versión sin publicar.
   */
  next_segment?: unknown;
}

type DraftEvent = DraftEventRecord<EventType>;

const route = useRoute();
const auth = useAuthStore();
const { request } = useApi();
const { t, statusLabel, formatDateTime, errorMessage } = useI18n();
const realtime = useRealtime();
const matchId = String(route.params.id);

const operation = ref<MatchOperation | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const actionError = ref<string | null>(null);
const openingBlocked = ref<OpeningBlockedDescription | null>(null);
const busyAction = ref<string | null>(null);
const selectedSegmentId = ref('');
const lineupRoles = ref<Record<string, LineupRole | ''>>({});
const lineupPositions = ref<Record<string, string>>({});
const lineupFormations = ref<Record<string, FormationCode | ''>>({});
const draftEvents = ref<DraftEvent[]>([]);
const draftRestored = ref(false);
const draftSavedAt = ref<string | null>(null);
// Eventos del borrador guardado que ya no cumplen el contrato del acta y se
// descartaron al restaurar (spec 015, D-9). Solo se informa del número.
const draftDroppedEvents = ref(0);
let hydratingDraft = false;
let disposed = false;

const segmentForm = reactive({ segment_number: 1, minute_start: 0, minuteDirty: false });
const interruptionForm = reactive<{ reason: InterruptionReason; minute: number; minuteDirty: boolean; notes: string }>({
  reason: 'other',
  minute: 0,
  minuteDirty: false,
  notes: '',
});
const officialForm = reactive<{ organization_user_id: string; official_role: OfficialRole }>({
  organization_user_id: '',
  official_role: 'main_referee',
});
const eventForm = reactive<{
  event_type: EventType;
  team_id: string;
  beneficiary_team_id: string;
  player_id: string;
  assist_player_id: string;
  player_out_id: string;
  player_in_id: string;
  minute: number;
  added_minute: number;
  red_card_type: RedCardType;
}>({
  event_type: 'goal',
  team_id: '',
  beneficiary_team_id: '',
  player_id: '',
  assist_player_id: '',
  player_out_id: '',
  player_in_id: '',
  minute: 1,
  added_minute: 0,
  red_card_type: 'direct_red',
});
const eventIdError = ref<string | null>(null);
// RNF-007: cada error del alta vive en su campo, con `aria-invalid` y
// `aria-describedby`, y se muestra en el idioma activo. Se guarda la clave y
// sus parámetros (no el texto) para que un cambio de idioma lo reescriba.
type EventFieldKey =
  | 'event_type'
  | 'segment'
  | 'team'
  | 'player'
  | 'player_out'
  | 'player_in'
  | 'assist'
  | 'beneficiary'
  | 'red_card_type'
  | 'minute'
  | 'added_minute';
interface EventFieldIssue {
  readonly key: string;
  readonly params?: Record<string, string | number>;
}
const eventFieldIssues = ref<Partial<Record<EventFieldKey, EventFieldIssue>>>({});
const closeForm = reactive<{
  home_score_regular: number;
  away_score_regular: number;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  winner_team_id: string;
  reason: string;
}>({
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
const eventTypeValues = eventTypes.map((item) => item.value);
const substitutionReasonKeys: Record<SubstitutionUnavailableReason, string> = {
  no_state: 'match.substitutionUnavailable',
  no_lineup: 'match.substitutionNoLineup',
  disabled: 'match.substitutionDisabled',
  exhausted: 'match.substitutionExhausted',
  not_on_field: 'match.substitutionOutUnavailable',
  not_on_bench: 'match.substitutionInUnavailable',
  reentry_blocked: 'match.substitutionReentryBlocked',
  same_player: 'match.substitutionSamePlayer',
  pair_required: 'match.substitutionPairRequired',
};

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

const match = computed(() => operation.value?.match || null);
const isTerminal = computed(() => ['finished', 'cancelled', 'administrative_resolution'].includes(match.value?.status || ''));
const canManageTournaments = computed(() => auth.hasPermission('MANAGE_TOURNAMENTS'));
const canOperateMatch = computed(() => {
  if (!auth.hasPermission('CLOSE_MATCH_REPORT')) return false;
  const role = auth.access?.role_code;
  if (role === 'owner' || role === 'administrator' || role === 'operator') return true;
  return Boolean(auth.access?.organization_user_id && operation.value?.officials.some(
    (official) => official.organization_user_id === auth.access?.organization_user_id,
  ));
});
const workspaceBreadcrumbs = computed(() => [
  { label: t('shell.tournaments'), to: '/workspace' },
  ...(match.value
    ? [{ label: match.value.tournament_name, to: `/workspace/tournaments/${match.value.tournament_id}` }]
    : []),
  { label: match.value ? `${match.value.home_team_name || t('public.toDefine')} vs ${match.value.away_team_name || t('public.toDefine')}` : t('match.matchReport'), current: true },
]);
const tournamentContext = computed(() => match.value
  ? { id: match.value.tournament_id, name: match.value.tournament_name }
  : null);
const selectedSegment = computed(() => operation.value?.segments.find((segment) => segment.id === selectedSegmentId.value));
const activeSegment = computed(() => operation.value?.segments.find((segment) => segment.status === 'active'));
const selectedSegmentIsActive = computed(() => selectedSegment.value?.status === 'active');
const selectedInterruption = computed(() => operation.value?.interruptions.find((item) => item.segment_id === selectedSegment.value?.id));
// RF-015/RNF-007: origen del minuto propuesto. El número del segmento es
// siempre el del servidor; este texto dice si el minuto se dedujo de lo
// persistido o lo tiene que indicar el operador, y se anuncia al cambiar.
const segmentProposalHintText = computed(() => {
  const kind = segmentProposalHint(operation.value?.next_segment);
  return kind ? t(SEGMENT_PROPOSAL_HINT_LABEL_KEYS[kind]) : '';
});
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
const eventRosterPlayers = computed(() => operation.value?.rosters.filter((entry) => (
  entry.team_id === eventForm.team_id && entry.is_active
)) || []);
// RF-001: el formulario pinta solo los campos propios del tipo elegido.
const eventOwnFields = computed(() => visibleEventFields(eventForm.event_type));
// RNF-007: el `<select>` nativo anuncia su valor, no que el formulario cambie
// sus campos (autogol añade el beneficiario, la roja la clase, las tarjetas y
// el penalti retiran la asistencia). La región viva está siempre montada y su
// texto cambia con el tipo; si se montara con el cambio no se anunciaría.
const eventTypeNotice = computed(() => eventTypeAnnouncement(
  eventForm.event_type,
  t(eventTypes.find((event) => event.value === eventForm.event_type)?.labelKey || 'match.eventType'),
  t,
) ?? '');
// RF-007/RF-008: el asistente solo existe en un gol; los candidatos son los
// jugadores de la **alineación** del mismo equipo salvo el goleador, la misma
// fuente que el selector de jugador. El resto de la validez (plantilla del
// partido, estar en campo en ese minuto) es del servidor.
const eventAssistCandidates = computed(() => assistCandidates(
  eventPlayers.value,
  eventForm.team_id,
  eventForm.player_id,
));
const substitutionState = computed(() => normalizeSubstitutionsState(operation.value?.substitutions));
const matchLimits = computed(() => normalizeMatchLimits(operation.value?.limits) ?? DEFAULT_MATCH_LIMITS);

// RF-033/RF-034 (P3): un único valor vigente de resolución prevista, elegido
// en la operación, mostrado con el máximo que resuelve el servidor y enviado al
// crear o interrumpir segmentos y al cerrar. Vive solo en la sesión de la
// pestaña; no se mezcla con el borrador local del partido.
const operationLimits = computed<OperationLimits | null>(() => operation.value?.limits ?? null);
const {
  resolution,
  planned: plannedResolution,
  restore: restoreResolution,
  select: selectResolution,
  snapshot: snapshotResolution,
} = useMatchResolution({
  userId: () => auth.userId,
  organizationId: () => auth.organizationId,
  matchId: () => matchId,
});
const resolutionFallback = ref(false);
const resolutionChangeNotice = ref<{ key: string; params: Record<string, string | number> } | null>(null);
// RF-034/RP-1: la prevista que el cierre compara es la vigente al abrir el
// panel. La instantánea se toma una sola vez por operación para no confundir un
// cambio hecho durante el partido con uno hecho al cerrar.
const closeSnapshotTaken = ref(false);
function beginClose(): void {
  if (closeSnapshotTaken.value) return;
  closeSnapshotTaken.value = true;
  snapshotResolution();
}
const resolutionOptions = computed(() => enabledResolutions(operationLimits.value).map((value) => ({
  value,
  labelKey: RESOLUTION_LABEL_KEYS[value],
})));
const resolutionLimits = computed(() => matchLimitsFor(operationLimits.value, resolution.value));
// RF-032: el mismo tope combinado del cierre se aplica al borrador restaurado.
// Un evento guardado con otro máximo no se descarta en silencio: se avisa y el
// cierre queda bloqueado hasta que el operador lo corrija o lo retire.
const draftMinuteViolations = computed(() => findDraftMinuteViolations(
  draftEvents.value,
  resolutionLimits.value.maxMinute,
  resolutionLimits.value.addedMax,
));
const draftMinuteMessage = computed(() => {
  const first = draftMinuteViolations.value[0];
  return first ? eventMinuteMessage(first.validation) : null;
});
const resolutionMaximumSource = computed<MaximumSource>(
  () => maximumMinuteSource(operationLimits.value, resolution.value),
);

function resolutionLabel(value: ResolutionType): string {
  return t(RESOLUTION_LABEL_KEYS[value]);
}

/**
 * Mensaje del tope combinado (RF-032): nombra el minuto, el añadido y el
 * máximo que el cierre aplicará. No vacía el formulario y no añade el evento.
 */
function eventMinuteMessage(validation: EventMinuteValidation): string {
  return t('match.eventMinuteExceedsMaximum', {
    minute: validation.minute,
    added: validation.added,
    max: validation.max,
  });
}

/**
 * Cambio de la resolución prevista (RF-033, P2). Antes de aplicarlo se juzga
 * contra los segmentos persistidos y los eventos del borrador: con segmentos
 * fuera del nuevo máximo el cambio no se permite, y con solo eventos del
 * borrador se pide confirmación y se avisa sin borrar nada. El valor vigente no
 * se escribe en el servidor ni en el borrador local.
 */
function changeResolution(next: ResolutionType): void {
  resolutionFallback.value = false;
  const effective = normalizeResolution(operationLimits.value, next);
  if (effective === resolution.value) {
    resolutionChangeNotice.value = null;
    return;
  }
  const outcome = resolutionChangeOutcome(
    operation.value?.segments,
    draftEvents.value,
    maximumMinuteFor(operationLimits.value, effective),
    // Spec 016, D-13: el W.O. no valida segmentos, así que un segmento
    // persistido por encima del máximo no bloquea el cambio a `walkover`.
    { resolution: effective },
  );
  if (outcome.outcome === 'blocked') {
    // P2: no se corrige ningún segmento guardado; se pide resolver primero.
    resolutionChangeNotice.value = { key: outcome.messageKey, params: outcome.messageParams };
    actionError.value = t(outcome.messageKey, outcome.messageParams);
    return;
  }
  if (outcome.outcome === 'confirm') {
    resolutionChangeNotice.value = { key: outcome.messageKey, params: outcome.messageParams };
    if (import.meta.client && !window.confirm(t(outcome.messageKey, outcome.messageParams))) return;
  } else {
    resolutionChangeNotice.value = null;
  }
  selectResolution(effective, operationLimits.value);
}

const selectedResolution = computed<ResolutionType>({
  get: () => resolution.value,
  set: (next) => changeResolution(next),
});

const eventSubstitutionTeam = computed(() => teamSubstitutionState(substitutionState.value, eventForm.team_id));
const eventSubstitutionAvailability = computed(() => substitutionAvailability(eventSubstitutionTeam.value));
const eventSubstitutionCounters = computed(() => previewCounters(eventSubstitutionTeam.value, draftEvents.value));
const eventSubstitutionOptions = computed(() => substitutionOptions(eventSubstitutionTeam.value, draftEvents.value));
const eventOutgoingOptions = computed(() => rosterOptions(eventSubstitutionOptions.value.outgoing));
const eventIncomingOptions = computed(() => rosterOptions(eventSubstitutionOptions.value.incoming));

function rosterOptions(options: SubstitutionOption[]): Array<{ player: RosterEntry; option: SubstitutionOption }> {
  const byPlayer = new Map(options.map((option) => [option.player_id, option]));
  return eventRosterPlayers.value
    .filter((player) => byPlayer.has(player.player_id))
    .map((player) => ({ player, option: byPlayer.get(player.player_id) as SubstitutionOption }));
}

function substitutionMessage(reason: SubstitutionUnavailableReason | null): string {
  return t(substitutionReasonKeys[reason || 'no_state']);
}

function clearEventFieldIssues(): void {
  eventFieldIssues.value = {};
}

function setEventFieldIssue(
  field: EventFieldKey,
  key: string,
  params?: Record<string, string | number>,
): void {
  eventFieldIssues.value = {
    ...eventFieldIssues.value,
    [field]: params ? { key, params } : { key },
  };
}

/** Texto del error del campo en el idioma activo; vacío cuando es válido. */
function eventFieldError(field: EventFieldKey): string {
  const issue = eventFieldIssues.value[field];
  return issue ? t(issue.key, issue.params) : '';
}

function eventFieldErrorId(field: EventFieldKey): string {
  return `event-field-${field}-error`;
}

/** `aria-describedby` del control: su mensaje de error, si lo tiene. */
function eventFieldDescribedBy(field: EventFieldKey): string | undefined {
  return eventFieldError(field) ? eventFieldErrorId(field) : undefined;
}
const teamRosters = computed(() => [
  { key: 'home', team_id: match.value?.home_team_id || '', name: match.value?.home_team_name || t('setup.home'), players: homeRoster.value },
  { key: 'away', team_id: match.value?.away_team_id || '', name: match.value?.away_team_name || t('setup.away'), players: awayRoster.value },
]);
// RF-050: los límites y el recuento local solo sirven para **describir** el 409
// de apertura que ya devolvió el servidor. No bloquean el intento.
const openingRosterLimits = computed(() => effectiveRosterLimits(
  (match.value?.rules_config ?? null) as Record<string, unknown> | null,
));
const openingRosterParticipants = computed(() => teamRosters.value
  .filter((team) => Boolean(team.team_id))
  .map((team) => ({
    teamId: team.team_id,
    teamName: team.name,
    count: team.players.filter((player) => player.is_active).length,
  })));
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
// RF-043: el formato es informativo; la operación advierte cuando la planilla
// de once no coincide con la modalidad declarada, sin bloquear nada.
const matchGameFormat = computed(() => gameFormatOf(match.value?.rules_config ?? null));
const operationChecklist = computed(() => [
  { label: t('status.published'), valid: match.value?.version_status === 'published' },
  { label: t('match.activeSegment'), valid: Boolean(activeSegment.value) },
  { label: t('match.roster'), valid: hasCompleteLineup.value || Boolean(operation.value?.lineup.length) },
  { label: t('match.mainReferee'), valid: Boolean(operation.value?.officials.some((official) => official.official_role === 'main_referee')) },
]);

const defaultCloseForm = {
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

// RF-022/RF-034: el borrador local (eventos y formulario de cierre) se lee y
// se escribe solo a través del saneado de `utils/matchDraft`; la resolución
// prevista no forma parte de él. El almacenamiento se inyecta como en el resto
// de utilidades puras.
function draftStorageOrNull(): MatchDraftStorage | null {
  if (!import.meta.client) return null;
  try {
    return window.localStorage;
  } catch {
    // Storage can be unavailable in private browsing.
    return null;
  }
}

const draftStore = computed(() => createMatchDraftStore({
  userId: auth.userId,
  organizationId: auth.organizationId,
  matchId,
}, draftStorageOrNull()));

function closeFormSnapshot() {
  return { ...closeForm };
}

function removePersistedDraft() {
  if (!import.meta.client) return;
  draftStore.value.clear();
}

function loadPersistedDraft() {
  if (!import.meta.client || !operation.value) return;
  const { draft, discard } = draftStore.value.read();
  if (discard) {
    removePersistedDraft();
    return;
  }
  if (!draft) return;
  if (isTerminal.value) {
    removePersistedDraft();
    return;
  }

  hydratingDraft = true;
  try {
    // Spec 015, T10: un evento que ya no se puede reenviar (identificador que no
    // es UUID, asistente en un tipo ajeno, `metadata` cerrada…) se descarta y se
    // cuenta; el resto del borrador se restaura tal cual, en su orden.
    const restored = readDraftEvents(draft.events, eventTypeValues, matchLimits.value);
    draftEvents.value = restored.events;
    draftDroppedEvents.value = restored.dropped;
    // Solo los campos conocidos y válidos del formulario de cierre; un borrador
    // antiguo con la resolución prevista ya la trae descartada de `read()`.
    Object.assign(closeForm, draft.result);
    draftRestored.value = hasUnsavedDraft.value;
    draftSavedAt.value = draft.saved_at;
  } catch {
    // Un guardado que no se puede aplicar se descarta como antes de la spec 012.
    draftDroppedEvents.value = 0;
    removePersistedDraft();
  } finally {
    hydratingDraft = false;
  }
  // Lo descartado no vuelve: el guardado se reescribe ya limpio y, si no queda
  // nada que reenviar, se borra (D-9).
  if (draftDroppedEvents.value > 0) persistDraft();
}

function persistDraft() {
  if (!import.meta.client || hydratingDraft || !operation.value) return;
  if (isTerminal.value) {
    removePersistedDraft();
    return;
  }
  if (!hasUnsavedDraft.value) {
    removePersistedDraft();
    draftSavedAt.value = null;
    return;
  }
  const savedAt = new Date().toISOString();
  // `save` re-sanea el contenido: ninguna ruta escribe la resolución prevista.
  if (draftStore.value.save({ events: draftEvents.value, result: closeFormSnapshot(), saved_at: savedAt })) {
    draftSavedAt.value = savedAt;
  }
}

function discardDraft() {
  if (!import.meta.client || !window.confirm(t('match.discardDraft'))) return;
  draftEvents.value = [];
  Object.assign(closeForm, defaultCloseForm);
  eventForm.player_out_id = '';
  eventForm.player_in_id = '';
  clearEventFieldIssues();
  draftRestored.value = false;
  draftDroppedEvents.value = 0;
  persistDraft();
}

// Spec 016 (RF-012, RF-007): el walkover pide ganador y motivo y **no** pide
// ninguno de los seis marcadores. La pareja efectiva la publica el servidor en
// `limits.walkover_score`; la pantalla la muestra en solo lectura y no la envía.
const walkoverScore = computed(() => walkoverScoreFrom(operationLimits.value));
const walkoverReasonOptions = WALKOVER_REASONS.map((reason) => ({
  value: reason,
  labelKey: WALKOVER_REASON_LABEL_KEYS[reason],
}));
// RNF-007: el ganador y el motivo son campos más del cierre, cada uno con su
// error asociado por `aria-invalid`/`aria-describedby` (el patrón que ya usa el
// alta de eventos).
const WALKOVER_WINNER_ERROR_ID = 'close-walkover-winner-error';
const WALKOVER_REASON_ERROR_ID = 'close-walkover-reason-error';
const closeFieldIssue = ref<ClosePreflightIssue | null>(null);
const walkoverWinnerError = computed(() => (
  resolution.value === 'walkover' && closeFieldIssue.value?.key === 'match.walkoverWinnerRequired'
    ? t(closeFieldIssue.value.key, closeFieldIssue.value.params)
    : ''
));
const walkoverWinnerDescribedBy = computed(() => (
  walkoverWinnerError.value ? WALKOVER_WINNER_ERROR_ID : undefined
));
const walkoverReasonError = computed(() => (
  resolution.value === 'walkover' && closeFieldIssue.value?.key === 'match.walkoverReasonRequired'
    ? t(closeFieldIssue.value.key, closeFieldIssue.value.params)
    : ''
));
const walkoverReasonDescribedBy = computed(() => (
  walkoverReasonError.value ? WALKOVER_REASON_ERROR_ID : undefined
));

/**
 * Primer problema del cierre (RF-012). La decisión vive en la utilidad pura: el
 * walkover no exige segmento activo ni planilla y exige motivo de catálogo; el
 * resto de resoluciones conserva sus exigencias. El servidor sigue siendo la
 * autoridad y esto solo evita un 422 evitable.
 */
function closeValidationIssue(): ClosePreflightIssue | null {
  const minuteViolation = draftMinuteViolations.value[0];
  return closePreflight({
    resolution: resolution.value,
    limits: operationLimits.value,
    homeTeamId: match.value?.home_team_id,
    awayTeamId: match.value?.away_team_id,
    segmentActive: selectedSegmentIsActive.value,
    lineupComplete: hasCompleteLineup.value,
    scores: { ...closeForm },
    winnerTeamId: closeForm.winner_team_id,
    reason: closeForm.reason,
    draftEvents: draftEvents.value,
    minuteIssue: minuteViolation
      ? {
          key: 'match.eventMinuteExceedsMaximum',
          params: {
            minute: minuteViolation.validation.minute,
            added: minuteViolation.validation.added,
            max: minuteViolation.validation.max,
          },
        }
      : null,
  });
}

function closeValidationError(): string | null {
  const issue = closeValidationIssue();
  // RNF-007: el problema se guarda además de mostrarse, para que el motivo del
  // walkover lo anuncie su propio campo y no solo la región del error.
  closeFieldIssue.value = issue;
  if (!issue) return null;
  return t(issue.key, issue.params);
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

/**
 * RF-015/D-5: el formulario de segmento sale de la propuesta del servidor
 * (`next_segment`), no de una suma del cliente. El número es siempre el del
 * servidor; el minuto solo se escribe si la propuesta es derivada y el refresco
 * lo permite (`forceMinuteOnRefresh`): al montar y tras crear o interrumpir,
 * pero no en un refresco manual ni en el que provoca el socket.
 */
function syncSegmentForm(proposal: unknown, cause: SegmentRefreshCause): void {
  const resolved = applySegmentProposal({
    segment_number: segmentForm.segment_number,
    minute_start: segmentForm.minute_start,
    minuteDirty: segmentForm.minuteDirty,
  }, proposal, { forceMinute: forceMinuteOnRefresh(cause) });
  segmentForm.segment_number = resolved.segment_number;
  segmentForm.minute_start = resolved.minute_start;
  segmentForm.minuteDirty = resolved.minuteDirty;
}

/** El operador ha escrito el minuto: un refresco normal ya no lo pisa. */
function markSegmentMinuteDirty(): void {
  segmentForm.minuteDirty = true;
}

/**
 * El minuto de la interrupción sigue la misma regla que el del segmento (D-5):
 * se prefija con el `minute_start` del segmento activo al montar y tras crear o
 * interrumpir, y un refresco normal —incluido el que provoca el socket— no pisa
 * lo que el operador está escribiendo.
 */
function syncInterruptionForm(proposal: number | null, cause: SegmentRefreshCause): void {
  const resolved = applyInterruptionMinute(
    { minute: interruptionForm.minute, dirty: interruptionForm.minuteDirty },
    proposal,
    { forceMinute: forceMinuteOnRefresh(cause) },
  );
  interruptionForm.minute = resolved.minute;
  interruptionForm.minuteDirty = resolved.dirty;
}

/** El operador ha escrito el minuto de la interrupción: un refresco no lo pisa. */
function markInterruptionMinuteDirty(): void {
  interruptionForm.minuteDirty = true;
}

function applyOperation(value: MatchOperation, cause: SegmentRefreshCause = 'refresh') {
  operation.value = value;
  // Si el partido ya tiene segmentos (por ejemplo, abierto en otra pestaña) el
  // aviso de apertura bloqueada dejó de ser cierto.
  if (value.segments.length) openingBlocked.value = null;
  const currentSegment = value.segments.find((segment) => segment.id === selectedSegmentId.value);
  const nextActiveSegment = value.segments.find((segment) => segment.status === 'active');
  if (!currentSegment || (currentSegment.status !== 'active' && nextActiveSegment)) {
    selectedSegmentId.value = nextActiveSegment?.id || value.segments.at(-1)?.id || '';
  }
  syncSegmentForm(value.next_segment, cause);
  syncInterruptionForm(nextActiveSegment?.minute_start ?? null, cause);
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
  for (const roster of operation.value?.rosters || []) {
    if (roster.team_id === match.value?.home_team_id || roster.team_id === match.value?.away_team_id) {
      roles[roster.roster_id] ||= '';
    }
  }
  lineupRoles.value = roles;
}

function setFormation(teamId: string, event: Event) {
  const formation = (event.target as HTMLSelectElement).value as FormationCode | '';
  lineupFormations.value[teamId] = formation;
  const allowed = new Set(formationSlots(formation));
  for (const roster of operation.value?.rosters.filter((entry) => entry.team_id === teamId) || []) {
    const current = lineupPositions.value[roster.roster_id];
    if (current === undefined || !allowed.has(current)) delete lineupPositions.value[roster.roster_id];
  }
}

function availablePositions(teamId: string): string[] {
  return formationSlots(lineupFormations.value[teamId] || '');
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

async function refreshOperation(cause: SegmentRefreshCause = 'refresh') {
  applyOperation(await fetchOperation(), cause);
}

const operationReload = createReloadCoordinator(async () => {
  if (disposed) return;
  try {
    await refreshOperation();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) actionError.value = failureMessage(cause, t('match.noLoad'));
  }
});

function requestOperationReload(trigger: ReloadTrigger, payload?: unknown) {
  if (!payloadTargetsMatch(payload) || busyAction.value || isTerminal.value) return;
  const decision = decideReload({
    consumer: 'workspace',
    trigger,
    initialized: realtime.initialization.initialized,
    initializedWithJoin: realtime.initialization.initializedWithJoin,
  });
  if (decision.action === 'reload') {
    void operationReload.request({ resetPagination: decision.resetPagination });
  }
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

async function runAction(
  action: string,
  callback: () => Promise<void>,
  onError?: (cause: unknown) => boolean,
) {
  busyAction.value = action;
  actionError.value = null;
  clearEventFieldIssues();
  try {
    await callback();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    if (onError?.(cause)) return;
    openingBlocked.value = null;
    // RF-050/RNF-003: el 409 de resolución se distingue por su `code` aditivo.
    // Un 409 anterior sin `code` conserva el mensaje de `detail`.
    if (classifyMatchConflict(cause) === 'resolution_not_enabled') {
      actionError.value = t('match.resolutionNotEnabled');
      return;
    }
    actionError.value = failureMessage(cause, t('match.noOperation'));
  } finally {
    busyAction.value = null;
  }
}

/**
 * Apertura del partido = primer segmento (RF-050). El servidor es la autoridad
 * del tamaño de plantilla: la petición se envía siempre. Si responde **409**
 * `ROSTER_SIZE_OUT_OF_RANGE`, el segmento no se crea en la interfaz, el estado
 * no se recarga —el partido sigue sin abrir— y se muestra el aviso con los
 * equipos implicados, el rango, la cantidad y el enlace a su plantilla para
 * corregir y reintentar.
 */
function showOpeningBlocked(cause: unknown): void {
  actionError.value = null;
  openingBlocked.value = describeOpeningBlocked({
    detail: matchConflictDetail(cause),
    limits: openingRosterLimits.value,
    participants: openingRosterParticipants.value,
  }, t);
}

async function createSegment() {
  const opening = (operation.value?.segments.length ?? 0) === 0;
  await runAction('segment', async () => {
    await request(`/matches/${matchId}/segments`, {
      method: 'POST',
      body: {
        segment_number: segmentForm.segment_number,
        minute_start: segmentForm.minute_start,
        ...resolutionPayload(operationLimits.value, resolution.value),
      },
    });
    openingBlocked.value = null;
    segmentForm.minuteDirty = false;
    await refreshOperation('segment-changed');
  }, (cause) => {
    if (opening && classifyMatchConflict(cause) === 'roster_size_out_of_range') {
      showOpeningBlocked(cause);
      return true;
    }
    return false;
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
        ...resolutionPayload(operationLimits.value, resolution.value),
      },
    });
    segmentForm.minuteDirty = false;
    interruptionForm.minuteDirty = false;
    interruptionForm.notes = '';
    await refreshOperation('segment-changed');
  });
}

async function assignOfficial() {
  if (!officialForm.organization_user_id) return;
  await runAction('official', async () => {
    await request(`/matches/${matchId}/officials`, { method: 'POST', body: buildOfficialAssignmentBody(officialForm) });
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

// RF-021: el alta de jugadores vive solo en la administración de plantillas.
// RF-022: desde aquí se enlaza a la plantilla del equipo con contexto de
// retorno; el partido (dirección), el segmento seleccionado y el borrador local
// se conservan al volver.
const rostersHref = computed(() => (match.value
  ? `/workspace/tournaments/${match.value.tournament_id}/rosters`
  : ''));

function teamRosterLink(teamId: string): string {
  return teamRosterHref({
    tournamentId: match.value?.tournament_id || '',
    teamId,
    matchId,
  });
}

const selectedSegmentStorageKey = computed(() => matchSelectionKey({
  userId: auth.userId || 'anonymous',
  organizationId: auth.organizationId || 'anonymous',
  matchId,
}));

function persistSelectedSegment(segmentId: string) {
  if (!import.meta.client || !segmentId) return;
  try {
    sessionStorage.setItem(selectedSegmentStorageKey.value, writeMatchSelection(segmentId));
  } catch {
    // Storage can be unavailable in private browsing; the in-memory selection remains usable.
  }
}

function restoreSelectedSegment() {
  if (!import.meta.client || !operation.value) return;
  try {
    const stored = readMatchSelection(
      sessionStorage.getItem(selectedSegmentStorageKey.value),
      operation.value.segments.map((segment) => segment.id),
    );
    if (stored) selectedSegmentId.value = stored;
  } catch {
    // Storage can be unavailable in private browsing; the default selection remains.
  }
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

watch(selectedSegmentId, (segmentId) => {
  if (operation.value) syncTacticalEditor();
  persistSelectedSegment(segmentId);
});

function pushDraftEvent(formValues: EventFormValues): boolean {
  // RF-015: el identificador sale de `crypto.randomUUID()`. Sin él no se
  // inventa un texto: el evento no entra y se avisa (el texto fino es T11).
  const clientEventId = newClientEventId(globalThis.crypto);
  if (!clientEventId) {
    eventIdError.value = t('match.eventIdUnavailable');
    return false;
  }
  // RF-001/RF-002: el payload se construye desde el catálogo del tipo, así que
  // nunca lleva un campo prohibido con valor ni una clave desconocida.
  const event = buildDraftEvent(formValues, selectedSegmentId.value, clientEventId);
  if (!event) return false;
  draftEvents.value.push(event);
  return true;
}

/** Campo y texto de cada problema estructural del catálogo (RF-006). */
const eventValidationIssues: Record<string, { field: EventFieldKey; key: string }> = {
  unknown_event_type: { field: 'event_type', key: 'match.eventUnknownType' },
  missing_player: { field: 'player', key: 'match.eventMissingPlayer' },
  missing_beneficiary: { field: 'beneficiary', key: 'match.ownGoalBeneficiary' },
  beneficiary_same_team: { field: 'beneficiary', key: 'match.eventBeneficiarySameTeam' },
  missing_player_out: { field: 'player_out', key: 'match.substitutionPairRequired' },
  missing_player_in: { field: 'player_in', key: 'match.substitutionPairRequired' },
  same_substitution_player: { field: 'player_in', key: 'match.substitutionSamePlayer' },
  assist_same_as_scorer: { field: 'assist', key: 'match.eventAssistSameAsScorer' },
  assist_not_in_goal: { field: 'assist', key: 'match.eventAssistNotAllowed' },
};

/** Texto del rechazo por el intervalo del segmento (RF-006, viñeta 2). */
const eventSegmentMinuteKeys = {
  before_segment: { key: 'match.eventMinuteBeforeSegment' },
  after_segment: { key: 'match.eventMinuteAfterSegment' },
} as const;

/** Texto del asistente que no es del equipo del goleador (RF-006). */
const eventAssistIssueKeys = {
  not_in_team: { key: 'match.eventAssistOtherTeam' },
} as const;

/** Textos de los campos que no dependen del tipo (RF-006). */
const eventFormIssueKeys = {
  segment: { key: 'match.needSegmentEvent' },
  team: { key: 'match.eventMissingTeam' },
} as const;

function addEvent() {
  eventIdError.value = null;
  clearEventFieldIssues();

  if (!selectedSegmentId.value || !selectedSegmentIsActive.value) {
    setEventFieldIssue('segment', eventFormIssueKeys.segment.key);
    return;
  }
  if (!eventForm.team_id) {
    setEventFieldIssue('team', eventFormIssueKeys.team.key);
    return;
  }

  const values: EventFormValues = { ...eventForm };
  // RF-006: solo el subconjunto declarado. La plantilla del partido, las
  // sanciones, el estado en campo y los límites de sustitución son autoridad
  // del servidor. Cada problema se queda junto a su campo (RNF-007).
  let blocked = false;
  for (const issue of validateEventValues(values).issues) {
    const target = eventValidationIssues[issue.code];
    if (!target) continue;
    setEventFieldIssue(target.field, target.key);
    blocked = true;
  }

  const limits = resolutionLimits.value;
  // RF-032: la misma regla que el cierre, sobre `minute + added_minute`; el
  // evento inválido no se añade y lo escrito se conserva para corregirlo.
  const minuteCheck = validateEventMinute(
    eventForm.minute,
    eventForm.added_minute,
    limits.maxMinute,
    limits.addedMax,
  );
  if (!minuteCheck.ok) {
    if (minuteCheck.reason === 'added') {
      // El añadido por sí solo no es válido o supera su tope: el error se
      // queda junto a su campo, que es el único que hay que corregir. El
      // exceso combinado sigue junto al minuto, que es el campo principal.
      setEventFieldIssue('added_minute', 'match.addedMinuteOutOfRange', { max: limits.addedMax });
    } else {
      // Los valores que se nombran son los escritos, no una normalización: el
      // operador ve exactamente qué minuto y qué añadido corregir.
      setEventFieldIssue('minute', 'match.eventMinuteExceedsMaximum', {
        minute: eventForm.minute,
        added: eventForm.added_minute,
        max: limits.maxMinute,
      });
    }
    blocked = true;
  } else {
    // RF-006: el minuto debe caer dentro del segmento seleccionado cuando ya
    // tiene fin; el servidor lo vuelve a comprobar al cerrar.
    const segmentCheck = validateSegmentMinute(eventForm.minute, selectedSegment.value);
    if (!segmentCheck.ok) {
      const before = segmentCheck.issue === 'before_segment';
      setEventFieldIssue(
        'minute',
        eventSegmentMinuteKeys[before ? 'before_segment' : 'after_segment'].key,
        before ? { start: segmentCheck.start ?? 0 } : { end: segmentCheck.end ?? 0 },
      );
      blocked = true;
    }
  }

  if (eventForm.event_type === 'goal' && eventForm.assist_player_id) {
    const assist = validateAssist(
      eventForm.assist_player_id,
      eventForm.player_id,
      eventPlayers.value,
    );
    if (!assist.ok && assist.issue === 'not_in_team') {
      setEventFieldIssue('assist', eventAssistIssueKeys.not_in_team.key);
      blocked = true;
    }
  }

  if (blocked) return;

  if (eventForm.event_type === SUBSTITUTION_EVENT_TYPE) {
    const pair = validateSubstitutionPair(
      eventSubstitutionTeam.value,
      draftEvents.value,
      eventForm.player_out_id,
      eventForm.player_in_id,
    );
    if (!pair.ok) {
      const field: EventFieldKey = pair.reason === 'not_on_field' ? 'player_out' : 'player_in';
      setEventFieldIssue(field, substitutionReasonKeys[pair.reason || 'no_state']);
      return;
    }
    if (!pushDraftEvent({
      ...values,
      player_out_id: pair.player_out_id,
      player_in_id: pair.player_in_id,
    })) {
      if (!eventIdError.value) setEventFieldIssue('team', eventFormIssueKeys.team.key);
      return;
    }
    eventForm.player_out_id = '';
    eventForm.player_in_id = '';
    actionError.value = null;
    return;
  }

  if (!pushDraftEvent(values)) {
    // Un evento no construible no entra al borrador; el aviso ya está puesto.
    if (!eventIdError.value) setEventFieldIssue('team', eventFormIssueKeys.team.key);
    return;
  }
  eventForm.player_id = '';
  eventForm.assist_player_id = '';
  eventForm.beneficiary_team_id = '';
  eventForm.red_card_type = 'direct_red';
  actionError.value = null;
}

function removeEvent(clientEventId: string) {
  draftEvents.value = draftEvents.value.filter((event) => event.client_event_id !== clientEventId);
}

watch([draftEvents, closeForm], persistDraft, { deep: true });

// RNF-007: al corregir el formulario, el error asociado a su campo deja de
// estar vigente; el aviso general se limpia al reintentar el cierre.
watch(closeForm, () => {
  if (closeFieldIssue.value) closeFieldIssue.value = null;
}, { deep: true });

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedDraft.value || isTerminal.value) return;
  event.preventDefault();
  event.returnValue = '';
}

onBeforeRouteLeave((to) => {
  if (!import.meta.client || !hasUnsavedDraft.value || isTerminal.value) return true;
  // RF-022: el enlace a la plantilla conserva el segmento y el borrador local y
  // los restaura al volver, así que avisar de una pérdida que no ocurre sería
  // falso. Cualquier otro destino mantiene la confirmación.
  if (to.path === rostersHref.value) return true;
  return window.confirm(t('match.unsavedLeave'));
});

async function closeMatch() {
  const validationError = closeValidationError();
  if (validationError) {
    actionError.value = validationError;
    return;
  }
  // RF-034/RP-1: el cierre usa la resolución prevista. Si se elige otra
  // compatible, hay aviso y confirmación explícita; sin ella no se cierra. Con
  // segmentos persistidos fuera del máximo no hay confirmación posible (P2).
  const closeInput = {
    planned: plannedResolution.value,
    chosen: resolution.value,
    limits: operationLimits.value,
    segments: operation.value?.segments,
    draftEvents: draftEvents.value,
    confirmed: false,
  };
  const decision = closeResolutionDecision(closeInput);
  if (decision.outcome === 'blocked') {
    actionError.value = t(decision.messageKey, decision.messageParams);
    return;
  }
  if (decision.needsConfirmation) {
    if (!import.meta.client) return;
    const params = {
      ...decision.messageParams,
      resolution: resolutionLabel(resolution.value),
      planned: resolutionLabel(plannedResolution.value),
    };
    if (!window.confirm(t(decision.messageKey, params))) return;
    if (!closeResolutionDecision({ ...closeInput, confirmed: true }).send) return;
  } else if (import.meta.client && !window.confirm(t('match.confirmClosePrompt'))) {
    return;
  }
  await runAction('close', async () => {
    await request(`/matches/${matchId}/close`, {
      method: 'POST',
      // RF-005/RF-012: el cuerpo lo construye la utilidad pura. En `walkover` no
      // se envía ninguna de las seis claves de marcador: lo deriva el servidor.
      body: buildCloseReportBody({
        resolution: resolution.value,
        limits: operationLimits.value,
        scores: { ...closeForm },
        winnerTeamId: closeForm.winner_team_id,
        reason: closeForm.reason,
        events: draftEvents.value,
      }),
    });
    draftEvents.value = [];
    draftRestored.value = false;
    draftDroppedEvents.value = 0;
    await refreshOperation();
    removePersistedDraft();
  }, (cause) => {
    // RF-006/RF-010: el 409 del cierre se explica por su `code` aditivo con el
    // clasificador de `matchSegments`. Una causa sin código conocido conserva
    // el `detail` del servidor, que es más concreto que un texto genérico.
    const kind = classifyCloseConflict(cause);
    const key = kind === 'other' ? null : closeConflictMessageKey(kind);
    if (!key) return false;
    actionError.value = t(key);
    return true;
  });
}

function playerName(roster: RosterEntry): string {
  return `${roster.first_name} ${roster.last_name}`;
}

function rosterPlayerName(playerId: string | null): string {
  const roster = operation.value?.rosters.find((entry) => entry.player_id === playerId);
  return roster ? playerName(roster) : '';
}

/** Textos del resumen, siempre por i18n y con paridad es/en (RF-005). */
function eventSummaryLabels() {
  return {
    assist: t('match.assistShort'),
    ownGoal: t('match.ownGoalBeneficiaryShort'),
    redCardDirect: t('match.redCardDirectShort'),
    redCardDouble: t('match.redCardDoubleShort'),
  };
}

function draftEventSummary(event: DraftEvent): string {
  // RF-005: borrador y acta comparten el resumen; el asistente del gol y el
  // equipo beneficiado del autogol se resuelven desde la operación. Las
  // palabras son formas cortas del catálogo, no etiquetas de campo.
  return eventSummary(event, rosterPlayerName, eventSummaryLabels(), teamName);
}

function persistedEventSummary(event: MatchEvent): string {
  // RF-011: la operación no devuelve el nombre del asistente; se resuelve de la
  // plantilla. El jugador principal conserva el nombre que trae el evento.
  const ownName = `${event.first_name} ${event.last_name}`.trim();
  return eventSummary(
    event,
    (playerId) => (playerId === event.player_id && ownName ? ownName : rosterPlayerName(playerId)),
    eventSummaryLabels(),
    teamName,
  );
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
  return formatDateTime(value);
}

watch(() => eventForm.team_id, () => {
  if (!eventPlayers.value.some((player) => player.player_id === eventForm.player_id)) eventForm.player_id = '';
  if (eventForm.beneficiary_team_id === eventForm.team_id) eventForm.beneficiary_team_id = '';
  // RF-007: un asistente del equipo anterior deja de ser candidato.
  if (!eventAssistCandidates.value.some((player) => player.player_id === eventForm.assist_player_id)) {
    eventForm.assist_player_id = '';
  }
  eventForm.player_out_id = '';
  eventForm.player_in_id = '';
});

watch(() => eventForm.event_type, (eventType) => {
  clearEventFieldIssues();
  eventIdError.value = null;
  // RF-001: al cambiar de tipo se descarta el valor de un campo que el nuevo
  // tipo no admite; ningún valor residual viaja al evento.
  if (eventType !== 'goal') eventForm.assist_player_id = '';
  if (eventType !== 'own_goal') eventForm.beneficiary_team_id = '';
  if (eventType !== 'red_card') eventForm.red_card_type = 'direct_red';
  if (eventType === SUBSTITUTION_EVENT_TYPE) {
    eventForm.player_id = '';
  } else {
    eventForm.player_out_id = '';
    eventForm.player_in_id = '';
  }
});

watch(() => eventForm.player_id, (playerId) => {
  // RF-008: el goleador no puede ser su propio asistente.
  if (eventForm.event_type === 'goal' && eventForm.assist_player_id === playerId) {
    eventForm.assist_player_id = '';
  }
});

// RNF-007: al corregir un valor, su error deja de estar vigente. El aviso de
// identificador no depende de un campo y vive aparte.
watch(eventForm, () => {
  if (Object.keys(eventFieldIssues.value).length) clearEventFieldIssues();
});

watch([eventOutgoingOptions, eventIncomingOptions], () => {
  if (!eventOutgoingOptions.value.some((row) => row.player.player_id === eventForm.player_out_id && !row.option.disabled)) {
    eventForm.player_out_id = '';
  }
  if (!eventIncomingOptions.value.some((row) => row.player.player_id === eventForm.player_in_id && !row.option.disabled)) {
    eventForm.player_in_id = '';
  }
});

watch(resolution, () => {
  // D-8: `reason` es el mismo campo con dos dominios (catálogo del walkover y
  // texto libre de la administrativa). Al cambiar de resolución se vacía para
  // no arrastrar un texto libre al catálogo cerrado ni al revés.
  closeForm.reason = '';
  closeFieldIssue.value = null;
});

// RF-034: si la configuración efectiva deja de habilitar la resolución elegida,
// se cae a tiempo reglamentario sin romper y se avisa en pantalla.
watch(operationLimits, (limits) => {
  if (!operation.value || resolutionEnabled(limits, resolution.value)) return;
  selectResolution('regular', limits);
  resolutionFallback.value = true;
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
  // Primer prerrelleno del formulario de segmento: es el único refresco que
  // escribe el minuto propuesto además de crear o interrumpir.
  applyOperation(initialOperation.value, 'mount');
}
loading.value = false;

if (operation.value) {
  restoreSelectedSegment();
  loadPersistedDraft();
}

const realtimeStatusLabel = computed(() => {
  const key = realtimeStatusLabelKey(realtime.status.value, 'match');
  return key ? t(key) : '';
});

onMounted(() => {
  // RF-034/P3: la resolución prevista se restaura después de montar para no
  // desajustar la hidratación; solo existe en la sesión de esta pestaña.
  const restored = restoreResolution(operation.value?.limits ?? null);
  resolutionFallback.value = restored.fellBack;
  window.addEventListener('beforeunload', handleBeforeUnload);
  realtime.connect({
    onEvent: (event, payload) => {
      if (['MATCH_CLOSED', 'MATCH_UPDATED'].includes(event)) requestOperationReload('event', payload);
    },
    onReconnect: () => requestOperationReload('reconnect'),
    onResync: (payload) => requestOperationReload(resyncTrigger(payload.reason)),
  });
});

onBeforeUnmount(() => {
  disposed = true;
  window.removeEventListener('beforeunload', handleBeforeUnload);
  realtime.disconnect();
});
</script>

<template>
  <WorkspaceShell
    :breadcrumbs="workspaceBreadcrumbs"
    :tournament="tournamentContext"
  >
   <main id="main-content" class="operation-shell">
    <section class="container operation-hero">
      <div class="hero-line">
         <p class="eyebrow">{{ t('match.matchReport') }}</p>
         <span v-if="realtimeStatusLabel" class="realtime-status" :class="`realtime-${realtime.status.value}`" role="status">{{ realtimeStatusLabel }}</span>
         <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="realtime.retry()">{{ t('common.retry') }}</button>
         <span class="status-pill" :class="{ finished: isTerminal, interrupted: match?.status === 'interrupted' }">{{ statusLabel(match?.status) }}</span>
      </div>
      <div v-if="match" class="match-heading">
        <div>
          <p class="context-line">{{ match.tournament_name }} · {{ match.stage_name }} · {{ t('public.matchday', { value: match.matchday || '-' }) }}</p>
          <h1 class="match-title">
            <TeamCrest
              :team="{ name: match.home_team_name || t('public.toDefine'), short_code: match.home_team_short_code }"
              :crest-url="match.home_team_crest_url"
              :logo-url="match.home_team_logo_url"
              surface="workspace"
            />
            <span>{{ match.home_team_name || t('public.toDefine') }}</span>
            <span class="match-versus">vs</span>
            <TeamCrest
              :team="{ name: match.away_team_name || t('public.toDefine'), short_code: match.away_team_short_code }"
              :crest-url="match.away_team_crest_url"
              :logo-url="match.away_team_logo_url"
              surface="workspace"
            />
            <span>{{ match.away_team_name || t('public.toDefine') }}</span>
          </h1>
          <p class="workspace-copy">{{ formatDate(match.match_date) }}<span v-if="match.group_name"> · {{ match.group_name }}</span></p>
        </div>
        <div class="scoreboard" :aria-label="t('match.result')">
          <strong>{{ match.home_score ?? '—' }}</strong>
          <span>:</span>
          <strong>{{ match.away_score ?? '—' }}</strong>
        </div>
      </div>
      <FormatWarning :format="matchGameFormat" message-key="format.notice.operation" />
    </section>

    <section id="operacion" class="container operation-content">
      <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('match.loadingOperation') }}</div>
       <div v-else-if="error" class="form-error" role="alert"><span>{{ error }}</span><button class="button-secondary" type="button" @click="retryOperation">{{ t('common.retry') }}</button></div>
      <template v-else-if="operation && match">
        <div class="checklist" :aria-label="t('match.matchReport')">
          <div v-for="item in operationChecklist" :key="item.label" class="check-item" :class="{ valid: item.valid }">
            <span aria-hidden="true">{{ item.valid ? '✓' : '!' }}</span><strong>{{ item.label }}</strong><small>{{ item.valid ? t('common.ready') : t('common.incomplete') }}</small>
          </div>
        </div>

        <p v-if="isTerminal" class="segment-warning report-locked" role="status">{{ t('match.reportLocked') }}</p>

        <div v-if="actionError" class="form-error" role="alert">{{ actionError }}</div>

        <section v-if="openingBlocked" class="stage-partial opening-blocked" role="alert" aria-live="assertive">
          <strong>{{ t(OPENING_BLOCKED_LABEL_KEYS.title) }}</strong>
          <p>{{ t(OPENING_BLOCKED_LABEL_KEYS.reason) }}</p>
          <ul>
            <li v-for="team in openingBlocked.teams" :key="`opening-blocked-${team.teamId}`">{{ team.message }}</li>
          </ul>
          <p class="field-hint">{{ t(OPENING_BLOCKED_LABEL_KEYS.retry) }}</p>
          <ul class="roster-links">
            <li v-for="team in openingBlocked.teams" :key="`opening-roster-${team.teamId}`">
              <NuxtLink :to="teamRosterLink(team.teamId)">{{ t(OPENING_BLOCKED_LABEL_KEYS.openRoster, { team: team.teamName }) }}</NuxtLink>
            </li>
          </ul>
          <p class="muted-note">{{ t(OPENING_BLOCKED_LABEL_KEYS.serverDetail, { detail: openingBlocked.detail }) }}</p>
          <button v-if="canOperateMatch" class="button-secondary" type="button" :disabled="Boolean(busyAction) || isTerminal" @click="createSegment">{{ t(OPENING_BLOCKED_LABEL_KEYS.retryAction) }}</button>
        </section>

        <section class="panel panel-wide resolution-panel" aria-labelledby="planned-resolution-heading">
          <div class="panel-heading">
            <div><p class="eyebrow">{{ t('match.plannedResolution') }}</p><h2 id="planned-resolution-heading">{{ t('match.resolution') }}</h2></div>
            <span class="muted-note">{{ t('match.plannedResolutionHint') }}</span>
          </div>
          <div class="resolution-summary">
            <label>{{ t('match.plannedResolution') }}
              <select v-model="selectedResolution" :disabled="!canOperateMatch || isTerminal">
                <option v-for="option in resolutionOptions" :key="option.value" :value="option.value">{{ t(option.labelKey) }}</option>
              </select>
            </label>
            <p class="resolution-limits" role="status">
              <strong>{{ t('match.resolutionMaximum', { max: resolutionLimits.maxMinute }) }}</strong>
              <span>{{ t('match.resolutionAddedMaximum', { max: resolutionLimits.addedMax }) }}</span>
              <span>{{ t(MAXIMUM_SOURCE_LABEL_KEYS[resolutionMaximumSource]) }}</span>
            </p>
            <p v-if="resolutionFallback" class="segment-warning" role="status">{{ t('match.resolutionFallenBack') }}</p>
            <p v-if="resolutionChangeNotice" class="segment-warning" role="status">{{ t(resolutionChangeNotice.key, resolutionChangeNotice.params) }}</p>
          </div>
        </section>

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
                  <label>{{ t('match.startMinute') }}<input v-model.number="segmentForm.minute_start" type="number" min="0" :max="resolutionLimits.maxMinute" required :aria-describedby="segmentProposalHintText ? 'segment-proposal-hint' : undefined" @input="markSegmentMinuteDirty" /></label>
                </div>
                <p v-if="segmentProposalHintText" id="segment-proposal-hint" class="field-hint" role="status">{{ segmentProposalHintText }}</p>
                  <label>{{ t('match.activeSegment') }}
                   <select v-model="selectedSegmentId" required :aria-invalid="Boolean(eventFieldError('segment'))" :aria-describedby="eventFieldDescribedBy('segment')">
                     <option value="" disabled>{{ t('match.selectSegment') }}</option>
                     <option v-for="segment in operation.segments" :key="segment.id" :value="segment.id">{{ t('match.segmentOption', { number: segment.segment_number, minute: segment.minute_start }) }} · {{ statusLabel(segment.status) }}</option>
                   </select>
                   <small v-if="eventFieldError('segment')" :id="eventFieldErrorId('segment')" class="form-error" role="alert">{{ eventFieldError('segment') }}</small>
                 </label>
                 <div v-if="selectedSegment" class="segment-status">
                   <span class="muted-note">{{ t('match.segmentStatus') }}</span>
                   <strong>{{ statusLabel(selectedSegment.status) }}</strong>
                 </div>
                 <p v-if="!activeSegment" class="segment-warning">{{ t('match.noActiveSegment') }}</p>
                   <button v-if="canOperateMatch" class="button-primary" type="button" :disabled="Boolean(busyAction) || isTerminal" @click="createSegment">{{ activeSegment ? t('match.createSegment') : t('match.startNextSegment') }}</button>
                  <form v-if="canOperateMatch && activeSegment" class="interruption-form" @submit.prevent="interruptSegment">
                   <h3>{{ t('match.interruptSegment') }}</h3>
                   <p class="muted-note">{{ t('match.interruptionHint') }}</p>
                   <label>{{ t('match.interruptReason') }}<select v-model="interruptionForm.reason"><option value="lighting_failure">{{ t('match.reasonLightingFailure') }}</option><option value="weather">{{ t('match.reasonWeather') }}</option><option value="pitch_invasion">{{ t('match.reasonPitchInvasion') }}</option><option value="other">{{ t('match.reasonOther') }}</option></select></label>
                   <label>{{ t('match.interruptMinute') }}<input v-model.number="interruptionForm.minute" type="number" min="0" :max="resolutionLimits.maxMinute" required @input="markInterruptionMinuteDirty" /></label>
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
                <form v-if="canManageTournaments" class="field-row official-row" @submit.prevent="assignOfficial">
                  <label>{{ t('match.person') }}<select v-model="officialForm.organization_user_id" required><option value="" disabled>{{ t('match.selectOfficial') }}</option><option v-for="official in operation.eligible_officials" :key="official.organization_user_id" :value="official.organization_user_id">{{ official.full_name }} · {{ official.email }}</option></select></label>
                  <label>{{ t('match.role') }}<select v-model="officialForm.official_role"><option v-for="role in officialRoles" :key="role.value" :value="role.value">{{ t(role.labelKey) }}</option></select></label>
                  <button class="button-secondary compact-button" type="submit" :disabled="Boolean(busyAction) || isTerminal">{{ t('match.assign') }}</button>
                 </form>
                <ul v-if="operation.officials.length" class="compact-list">
                   <li v-for="official in operation.officials" :key="official.id"><span><strong>{{ officialLabel(official.official_role) }}</strong> · {{ official.full_name }}</span><button v-if="canManageTournaments" type="button" class="text-button" :disabled="Boolean(busyAction) || isTerminal" @click="removeOfficial(official)">{{ t('match.remove') }}</button></li>
                </ul>
                <p v-else class="muted-note">{{ t('match.noOfficials') }}</p>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-heading"><div><p class="eyebrow">02 · {{ t('match.roster') }}</p><h2>{{ t('match.roster') }}</h2></div></div>
            <p class="muted-note">{{ t('match.rosterManagedInRosters') }}</p>
            <ul class="roster-links">
              <li v-for="team in teamRosters" :key="`roster-link-${team.key}`">
                <NuxtLink v-if="team.team_id" :to="teamRosterLink(team.team_id)">{{ t('match.openTeamRoster', { team: team.name }) }}</NuxtLink>
              </li>
            </ul>
          </section>

           <section class="panel panel-wide">
               <div class="panel-heading"><div><p class="eyebrow">03 · {{ t('match.roster') }}</p><h2>{{ t('match.definePlayers') }}</h2></div><button v-if="canOperateMatch" class="button-primary" type="button" :disabled="Boolean(busyAction) || isTerminal || !selectedSegmentIsActive" @click="saveLineup">{{ busyAction === 'lineup' ? t('match.savingLineup') : t('match.saveLineup') }}</button></div>
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
                    <select :value="lineupFormations[team.team_id] || ''" :disabled="!canOperateMatch || !team.team_id || isTerminal || !selectedSegmentIsActive" @change="setFormation(team.team_id, $event)">
                     <option value="">{{ t('match.classicLineup') }}</option>
                     <option v-for="formation in FORMATION_OPTIONS" :key="formation" :value="formation">{{ formation }}</option>
                   </select>
                 </label>
                  <button v-if="canOperateMatch && team.team_id && lineupFormations[team.team_id]" class="text-button publication-button" type="button" :disabled="Boolean(busyAction) || isTerminal || !tacticalRowsForTeam(team.team_id).length" @click="toggleLineupPublication(team.team_id)">
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
                       <select v-model="lineupRoles[player.roster_id]" :disabled="!canOperateMatch || !player.is_active || isTerminal || !selectedSegmentIsActive" :aria-label="`${t('match.role')} ${playerName(player)}`"><option value="">{{ t('match.notParticipating') }}</option><option value="starter">{{ t('match.starter') }}</option><option value="substitute">{{ t('match.substitute') }}</option></select>
                       <select v-if="lineupRoles[player.roster_id] === 'starter'" v-model="lineupPositions[player.roster_id]" :disabled="!canOperateMatch || !player.is_active || isTerminal || !selectedSegmentIsActive || !lineupFormations[team.team_id]" :aria-label="`${t('match.position')} ${playerName(player)}`">
                        <option value="">{{ t('match.selectPosition') }}</option>
                        <option v-for="position in availablePositions(team.team_id)" :key="position" :value="position">{{ positionLabel(position, t) }}</option>
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
             <p v-if="draftDroppedEvents > 0" class="segment-warning" role="status">{{ t('match.draftEventsDropped', { count: draftDroppedEvents }) }}</p>
             <div v-if="canOperateMatch" class="event-form">
              <label>{{ t('match.eventType') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.event_type" required :aria-invalid="Boolean(eventFieldError('event_type'))" :aria-describedby="eventFieldDescribedBy('event_type')"><option v-for="event in eventTypes" :key="event.value" :value="event.value">{{ t(event.labelKey) }}</option></select><small v-if="eventFieldError('event_type')" :id="eventFieldErrorId('event_type')" class="form-error" role="alert">{{ eventFieldError('event_type') }}</small></label>
              <p class="field-hint full-width" role="status">{{ eventTypeNotice }}</p>
              <label>{{ t('setup.teams') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.team_id" required :aria-invalid="Boolean(eventFieldError('team'))" :aria-describedby="eventFieldDescribedBy('team')"><option value="" disabled>{{ t('match.select') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select><small v-if="eventFieldError('team')" :id="eventFieldErrorId('team')" class="form-error" role="alert">{{ eventFieldError('team') }}</small></label>
               <template v-if="eventOwnFields.includes('player_out')">
                  <label>{{ t('match.playerOut') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.player_out_id" :disabled="eventSubstitutionAvailability.disabled" :required="isEventFieldRequired(eventForm.event_type, 'player_out')" :aria-invalid="Boolean(eventFieldError('player_out'))" :aria-describedby="eventFieldDescribedBy('player_out')"><option value="" disabled>{{ t('match.select') }}</option><option v-for="row in eventOutgoingOptions" :key="`out-${row.player.roster_id}`" :value="row.player.player_id" :disabled="row.option.disabled">#{{ row.player.dorsal_number }} · {{ playerName(row.player) }}<template v-if="row.option.disabled"> · {{ substitutionMessage(row.option.reason) }}</template></option></select><small v-if="eventFieldError('player_out')" :id="eventFieldErrorId('player_out')" class="form-error" role="alert">{{ eventFieldError('player_out') }}</small></label>
                  <label>{{ t('match.playerIn') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.player_in_id" :disabled="eventSubstitutionAvailability.disabled" :required="isEventFieldRequired(eventForm.event_type, 'player_in')" :aria-invalid="Boolean(eventFieldError('player_in'))" :aria-describedby="eventFieldDescribedBy('player_in')"><option value="" disabled>{{ t('match.select') }}</option><option v-for="row in eventIncomingOptions" :key="`in-${row.player.roster_id}`" :value="row.player.player_id" :disabled="row.option.disabled">#{{ row.player.dorsal_number }} · {{ playerName(row.player) }}<template v-if="row.option.disabled"> · {{ substitutionMessage(row.option.reason) }}</template></option></select><small v-if="eventFieldError('player_in')" :id="eventFieldErrorId('player_in')" class="form-error" role="alert">{{ eventFieldError('player_in') }}</small></label>
                </template>
                <template v-else>
                  <label>{{ t('match.player') }}<span v-if="isEventFieldRequired(eventForm.event_type, 'player')" class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.player_id" :required="isEventFieldRequired(eventForm.event_type, 'player')" :aria-invalid="Boolean(eventFieldError('player'))" :aria-describedby="eventFieldDescribedBy('player')"><option value="" disabled>{{ t('match.select') }}</option><option v-for="player in eventPlayers" :key="player.roster_id" :value="player.player_id">#{{ player.dorsal_number }} · {{ playerName(player) }}</option></select><small v-if="eventFieldError('player')" :id="eventFieldErrorId('player')" class="form-error" role="alert">{{ eventFieldError('player') }}</small></label>
                  <label v-if="eventOwnFields.includes('beneficiary')">{{ t('match.beneficiary') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.beneficiary_team_id" required :aria-invalid="Boolean(eventFieldError('beneficiary'))" :aria-describedby="eventFieldDescribedBy('beneficiary')"><option value="" disabled>{{ t('match.select') }}</option><option v-if="match.home_team_id && match.home_team_id !== eventForm.team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id && match.away_team_id !== eventForm.team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select><small v-if="eventFieldError('beneficiary')" :id="eventFieldErrorId('beneficiary')" class="form-error" role="alert">{{ eventFieldError('beneficiary') }}</small></label>
                  <label v-if="eventOwnFields.includes('assist')">{{ t('match.assist') }}<select v-model="eventForm.assist_player_id" :aria-invalid="Boolean(eventFieldError('assist'))" :aria-describedby="eventFieldDescribedBy('assist')"><option value="">{{ t('match.assistNone') }}</option><option v-for="player in eventAssistCandidates" :key="`assist-${player.roster_id}`" :value="player.player_id">#{{ player.dorsal_number }} · {{ playerName(player) }}</option></select><small v-if="eventFieldError('assist')" :id="eventFieldErrorId('assist')" class="form-error" role="alert">{{ eventFieldError('assist') }}</small></label>
                </template>
               <label v-if="eventOwnFields.includes('red_card_type')">{{ t('match.redCardType') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="eventForm.red_card_type" :required="isEventFieldRequired(eventForm.event_type, 'red_card_type')" :aria-invalid="Boolean(eventFieldError('red_card_type'))" :aria-describedby="eventFieldDescribedBy('red_card_type')"><option value="direct_red">{{ t('match.directRed') }}</option><option value="double_yellow_red">{{ t('match.doubleYellowRed') }}</option></select><small v-if="eventFieldError('red_card_type')" :id="eventFieldErrorId('red_card_type')" class="form-error" role="alert">{{ eventFieldError('red_card_type') }}</small></label>
               <label>{{ t('match.minute') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><input v-model.number="eventForm.minute" type="number" min="0" :max="resolutionLimits.maxMinute" required :aria-invalid="Boolean(eventFieldError('minute'))" :aria-describedby="eventFieldDescribedBy('minute')" /><small v-if="eventFieldError('minute')" :id="eventFieldErrorId('minute')" class="form-error" role="alert">{{ eventFieldError('minute') }}</small></label>
              <label>{{ t('match.addedMinute') }}<input v-model.number="eventForm.added_minute" type="number" min="0" :max="resolutionLimits.addedMax" :aria-invalid="Boolean(eventFieldError('added_minute'))" :aria-describedby="eventFieldDescribedBy('added_minute')" /><small v-if="eventFieldError('added_minute')" :id="eventFieldErrorId('added_minute')" class="form-error" role="alert">{{ eventFieldError('added_minute') }}</small></label>
              <p v-if="eventForm.event_type === 'goal'" class="field-hint" role="status">{{ t('match.assistHint') }}</p>
              <p v-else-if="eventForm.event_type === 'foul'" class="field-hint" role="status">{{ t('match.foulInformative') }}</p>
                <div v-if="eventForm.event_type === 'substitution'" class="substitution-preview" role="status">
                  <strong>{{ t('match.substitutionPreview') }}</strong>
                  <span>{{ t('match.substitutionsRemaining', { used: eventSubstitutionCounters.substitutions_used, max: eventSubstitutionTeam?.max_per_team ?? 0 }) }}</span>
                  <span>{{ t('match.windowsRemaining', { used: eventSubstitutionCounters.windows_used, max: eventSubstitutionTeam?.max_windows ?? 0 }) }}</span>
                  <span v-if="eventSubstitutionAvailability.disabled || !eventSubstitutionCounters.can_register" class="substitution-blocked">{{ substitutionMessage(eventSubstitutionAvailability.reason || 'exhausted') }}</span>
                </div>
                <button class="button-secondary" type="button" :disabled="isTerminal || !selectedSegmentIsActive || (eventForm.event_type === 'substitution' && (eventSubstitutionAvailability.disabled || !eventSubstitutionCounters.can_register))" @click="addEvent">{{ t('match.addEvent') }}</button>
                <p v-if="eventIdError" class="form-error event-id-error" role="alert">{{ eventIdError }}</p>
            </div>
              <p v-if="draftMinuteMessage" class="segment-warning" role="alert">{{ draftMinuteMessage }}</p>
              <ul v-if="draftEvents.length" class="event-list">
                <li v-for="event in draftEvents" :key="event.client_event_id"><span><strong>{{ event.minute }}' · {{ eventLabel(event.event_type) }}</strong> · {{ teamName(event.team_id) }} · {{ draftEventSummary(event) }}</span><button v-if="canOperateMatch" type="button" class="text-button" @click="removeEvent(event.client_event_id)">{{ t('match.remove') }}</button></li>
             </ul>
              <button v-if="canOperateMatch && hasUnsavedDraft" class="text-button draft-discard" type="button" @click="discardDraft">{{ t('match.discardDraft') }}</button>
             <ul v-if="!draftEvents.length && operation.events.length" class="event-list persisted-events">
               <li v-for="event in operation.events" :key="event.id"><span><strong>{{ event.minute }}' · {{ eventLabel(event.event_type) }}</strong> · {{ event.team_name }} · {{ persistedEventSummary(event) }}</span><small>{{ event.is_voided ? t('match.voided') : t('match.confirmed') }}</small></li>
            </ul>
              <p v-else-if="!draftEvents.length" class="muted-note">{{ t('match.eventsAtomic') }}</p>
          </section>

           <section class="panel close-panel panel-wide" @focusin="beginClose">
            <div class="panel-heading"><div><p class="eyebrow">05 · {{ t('match.result') }}</p><h2>{{ t('match.closeReport') }}</h2></div><span class="muted-note">{{ rulesDefaults.extra_time_enabled ? t('match.overtimeEnabled') : t('match.noOvertime') }}</span></div>
             <div class="score-form">
               <p class="muted-note close-resolution full-width">{{ t('match.closeUsesResolution', { resolution: resolutionLabel(resolution) }) }}<template v-if="resolution !== 'walkover'"> · {{ t('match.resolutionMaximum', { max: resolutionLimits.maxMinute }) }}</template></p>
               <template v-if="resolution === 'walkover'">
                 <!-- RF-012/D-7: el W.O. no necesita segmento ni planilla; se dice para que el botón habilitado no parezca un defecto. -->
                 <p class="muted-note full-width walkover-notice" role="status">{{ t('match.walkoverNoSegment') }}</p>
                  <label>{{ t('match.winner') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="closeForm.winner_team_id" required :disabled="!canOperateMatch || isTerminal" :aria-invalid="Boolean(walkoverWinnerError)" :aria-describedby="walkoverWinnerDescribedBy"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select><small v-if="walkoverWinnerError" :id="WALKOVER_WINNER_ERROR_ID" class="form-error" role="alert">{{ walkoverWinnerError }}</small></label>
                  <label>{{ t('match.walkoverReason') }}<span class="required-mark" aria-hidden="true" :title="t('match.requiredField')">*</span><select v-model="closeForm.reason" required :disabled="!canOperateMatch || isTerminal" :aria-invalid="Boolean(walkoverReasonError)" :aria-describedby="walkoverReasonDescribedBy"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-for="option in walkoverReasonOptions" :key="option.value" :value="option.value">{{ t(option.labelKey) }}</option></select><small v-if="walkoverReasonError" :id="WALKOVER_REASON_ERROR_ID" class="form-error" role="alert">{{ walkoverReasonError }}</small></label>
                 <!-- RF-005: la pareja efectiva la deriva el servidor; aquí solo se muestra, nunca se edita ni se envía. -->
                 <p class="muted-note full-width walkover-score" role="status">{{ t('match.walkoverScore') }}: {{ walkoverScore ? `${walkoverScore.winner}-${walkoverScore.loser}` : '—' }}</p>
               </template>
               <template v-else>
               <label>{{ match.home_team_name }} · {{ t('match.regularScore') }}<input v-model.number="closeForm.home_score_regular" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" /></label>
               <label>{{ match.away_team_name }} · {{ t('match.regularScore') }}<input v-model.number="closeForm.away_score_regular" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" /></label>
              <template v-if="resolution !== 'regular'">
                  <label>{{ match.home_team_name }} · {{ t('match.finalScore') }}<input v-model.number="closeForm.home_score" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" /></label>
                  <label>{{ match.away_team_name }} · {{ t('match.finalScore') }}<input v-model.number="closeForm.away_score" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" /></label>
                  <label v-if="resolution === 'penalties'">{{ t('match.homePenalties') }}<input v-model.number="closeForm.home_penalties" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" /></label>
                  <label v-if="resolution === 'penalties'">{{ t('match.awayPenalties') }}<input v-model.number="closeForm.away_penalties" type="number" min="0" required :disabled="!canOperateMatch || isTerminal" /></label>
                   <label>{{ t('match.winner') }}<select v-model="closeForm.winner_team_id" required :disabled="!canOperateMatch || isTerminal"><option value="" disabled>{{ t('match.selectWinner') }}</option><option v-if="match.home_team_id" :value="match.home_team_id">{{ match.home_team_name }}</option><option v-if="match.away_team_id" :value="match.away_team_id">{{ match.away_team_name }}</option></select></label>
               </template>
                <label v-if="resolution === 'administrative'" class="full-width">{{ t('match.administrativeReason') }}<textarea v-model="closeForm.reason" maxlength="1000" required :disabled="!canOperateMatch || isTerminal" /></label>
               </template>
             </div>
                <div class="close-actions"><p class="muted-note">{{ t('match.backendValidation') }}</p><button v-if="canOperateMatch" class="button-primary close-button" type="button" :disabled="Boolean(busyAction) || isTerminal || (!selectedSegmentIsActive && resolution !== 'walkover')" @click="closeMatch">{{ busyAction === 'close' ? t('match.closing') : isTerminal ? t('match.closed') : t('match.confirmReport') }}</button></div>
          </section>
        </div>
      </template>
    </section>
   </main>
  </WorkspaceShell>
</template>

<style scoped>
.match-title { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.match-title :deep(.team-crest) { flex: 0 0 auto; }
.match-versus { color: var(--accent); font-size: 0.62em; letter-spacing: 0; }
.operation-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, rgba(212, 243, 106, 0.09), transparent 30rem), #0c0f0c; }
.realtime-status { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; }
.realtime-error, .realtime-reconnecting, .realtime-retrying { color: #ffcb7a; }
.realtime-retry { padding: 0; background: transparent; color: var(--accent); font-size: 0.68rem; text-decoration: underline; }
.operation-hero { padding: 4vh 0 3vh; animation: rise-in 700ms var(--ease-out) both; }
.hero-line, .panel-heading, .team-heading, .close-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.status-pill, .check-item { display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--line); border-radius: 999px; padding: 0.42rem 0.7rem; color: var(--muted); font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; }
.status-pill.finished { color: var(--accent); border-color: rgba(212, 243, 106, 0.4); }
.status-pill.interrupted { color: #ffcb7a; border-color: rgba(255, 203, 122, 0.4); }
.match-heading { display: flex; align-items: end; justify-content: space-between; gap: 30px; margin-top: 18px; }
.context-line, .workspace-copy, .panel-description { color: var(--muted); }
.context-line { margin: 0; font-size: 0.82rem; letter-spacing: 0.08em; text-transform: uppercase; }
.match-heading h1 { max-width: 880px; margin: 12px 0; font-size: clamp(2.2rem, 5vw, 4.6rem); line-height: 0.94; letter-spacing: -0.08em; }
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
.required-mark { margin-left: 3px; color: var(--accent); font-weight: 700; }
label > small.form-error { padding: 0; border: 0; font-size: 0.72rem; }
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
.substitution-preview { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid rgba(212, 243, 106, 0.22); border-radius: 10px; background: rgba(212, 243, 106, 0.05); color: var(--muted); font-size: 0.76rem; }
.substitution-preview strong { color: var(--accent); font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase; }
.substitution-blocked { color: #ffcb7a; }
.substitution-error { grid-column: 1 / -1; padding: 10px 12px; }
.official-row { grid-template-columns: minmax(0, 1fr) minmax(150px, 0.7fr) auto; align-items: end; }
.roster-links { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.roster-links a { color: var(--accent); font-size: 0.82rem; text-decoration: none; }
.roster-links a:hover { text-decoration: underline; }
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
.resolution-panel { margin-bottom: 16px; border-color: rgba(212, 243, 106, 0.24); }
.resolution-summary { display: flex; flex-wrap: wrap; align-items: end; gap: 16px; }
.resolution-summary label { flex: 0 1 280px; }
.resolution-limits { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0; color: var(--muted); font-size: 0.78rem; }
.resolution-limits strong { color: var(--accent); }
.close-resolution { grid-column: 1 / -1; margin: 0; }
.close-button { min-width: 190px; }
.empty-state, .form-error { padding: 20px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.form-error { border-style: solid; border-color: #a45b5b; color: var(--danger); }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
@media (max-width: 1000px) { .event-form { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .container { width: min(100% - 28px, 620px); } .match-heading, .close-actions { align-items: start; flex-direction: column; } .scoreboard { align-self: end; } .operation-grid, .sub-grid, .roster-columns, .formation-config-grid { grid-template-columns: 1fr; } .panel-wide { grid-column: auto; } .official-row, .event-form, .score-form { grid-template-columns: 1fr; } .close-button { width: 100%; } }
@media (max-width: 480px) { .player-row { grid-template-columns: 27px minmax(0, 1fr); } .player-row select { grid-column: 2; } .position-placeholder { grid-column: 2; } }
@media (max-width: 375px) { .operation-actions, .draft-status-group { align-items: stretch; flex-direction: column; } .operation-actions > * { justify-content: center; text-align: center; } .panel { padding: 16px; } .scoreboard { align-self: stretch; justify-content: center; } }
</style>
