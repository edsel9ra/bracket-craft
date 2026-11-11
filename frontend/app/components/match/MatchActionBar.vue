<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import type { MatchPrimaryAction } from '~/utils/matchPrimaryAction';

defineProps<{ action: MatchPrimaryAction | null; disabled: boolean; busy: boolean }>();
const emit = defineEmits<{ activate: [action: MatchPrimaryAction] }>();
const { t } = useI18n();
const textFocused = shallowRef(false);
let frame = 0;
function updateFocus() {
  const element = document.activeElement;
  textFocused.value = element instanceof HTMLElement && (element.matches('textarea, input:not([type="button"]):not([type="submit"]):not([type="reset"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="color"])') || element.isContentEditable);
}
function deferFocus() { cancelAnimationFrame(frame); frame = requestAnimationFrame(updateFocus); }
onMounted(() => {
  updateFocus();
  document.addEventListener('focusin', updateFocus);
  document.addEventListener('focusout', deferFocus);
});
onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
  document.removeEventListener('focusin', updateFocus);
  document.removeEventListener('focusout', deferFocus);
});
</script>

<template>
  <div v-show="action && !textFocused" class="match-action-bar" :aria-label="t('match.primaryAction')" role="region">
    <Button v-if="action" :disabled="disabled" :busy="busy" @click="emit('activate', action)">{{ t(action.labelKey) }}</Button>
  </div>
</template>

<style scoped>
.match-action-bar { display: none; }
@media (width < 760px) {
  .match-action-bar { position: fixed; z-index: 35; inset: auto 0 0; display: grid; padding: var(--space-3) var(--space-4) calc(var(--space-3) + env(safe-area-inset-bottom)); border-top: 1px solid var(--color-muted); background: var(--color-surface); }
}
@media (prefers-reduced-motion: reduce) { .match-action-bar { transition: none; } }
</style>
