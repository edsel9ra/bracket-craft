<script setup lang="ts">
import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { rosterReturnHref } from '~/utils/matchNavigation';
import { safeInternalRedirect } from '~/utils/navigation';
import { buildRosterPlayerBody } from '~/utils/requestBodies';
import {
  latestPublishedVersion,
  rosterLockMatchday,
  type RosterLockMatchLike,
  type RosterLockStageLike,
  type RosterLockVersionLike,
} from '~/utils/rosterLock';
import {
  ROSTER_STATE_OK,
  describeRosterSize,
  effectiveRosterLimits,
  rosterStatusFailureKey,
  rosterStatusGuidance,
} from '~/utils/rosterLimits';
import { phasesAssistantHref } from '~/utils/teamsWizard';

// Sección con dirección propia de las plantillas del torneo (spec 012, RF-017).
// Es la **única** pantalla que da de alta jugadores (RF-021): formulario único
// de una sola pantalla —lista, alta individual, importación CSV/ZIP, foto y
// consentimiento—, sin pasos (WIZ-1). El alta duplicada de la operación se
// retira en H1-T09; aquí no se replica ninguna otra escritura.
// RF-024: solo se pide la plantilla del equipo seleccionado. Las versiones, las
// fases y los partidos se leen únicamente para el aviso de cierre (CI-1/P4).
definePageMeta({ middleware: 'auth' });

interface VersionSummary extends RosterLockVersionLike {
  rules_config?: Record<string, unknown> | null;
}

interface StageSummary extends RosterLockStageLike {
  name: string;
  stage_type: string;
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
  player_id: string;
  team_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  age: number;
  photo_url: string | null;
  photo_consent: boolean;
  is_active: boolean;
}

interface MatchSummary extends RosterLockMatchLike {
  match_date: string | null;
}

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const { request } = useApi();
const { t, errorMessage } = useI18n();
const tournamentId = String(route.params.id);
const tournamentName = computed(
  () => tournamentsStore.tournaments.find((tournament) => tournament.id === tournamentId)?.name || null,
);
const tournamentLabel = computed(() => tournamentName.value || t('shell.tournament'));
const canManageTournaments = computed(() => auth.hasPermission('MANAGE_TOURNAMENTS'));
const phasesHref = computed(() => phasesAssistantHref(tournamentId));

const versions = ref<VersionSummary[]>([]);
const stages = ref<StageSummary[]>([]);
const matches = ref<MatchSummary[]>([]);
const teams = ref<TeamSummary[]>([]);
const rosters = ref<RosterSummary[]>([]);
const selectedTeamId = ref('');
const loading = ref(true);
const rosterLoading = ref(false);
const loadError = ref<string | null>(null);
const rosterError = ref<string | null>(null);
const actionError = ref<string | null>(null);
const notice = ref<string | null>(null);
const busy = ref(false);
const photoBusyRosterId = ref<string | null>(null);
const statusBusyRosterId = ref<string | null>(null);
const rosterCsvFile = ref<File | null>(null);
const rosterZipFile = ref<File | null>(null);
const rosterCsvInput = ref<HTMLInputElement | null>(null);
const rosterZipInput = ref<HTMLInputElement | null>(null);
const rosterWarnings = ref<string[]>([]);
const playerForm = reactive({
  first_name: '',
  last_name: '',
  national_id: '',
  birth_date: '',
  dorsal_number: 1,
  photo_consent: false,
});

const PAGE_SIZE = 200;
const ROSTER_PAGE_SIZE = 1000;

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

const selectedTeam = computed(
  () => teams.value.find((team) => team.team_id === selectedTeamId.value) || null,
);

// Aviso de cierre de inscripción: copia deliberada de la regla del servidor
// (P4). Es informativo y nunca impide guardar: el 409 real manda.
const publishedVersion = computed(() => latestPublishedVersion(versions.value));
// El aviso solo mira los partidos de la versión publicada; la lectura no filtra
// por versión porque la misma lista valida el retorno a la operación.
const publishedMatches = computed(() => {
  const published = publishedVersion.value;
  if (!published) return [];
  return matches.value.filter((match) => match.tournament_version_id === published.id);
});
const lockMatchday = computed(() => {
  const published = publishedVersion.value;
  if (!published) return null;
  return rosterLockMatchday(published.rules_config ?? null, stages.value, publishedMatches.value);
});

// RF-046: estado de la plantilla seleccionada con los límites efectivos de la
// versión de referencia. Se usa la publicada (la que está en vigor) y, mientras
// no exista, la última por número para que un borrador nuevo también avise. Es
// informativo: ningún control de edición se bloquea por tamaño.
const limitsVersion = computed<VersionSummary | null>(() => {
  if (publishedVersion.value) return publishedVersion.value;
  return versions.value.reduce<VersionSummary | null>(
    (latest, version) => (!latest || version.version_number > latest.version_number ? version : latest),
    null,
  );
});
const rosterLimits = computed(() => effectiveRosterLimits(limitsVersion.value?.rules_config ?? null));
const activeRosterCount = computed(() => rosters.value.filter((roster) => roster.is_active).length);
const sizeDescription = computed(() => describeRosterSize(activeRosterCount.value, rosterLimits.value, t));
const sizeWarning = computed(() => sizeDescription.value.state !== ROSTER_STATE_OK);
// RA-1: la reactivación se comporta como un alta; el retiro nunca se bloquea
// por jornada (RL-1).
const reactivateGuidance = computed(() => rosterStatusGuidance('reactivate', {
  lockActive: lockMatchday.value !== null,
}));

// RF-022: solo se ofrece volver si `returnTo` apunta a la operación de un
// partido **de este torneo**; el destino se reconstruye y nunca se copia.
const tournamentMatchIds = computed(() => matches.value.map((match) => match.id));
const returnToHref = computed(() => rosterReturnHref(route.query.returnTo, {
  tournamentId,
  matchIds: tournamentMatchIds.value,
}));

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
    await navigateTo({ path: '/forbidden', query: { returnTo: safeInternalRedirect(route.fullPath, '/workspace'), resource: 'tournament' } });
    return true;
  }
  return false;
}

function withPagination(path: string, limit: number, offset: number): string {
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}limit=${limit}&offset=${offset}`;
}

async function fetchPaged<T>(path: string, pageSize = PAGE_SIZE): Promise<T[]> {
  const rows: T[] = [];
  let offset = 0;
  while (true) {
    const page = await request<T[]>(withPagination(path, pageSize, offset));
    rows.push(...page);
    if (page.length < pageSize) return rows;
    offset += page.length;
  }
}

function resolveSelectedTeam(candidate: unknown): string {
  const requested = typeof candidate === 'string' ? candidate : '';
  if (teams.value.some((team) => team.team_id === requested)) return requested;
  return teams.value[0]?.team_id || '';
}

async function loadRoster() {
  if (!selectedTeamId.value) {
    rosters.value = [];
    return;
  }
  rosterLoading.value = true;
  rosterError.value = null;
  try {
    rosters.value = await fetchPaged<RosterSummary>(
      `/tournaments/${tournamentId}/rosters?team_id=${encodeURIComponent(selectedTeamId.value)}`,
      ROSTER_PAGE_SIZE,
    );
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    rosterError.value = failureMessage(cause, t('tournament.rosters.loadFailed'));
  } finally {
    rosterLoading.value = false;
  }
}

async function loadPage() {
  loading.value = true;
  loadError.value = null;
  try {
    const [versionRows, teamRows, matchRows] = await Promise.all([
      fetchPaged<VersionSummary>(`/tournaments/${tournamentId}/versions`),
      fetchPaged<TeamSummary>(`/tournaments/${tournamentId}/teams`),
      fetchPaged<MatchSummary>(`/tournaments/${tournamentId}/matches`),
    ]);
    versions.value = versionRows;
    teams.value = teamRows.filter((team) => team.status === 'registered');
    // Los partidos se leen una sola vez para el aviso de cierre (solo los de la
    // versión publicada) y para validar el retorno a la operación (todos los
    // del torneo). El endpoint filtra por organización y torneo con RLS.
    matches.value = matchRows;
    const published = latestPublishedVersion(versions.value);
    if (published) {
      const stageRows = await fetchPaged<StageSummary>(
        `/tournaments/${tournamentId}/stages?version_id=${encodeURIComponent(published.id)}`,
      );
      stages.value = stageRows.filter((stage) => stage.tournament_version_id === published.id);
    } else {
      stages.value = [];
    }
    selectedTeamId.value = resolveSelectedTeam(route.query.team);
    await loadRoster();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    loadError.value = failureMessage(cause, t('tournament.rosters.loadFailed'));
  } finally {
    loading.value = false;
  }
}

function onTeamChange() {
  const next = resolveSelectedTeam(selectedTeamId.value);
  selectedTeamId.value = next;
  if (next && route.query.team !== next) {
    void router.replace({ query: { ...route.query, team: next } });
  }
  void loadRoster();
}

watch(
  () => route.query.team,
  (value) => {
    const next = resolveSelectedTeam(value);
    if (next && next !== selectedTeamId.value) {
      selectedTeamId.value = next;
      void loadRoster();
    }
  },
);

async function createPlayer() {
  if (!canManageTournaments.value || !selectedTeamId.value) return;
  busy.value = true;
  actionError.value = null;
  notice.value = null;
  try {
    await request(`/tournaments/${tournamentId}/rosters`, {
      method: 'POST',
      body: buildRosterPlayerBody({ team_id: selectedTeamId.value, ...playerForm }),
    });
    playerForm.first_name = '';
    playerForm.last_name = '';
    playerForm.national_id = '';
    playerForm.birth_date = '';
    playerForm.dorsal_number = 1;
    playerForm.photo_consent = false;
    notice.value = t('tournament.rosters.created');
    await loadRoster();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    actionError.value = failureMessage(cause, t('tournament.rosters.createFailed'));
  } finally {
    busy.value = false;
  }
}

// RF-051 / RL-1 / RA-1: escritura única de actividad. El retiro está exento
// del bloqueo por jornada; la reactivación responde el mismo 409 del alta
// (cierre), además de los 409 por jugador con otra fila activa y por dorsal.
async function changeRosterStatus(roster: RosterSummary) {
  if (!canManageTournaments.value) return;
  const nextActive = !roster.is_active;
  statusBusyRosterId.value = roster.roster_id;
  actionError.value = null;
  notice.value = null;
  try {
    await request(`/tournaments/${tournamentId}/rosters/${roster.roster_id}/status`, {
      method: 'PATCH',
      body: { is_active: !roster.is_active },
    });
    notice.value = t(nextActive ? 'tournament.rosters.reactivated' : 'tournament.rosters.retired');
    await loadRoster();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    actionError.value = failureMessage(cause, t(rosterStatusFailureKey(nextActive ? 'reactivate' : 'retire')));
  } finally {
    statusBusyRosterId.value = null;
  }
}

function chooseRosterCsv(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  actionError.value = null;
  rosterCsvFile.value = null;
  if (file && !['.csv', '.txt'].some((extension) => file.name.toLowerCase().endsWith(extension))) {
    actionError.value = t('setup.rosterCsvType');
    input.value = '';
    return;
  }
  rosterCsvFile.value = file;
}

function chooseRosterZip(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  actionError.value = null;
  rosterZipFile.value = null;
  if (file && !file.name.toLowerCase().endsWith('.zip')) {
    actionError.value = t('setup.rosterZipType');
    input.value = '';
    return;
  }
  rosterZipFile.value = file;
}

function clearRosterFiles(clearWarnings = true) {
  rosterCsvFile.value = null;
  rosterZipFile.value = null;
  if (clearWarnings) rosterWarnings.value = [];
  if (rosterCsvInput.value) rosterCsvInput.value.value = '';
  if (rosterZipInput.value) rosterZipInput.value.value = '';
}

async function importRoster() {
  if (!canManageTournaments.value || !selectedTeamId.value || !rosterCsvFile.value) return;
  busy.value = true;
  actionError.value = null;
  notice.value = null;
  rosterWarnings.value = [];
  try {
    const body = new FormData();
    body.append('team_id', selectedTeamId.value);
    body.append('csv_file', rosterCsvFile.value);
    if (rosterZipFile.value) body.append('photos_zip', rosterZipFile.value);
    const result = await request<{ count: number; warnings: string[] }>(`/tournaments/${tournamentId}/rosters/bulk`, {
      method: 'POST',
      body,
    });
    rosterWarnings.value = result.warnings;
    clearRosterFiles(false);
    notice.value = t('tournament.rosters.imported', { count: result.count });
    await loadRoster();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    actionError.value = failureMessage(cause, t('setup.noRosterImport'));
  } finally {
    busy.value = false;
  }
}

async function uploadRosterPhoto(event: Event, rosterId: string) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  photoBusyRosterId.value = rosterId;
  actionError.value = null;
  try {
    const body = new FormData();
    body.append('photo', file);
    await request(`/tournaments/${tournamentId}/rosters/${rosterId}/photo`, { method: 'POST', body });
    await loadRoster();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    actionError.value = failureMessage(cause, t('setup.noPhotoUpload'));
  } finally {
    photoBusyRosterId.value = null;
    input.value = '';
  }
}

async function toggleRosterPhotoConsent(roster: RosterSummary) {
  const nextConsent = !roster.photo_consent;
  if (!nextConsent && roster.photo_url && import.meta.client && !window.confirm(t('setup.confirmRevokePhotoConsent'))) return;
  photoBusyRosterId.value = roster.roster_id;
  actionError.value = null;
  try {
    await request(`/tournaments/${tournamentId}/rosters/${roster.roster_id}/photo-consent`, {
      method: 'PATCH',
      body: { photo_consent: nextConsent },
    });
    await loadRoster();
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    actionError.value = failureMessage(cause, t('setup.noPhotoUpload'));
  } finally {
    photoBusyRosterId.value = null;
  }
}

await loadPage();
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
        <p class="eyebrow">{{ t('tournament.rosters.eyebrow') }}</p>
        <h1>{{ t('tournament.rosters.title') }}</h1>
        <p class="section-copy">{{ t('tournament.rosters.copy') }}</p>
        <p v-if="returnToHref" class="return-link">
          <a class="button-secondary" :href="returnToHref">{{ t('tournament.rosters.backToOperation') }}</a>
        </p>
      </section>

      <section class="container roster-content">
        <div v-if="loading" class="empty-state loading-state" role="status">
          <span class="loading-orb" aria-hidden="true" /> {{ t('setup.loading') }}
        </div>
        <div v-else-if="loadError" class="form-error" role="alert">
          <span>{{ loadError }}</span>
          <button class="button-secondary" type="button" @click="loadPage">{{ t('common.retry') }}</button>
        </div>
        <template v-else>
          <div v-if="!teams.length" class="panel">
            <p class="muted-note">{{ t('tournament.rosters.noTeams') }}</p>
            <p class="field-hint">
              {{ t('tournament.rosters.registerHint') }}
              <a :href="phasesHref">{{ t('teams.wizard.goToPhases') }}</a>
            </p>
          </div>
          <template v-else>
            <div class="panel roster-toolbar">
              <label>
                {{ t('setup.team') }}
                <select v-model="selectedTeamId" @change="onTeamChange">
                  <option v-for="team in teams" :key="team.team_id" :value="team.team_id">
                    {{ team.name }}
                  </option>
                </select>
              </label>
              <p class="field-hint">
                {{ t('tournament.rosters.registerHint') }}
                <a :href="phasesHref">{{ t('teams.wizard.goToPhases') }}</a>
              </p>
              <div class="roster-size-status" role="status">
                <strong>{{ t('tournament.rosters.sizeTitle') }}:</strong>
                <span class="roster-size-label">{{ sizeDescription.label }}</span>
                <small>{{ sizeDescription.detail }}</small>
              </div>
              <p v-if="sizeWarning" class="roster-size-notice" role="status">
                {{ t('tournament.rosters.sizeOutOfRange') }}
              </p>
            </div>

            <div v-if="!canManageTournaments" class="panel">
              <p class="muted-note">{{ t('tournament.rosters.readOnly') }}</p>
            </div>

            <p v-if="lockMatchday !== null" class="roster-lock-notice" role="status">
              <strong>{{ t('tournament.rosters.lockNotice', { matchday: lockMatchday }) }}</strong>
              <span>{{ t('tournament.rosters.lockAuthority') }}</span>
              <span>{{ t('tournament.rosters.lockRetireHint') }}</span>
              <span v-if="reactivateGuidance.hintKey">{{ t(reactivateGuidance.hintKey) }}</span>
            </p>

            <div class="roster-grid">
              <form v-if="canManageTournaments" class="panel" :aria-busy="busy" @submit.prevent="createPlayer">
                <div class="panel-heading">
                  <div><p class="eyebrow">{{ t('tournament.rosters.addEyebrow') }}</p><h2>{{ t('tournament.rosters.addTitle') }}</h2></div>
                </div>
                <p class="field-hint">{{ t('tournament.rosters.addCopy', { team: selectedTeam?.name || '' }) }}</p>
                <div class="field-row">
                  <label>{{ t('match.firstName') }}<input v-model="playerForm.first_name" required maxlength="100" /></label>
                  <label>{{ t('match.lastName') }}<input v-model="playerForm.last_name" required maxlength="100" /></label>
                </div>
                <label>
                  {{ t('match.document') }} <span class="field-hint">{{ t('match.encryptedOnServer') }}</span>
                  <input v-model="playerForm.national_id" required maxlength="100" autocomplete="off" />
                </label>
                <div class="field-row">
                  <label>{{ t('match.birthDate') }}<input v-model="playerForm.birth_date" type="date" required /></label>
                  <label>{{ t('match.number') }}<input v-model.number="playerForm.dorsal_number" type="number" min="1" max="999" required /></label>
                </div>
                <label class="checkbox-label"><input v-model="playerForm.photo_consent" type="checkbox" /> {{ t('match.imageConsent') }}</label>
                <button class="button-primary" type="submit" :disabled="busy">{{ busy ? t('common.saving') : t('match.addPlayer') }}</button>
              </form>

              <form v-if="canManageTournaments" class="panel" :aria-busy="busy" @submit.prevent="importRoster">
                <div class="panel-heading">
                  <div><p class="eyebrow">{{ t('tournament.rosters.importEyebrow') }}</p><h2>{{ t('setup.importRoster') }}</h2></div>
                  <span class="muted-note">{{ t('setup.rosterPhotoHint') }}</span>
                </div>
                <div class="roster-import-controls">
                  <label class="button-secondary file-picker">{{ t('setup.chooseRosterCsv') }}<input ref="rosterCsvInput" class="file-input" type="file" accept=".csv,.txt,text/csv,text/plain" @change="chooseRosterCsv" /></label>
                  <label class="button-secondary file-picker">{{ t('setup.choosePhotosZip') }}<input ref="rosterZipInput" class="file-input" type="file" accept=".zip,application/zip" @change="chooseRosterZip" /></label>
                </div>
                <div class="selected-roster-files">
                  <span v-if="rosterCsvFile">{{ t('setup.selectedRosterCsv', { name: rosterCsvFile.name }) }}</span>
                  <span v-if="rosterZipFile">{{ t('setup.selectedPhotosZip', { name: rosterZipFile.name }) }}</span>
                  <button v-if="rosterCsvFile || rosterZipFile" class="file-clear" type="button" @click="clearRosterFiles()">{{ t('setup.clearFiles') }}</button>
                </div>
                <p class="field-hint">{{ t('setup.rosterCsvHint') }}</p>
                <button class="button-primary" type="submit" :disabled="busy || !rosterCsvFile">{{ busy ? t('setup.importingRoster') : t('setup.importRoster') }}</button>
              </form>
            </div>

            <p v-if="actionError" class="form-error" role="alert">{{ actionError }}</p>
            <p v-if="notice" class="muted-note" role="status">{{ notice }}</p>
            <ul v-if="rosterWarnings.length" class="warning-list">
              <li v-for="warning in rosterWarnings" :key="warning">{{ warning }}</li>
            </ul>

            <section class="panel panel-wide roster-list-panel" :aria-busy="rosterLoading">
              <div class="panel-heading">
                <div><p class="eyebrow">{{ t('tournament.rosters.listEyebrow') }}</p><h2>{{ t('tournament.rosters.listTitle', { team: selectedTeam?.name || '' }) }}</h2></div>
              </div>
              <p v-if="rosterError" class="form-error" role="alert">{{ rosterError }}</p>
              <p v-if="rosterLoading" class="muted-note" role="status">{{ t('setup.loading') }}</p>
              <div v-else-if="rosters.length" class="roster-list">
                <div v-for="roster in rosters" :key="roster.roster_id" class="roster-card">
                  <img v-if="roster.photo_url && roster.photo_consent" :src="roster.photo_url" :alt="`${roster.first_name} ${roster.last_name}`" class="roster-photo" />
                  <div v-else class="roster-photo roster-photo-empty" aria-hidden="true">{{ roster.first_name.charAt(0) }}</div>
                  <div class="roster-card-info">
                    <strong>#{{ roster.dorsal_number }} · {{ roster.first_name }} {{ roster.last_name }}</strong>
                    <small>{{ t('setup.age', { age: roster.age }) }}</small>
                    <small>{{ roster.is_active ? t('tournament.rosters.stateActive') : t('tournament.rosters.stateRetired') }}</small>
                  </div>
                  <div v-if="canManageTournaments" class="photo-actions">
                    <button class="player-status" type="button" :disabled="statusBusyRosterId === roster.roster_id" @click="changeRosterStatus(roster)">
                      {{ roster.is_active ? t('tournament.rosters.retire') : t('tournament.rosters.reactivate') }}
                    </button>
                    <button class="photo-consent" type="button" :disabled="photoBusyRosterId === roster.roster_id" @click="toggleRosterPhotoConsent(roster)">
                      {{ roster.photo_consent ? t('setup.revokePhotoConsent') : t('setup.grantPhotoConsent') }}
                    </button>
                    <label v-if="roster.photo_consent" class="photo-picker">{{ roster.photo_url ? t('setup.replacePhoto') : t('setup.uploadPhoto') }}<input type="file" accept="image/jpeg,image/png,image/webp" :disabled="photoBusyRosterId === roster.roster_id" @change="uploadRosterPhoto($event, roster.roster_id)" /></label>
                  </div>
                </div>
              </div>
              <p v-else class="muted-note">{{ t('setup.noRosterPlayers') }}</p>
            </section>
          </template>
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
.return-link { margin-top: 18px; }
.roster-content { display: grid; gap: 18px; padding-bottom: 6vh; }
.roster-toolbar { display: grid; gap: 10px; }
.roster-toolbar select { width: min(100%, 420px); }
.roster-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }
.roster-import-controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); align-items: end; gap: 12px; }
.selected-roster-files { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; color: var(--muted); font-size: 0.78rem; }
.roster-list { display: grid; gap: 8px; padding-top: 14px; border-top: 1px solid var(--line); }
.roster-card { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 9px; border-radius: 11px; background: rgba(12, 15, 12, 0.3); }
.roster-photo { width: 42px; height: 42px; border-radius: 10px; object-fit: cover; }
.roster-photo-empty { display: grid; place-items: center; background: rgba(212, 243, 106, 0.12); color: var(--accent); font-weight: 800; }
.roster-card-info { display: grid; gap: 3px; min-width: 0; }
.roster-card-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.82rem; }
.roster-card-info small { color: var(--muted); font-size: 0.72rem; }
.photo-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: end; gap: 7px; }
.roster-lock-notice { display: grid; gap: 4px; margin: 0; padding: 12px 14px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 12px; background: rgba(255, 203, 122, 0.06); color: #ffcb7a; font-size: 0.82rem; }
.roster-size-status { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; color: var(--muted); font-size: 0.82rem; }
.roster-size-status strong { color: var(--ink); }
.roster-size-label { color: var(--accent); font-weight: 700; }
.roster-size-status small { color: var(--muted); font-size: 0.74rem; }
.roster-size-notice { margin: 0; padding: 11px 13px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 12px; background: rgba(255, 203, 122, 0.06); color: #ffcb7a; font-size: 0.8rem; }
.player-status { padding: 5px 10px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--ink); font-size: 0.72rem; }
.player-status:hover { border-color: var(--accent); color: var(--accent); }
.warning-list { display: grid; gap: 5px; margin: 0; padding: 10px 12px 10px 28px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 10px; color: #ffcb7a; font-size: 0.78rem; }
@media (max-width: 620px) {
  .roster-card { grid-template-columns: 42px minmax(0, 1fr); }
  .photo-actions { grid-column: 2; justify-self: start; justify-content: start; }
}
</style>
