<script setup lang="ts">
import {
  obligationLabelKey,
  stepStateLabelKey,
  type WizardStepId,
  type WizardStepStatus,
} from '~/utils/wizardModel';

const props = defineProps<{
  steps: WizardStepStatus[];
  current: WizardStepId;
  label: string;
}>();

const emit = defineEmits<{
  select: [stepId: WizardStepId];
}>();

const { t } = useI18n();

const list = ref<HTMLOListElement | null>(null);
const visibleSteps = computed(() =>
  props.steps.filter((step) => step.showInIndex === true || step.id === props.current),
);
const currentIndex = computed(() => {
  const index = visibleSteps.value.findIndex((step) => step.id === props.current);
  return index < 0 ? 0 : index;
});

function focusStepAt(index: number) {
  const buttons = list.value?.querySelectorAll<HTMLButtonElement>('.wizard-step-button');
  const target = buttons ? buttons[index] : undefined;
  if (target) target.focus();
}

function onStepKeydown(event: KeyboardEvent, index: number) {
  const last = visibleSteps.value.length - 1;
  let target: number;
  switch (event.key) {
    case 'ArrowRight':
    case 'ArrowDown':
      target = Math.min(index + 1, last);
      break;
    case 'ArrowLeft':
    case 'ArrowUp':
      target = Math.max(index - 1, 0);
      break;
    case 'Home':
      target = 0;
      break;
    case 'End':
      target = last;
      break;
    default:
      return;
  }
  event.preventDefault();
  focusStepAt(target);
}
</script>

<template>
  <nav class="wizard-steps" :aria-label="`${t('wizard.indexLabel')}: ${label}`">
    <p class="wizard-step-count">
      {{ t('wizard.stepCount', { current: currentIndex + 1, total: visibleSteps.length }) }}
    </p>
    <ol ref="list" class="wizard-step-list">
      <li v-for="(step, index) in visibleSteps" :key="step.id" class="wizard-step-item">
        <button
          type="button"
          class="wizard-step-button"
          :class="`is-${step.state}`"
          :aria-current="step.id === current ? 'step' : undefined"
          @click="emit('select', step.id)"
          @keydown="onStepKeydown($event, index)"
        >
          <span class="wizard-step-index" aria-hidden="true">{{ index + 1 }}</span>
          <span class="wizard-step-label">{{ step.label }}</span>
          <span class="wizard-step-obligation">{{ t(obligationLabelKey(step.obligation)) }}</span>
          <span class="wizard-step-state">{{ t(stepStateLabelKey(step.state)) }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.wizard-steps {
  display: grid;
  gap: var(--space-2);
  align-content: start;
}

.wizard-step-count {
  margin: 0;
  color: var(--color-muted);
  font-size: var(--text-sm);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.wizard-step-list {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.wizard-step-button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  grid-template-areas:
    'index label state'
    'index obligation state';
  gap: var(--space-1) var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-ink);
  text-align: left;
}

.wizard-step-button:hover:not(:disabled) {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 6%, transparent);
}

.wizard-step-button[aria-current='step'] {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  box-shadow: inset 0 0 0 1px var(--color-accent);
}

.wizard-step-index {
  grid-area: index;
  align-self: center;
  color: var(--color-muted);
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}

.wizard-step-label {
  grid-area: label;
  font-weight: 600;
  line-height: 1.25;
}

.wizard-step-obligation {
  grid-area: obligation;
  color: var(--color-muted);
  font-size: var(--text-2xs);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.wizard-step-state {
  grid-area: state;
  align-self: center;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-pill);
  color: var(--color-muted);
  font-size: var(--text-2xs);
  white-space: nowrap;
}

.wizard-step-button.is-complete .wizard-step-state {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.wizard-step-button.is-error .wizard-step-state {
  border-color: var(--color-danger);
  color: var(--color-danger);
}

.wizard-step-button.is-omitted .wizard-step-state,
.wizard-step-button.is-alternative .wizard-step-state {
  border-style: dashed;
}
</style>
