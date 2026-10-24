<script setup lang="ts">
/**
 * Asistente de fases (spec 012, RF-002, RF-006, RF-010; AT-1).
 *
 * Identificación → composición opcional (0..64) → revisión. Al confirmar crea la
 * fase con `POST /stages` y **después** inscribe con `POST /stages/{id}/teams`.
 * No hay atomicidad: si la inscripción falla, la fase queda creada y visible, el
 * asistente muestra el guardado parcial con los equipos que quedaron fuera y
 * ofrece reintentar sobre esa misma fase. El reintento usa `planStageRetry`, que
 * no contiene ningún paso de creación.
 *
 * Todas las llamadas pasan por `useApi()`. El modelo puro (`utils/stageWizard.ts`)
 * decide la secuencia, la validación y los mensajes; este componente solo
 * ejecuta y muestra.
 */
import { STAGE_FORMATS } from '~/constants/stageFormats';
import { firstStageByOrder, nextStageOrder, openExistingStage, planStageCreation, planStageRetry, reviewStage, sortStagesByOrder, stageConfirmation, stageCreateFailure, stageSaveFailed, stageSaveSucceeded, stageTeamPath, stageTeamsPath, stagesPath, stageWizardStatuses, validateStageValues, MAX_STAGE_TEAMS, type StageCreateFailure, type StageIssue, type StageSaveResult, type StageWizardValues } from '~/utils/stageWizard';
import { availableStageTeams, normalizeStageTeamsResponse, pruneStageTeamSelection, sortStageTeams, type StageTeamSummary, type StageTeamsResponse } from '~/utils/stageTeams';
import {
  ROSTER_STATE_OK,
  describeRosterSize,
  explainRosterEnrollment,
  rosterSizeState,
  type RosterLimits,
  type RosterSizeDescription,
} from '~/utils/rosterLimits';
import { resolveNavigation } from '~/utils/wizardStep';
import { useWizardStep } from '~/composables/useWizardStep';
import { useWizardDraft } from '~/composables/useWizardDraft';
import { draftForStep } from '~/utils/wizardDraft';

interface StageOption {
  id: string;
  name: string;
  stage_type: string;
  stage_order: number;
  tournament_version_id?: string;
}

interface TeamOption {
  team_id: string;
  name: string;
  short_code: string;
  stage_ids?: string[];
}

const props = withDefaults(defineProps<{
  tournamentId: string;
  versionId: string;
  /** Fases de la versión seleccionada. */
  stages?: StageOption[];
  /** Equipos registrados en el torneo. */
  teams?: TeamOption[];
  /** Límites efectivos de la versión seleccionada (0 = sin límite). */
  rosterLimits?: RosterLimits;
  /** Jugadores activos por equipo, contados en el torneo. */
  rosterCounts?: Record<string, number>;
  /** Cierre de inscripción por jornada activo (RL-1/RA-1). */
  lockActive?: boolean;
  disabled?: boolean;
  busy?: boolean;
  /** Cambia cuando la página descarta el borrador por versión o torneo (RF-008). */
  resetToken?: number;
}>(), {
  stages: () => [],
  teams: () => [],
  rosterLimits: () => ({ min: 0, max: 0 }),
  rosterCounts: () => ({}),
  lockActive: false,
  disabled: false,
  busy: false,
  resetToken: 0,
});

const emit = defineEmits<{
  saved: [];
  reload: [];
  'dirty-change': [value: boolean];
}>();

const { request } = useApi();
const { t, stageTypeLabel, errorMessage } = useI18n();
const auth = useAuthStore();

const formatOptions = computed(() => STAGE_FORMATS.map((format) => ({
  value: format.value,
  label: t(format.labelKey),
  description: t(format.descriptionKey),
})));
const sortedStages = computed(() => sortStagesByOrder(props.stages));

const mode = ref<'create' | 'existing'>(props.stages.length ? 'existing' : 'create');
const selectedStageId = ref(firstStageByOrder(props.stages)?.id ?? '');
const form = reactive({
  name: '',
  stageOrder: nextStageOrder(props.stages) as number | string,
  stageType: STAGE_FORMATS[0].value as string,
  teamIds: [] as string[],
});

const existing = computed(() => (
  mode.value === 'existing' ? openExistingStage(props.stages, selectedStageId.value) : null
));

const values = computed<StageWizardValues>(() => (existing.value
  ? {
    name: existing.value.identity.name,
    stageOrder: existing.value.identity.stageOrder,
    stageType: existing.value.identity.stageType,
    teamIds: form.teamIds,
  }
  : {
    name: form.name,
    stageOrder: form.stageOrder,
    stageType: form.stageType,
    teamIds: form.teamIds,
  }));

const issues = computed(() => validateStageValues(values.value));
const statuses = computed(() => stageWizardStatuses(values.value, issues.value, t));
const confirmation = computed(() => stageConfirmation(values.value, issues.value, t));
const review = computed(() => reviewStage({
  mode: mode.value,
  stageId: existing.value?.stageId ?? null,
  values: values.value,
}));
const confirmLabel = computed(() => (
  mode.value === 'existing' ? 'stage.wizard.confirmAssign' : 'stage.wizard.confirmCreate'
));

// RF-046: estado de la plantilla de cada equipo con los límites efectivos de la
// versión. Es informativo y **no** bloquea la edición de la plantilla; el único
// bloqueo que se anticipa aquí es el de la inscripción de la fase.
const rosterCount = (teamId: string): number => props.rosterCounts[teamId] ?? 0;
const teamName = (teamId: string): string => {
  const fromProps = props.teams.find((team) => team.team_id === teamId);
  if (fromProps) return fromProps.name;
  const fromStage = [...(stageTeams.value?.assigned ?? []), ...(stageTeams.value?.unassigned ?? [])]
    .find((team) => team.team_id === teamId);
  return fromStage?.name ?? teamId;
};
const teamSizes = computed(() => {
  const sizes = new Map<string, RosterSizeDescription>();
  const ids = new Set<string>([
    ...props.teams.map((team) => team.team_id),
    ...(stageTeams.value?.assigned ?? []).map((team) => team.team_id),
    ...(stageTeams.value?.unassigned ?? []).map((team) => team.team_id),
  ]);
  for (const id of ids) {
    sizes.set(id, describeRosterSize(rosterCount(id), props.rosterLimits, t));
  }
  return sizes;
});

function teamSize(teamId: string): RosterSizeDescription {
  return teamSizes.value.get(teamId)
    ?? describeRosterSize(rosterCount(teamId), props.rosterLimits, t);
}

// RF-046: con un equipo fuera de rango la inscripción de la composición está
// bloqueada y el mensaje explica qué falta con el equipo, el rango y la
// cantidad actual. La selección se conserva para reintentar tras corregir la
// plantilla; en el alta de fase la creación no se bloquea (AT-1), de modo que
// el servidor devuelve su 409 y la fase queda visible para el reintento.
const enrollmentExplanations = computed(() => review.value.teamIds
  .filter((teamId) => rosterSizeState(rosterCount(teamId), props.rosterLimits) !== ROSTER_STATE_OK)
  .map((teamId) => explainRosterEnrollment({
    teamId,
    teamName: teamName(teamId),
    count: rosterCount(teamId),
    limits: props.rosterLimits,
    lockActive: props.lockActive,
  }, t)));
const enrollmentBlocked = computed(() => enrollmentExplanations.value.length > 0);

// En una fase existente confirmar sin equipos no escribiría nada; en el alta sí
// es válido crear la fase sin composición (RF-002, RF-006).
const confirmDisabled = computed(() => (
  !confirmation.value.ok
  || (mode.value === 'existing' && (review.value.teamIds.length === 0 || enrollmentBlocked.value))
));

const { step, blocked, previous, next, goTo } = useWizardStep({
  wizard: 'phases',
  // RF-015: la composición depende de que exista la fase; en el alta la aporta
  // la identificación, así que solo se bloquea sin nombre ni fase elegida.
  data: () => ({
    stageId: mode.value === 'existing'
      ? selectedStageId.value
      : (form.name.trim() ? 'new-stage' : ''),
  }),
  // RF-002: trabajar sobre una fase existente abre directamente su composición;
  // el alta empieza por la identificación. Es el paso de entrada, no un cambio.
  entryStep: () => (mode.value === 'existing' ? 'phases.composition' : 'phases.identity'),
  // RF-014: el borrador de la pestaña aporta el paso de entrada al recargar.
  draftStep: () => draft.read()?.step ?? null,
});

/** Mensaje del campo, en el idioma activo; vacío cuando el campo es válido. */
function fieldError(field: StageIssue['field']): string {
  const issue = issues.value.find((candidate) => candidate.field === field);
  return issue ? t(issue.messageKey) : '';
}

const draft = useWizardDraft({
  wizard: 'phases',
  userId: () => auth.userId,
  organizationId: () => auth.organizationId,
  tournamentId: () => props.tournamentId,
  versionId: () => props.versionId,
});

const stageTeams = ref<StageTeamsResponse | null>(null);
const teamsLoading = ref(false);
const teamsError = ref<string | null>(null);
const saving = ref(false);
const notice = ref<string | null>(null);
const errorText = ref<string | null>(null);
const partial = ref<StageSaveResult | null>(null);
const createFailure = ref<StageCreateFailure | null>(null);
const createdStageId = ref<string | null>(null);

const assignedTeams = computed<StageTeamSummary[]>(() => stageTeams.value?.assigned ?? []);
const availableTeams = computed<StageTeamSummary[]>(() => {
  if (mode.value === 'existing') return availableStageTeams(stageTeams.value);
  return sortStageTeams(props.teams.map((team) => ({
    team_id: team.team_id,
    name: team.name,
    short_code: team.short_code,
  })));
});
const pendingTeams = computed(() => {
  const ids = new Set(partial.value?.pendingTeamIds ?? []);
  return props.teams
    .filter((team) => ids.has(team.team_id))
    .map((team) => `${team.name} (${team.short_code})`);
});

/**
 * Cambios sin guardar del asistente (RF-008). En el alta son los datos de la
 * fase nueva; en una fase existente, la selección de equipos pendiente de
 * inscribir o el guardado parcial que espera reintento. Elegir una fase para
 * mirarla no es un cambio.
 */
const dirty = computed(() => Boolean(
  (mode.value === 'create' && (form.name.trim() || form.teamIds.length))
  || form.teamIds.length
  || partial.value
  || createdStageId.value,
));

/** Descarte explícito: confirma, vuelve a los valores del servidor y limpia el borrador. */
function discardChanges(): void {
  if (props.disabled || !dirty.value) return;
  const accepted = import.meta.client
    ? window.confirm(t('wizard.navigation.confirmDiscard'))
    : true;
  const effect = resolveNavigation('discard', dirty.value, accepted);
  if (!effect.proceed) return;
  restoreServerValues();
}

function restoreServerValues(): void {
  partial.value = null;
  createFailure.value = null;
  createdStageId.value = null;
  notice.value = null;
  errorText.value = null;
  teamsError.value = null;
  const nextMode: 'create' | 'existing' = props.stages.length ? 'existing' : 'create';
  mode.value = nextMode;
  selectedStageId.value = firstStageByOrder(props.stages)?.id ?? '';
  resetCreateForm();
  draft.clear();
  if (nextMode === 'existing') void loadStageTeams();
}

function persistDraft(): void {
  if (props.disabled) return;
  // RF-014: sin cambios se recuerda solo el paso; con cambios, paso y valores.
  draft.save(draftForStep(step.value, {
    mode: mode.value,
    selectedStageId: selectedStageId.value,
    name: form.name,
    stageOrder: form.stageOrder,
    stageType: form.stageType,
    teamIds: [...form.teamIds],
    // RF-010: el borrador conserva la fase creada para reintentar tras recargar.
    partialStageId: partial.value?.stageId ?? createdStageId.value ?? null,
    pendingTeamIds: [...(partial.value?.pendingTeamIds ?? [])],
  }, dirty.value));
}

async function loadStageTeams(): Promise<void> {
  if (mode.value !== 'existing' || !selectedStageId.value) {
    stageTeams.value = null;
    return;
  }
  teamsLoading.value = true;
  teamsError.value = null;
  try {
    const data = await request<unknown>(stageTeamsPath(props.tournamentId, selectedStageId.value));
    const normalized = normalizeStageTeamsResponse(data);
    stageTeams.value = normalized;
    form.teamIds = pruneStageTeamSelection(form.teamIds, availableStageTeams(normalized));
  } catch (cause) {
    stageTeams.value = null;
    teamsError.value = errorMessage(cause, t('setup.stageTeamsLoadError'));
  } finally {
    teamsLoading.value = false;
  }
}

function setMode(nextMode: string): void {
  const target = nextMode === 'existing' && props.stages.length ? 'existing' : 'create';
  if (target === mode.value) return;
  mode.value = target;
  goTo(target === 'existing' ? 'phases.composition' : 'phases.identity');
  if (target === 'existing') void loadStageTeams();
}

function onModeChange(event: Event): void {
  setMode((event.target as HTMLSelectElement).value);
}

function resetCreateForm(): void {
  form.name = '';
  form.teamIds = [];
  form.stageOrder = nextStageOrder(props.stages);
  form.stageType = STAGE_FORMATS[0].value;
}

/**
 * `POST /stages/{id}/teams` sobre una fase conocida. `mode` decide el mensaje:
 * `create` (tras crear la fase), `existing` (composición de una fase ya hecha) o
 * `retry` (reintento del guardado parcial).
 */
async function assignTeams(
  stageId: string,
  teamIds: string[],
  assignMode: 'create' | 'existing' | 'retry',
): Promise<void> {
  try {
    const data = await request<unknown>(stageTeamsPath(props.tournamentId, stageId), {
      method: 'POST',
      body: { team_ids: teamIds },
    });
    const result = stageSaveSucceeded({
      mode: assignMode === 'create' ? 'create' : assignMode === 'existing' ? 'existing' : 'retry',
      stageId,
      requestedTeamIds: teamIds,
      response: data,
    });
    partial.value = result.canRetry ? result : null;
    notice.value = result.messageKey;
    form.teamIds = result.pendingTeamIds;
    if (!result.canRetry) createdStageId.value = null;
    if (result.canRetry) return;
    draft.clear();
    if (assignMode !== 'existing') resetCreateForm();
    emit('saved');
    if (assignMode !== 'create') await loadStageTeams();
  } catch (cause) {
    partial.value = stageSaveFailed({ stageId, requestedTeamIds: teamIds, cause });
    errorText.value = errorMessage(cause, t('stage.wizard.partial'));
    // La fase ya existe: refresca la lista para que sea identificable (RF-010).
    emit('saved');
  }
}

async function createStage(): Promise<void> {
  const plan = planStageCreation({ versionId: props.versionId, values: values.value });
  const createStep = plan.steps[0];
  if (!createStep || createStep.kind !== 'create_stage') return;

  try {
    const created = await request<{ id?: unknown }>(stagesPath(props.tournamentId), {
      method: 'POST',
      body: createStep.body,
    });
    const stageId = typeof created?.id === 'string' ? created.id : '';
    if (!stageId) {
      // Respuesta sin identificador: el mismo caso ambiguo que una respuesta perdida.
      createFailure.value = stageCreateFailure(null);
      errorText.value = t(createFailure.value.messageKey);
      return;
    }
    createdStageId.value = stageId;
    const assignStep = plan.steps[1];
    if (!assignStep || assignStep.kind !== 'assign_teams') {
      notice.value = 'stage.wizard.createdWithoutTeams';
      // No hay inscripción pendiente: la fase no queda como borrador abierto.
      createdStageId.value = null;
      draft.clear();
      resetCreateForm();
      emit('saved');
      return;
    }
    await assignTeams(stageId, assignStep.teamIds, 'create');
  } catch (cause) {
    const failure = stageCreateFailure(cause);
    createFailure.value = failure;
    errorText.value = `${t(failure.messageKey)} ${errorMessage(cause, '')}`.trim();
  }
}

async function confirm(): Promise<void> {
  if (props.disabled || props.busy || saving.value) return;
  if (!confirmation.value.ok) {
    const first = confirmation.value.blockedBy[0];
    if (first) goTo(first);
    return;
  }
  if (mode.value === 'existing' && review.value.teamIds.length === 0) return;
  saving.value = true;
  notice.value = null;
  errorText.value = null;
  partial.value = null;
  createFailure.value = null;
  try {
    if (mode.value === 'existing' && existing.value) {
      await assignTeams(existing.value.stageId, review.value.teamIds, 'existing');
    } else {
      await createStage();
    }
  } finally {
    saving.value = false;
  }
}

/** Reintento del guardado parcial: solo la inscripción sobre la fase conocida. */
async function retryAssign(): Promise<void> {
  if (props.disabled || props.busy || saving.value) return;
  const stageId = partial.value?.stageId ?? createdStageId.value;
  if (!stageId) return;

  const plan = planStageRetry({ stageId, teamIds: review.value.teamIds });
  const assignStep = plan.steps[0];
  if (!assignStep || assignStep.kind !== 'assign_teams') {
    notice.value = 'stage.wizard.createdWithoutTeams';
    draft.clear();
    emit('saved');
    return;
  }
  const targetStageId = assignStep.stageId;
  if (!targetStageId) return;

  saving.value = true;
  errorText.value = null;
  try {
    await assignTeams(targetStageId, assignStep.teamIds, 'retry');
  } finally {
    saving.value = false;
  }
}

async function removeTeam(teamId: string): Promise<void> {
  if (props.disabled || saving.value || !existing.value) return;
  saving.value = true;
  notice.value = null;
  errorText.value = null;
  try {
    await request(stageTeamPath(props.tournamentId, existing.value.stageId, teamId), { method: 'DELETE' });
    notice.value = 'setup.stageTeamsRemoved';
    form.teamIds = form.teamIds.filter((id) => id !== teamId);
    emit('saved');
    await loadStageTeams();
  } catch (cause) {
    errorText.value = errorMessage(cause, t('setup.stageTeamsRemoveError'));
  } finally {
    saving.value = false;
  }
}

function requestReload(): void {
  createFailure.value = null;
  errorText.value = null;
  emit('reload');
}

watch(selectedStageId, () => {
  form.teamIds = [];
  // La composición es una lectura: también se carga en solo lectura para que
  // el observador vea los equipos inscritos (RF-038).
  void loadStageTeams();
});

watch(() => props.stages, (nextStages) => {
  if (!nextStages.length) {
    mode.value = 'create';
    selectedStageId.value = '';
    return;
  }
  if (!nextStages.some((stage) => stage.id === selectedStageId.value)) {
    selectedStageId.value = firstStageByOrder(nextStages)?.id ?? '';
  }
  if (!form.name.trim()) form.stageOrder = nextStageOrder(nextStages);
}, { deep: true });

watch(
  [
    mode,
    selectedStageId,
    step,
    () => form.name,
    () => form.stageOrder,
    () => form.stageType,
    () => form.teamIds,
    partial,
    createdStageId,
  ],
  persistDraft,
  { deep: true },
);

watch(dirty, (value) => emit('dirty-change', value), { immediate: true });
watch(() => props.resetToken, () => {
  if (!props.disabled) restoreServerValues();
});

onMounted(() => {
  if (mode.value !== 'existing') return;
  void loadStageTeams();
});

draft.applyAfterMount((stored) => {
  // Un borrador con solo paso no aporta valores: mandan los del servidor.
  if (!stored || !stored.values || props.disabled) return;
  const saved = stored.values;
  const wantsExisting = saved.mode === 'existing' && props.stages.length > 0;
  mode.value = wantsExisting ? 'existing' : 'create';
  if (wantsExisting && typeof saved.selectedStageId === 'string') selectedStageId.value = saved.selectedStageId;
  if (typeof saved.name === 'string') form.name = saved.name;
  if (typeof saved.stageOrder === 'number' || typeof saved.stageOrder === 'string') form.stageOrder = saved.stageOrder;
  if (typeof saved.stageType === 'string') form.stageType = saved.stageType;
  if (Array.isArray(saved.teamIds)) {
    form.teamIds = saved.teamIds.filter((id): id is string => typeof id === 'string');
  }
  const restoredStageId = typeof saved.partialStageId === 'string' ? saved.partialStageId : null;
  const restoredPending = Array.isArray(saved.pendingTeamIds)
    ? saved.pendingTeamIds.filter((id): id is string => typeof id === 'string')
    : [];
  if (restoredStageId && restoredPending.length) {
    partial.value = {
      status: 'partial',
      stageId: restoredStageId,
      pendingTeamIds: restoredPending,
      messageKey: 'stage.wizard.partial',
      canRetry: true,
      verifyByReload: false,
    };
    createdStageId.value = restoredStageId;
  }
  if (mode.value === 'existing') void loadStageTeams();
});
</script>

<template>
  <section class="panel stage-wizard-panel" :aria-busy="saving || busy">
    <WizardShell
      wizard="phases"
      :title="t('stage.wizard.title')"
      :statuses="statuses"
      :current="step"
      :read-only="disabled"
      :busy="busy || saving"
      @update:current="goTo"
    >
      <p class="field-hint">{{ t('stage.wizard.description') }}</p>
      <p class="muted-note">{{ t('stage.wizard.calendarNotice') }}</p>

      <div class="stage-wizard-mode">
        <label>
          {{ t('stage.wizard.mode') }}
          <select :value="mode" :disabled="disabled || saving" @change="onModeChange">
            <option v-if="stages.length" value="existing">{{ t('stage.wizard.modeExisting') }}</option>
            <option value="create">{{ t('stage.wizard.modeCreate') }}</option>
          </select>
        </label>
        <label v-if="mode === 'existing'">
          {{ t('stage.wizard.selectStage') }}
          <select v-model="selectedStageId" :disabled="saving">
            <option v-for="stage in sortedStages" :key="stage.id" :value="stage.id">
              {{ stage.stage_order }}. {{ stage.name }}
            </option>
          </select>
        </label>
      </div>

      <template v-if="step === 'phases.identity'">
        <div v-if="existing" class="stage-identity-readonly">
          <p class="field-hint">{{ t('stage.wizard.existingIdentityHint') }}</p>
          <dl>
            <div><dt>{{ t('workspace.name') }}</dt><dd>{{ existing.identity.name }}</dd></div>
            <div><dt>{{ t('setup.type') }}</dt><dd>{{ stageTypeLabel(existing.identity.stageType) }}</dd></div>
            <div><dt>{{ t('setup.order') }}</dt><dd>{{ existing.identity.stageOrder }}</dd></div>
          </dl>
        </div>
        <template v-else>
          <label>
            {{ t('workspace.name') }}
            <input
              v-model="form.name"
              :disabled="disabled || saving"
              :aria-invalid="Boolean(fieldError('name'))"
              minlength="2"
              maxlength="50"
              required
            />
            <span v-if="fieldError('name')" class="field-error" role="alert">{{ fieldError('name') }}</span>
          </label>
          <label>
            {{ t('setup.type') }}
            <select
              v-model="form.stageType"
              :disabled="disabled || saving"
              :aria-invalid="Boolean(fieldError('stageType'))"
            >
              <option v-for="format in formatOptions" :key="format.value" :value="format.value" :title="format.description">
                {{ format.label }}
              </option>
            </select>
            <span v-if="fieldError('stageType')" class="field-error" role="alert">{{ fieldError('stageType') }}</span>
            <span class="field-hint">{{ formatOptions.find((format) => format.value === form.stageType)?.description }}</span>
          </label>
          <label>
            {{ t('setup.order') }}
            <input
              v-model.number="form.stageOrder"
              :disabled="disabled || saving"
              :aria-invalid="Boolean(fieldError('stageOrder'))"
              type="number"
              min="1"
              required
            />
            <span v-if="fieldError('stageOrder')" class="field-error" role="alert">{{ fieldError('stageOrder') }}</span>
          </label>
        </template>
      </template>

      <template v-else-if="step === 'phases.composition'">
        <p v-if="blocked" class="wizard-blocked">
          {{ t(blocked.messageKey) }}
          <button type="button" class="stage-wizard-link" @click="goTo(blocked.provider)">
            {{ t(blocked.actionKey) }}
          </button>
        </p>
        <template v-else>
          <p class="field-hint">{{ t('setup.stageTeamsHint') }}</p>
          <p class="muted-note">{{ t('stage.wizard.teamCount', { count: review.teamCount, max: MAX_STAGE_TEAMS }) }}</p>
          <p v-if="fieldError('teamIds')" class="field-error" role="alert">{{ fieldError('teamIds') }}</p>

          <div v-if="mode === 'existing'" class="stage-team-group">
            <p class="eyebrow">{{ t('setup.assignedTeams') }}</p>
            <ul v-if="assignedTeams.length" class="stage-team-list">
              <li v-for="team in assignedTeams" :key="`assigned-${team.team_id}`">
                <span class="stage-team-name">
                  {{ team.name }} <small>{{ team.short_code }}</small>
                  <small class="team-size">{{ teamSize(team.team_id).label }} · {{ teamSize(team.team_id).detail }}</small>
                </span>
                <button
                  class="button-secondary stage-team-remove"
                  type="button"
                  :disabled="disabled || saving"
                  @click="removeTeam(team.team_id)"
                >{{ t('setup.removeTeam') }}</button>
              </li>
            </ul>
            <p v-else class="muted-note">{{ t('setup.noAssignedTeams') }}</p>
          </div>

          <div class="stage-team-group">
            <p class="eyebrow">
              {{ mode === 'existing' ? t('setup.availableTeams') : t('stage.wizard.compositionTeams') }}
            </p>
            <div v-if="availableTeams.length" class="stage-team-options">
              <label v-for="team in availableTeams" :key="`available-${team.team_id}`" class="checkbox-label">
                <input
                  v-model="form.teamIds"
                  type="checkbox"
                  :value="team.team_id"
                  :disabled="disabled || saving"
                />
                <span>{{ team.name }} <small>{{ team.short_code }}</small></span>
                <small class="team-size">{{ teamSize(team.team_id).label }} · {{ teamSize(team.team_id).detail }}</small>
              </label>
            </div>
            <p v-else class="muted-note">
              {{ mode === 'existing' ? t('setup.noAvailableTeams') : t('stage.wizard.noTeams') }}
            </p>
            <p v-if="mode === 'existing' && !review.teamIds.length && availableTeams.length" class="muted-note">
              {{ t('stage.wizard.needSelection') }}
            </p>
          </div>

          <p v-if="teamsLoading" class="muted-note" role="status">{{ t('common.loading') }}</p>
          <p v-if="teamsError" class="form-error" role="alert">{{ teamsError }}</p>
        </template>
      </template>

      <template v-else>
        <dl class="stage-review">
          <div><dt>{{ t('workspace.name') }}</dt><dd>{{ review.name }}</dd></div>
          <div><dt>{{ t('setup.type') }}</dt><dd>{{ t(review.stageTypeLabelKey) }}</dd></div>
          <div><dt>{{ t('setup.order') }}</dt><dd>{{ review.stageOrder ?? '—' }}</dd></div>
          <div>
            <dt>{{ t('stage.wizard.composition') }}</dt>
            <dd>{{ t('stage.wizard.teamCount', { count: review.teamCount, max: MAX_STAGE_TEAMS }) }}</dd>
          </div>
        </dl>
        <ul class="stage-warnings">
          <li v-for="key in review.warningKeys" :key="key">{{ t(key) }}</li>
        </ul>
      </template>

      <div v-if="enrollmentExplanations.length" class="stage-enrollment-block" role="status">
        <strong>{{ t('stage.wizard.enrollmentBlocked') }}</strong>
        <ul>
          <li v-for="explanation in enrollmentExplanations" :key="explanation.teamId">
            {{ explanation.message }}
          </li>
        </ul>
        <span class="field-hint">{{ t(lockActive ? 'stage.wizard.enrollmentLockedHint' : 'stage.wizard.enrollmentBlockedHint') }}</span>
      </div>
      <p v-if="errorText" class="form-error" role="alert">{{ errorText }}</p>
      <div v-if="partial" class="stage-partial" role="alert">
        <strong>{{ t(partial.messageKey) }}</strong>
        <span v-if="partial.pendingTeamIds.length">
          {{ t('stage.wizard.pending', { count: partial.pendingTeamIds.length }) }}
        </span>
        <ul v-if="pendingTeams.length">
          <li v-for="name in pendingTeams" :key="name">{{ name }}</li>
        </ul>
      </div>
      <p v-if="notice" class="muted-note" role="status">{{ t(notice) }}</p>

      <template #actions="{ goTo: goToStep }">
        <button
          type="button"
          class="button-secondary"
          :disabled="!previous"
          @click="previous && goToStep(previous)"
        >{{ t('wizard.previous') }}</button>
        <button
          type="button"
          class="button-secondary"
          :disabled="!next"
          @click="next && goToStep(next)"
        >{{ t('wizard.next') }}</button>
        <button
          v-if="!disabled"
          type="button"
          class="button-secondary"
          :disabled="saving || busy || !dirty"
          @click="discardChanges"
        >{{ t('wizard.navigation.discard') }}</button>
        <button
          v-if="partial?.canRetry && !disabled"
          type="button"
          class="button-primary"
          :disabled="saving || busy"
          @click="retryAssign"
        >{{ saving ? t('common.saving') : t('stage.wizard.retryAssign') }}</button>
        <button
          v-else-if="createFailure?.reloadStages"
          type="button"
          class="button-secondary"
          :disabled="saving || busy"
          @click="requestReload"
        >{{ t('stage.wizard.reloadStages') }}</button>
        <button
          v-else-if="!disabled"
          type="button"
          class="button-primary"
          :disabled="saving || busy || confirmDisabled"
          @click="confirm"
        >{{ saving || busy ? t('common.saving') : t(confirmLabel) }}</button>
      </template>
    </WizardShell>
  </section>
</template>

<style scoped>
.stage-wizard-panel {
  display: grid;
  gap: 14px;
}

.stage-wizard-mode {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}

.stage-wizard-mode label {
  display: grid;
  gap: 7px;
  color: var(--muted);
  font-size: 0.82rem;
}

.stage-wizard-mode select,
.stage-wizard-panel input[type='number'],
.stage-wizard-panel input[type='text'],
.stage-wizard-panel input:not([type]) {
  min-width: 0;
  padding: 0.82rem 0.9rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #0c0f0c;
  color: var(--ink);
}

.stage-identity-readonly dl,
.stage-review {
  display: grid;
  gap: 8px;
  margin: 0;
}

.stage-identity-readonly dl > div,
.stage-review > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line);
}

.stage-identity-readonly dt,
.stage-review dt {
  color: var(--muted);
  font-size: 0.8rem;
}

.stage-identity-readonly dd,
.stage-review dd {
  margin: 0;
  color: var(--ink);
  font-weight: 600;
}

.stage-team-group {
  display: grid;
  gap: 8px;
}

.stage-team-list {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.stage-team-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.stage-team-list small,
.stage-team-options small {
  color: var(--muted);
  font-size: 0.72rem;
}

.stage-team-name {
  display: grid;
  gap: 2px;
}

.team-size {
  color: var(--muted);
  font-size: 0.7rem;
}

.stage-enrollment-block {
  display: grid;
  gap: 5px;
  padding: 0.7rem 0.9rem;
  border: 1px solid rgba(255, 203, 122, 0.3);
  border-radius: 0.75rem;
  background: rgba(255, 203, 122, 0.06);
  color: #ffcb7a;
  font-size: 0.82rem;
}

.stage-enrollment-block ul {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 1.1rem;
}

.stage-team-remove {
  padding: 5px 9px;
  font-size: 0.72rem;
}

.stage-team-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px 14px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink);
}

.checkbox-label input {
  width: auto;
}

.stage-warnings {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0.6rem 0.9rem 0.6rem 1.4rem;
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  color: var(--muted);
  font-size: 0.82rem;
}

.stage-partial {
  display: grid;
  gap: 4px;
  padding: 0.7rem 0.9rem;
  border: 1px solid var(--danger);
  border-radius: 0.75rem;
  color: var(--danger);
  font-size: 0.82rem;
}

.stage-partial ul {
  margin: 0;
  padding-left: 1.2rem;
}

.stage-wizard-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: inherit;
  text-decoration: underline;
}

.field-error {
  margin: 0;
  color: #ffb0a8;
  font-size: 0.78rem;
}

.wizard-blocked {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}

.form-error {
  margin: 0;
  color: #ffb0a8;
  font-size: 0.85rem;
}
</style>
