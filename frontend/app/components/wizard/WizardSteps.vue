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
  <nav class="wizard-steps" :aria-label="t('wizard.indexLabel')">
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
  gap: 0.5rem;
  align-content: start;
}

.wizard-step-count {
  margin: 0;
  color: var(--muted);
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.wizard-step-list {
  display: grid;
  gap: 0.35rem;
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
  gap: 0.15rem 0.6rem;
  width: 100%;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--line);
  border-radius: 0.75rem;
  background: transparent;
  color: var(--ink);
  text-align: left;
}

.wizard-step-button:hover:not(:disabled) {
  border-color: var(--accent);
  background: rgba(212, 243, 106, 0.06);
}

.wizard-step-button[aria-current='step'] {
  border-color: var(--accent);
  background: rgba(212, 243, 106, 0.1);
  box-shadow: inset 0 0 0 1px var(--accent);
}

.wizard-step-index {
  grid-area: index;
  align-self: center;
  color: var(--muted);
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
  color: var(--muted);
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.wizard-step-state {
  grid-area: state;
  align-self: center;
  padding: 0.15rem 0.45rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  font-size: 0.7rem;
  white-space: nowrap;
}

.wizard-step-button.is-complete .wizard-step-state {
  border-color: var(--accent);
  color: var(--accent);
}

.wizard-step-button.is-error .wizard-step-state {
  border-color: var(--danger);
  color: var(--danger);
}

.wizard-step-button.is-omitted .wizard-step-state,
.wizard-step-button.is-alternative .wizard-step-state {
  border-style: dashed;
}
</style>
