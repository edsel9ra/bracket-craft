<script setup lang="ts">
import FormField from '~/components/ui/FormField.vue';
import type { StageFormat } from '~/constants/stageFormats';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';

// Sección con dirección propia del calendario del torneo (spec 012, RF-016).
// Aquí viven la creación de partidos, el sorteo/regeneración con sus
// confirmaciones y el listado con enlace a operación, reutilizando el mismo
// contrato que ya existía (RF-018, RF-023, RF-024).
definePageMeta({ middleware: 'auth' });

interface VersionSummary {
  id: string;
  version_number: number;
  status: string;
}

interface StageSummary {
  id: string;
  tournament_version_id: string;
  name: string;
  stage_type: StageFormat;
  stage_order: number;
  version_status: string;
}

interface TeamSummary {
  team_id: string;
  name: string;
  short_code: string;
  status: string;
  stage_ids: string[];
}

interface MatchSummary {
  id: string;
  tournament_version_id: string;
  stage_id: string;
  bracket_code: string | null;
  home_team_id: string | null;
  away_team_id: string | null;
  matchday: number | null;
  match_date: string | null;
  home_team_name: string | null;
  away_team_name: string | null;
  status: string;
  home_score: number | null;
  away_score: number | null;
}

interface ScheduleGenerationResponse {
  version_id: string;
  stage_id: string;
  stage_type: StageFormat;
  seed: number;
  bracket_size: number | null;
  round_count: number;
  match_count: number;
  bye_count: number;
  group_count: number;
  round_number: number | null;
}

interface CalendarData {
  versions: VersionSummary[];
  stages: StageSummary[];
  teams: TeamSummary[];
  matches: MatchSummary[];
}

const route = useRoute();
const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const { request } = useApi();
const { t, statusLabel, formatDateTime, errorMessage } = useI18n();
const tournamentId = String(route.params.id);
const tournamentName = computed(
  () => tournamentsStore.tournaments.find((tournament) => tournament.id === tournamentId)?.name || null,
);
const tournamentLabel = computed(() => tournamentName.value || t('shell.tournament'));

const versions = ref<VersionSummary[]>([]);
const stages = ref<StageSummary[]>([]);
const teams = ref<TeamSummary[]>([]);
const matches = ref<MatchSummary[]>([]);
const loading = ref(true);
const saving = ref(false);
const loadError = ref<string | null>(null);
const error = ref<string | null>(null);
const selectedVersionId = ref('');
const selectedStageId = ref('');
const matchForm = reactive({ home_team_id: '', away_team_id: '', matchday: 1, match_date: '' });
const matchFormTouched = ref(false);
const matchdayError = computed(() => matchFormTouched.value && (!matchForm.matchday || matchForm.matchday < 1) ? t('validation.required') : null);
const matchDateError = computed(() => matchFormTouched.value && !matchForm.match_date ? t('validation.required') : null);
const scheduleForm = reactive({
  start_date: '',
  round_interval_days: 7,
  match_interval_hours: 2,
  seed: '',
  legs: 2 as 1 | 2,
  group_count: 2,
  use_group_heads: false,
  head_team_ids: [] as string[],
  swiss_rounds: 8,
  swiss_round: 1,
  swiss_home_target: 4,
  swiss_away_target: 4,
});
const scheduleBusy = ref(false);
const scheduleResult = ref<ScheduleGenerationResponse | null>(null);
const CONFIG_PAGE_SIZE = 200;

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

const activeVersion = computed(() => versions.value.find((version) => version.id === selectedVersionId.value));
const selectedVersionStages = computed(() => stages.value.filter((stage) => stage.tournament_version_id === selectedVersionId.value));
const selectedVersionMatches = computed(() => matches.value.filter((match) => match.tournament_version_id === selectedVersionId.value));
const selectedStage = computed(() => selectedVersionStages.value.find((stage) => stage.id === selectedStageId.value));
const selectedStageTeams = computed(() => teams.value.filter((team) => team.stage_ids.includes(selectedStageId.value)));
const visibleStageMatches = computed(() => selectedVersionMatches.value.filter(
  (match) => match.stage_id === selectedStageId.value && match.status !== 'cancelled',
));
const availableAwayTeams = computed(() => selectedStageTeams.value.filter((team) => team.team_id !== matchForm.home_team_id));
const canManageTournaments = computed(() => auth.hasPermission('MANAGE_TOURNAMENTS'));
const canGenerateSchedule = computed(() => Boolean(
  canManageTournaments.value
  && selectedStage.value
  && selectedStageTeams.value.length >= 2
  && (selectedStage.value.stage_type !== 'swiss'
    || (scheduleForm.swiss_round >= 1 && scheduleForm.swiss_round <= scheduleForm.swiss_rounds))
  && (
    activeVersion.value?.status === 'draft'
    || (selectedStage.value.stage_type === 'swiss'
      && activeVersion.value?.status === 'published'
      && scheduleForm.swiss_round > 1)
  )
));

watch(() => matchForm.home_team_id, (homeTeamId) => {
  if (homeTeamId && matchForm.away_team_id === homeTeamId) matchForm.away_team_id = '';
});

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

function formatMatchDate(value: string | null): string {
  if (!value) return t('public.dateToDefine');
  return formatDateTime(value);
}

async function redirectOnSessionFailure(cause: unknown): Promise<boolean> {
  if (isUnauthorized(cause) || isNotFound(cause)) {
    await auth.logout();
    await navigateTo({ path: '/login', query: { redirect: safeInternalRedirect(route.fullPath, '/workspace') } });
    return true;
  }
  if (isForbidden(cause)) {
    await navigateTo({ path: '/forbidden', query: { returnTo: safeInternalRedirect(route.fullPath, '/workspace'), resource: 'tournament' } });
    return true;
  }
  return false;
}

async function fetchPaged<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  let offset = 0;
  while (true) {
    const page = await request<T[]>(`${path}?limit=${CONFIG_PAGE_SIZE}&offset=${offset}`);
    rows.push(...page);
    if (page.length < CONFIG_PAGE_SIZE) return rows;
    offset += page.length;
  }
}

async function fetchCalendar(): Promise<CalendarData> {
  const [versions, stages, teams, matches] = await Promise.all([
    fetchPaged<VersionSummary>(`/tournaments/${tournamentId}/versions`),
    fetchPaged<StageSummary>(`/tournaments/${tournamentId}/stages`),
    fetchPaged<TeamSummary>(`/tournaments/${tournamentId}/teams`),
    fetchPaged<MatchSummary>(`/tournaments/${tournamentId}/matches`),
  ]);

  return { versions, stages, teams, matches };
}

function stageFromQuery(versionStages: StageSummary[]): string {
  const requested = typeof route.query.stage === 'string' ? route.query.stage : '';
  return versionStages.some((stage) => stage.id === requested) ? requested : '';
}

function syncSwissForm(stage: StageSummary | undefined, allMatches: MatchSummary[]) {
  if (stage?.stage_type !== 'swiss') return;
  const swissMatches = allMatches.filter((match) => match.tournament_version_id === selectedVersionId.value
    && match.stage_id === stage.id
    && match.bracket_code?.startsWith('SW'));
  const configuredRounds = swissMatches.reduce((highest, match) => Math.max(highest, match.matchday || 0), 0);
  const highestGeneratedRound = swissMatches
    .filter((match) => match.status !== 'cancelled')
    .reduce((highest, match) => Math.max(highest, match.matchday || 0), 0);
  if (configuredRounds > 0 && !scheduleResult.value) {
    scheduleForm.swiss_rounds = configuredRounds;
    scheduleForm.swiss_home_target = Math.floor(configuredRounds / 2);
    scheduleForm.swiss_away_target = configuredRounds - scheduleForm.swiss_home_target;
  }
  if (highestGeneratedRound > 0) {
    scheduleForm.swiss_round = Math.min(highestGeneratedRound + 1, scheduleForm.swiss_rounds + 1);
  }
}

function applyCalendar(configuration: CalendarData) {
  versions.value = configuration.versions;
  stages.value = configuration.stages;
  teams.value = configuration.teams;
  matches.value = configuration.matches;
  if (!selectedVersionId.value || !configuration.versions.some((version) => version.id === selectedVersionId.value)) {
    selectedVersionId.value = configuration.versions.find((version) => version.status === 'draft')?.id
      || configuration.versions[0]?.id
      || '';
  }
  const versionStages = configuration.stages.filter((stage) => stage.tournament_version_id === selectedVersionId.value);
  if (!selectedStageId.value || !versionStages.some((stage) => stage.id === selectedStageId.value)) {
    selectedStageId.value = stageFromQuery(versionStages) || versionStages[0]?.id || '';
  }
  syncSwissForm(versionStages.find((stage) => stage.id === selectedStageId.value), configuration.matches);
}

async function loadCalendar() {
  applyCalendar(await fetchCalendar());
}

async function retryCalendar() {
  loading.value = true;
  loadError.value = null;
  try {
    await loadCalendar();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) loadError.value = failureMessage(cause, t('setup.loading'));
  } finally {
    loading.value = false;
  }
}

watch(selectedVersionId, (versionId) => {
  const nextStages = stages.value.filter((stage) => stage.tournament_version_id === versionId);
  if (!nextStages.some((stage) => stage.id === selectedStageId.value)) {
    selectedStageId.value = stageFromQuery(nextStages) || nextStages[0]?.id || '';
  }
  syncSwissForm(nextStages.find((stage) => stage.id === selectedStageId.value), matches.value);
});

function selectStage(stageId: string) {
  selectedStageId.value = stageId;
  syncStageQuery();
}

// RF-016: la fase elegida sobrevive a una recarga sin llenar el historial.
function syncStageQuery() {
  if (!import.meta.client || !selectedStageId.value) return;
  if (route.query.stage === selectedStageId.value) return;
  void navigateTo({ query: { ...route.query, stage: selectedStageId.value } }, { replace: true });
}

async function createMatch() {
  if (!selectedStageId.value || !selectedVersionId.value) return;
  matchFormTouched.value = true;
  if (matchdayError.value || matchDateError.value) return;
  if (!matchForm.match_date) {
    error.value = t('setup.matchDateRequired');
    return;
  }
  saving.value = true;
  error.value = null;
  try {
    await request(`/tournaments/${tournamentId}/matches`, {
      method: 'POST',
      body: {
        version_id: selectedVersionId.value,
        stage_id: selectedStageId.value,
        home_team_id: matchForm.home_team_id || null,
        away_team_id: matchForm.away_team_id || null,
        matchday: matchForm.matchday,
        match_date: new Date(matchForm.match_date).toISOString(),
      },
    });
    matchForm.home_team_id = '';
    matchForm.away_team_id = '';
    matchForm.match_date = '';
    await loadCalendar();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    error.value = failureMessage(cause, t('setup.noMatch'));
  } finally {
    saving.value = false;
  }
}

async function drawStageSchedule() {
  if (!selectedStageId.value || !selectedVersionId.value) return;
  if (!scheduleForm.start_date) {
    error.value = t('setup.scheduleStartRequired');
    return;
  }
  if (
    !Number.isInteger(scheduleForm.round_interval_days)
    || scheduleForm.round_interval_days < 1
    || scheduleForm.round_interval_days > 365
    || !Number.isInteger(scheduleForm.match_interval_hours)
    || scheduleForm.match_interval_hours < 1
    || scheduleForm.match_interval_hours > 168
  ) {
    error.value = t('setup.scheduleIntervalsInvalid');
    return;
  }

  if ((selectedStage.value?.stage_type === 'custom_group')
    && (!Number.isInteger(scheduleForm.group_count)
      || scheduleForm.group_count < 2
      || scheduleForm.group_count > selectedStageTeams.value.length)) {
    error.value = t('setup.groupCountInvalid');
    return;
  }
  if (selectedStage.value?.stage_type === 'custom_group'
    && scheduleForm.use_group_heads
    && scheduleForm.head_team_ids.length !== scheduleForm.group_count) {
    error.value = t('setup.groupHeadsInvalid');
    return;
  }
  if (selectedStage.value?.stage_type === 'swiss') {
    if (!Number.isInteger(scheduleForm.swiss_rounds) || scheduleForm.swiss_rounds < 1 || scheduleForm.swiss_rounds > 64
      || !Number.isInteger(scheduleForm.swiss_round) || scheduleForm.swiss_round < 1 || scheduleForm.swiss_round > scheduleForm.swiss_rounds) {
      error.value = t('setup.swissRoundsInvalid');
      return;
    }
    if (scheduleForm.swiss_home_target + scheduleForm.swiss_away_target !== scheduleForm.swiss_rounds) {
      error.value = t('setup.swissHomeAwayInvalid');
      return;
    }
  }

  const seed = scheduleForm.seed.trim() ? Number(scheduleForm.seed) : null;
  if (seed !== null && (!Number.isSafeInteger(seed) || seed < 0)) {
    error.value = t('setup.scheduleSeedInvalid');
    return;
  }

  const replaceExisting = selectedStage.value?.stage_type === 'swiss'
    ? scheduleForm.swiss_round === 1 && visibleStageMatches.value.length > 0
    : visibleStageMatches.value.length > 0;
  if (replaceExisting && import.meta.client && !window.confirm(t('setup.confirmRegenerateSchedule'))) return;

  scheduleBusy.value = true;
  error.value = null;
  scheduleResult.value = null;
  try {
    const result = await request<ScheduleGenerationResponse>(`/tournaments/${tournamentId}/matches/draw`, {
      method: 'POST',
      body: {
        version_id: selectedVersionId.value,
        stage_id: selectedStageId.value,
        start_date: new Date(scheduleForm.start_date).toISOString(),
        round_interval_days: scheduleForm.round_interval_days,
        match_interval_hours: scheduleForm.match_interval_hours,
        seed,
        replace_existing: replaceExisting,
        legs: scheduleForm.legs,
        group_count: selectedStage.value?.stage_type === 'custom_group' ? scheduleForm.group_count : null,
        use_group_heads: scheduleForm.use_group_heads,
        head_team_ids: scheduleForm.head_team_ids,
        swiss_rounds: scheduleForm.swiss_rounds,
        swiss_round: scheduleForm.swiss_round,
        swiss_home_target: selectedStage.value?.stage_type === 'swiss' ? scheduleForm.swiss_home_target : null,
        swiss_away_target: selectedStage.value?.stage_type === 'swiss' ? scheduleForm.swiss_away_target : null,
      },
    });
    scheduleResult.value = result;
    if (result.stage_type === 'swiss' && result.round_number && result.round_number < scheduleForm.swiss_rounds) {
      scheduleForm.swiss_round = result.round_number + 1;
    }
    await loadCalendar();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    error.value = failureMessage(cause, t('setup.noScheduleGeneration'));
  } finally {
    scheduleBusy.value = false;
  }
}

const { data: initialCalendar, error: initialCalendarError } = await useAsyncData<CalendarData>(
  `workspace-tournament-calendar-${tournamentId}-${auth.userId || 'none'}-${auth.organizationId || 'none'}-${auth.sessionVersion}`,
  fetchCalendar,
);

if (initialCalendarError.value) {
  if (!(await redirectOnSessionFailure(initialCalendarError.value))) {
    loadError.value = failureMessage(initialCalendarError.value, t('setup.loading'));
  }
} else if (initialCalendar.value) {
  applyCalendar(initialCalendar.value);
}
loading.value = false;
</script>

<template>
  <WorkspaceShell
    :breadcrumbs="[
      { label: t('shell.tournaments'), to: '/workspace' },
      { label: tournamentLabel, current: true },
    ]"
    :tournament="{ id: tournamentId, name: tournamentName }"
  >
    <main id="main-content" class="workspace-shell">
      <section class="container section-hero">
        <p class="eyebrow">{{ t('tournament.calendar.eyebrow') }}</p>
        <h1>{{ t('tournament.calendar.title') }}</h1>
        <p class="section-copy">{{ t('tournament.calendar.copy') }}</p>
      </section>

      <section class="container calendar-content">
        <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('setup.loading') }}</div>
        <div v-else-if="loadError" class="form-error" role="alert"><span>{{ loadError }}</span><button class="button-secondary" type="button" @click="retryCalendar">{{ t('common.retry') }}</button></div>
        <template v-else>
          <div class="calendar-toolbar">
            <label class="field">
              {{ t('setup.version') }}
              <select :value="selectedVersionId" @change="selectedVersionId = ($event.target as HTMLSelectElement).value">
                <option v-for="version in versions" :key="version.id" :value="version.id">
                  v{{ version.version_number }} · {{ statusLabel(version.status) }}
                </option>
              </select>
            </label>
            <label class="field">
              {{ t('setup.stage') }}
              <select :value="selectedStageId" :disabled="!selectedVersionStages.length" @change="selectStage(($event.target as HTMLSelectElement).value)">
                <option v-if="!selectedVersionStages.length" value="">{{ t('setup.selectStage') }}</option>
                <option v-for="stage in selectedVersionStages" :key="stage.id" :value="stage.id">
                  {{ stage.stage_order }}. {{ stage.name }}
                </option>
              </select>
            </label>
          </div>

          <form class="panel panel-wide" :aria-busy="saving || scheduleBusy" novalidate @submit.prevent="createMatch">
            <p class="eyebrow">{{ t('setup.calendarEyebrow') }}</p>
            <h2>{{ t('setup.scheduleMatch') }}</h2>
            <div class="match-form-grid">
              <FormField :label="t('setup.home')" for-id="match-home">
                <template #default="{ id, ariaDescribedby }">
                  <select :id="id" v-model="matchForm.home_team_id" :disabled="!canManageTournaments" :aria-describedby="ariaDescribedby">
                    <option value="">{{ t('setup.noDefine') }}</option>
                    <option v-for="team in selectedStageTeams" :key="`home-${team.team_id}`" :value="team.team_id">{{ team.name }}</option>
                  </select>
                </template>
              </FormField>
              <FormField :label="t('setup.away')" for-id="match-away">
                <template #default="{ id, ariaDescribedby }">
                  <select :id="id" v-model="matchForm.away_team_id" :disabled="!canManageTournaments" :aria-describedby="ariaDescribedby">
                    <option value="">{{ t('setup.noDefine') }}</option>
                    <option v-for="team in availableAwayTeams" :key="`away-${team.team_id}`" :value="team.team_id">{{ team.name }}</option>
                  </select>
                </template>
              </FormField>
              <FormField :label="t('setup.matchday')" for-id="match-matchday" :error="matchdayError">
                <template #default="{ id, ariaDescribedby }">
                  <input :id="id" v-model.number="matchForm.matchday" :disabled="!canManageTournaments" type="number" min="1" required :aria-describedby="ariaDescribedby" />
                </template>
              </FormField>
              <FormField :label="t('setup.matchDateTime')" for-id="match-date" :error="matchDateError">
                <template #default="{ id, ariaDescribedby }">
                  <input :id="id" v-model="matchForm.match_date" :disabled="!canManageTournaments" type="datetime-local" required :aria-describedby="ariaDescribedby" />
                </template>
              </FormField>
              <button v-if="canManageTournaments" class="button-primary match-submit" type="submit" :disabled="saving || scheduleBusy || activeVersion?.status !== 'draft' || !selectedStageId">{{ t('setup.createMatch') }}</button>
            </div>
            <div v-if="selectedStage" class="schedule-generator">
              <div class="schedule-generator-heading">
                <div><p class="eyebrow">{{ t('setup.generatorEyebrow') }}</p><h3>{{ t('setup.drawSchedule') }}</h3></div>
                <span class="muted-note">{{ t('setup.generatorDescription') }}</span>
              </div>
              <div class="schedule-generator-grid">
                <label class="field">{{ t('setup.generatorStart') }}<input v-model="scheduleForm.start_date" :disabled="!canManageTournaments" type="datetime-local" /></label>
                <label class="field">{{ t('setup.generatorRoundInterval') }}<input v-model.number="scheduleForm.round_interval_days" :disabled="!canManageTournaments" type="number" min="1" max="365" /></label>
                <label class="field">{{ t('setup.generatorMatchInterval') }}<input v-model.number="scheduleForm.match_interval_hours" :disabled="!canManageTournaments" type="number" min="1" max="168" /></label>
                <label class="field">{{ t('setup.generatorSeed') }}<input v-model="scheduleForm.seed" :disabled="!canManageTournaments" type="number" min="0" step="1" :placeholder="t('setup.generatorSeedOptional')" /></label>
              </div>
              <div v-if="selectedStage.stage_type === 'round_robin' || selectedStage.stage_type === 'custom_group'" class="schedule-generator-options">
                <label class="field">{{ t('setup.generatorLegs') }}
                  <select v-model.number="scheduleForm.legs" :disabled="!canManageTournaments">
                    <option :value="2">{{ t('setup.generatorHomeAway') }}</option>
                    <option :value="1">{{ t('setup.generatorSingleLeg') }}</option>
                  </select>
                </label>
                <label v-if="selectedStage.stage_type === 'custom_group'">{{ t('setup.groupCount') }}<input v-model.number="scheduleForm.group_count" :disabled="!canManageTournaments" type="number" min="2" :max="selectedStageTeams.length" /></label>
              </div>
              <div v-if="selectedStage.stage_type === 'custom_group'" class="group-head-options">
                <label class="checkbox-label"><input v-model="scheduleForm.use_group_heads" :disabled="!canManageTournaments" type="checkbox" /> {{ t('setup.useGroupHeads') }}</label>
                <div v-if="scheduleForm.use_group_heads" class="team-head-picker">
                  <span class="field-hint">{{ t('setup.selectGroupHeads', { count: scheduleForm.group_count }) }}</span>
                  <label v-for="team in selectedStageTeams" :key="`head-${team.team_id}`" class="checkbox-label">
                    <input v-model="scheduleForm.head_team_ids" :disabled="!canManageTournaments" type="checkbox" :value="team.team_id" />
                    {{ team.name }}
                  </label>
                </div>
              </div>
              <div v-if="selectedStage.stage_type === 'swiss'" class="schedule-generator-options">
                <label class="field">{{ t('setup.swissRounds') }}<input v-model.number="scheduleForm.swiss_rounds" :disabled="!canManageTournaments" type="number" min="1" max="64" /></label>
                <label class="field">{{ t('setup.swissRound') }}<input v-model.number="scheduleForm.swiss_round" :disabled="!canManageTournaments" type="number" min="1" :max="scheduleForm.swiss_rounds" /></label>
                <label class="field">{{ t('setup.swissHomeTarget') }}<input v-model.number="scheduleForm.swiss_home_target" :disabled="!canManageTournaments" type="number" min="0" :max="scheduleForm.swiss_rounds" /></label>
                <label class="field">{{ t('setup.swissAwayTarget') }}<input v-model.number="scheduleForm.swiss_away_target" :disabled="!canManageTournaments" type="number" min="0" :max="scheduleForm.swiss_rounds" /></label>
              </div>
              <p class="field-hint">{{ t('setup.generatorHint') }}</p>
              <div class="schedule-generator-actions">
                <button v-if="canManageTournaments" class="button-secondary" type="button" :disabled="scheduleBusy || saving || !canGenerateSchedule || !scheduleForm.start_date" @click="drawStageSchedule">
                  {{ scheduleBusy ? t('setup.generatingSchedule') : selectedStage.stage_type === 'swiss' && scheduleForm.swiss_round > 1 ? t('setup.drawNextSwissRound') : visibleStageMatches.length ? t('setup.regenerateSchedule') : t('setup.generateSchedule') }}
                </button>
                <span v-if="selectedStageTeams.length < 2" class="muted-note">{{ t('setup.generatorNeedsTeams') }}</span>
              </div>
              <p v-if="scheduleResult" class="schedule-result" role="status">
                {{ t('setup.scheduleGenerated', { matches: scheduleResult.match_count, rounds: scheduleResult.round_count, byes: scheduleResult.bye_count }) }}
                <code>{{ scheduleResult.seed }}</code>
              </p>
            </div>
            <TransitionGroup id="operacion" name="card-list" tag="ul" class="resource-list match-list">
              <li v-for="match in visibleStageMatches" :key="match.id"><NuxtLink :to="`/workspace/matches/${match.id}`"><span><strong v-if="match.bracket_code">{{ match.bracket_code }} · </strong>{{ match.home_team_name || t('setup.noDefine') }} vs {{ match.away_team_name || t('setup.noDefine') }}</span><small>{{ formatMatchDate(match.match_date) }} · {{ t('public.matchday', { value: match.matchday || '-' }) }} · {{ statusLabel(match.status) }}</small></NuxtLink></li>
            </TransitionGroup>
          </form>
          <div v-if="error" class="form-error" role="alert">{{ error }}</div>
        </template>
      </section>
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.workspace-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, rgba(212, 243, 106, 0.08), transparent 28rem), #0c0f0c; }
.section-hero { padding: 4vh 0 4vh; animation: rise-in 700ms var(--ease-out) both; }
.section-hero h1 { max-width: 800px; margin: 14px 0; font-size: clamp(2.5rem, 6vw, 5.5rem); line-height: 0.92; letter-spacing: -0.08em; }
.section-copy { max-width: 520px; color: var(--muted); font-size: 1.1rem; line-height: 1.6; }
.calendar-content { display: grid; gap: 20px; padding-bottom: 80px; }
.calendar-toolbar { display: flex; align-items: end; flex-wrap: wrap; gap: 20px; }
label { display: grid; gap: 7px; color: var(--muted); font-size: 0.82rem; }
select, input { min-width: 0; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: #0c0f0c; color: var(--ink); }
select:hover, input:hover { border-color: var(--muted); }
select:focus, input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.panel { display: grid; align-content: start; gap: 14px; min-width: 0; padding: 22px; border: 1px solid var(--line); border-radius: 20px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.9), rgba(21, 24, 20, 0.94)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.12); }
.panel:hover { border-color: rgba(212, 243, 106, 0.32); }
.panel h2 { margin: 0 0 10px; font-size: 1.6rem; letter-spacing: -0.05em; }
.resource-list { position: relative; display: grid; gap: 8px; margin: 8px 0 0; padding: 14px 0 0; border-top: 1px solid var(--line); list-style: none; }
.resource-list li { display: flex; justify-content: space-between; gap: 10px; color: var(--ink); font-size: 0.85rem; }
.resource-list a { display: flex; justify-content: space-between; gap: 10px; width: 100%; padding: 8px; border-radius: 8px; color: inherit; text-decoration: none; }
.resource-list a:hover { background: rgba(212, 243, 106, 0.06); }
.resource-list small { color: var(--muted); font-size: 0.7rem; }
.match-form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: end; gap: 14px; }
.match-submit { min-height: 47px; }
.schedule-generator { display: grid; gap: 12px; margin-top: 8px; padding-top: 18px; border-top: 1px solid var(--line); }
.schedule-generator-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.schedule-generator-heading h3 { margin: 0; font-size: 1.05rem; letter-spacing: -0.03em; }
.schedule-generator-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: end; gap: 12px; }
.schedule-generator-options { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: end; gap: 12px; }
.group-head-options { display: grid; gap: 10px; }
.checkbox-label { display: flex; grid-template-columns: none; align-items: center; gap: 8px; color: var(--ink); }
.checkbox-label input { width: auto; }
.team-head-picker { display: flex; flex-wrap: wrap; gap: 8px 14px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; }
.schedule-generator-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.schedule-result { margin: 0; padding: 11px 12px; border: 1px solid rgba(212, 243, 106, 0.28); border-radius: 10px; background: rgba(212, 243, 106, 0.06); color: var(--muted); font-size: 0.78rem; }
.schedule-result code { margin-left: 4px; }
.match-list { margin-top: 2px; }
.empty-state, .form-error { padding: 20px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
.form-error { border-style: solid; border-color: #a45b5b; color: #ffb0a8; }
code { color: var(--accent); font-size: 0.75rem; }
@media (max-width: 900px) { .match-form-grid, .schedule-generator-grid, .schedule-generator-options { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: stretch; } }
@media (max-width: 620px) { .container { width: min(100% - 28px, 620px); } .schedule-generator-heading { align-items: stretch; flex-direction: column; } .match-form-grid, .schedule-generator-grid, .schedule-generator-options { grid-template-columns: 1fr; } }
</style>
