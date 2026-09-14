<script setup lang="ts">
import { nextTick } from 'vue';
import type { FormationCode } from '~/constants/formations';
import { useRealtime } from '~/composables/useRealtime';

interface PublicTournament {
  id: string;
  name: string;
  season: string;
  start_date: string;
  status: string;
}

interface PublicStanding {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  group_id: string | null;
  group_name: string | null;
  team_id: string;
  team_name: string;
  short_code: string;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
  fair_play_points: number;
  rank: number;
}

interface PublicMatch {
  id: string;
  stage_name: string;
  group_name: string | null;
  matchday: number | null;
  match_date: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  status: string;
  resolution_type: string | null;
  lineup: PublicMatchLineup | null;
}

interface PublicLineupPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number | null;
  role: 'starter' | 'substitute';
  position_slot: string | null;
  photo_url: string | null;
}

interface PublicTeamLineup {
  team_id: string;
  team_name: string;
  formation_code: FormationCode | null;
  starters: PublicLineupPlayer[];
  substitutes: PublicLineupPlayer[];
}

interface PublicMatchLineup {
  home: PublicTeamLineup | null;
  away: PublicTeamLineup | null;
}

const route = useRoute();
const { request } = useApi();
const { t, statusLabel, dateLocale, errorMessage } = useI18n();
const realtime = useRealtime();
const tournamentId = String(route.params.id);
const PAGE_SIZE = 50;
const PUBLIC_REFRESH_INTERVAL_MS = 30_000;

interface PublicTournamentData {
  tournament: PublicTournament;
  standings: PublicStanding[];
  matches: PublicMatch[];
}

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

const { data, status, error: dataError, refresh } = await useAsyncData<PublicTournamentData>(
  `public-tournament-${tournamentId}`,
  async () => {
    const [tournament, standings, matches] = await Promise.all([
      request<PublicTournament>(`/tournaments/public/${tournamentId}`),
      request<PublicStanding[]>(`/tournaments/public/${tournamentId}/standings?limit=${PAGE_SIZE}&offset=0`),
      request<PublicMatch[]>(`/tournaments/public/${tournamentId}/matches?limit=${PAGE_SIZE}&offset=0`),
    ]);
    return { tournament, standings, matches };
  },
);

const tournament = computed(() => data.value?.tournament ?? null);
const standings = computed(() => data.value?.standings ?? []);
const matches = computed(() => data.value?.matches ?? []);
const selectedLineupMatchId = ref<string | null>(null);
const lineupTrigger = ref<HTMLButtonElement | null>(null);
const selectedLineupMatch = computed(() => matches.value.find((match) => match.id === selectedLineupMatchId.value) ?? null);
const loading = computed(() => status.value === 'pending');
const error = computed(() => dataError.value ? failureMessage(dataError.value, t('public.noLoad')) : null);
const standingsHasMore = ref(Boolean(data.value?.standings.length === PAGE_SIZE));
const matchesHasMore = ref(Boolean(data.value?.matches.length === PAGE_SIZE));
const loadingMore = ref<'standings' | 'matches' | null>(null);
const refreshing = ref(false);
const listError = ref<string | null>(null);
let refreshGeneration = 0;
let publicRefreshTimer: number | null = null;

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
  return new Intl.DateTimeFormat(dateLocale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
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

async function refreshPublicData() {
  if (refreshing.value || loadingMore.value) return;
  const generation = ++refreshGeneration;
  refreshing.value = true;
  listError.value = null;
  try {
    await refresh();
    if (generation === refreshGeneration && data.value) {
      standingsHasMore.value = data.value.standings.length === PAGE_SIZE;
      matchesHasMore.value = data.value.matches.length === PAGE_SIZE;
    }
  } catch (cause) {
    if (generation === refreshGeneration) listError.value = failureMessage(cause, t('public.noLoad'));
  } finally {
    if (generation === refreshGeneration) refreshing.value = false;
  }
}

async function loadMore(kind: 'standings' | 'matches') {
  if (loadingMore.value || refreshing.value || !data.value) return;
  const currentLength = data.value[kind].length;
  const hasMore = kind === 'standings' ? standingsHasMore.value : matchesHasMore.value;
  if (!hasMore) return;
  const generation = ++refreshGeneration;
  loadingMore.value = kind;
  try {
    const path = kind === 'standings' ? 'standings' : 'matches';
    const page = await request<PublicStanding[] | PublicMatch[]>(
      `/tournaments/public/${tournamentId}/${path}?limit=${PAGE_SIZE}&offset=${currentLength}`,
    );
    if (generation !== refreshGeneration || !data.value) return;
    if (kind === 'standings') {
      data.value = { ...data.value, standings: [...data.value.standings, ...(page as PublicStanding[])] };
      standingsHasMore.value = page.length === PAGE_SIZE;
    } else {
      data.value = { ...data.value, matches: [...data.value.matches, ...(page as PublicMatch[])] };
      matchesHasMore.value = page.length === PAGE_SIZE;
    }
  } catch (cause) {
    if (generation === refreshGeneration) listError.value = failureMessage(cause, t('public.noLoad'));
  } finally {
    if (generation === refreshGeneration) loadingMore.value = null;
  }
}

const realtimeStatusLabel = computed(() => {
  if (realtime.status.value === 'connected') return t('public.realtimeConnected');
  if (realtime.status.value === 'reconnecting') return t('public.realtimeReconnecting');
  if (realtime.status.value === 'error') return t('public.realtimeError');
  return '';
});

function onRealtimeEvent(event: string, payload: unknown) {
  if (!['MATCH_CLOSED', 'MATCH_UPDATED', 'STANDINGS_UPDATED'].includes(event)) return;
  if (payloadTargetsTournament(payload)) void refreshPublicData();
}

onMounted(() => {
  realtime.connect({ onEvent: onRealtimeEvent }, { tournamentId });
  publicRefreshTimer = window.setInterval(() => {
    if (realtime.status.value !== 'connected') void refreshPublicData();
  }, PUBLIC_REFRESH_INTERVAL_MS);
});
onBeforeUnmount(() => {
  if (publicRefreshTimer !== null) window.clearInterval(publicRefreshTimer);
  realtime.disconnect();
});

</script>

<template>
  <main id="main-content" class="public-shell">
     <header class="container detail-topbar">
       <NuxtLink to="/" class="brand-mark"><span class="brand-dot" aria-hidden="true" /> BRACKET CRAFT</NuxtLink>
        <div class="detail-actions">
          <span v-if="realtimeStatusLabel" class="realtime-status" :class="`realtime-${realtime.status.value}`" role="status">{{ realtimeStatusLabel }}</span>
  <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="realtime.connect({ onEvent: onRealtimeEvent }, { tournamentId })">{{ t('common.retry') }}</button>
          <NuxtLink to="/login" class="button-secondary">{{ t('common.login') }}</NuxtLink>
        </div>
    </header>

    <Transition name="content-fade" mode="out-in">
      <div v-if="loading" key="loading" class="container empty-state loading-state" role="status">
         <span class="loading-orb" aria-hidden="true" /> {{ t('common.loading') }} {{ t('public.tournament').toLowerCase() }}...
      </div>
      <div v-else-if="error" key="error" class="container empty-state" role="alert">
        <span>{{ error }}</span>
        <button class="button-secondary" type="button" @click="refreshPublicData">{{ refreshing ? t('common.loading') : t('common.retry') }}</button>
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

        <section class="container public-grid">
          <div class="panel standings-panel">
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
                      <th scope="col">{{ t('public.goalDifference') }}</th>
                      <th scope="col">{{ t('public.points') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="standing in standings" :key="`${standing.stage_id}:${standing.group_id}:${standing.team_id}`">
                    <td class="rank">{{ standing.rank }}</td>
                    <td><strong>{{ standing.team_name }}</strong><small>{{ standing.short_code }} · {{ standing.group_name || standing.stage_name }}</small></td>
                    <td>{{ standing.played }}</td>
                    <td>{{ standing.goal_difference > 0 ? `+${standing.goal_difference}` : standing.goal_difference }}</td>
                    <td class="points">{{ standing.points }}</td>
                  </tr>
                </tbody>
               </table>
             </div>
             <button v-if="standingsHasMore" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('standings')">
               {{ loadingMore === 'standings' ? t('common.loading') : t('public.loadMoreStandings') }}
             </button>
          </div>

          <div class="panel matches-panel">
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
                    <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
                    <strong>{{ formatScore(match) }}</strong>
                    <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
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
             <button v-if="matchesHasMore" class="button-secondary load-more" type="button" :disabled="loadingMore !== null" @click="loadMore('matches')">
               {{ loadingMore === 'matches' ? t('common.loading') : t('public.loadMoreMatches') }}
             </button>
           </div>
        </section>
     </div>
    </Transition>
    <PublicLineupModal
      :open="Boolean(selectedLineupMatch)"
      :match="selectedLineupMatch"
      @close="closeLineup"
    />
  </main>
</template>

<style scoped>
.public-shell { min-height: 100vh; padding-bottom: 80px; background: radial-gradient(circle at 84% 0%, rgba(212, 243, 106, 0.08), transparent 30rem), #0c0f0c; }
.detail-topbar { display: flex; justify-content: space-between; align-items: center; padding: 24px 0; }
.detail-actions { display: flex; align-items: center; gap: 12px; }
.realtime-status { color: var(--muted); font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em; }
.realtime-error, .realtime-reconnecting { color: #ffcb7a; }
.realtime-retry { padding: 0; background: transparent; color: var(--accent); font-size: 0.68rem; text-decoration: underline; }
.brand-mark { display: inline-flex; align-items: center; gap: 9px; color: var(--ink); font-size: 0.78rem; font-weight: 900; letter-spacing: 0.16em; text-decoration: none; }
.brand-mark:hover { color: var(--accent); }
.brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); }
.tournament-hero { display: flex; justify-content: space-between; align-items: end; gap: 32px; padding: 10vh 0 8vh; animation: rise-in 700ms var(--ease-out) both; }
.tournament-hero h1 { max-width: 850px; margin: 14px 0 8px; font-size: clamp(3.4rem, 10vw, 8.5rem); line-height: 0.88; letter-spacing: -0.09em; }
.tournament-meta, .muted { color: var(--muted); }
.hero-stamp { padding: 14px; border: 1px solid var(--accent); color: var(--accent); font-size: 0.7rem; font-weight: 900; letter-spacing: 0.12em; line-height: 1.4; text-align: right; white-space: pre-line; }
.public-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr); gap: 18px; }
.panel { min-width: 0; padding: 22px; border: 1px solid var(--line); border-radius: 22px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.9), rgba(21, 24, 20, 0.94)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.14); }
.panel-heading { display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-bottom: 20px; }
.panel-heading h2 { margin: 7px 0 0; font-size: 2rem; letter-spacing: -0.06em; }
.eyebrow { margin: 0; color: var(--accent); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; min-width: 430px; }
th { color: var(--muted); font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em; text-align: left; text-transform: uppercase; }
th, td { padding: 13px 8px; border-bottom: 1px solid rgba(166, 170, 159, 0.14); }
tbody tr { transition: background-color 180ms ease, transform 180ms var(--ease-out); }
tbody tr:hover { background: rgba(212, 243, 106, 0.05); transform: translateX(3px); }
td { font-size: 0.9rem; }
td small { display: block; margin-top: 4px; color: var(--muted); font-size: 0.72rem; }
.rank, .points { color: var(--accent); font-weight: 800; }
.match-list { position: relative; display: grid; gap: 12px; }
.match-card { padding: 15px; border: 1px solid rgba(166, 170, 159, 0.15); border-radius: 15px; background: var(--surface-raised); }
.match-card:hover { border-color: rgba(212, 243, 106, 0.42); transform: translateY(-3px); }
.match-context, .match-footer { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase; }
.match-teams { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; padding: 22px 0; font-size: 0.9rem; }
.match-teams span:last-child { text-align: right; }
.match-teams strong { color: var(--accent); font-size: 1.2rem; }
.lineup-trigger { display: block; width: 100%; margin-top: 14px; padding: 13px 0 0; border-top: 1px solid rgba(166, 170, 159, 0.14); background: transparent; color: var(--accent); font-size: 0.7rem; font-weight: 800; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; }
.lineup-trigger:hover { color: var(--ink); }
.empty-state { padding: 28px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
.empty-state.compact { padding: 20px; }
.list-error { margin-bottom: 12px; color: var(--danger); font-size: 0.8rem; }
.load-more { display: block; margin: 16px auto 0; }
@media (max-width: 900px) {
  .public-grid { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .container { width: min(100% - 28px, 620px); }
  .tournament-hero { align-items: start; flex-direction: column; padding-top: 8vh; }
  .hero-stamp { align-self: end; }
}
@media (max-width: 375px) {
  .detail-topbar, .detail-actions { align-items: stretch; flex-direction: column; }
  .detail-actions > * { justify-content: center; text-align: center; }
  .match-teams { grid-template-columns: 1fr; gap: 7px; text-align: center; }
  .match-teams span:last-child { text-align: center; }
}
</style>
