import { isForbidden, isNotFound, isUnauthorized } from '~/utils/api';
import { safeInternalRedirect } from '~/utils/navigation';
import {
  DEFAULT_RULES_CONFIG,
  RULES_VALIDATION_MESSAGE_KEYS,
  validateRulesConfig,
  normalizeRulesConfig,
  type RulesConfig,
} from '~/utils/rulesConfig';
import { buildRulesPayload, gameFormatOf, serverValidationDetail } from '~/utils/rulesWizard';
import { effectiveRosterLimits } from '~/utils/rosterLimits';
import { isRosterLockActive, latestPublishedVersion } from '~/utils/rosterLock';
import {
  advanceAfterSave,
  resolveNotice,
  type AdvanceDecision,
  type AdvanceTarget,
} from '~/utils/sectionAdvance';
import { createWizardDraftStore, type WizardStorage } from '~/utils/wizardDraft';
import { resolveNavigation } from '~/utils/wizardStep';
import type { WizardKind } from '~/utils/wizardModel';

import type { ConfigurationData, VersionSummary, VersionDetail, StageSummary, TeamSummary, RosterSummary, MatchSummary } from '~/components/workspace/setup/types';
import { useTournamentSetupCrests } from '~/composables/useTournamentSetupCrests';
import { useTournamentSetupRules } from '~/composables/useTournamentSetupRules';

export function useTournamentSetup(tournamentId: string) {
  const route = useRoute();
  const router = useRouter();
  const auth = useAuthStore();
  const tournamentsStore = useTournamentsStore();
  const { request } = useApi();
  const { t, statusLabel, errorMessage } = useI18n();
  const { confirm } = useConfirm({ singleFlight: true });

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

  useHead(() => ({
    title: `${t('shell.configuration')} | Bracket Craft`,
    meta: [{ name: 'robots', content: 'noindex, nofollow' }],
  }));

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

  async function continueAfterNotice(): Promise<void> {
    const target = pendingAdvance.value;
    if (!target) return;
    await executeAdvance(resolveNotice({ kind: 'wait', target }, 'continue'));
  }

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
  async function onVersionChange(event: Event): Promise<void> {
    const select = event.target as HTMLSelectElement;
    const next = select.value;
    select.value = selectedVersionId.value;
    if (next === selectedVersionId.value) return;

    const accepted = hasWizardChanges.value && import.meta.client
      ? await confirm({ title: t('confirm.changeVersion.title'), message: t('wizard.navigation.confirmVersion'), confirmLabel: t('confirm.changeVersion.action'), tone: 'danger' })
      : hasWizardChanges.value;
    const effect = resolveNavigation('version', hasWizardChanges.value, accepted);
    if (!effect.proceed) {
      select.value = selectedVersionId.value;
      return;
    }
    if (effect.discardDraft) clearWizardDrafts(selectedVersionId.value);
    selectedVersionId.value = next;
    select.value = next;
    // RF-016: cambiar de versión descarta el aviso y el salto armado.
    clearPendingAdvance();
    if (effect.discardDraft) wizardResetToken.value += 1;
  }

  // Cambiar de torneo con cambios sin guardar pide confirmación; recargar,
  // cambiar de sección o el botón atrás dentro del asistente no pasan por aquí
  // (mismo torneo) o conservan el borrador de la pestaña.
  onBeforeRouteLeave(async (to) => {
    const targetId = typeof to.params.id === 'string' ? to.params.id : '';
    const otherTournament = to.path.startsWith('/workspace/tournaments/')
      && Boolean(targetId)
      && targetId !== tournamentId;
    if (!otherTournament || !hasWizardChanges.value) return true;

    const accepted = import.meta.client
      ? await confirm({ title: t('confirm.leaveTournament.title'), message: t('wizard.navigation.confirmTournament'), confirmLabel: t('confirm.leaveTournament.action'), tone: 'danger' })
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

  async function useDefaultRules() {
    if (!rulesEditable.value) return;
    if (import.meta.client && !(await confirm({ title: t('confirm.replaceRules.title'), message: t('setup.confirmReplaceRules'), confirmLabel: t('confirm.replaceRules.action'), tone: 'danger' }))) return;
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

  const services = { auth, request, t, confirm, tournamentId, redirectOnSessionFailure, failureMessage };
  const { crestBusyTeamId, crestStatusMessage, crestErrors, crestInputVersions, crestInputId, crestErrorId, onCrestFileSelected, removeCrest } = useTournamentSetupCrests({ ...services, teams, canManageTournaments });

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

  async function onTeamsSaved(): Promise<void> {
    void refreshConfiguration();
    await executeAdvance(advanceAfterSave({
      section: 'teams',
      effective: true,
      notice: false,
      tournamentId,
    }));
  }

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
    if (import.meta.client && !(await confirm({ title: t('confirm.publish.title'), message: t('workspace.confirmPublish'), confirmLabel: t('confirm.publish.action'), tone: 'danger' }))) return;
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

  const { minutesImpactBeforeSave } = useTournamentSetupRules({ auth, request, serverRulesConfig, selectedVersionMatches });

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
      if (import.meta.client && !(await confirm({ title: t('confirm.saveRules.title'), message, confirmLabel: t('confirm.saveRules.action'), tone: 'primary' }))) return;
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
  return { auth, tournamentId, t, statusLabel, tournamentName, tournamentLabel, loading, loadError, error, saving,
  versions, selectedVersionId, draftVersion, activeVersion, canManageTournaments, canPublish, configurationReadOnly,
  rulesEditable, declaredGameFormat, setupChecks, rulesConfig, serverRulesConfig, selectedVersionStages,
  rulesServerDetail, rulesError, rulesMinutesNotice, wizardResetToken, wizardDirty, rulesTitle, teamsTitle,
  teams, selectedVersionRosterLimits, rosterCountsByTeam, rosterLockActive,
  onVersionChange, publishVersion, createDraftVersion, retryConfiguration, useDefaultRules,
  updateRulesConfig, saveRules, continueAfterNotice, stayAfterNotice, onTeamsSaved, onStagesConfirmed, refreshConfiguration,
  fetchConfiguration, applyConfiguration, redirectOnSessionFailure, failureMessage, crestBusyTeamId, crestStatusMessage, crestErrors, crestInputVersions, crestInputId, crestErrorId, onCrestFileSelected, removeCrest };
}
