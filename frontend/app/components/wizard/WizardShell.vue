<script setup lang="ts">
import {
  canConfirm,
  nextStepId,
  previousStepId,
  stepStateLabelKey,
  type WizardKind,
  type WizardStepId,
  type WizardStepStatus,
} from '~/utils/wizardModel';

const props = withDefaults(defineProps<{
  wizard: WizardKind;
  title: string;
  statuses: WizardStepStatus[];
  current: WizardStepId;
  readOnly?: boolean;
  busy?: boolean;
}>(), {
  readOnly: false,
  busy: false,
});

const emit = defineEmits<{
  'update:current': [stepId: WizardStepId];
  confirm: [];
}>();

const { t } = useI18n();

const headingId = computed(() => `wizard-title-${props.wizard}`);
const stepTitleId = computed(() => `wizard-step-title-${props.wizard}`);
const stepTitle = ref<HTMLElement | null>(null);
const announcement = ref('');

const currentIndex = computed(() => {
  const index = props.statuses.findIndex((step) => step.id === props.current);
  return index < 0 ? 0 : index;
});
const currentStatus = computed(
  () => props.statuses.find((step) => step.id === props.current) ?? null,
);
const currentLabel = computed(() => currentStatus.value?.label ?? '');
const currentStateLabel = computed(
  () => (currentStatus.value ? t(stepStateLabelKey(currentStatus.value.state)) : ''),
);
const previousId = computed(() => previousStepId(props.wizard, props.current));
const nextId = computed(() => nextStepId(props.wizard, props.current));
const confirmation = computed(() => canConfirm(props.wizard, props.statuses));
const blockedLabels = computed(() => confirmation.value.blockedBy.map((id) => (
  props.statuses.find((step) => step.id === id)?.label ?? id
)));
const blockedMessage = computed(() => t('wizard.blocked', { steps: blockedLabels.value.join(', ') }));
const confirmDisabled = computed(() => props.readOnly || props.busy || !confirmation.value.ok);

function describeStep(stepId: WizardStepId): string {
  const status = props.statuses.find((step) => step.id === stepId);
  if (!status) return '';
  const index = props.statuses.findIndex((step) => step.id === stepId);
  return t('wizard.announce', {
    current: index + 1,
    total: props.statuses.length,
    label: status.label,
    state: t(stepStateLabelKey(status.state)),
  });
}

function goTo(stepId: WizardStepId) {
  if (stepId === props.current) return;
  emit('update:current', stepId);
}

function requestConfirm() {
  if (props.readOnly || props.busy) return;
  if (!confirmation.value.ok) {
    const first = confirmation.value.blockedBy[0];
    if (first) goTo(first);
    return;
  }
  emit('confirm');
}

watch(() => props.current, async (stepId) => {
  announcement.value = describeStep(stepId);
  await nextTick();
  stepTitle.value?.focus();
});
</script>

<template>
  <section class="wizard-shell" :aria-labelledby="headingId">
    <header class="wizard-shell-header">
      <h2 :id="headingId" class="wizard-shell-title">{{ title }}</h2>
    </header>

    <p v-if="readOnly" class="wizard-readonly" role="status">{{ t('wizard.readOnly') }}</p>

    <div class="wizard-shell-body">
      <WizardSteps :steps="statuses" :current="current" @select="goTo" />

      <div class="wizard-step">
        <h3 :id="stepTitleId" ref="stepTitle" class="wizard-step-title" tabindex="-1">
          {{ currentLabel }}
        </h3>
        <p class="wizard-step-summary">{{ currentStateLabel }}</p>

        <div class="wizard-step-body">
          <slot />
        </div>

        <div class="wizard-step-actions">
          <slot
            name="actions"
            :confirmation="confirmation"
            :confirm-disabled="confirmDisabled"
            :go-to="goTo"
            :request-confirm="requestConfirm"
          >
            <button
              type="button"
              class="button-secondary"
              :disabled="!previousId"
              @click="previousId && goTo(previousId)"
            >{{ t('wizard.previous') }}</button>
            <button
              type="button"
              class="button-secondary"
              :disabled="!nextId"
              @click="nextId && goTo(nextId)"
            >{{ t('wizard.next') }}</button>
            <button
              v-if="!readOnly"
              type="button"
              class="button-primary"
              :disabled="confirmDisabled"
              @click="requestConfirm"
            >{{ t('wizard.confirm') }}</button>
          </slot>
        </div>

        <p v-if="!readOnly && !confirmation.ok" class="wizard-blocked">
          {{ blockedMessage }}
        </p>
      </div>
    </div>

    <p class="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
      {{ announcement }}
    </p>
  </section>
</template>

<style scoped>
.wizard-shell {
  display: grid;
  gap: 1rem;
}

.wizard-shell-title {
  margin: 0;
  font-size: clamp(1.25rem, 2vw, 1.6rem);
}

.wizard-shell-body {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}

.wizard-step {
  display: grid;
  gap: 0.75rem;
  padding: 1.1rem;
  border: 1px solid var(--line);
  border-radius: 1rem;
  background: var(--surface);
}

.wizard-step-title {
  margin: 0;
  font-size: 1.15rem;
}

.wizard-step-title:focus {
  outline: 2px solid var(--accent);
  outline-offset: 3px;
  border-radius: 0.35rem;
}

.wizard-step-summary {
  margin: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

.wizard-step-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: flex-end;
}

.wizard-blocked {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}

.wizard-readonly {
  margin: 0;
  padding: 0.6rem 0.9rem;
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  color: var(--muted);
  font-size: 0.85rem;
}

@media (max-width: 900px) {
  .wizard-shell-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
