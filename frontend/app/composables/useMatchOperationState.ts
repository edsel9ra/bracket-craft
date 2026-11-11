import { useMatchResolution } from '~/composables/useMatchResolution';
import { checklistPresentation } from '~/utils/operationChecklist';
import { type FormationCode } from '~/constants/formations';
import { matchSelectionKey } from '~/utils/matchNavigation';
import { RESOLUTION_LABEL_KEYS, enabledResolutions, findDraftMinuteViolations, matchLimitsFor, maximumMinuteSource, type EventMinuteValidation, type MaximumSource, type OperationLimits, type ResolutionType } from '~/utils/matchResolution';
import { assistCandidates, eventTypeAnnouncement, visibleEventFields } from '~/utils/matchEvents';
import { WALKOVER_REASON_LABEL_KEYS, WALKOVER_REASONS, walkoverScoreFrom, type ClosePreflightIssue } from '~/utils/matchClose';
import { SEGMENT_PROPOSAL_HINT_LABEL_KEYS, segmentProposalHint } from '~/utils/matchSegments';
import { effectiveRosterLimits, type OpeningBlockedDescription } from '~/utils/rosterLimits';
import { gameFormatOf } from '~/utils/rulesWizard';
import { createMatchDraftStore, type MatchDraftStorage } from '~/utils/matchDraft';
import { realtimeStatusLabelKey } from '~/utils/realtimeStatusLabel';
import { DEFAULT_MATCH_LIMITS, normalizeMatchLimits, normalizeSubstitutionsState, previewCounters, substitutionAvailability, substitutionOptions, teamSubstitutionState, type SubstitutionOption, type SubstitutionUnavailableReason } from '~/utils/substitutions';
import type { EventType, RedCardType, OfficialRole, LineupRole, InterruptionReason, RosterEntry, MatchOperation, DraftEvent, EventFieldKey, EventFieldIssue } from '~/components/match/types';

export interface MatchOperationBindings {
  eventMinuteMessage(validation: EventMinuteValidation): string;
  changeResolution(next: ResolutionType): Promise<void>;
  rosterOptions(options: SubstitutionOption[]): Array<{ player: RosterEntry; option: SubstitutionOption }>;
  draftStorageOrNull(): MatchDraftStorage | null;
  teamName(teamId: string | null): string;
}

export function useMatchOperationState(bindings: MatchOperationBindings) {
  const { eventMinuteMessage, changeResolution, rosterOptions, draftStorageOrNull, teamName } = bindings;

  const route = useRoute();

  const auth = useAuthStore();

  const { request } = useApi();

  const { t, statusLabel, formatDateTime, errorMessage } = useI18n();

  const { confirm } = useConfirm({ singleFlight: true });

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
    { label: t('status.published'), ...checklistPresentation(match.value?.version_status === 'published', isTerminal.value) },
    { label: t('match.activeSegment'), ...checklistPresentation(Boolean(activeSegment.value), isTerminal.value, 'match.notRequired') },
    { label: t('match.roster'), ...checklistPresentation(hasCompleteLineup.value || Boolean(operation.value?.lineup.length), isTerminal.value) },
    { label: t('match.mainReferee'), ...checklistPresentation(Boolean(operation.value?.officials.some((official) => official.official_role === 'main_referee')), isTerminal.value, 'match.unassigned') },
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

  const draftStore = computed(() => createMatchDraftStore({
    userId: auth.userId,
    organizationId: auth.organizationId,
    matchId,
  }, draftStorageOrNull()));

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

  // RF-021: el alta de jugadores vive solo en la administración de plantillas.
  // RF-022: desde aquí se enlaza a la plantilla del equipo con contexto de
  // retorno; el partido (dirección), el segmento seleccionado y el borrador local
  // se conservan al volver.
  const rostersHref = computed(() => (match.value
    ? `/workspace/tournaments/${match.value.tournament_id}/rosters`
    : ''));

  const selectedSegmentStorageKey = computed(() => matchSelectionKey({
    userId: auth.userId || 'anonymous',
    organizationId: auth.organizationId || 'anonymous',
    matchId,
  }));

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

  const realtimeStatusLabel = computed(() => {
    const key = realtimeStatusLabelKey(realtime.status.value, 'match');
    return key ? t(key) : '';
  });

  return {
    route,
    auth,
    request,
    t,
    statusLabel,
    formatDateTime,
    errorMessage,
    confirm,
    realtime,
    matchId,
    operation,
    loading,
    error,
    actionError,
    openingBlocked,
    busyAction,
    selectedSegmentId,
    lineupRoles,
    lineupPositions,
    lineupFormations,
    draftEvents,
    draftRestored,
    draftSavedAt,
    draftDroppedEvents,
    segmentForm,
    interruptionForm,
    officialForm,
    eventForm,
    eventIdError,
    eventFieldIssues,
    closeForm,
    officialRoles,
    eventTypes,
    eventTypeValues,
    substitutionReasonKeys,
    match,
    isTerminal,
    canManageTournaments,
    canOperateMatch,
    workspaceBreadcrumbs,
    tournamentContext,
    selectedSegment,
    activeSegment,
    selectedSegmentIsActive,
    selectedInterruption,
    segmentProposalHintText,
    homeRoster,
    awayRoster,
    eventPlayers,
    eventRosterPlayers,
    eventOwnFields,
    eventTypeNotice,
    eventAssistCandidates,
    substitutionState,
    matchLimits,
    operationLimits,
    resolution,
    plannedResolution,
    restoreResolution,
    selectResolution,
    snapshotResolution,
    resolutionFallback,
    resolutionChangeNotice,
    closeSnapshotTaken,
    resolutionOptions,
    resolutionLimits,
    draftMinuteViolations,
    draftMinuteMessage,
    resolutionMaximumSource,
    selectedResolution,
    eventSubstitutionTeam,
    eventSubstitutionAvailability,
    eventSubstitutionCounters,
    eventSubstitutionOptions,
    eventOutgoingOptions,
    eventIncomingOptions,
    teamRosters,
    openingRosterLimits,
    openingRosterParticipants,
    lineupEntries,
    selectedLineupTeams,
    selectedTacticalLineups,
    hasCompleteLineup,
    rulesDefaults,
    matchGameFormat,
    operationChecklist,
    defaultCloseForm,
    hasUnsavedDraft,
    draftStore,
    walkoverScore,
    walkoverReasonOptions,
    WALKOVER_WINNER_ERROR_ID,
    WALKOVER_REASON_ERROR_ID,
    closeFieldIssue,
    walkoverWinnerError,
    walkoverWinnerDescribedBy,
    walkoverReasonError,
    walkoverReasonDescribedBy,
    rostersHref,
    selectedSegmentStorageKey,
    eventValidationIssues,
    eventSegmentMinuteKeys,
    eventAssistIssueKeys,
    eventFormIssueKeys,
    realtimeStatusLabel,
  };
}

export type MatchOperationState = ReturnType<typeof useMatchOperationState>;
