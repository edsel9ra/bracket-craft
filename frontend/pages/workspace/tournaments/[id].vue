<script setup lang="ts">
import { getStageFormatOptions, type StageFormat } from '~/constants/stageFormats';
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';
import {
  DEFAULT_RULES_CONFIG,
  RULES_VALIDATION_MESSAGE_KEYS,
  buildRulesRequest,
  normalizeRulesConfig,
  validateRulesConfig,
  type RulesConfig,
} from '~/utils/rulesConfig';

definePageMeta({ middleware: 'auth' });

interface VersionSummary {
  id: string;
  version_number: number;
  status: string;
  rules_config?: Record<string, unknown>;
}

interface VersionDetail extends VersionSummary {
  rules_config: Record<string, unknown>;
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

interface RosterSummary {
  roster_id: string;
  team_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  photo_url: string | null;
  photo_consent: boolean;
  is_active: boolean;
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

const route = useRoute();
const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const { request } = useApi();
const { t, statusLabel, stageTypeLabel, dateLocale, errorMessage } = useI18n();
const tournamentId = String(route.params.id);

interface ConfigurationData {
  versions: VersionSummary[];
  stages: StageSummary[];
  teams: TeamSummary[];
  rosters: RosterSummary[];
  matches: MatchSummary[];
}

const versions = ref<VersionSummary[]>([]);
const stages = ref<StageSummary[]>([]);
const teams = ref<TeamSummary[]>([]);
const rosters = ref<RosterSummary[]>([]);
const matches = ref<MatchSummary[]>([]);
const loading = ref(true);
const saving = ref(false);
const loadError = ref<string | null>(null);
const error = ref<string | null>(null);
const selectedVersionId = ref('');
const selectedStageId = ref('');
const stageForm = reactive<{ name: string; stage_type: StageFormat; stage_order: number }>({ name: '', stage_type: 'round_robin', stage_order: 1 });
const teamForm = reactive({ name: '', short_code: '' });
const matchForm = reactive({ home_team_id: '', away_team_id: '', matchday: 1, match_date: '' });
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
const bulkTeamText = ref('');
const bulkTeamError = ref<string | null>(null);
const bulkFileName = ref('');
const csvFileInput = ref<HTMLInputElement | null>(null);
const rosterTeamId = ref('');
const rosterCsvFile = ref<File | null>(null);
const rosterZipFile = ref<File | null>(null);
const rosterCsvInput = ref<HTMLInputElement | null>(null);
const rosterZipInput = ref<HTMLInputElement | null>(null);
const rosterImportError = ref<string | null>(null);
const rosterImportWarnings = ref<string[]>([]);
const rosterBusy = ref(false);
const photoBusyRosterId = ref<string | null>(null);
const knownStageTeamAssignments = ref<Record<string, string[]>>({});
const rulesConfig = ref<RulesConfig | null>(null);
const rulesError = ref<string | null>(null);
const CONFIG_PAGE_SIZE = 200;

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

const activeVersion = computed(() => versions.value.find((version) => version.id === selectedVersionId.value));
const draftVersion = computed(() => versions.value.find((version) => version.status === 'draft'));
const rulesEditable = computed(() => activeVersion.value?.status === 'draft');
const stageFormatOptions = computed(() => getStageFormatOptions(t));
const selectedStageFormatDescription = computed(() => stageFormatOptions.value.find((format) => format.value === stageForm.stage_type)?.description || '');
const selectedVersionStages = computed(() => stages.value.filter((stage) => stage.tournament_version_id === selectedVersionId.value));
const selectedVersionMatches = computed(() => matches.value.filter((match) => match.tournament_version_id === selectedVersionId.value));
const draftVersionStages = computed(() => stages.value.filter((stage) => stage.tournament_version_id === draftVersion.value?.id));
const draftVersionMatches = computed(() => matches.value.filter((match) => match.tournament_version_id === draftVersion.value?.id));
const selectedStage = computed(() => selectedVersionStages.value.find((stage) => stage.id === selectedStageId.value));
const selectedStageTeams = computed(() => teams.value.filter((team) => team.stage_ids.includes(selectedStageId.value)));
const selectedStageMatches = computed(() => selectedVersionMatches.value.filter((match) => match.stage_id === selectedStageId.value));
const visibleStageMatches = computed(() => selectedStageMatches.value.filter((match) => match.status !== 'cancelled'));
const selectedRosters = computed(() => rosters.value.filter((roster) => roster.team_id === rosterTeamId.value));
const availableAwayTeams = computed(() => selectedStageTeams.value.filter((team) => team.team_id !== matchForm.home_team_id));
const tournamentName = computed(() => tournamentsStore.tournaments.find((tournament) => tournament.id === tournamentId)?.name || null);
const tournamentLabel = computed(() => tournamentName.value || t('shell.tournament'));
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

function assignmentKey(versionId: string, stageId: string): string {
  return `${versionId}:${stageId}`;
}

function rememberStageTeam(versionId: string, stageId: string, teamId: string) {
  const key = assignmentKey(versionId, stageId);
  const existing = knownStageTeamAssignments.value[key] || [];
  if (!existing.includes(teamId)) knownStageTeamAssignments.value[key] = [...existing, teamId];
}

function stageTeamCount(versionId: string, stageId: string): number {
  const ids = new Set(knownStageTeamAssignments.value[assignmentKey(versionId, stageId)] || []);
  for (const match of matches.value) {
    if (match.tournament_version_id !== versionId || match.stage_id !== stageId) continue;
    if (match.home_team_id) ids.add(match.home_team_id);
    if (match.away_team_id) ids.add(match.away_team_id);
  }
  return ids.size;
}

const draftAssignedStageTeamCount = computed(() => draftVersion.value
  ? draftVersionStages.value.reduce((count, stage) => count + stageTeamCount(draftVersion.value!.id, stage.id), 0)
  : 0);
const setupChecks = computed(() => [
  { label: t('setup.versionDraft'), detail: draftVersion.value ? t('setup.readyToEdit') : t('setup.createVersion'), valid: Boolean(draftVersion.value) },
  { label: t('setup.stages'), detail: t('setup.configured', { count: draftVersionStages.value.length }), valid: draftVersionStages.value.length > 0 },
  { label: t('setup.teams'), detail: t('setup.assigned', { count: draftAssignedStageTeamCount.value }), valid: draftAssignedStageTeamCount.value >= 2 },
  { label: t('setup.matches'), detail: t('setup.scheduled', { count: draftVersionMatches.value.length }), valid: draftVersionMatches.value.length > 0 },
  { label: t('setup.rosters'), detail: t('setup.players', { count: rosters.value.length }), valid: rosters.value.length > 0 },
]);
const canPublish = computed(() => Boolean(draftVersion.value && draftVersionStages.value.length && draftAssignedStageTeamCount.value >= 2 && draftVersionMatches.value.length));

function syncRulesForVersion(versionId: string) {
  const version = versions.value.find((candidate) => candidate.id === versionId);
  rulesError.value = null;
  if (version?.rules_config) {
    rulesConfig.value = normalizeRulesConfig(version.rules_config);
  } else {
    rulesConfig.value = null;
  }
}

function updateRulesConfig(value: RulesConfig) {
  rulesConfig.value = normalizeRulesConfig(value);
  rulesError.value = null;
}

watch(selectedVersionId, (versionId) => {
  const nextStages = stages.value.filter((stage) => stage.tournament_version_id === versionId);
  if (!nextStages.some((stage) => stage.id === selectedStageId.value)) {
    selectedStageId.value = nextStages[0]?.id || '';
  }
  syncRulesForVersion(versionId);
});

watch(() => matchForm.home_team_id, (homeTeamId) => {
  if (homeTeamId && matchForm.away_team_id === homeTeamId) matchForm.away_team_id = '';
});

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

function setRulesConfig(config: unknown): boolean {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return false;
  rulesConfig.value = normalizeRulesConfig(config);
  rulesError.value = null;
  return true;
}

function useDefaultRules() {
  if (!rulesEditable.value) return;
  if (import.meta.client && !window.confirm(t('setup.confirmReplaceRules'))) return;
  setRulesConfig(DEFAULT_RULES_CONFIG);
}

function formatMatchDate(value: string | null): string {
  if (!value) return t('public.dateToDefine');
  return new Intl.DateTimeFormat(dateLocale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
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

async function fetchConfiguration(): Promise<ConfigurationData> {
  const [versions, stages, teams, rosters, matches] = await Promise.all([
    fetchPaged<VersionSummary>(`/tournaments/${tournamentId}/versions`),
    fetchPaged<StageSummary>(`/tournaments/${tournamentId}/stages`),
    fetchPaged<TeamSummary>(`/tournaments/${tournamentId}/teams`),
    fetchPaged<RosterSummary>(`/tournaments/${tournamentId}/rosters`),
    fetchPaged<MatchSummary>(`/tournaments/${tournamentId}/matches`),
  ]);

  return { versions, stages, teams, rosters, matches };
}

function applyConfiguration(configuration: ConfigurationData) {
  versions.value = configuration.versions;
  stages.value = configuration.stages;
  teams.value = configuration.teams;
  rosters.value = configuration.rosters;
  matches.value = configuration.matches;
  const stageVersionById = new Map(configuration.stages.map((stage) => [stage.id, stage.tournament_version_id]));
  for (const team of configuration.teams) {
    for (const stageId of team.stage_ids) {
      const versionId = stageVersionById.get(stageId);
      if (versionId) rememberStageTeam(versionId, stageId, team.team_id);
    }
  }
  for (const match of configuration.matches) {
    if (match.home_team_id) rememberStageTeam(match.tournament_version_id, match.stage_id, match.home_team_id);
    if (match.away_team_id) rememberStageTeam(match.tournament_version_id, match.stage_id, match.away_team_id);
  }
  if (!selectedVersionId.value || !configuration.versions.some((version) => version.id === selectedVersionId.value)) {
    selectedVersionId.value = configuration.versions.find((version) => version.status === 'draft')?.id || configuration.versions[0]?.id || '';
  }
  const versionStages = configuration.stages.filter((stage) => stage.tournament_version_id === selectedVersionId.value);
  if (!selectedStageId.value || !versionStages.some((stage) => stage.id === selectedStageId.value)) {
    selectedStageId.value = versionStages[0]?.id || '';
  }
  const selectedStageConfig = versionStages.find((stage) => stage.id === selectedStageId.value);
  if (selectedStageConfig?.stage_type === 'swiss') {
    const swissMatches = configuration.matches.filter((match) => match.tournament_version_id === selectedVersionId.value
      && match.stage_id === selectedStageId.value
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
  syncRulesForVersion(selectedVersionId.value);
  if (!rosterTeamId.value || !configuration.teams.some((team) => team.team_id === rosterTeamId.value)) {
    rosterTeamId.value = configuration.teams[0]?.team_id || '';
  }
}

async function loadConfiguration() {
  applyConfiguration(await fetchConfiguration());
}

async function retryConfiguration() {
  loading.value = true;
  loadError.value = null;
  try {
    await loadConfiguration();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) loadError.value = failureMessage(cause, t('setup.loading'));
  } finally {
    loading.value = false;
  }
}

async function createStage() {
  if (!selectedVersionId.value) return;
  saving.value = true;
  error.value = null;
  try {
    await request(`/tournaments/${tournamentId}/stages`, {
      method: 'POST',
      body: { ...stageForm, version_id: selectedVersionId.value },
    });
    stageForm.name = '';
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
     error.value = failureMessage(cause, t('setup.noStage'));
  } finally {
    saving.value = false;
  }
}

async function createTeam() {
  if (!selectedStageId.value) return;
  saving.value = true;
  error.value = null;
  try {
    const created = await request<{ team_id: string }>(`/tournaments/${tournamentId}/teams`, {
      method: 'POST',
      body: { ...teamForm, stage_id: selectedStageId.value },
    });
    rememberStageTeam(selectedVersionId.value, selectedStageId.value, created.team_id);
    teamForm.name = '';
    teamForm.short_code = '';
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
     error.value = failureMessage(cause, t('setup.noTeam'));
  } finally {
    saving.value = false;
  }
}

async function createMatch() {
  if (!selectedStageId.value || !selectedVersionId.value) return;
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
    await loadConfiguration();
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
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    error.value = failureMessage(cause, t('setup.noScheduleGeneration'));
  } finally {
    scheduleBusy.value = false;
  }
}

function parseBulkTeamLine(line: string): string[] {
  const values: string[] = [];
  let value = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === ',' && !quoted) {
      values.push(value.trim());
      value = '';
    } else {
      value += character;
    }
  }
  values.push(value.trim());
  return values;
}

function parseBulkTeams() {
  const lines = bulkTeamText.value.replace(/^\uFEFF/, '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) throw new Error(t('setup.csvEmpty'));
  const firstColumns = parseBulkTeamLine(lines[0]).map((column) => column.toLowerCase());
  const dataLines = firstColumns[0] === 'name' && firstColumns[1] === 'short_code' ? lines.slice(1) : lines;
  if (!dataLines.length) throw new Error(t('setup.csvHeaderOnly'));
  if (dataLines.length > 200) throw new Error(t('setup.csvLimit'));
  const codes = new Set<string>();
  return dataLines.map((line, index) => {
    const [name, short_code, logo_url = ''] = parseBulkTeamLine(line);
    if (!name || name.length < 2 || name.length > 100) throw new Error(t('setup.csvName', { row: index + 1 }));
    if (!/^[A-Za-z0-9_-]{2,10}$/.test(short_code || '')) throw new Error(t('setup.csvCode', { row: index + 1 }));
    const normalizedCode = short_code.toLowerCase();
    if (codes.has(normalizedCode)) throw new Error(t('setup.csvDuplicate', { row: index + 1 }));
    codes.add(normalizedCode);
    if (logo_url && !/^https?:\/\//i.test(logo_url)) throw new Error(t('setup.csvLogo', { row: index + 1 }));
    return { name, short_code, logo_url: logo_url || null };
  });
}

async function loadCsvFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  bulkTeamError.value = null;
  if (!file.name.toLowerCase().endsWith('.csv')) {
    bulkTeamError.value = t('setup.csvFileType');
    input.value = '';
    return;
  }
  try {
    bulkTeamText.value = await file.text();
    bulkFileName.value = file.name;
  } catch {
    bulkTeamError.value = t('setup.csvReadError');
    input.value = '';
  }
}

function clearCsvFile() {
  bulkTeamText.value = '';
  bulkFileName.value = '';
  if (csvFileInput.value) csvFileInput.value.value = '';
}

async function importBulkTeams() {
  if (!selectedStageId.value) return;
  bulkTeamError.value = null;
  try {
    const bulkTeams = parseBulkTeams();
    saving.value = true;
    const created = await request<{ teams: Array<{ team_id: string }> }>(`/tournaments/${tournamentId}/teams/bulk`, {
      method: 'POST',
      body: { teams: bulkTeams, stage_id: selectedStageId.value },
    });
    for (const team of created.teams) rememberStageTeam(selectedVersionId.value, selectedStageId.value, team.team_id);
    clearCsvFile();
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    bulkTeamError.value = failureMessage(cause, t('setup.noImport'));
  } finally {
    saving.value = false;
  }
}

function chooseRosterCsv(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  rosterImportError.value = null;
  rosterCsvFile.value = null;
  if (file && !['.csv', '.txt'].some((extension) => file.name.toLowerCase().endsWith(extension))) {
    rosterImportError.value = t('setup.rosterCsvType');
    input.value = '';
    return;
  }
  rosterCsvFile.value = file;
}

function chooseRosterZip(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  rosterImportError.value = null;
  rosterZipFile.value = null;
  if (file && !file.name.toLowerCase().endsWith('.zip')) {
    rosterImportError.value = t('setup.rosterZipType');
    input.value = '';
    return;
  }
  rosterZipFile.value = file;
}

function clearRosterFiles(clearWarnings = true) {
  rosterCsvFile.value = null;
  rosterZipFile.value = null;
  if (clearWarnings) rosterImportWarnings.value = [];
  if (rosterCsvInput.value) rosterCsvInput.value.value = '';
  if (rosterZipInput.value) rosterZipInput.value.value = '';
}

async function importRoster() {
  if (!rosterTeamId.value || !rosterCsvFile.value) return;
  rosterImportError.value = null;
  rosterImportWarnings.value = [];
  rosterBusy.value = true;
  try {
    const body = new FormData();
    body.append('team_id', rosterTeamId.value);
    body.append('csv_file', rosterCsvFile.value);
    if (rosterZipFile.value) body.append('photos_zip', rosterZipFile.value);
    const result = await request<{ count: number; warnings: string[] }>(`/tournaments/${tournamentId}/rosters/bulk`, {
      method: 'POST',
      body,
    });
    rosterImportWarnings.value = result.warnings;
    clearRosterFiles(false);
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    rosterImportError.value = failureMessage(cause, t('setup.noRosterImport'));
  } finally {
    rosterBusy.value = false;
  }
}

async function uploadRosterPhoto(event: Event, rosterId: string) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  photoBusyRosterId.value = rosterId;
  rosterImportError.value = null;
  try {
    const body = new FormData();
    body.append('photo', file);
    await request(`/tournaments/${tournamentId}/rosters/${rosterId}/photo`, { method: 'POST', body });
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    rosterImportError.value = failureMessage(cause, t('setup.noPhotoUpload'));
  } finally {
    photoBusyRosterId.value = null;
    input.value = '';
  }
}

async function toggleRosterPhotoConsent(roster: RosterSummary) {
  const nextConsent = !roster.photo_consent;
  if (!nextConsent && roster.photo_url && import.meta.client && !window.confirm(t('setup.confirmRevokePhotoConsent'))) return;
  photoBusyRosterId.value = roster.roster_id;
  rosterImportError.value = null;
  try {
    await request(`/tournaments/${tournamentId}/rosters/${roster.roster_id}/photo-consent`, {
      method: 'PATCH',
      body: { photo_consent: nextConsent },
    });
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    rosterImportError.value = failureMessage(cause, t('setup.noPhotoUpload'));
  } finally {
    photoBusyRosterId.value = null;
  }
}

function teamName(teamId: string): string {
  return teams.value.find((team) => team.team_id === teamId)?.name || t('setup.noDefine');
}

async function publishVersion() {
  if (!draftVersion.value) return;
  if (!canPublish.value) {
    error.value = t('setup.publishRequirement');
    return;
  }
  if (import.meta.client && !window.confirm(t('workspace.confirmPublish'))) return;
  saving.value = true;
  error.value = null;
  try {
    await request(`/tournaments/${draftVersion.value.id}/publish`, { method: 'POST' });
    await loadConfiguration();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    error.value = failureMessage(cause, t('setup.noPublish'));
  } finally {
    saving.value = false;
  }
}

async function createDraftVersion() {
  if (draftVersion.value || !activeVersion.value) return;
  saving.value = true;
  error.value = null;
  try {
    const created = await request<VersionDetail>(`/tournaments/${tournamentId}/versions`, {
      method: 'POST',
      body: {},
    });
    await loadConfiguration();
    selectedVersionId.value = created.id;
    setRulesConfig(created.rules_config);
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    error.value = failureMessage(cause, t('setup.noVersion'));
  } finally {
    saving.value = false;
  }
}

async function saveRules() {
  const versionId = selectedVersionId.value;
  const version = versions.value.find((candidate) => candidate.id === versionId);
  if (!version || version.status !== 'draft') {
    rulesError.value = t('rules.error.draftOnly');
    return;
  }
  if (!rulesConfig.value) {
    rulesError.value = t('rules.error.noConfig');
    return;
  }
  const validationErrors = validateRulesConfig(rulesConfig.value);
  if (validationErrors.length) {
    rulesError.value = t(RULES_VALIDATION_MESSAGE_KEYS[validationErrors[0].code]);
    return;
  }

  saving.value = true;
  rulesError.value = null;
  try {
    const updated = await request<VersionDetail>(`/tournaments/${tournamentId}/versions/${versionId}/rules`, {
      method: 'PATCH',
      body: buildRulesRequest(rulesConfig.value),
    });
    if (selectedVersionId.value !== versionId || updated.id !== versionId) {
      rulesError.value = t('rules.error.versionChanged');
      return;
    }
    setRulesConfig(updated.rules_config);
    await loadConfiguration();
    if (selectedVersionId.value === versionId) syncRulesForVersion(versionId);
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    rulesError.value = failureMessage(cause, t('setup.noRulesUpdate'));
  } finally {
    saving.value = false;
  }
}

const { data: initialConfiguration, error: initialConfigurationError } = await useAsyncData<ConfigurationData>(
  `workspace-tournament-${tournamentId}-${auth.userId || 'none'}-${auth.organizationId || 'none'}-${auth.sessionVersion}`,
  fetchConfiguration,
);

if (initialConfigurationError.value) {
  if (!(await redirectOnSessionFailure(initialConfigurationError.value))) {
     loadError.value = failureMessage(initialConfigurationError.value, t('setup.loading'));
  }
} else if (initialConfiguration.value) {
  applyConfiguration(initialConfiguration.value);
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
    active-section="configuration"
  >
   <main id="main-content" class="workspace-shell">
    <section id="resumen" class="container config-hero">
      <div class="hero-line">
        <p class="eyebrow">{{ t('setup.tournamentSetup') }}</p>
        <span class="draft-status"><span aria-hidden="true" /> {{ draftVersion ? t('setup.editableDraft') : t('setup.publishedVersion') }}</span>
      </div>
      <h1>{{ t('setup.headline') }}</h1>
      <p class="workspace-copy">{{ t('setup.copy') }}</p>
    </section>

    <section class="container config-content">
        <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('setup.loading') }}</div>
        <div v-else-if="loadError" class="form-error" role="alert"><span>{{ loadError }}</span><button class="button-secondary" type="button" @click="retryConfiguration">{{ t('common.retry') }}</button></div>
        <template v-else>
          <div class="config-toolbar">
           <label>
              {{ t('setup.version') }}
            <select v-model="selectedVersionId">
              <option v-for="version in versions" :key="version.id" :value="version.id">
                 v{{ version.version_number }} · {{ statusLabel(version.status) }}
              </option>
            </select>
          </label>
             <button v-if="canManageTournaments && draftVersion" class="button-primary" type="button" :disabled="saving || !canPublish" @click="publishVersion">
             {{ saving ? t('common.saving') : t('setup.publishDraft') }}
           </button>
             <button v-else-if="canManageTournaments && activeVersion?.status === 'published'" class="button-secondary" type="button" :disabled="saving" @click="createDraftVersion">
              {{ saving ? t('common.saving') : t('setup.createDraftVersion') }}
           </button>
          </div>

           <form id="configuracion" class="panel panel-wide rules-panel" :aria-busy="saving" @submit.prevent="saveRules">
             <div class="panel-heading">
               <div><p class="eyebrow">{{ t('setup.rulesEyebrow') }}</p><h2>{{ t('setup.editRules') }}</h2></div>
               <div class="rules-heading-actions">
                 <span v-if="activeVersion && !rulesEditable" class="muted-note">{{ t('rules.readOnlyVersion') }}</span>
                <button v-if="canManageTournaments && rulesEditable && !rulesConfig" class="button-secondary" type="button" @click="useDefaultRules">{{ t('setup.useDefaultRules') }}</button>
               </div>
             </div>
             <p class="field-hint">{{ t('setup.rulesDescription') }}</p>
             <RulesEditor
               :model-value="rulesConfig"
               :stages="selectedVersionStages"
                :disabled="!canManageTournaments || !rulesEditable"
               :aria-label="t('setup.editRules')"
               @update:model-value="updateRulesConfig"
             />
             <p v-if="!rulesConfig && rulesEditable" class="muted-note">{{ t('setup.rulesLoadNote') }}</p>
             <p v-if="rulesError" class="form-error" role="alert">{{ rulesError }}</p>
              <button v-if="canManageTournaments" class="button-primary" type="submit" :disabled="saving || !rulesEditable || !rulesConfig">{{ saving ? t('common.saving') : t('setup.saveRules') }}</button>
           </form>

          <div class="setup-checklist" :aria-label="t('setup.operationalChecklist')">
           <div class="checklist-heading"><div><p class="eyebrow">{{ t('setup.beforePublish') }}</p><h2>{{ t('setup.operationalChecklist') }}</h2></div><span class="muted-note">{{ t('setup.rosterNote') }}</span></div>
           <div class="checklist-items"><div v-for="check in setupChecks" :key="check.label" class="check-item" :class="{ valid: check.valid }"><span aria-hidden="true">{{ check.valid ? '✓' : '!' }}</span><strong>{{ check.label }}</strong><small>{{ check.detail }}</small></div></div>
         </div>

         <Transition name="content-fade" mode="out-in">
         <div key="configuration" class="config-grid">
          <form class="panel" :aria-busy="saving" @submit.prevent="createStage">
             <p class="eyebrow">{{ t('setup.stagesEyebrow') }}</p>
             <h2>{{ t('setup.definePath') }}</h2>
              <label>{{ t('workspace.name') }}<input v-model="stageForm.name" :disabled="!canManageTournaments" minlength="2" maxlength="50" required /></label>
              <label>{{ t('setup.type') }}
                 <select v-model="stageForm.stage_type" :disabled="!canManageTournaments">
                   <option v-for="format in stageFormatOptions" :key="format.value" :value="format.value" :title="format.description">{{ format.label }}</option>
                </select>
                <span class="field-hint stage-format-description">{{ selectedStageFormatDescription }}</span>
              </label>
              <label>{{ t('setup.order') }}<input v-model.number="stageForm.stage_order" :disabled="!canManageTournaments" type="number" min="1" required /></label>
              <button v-if="canManageTournaments" class="button-primary" type="submit" :disabled="saving || activeVersion?.status !== 'draft'">{{ t('setup.addStage') }}</button>
             <TransitionGroup name="card-list" tag="ul" class="resource-list">
                <li v-for="stage in selectedVersionStages" :key="stage.id" :class="{ active: stage.id === selectedStageId }"><button type="button" :aria-pressed="stage.id === selectedStageId" @click="selectedStageId = stage.id">{{ stage.stage_order }}. {{ stage.name }} <small>{{ stageTypeLabel(stage.stage_type) }}</small></button></li>
             </TransitionGroup>
          </form>

            <form id="equipos" class="panel" :aria-busy="saving" @submit.prevent="createTeam">
             <p class="eyebrow">{{ t('setup.teamsEyebrow') }}</p>
             <h2>{{ t('setup.nameTheField') }}</h2>
             <label>{{ t('setup.stage') }}
                <select v-model="selectedStageId" :disabled="!canManageTournaments" required>
                 <option value="" disabled>{{ t('setup.selectStage') }}</option>
               <option v-for="stage in selectedVersionStages" :key="stage.id" :value="stage.id">{{ stage.name }}</option>
              </select>
            </label>
              <label>{{ t('workspace.name') }}<input v-model="teamForm.name" :disabled="!canManageTournaments" minlength="2" maxlength="100" required /></label>
              <label>{{ t('setup.code') }}<input v-model="teamForm.short_code" :disabled="!canManageTournaments" minlength="2" maxlength="10" pattern="[A-Za-z0-9_\-]+" required /></label>
              <button v-if="canManageTournaments" class="button-primary" type="submit" :disabled="saving || activeVersion?.status !== 'draft' || !selectedStageId">{{ t('setup.registerTeam') }}</button>
               <TransitionGroup name="card-list" tag="ul" class="resource-list">
                 <li v-for="team in teams" :key="team.team_id"><span>{{ team.name }}</span><small>{{ team.short_code }}</small></li>
               </TransitionGroup>
                <div v-if="canManageTournaments" class="bulk-import">
                  <div><p class="eyebrow">{{ t('setup.bulkImport') }}</p><h3>{{ t('setup.pasteCsv') }}</h3><p class="field-hint">{{ t('setup.csvHint', { columns: 'name,short_code,logo_url' }) }}</p></div>
                 <div class="csv-file-actions">
                   <label class="button-secondary file-picker">
                     {{ t('setup.chooseCsv') }}
                     <input ref="csvFileInput" class="file-input" type="file" accept=".csv,text/csv" @change="loadCsvFile" />
                   </label>
                   <span v-if="bulkFileName" class="csv-file-name">{{ t('setup.selectedFile', { name: bulkFileName }) }}</span>
                   <button v-if="bulkFileName" class="file-clear" type="button" @click="clearCsvFile">{{ t('setup.clearFile') }}</button>
                 </div>
                 <textarea v-model="bulkTeamText" rows="5" placeholder="name,short_code,logo_url&#10;Club Norte,CN,https://...&#10;Club Sur,CS," @input="bulkFileName = ''"></textarea>
                 <p v-if="bulkTeamError" class="form-error" role="alert">{{ bulkTeamError }}</p>
                  <button class="button-secondary" type="button" :disabled="saving || activeVersion?.status !== 'draft' || !selectedStageId || !bulkTeamText.trim()" @click="importBulkTeams">{{ saving ? t('setup.importing') : t('setup.importTeams') }}</button>
              </div>
            </form>

            <section id="plantillas" class="panel panel-wide roster-import-panel">
             <div class="panel-heading"><div><p class="eyebrow">04 · {{ t('setup.rosterImport') }}</p><h2>{{ t('setup.importRoster') }}</h2></div><span class="muted-note">{{ t('setup.rosterPhotoHint') }}</span></div>
              <div v-if="canManageTournaments" class="roster-import-controls">
               <label>{{ t('setup.team') }}<select v-model="rosterTeamId" required><option value="" disabled>{{ t('match.selectTeam') }}</option><option v-for="team in teams" :key="`roster-${team.team_id}`" :value="team.team_id">{{ team.name }}</option></select></label>
               <label class="button-secondary file-picker">{{ t('setup.chooseRosterCsv') }}<input ref="rosterCsvInput" class="file-input" type="file" accept=".csv,.txt,text/csv,text/plain" @change="chooseRosterCsv" /></label>
               <label class="button-secondary file-picker">{{ t('setup.choosePhotosZip') }}<input ref="rosterZipInput" class="file-input" type="file" accept=".zip,application/zip" @change="chooseRosterZip" /></label>
             </div>
              <div v-if="canManageTournaments" class="selected-roster-files">
               <span v-if="rosterCsvFile">{{ t('setup.selectedRosterCsv', { name: rosterCsvFile.name }) }}</span>
               <span v-if="rosterZipFile">{{ t('setup.selectedPhotosZip', { name: rosterZipFile.name }) }}</span>
               <button v-if="rosterCsvFile || rosterZipFile" class="file-clear" type="button" @click="clearRosterFiles()">{{ t('setup.clearFiles') }}</button>
             </div>
              <p v-if="canManageTournaments" class="field-hint">{{ t('setup.rosterCsvHint') }}</p>
             <p v-if="rosterImportError" class="form-error" role="alert">{{ rosterImportError }}</p>
             <ul v-if="rosterImportWarnings.length" class="warning-list">
               <li v-for="warning in rosterImportWarnings" :key="warning">{{ warning }}</li>
             </ul>
              <button v-if="canManageTournaments" class="button-primary" type="button" :disabled="rosterBusy || !rosterTeamId || !rosterCsvFile" @click="importRoster">{{ rosterBusy ? t('setup.importingRoster') : t('setup.importRoster') }}</button>
              <div v-if="selectedRosters.length" class="roster-list">
                <div v-for="roster in selectedRosters" :key="roster.roster_id" class="roster-card">
                 <img v-if="roster.photo_url && roster.photo_consent" :src="roster.photo_url" :alt="`${roster.first_name} ${roster.last_name}`" class="roster-photo" />
                 <div v-else class="roster-photo roster-photo-empty" aria-hidden="true">{{ roster.first_name.charAt(0) }}</div>
                 <div class="roster-card-info"><strong>#{{ roster.dorsal_number }} · {{ roster.first_name }} {{ roster.last_name }}</strong><small>{{ teamName(roster.team_id) }}</small></div>
                   <div v-if="canManageTournaments" class="photo-actions">
                    <button class="photo-consent" type="button" :disabled="photoBusyRosterId === roster.roster_id" @click="toggleRosterPhotoConsent(roster)">
                      {{ roster.photo_consent ? t('setup.revokePhotoConsent') : t('setup.grantPhotoConsent') }}
                    </button>
                    <label v-if="roster.photo_consent" class="photo-picker">{{ roster.photo_url ? t('setup.replacePhoto') : t('setup.uploadPhoto') }}<input type="file" accept="image/jpeg,image/png,image/webp" :disabled="photoBusyRosterId === roster.roster_id" @change="uploadRosterPhoto($event, roster.roster_id)" /></label>
                  </div>
               </div>
              </div>
              <p v-else class="muted-note">{{ t('setup.noRosterPlayers') }}</p>
            </section>

             <form id="calendario" class="panel panel-wide" :aria-busy="saving || scheduleBusy" @submit.prevent="createMatch">
                <p class="eyebrow">{{ t('setup.calendarEyebrow') }}</p>
                <h2>{{ t('setup.scheduleMatch') }}</h2>
                <div class="match-form-grid">
                 <label>{{ t('setup.home') }}
                  <select v-model="matchForm.home_team_id" :disabled="!canManageTournaments">
                     <option value="">{{ t('setup.noDefine') }}</option>
                    <option v-for="team in selectedStageTeams" :key="`home-${team.team_id}`" :value="team.team_id">{{ team.name }}</option>
                   </select>
                 </label>
                 <label>{{ t('setup.away') }}
                    <select v-model="matchForm.away_team_id" :disabled="!canManageTournaments">
                     <option value="">{{ t('setup.noDefine') }}</option>
                    <option v-for="team in availableAwayTeams" :key="`away-${team.team_id}`" :value="team.team_id">{{ team.name }}</option>
                   </select>
                 </label>
                  <label>{{ t('setup.matchday') }}<input v-model.number="matchForm.matchday" :disabled="!canManageTournaments" type="number" min="1" required /></label>
                   <label>{{ t('setup.matchDateTime') }}<input v-model="matchForm.match_date" :disabled="!canManageTournaments" type="datetime-local" required /></label>
                   <button v-if="canManageTournaments" class="button-primary match-submit" type="submit" :disabled="saving || scheduleBusy || activeVersion?.status !== 'draft' || !selectedStageId">{{ t('setup.createMatch') }}</button>
                </div>
                <div v-if="selectedStage" class="schedule-generator">
                   <div class="schedule-generator-heading">
                     <div><p class="eyebrow">{{ t('setup.generatorEyebrow') }}</p><h3>{{ t('setup.drawSchedule') }}</h3></div>
                     <span class="muted-note">{{ t('setup.generatorDescription') }}</span>
                   </div>
                   <div class="schedule-generator-grid">
                     <label>{{ t('setup.generatorStart') }}<input v-model="scheduleForm.start_date" :disabled="!canManageTournaments" type="datetime-local" /></label>
                     <label>{{ t('setup.generatorRoundInterval') }}<input v-model.number="scheduleForm.round_interval_days" :disabled="!canManageTournaments" type="number" min="1" max="365" /></label>
                     <label>{{ t('setup.generatorMatchInterval') }}<input v-model.number="scheduleForm.match_interval_hours" :disabled="!canManageTournaments" type="number" min="1" max="168" /></label>
                     <label>{{ t('setup.generatorSeed') }}<input v-model="scheduleForm.seed" :disabled="!canManageTournaments" type="number" min="0" step="1" :placeholder="t('setup.generatorSeedOptional')" /></label>
                   </div>
                   <div v-if="selectedStage.stage_type === 'round_robin' || selectedStage.stage_type === 'custom_group'" class="schedule-generator-options">
                     <label>{{ t('setup.generatorLegs') }}
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
                     <label>{{ t('setup.swissRounds') }}<input v-model.number="scheduleForm.swiss_rounds" :disabled="!canManageTournaments" type="number" min="1" max="64" /></label>
                     <label>{{ t('setup.swissRound') }}<input v-model.number="scheduleForm.swiss_round" :disabled="!canManageTournaments" type="number" min="1" :max="scheduleForm.swiss_rounds" /></label>
                     <label>{{ t('setup.swissHomeTarget') }}<input v-model.number="scheduleForm.swiss_home_target" :disabled="!canManageTournaments" type="number" min="0" :max="scheduleForm.swiss_rounds" /></label>
                     <label>{{ t('setup.swissAwayTarget') }}<input v-model.number="scheduleForm.swiss_away_target" :disabled="!canManageTournaments" type="number" min="0" :max="scheduleForm.swiss_rounds" /></label>
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

          </div>
         </Transition>
         <div v-if="error" class="form-error" role="alert">{{ error }}</div>
      </template>
    </section>
   </main>
  </WorkspaceShell>
</template>

<style scoped>
.workspace-shell { min-height: 100vh; background: radial-gradient(circle at 90% 8%, rgba(212, 243, 106, 0.08), transparent 28rem), #0c0f0c; }
.config-hero { padding: 4vh 0 4vh; }
.config-hero { animation: rise-in 700ms var(--ease-out) both; }
.hero-line { display: flex; align-items: center; gap: 18px; }
.draft-status { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; }
.draft-status span { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 12px var(--accent); }
.config-hero h1 { max-width: 800px; margin: 14px 0; font-size: clamp(2.5rem, 6vw, 5.5rem); line-height: 0.92; letter-spacing: -0.08em; }
.workspace-copy { max-width: 520px; color: var(--muted); font-size: 1.1rem; line-height: 1.6; }
.config-content { padding-bottom: 80px; }
.config-toolbar { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 24px; }
.config-toolbar label, label { display: grid; gap: 7px; color: var(--muted); font-size: 0.82rem; }
.setup-checklist { display: grid; gap: 16px; margin-bottom: 24px; padding: 20px; border: 1px solid rgba(212, 243, 106, 0.24); border-radius: 20px; background: rgba(212, 243, 106, 0.04); }
.checklist-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; }
.checklist-heading h2 { margin: 0; font-size: 1.5rem; letter-spacing: -0.05em; }
.checklist-items { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 9px; }
.check-item { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 6px 8px; min-width: 0; padding: 11px; border: 1px solid var(--line); border-radius: 12px; color: var(--muted); }
.check-item > span { display: grid; grid-row: span 2; width: 20px; height: 20px; place-items: center; border-radius: 50%; background: rgba(255, 176, 168, 0.1); color: var(--danger); font-size: 0.75rem; font-weight: 900; }
.check-item strong { overflow: hidden; color: var(--ink); font-size: 0.78rem; text-overflow: ellipsis; white-space: nowrap; }
.check-item small { color: var(--muted); font-size: 0.7rem; }
.check-item.valid { border-color: rgba(212, 243, 106, 0.28); }
.check-item.valid > span { background: rgba(212, 243, 106, 0.16); color: var(--accent); }
select, input { min-width: 0; padding: 0.82rem 0.9rem; border: 1px solid var(--line); border-radius: 10px; background: #0c0f0c; color: var(--ink); }
select:hover, input:hover { border-color: var(--muted); }
select:focus, input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }
.config-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; gap: 20px; }
.panel { display: grid; align-content: start; gap: 14px; min-width: 0; padding: 22px; border: 1px solid var(--line); border-radius: 20px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.9), rgba(21, 24, 20, 0.94)); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.12); }
.panel-wide { grid-column: 1 / -1; }
.panel:hover { border-color: rgba(212, 243, 106, 0.32); }
.panel h2 { margin: 0 0 10px; font-size: 1.6rem; letter-spacing: -0.05em; }
.panel-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.panel-heading h2 { margin-bottom: 0; }
.rules-heading-actions { display: flex; align-items: center; justify-content: end; gap: 10px; }
.rules-panel { margin-bottom: 20px; }
.rules-panel textarea { min-height: 260px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; }
.stage-format-description { line-height: 1.35; }
.resource-list { position: relative; display: grid; gap: 8px; margin: 8px 0 0; padding: 14px 0 0; border-top: 1px solid var(--line); list-style: none; }
.resource-list li { display: flex; justify-content: space-between; gap: 10px; color: var(--ink); font-size: 0.85rem; }
.resource-list button { width: 100%; padding: 8px; border-radius: 8px; color: inherit; background: transparent; text-align: left; }
.resource-list button:hover { background: rgba(212, 243, 106, 0.06); }
.resource-list a { display: flex; justify-content: space-between; gap: 10px; width: 100%; padding: 8px; border-radius: 8px; color: inherit; text-decoration: none; }
.resource-list a:hover { background: rgba(212, 243, 106, 0.06); }
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
.resource-list li.active { color: var(--accent); }
.resource-list li.active button { background: rgba(212, 243, 106, 0.08); }
.resource-list small { color: var(--muted); font-size: 0.7rem; }
.empty-state, .form-error { padding: 20px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
.form-error { border-style: solid; border-color: #a45b5b; color: #ffb0a8; }
.bulk-import { display: grid; gap: 10px; margin-top: 4px; padding-top: 16px; border-top: 1px solid var(--line); }
.bulk-import h3 { margin: 0; font-size: 1rem; }
.bulk-import .eyebrow { margin-bottom: 5px; }
.csv-file-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.file-picker { position: relative; justify-content: center; cursor: pointer; font-size: 0.78rem; }
.file-picker:focus-within { outline: 2px solid var(--accent); outline-offset: 4px; }
.file-input { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.csv-file-name { min-width: 0; overflow: hidden; color: var(--muted); font-size: 0.78rem; text-overflow: ellipsis; white-space: nowrap; }
.file-clear { padding: 4px 0; border: 0; background: transparent; color: var(--muted); font-size: 0.75rem; }
.file-clear:hover { color: var(--danger); }
.roster-import-panel { gap: 16px; }
.roster-import-controls { display: grid; grid-template-columns: minmax(180px, 1fr) auto auto; align-items: end; gap: 12px; }
.selected-roster-files { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; color: var(--muted); font-size: 0.78rem; }
.warning-list { display: grid; gap: 5px; margin: 0; padding: 10px 12px 10px 28px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 10px; color: #ffcb7a; font-size: 0.78rem; }
.roster-list { display: grid; gap: 8px; padding-top: 14px; border-top: 1px solid var(--line); }
.roster-card { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 9px; border-radius: 11px; background: rgba(12, 15, 12, 0.3); }
.roster-photo { width: 42px; height: 42px; border-radius: 10px; object-fit: cover; }
.roster-photo-empty { display: grid; place-items: center; background: rgba(212, 243, 106, 0.12); color: var(--accent); font-weight: 800; }
.roster-card-info { display: grid; gap: 3px; min-width: 0; }
.roster-card-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.82rem; }
.roster-card-info small { color: var(--muted); font-size: 0.72rem; }
.photo-picker { display: inline-flex; align-items: center; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; color: var(--muted); cursor: pointer; font-size: 0.7rem; }
.photo-picker:hover { border-color: var(--accent); color: var(--accent); }
.photo-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: end; gap: 7px; }
.photo-consent { padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--muted); font-size: 0.7rem; }
.photo-consent:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.photo-consent:disabled { cursor: wait; opacity: 0.6; }
.photo-picker input { width: 1px; height: 1px; padding: 0; overflow: hidden; opacity: 0; position: absolute; }
textarea { width: 100%; resize: vertical; padding: 0.8rem; border: 1px solid var(--line); border-radius: 10px; background: #0c0f0c; color: var(--ink); font: inherit; line-height: 1.5; }
textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); outline: none; }
code { color: var(--accent); font-size: 0.75rem; }
@media (max-width: 900px) { .config-grid { grid-template-columns: 1fr; } .panel-wide { grid-column: auto; } .roster-import-controls, .match-form-grid, .schedule-generator-grid, .schedule-generator-options { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: stretch; } }
@media (max-width: 900px) { .checklist-items { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .container { width: min(100% - 28px, 620px); } .config-toolbar, .checklist-heading, .panel-heading, .schedule-generator-heading { align-items: stretch; flex-direction: column; } .checklist-items { grid-template-columns: 1fr; } .roster-card { grid-template-columns: 42px minmax(0, 1fr); } .photo-actions { grid-column: 2; justify-self: start; justify-content: start; } .photo-picker { grid-column: auto; justify-self: start; } .roster-import-controls, .match-form-grid, .schedule-generator-grid, .schedule-generator-options { grid-template-columns: 1fr; } }
</style>
