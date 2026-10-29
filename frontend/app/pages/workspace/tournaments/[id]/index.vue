<script setup lang="ts">
import { type StageFormat } from '~/constants/stageFormats';
import { getApiCode, isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';
import {
  DEFAULT_RULES_CONFIG,
  RULES_VALIDATION_MESSAGE_KEYS,
  normalizeRulesConfig,
  validateRulesConfig,
  type RulesConfig,
} from '~/utils/rulesConfig';
import { buildRulesPayload, gameFormatOf, serverValidationDetail } from '~/utils/rulesWizard';
import { effectiveRosterLimits } from '~/utils/rosterLimits';
import { applyCrestResponse, crestActionKey, crestErrorMessageKey } from '~/utils/teamCrest';
import { isRosterLockActive, latestPublishedVersion } from '~/utils/rosterLock';
import { createMatchDraftStore } from '~/utils/matchDraft';
import { findMinutesOutside, minutesLimits } from '~/utils/rulesMinutes';
import {
  advanceAfterSave,
  resolveNotice,
  type AdvanceDecision,
  type AdvanceTarget,
} from '~/utils/sectionAdvance';
import type { ResolutionDraftEventInput, ResolutionSegmentInput } from '~/utils/matchResolution';
import { createWizardDraftStore, type WizardStorage } from '~/utils/wizardDraft';
import { resolveNavigation } from '~/utils/wizardStep';
import type { WizardKind } from '~/utils/wizardModel';

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
  logo_url?: string | null;
  crest_url?: string | null;
}

interface TeamCrestResponse {
  team_id: string;
  crest_url: string | null;
  logo_url: string | null;
}

interface RosterSummary {
  roster_id: string;
  team_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number;
  age: number;
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

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const tournamentsStore = useTournamentsStore();
const { request } = useApi();
const { t, statusLabel, errorMessage } = useI18n();
const tournamentId = String(route.params.id);
// RF-020: `#calendario` y `#plantillas` redirigen a su dirección propia
// reemplazando la entrada de historial.
const redirectLegacyTournamentHash = useLegacyTournamentSectionRedirect(tournamentId);
await redirectLegacyTournamentHash();

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
// RF-008: los tres asistentes informan de sus cambios sin guardar; la página es
// la única que decide si una navegación los descarta, con la tabla compartida.
const wizardDirty = reactive<Record<WizardKind, boolean>>({ rules: false, phases: false, teams: false });
const wizardResetToken = ref(0);
const hasWizardChanges = computed(() => wizardDirty.rules || wizardDirty.phases || wizardDirty.teams);
const knownStageTeamAssignments = ref<Record<string, string[]>>({});
const rulesConfig = ref<RulesConfig | null>(null);
const rulesError = ref<string | null>(null);
const rulesServerDetail = ref<unknown[] | null>(null);
/** Aviso de minutos (RF-035): registros que quedan fuera del nuevo máximo. */
const rulesMinutesNotice = ref<string | null>(null);
/**
 * Salto a Equipos que un guardado efectivo de reglas deja armado porque el aviso
 * de minutos aparece con sus controles (RF-015, ORD-9). Vive solo en la página:
 * no se guarda en `sessionStorage`, así que una recarga lo descarta (RF-016).
 */
const pendingAdvance = ref<AdvanceTarget | null>(null);
/** Títulos enfocables del formulario de reglas y del bloque de equipos (RF-007). */
const rulesTitle = ref<HTMLElement | null>(null);
const teamsTitle = ref<HTMLElement | null>(null);
const CONFIG_PAGE_SIZE = 200;

useHead({
  meta: [{ name: 'robots', content: 'noindex, nofollow' }],
});

const activeVersion = computed(() => versions.value.find((version) => version.id === selectedVersionId.value));
const draftVersion = computed(() => versions.value.find((version) => version.status === 'draft'));
const rulesEditable = computed(() => activeVersion.value?.status === 'draft');
const serverRulesConfig = computed<RulesConfig | null>(() => (
  activeVersion.value?.rules_config ? normalizeRulesConfig(activeVersion.value.rules_config) : null
));
// RF-043: el formato es informativo; el resumen lo muestra junto al aviso
// cuando la modalidad declarada no es la planilla de once.
const declaredGameFormat = computed(() => gameFormatOf(activeVersion.value?.rules_config ?? null));
const selectedVersionStages = computed(() => stages.value.filter((stage) => stage.tournament_version_id === selectedVersionId.value));
const selectedVersionMatches = computed(() => matches.value.filter((match) => match.tournament_version_id === selectedVersionId.value));
const draftVersionStages = computed(() => stages.value.filter((stage) => stage.tournament_version_id === draftVersion.value?.id));
const draftVersionMatches = computed(() => matches.value.filter((match) => match.tournament_version_id === draftVersion.value?.id));
// RF-046: el asistente de fases muestra el estado por equipo con los límites
// efectivos de la versión seleccionada y el conteo de jugadores activos que ya
// carga esta pantalla. La escritura y el 409 siguen siendo del servidor.
const selectedVersionRosterLimits = computed(() => effectiveRosterLimits(activeVersion.value?.rules_config ?? null));
// RL-1/RA-1: el bloqueo por jornada sale de la versión publicada más reciente,
// la misma regla que aplica el servidor y la pantalla de plantillas. El
// asistente de fases lo usa para explicar por qué no puede añadir jugadores.
const rosterLockActive = computed(() => {
  const published = latestPublishedVersion(versions.value);
  if (!published) return false;
  const publishedStages = stages.value.filter((stage) => stage.tournament_version_id === published.id);
  const publishedMatches = matches.value.filter((match) => match.tournament_version_id === published.id);
  return isRosterLockActive(published.rules_config ?? null, publishedStages, publishedMatches);
});
const rosterCountsByTeam = computed<Record<string, number>>(() => {
  const counts: Record<string, number> = {};
  for (const roster of rosters.value) {
    if (!roster.is_active) continue;
    counts[roster.team_id] = (counts[roster.team_id] ?? 0) + 1;
  }
  return counts;
});
const tournamentName = computed(() => tournamentsStore.tournaments.find((tournament) => tournament.id === tournamentId)?.name || null);
const tournamentLabel = computed(() => tournamentName.value || t('shell.tournament'));
const canManageTournaments = computed(() => auth.hasPermission('MANAGE_TOURNAMENTS'));
// RF-038: el modo solo lectura sale del permiso vigente del contexto de
// organización; no hay una segunda regla de autorización ni un permiso nuevo.
const configurationReadOnly = computed(() => !canManageTournaments.value);

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
// Spec 025 (RF-006): la checklist se lee versión → equipos → fases → partidos →
// plantillas, el mismo orden del documento. Textos y umbrales no cambian.
const setupChecks = computed(() => [
  { label: t('setup.versionDraft'), detail: draftVersion.value ? t('setup.readyToEdit') : t('setup.createVersion'), valid: Boolean(draftVersion.value) },
  { label: t('setup.teams'), detail: t('setup.assigned', { count: draftAssignedStageTeamCount.value }), valid: draftAssignedStageTeamCount.value >= 2 },
  { label: t('setup.stages'), detail: t('setup.configured', { count: draftVersionStages.value.length }), valid: draftVersionStages.value.length > 0 },
  { label: t('setup.matches'), detail: t('setup.scheduled', { count: draftVersionMatches.value.length }), valid: draftVersionMatches.value.length > 0 },
  { label: t('setup.rosters'), detail: t('setup.players', { count: rosters.value.length }), valid: rosters.value.length > 0 },
]);
const canPublish = computed(() => Boolean(draftVersion.value && draftVersionStages.value.length && draftAssignedStageTeamCount.value >= 2 && draftVersionMatches.value.length));

function syncRulesForVersion(versionId: string) {
  const version = versions.value.find((candidate) => candidate.id === versionId);
  rulesError.value = null;
  rulesServerDetail.value = null;
  if (version?.rules_config) {
    rulesConfig.value = normalizeRulesConfig(version.rules_config);
  } else {
    rulesConfig.value = null;
  }
}

function updateRulesConfig(value: RulesConfig) {
  // Sin normalizar: un límite inválido recién escrito debe llegar a la
  // validación con su mensaje por campo, no recortarse en silencio (RF-044).
  rulesConfig.value = value;
  rulesError.value = null;
  rulesServerDetail.value = null;
  // RF-016: editar una regla oculta el aviso y cancela el salto armado.
  clearPendingAdvance();
}

/**
 * RF-016: descarta el aviso y el salto pendiente **sin ejecutarlo**. Ninguno de
 * estos descartes escribe en el servidor ni cambia el resultado del guardado.
 */
function clearPendingAdvance(): void {
  rulesMinutesNotice.value = null;
  pendingAdvance.value = null;
}

/** Mueve el foco al título de la sección de destino (RF-007, RNF-003). */
async function focusAdvanceTarget(target: AdvanceTarget): Promise<void> {
  await nextTick();
  if (target.hash === '#equipos') {
    teamsTitle.value?.focus();
    return;
  }
  if (target.hash === '#fases') {
    // El título del asistente de fases es la cabecera enfocable del bloque.
    document.getElementById('wizard-title-phases')?.focus();
    return;
  }
  if (target.hash === '#configuracion') rulesTitle.value?.focus();
  // El salto a otra ruta deja el foco en el documento de la pantalla de destino.
}

/**
 * Ejecuta la decisión pura de avance (D-2): navega con la consulta actual —así
 * el `?step=` presente no se añade ni se retira (RF-007)— o deja el salto
 * armado cuando el aviso de minutos retiene la salida (RF-015). No traslada
 * ningún mensaje de éxito al destino (RF-009).
 */
async function executeAdvance(decision: AdvanceDecision): Promise<void> {
  if (decision.kind === 'stay') return;
  if (decision.kind === 'wait') {
    pendingAdvance.value = decision.target;
    return;
  }

  const target = decision.target;
  clearPendingAdvance();
  await router.push({
    path: target.path,
    hash: target.hash ?? undefined,
    query: target.keepQuery ? { ...route.query } : {},
  });
  await focusAdvanceTarget(target);
}

/**
 * «Continuar» (RF-015): descarta el aviso y reanuda el salto ya armado. No
 * guarda, no envía peticiones y, al limpiar el estado en el mismo tick, un
 * segundo clic no navega otra vez.
 */
async function continueAfterNotice(): Promise<void> {
  const target = pendingAdvance.value;
  if (!target) return;
  await executeAdvance(resolveNotice({ kind: 'wait', target }, 'continue'));
}

/**
 * «Quedarme» (RF-015, RF-017): descarta el aviso, cancela el salto, conserva lo
 * editado y devuelve el foco a un punto estable del formulario de reglas.
 */
async function stayAfterNotice(): Promise<void> {
  const target = pendingAdvance.value;
  if (!target) return;
  const decision = resolveNotice({ kind: 'wait', target }, 'stay');
  clearPendingAdvance();
  if (decision.kind !== 'stay') return;
  await nextTick();
  rulesTitle.value?.focus();
}


function wizardStorageOrNull(): WizardStorage | null {
  if (!import.meta.client) return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Borradores locales de partido: solo se leen para el aviso de minutos. */
function matchDraftStorageOrNull(): Storage | null {
  if (!import.meta.client) return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Descarta los borradores de los tres asistentes de la versión vigente
 * (RF-008). El borrador de otra versión u otro torneo no se toca: su clave ya
 * lo aísla y al volver a esa versión sigue en la pestaña.
 */
function clearWizardDrafts(versionId = selectedVersionId.value): void {
  const storage = wizardStorageOrNull();
  for (const wizard of ['rules', 'phases', 'teams'] as const) {
    createWizardDraftStore({
      wizard,
      userId: auth.userId,
      organizationId: auth.organizationId,
      tournamentId,
      versionId,
    }, storage).clear();
  }
}

/** Descarta los borradores y devuelve los asistentes a los valores del servidor. */
function discardDraft(): void {
  clearWizardDrafts();
  wizardResetToken.value += 1;
}

/**
 * Cambio de versión desde el selector (RF-008). Con cambios sin guardar pide
 * confirmación; si se cancela, la versión no cambia y el borrador se conserva;
 * si se acepta, se descarta el borrador y el asistente carga los valores del
 * servidor de la versión nueva.
 */
function onVersionChange(event: Event): void {
  const select = event.target as HTMLSelectElement;
  const next = select.value;
  if (next === selectedVersionId.value) return;

  const accepted = hasWizardChanges.value && import.meta.client
    ? window.confirm(t('wizard.navigation.confirmVersion'))
    : hasWizardChanges.value;
  const effect = resolveNavigation('version', hasWizardChanges.value, accepted);
  if (!effect.proceed) {
    select.value = selectedVersionId.value;
    return;
  }
  if (effect.discardDraft) clearWizardDrafts(selectedVersionId.value);
  selectedVersionId.value = next;
  // RF-016: cambiar de versión descarta el aviso y el salto armado.
  clearPendingAdvance();
  if (effect.discardDraft) wizardResetToken.value += 1;
}

// Cambiar de torneo con cambios sin guardar pide confirmación; recargar,
// cambiar de sección o el botón atrás dentro del asistente no pasan por aquí
// (mismo torneo) o conservan el borrador de la pestaña.
onBeforeRouteLeave((to) => {
  const targetId = typeof to.params.id === 'string' ? to.params.id : '';
  const otherTournament = to.path.startsWith('/workspace/tournaments/')
    && Boolean(targetId)
    && targetId !== tournamentId;
  if (!otherTournament || !hasWizardChanges.value) return true;

  const accepted = import.meta.client
    ? window.confirm(t('wizard.navigation.confirmTournament'))
    : true;
  const effect = resolveNavigation('tournament', true, accepted);
  if (!effect.proceed) return false;
  if (effect.discardDraft) discardDraft();
  return true;
});

// RF-016: una navegación dentro de la misma pantalla (entrada del índice,
// ancla `#resumen`/`#configuracion`/`#equipos`/`#fases` o enlace cruzado ya
// existente) retira el aviso y descarta el salto armado sin ejecutarlo; la
// navegación que pidió el usuario sí ocurre. Un cambio de paso de los asistentes
// solo reescribe `?step=`, así que no es una salida de la sección: el aviso
// recién mostrado tras el guardado debe seguir a la vista (RF-015).
onBeforeRouteUpdate((to, from) => {
  if (to.path !== from.path || to.hash !== from.hash) clearPendingAdvance();
  return true;
});

// RF-016: un ancla pulsada en la misma página no desmonta la pantalla, así que
// el descarte es explícito también cuando el navegador solo cambia el fragmento.
if (import.meta.client) {
  onMounted(() => window.addEventListener('hashchange', clearPendingAdvance));
  onBeforeUnmount(() => window.removeEventListener('hashchange', clearPendingAdvance));
}

watch(selectedVersionId, (versionId) => {
  syncRulesForVersion(versionId);
});

// RF-016: descartar el borrador (cambio de versión o de torneo aceptado)
// descarta también el aviso y el salto armado.
watch(wizardResetToken, () => clearPendingAdvance());

function failureMessage(cause: unknown, fallback: string): string {
  return errorMessage(cause, fallback);
}

function setRulesConfig(config: unknown): boolean {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return false;
  rulesConfig.value = normalizeRulesConfig(config);
  rulesError.value = null;
  rulesServerDetail.value = null;
  return true;
}

function useDefaultRules() {
  if (!rulesEditable.value) return;
  if (import.meta.client && !window.confirm(t('setup.confirmReplaceRules'))) return;
  setRulesConfig(DEFAULT_RULES_CONFIG);
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

// RF-055/RF-056: una imagen por equipo, gestionada solo desde el torneo donde
// está inscrito. El estado vive en la página: la fila se actualiza en sitio y
// no se recarga ni se tocan la versión seleccionada ni los borradores de la 012.
const crestBusyTeamId = ref<string | null>(null);
const crestStatusMessage = ref<string | null>(null);
const crestErrors = reactive<Record<string, string>>({});
const crestFiles = reactive<Record<string, File | null>>({});
const crestInputVersions = reactive<Record<string, number>>({});

function crestInputId(teamId: string): string {
  return `crest-file-${teamId}`;
}

function crestErrorId(teamId: string): string {
  return `crest-error-${teamId}`;
}

function onCrestFileSelected(teamId: string, event: Event): void {
  const input = event.target as HTMLInputElement;
  crestFiles[teamId] = input.files?.[0] ?? null;
  delete crestErrors[teamId];
}

function applyCrestRow(response: TeamCrestResponse): void {
  const index = teams.value.findIndex((candidate) => candidate.team_id === response.team_id);
  if (index < 0) return;
  const team = teams.value[index];
  if (!team) return;
  const updated = applyCrestResponse(team, response);
  if (updated) teams.value[index] = updated;
}

function crestFailureMessage(teamId: string, cause: unknown): void {
  const key = crestErrorMessageKey(getApiCode(cause));
  crestErrors[teamId] = key ? t(key) : failureMessage(cause, t('crest.error.generic'));
}

async function uploadCrest(team: TeamSummary): Promise<void> {
  if (!canManageTournaments.value) return;
  const file = crestFiles[team.team_id] ?? null;
  delete crestErrors[team.team_id];
  if (!file) {
    crestErrors[team.team_id] = t('crest.error.selectFile');
    return;
  }
  crestBusyTeamId.value = team.team_id;
  crestStatusMessage.value = t('crest.uploading');
  const body = new FormData();
  // El nombre del campo es el del contrato; el nombre del archivo no se usa.
  body.append('file', file);
  try {
    // `FormData` fija el Content-Type con su boundary: no se sobrescribe.
    const updated = await request<TeamCrestResponse>(
      `/tournaments/${tournamentId}/teams/${team.team_id}/crest`,
      { method: 'POST', body },
    );
    applyCrestRow(updated);
    crestFiles[team.team_id] = null;
    crestInputVersions[team.team_id] = (crestInputVersions[team.team_id] ?? 0) + 1;
    crestStatusMessage.value = t('crest.updated');
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    crestFailureMessage(team.team_id, cause);
    crestStatusMessage.value = null;
  } finally {
    crestBusyTeamId.value = null;
  }
}

async function removeCrest(team: TeamSummary): Promise<void> {
  if (!canManageTournaments.value || !team.crest_url) return;
  if (import.meta.client && !window.confirm(t('crest.confirmRemove', { team: team.name }))) return;
  crestBusyTeamId.value = team.team_id;
  crestStatusMessage.value = t('crest.removing');
  delete crestErrors[team.team_id];
  try {
    await request(`/tournaments/${tournamentId}/teams/${team.team_id}/crest`, { method: 'DELETE' });
    applyCrestRow({ team_id: team.team_id, crest_url: null, logo_url: null });
    crestStatusMessage.value = t('crest.removed');
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    crestFailureMessage(team.team_id, cause);
    crestStatusMessage.value = null;
  } finally {
    crestBusyTeamId.value = null;
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
  syncRulesForVersion(selectedVersionId.value);
}

async function loadConfiguration() {
  applyConfiguration(await fetchConfiguration());
}

async function refreshConfiguration() {
  try {
    await loadConfiguration();
  } catch (cause) {
    if (!(await redirectOnSessionFailure(cause))) error.value = failureMessage(cause, t('setup.loading'));
  }
}

/**
 * Alta de equipos efectiva (individual o en lote): abre el bloque de fases con
 * `#fases` conservando la consulta actual y sin escribir `?step=` (RF-002,
 * RF-007). Solo se ejecuta tras un alta exitosa: `TeamsWizard` solo emite
 * `saved` en ese caso, así que una alta fallida o con validación pendiente no
 * navega ni deja un salto armado. La recarga posterior no condiciona el salto.
 */
async function onTeamsSaved(): Promise<void> {
  void refreshConfiguration();
  await executeAdvance(advanceAfterSave({
    section: 'teams',
    effective: true,
    notice: false,
    tournamentId,
  }));
}

/**
 * Confirmación efectiva de una fase (creada sin composición, creada con
 * inscripción completa o reintento que completa): abre el calendario sin
 * consulta ni fragmento, sin crear partido, sortear ni escribir (RF-003,
 * RF-004). El guardado parcial, el error y el retiro de equipo no llegan aquí.
 */
async function onStagesConfirmed(): Promise<void> {
  void refreshConfiguration();
  await executeAdvance(advanceAfterSave({
    section: 'stages',
    effective: true,
    notice: false,
    tournamentId,
  }));
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

const CLOSED_MATCH_STATUSES = ['finished', 'cancelled', 'administrative_resolution'];

/**
 * Impacto de un cambio de minutos en un borrador (RF-035, criterio 23).
 *
 * Solo se miran partidos no cerrados de la versión seleccionada: las actas
 * confirmadas no se revalidan. Los segmentos persistidos se leen de la
 * operación de los partidos en juego o suspendidos; los eventos salen del
 * borrador local del navegador. La comprobación es informativa: no borra ni
 * reescribe nada y el servidor sigue siendo la autoridad del guardado.
 */
async function minutesImpactBeforeSave(config: RulesConfig) {
  const previous = serverRulesConfig.value ?? DEFAULT_RULES_CONFIG;
  const storage = matchDraftStorageOrNull();
  const relevant = selectedVersionMatches.value.filter(
    (match) => !CLOSED_MATCH_STATUSES.includes(match.status),
  );

  const draftEvents = new Map<string, readonly ResolutionDraftEventInput[]>();
  for (const match of relevant) {
    let events: readonly ResolutionDraftEventInput[] = [];
    if (storage) {
      const draft = createMatchDraftStore({
        userId: auth.userId,
        organizationId: auth.organizationId,
        matchId: match.id,
      }, storage).read().draft;
      if (draft) events = draft.events as unknown as readonly ResolutionDraftEventInput[];
    }
    draftEvents.set(match.id, events);
  }

  const segments = new Map<string, readonly ResolutionSegmentInput[]>();
  await Promise.all(relevant
    .filter((match) => match.status === 'live' || match.status === 'suspended')
    .map(async (match) => {
      try {
        const operation = await request<{ segments?: ResolutionSegmentInput[] }>(
          `/matches/${match.id}/operation`,
        );
        segments.set(match.id, Array.isArray(operation.segments) ? operation.segments : []);
      } catch {
        // Si la lectura falla, el aviso es parcial; el guardado no se bloquea.
        segments.set(match.id, []);
      }
    }));

  return findMinutesOutside(relevant.map((match) => ({
    matchId: match.id,
    previous: minutesLimits(previous, match.stage_id),
    next: minutesLimits(config, match.stage_id),
    segments: segments.get(match.id) ?? [],
    draftEvents: draftEvents.get(match.id) ?? [],
  })));
}

async function saveRules() {
  // RF-005: sin acción principal —observador o versión publicada— no hay
  // guardado de reglas, así que tampoco hay aviso, controles ni salto.
  if (!canManageTournaments.value) return;
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
  // RF-016: un guardado nuevo recalcula el aviso desde cero; nunca se acumulan
  // dos avisos ni dos salidas pendientes.
  clearPendingAdvance();
  // `v-model.number` leaves '' when the operator clears the field; normalize
  // it before validating so an empty registration matchday means `null`.
  if ((rulesConfig.value.roster_lock_matchday as unknown) === '') {
    rulesConfig.value.roster_lock_matchday = null;
  }
  const validationErrors = validateRulesConfig(rulesConfig.value);
  if (validationErrors.length) {
    const firstError = validationErrors[0];
    if (!firstError) return;
    rulesError.value = t(RULES_VALIDATION_MESSAGE_KEYS[firstError.code] ?? 'rules.error.invalidObject');
    return;
  }

  // RF-035: avisar de los registros que el nuevo máximo deja fuera, sin
  // borrarlos ni reescribirlos. Los segmentos persistidos piden decisión
  // explícita; los eventos del borrador dejan un aviso y no bloquean el guardado.
  // El texto se calcula aquí, pero solo se **publica** si la escritura termina
  // con éxito (ORD-12, RF-015): mientras la petición está en vuelo no se ve.
  const minutesImpact = await minutesImpactBeforeSave(rulesConfig.value);
  let minutesNotice: string | null = null;
  if (minutesImpact.segments.length) {
    const message = t('rules.minutesWarning.confirm', {
      segments: minutesImpact.segments.length,
      events: minutesImpact.events.length,
      max: minutesImpact.maxMinute ?? 0,
    });
    if (import.meta.client && !window.confirm(message)) return;
    minutesNotice = message;
  } else if (minutesImpact.events.length) {
    minutesNotice = t('rules.minutesWarning.events', {
      events: minutesImpact.events.length,
      max: minutesImpact.maxMinute ?? 0,
    });
  }

  saving.value = true;
  rulesError.value = null;
  rulesServerDetail.value = null;
  try {
    const updated = await request<VersionDetail>(`/tournaments/${tournamentId}/versions/${versionId}/rules`, {
      method: 'PATCH',
      body: buildRulesPayload(rulesConfig.value),
    });
    if (selectedVersionId.value !== versionId || updated.id !== versionId) {
      rulesError.value = t('rules.error.versionChanged');
      return;
    }
    setRulesConfig(updated.rules_config);
    // ORD-12: el aviso y sus dos controles aparecen solo cuando el guardado ya
    // terminó con éxito; si hubiera fallado, el `catch` no deja ninguno.
    rulesMinutesNotice.value = minutesNotice;
    // RF-008: la recarga posterior no condiciona el salto. Si falla, registra su
    // error en la página y la sección de destino muestra su propio estado.
    void refreshConfiguration();
    // RF-001, RF-015: sin aviso el salto es inmediato; con aviso queda armado
    // hasta que el usuario elija «Continuar» o «Quedarme».
    await executeAdvance(advanceAfterSave({
      section: 'rules',
      effective: true,
      notice: Boolean(minutesNotice),
      tournamentId,
    }));
  } catch (cause) {
    if (await redirectOnSessionFailure(cause)) return;
    // RF-016: un guardado fallido no deja aviso, controles ni salto armado.
    clearPendingAdvance();
    rulesServerDetail.value = serverValidationDetail(cause);
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
  >
   <main id="main-content" class="workspace-shell">
    <section id="resumen" class="container config-hero">
      <div class="hero-line">
        <p class="eyebrow">{{ t('setup.tournamentSetup') }}</p>
        <span class="draft-status"><span aria-hidden="true" /> {{ draftVersion ? t('setup.editableDraft') : t('setup.publishedVersion') }}</span>
      </div>
      <h1>{{ t('setup.headline') }}</h1>
      <p class="workspace-copy">{{ t('setup.copy') }}</p>
      <p class="format-summary">{{ t('setup.gameFormat', { format: declaredGameFormat }) }}</p>
      <p v-if="declaredGameFormat !== '11v11'" class="muted-note">{{ t('format.context', { format: declaredGameFormat }) }}</p>
    </section>

    <section class="container config-content">
        <div v-if="loading" class="empty-state loading-state" role="status"><span class="loading-orb" aria-hidden="true" /> {{ t('setup.loading') }}</div>
        <div v-else-if="loadError" class="form-error" role="alert"><span>{{ loadError }}</span><button class="button-secondary" type="button" @click="retryConfiguration">{{ t('common.retry') }}</button></div>
        <template v-else>
          <p v-if="configurationReadOnly" class="read-only-notice" role="status">
            {{ t('setup.readOnlyMode') }}
          </p>
          <div class="config-toolbar">
           <label class="field">
              {{ t('setup.version') }}
            <select :value="selectedVersionId" @change="onVersionChange">
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

          <div class="setup-checklist" :aria-label="t('setup.operationalChecklist')">
           <div class="checklist-heading"><div><p class="eyebrow">{{ t('setup.beforePublish') }}</p><h2>{{ t('setup.operationalChecklist') }}</h2></div><span class="muted-note">{{ t('setup.rosterNote') }}</span></div>
           <div class="checklist-items"><div v-for="check in setupChecks" :key="check.label" class="check-item" :class="{ valid: check.valid }"><span aria-hidden="true">{{ check.valid ? '✓' : '!' }}</span><strong>{{ check.label }}</strong><small>{{ check.detail }}</small></div></div>
         </div>

           <form id="configuracion" class="panel panel-wide rules-panel" :aria-busy="saving" @submit.prevent="saveRules">
             <div class="panel-heading">
               <div><p class="eyebrow">{{ t('setup.rulesEyebrow') }}</p><h2 ref="rulesTitle" tabindex="-1">{{ t('setup.editRules') }}</h2></div>
               <div class="rules-heading-actions">
                 <span v-if="activeVersion && !rulesEditable" class="muted-note">{{ t('rules.readOnlyVersion') }}</span>
                <button v-if="canManageTournaments && rulesEditable && !rulesConfig" class="button-secondary" type="button" @click="useDefaultRules">{{ t('setup.useDefaultRules') }}</button>
               </div>
             </div>
             <p class="field-hint">{{ t('setup.rulesDescription') }}</p>
             <RulesWizard
               :model-value="rulesConfig"
               :server-config="serverRulesConfig"
               :stages="selectedVersionStages"
               :disabled="!canManageTournaments || !rulesEditable"
               :busy="saving"
               :save-disabled="!rulesConfig"
               :tournament-id="tournamentId"
               :version-id="selectedVersionId"
               :server-detail="rulesServerDetail"
               :reset-token="wizardResetToken"
               @update:model-value="updateRulesConfig"
               @dirty-change="wizardDirty.rules = $event"
               @save="saveRules"
             />
             <p v-if="!rulesConfig && rulesEditable" class="muted-note">{{ t('setup.rulesLoadNote') }}</p>
             <p v-if="rulesError" class="form-error" role="alert">{{ rulesError }}</p>
             <!-- RF-017: se anuncia solo el texto del aviso; sus dos controles
                  van fuera de la región anunciada y conservan el orden de
                  lectura (texto primero, controles después). -->
             <template v-if="rulesMinutesNotice">
               <p class="minutes-warning" role="status">{{ rulesMinutesNotice }}</p>
               <div class="minutes-warning-actions">
                 <button type="button" class="button-secondary" @click="continueAfterNotice">{{ t('rules.minutesWarning.continue') }}</button>
                 <button type="button" class="button-secondary" @click="stayAfterNotice">{{ t('rules.minutesWarning.stay') }}</button>
               </div>
             </template>
           </form>


         <Transition name="content-fade" mode="out-in">
         <div key="configuration" class="config-grid">
            <!-- RF-003 / RF-021 (IN-1): único lugar que da de alta equipos.
                 El alta no pide fase: para inscribir se usa el asistente de fases.
                 Spec 025 (RF-001): el orden del documento es reglas → equipos → fases. -->
            <div id="equipos" class="panel teams-panel panel-wide">
              <p class="eyebrow">{{ t('setup.teamsEyebrow') }}</p>
              <h2 ref="teamsTitle" tabindex="-1">{{ t('setup.nameTheField') }}</h2>
              <TeamsWizard
                :tournament-id="tournamentId"
                :version-id="selectedVersionId"
                :disabled="!canManageTournaments || activeVersion?.status !== 'draft'"
                :busy="saving"
                :reset-token="wizardResetToken"
                @saved="onTeamsSaved"
                @dirty-change="wizardDirty.teams = $event"
              />
              <p v-if="crestStatusMessage" class="muted-note" role="status">{{ crestStatusMessage }}</p>
              <TransitionGroup name="card-list" tag="ul" class="resource-list">
                <li
                  v-for="team in teams"
                  :key="team.team_id"
                  class="team-row"
                  :aria-busy="crestBusyTeamId === team.team_id"
                >
                  <TeamCrest
                    :team="team"
                    :crest-url="team.crest_url ?? null"
                    :logo-url="team.logo_url ?? null"
                    surface="workspace"
                  />
                  <span class="team-name">{{ team.name }}</span>
                  <small>{{ team.short_code }}</small>
                  <div v-if="canManageTournaments" class="crest-actions">
                    <label :for="crestInputId(team.team_id)">{{ t('crest.fileLabel') }}</label>
                    <input
                      :id="crestInputId(team.team_id)"
                      :key="crestInputVersions[team.team_id] ?? 0"
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      :disabled="crestBusyTeamId === team.team_id"
                      :aria-invalid="crestErrors[team.team_id] ? 'true' : undefined"
                      :aria-describedby="crestErrors[team.team_id] ? crestErrorId(team.team_id) : undefined"
                      @change="onCrestFileSelected(team.team_id, $event)"
                    >
                    <button
                      type="button"
                      class="button-secondary"
                      :disabled="crestBusyTeamId === team.team_id || !crestFiles[team.team_id]"
                      :aria-describedby="crestErrors[team.team_id] ? crestErrorId(team.team_id) : undefined"
                      @click="uploadCrest(team)"
                    >{{ t(crestActionKey(Boolean(team.crest_url))) }}</button>
                    <button
                      v-if="team.crest_url"
                      type="button"
                      class="button-secondary"
                      :disabled="crestBusyTeamId === team.team_id"
                      :aria-describedby="crestErrors[team.team_id] ? crestErrorId(team.team_id) : undefined"
                      @click="removeCrest(team)"
                    >{{ t('crest.remove') }}</button>
                    <p
                      v-if="crestErrors[team.team_id]"
                      :id="crestErrorId(team.team_id)"
                      class="form-error"
                      role="alert"
                    >{{ crestErrors[team.team_id] }}</p>
                  </div>
                </li>
              </TransitionGroup>
            </div>

            <!-- RF-002/RF-010 (AT-1): único lugar que crea fases e inscribe equipos.
                 La creación y la inscripción son dos peticiones; si la segunda falla,
                 la fase queda visible y el asistente permite reintentar sobre ella.
                 Spec 025 (RF-001): el bloque de fases va después del de equipos. -->
            <StageTeamsWizard
              class="panel-wide"
              :tournament-id="tournamentId"
              :version-id="selectedVersionId"
              :stages="selectedVersionStages"
              :teams="teams"
              :roster-limits="selectedVersionRosterLimits"
              :roster-counts="rosterCountsByTeam"
              :lock-active="rosterLockActive"
              :disabled="!canManageTournaments || activeVersion?.status !== 'draft'"
              :busy="saving"
              :reset-token="wizardResetToken"
              @saved="refreshConfiguration"
              @confirmed="onStagesConfirmed"
              @reload="refreshConfiguration"
              @dirty-change="wizardDirty.phases = $event"
            />
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
.read-only-notice { margin: 0 0 18px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; color: var(--muted); font-size: 0.85rem; }
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
.panel h2:focus { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 0.35rem; }
.panel-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.panel-heading h2 { margin-bottom: 0; }
.rules-heading-actions { display: flex; align-items: center; justify-content: end; gap: 10px; }
.rules-panel { margin-bottom: 20px; }
.rules-panel textarea { min-height: 260px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.78rem; }
.resource-list { position: relative; display: grid; gap: 8px; margin: 8px 0 0; padding: 14px 0 0; border-top: 1px solid var(--line); list-style: none; }
.resource-list li { display: flex; justify-content: space-between; gap: 10px; color: var(--ink); font-size: 0.85rem; }
.resource-list button { width: 100%; padding: 8px; border-radius: 8px; color: inherit; background: transparent; text-align: left; }
.resource-list button:hover { background: rgba(212, 243, 106, 0.06); }
.resource-list li.active { color: var(--accent); }
.resource-list li.active button { background: rgba(212, 243, 106, 0.08); }
.resource-list small { color: var(--muted); font-size: 0.7rem; }
.resource-list li.team-row { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; }
.team-name { color: var(--ink); font-size: 0.85rem; }
.crest-actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; align-items: end; gap: 8px; }
.crest-actions label { font-size: 0.72rem; }
.crest-actions .form-error { flex-basis: 100%; margin: 0; }

.empty-state, .form-error { padding: 20px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.loading-state { display: flex; align-items: center; gap: 12px; }
.loading-orb { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 18px var(--accent); animation: pulse 1s ease-in-out infinite; }
.form-error { border-style: solid; border-color: #a45b5b; color: #ffb0a8; }
.minutes-warning { margin: 0; padding: 11px 13px; border: 1px solid rgba(255, 203, 122, 0.3); border-radius: 12px; background: rgba(255, 203, 122, 0.06); color: #ffcb7a; font-size: 0.82rem; }
.minutes-warning-actions { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 900px) { .config-grid { grid-template-columns: 1fr; } .panel-wide { grid-column: auto; } }
@media (max-width: 900px) { .checklist-items { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .container { width: min(100% - 28px, 620px); } .config-toolbar, .checklist-heading, .panel-heading { align-items: stretch; flex-direction: column; } .checklist-items { grid-template-columns: 1fr; } }
</style>
