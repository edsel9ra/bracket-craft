<script setup lang="ts">
import { nextTick, ref } from 'vue';
import Button from '~/components/ui/Button.vue';
import { runShare, type ShareOutcome } from '~/utils/publicShare';

const props = defineProps<{
  label: string;
  title: string;
  url: string;
}>();

const { t } = useI18n();
const fieldId = `${useId()}-share-url`;
const busy = ref(false);
const outcome = ref<ShareOutcome | null>(null);
const field = ref<HTMLInputElement | null>(null);

const MESSAGES: Partial<Record<ShareOutcome, string>> = {
  shared: 'share.shared',
  copied: 'share.copied',
  manual: 'share.manual',
};

async function share() {
  if (busy.value) return;
  busy.value = true;
  outcome.value = null;
  try {
    outcome.value = await runShare({ title: props.title, url: props.url }, import.meta.client ? window.navigator : undefined);
  } finally {
    busy.value = false;
  }
  if (outcome.value === 'manual') {
    await nextTick();
    field.value?.focus();
    field.value?.select();
  }
}
</script>

<template>
  <div class="share">
    <Button variant="secondary" :busy="busy" @click="share">{{ label }}</Button>
    <p class="share-status" aria-live="polite">{{ outcome && MESSAGES[outcome] ? t(MESSAGES[outcome]!) : '' }}</p>
    <div v-if="outcome === 'manual'" class="share-manual">
      <label :for="fieldId">{{ t('share.manualLabel') }}</label>
      <input
        :id="fieldId"
        ref="field"
        type="text"
        readonly
        :value="url"
        @focus="field?.select()"
      >
    </div>
  </div>
</template>

<style scoped>
.share { display: grid; gap: var(--space-2); justify-items: start; }
.share-status { margin: 0; min-height: 1lh; color: var(--color-muted); font-size: var(--text-xs); }
.share-status:empty { min-height: 0; }
.share-manual { display: grid; gap: var(--space-1); width: 100%; }
.share-manual label { font-size: var(--text-xs); font-weight: 700; }
.share-manual input { width: 100%; padding: var(--space-2); border: 1px solid var(--color-muted); border-radius: var(--radius-sm); background: var(--color-canvas); color: var(--color-ink); font: inherit; }
.share-manual input:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
</style>
