<script setup lang="ts">
/**
 * Asistente de reglas (spec 012, RF-001, RF-004, RF-005, RF-006, RF-007, RF-009).
 *
 * Envuelve `RulesEditor` en pasos: no duplica sus controles ni su validación.
 * La validación sigue siendo `validateRulesConfig` (y el modo avanzado,
 * `parseRulesConfigJson`); este componente solo los agrupa por paso y decide
 * cuándo se puede confirmar. El guardado lo hace la página con
 * `buildRulesPayload` en una sola escritura con la configuración completa.
 */
import { DEFAULT_RULES_CONFIG, normalizeRulesConfig, validateRulesConfig, type RulesConfig, type RulesValidationError } from '~/utils/rulesConfig';
import {
  checkRulesSave,
  describeRulesIssue,
  rulesErrorsByStep,
  rulesIssues,
  rulesSectionForStep,
  rulesServerIssues,
  RULES_SECTIONS,
  rulesWizardStatuses,
  summaryFieldIssues,
  type RulesFieldIssue,
} from '~/utils/rulesWizard';
import { firstStepId } from '~/utils/wizardModel';
import type { RulesStepId } from '~/utils/wizardModel';
import { resolveNavigation, sameValues } from '~/utils/wizardStep';
import { useWizardStep } from '~/composables/useWizardStep';
import { useWizardDraft } from '~/composables/useWizardDraft';
import { draftForStep } from '~/utils/wizardDraft';

interface StageOption {
  id: string;
  name: string;
  stage_order?: number;
}

const props = withDefaults(defineProps<{
  modelValue?: RulesConfig | null;
  /** Valores vigentes en el servidor: punto de partida y comparación del borrador. */
  serverConfig?: RulesConfig | null;
  stages?: StageOption[];
  disabled?: boolean;
  busy?: boolean;
  /** La versión todavía no tiene configuración: primero se elige una. */
  saveDisabled?: boolean;
  tournamentId?: string | null;
  versionId?: string | null;
  /** Detalle de un 422 del servidor, para ubicar el campo por paso. */
  serverDetail?: readonly unknown[] | null;
  /**
   * Cambia cuando la página descarta el borrador (cambio de versión o de
   * torneo aceptado): el asistente vuelve a los valores del servidor (RF-008).
   */
  resetToken?: number;
}>(), {
  modelValue: null,
  serverConfig: null,
  stages: () => [],
  disabled: false,
  busy: false,
  saveDisabled: false,
  tournamentId: null,
  versionId: null,
  serverDetail: null,
  resetToken: 0,
});

const emit = defineEmits<{
  'update:modelValue': [value: RulesConfig];
  'dirty-change': [value: boolean];
  save: [];
}>();

const { t } = useI18n();
const auth = useAuthStore();

const workingConfig = computed<RulesConfig>(() => normalizeRulesConfig(props.modelValue || DEFAULT_RULES_CONFIG));
const serverConfig = computed<RulesConfig>(() => normalizeRulesConfig(props.serverConfig || DEFAULT_RULES_CONFIG));

const draft = useWizardDraft({
  wizard: 'rules',
  userId: () => auth.userId,
  organizationId: () => auth.organizationId,
  tournamentId: () => props.tournamentId,
  versionId: () => props.versionId,
});

const { step, previous, next, goTo } = useWizardStep({
  wizard: 'rules',
  // RF-014: el borrador de la pestaña aporta el paso de entrada al recargar o al
  // volver de otra sección; solo al montar, porque después manda la dirección.
  draftStep: () => draft.read()?.step ?? null,
  onStepChange: () => persistDraft(),
});

const jsonErrors = ref<RulesValidationError[]>([]);
const showAdvanced = ref(false);
const liveIssues = computed<RulesFieldIssue[]>(() => rulesIssues([
  ...validateRulesConfig(props.modelValue || DEFAULT_RULES_CONFIG),
  ...jsonErrors.value,
]));
const issues = computed<RulesFieldIssue[]>(() => ([
  ...liveIssues.value,
  ...rulesServerIssues(props.serverDetail),
]));
const groups = computed(() => rulesErrorsByStep(issues.value));
const statuses = computed(() => rulesWizardStatuses(workingConfig.value, t, issues.value));
const saveCheck = computed(() => checkRulesSave(workingConfig.value, issues.value, t));
const currentIssues = computed(() => groups.value.byStep[step.value as RulesStepId] ?? []);
const summaryIssues = computed(() => summaryFieldIssues(currentIssues.value));
const currentSection = computed(() => rulesSectionForStep(step.value));
const dirty = computed(() => !sameValues(
  workingConfig.value as unknown as Record<string, unknown>,
  serverConfig.value as unknown as Record<string, unknown>,
));
const blockedLabels = computed(() => saveCheck.value.blockedBy.map(
  (stepId) => statuses.value.find((entry) => entry.id === stepId)?.label ?? stepId,
));
const blockedMessage = computed(() => (blockedLabels.value.length
  ? t('wizard.blocked', { steps: blockedLabels.value.join(', ') })
  : t('rules.error.summary', { count: issues.value.length })));

let pendingSave = false;

function persistDraft(): void {
  if (props.disabled) return;
  // RF-014: sin cambios se recuerda solo el paso; con cambios, paso y valores.
  draft.save(draftForStep(
    step.value,
    workingConfig.value as unknown as Record<string, unknown>,
    dirty.value,
  ));
}

/**
 * Descarte explícito (RF-008): confirma, vuelve a los valores del servidor y
 * elimina el borrador de la pestaña. Es la misma operación que ejecuta la
 * página al aceptar un cambio de versión o de torneo.
 */
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
  jsonErrors.value = [];
  pendingSave = false;
  emit('update:modelValue', normalizeRulesConfig(props.serverConfig || DEFAULT_RULES_CONFIG));
  draft.clear();
}

function confirmSave(): void {
  if (props.disabled || props.busy || props.saveDisabled) return;
  if (!saveCheck.value.ok) {
    const first = saveCheck.value.blockedBy[0];
    if (first) goTo(first);
    return;
  }
  pendingSave = true;
  emit('save');
}

function onEditorValidation(errors: RulesValidationError[]): void {
  jsonErrors.value = [...errors];
}

watch(() => props.modelValue, persistDraft, { deep: true });
watch(step, () => persistDraft());
watch(dirty, (value) => emit('dirty-change', value), { immediate: true });
// Cambio de versión o de torneo aceptado por la página: se descarta el borrador
// del asistente y se cargan los valores del servidor de la versión nueva.
watch(() => props.resetToken, () => {
  if (!props.disabled) restoreServerValues();
});

// Guardado aceptado: la página reemplaza el valor por el del servidor; el
// borrador se descarta y el asistente vuelve al primer paso (RF-007).
watch(serverConfig, (next) => {
  if (!pendingSave) return;
  if (!sameValues(next as unknown as Record<string, unknown>, workingConfig.value as unknown as Record<string, unknown>)) return;
  pendingSave = false;
  draft.clear();
  const first = firstStepId('rules');
  if (first) goTo(first);
}, { deep: true });

draft.applyAfterMount((stored) => {
  // Un borrador con solo paso no aporta valores: mandan los del servidor.
  if (!stored || !stored.values || props.disabled) return;
  emit('update:modelValue', normalizeRulesConfig(stored.values));
});
</script>

<template>
  <div class="rules-wizard-shell">
    <div class="editor-mode" role="tablist" :aria-label="t('rules.editorMode')">
      <button
        class="mode-button"
        :class="{ active: !showAdvanced }"
        type="button"
        role="tab"
        :aria-selected="!showAdvanced"
        @click="showAdvanced = false"
      >{{ t('rules.visualMode') }}</button>
      <button
        class="mode-button"
        :class="{ active: showAdvanced }"
        type="button"
        role="tab"
        :aria-selected="showAdvanced"
        @click="showAdvanced = true"
      >{{ t('rules.jsonMode') }}</button>
    </div>
  <template v-if="!showAdvanced">
  <WizardShell
    wizard="rules"
    :title="t('rules.wizardTitle')"
    :statuses="statuses"
    :current="step"
    :read-only="disabled"
    :busy="busy"
    @update:current="goTo"
  >
    <p class="wizard-description">{{ t('rules.wizardDescription') }}</p>

    <ul v-if="groups.global.length" class="rules-errors" role="alert">
      <li v-for="(issue, index) in groups.global" :key="`global-${issue.code}-${index}`">
        {{ t(issue.messageKey) }}
      </li>
    </ul>

    <ul v-if="summaryIssues.length" class="rules-errors" role="alert">
      <li v-for="(issue, index) in summaryIssues" :key="`${issue.code}-${issue.path ?? index}`">
        {{ describeRulesIssue(issue, t) }}
      </li>
    </ul>

    <RulesEditor
      :model-value="modelValue"
      :sections="[currentSection]"
      :stages="stages"
      :disabled="disabled"
      :field-issues="currentIssues"
      :show-mode-toggle="false"
      :show-advanced="showAdvanced"
      @update:model-value="emit('update:modelValue', $event)"
      @update:show-advanced="showAdvanced = $event"
      @validation="onEditorValidation"
    />

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
        :disabled="busy || !dirty"
        @click="discardChanges"
      >{{ t('wizard.navigation.discard') }}</button>
      <button
        v-if="!disabled"
        type="button"
        class="button-primary"
        :disabled="busy || saveDisabled || !saveCheck.ok"
        @click="confirmSave"
      >{{ busy ? t('common.saving') : t('setup.saveRules') }}</button>
    </template>

    <p v-if="!disabled && !saveCheck.ok && !saveCheck.blockedBy.length" class="wizard-blocked">{{ blockedMessage }}</p>
  </WizardShell>
  </template>
  <RulesEditor
    v-else
    :model-value="modelValue"
    :sections="RULES_SECTIONS"
    :stages="stages"
    :disabled="disabled"
    :field-issues="[]"
    :show-mode-toggle="false"
    :show-advanced="true"
    @update:model-value="emit('update:modelValue', $event)"
    @validation="onEditorValidation"
  />
  </div>
</template>

<style scoped>
.wizard-description {
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

.rules-errors {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding: 0.7rem 0.9rem 0.7rem 1.6rem;
  border: 1px solid var(--danger);
  border-radius: 0.75rem;
  color: var(--danger);
  font-size: 0.82rem;
}

.wizard-blocked {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}

.editor-mode { display: inline-flex; width: fit-content; padding: 4px; border: 1px solid var(--line); border-radius: 999px; background: rgba(12, 15, 12, 0.45); margin-bottom: 12px; }
.mode-button { padding: 8px 13px; border-radius: 999px; background: transparent; color: var(--muted); font-size: 0.78rem; font-weight: 800; }
.mode-button.active { background: var(--accent); color: var(--accent-ink); }
</style>
