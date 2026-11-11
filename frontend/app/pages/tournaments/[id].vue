<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import { nextTick } from 'vue';
import { useRealtime } from '~/composables/useRealtime';
import {
  appendedPageSlice,
  createReloadCoordinator,
  createRequestGeneration,
  decideReload,
  firstPageSlice,
  PUBLIC_FIRST_PAGE_OFFSET,
  resyncTrigger,
  shouldPollPublicRealtime,
  type ReloadTrigger,
} from '~/utils/realtimeReload';
import {
  combinationKey,
  getPublicStagePresentation,
  groupsOfStage,
  matchesForGroup,
  normalizePublicSelection,
  resolveMatchOutcomeLabel,
  resolvePublicStatsScope,
  sortPublicStages,
  standingsForGroup,
  type PublicMatch,
  type PublicSelection,
  type PublicStage,
  type PublicStanding,
  type PublicStatsScope,
  type PublicTournament,
  type PublicStagePresentation,
} from '~/utils/publicTournament';
import { realtimeStatusLabelKey } from '~/utils/realtimeStatusLabel';
import type { LocationQueryRaw } from 'vue-router';

const route = useRoute();
const router = useRouter();
const { request } = useApi();
const { t, statusLabel, stageTypeLabel, formatDateTime, errorMessage } = useI18n();
const realtime = useRealtime();
const tournamentId = String(route.params.id);
const PAGE_SIZE = 50;
const PUBLIC_REFRESH_INTERVAL_MS = 30_000;

interface PublicTournamentData {
  tournament: PublicTournament;
}

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

const { data: tournamentData, status, error: dataError, refresh } = await useAsyncData<PublicTournamentData>(
  `public-tournament-${tournamentId}`,
  async () => {
    const tournament = await request<PublicTournament>(`/tournaments/public/${tournamentId}`);
    return { tournament };
  },
);

const tournament = computed<PublicTournament | null>(() => tournamentData.value?.tournament ?? null);
const standings = ref<PublicStanding[]>([]);
const matches = ref<PublicMatch[]>([]);
const stages = computed(() => sortPublicStages(tournament.value?.stages ?? []));
const stageAwareLayout = computed(() => stages.value.length > 0);
const selectedStage = computed<PublicStage | null>(() =>
  stages.value.find((stage) => stage.id === selectedStageId.value) ?? stages.value[0] ?? null,
);
const selectedStageGroups = computed(() =>
  selectedStage.value ? groupsOfStage(standings.value, selectedStage.value.id) : [],
);

const routeStageParam = computed(() => (typeof route.query.stage === 'string' ? route.query.stage : null));
const routeGroupParam = computed(() => (typeof route.query.group === 'string' ? route.query.group : null));

const publicSelection = computed<PublicSelection>(() =>
  normalizePublicSelection(stages.value, standings.value, routeStageParam.value, routeGroupParam.value),
);
const selectedStageId = computed(() => publicSelection.value.stageId);
const selectedGroupId = computed(() => publicSelection.value.groupId);
const selectedLineupMatchId = ref<string | null>(null);
const lineupTrigger = ref<HTMLButtonElement | null>(null);
const selectedLineupMatch = computed(() => matches.value.find((match) => match.id === selectedLineupMatchId.value) ?? null);
const loading = computed(() => status.value === 'pending');
const error = computed(() => dataError.value ? failureMessage(dataError.value, t('public.noLoad')) : null);
const standingsOffsets = ref(new Map<string, number>());
const standingsHasMoreByCombo = ref(new Map<string, boolean>());
const matchesOffsets = ref(new Map<string, number>());
const matchesHasMoreByCombo = ref(new Map<string, boolean>());
const loadingMore = ref<'standings' | 'matches' | null>(null);

const playerStats = ref<any[]>([]);
const teamStats = ref<any[]>([]);
const playerStatsOffset = ref(0);
const teamStatsOffset = ref(0);
const playerStatsHasMore = ref(false);
const teamStatsHasMore = ref(false);
const statsLoadingMore = ref<'players' | 'teams' | null>(null);
const statsTab = ref<'players' | 'teams'>('players');

// Ámbito de las tablas de estadísticas (spec 022, RF-021): el valor inicial es
// el torneo completo y ninguna fase se preselecciona, así que la primera
// petición sale sin `stage_id`. La fase solo llega desde el control de la
// sección, que es una acción explícita del usuario y reversible.
const statsStageId = ref<string | null>(null);
// Un grupo solo vale dentro de una fase elegida y esa fase es la que la
// dirección tiene seleccionada, porque sus grupos son los que están cargados.
const statsGroupParam = computed<string | null>(() => (
  statsStageId.value !== null && routeStageParam.value === statsStageId.value
    ? routeGroupParam.value
    : null
));
const statsScope = computed<PublicStatsScope>(() => resolvePublicStatsScope(
  stages.value,
  statsStageId.value,
  statsGroupParam.value,
  standings.value,
));
const statsScopeKey = computed(() => combinationKey(statsScope.value.stageId, statsScope.value.groupId));
// Generación propia de las peticiones de estadísticas: una respuesta lenta de
// un ámbito anterior no sobrescribe el ámbito actual.
const statsGeneration = createRequestGeneration();

const activeComboKey = computed(() => combinationKey(selectedStageId.value, selectedGroupId.value));
const activeStandingsHasMore = computed(() => standingsHasMoreByCombo.value.get(activeComboKey.value) ?? false);
const activeMatchesHasMore = computed(() => matchesHasMoreByCombo.value.get(activeComboKey.value) ?? false);

function comboHasMore(kind: 'standings' | 'matches', stageId: string | null, groupId: string | null): boolean {
  const map = kind === 'standings' ? standingsHasMoreByCombo.value : matchesHasMoreByCombo.value;
  return map.get(combinationKey(stageId, groupId)) ?? false;
}
const refreshing = ref(false);
const listError = ref<string | null>(null);
const requestGeneration = createRequestGeneration();
let publicRefreshTimer: number | null = null;

function stagePresentation(stage: PublicStage): PublicStagePresentation {
  return getPublicStagePresentation(stage.stage_type);
}

function resolutionLabel(match: PublicMatch): string {
  const outcome = resolveMatchOutcomeLabel(match);
  if (outcome === 'walkover') return t('match.walkover');
  if (outcome === 'penalties') return t('public.penalties');
  if (outcome === 'extra_time') return t('match.overtime');
  if (outcome === 'administrative') return t('match.administrative');
  return '';
}

function standingsForStage(stageId: string): PublicStanding[] {
  return standings.value.filter((standing) => standing.stage_id === stageId);
}

function matchesForStage(stageId: string): PublicMatch[] {
  return matches.value.filter((match) => match.stage_id === stageId);
}

const firstStandingsStageId = computed(() => stages.value.find(
  (stage) => stagePresentation(stage) === 'standings',
)?.id ?? null);
const firstMatchesStageId = computed(() => stages.value.find(
  (stage) => matchesForStage(stage.id).length > 0,
)?.id ?? stages.value[0]?.id ?? null);

useHead(() => ({
  title: tournament.value ? `${tournament.value.name} | Bracket Craft` : `${t('public.tournament')} | Bracket Craft`,
  meta: [
    {
      name: 'description',
      content: tournament.value
        ? `${t('public.standings')} y resultados públicos de ${tournament.value.name}.`
        : `${t('public.standings')} y resultados públicos del torneo.`,
    },
  ],
}));

function formatScore(match: PublicMatch) {
  if (match.home_score === null || match.away_score === null) return '-';
  const penalties = match.home_penalties !== null && match.away_penalties !== null
     ? ` (${match.home_penalties}-${match.away_penalties} ${t('public.penalties')})`
    : '';
  return `${match.home_score}-${match.away_score}${penalties}`;
}

function formatDate(value: string | null) {
  if (!value) return t('public.dateToDefine');
  return formatDateTime(value);
}

function openLineup(match: PublicMatch, event: MouseEvent) {
  if (!match.lineup) return;
  selectedLineupMatchId.value = match.id;
  lineupTrigger.value = event.currentTarget as HTMLButtonElement;
}

function closeLineup() {
  const trigger = lineupTrigger.value;
  selectedLineupMatchId.value = null;
  lineupTrigger.value = null;
  void nextTick(() => trigger?.focus());
}

function payloadTargetsTournament(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object') return true;
  const value = payload as { tournament_id?: unknown };
  if (value.tournament_id !== undefined) return String(value.tournament_id) === tournamentId;
  // A paginated list cannot prove that an unseen match belongs elsewhere.
  return true;
}

async function loadCombinationFirstPage(kind: 'standings' | 'matches', stageId: string | null, groupId: string | null): Promise<void> {
  const key = combinationKey(stageId, groupId);
  const params = new URLSearchParams();
  params.set('limit', String(PAGE_SIZE));
  params.set('offset', '0');
  if (stageId) params.set('stage_id', stageId);
  if (groupId) params.set('group_id', groupId);
  const path = kind === 'standings' ? 'standings' : 'matches';
  const page = await request<any[]>(`/tournaments/public/${tournamentId}/${path}?${params.toString()}`);
  if (kind === 'standings') {
    standings.value = standings.value.filter((s) => !(s.stage_id === stageId && s.group_id === groupId));
    standings.value = [...standings.value, ...page];
    standingsOffsets.value.set(key, page.length);
    standingsHasMoreByCombo.value.set(key, page.length === PAGE_SIZE);
  } else {
    matches.value = matches.value.filter((m) => !(m.stage_id === stageId && m.group_id === groupId));
    matches.value = [...matches.value, ...page];
    matchesOffsets.value.set(key, page.length);
    matchesHasMoreByCombo.value.set(key, page.length === PAGE_SIZE);
  }
}

function statsQuery(scope: PublicStatsScope, offset: number): string {
  const params = new URLSearchParams();
  params.set('limit', String(PAGE_SIZE));
  params.set('offset', String(offset));
  // Sin fase elegida no se envía `stage_id` ni `group_id`: torneo completo (RF-021).
  if (scope.stageId) params.set('stage_id', scope.stageId);
  if (scope.groupId) params.set('group_id', scope.groupId);
  return params.toString();
}

async function loadStatsFirstPage(scope: PublicStatsScope): Promise<void> {
  const generation = statsGeneration.next();
  const query = statsQuery(scope, 0);
  const [players, teams] = await Promise.allSettled([
    request<any[]>(`/tournaments/public/${tournamentId}/player-stats?${query}`),
    request<any[]>(`/tournaments/public/${tournamentId}/team-stats?${query}`),
  ]);
  if (!statsGeneration.isCurrent(generation)) return;
  if (players.status === 'fulfilled') {
    playerStats.value = players.value;
    playerStatsOffset.value = players.value.length;
    playerStatsHasMore.value = players.value.length === PAGE_SIZE;
  } else {
    listError.value = failureMessage(players.reason, t('public.noLoad'));
  }
  if (teams.status === 'fulfilled') {
    teamStats.value = teams.value;
    teamStatsOffset.value = teams.value.length;
    teamStatsHasMore.value = teams.value.length === PAGE_SIZE;
  } else {
    listError.value = failureMessage(teams.reason, t('public.noLoad'));
  }
}

function selectStatsStage(value: string | null | undefined): void {
  statsStageId.value = resolvePublicStatsScope(stages.value, value, null, standings.value).stageId;
}

async function loadMorePlayerStats() {
  if (statsLoadingMore.value || refreshing.value) return;
  if (!playerStatsHasMore.value) return;
  const generation = statsGeneration.next();
  statsLoadingMore.value = 'players';
  try {
    const query = statsQuery(statsScope.value, playerStatsOffset.value);
    const page = await request<any[]>(`/tournaments/public/${tournamentId}/player-stats?${query}`);
    if (!statsGeneration.isCurrent(generation)) return;
    playerStats.value = [...playerStats.value, ...page];
    playerStatsOffset.value = playerStatsOffset.value + page.length;
    playerStatsHasMore.value = page.length === PAGE_SIZE;
  } catch (cause) {
    if (statsGeneration.isCurrent(generation)) listError.value = failureMessage(cause, t('public.noLoad'));
  } finally {
    if (statsLoadingMore.value === 'players') statsLoadingMore.value = null;
  }
}

async function loadMoreTeamStats() {
  if (statsLoadingMore.value || refreshing.value) return;
  if (!teamStatsHasMore.value) return;
  const generation = statsGeneration.next();
  statsLoadingMore.value = 'teams';
  try {
    const query = statsQuery(statsScope.value, teamStatsOffset.value);
    const page = await request<any[]>(`/tournaments/public/${tournamentId}/team-stats?${query}`);
    if (!statsGeneration.isCurrent(generation)) return;
    teamStats.value = [...teamStats.value, ...page];
    teamStatsOffset.value = teamStatsOffset.value + page.length;
    teamStatsHasMore.value = page.length === PAGE_SIZE;
  } catch (cause) {
    if (statsGeneration.isCurrent(generation)) listError.value = failureMessage(cause, t('public.noLoad'));
  } finally {
    if (statsLoadingMore.value === 'teams') statsLoadingMore.value = null;
  }
}

async function resetActiveCombination(): Promise<void> {
  const stageId = selectedStageId.value;
  const groupId = selectedGroupId.value;
  const key = combinationKey(stageId, groupId);
  standings.value = standings.value.filter((s) => !(s.stage_id === stageId && s.group_id === groupId));
  matches.value = matches.value.filter((m) => !(m.stage_id === stageId && m.group_id === groupId));
  standingsOffsets.value.delete(key);
  standingsHasMoreByCombo.value.delete(key);
  matchesOffsets.value.delete(key);
  matchesHasMoreByCombo.value.delete(key);
  await loadCombinationFirstPage('standings', stageId, groupId);
  await loadCombinationFirstPage('matches', stageId, groupId);
}

const publicReload = createReloadCoordinator(async () => {
  const generation = requestGeneration.next();
  refreshing.value = true;
  listError.value = null;
  try {
    await refresh();
    if (requestGeneration.isCurrent(generation) && tournament.value) {
      await resetActiveCombination();
      await loadStatsFirstPage(statsScope.value);
    }
  } catch (cause) {
    if (requestGeneration.isCurrent(generation)) listError.value = failureMessage(cause, t('public.noLoad'));
  } finally {
    if (requestGeneration.isCurrent(generation)) refreshing.value = false;
  }
});

function refreshPublicData() {
  void publicReload.request();
}

function discardPageLoad() {
  if (loadingMore.value === null) return;
  // La respuesta de la página en curso ya no se aplicará.
  requestGeneration.next();
  loadingMore.value = null;
}

function reloadFromRealtime(trigger: ReloadTrigger) {
  const decision = decideReload({
    consumer: 'public',
    trigger,
    initialized: realtime.initialization.initialized,
    initializedWithJoin: realtime.initialization.initializedWithJoin,
  });
  if (decision.action !== 'reload') return;
  discardPageLoad();
  void publicReload.request({ resetPagination: decision.resetPagination });
}

async function loadMore(kind: 'standings' | 'matches', stageId: string | null = selectedStageId.value, groupId: string | null = selectedGroupId.value) {
  if (loadingMore.value || refreshing.value) return;
  const key = combinationKey(stageId, groupId);
  const offsets = kind === 'standings' ? standingsOffsets.value : matchesOffsets.value;
  const hasMoreMap = kind === 'standings' ? standingsHasMoreByCombo.value : matchesHasMoreByCombo.value;
  const hasMore = hasMoreMap.get(key) ?? false;
  if (!hasMore) return;
  const offset = offsets.get(key) ?? 0;
  const generation = requestGeneration.next();
  loadingMore.value = kind;
  try {
    const params = new URLSearchParams();
    params.set('limit', String(PAGE_SIZE));
    params.set('offset', String(offset));
    if (stageId) params.set('stage_id', stageId);
    if (groupId) params.set('group_id', groupId);
    const path = kind === 'standings' ? 'standings' : 'matches';
    const page = await request<any[]>(`/tournaments/public/${tournamentId}/${path}?${params.toString()}`);
    if (!requestGeneration.isCurrent(generation)) return;
    if (kind === 'standings') {
      standings.value = [...standings.value, ...page];
      standingsOffsets.value.set(key, offset + page.length);
      standingsHasMoreByCombo.value.set(key, page.length === PAGE_SIZE);
    } else {
      matches.value = [...matches.value, ...page];
      matchesOffsets.value.set(key, offset + page.length);
      matchesHasMoreByCombo.value.set(key, page.length === PAGE_SIZE);
    }
  } catch (cause) {
    if (requestGeneration.isCurrent(generation)) listError.value = failureMessage(cause, t('public.noLoad'));
  } finally {
    if (loadingMore.value === kind) loadingMore.value = null;
  }
}

const realtimeStatusLabel = computed(() => {
  const key = realtimeStatusLabelKey(realtime.status.value, 'public');
  return key ? t(key) : '';
});

function onRealtimeEvent(event: string, payload: unknown) {
  if (!['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'].includes(event)) return;
  if (payloadTargetsTournament(payload)) reloadFromRealtime('event');
}

function connectRealtime() {
  realtime.connect({
    onEvent: onRealtimeEvent,
    onResync: (payload) => reloadFromRealtime(resyncTrigger(payload.reason)),
  }, { tournamentId });
}

async function applyPublicSelection(selection: PublicSelection, mode: 'replace' | 'push'): Promise<void> {
  if (!import.meta.client) return;
  const query: LocationQueryRaw = { ...route.query };
  if (selection.stageId) query.stage = selection.stageId;
  else delete query.stage;
  if (selection.groupId) query.group = selection.groupId;
  else delete query.group;
  try {
    if (mode === 'replace') await router.replace({ query });
    else await router.push({ query });
  } catch {
    // Navegación cancelada: la dirección sigue siendo la fuente.
  }
}

function selectPublicStage(stageId: string | null): void {
  const normalized = normalizePublicSelection(stages.value, standings.value, stageId, null);
  void applyPublicSelection(normalized, 'push');
}

function selectPublicGroup(groupId: string | null): void {
  const normalized = normalizePublicSelection(stages.value, standings.value, selectedStageId.value, groupId);
  void applyPublicSelection(normalized, 'push');
}

watch([tournament, selectedStageId, selectedGroupId], async () => {
  if (!tournament.value) return;
  const stageId = selectedStageId.value;
  const groupId = selectedGroupId.value;
  const sKey = combinationKey(stageId, groupId);
  if (!standingsOffsets.value.has(sKey)) {
    try { await loadCombinationFirstPage('standings', stageId, groupId); }
    catch (cause) { listError.value = failureMessage(cause, t('public.noLoad')); }
  }
  const mKey = combinationKey(stageId, groupId);
  if (!matchesOffsets.value.has(mKey)) {
    try { await loadCombinationFirstPage('matches', stageId, groupId); }
    catch (cause) { listError.value = failureMessage(cause, t('public.noLoad')); }
  }
}, { immediate: true });

// El ámbito de las tablas de estadísticas es independiente de la fase que
// muestra la navegación (RF-021): se recarga solo cuando cambia de verdad y
// siempre desde la primera página.
watch(statsScopeKey, async () => {
  if (!tournament.value) return;
  // Una fase que deja de existir devuelve el ámbito al torneo completo.
  if (statsScope.value.stageId !== statsStageId.value) statsStageId.value = statsScope.value.stageId;
  statsLoadingMore.value = null;
  await loadStatsFirstPage(statsScope.value);
}, { immediate: true });

onMounted(() => {
  // Normalización inicial con replace: fase o grupo inexistente/ausente.
  const normalized = normalizePublicSelection(stages.value, standings.value, routeStageParam.value, routeGroupParam.value);
  if (normalized.stageId !== routeStageParam.value || normalized.groupId !== routeGroupParam.value) {
    void applyPublicSelection(normalized, 'replace');
  }
  connectRealtime();
  publicRefreshTimer = window.setInterval(() => {
    if (shouldPollPublicRealtime(realtime.status.value)) refreshPublicData();
  }, PUBLIC_REFRESH_INTERVAL_MS);
});
onBeforeUnmount(() => {
  if (publicRefreshTimer !== null) window.clearInterval(publicRefreshTimer);
  realtime.disconnect();
});

function standingsRows(rows: PublicStanding[]): PublicStanding[] {
  return [...rows].sort((a, b) => a.rank - b.rank || a.team_name.localeCompare(b.team_name));
}

</script>

<template>
  <main id="main-content" class="public-shell">
     <header class="container detail-topbar">
       <NuxtLink to="/" class="brand-mark"><span class="brand-dot" aria-hidden="true" /> BRACKET CRAFT</NuxtLink>
        <div class="detail-actions">
          <span v-if="realtimeStatusLabel" class="realtime-status" :class="`realtime-${realtime.status.value}`" role="status">{{ realtimeStatusLabel }}</span>
  <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="realtime.retry()">{{ t('common.retry') }}</button>
          <NuxtLink to="/login" class="button-secondary">{{ t('common.login') }}</NuxtLink>
        </div>
    </header>

    <Transition name="content-fade" mode="out-in">
      <div v-if="loading" key="loading" class="container empty-state loading-state" role="status">
         <span class="loading-orb" aria-hidden="true" /> {{ t('common.loading') }} {{ t('public.tournament').toLowerCase() }}...
      </div>
      <div v-else-if="error" key="error" class="container empty-state" role="alert">
        <span>{{ error }}</span>
        <Button variant="secondary" class="button-secondary" type="button" @click="refreshPublicData">{{ refreshing ? t('common.loading') : t('common.retry') }}</Button>
      </div>
      <div v-else-if="tournament" key="tournament" class="tournament-content">
        <section class="container tournament-hero">
          <div>
             <p class="eyebrow">{{ t('public.publicCompetition') }} · {{ statusLabel(tournament.status) }}</p>
            <h1>{{ tournament.name }}</h1>
             <p class="tournament-meta">{{ tournament.season }} · {{ t('public.starts') }} {{ tournament.start_date }}</p>
           </div>
           <div class="hero-stamp">{{ t('public.openScoreboard') }}</div>
        </section>

        <section v-if="tournament.teams?.length" class="container public-teams">
          <Surface class="panel">
            <div class="panel-heading">
              <div>
                <p class="eyebrow">{{ t('public.teamsCount', { count: tournament.teams.length }) }}</p>
                <h2>{{ t('setup.teams') }}</h2>
              </div>
            </div>
            <ul class="public-team-list">
              <li v-for="team in tournament.teams" :key="team.team_id">
                <TeamCrest :team="team" :crest-url="team.crest_url" surface="public" />
                <span>{{ team.name }}</span>
                <small>{{ team.short_code }}</small>
              </li>
            </ul>
          </Surface>
        </section>

         <section v-if="!stageAwareLayout" class="container public-grid">
           <Surface class="panel standings-panel">
             <div class="panel-heading">
               <div>
                 <p class="eyebrow">{{ t('public.table') }}</p>
                 <h2>{{ t('public.standings') }}</h2>
               </div>
               <span class="muted">{{ t('public.teamsCount', { count: standings.length }) }}</span>
             </div>
             <div v-if="listError" class="list-error" role="alert">{{ listError }}</div>
             <div v-if="!standings.length" class="empty-state compact">{{ t('public.noStandings') }}</div>
             <div v-else class="table-scroll">
               <table>
                 <caption class="visually-hidden">{{ t('public.standings') }}</caption>
                 <thead>
                   <tr>
                     <th scope="col">#</th>
                     <th scope="col">{{ t('setup.teams') }}</th>
                     <th scope="col">{{ t('public.played') }}</th>
                     <th scope="col">{{ t('public.won') }}</th>
                     <th scope="col">{{ t('public.drawn') }}</th>
                     <th scope="col">{{ t('public.lost') }}</th>
                     <th scope="col">{{ t('public.goalsFor') }}</th>
                     <th scope="col">{{ t('public.goalsAgainst') }}</th>
                     <th scope="col">{{ t('public.goalDifference') }}</th>
                     <th scope="col">{{ t('public.points') }}</th>
                     <th scope="col">{{ t('public.fairPlayPoints') }}</th>
                   </tr>
                 </thead>
                 <tbody>
                   <tr v-for="standing in standingsRows(standings)" :key="`${standing.stage_id}:${standing.group_id}:${standing.team_id}`">
                     <td class="rank">{{ standing.rank }}</td>
                     <td>
                        <div class="standing-team">
                          <TeamCrest :team="{ name: standing.team_name, short_code: standing.short_code }" :crest-url="standing.crest_url" surface="public" />
                          <div>
                            <strong>{{ standing.team_name }}</strong>
                            <small>{{ standing.short_code }} · {{ standing.group_name || standing.stage_name }}</small>
                          </div>
                        </div>
                      </td>
                     <td>{{ standing.played }}</td>
                     <td>{{ standing.won }}</td>
                     <td>{{ standing.drawn }}</td>
                     <td>{{ standing.lost }}</td>
                     <td>{{ standing.goals_for }}</td>
                     <td>{{ standing.goals_against }}</td>
                     <td>{{ standing.goal_difference > 0 ? `+${standing.goal_difference}` : standing.goal_difference }}</td>
                     <td class="points">{{ standing.points }}</td>
                     <td>{{ standing.fair_play_points }}</td>
                   </tr>
                 </tbody>
               </table>
             </div>
             <Button variant="secondary" v-if="activeStandingsHasMore" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('standings')">
               {{ loadingMore === 'standings' ? t('common.loading') : t('public.loadMoreStandings') }}
             </Button>
           </Surface>

           <Surface class="panel matches-panel">
             <div class="panel-heading">
               <div>
                 <p class="eyebrow">{{ t('public.fixtures') }}</p>
                 <h2>{{ t('public.matches') }}</h2>
               </div>
               <span class="muted">{{ t('public.matchesCount', { count: matches.length }) }}</span>
             </div>
             <div v-if="!matches.length" class="empty-state compact">{{ t('public.noFixtures') }}</div>
             <TransitionGroup v-else name="card-list" tag="div" class="match-list">
               <article v-for="match in matches" :key="match.id" class="match-card">
                 <div class="match-context"><span>{{ match.stage_name }}</span><span>{{ match.group_name || t('public.bracket') }}</span></div>
                 <div class="match-teams">
                        <div class="match-team">
                          <TeamCrest :team="{ name: match.home_team_name || match.home_team_short_code || t('public.toDefine'), short_code: match.home_team_short_code }" :crest-url="match.home_team_crest_url" surface="public" />
                          <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
                        </div>
                        <strong>{{ formatScore(match) }}</strong>
                        <div class="match-team match-team--away">
                          <TeamCrest :team="{ name: match.away_team_name || match.away_team_short_code || t('public.toDefine'), short_code: match.away_team_short_code }" :crest-url="match.away_team_crest_url" surface="public" />
                          <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
                        </div>
                      </div>
                 <div class="match-footer"><span>{{ formatDate(match.match_date) }}</span><span>{{ statusLabel(match.status) }}</span></div>
                 <button
                   v-if="match.lineup"
                   class="lineup-trigger"
                   type="button"
                   aria-controls="public-lineup-dialog"
                   aria-haspopup="dialog"
                   :aria-expanded="selectedLineupMatchId === match.id"
                   @click="openLineup(match, $event)"
                 >
                   {{ t('public.viewLineup') }}
                 </button>
               </article>
             </TransitionGroup>
             <Button variant="secondary" v-if="activeMatchesHasMore" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('matches')">
               {{ loadingMore === 'matches' ? t('common.loading') : t('public.loadMoreMatches') }}
             </Button>
           </Surface>
         </section>

         <section v-if="stageAwareLayout" class="container phase-selector" :aria-label="t('setup.stages')">
           <button
             v-for="stage in stages"
             :key="stage.id"
             type="button"
             class="phase-chip"
             :class="{ 'phase-chip--active': stage.id === selectedStageId }"
             :aria-pressed="stage.id === selectedStageId"
             @click="selectPublicStage(stage.id)"
           >
             {{ stage.name }}
           </button>
         </section>

         <section v-if="stageAwareLayout" class="container phase-selected">
           <div v-if="listError" class="list-error" role="alert">{{ listError }}</div>
           <section v-if="selectedStage" class="panel phase-panel">
             <div class="panel-heading">
               <div>
                 <p class="eyebrow">{{ stageTypeLabel(selectedStage.stage_type) }}</p>
                 <h2>{{ selectedStage.name }}</h2>
               </div>
               <span class="muted">
                 {{ stagePresentation(selectedStage) === 'standings'
                   ? t('public.teamsCount', { count: standingsForStage(selectedStage.id).length })
                   : t('public.matchesCount', { count: matchesForStage(selectedStage.id).length }) }}
               </span>
             </div>

             <template v-if="stagePresentation(selectedStage) === 'standings'">
               <template v-if="selectedStageGroups.length">
                 <div v-for="group in selectedStageGroups" :key="group.groupId ?? 'nogroup'" class="phase-group">
                   <h3 class="phase-group-title">{{ group.groupName || t('public.group') }}</h3>
                   <div v-if="!standingsForGroup(standings, selectedStage.id, group.groupId).length" class="empty-state compact">{{ t('public.noStandings') }}</div>
                   <div v-else class="table-scroll">
                     <table>
                       <caption class="visually-hidden">{{ `${t('public.standings')} · ${group.groupName || selectedStage.name}` }}</caption>
                       <thead>
                         <tr>
                           <th scope="col">#</th>
                           <th scope="col">{{ t('setup.teams') }}</th>
                           <th scope="col">{{ t('public.played') }}</th>
                           <th scope="col">{{ t('public.won') }}</th>
                           <th scope="col">{{ t('public.drawn') }}</th>
                           <th scope="col">{{ t('public.lost') }}</th>
                           <th scope="col">{{ t('public.goalsFor') }}</th>
                           <th scope="col">{{ t('public.goalsAgainst') }}</th>
                           <th scope="col">{{ t('public.goalDifference') }}</th>
                           <th scope="col">{{ t('public.points') }}</th>
                           <th scope="col">{{ t('public.fairPlayPoints') }}</th>
                         </tr>
                       </thead>
                       <tbody>
                         <tr v-for="standing in standingsRows(standingsForGroup(standings, selectedStage.id, group.groupId))" :key="`${standing.stage_id}:${standing.group_id}:${standing.team_id}`">
                           <td class="rank">{{ standing.rank }}</td>
                           <td>
                            <div class="standing-team">
                              <TeamCrest :team="{ name: standing.team_name, short_code: standing.short_code }" :crest-url="standing.crest_url" surface="public" />
                              <div>
                                <strong>{{ standing.team_name }}</strong>
                                <small>{{ standing.short_code }}</small>
                              </div>
                            </div>
                          </td>
                           <td>{{ standing.played }}</td>
                           <td>{{ standing.won }}</td>
                           <td>{{ standing.drawn }}</td>
                           <td>{{ standing.lost }}</td>
                           <td>{{ standing.goals_for }}</td>
                           <td>{{ standing.goals_against }}</td>
                           <td>{{ standing.goal_difference > 0 ? `+${standing.goal_difference}` : standing.goal_difference }}</td>
                           <td class="points">{{ standing.points }}</td>
                           <td>{{ standing.fair_play_points }}</td>
                         </tr>
                       </tbody>
                     </table>
                   </div>
                   <Button variant="secondary" v-if="comboHasMore('standings', selectedStage.id, group.groupId)" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('standings', selectedStage.id, group.groupId)">
                     {{ loadingMore === 'standings' ? t('common.loading') : t('public.loadMoreStandings') }}
                   </Button>

                   <div class="phase-matches">
                     <div v-if="!matchesForGroup(matches, selectedStage.id, group.groupId).length" class="empty-state compact">{{ t('public.noFixtures') }}</div>
                     <TransitionGroup v-else name="card-list" tag="div" class="match-list">
                       <article v-for="match in matchesForGroup(matches, selectedStage.id, group.groupId)" :key="match.id" class="match-card">
                         <div class="match-context"><span>{{ match.stage_name }}</span><span>{{ match.group_name || t('public.bracket') }}</span></div>
                         <div class="match-teams">
                            <div class="match-team">
                              <TeamCrest :team="{ name: match.home_team_name || match.home_team_short_code || t('public.toDefine'), short_code: match.home_team_short_code }" :crest-url="match.home_team_crest_url" surface="public" />
                              <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
                            </div>
                            <strong>{{ formatScore(match) }}</strong>
                            <div class="match-team match-team--away">
                              <TeamCrest :team="{ name: match.away_team_name || match.away_team_short_code || t('public.toDefine'), short_code: match.away_team_short_code }" :crest-url="match.away_team_crest_url" surface="public" />
                              <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
                            </div>
                          </div>
                         <div class="match-footer"><span>{{ formatDate(match.match_date) }}</span><span>{{ statusLabel(match.status) }}</span><span v-if="resolutionLabel(match)">{{ resolutionLabel(match) }}</span></div>
                         <button
                           v-if="match.lineup"
                           class="lineup-trigger"
                           type="button"
                           aria-controls="public-lineup-dialog"
                           aria-haspopup="dialog"
                           :aria-expanded="selectedLineupMatchId === match.id"
                           @click="openLineup(match, $event)"
                         >
                           {{ t('public.viewLineup') }}
                         </button>
                       </article>
                     </TransitionGroup>
                    <Button variant="secondary" v-if="comboHasMore('matches', selectedStage.id, group.groupId)" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('matches', selectedStage.id, group.groupId)">
                      {{ loadingMore === 'matches' ? t('common.loading') : t('public.loadMoreMatches') }}
                    </Button>
                   </div>
                 </div>
               </template>
               <template v-else>
                 <div v-if="!standingsForStage(selectedStage.id).length" class="empty-state compact">{{ t('public.noStandings') }}</div>
                 <div v-else class="table-scroll">
                   <table>
                     <caption class="visually-hidden">{{ `${t('public.standings')} · ${selectedStage.name}` }}</caption>
                     <thead>
                       <tr>
                         <th scope="col">#</th>
                         <th scope="col">{{ t('setup.teams') }}</th>
                         <th scope="col">{{ t('public.played') }}</th>
                         <th scope="col">{{ t('public.won') }}</th>
                         <th scope="col">{{ t('public.drawn') }}</th>
                         <th scope="col">{{ t('public.lost') }}</th>
                         <th scope="col">{{ t('public.goalsFor') }}</th>
                         <th scope="col">{{ t('public.goalsAgainst') }}</th>
                         <th scope="col">{{ t('public.goalDifference') }}</th>
                         <th scope="col">{{ t('public.points') }}</th>
                         <th scope="col">{{ t('public.fairPlayPoints') }}</th>
                       </tr>
                     </thead>
                     <tbody>
                       <tr v-for="standing in standingsRows(standingsForGroup(standings, selectedStage.id, selectedGroupId))" :key="`${standing.stage_id}:${standing.group_id}:${standing.team_id}`">
                         <td class="rank">{{ standing.rank }}</td>
                         <td>
                          <div class="standing-team">
                            <TeamCrest :team="{ name: standing.team_name, short_code: standing.short_code }" :crest-url="standing.crest_url" surface="public" />
                            <div>
                              <strong>{{ standing.team_name }}</strong>
                              <small>{{ standing.short_code }} · {{ standing.group_name || standing.stage_name }}</small>
                            </div>
                          </div>
                        </td>
                         <td>{{ standing.played }}</td>
                         <td>{{ standing.won }}</td>
                         <td>{{ standing.drawn }}</td>
                         <td>{{ standing.lost }}</td>
                         <td>{{ standing.goals_for }}</td>
                         <td>{{ standing.goals_against }}</td>
                         <td>{{ standing.goal_difference > 0 ? `+${standing.goal_difference}` : standing.goal_difference }}</td>
                         <td class="points">{{ standing.points }}</td>
                         <td>{{ standing.fair_play_points }}</td>
                       </tr>
                     </tbody>
                   </table>
                 </div>

                 <div class="phase-matches">
                   <div class="panel-heading phase-subheading">
                     <div>
                       <p class="eyebrow">{{ t('public.fixtures') }}</p>
                       <h3>{{ t('public.matches') }}</h3>
                     </div>
                     <span class="muted">{{ t('public.matchesCount', { count: matchesForStage(selectedStage.id).length }) }}</span>
                   </div>
                   <div v-if="!matchesForStage(selectedStage.id).length" class="empty-state compact">{{ t('public.noFixtures') }}</div>
                   <TransitionGroup v-else name="card-list" tag="div" class="match-list">
                     <article v-for="match in matchesForGroup(matches, selectedStage.id, selectedGroupId)" :key="match.id" class="match-card">
                       <div class="match-context"><span>{{ match.stage_name }}</span><span>{{ match.group_name || t('public.bracket') }}</span></div>
                       <div class="match-teams">
                          <div class="match-team">
                            <TeamCrest :team="{ name: match.home_team_name || match.home_team_short_code || t('public.toDefine'), short_code: match.home_team_short_code }" :crest-url="match.home_team_crest_url" surface="public" />
                            <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
                          </div>
                          <strong>{{ formatScore(match) }}</strong>
                          <div class="match-team match-team--away">
                            <TeamCrest :team="{ name: match.away_team_name || match.away_team_short_code || t('public.toDefine'), short_code: match.away_team_short_code }" :crest-url="match.away_team_crest_url" surface="public" />
                            <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
                          </div>
                        </div>
                       <div class="match-footer"><span>{{ formatDate(match.match_date) }}</span><span>{{ statusLabel(match.status) }}</span><span v-if="resolutionLabel(match)">{{ resolutionLabel(match) }}</span></div>
                       <button
                         v-if="match.lineup"
                         class="lineup-trigger"
                         type="button"
                         aria-controls="public-lineup-dialog"
                         aria-haspopup="dialog"
                         :aria-expanded="selectedLineupMatchId === match.id"
                         @click="openLineup(match, $event)"
                       >
                         {{ t('public.viewLineup') }}
                       </button>
                     </article>
                   </TransitionGroup>
                 <Button variant="secondary" v-if="comboHasMore('matches', selectedStage.id, selectedGroupId)" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('matches', selectedStage.id, selectedGroupId)">
                   {{ loadingMore === 'matches' ? t('common.loading') : t('public.loadMoreMatches') }}
                 </Button>
                 </div>
               </template>
             </template>

             <template v-else-if="stagePresentation(selectedStage) === 'bracket'">
               <PublicBracket
                 :matches="matchesForGroup(matches, selectedStage.id, selectedGroupId)"
                 @open-lineup="openLineup"
               />
               <Button variant="secondary" v-if="comboHasMore('matches', selectedStage.id, selectedGroupId)" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('matches', selectedStage.id, selectedGroupId)">
                 {{ loadingMore === 'matches' ? t('common.loading') : t('public.loadMoreMatches') }}
               </Button>
             </template>

             <template v-else>
               <div v-if="!matchesForStage(selectedStage.id).length" class="empty-state compact">{{ t('public.noFixtures') }}</div>
               <TransitionGroup v-else name="card-list" tag="div" class="match-list">
                 <article v-for="match in matchesForGroup(matches, selectedStage.id, selectedGroupId)" :key="match.id" class="match-card">
                   <div class="match-context"><span>{{ match.stage_name }}</span><span>{{ match.group_name || t('public.bracket') }}</span></div>
                   <div class="match-teams">
                        <div class="match-team">
                          <TeamCrest :team="{ name: match.home_team_name || match.home_team_short_code || t('public.toDefine'), short_code: match.home_team_short_code }" :crest-url="match.home_team_crest_url" surface="public" />
                          <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
                        </div>
                        <strong>{{ formatScore(match) }}</strong>
                        <div class="match-team match-team--away">
                          <TeamCrest :team="{ name: match.away_team_name || match.away_team_short_code || t('public.toDefine'), short_code: match.away_team_short_code }" :crest-url="match.away_team_crest_url" surface="public" />
                          <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
                        </div>
                      </div>
                   <div class="match-footer"><span>{{ formatDate(match.match_date) }}</span><span>{{ statusLabel(match.status) }}</span><span v-if="resolutionLabel(match)">{{ resolutionLabel(match) }}</span></div>
                   <button
                     v-if="match.lineup"
                     class="lineup-trigger"
                     type="button"
                     aria-controls="public-lineup-dialog"
                     aria-haspopup="dialog"
                     :aria-expanded="selectedLineupMatchId === match.id"
                     @click="openLineup(match, $event)"
                   >
                     {{ t('public.viewLineup') }}
                   </button>
                 </article>
               </TransitionGroup>
               <Button variant="secondary" v-if="comboHasMore('matches', selectedStage.id, selectedGroupId)" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('matches', selectedStage.id, selectedGroupId)">
                 {{ loadingMore === 'matches' ? t('common.loading') : t('public.loadMoreMatches') }}
               </Button>
             </template>
           </section>
           <div v-else class="empty-state compact">{{ t('public.noStandings') }}</div>
         </section>
      </div>
    </Transition>
    <section v-if="tournament" class="container public-stats">
      <Surface class="panel stats-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">{{ t('public.stats') }}</p>
            <h2>{{ t('public.stats') }}</h2>
          </div>
        </div>
        <div v-if="stageAwareLayout" class="stats-scope">
          <label for="public-stats-scope">{{ t('public.statsScope') }}</label>
          <select id="public-stats-scope" :value="statsStageId ?? ''" @change="selectStatsStage(($event.target as HTMLSelectElement).value)">
            <option value="">{{ t('public.statsWholeTournament') }}</option>
            <option v-for="stage in stages" :key="stage.id" :value="stage.id">{{ stage.name }}</option>
          </select>
        </div>
        <div class="stats-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            class="stats-tab"
            :class="{ 'stats-tab--active': statsTab === 'players' }"
            :aria-selected="statsTab === 'players'"
            @click="statsTab = 'players'"
          >{{ t('public.playerStats') }}</button>
          <button
            type="button"
            role="tab"
            class="stats-tab"
            :class="{ 'stats-tab--active': statsTab === 'teams' }"
            :aria-selected="statsTab === 'teams'"
            @click="statsTab = 'teams'"
          >{{ t('public.teamStats') }}</button>
        </div>
        <PublicPlayerStatsTable v-if="statsTab === 'players'" :rows="playerStats" :has-more="playerStatsHasMore" :loading-more="statsLoadingMore === 'players'" @load-more="loadMorePlayerStats" />
        <PublicTeamStatsTable v-else :rows="teamStats" :has-more="teamStatsHasMore" :loading-more="statsLoadingMore === 'teams'" @load-more="loadMoreTeamStats" />
      </Surface>
    </section>
    <PublicLineupModal
      :open="Boolean(selectedLineupMatch)"
      :match="selectedLineupMatch"
      @close="closeLineup"
    />
  </main>
</template>

<style scoped>
/* RF-006/VI-1: título y espaciado del hero conservan su composición fluida. */
.public-shell { min-height: 100vh; padding-bottom: var(--space-10); background: radial-gradient(circle at 84% 0%, color-mix(in srgb, var(--color-accent) 8%, transparent), transparent 30rem), var(--color-canvas); }
.detail-topbar { display: flex; justify-content: space-between; align-items: center; padding: var(--space-6) 0; }
.detail-actions { display: flex; align-items: center; gap: var(--space-3); }
.realtime-status { color: var(--color-muted); font-size: var(--text-2xs); text-transform: uppercase; letter-spacing: 0.08em; }
.realtime-error, .realtime-reconnecting, .realtime-retrying { color: var(--color-warning); }
.realtime-retry { padding: 0; background: transparent; color: var(--color-accent); font-size: var(--text-2xs); text-decoration: underline; }
.brand-mark { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--color-ink); font-size: var(--text-xs); font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.brand-mark:hover { color: var(--color-accent); }
.brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 18px var(--color-accent); }
.tournament-hero { display: flex; justify-content: space-between; align-items: end; gap: var(--space-7); padding: 10vh 0 8vh; animation: rise-in 700ms var(--ease-out) both; }
.tournament-hero h1 { max-width: 850px; margin: var(--space-3) 0 var(--space-2); font-size: clamp(3.4rem, 10vw, 8.5rem); line-height: 0.88; letter-spacing: -0.09em; }
.tournament-meta, .muted { color: var(--color-muted); }
.hero-stamp { padding: var(--space-3); border: 1px solid var(--color-accent); color: var(--color-accent); font-size: var(--text-2xs); font-weight: 900; letter-spacing: 0.12em; line-height: 1.4; text-align: right; white-space: pre-line; }
.public-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr); gap: var(--space-4); }
.phase-stack { display: grid; gap: var(--space-4); }
.phase-selector { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-4); }
.phase-chip { padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-pill); background: var(--color-surface-raised); color: var(--color-ink); font-size: var(--text-sm); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer; }
.phase-chip--active { border-color: var(--color-accent); color: var(--color-accent); }
.phase-group { display: grid; gap: var(--space-3); margin-bottom: var(--space-4); }
.phase-group-title { margin: var(--space-2) 0 var(--space-1); font-size: var(--text-lg); letter-spacing: -0.03em; color: var(--color-accent); }
.panel { min-width: 0; padding: var(--space-5); border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 90%, transparent), color-mix(in srgb, var(--color-surface) 94%, transparent)); box-shadow: 0 18px 50px color-mix(in srgb, var(--color-shadow) 14%, transparent); }
.phase-panel { animation: rise-in 500ms var(--ease-out) both; }
.panel-heading { display: flex; justify-content: space-between; align-items: end; gap: var(--space-4); margin-bottom: var(--space-5); }
.panel-heading h2 { margin: var(--space-2) 0 0; font-size: var(--text-xl); letter-spacing: -0.06em; }
.phase-subheading { margin-top: var(--space-6); margin-bottom: var(--space-3); }
.phase-subheading h3 { margin: var(--space-1) 0 0; font-size: var(--text-lg); letter-spacing: -0.04em; }
.eyebrow { margin: 0; color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
.table-scroll { overflow-x: auto; }
.standing-team { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.public-team-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.public-team-list li { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid color-mix(in srgb, var(--color-muted) 15%, transparent); border-radius: var(--radius-md); }
.public-team-list small { color: var(--color-muted); font-size: var(--text-2xs); }
table { width: 100%; border-collapse: collapse; min-width: 760px; }
th { color: var(--color-muted); font-size: var(--text-2xs); font-weight: 700; letter-spacing: 0.1em; text-align: left; text-transform: uppercase; }
th, td { padding: var(--space-3) var(--space-2); border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); }
tbody tr { transition: background-color 180ms ease, transform 180ms var(--ease-out); }
tbody tr:hover { background: color-mix(in srgb, var(--color-accent) 5%, transparent); transform: translateX(3px); }
td { font-size: var(--text-md); }
td small { display: block; margin-top: var(--space-1); color: var(--color-muted); font-size: var(--text-xs); }
.rank, .points { color: var(--color-accent); font-weight: 800; }
.match-list { position: relative; display: grid; gap: var(--space-3); }
.match-card { padding: var(--space-4); border: 1px solid color-mix(in srgb, var(--color-muted) 15%, transparent); border-radius: var(--radius-md); background: var(--color-surface-raised); }
.match-card:hover { border-color: color-mix(in srgb, var(--color-accent) 42%, transparent); transform: translateY(-3px); }
.match-context, .match-footer { display: flex; justify-content: space-between; gap: var(--space-3); color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.08em; text-transform: uppercase; }
.match-teams { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: var(--space-3); padding: var(--space-5) 0; font-size: var(--text-md); }
.match-team { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.match-team--away { justify-content: flex-end; text-align: right; }
.match-teams strong { color: var(--color-accent); font-size: var(--text-lg); }
.lineup-trigger { display: block; width: 100%; margin-top: var(--space-3); padding: var(--space-3) 0 0; border-top: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); background: transparent; color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; }
.lineup-trigger:hover { color: var(--color-ink); }
.empty-state { padding: var(--space-6); border: 1px dashed var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); }
.loading-state { display: flex; align-items: center; gap: var(--space-3); }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 18px var(--color-accent); animation: pulse 1s ease-in-out infinite; }
.empty-state.compact { padding: var(--space-5); }
.list-error { margin-bottom: var(--space-3); color: var(--color-danger); font-size: var(--text-sm); }
.load-more { display: block; margin: var(--space-4) auto 0; }
.stats-scope { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin: 0 0 var(--space-4); }
.stats-scope label { color: var(--color-muted); font-size: var(--text-sm); }
.stats-scope select { min-width: 0; max-width: 100%; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); font: inherit; }
.stats-scope select:hover { border-color: var(--color-muted); }
.stats-scope select:focus { border-color: var(--color-accent); box-shadow: 0 0 0 4px var(--accent-glow); }
@media (max-width: 1000px) {
  .public-grid { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .container { width: min(100% - 28px, 620px); }
  .tournament-hero { align-items: start; flex-direction: column; padding-top: 8vh; }
  .hero-stamp { align-self: end; }
}
@media (max-width: 480px) {
  .match-teams { grid-template-columns: 1fr; gap: var(--space-2); text-align: center; }
  .match-team--away { justify-content: center; text-align: center; }
}

.stats-panel { min-width: 0; }
.stats-tabs { display: flex; gap: var(--space-2); margin: 0 0 var(--space-4); border-bottom: 1px solid var(--color-line); padding-bottom: var(--space-2); }
.stats-tab { padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-pill); background: var(--color-surface-raised); color: var(--color-ink); font-size: var(--text-sm); font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; cursor: pointer; }
.stats-tab--active { border-color: var(--color-accent); color: var(--color-accent); }
</style>