<script setup lang="ts">
/**
 * Asistente de equipos (spec 012, RF-003, RF-006, RF-011, RF-021; IN-1).
 *
 * Datos del equipo → vía de alta alternativa (individual **o** carga masiva) →
 * revisión. El alta **no** pide ni envía fase: la inscripción vive solo en el
 * asistente de fases, al que este enlaza después de confirmar. La vía no elegida
 * conserva lo escrito (radio y CSV) sin contar como completa, de modo que la
 * confirmación exige exactamente una.
 *
 * Todas las llamadas pasan por `useApi()`. El modelo puro (`utils/teamsWizard.ts`)
 * decide la validación, los estados y los cuerpos; este componente solo ejecuta,
 * conserva el borrador de la pestaña y muestra.
 */
import {
  MAX_BULK_TEAMS,
  columnLabelKey,
  parseTeamCsv,
  phasesAssistantHref,
  planTeamCreation,
  restoreTeamValues,
  reviewTeams,
  showsEntryPathStep,
  teamConfirmation,
  teamDraftValues,
  teamWizardStatuses,
  validateTeamValues,
  type TeamEntryPath,
  type TeamIssue,
  type TeamWizardValues,
} from '~/utils/teamsWizard';
import { resolveNavigation } from '~/utils/wizardStep';
import { useWizardStep } from '~/composables/useWizardStep';
import { useWizardDraft } from '~/composables/useWizardDraft';
import { draftForStep } from '~/utils/wizardDraft';

const props = withDefaults(defineProps<{
  tournamentId: string;
  versionId: string;
  disabled?: boolean;
  busy?: boolean;
  /** Cambia cuando la página descarta el borrador por versión o torneo (RF-008). */
  resetToken?: number;
}>(), {
  disabled: false,
  busy: false,
  resetToken: 0,
});

const emit = defineEmits<{
  saved: [];
  'dirty-change': [value: boolean];
}>();

const { request } = useApi();
const { t, errorMessage } = useI18n();
const auth = useAuthStore();

const form = reactive({
  name: '',
  shortCode: '',
  entryPath: null as TeamEntryPath | null,
  bulkCsv: '',
  bulkFileName: '',
});

const values = computed<TeamWizardValues>(() => ({
  name: form.name,
  shortCode: form.shortCode,
  entryPath: form.entryPath,
  bulkCsv: form.bulkCsv,
  bulkFileName: form.bulkFileName,
}));

const issues = computed(() => validateTeamValues(values.value));
const statuses = computed(() => teamWizardStatuses(values.value, issues.value, t));
const confirmation = computed(() => teamConfirmation(values.value, issues.value, t));
const review = computed(() => reviewTeams(values.value));
const bulkPreview = computed(() => parseTeamCsv(form.bulkCsv));
const phasesHref = computed(() => phasesAssistantHref(props.tournamentId));
const bulkColumns = 'name,short_code,logo_url';
const bulkColumnsHint = computed(() => t('setup.csvHint', { columns: bulkColumns }));

/** Problemas de una fila concreta, con su fila y su columna. */
const rowIssues = computed(() => issues.value.filter(
  (issue) => issue.stepId === 'teams.bulk' && typeof issue.row === 'number' && issue.row > 0,
));
/** Problemas del archivo completo (vacío, solo encabezados, demasiadas filas). */
const fileIssues = computed(() => issues.value.filter(
  (issue) => issue.stepId === 'teams.bulk' && (issue.row ?? 0) === 0,
));

const saving = ref(false);
const notice = ref<string | null>(null);
const errorText = ref<string | null>(null);
const fileError = ref<string | null>(null);
const csvFileInput = ref<HTMLInputElement | null>(null);

const draft = useWizardDraft({
  wizard: 'teams',
  userId: () => auth.userId,
  organizationId: () => auth.organizationId,
  tournamentId: () => props.tournamentId,
  versionId: () => props.versionId,
});

const { step, previous, next, goTo } = useWizardStep({
  wizard: 'teams',
  // RF-014: el borrador aporta el paso de entrada al recargar o al volver de
  // otra sección; solo se lee al montar, porque después manda la dirección.
  draftStep: () => draft.read()?.step ?? null,
  // RF-011: cambiar de paso conserva el CSV y lo escrito en la otra vía.
  onStepChange: () => persistDraft(),
});

function hasChanges(): boolean {
  return Boolean(
    form.name.trim()
    || form.shortCode.trim()
    || form.bulkCsv.trim()
    || form.entryPath,
  );
}

/** Cambios sin guardar del asistente, para confirmar el descarte (RF-008). */
const dirty = computed(() => hasChanges());

function persistDraft(): void {
  if (props.disabled) return;
  // RF-014: sin cambios se recuerda solo el paso; con cambios, paso y valores.
  draft.save(draftForStep(step.value, teamDraftValues(values.value), hasChanges()));
}

/** Mensaje del campo, en el idioma activo; vacío cuando el campo es válido. */
function fieldError(field: TeamIssue['field']): string {
  const issue = issues.value.find((candidate) => candidate.field === field);
  return issue ? t(issue.messageKey) : '';
}

/** Mensaje de una fila del CSV: identifica la fila y la columna. */
function rowIssueMessage(issue: TeamIssue): string {
  const column = issue.column ? t(columnLabelKey(issue.column)) : t(columnLabelKey('file'));
  return t('teams.wizard.rowError', {
    row: issue.row ?? 0,
    column,
    reason: t(issue.messageKey, issue.params ?? {}),
  });
}

function choosePath(path: TeamEntryPath): void {
  if (props.disabled || saving.value) return;
  form.entryPath = path;
  errorText.value = null;
  // RF-011: la vía elegida es la que se muestra; la otra queda oculta y sus
  // valores se conservan para cuando el usuario vuelva a elegirla.
  void goTo(path === 'individual' ? 'teams.individual' : 'teams.bulk');
}

async function loadCsvFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  fileError.value = null;
  if (!file) return;
  if (!/\.(csv|txt)$/i.test(file.name)) {
    fileError.value = t('setup.csvFileType');
    input.value = '';
    return;
  }
  try {
    form.bulkCsv = await file.text();
    form.bulkFileName = file.name;
    choosePath('bulk');
  } catch {
    fileError.value = t('setup.csvReadError');
    input.value = '';
  }
}

function clearCsvFile(): void {
  form.bulkCsv = '';
  form.bulkFileName = '';
  fileError.value = null;
  if (csvFileInput.value) csvFileInput.value.value = '';
}

function resetForm(): void {
  form.name = '';
  form.shortCode = '';
  form.entryPath = null;
  form.bulkCsv = '';
  form.bulkFileName = '';
  clearCsvFile();
}

/**
 * Descarte explícito (RF-008): confirma, restaura los valores del servidor
 * —un formulario vacío, porque el alta no tiene datos previos— y elimina el
 * borrador de la pestaña.
 */
function discardChanges(): void {
  if (props.disabled || !hasChanges()) return;
  const accepted = import.meta.client
    ? window.confirm(t('wizard.navigation.confirmDiscard'))
    : true;
  const effect = resolveNavigation('discard', hasChanges(), accepted);
  if (!effect.proceed) return;
  restoreServerValues();
}

function restoreServerValues(): void {
  resetForm();
  notice.value = null;
  errorText.value = null;
  fileError.value = null;
  draft.clear();
}

function createdMessage(count: number): string {
  return count > 1
    ? t('teams.wizard.createdBulk', { count })
    : t('teams.wizard.createdIndividual');
}

async function confirm(): Promise<void> {
  if (props.disabled || props.busy || saving.value) return;
  if (!confirmation.value.ok) {
    const first = confirmation.value.blockedBy[0];
    if (first) goTo(first);
    return;
  }

  const plan = planTeamCreation({ tournamentId: props.tournamentId, values: values.value });
  const stepToRun = plan.steps[0];
  if (!stepToRun) return;

  saving.value = true;
  notice.value = null;
  errorText.value = null;
  fileError.value = null;
  try {
    await request(stepToRun.path, {
      method: 'POST',
      body: stepToRun.body,
    });
    const count = stepToRun.kind === 'create_team'
      ? 1
      : (Array.isArray(stepToRun.body.teams) ? stepToRun.body.teams.length : 0);
    notice.value = createdMessage(count);
    draft.clear();
    resetForm();
    goTo('teams.entry');
    emit('saved');
  } catch (cause) {
    // RF-007: el rechazo no vacía el formulario ni cambia de paso.
    errorText.value = errorMessage(
      cause,
      t(review.value.path === 'bulk' ? 'setup.noImport' : 'setup.noTeam'),
    );
  } finally {
    saving.value = false;
  }
}

watch(
  [
    step,
    () => form.name,
    () => form.shortCode,
    () => form.entryPath,
    () => form.bulkCsv,
    () => form.bulkFileName,
  ],
  persistDraft,
);

watch(dirty, (value) => emit('dirty-change', value), { immediate: true });
watch(() => props.resetToken, () => {
  if (!props.disabled) restoreServerValues();
});

draft.applyAfterMount((stored) => {
  // Un borrador con solo paso no aporta valores: el alta empieza vacía.
  if (!stored || !stored.values || props.disabled) return;
  const saved = restoreTeamValues(stored.values);
  form.name = typeof saved.name === 'string' ? saved.name : '';
  form.shortCode = typeof saved.shortCode === 'string' ? saved.shortCode : '';
  form.entryPath = saved.entryPath === 'individual' || saved.entryPath === 'bulk' ? saved.entryPath : null;
  form.bulkCsv = typeof saved.bulkCsv === 'string' ? saved.bulkCsv : '';
  form.bulkFileName = typeof saved.bulkFileName === 'string' ? saved.bulkFileName : '';
});
</script>

<template>
  <section class="panel teams-wizard-panel" :aria-busy="saving || busy">
    <WizardShell
      wizard="teams"
      :title="t('teams.wizard.title')"
      :statuses="statuses"
      :current="step"
      :read-only="disabled"
      :busy="busy || saving"
      @update:current="goTo"
    >
      <p class="field-hint">{{ t('teams.wizard.description') }}</p>

      <template v-if="step === 'teams.entry'">
        <template v-if="showsEntryPathStep('teams.entry', form.entryPath)">
          <fieldset
            class="team-entry-path"
            :disabled="disabled || saving"
          >
            <legend>{{ t('teams.wizard.pathLegend') }}</legend>
            <label class="checkbox-label">
              <input
                type="radio"
                name="team-entry-path"
                value="individual"
                :checked="form.entryPath === 'individual'"
                @change="choosePath('individual')"
              />
              <span>{{ t('teams.wizard.pathIndividual') }}</span>
            </label>
            <label class="checkbox-label">
              <input
                type="radio"
                name="team-entry-path"
                value="bulk"
                :checked="form.entryPath === 'bulk'"
                @change="choosePath('bulk')"
              />
              <span>{{ t('teams.wizard.pathBulk') }}</span>
            </label>
            <p class="field-hint">{{ t('teams.wizard.pathHint') }}</p>
          </fieldset>
        </template>
        <p v-else class="field-hint">{{ t('teams.wizard.otherPathChosen') }}</p>
      </template>

      <template v-else-if="step === 'teams.details'">
        <p class="field-hint">{{ t('teams.wizard.detailsHint') }}</p>
        <label class="field">
          {{ t('workspace.name') }}
          <input
            v-model="form.name"
            :disabled="disabled || saving"
            :aria-invalid="Boolean(fieldError('name'))"
            minlength="2"
            maxlength="100"
            required
          />
          <span v-if="fieldError('name')" class="field-error" role="alert">{{ fieldError('name') }}</span>
        </label>
        <label class="field">
          {{ t('setup.code') }}
          <input
            v-model="form.shortCode"
            :disabled="disabled || saving"
            :aria-invalid="Boolean(fieldError('shortCode'))"
            minlength="2"
            maxlength="10"
            pattern="[A-Za-z0-9_\-]+"
            required
          />
          <span v-if="fieldError('shortCode')" class="field-error" role="alert">{{ fieldError('shortCode') }}</span>
        </label>
      </template>

      <template v-else-if="step === 'teams.individual'">
        <template v-if="showsEntryPathStep('teams.individual', form.entryPath)">
          <p class="field-hint">{{ t('teams.wizard.pathIndividualHint') }}</p>
          <p v-if="review.path === 'individual' && review.teams.length" class="team-entry-summary">
            {{ t('teams.wizard.individualReady', { name: review.teams[0]?.name ?? '', code: review.teams[0]?.short_code ?? '' }) }}
          </p>
          <p v-else class="muted-note">{{ t('teams.wizard.individualMissing') }}</p>
        </template>
        <p v-else class="field-hint">{{ t('teams.wizard.otherPathChosen') }}</p>
      </template>

      <template v-else-if="step === 'teams.bulk'">
        <template v-if="showsEntryPathStep('teams.bulk', form.entryPath)">
          <p class="field-hint">{{ bulkColumnsHint }}</p>
          <div class="csv-file-actions">
            <label class="button-secondary file-picker">
              {{ t('setup.chooseCsv') }}
              <input
                ref="csvFileInput"
                class="file-input"
                type="file"
                accept=".csv,.txt,text/csv,text/plain"
                :disabled="disabled || saving"
                @change="loadCsvFile"
              />
            </label>
            <span v-if="form.bulkFileName" class="csv-file-name">
              {{ t('setup.selectedFile', { name: form.bulkFileName }) }}
            </span>
            <button
              v-if="form.bulkFileName || form.bulkCsv"
              class="file-clear"
              type="button"
              :disabled="disabled || saving"
              @click="clearCsvFile"
            >{{ t('setup.clearFile') }}</button>
          </div>
          <label class="field">
            {{ t('teams.wizard.pasteCsv') }}
            <textarea
              v-model="form.bulkCsv"
              :disabled="disabled || saving"
              :aria-invalid="Boolean(fieldError('bulkCsv'))"
              rows="6"
              :placeholder="t('teams.wizard.csvPlaceholder')"
              @input="form.bulkFileName = ''"
            />
          </label>
          <p v-if="fileError" class="form-error" role="alert">{{ fileError }}</p>
          <p v-for="issue in fileIssues" :key="`file-${issue.messageKey}`" class="form-error" role="alert">
            {{ t(issue.messageKey, issue.params ?? {}) }}
          </p>
          <ul v-if="rowIssues.length" class="team-csv-issues" role="alert">
            <li v-for="issue in rowIssues" :key="`row-${issue.row}-${issue.column}`">
              {{ rowIssueMessage(issue) }}
            </li>
          </ul>
          <p class="muted-note">
            {{ t('teams.wizard.parsedRows', { count: bulkPreview.rows.length, max: MAX_BULK_TEAMS }) }}
          </p>
        </template>
        <p v-else class="field-hint">{{ t('teams.wizard.otherPathChosen') }}</p>
      </template>

      <template v-else>
        <dl class="team-review">
          <div>
            <dt>{{ t('teams.wizard.pathLabel') }}</dt>
            <dd>{{ review.path ? t(review.pathLabelKey) : t('teams.wizard.pathNone') }}</dd>
          </div>
          <div>
            <dt>{{ t('teams.wizard.countLabel') }}</dt>
            <dd>{{ review.count }}</dd>
          </div>
        </dl>
        <ul v-if="review.teams.length" class="team-review-list">
          <li v-for="team in review.teams" :key="`${team.name}-${team.short_code}`">
            <span>{{ team.name }}</span>
            <small>{{ team.short_code }}</small>
          </li>
        </ul>
        <ul class="team-warnings">
          <li v-for="key in review.warningKeys" :key="key">{{ t(key) }}</li>
        </ul>
      </template>

      <p v-if="errorText" class="form-error" role="alert">{{ errorText }}</p>
      <p v-if="notice" class="team-created" role="status">
        {{ notice }}
        <a :href="phasesHref">{{ t('teams.wizard.goToPhases') }}</a>
      </p>

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
          v-if="!disabled"
          type="button"
          class="button-primary"
          :disabled="saving || busy || !confirmation.ok"
          @click="confirm"
        >{{ saving || busy ? t('common.saving') : t('teams.wizard.confirm') }}</button>
      </template>
    </WizardShell>
  </section>
</template>

<style scoped>
.teams-wizard-panel {
  display: grid;
  gap: 14px;
}

.teams-wizard-panel input:not([type='radio']):not([type='file']) {
  min-width: 0;
  padding: 0.82rem 0.9rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #0c0f0c;
  color: var(--ink);
}

.team-entry-path {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.team-entry-path legend {
  padding: 0 6px;
  color: var(--muted);
  font-size: 0.78rem;
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

.team-entry-summary {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--ink);
  font-size: 0.88rem;
}

.csv-file-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.file-picker {
  position: relative;
  justify-content: center;
  cursor: pointer;
  font-size: 0.78rem;
}

.file-picker:focus-within {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

.file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.csv-file-name {
  min-width: 0;
  overflow: hidden;
  color: var(--muted);
  font-size: 0.78rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-clear {
  padding: 4px 0;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-size: 0.75rem;
}

.file-clear:hover {
  color: var(--danger);
}

.team-csv-issues {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 1.2rem;
  color: #ffb0a8;
  font-size: 0.82rem;
}

.team-review {
  display: grid;
  gap: 8px;
  margin: 0;
}

.team-review > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--line);
}

.team-review dt {
  color: var(--muted);
  font-size: 0.8rem;
}

.team-review dd {
  margin: 0;
  color: var(--ink);
  font-weight: 600;
}

.team-review-list {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.team-review-list li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.team-review-list small {
  color: var(--muted);
  font-size: 0.72rem;
}

.team-warnings {
  display: grid;
  gap: 4px;
  margin: 0;
  padding: 0.6rem 0.9rem 0.6rem 1.4rem;
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  color: var(--muted);
  font-size: 0.82rem;
}

.team-created {
  margin: 0;
  color: var(--accent);
  font-size: 0.85rem;
}

.team-created a {
  color: var(--accent);
  text-decoration: underline;
}

.field-error,
.form-error {
  margin: 0;
  color: #ffb0a8;
  font-size: 0.82rem;
}

textarea {
  width: 100%;
  resize: vertical;
  padding: 0.8rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #0c0f0c;
  color: var(--ink);
  font: inherit;
  line-height: 1.5;
}

textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 4px var(--accent-glow);
  outline: none;
}
</style>
