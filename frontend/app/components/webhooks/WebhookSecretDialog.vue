<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue';
import Button from '~/components/ui/Button.vue';

const props = defineProps<{ secret: string | null }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const id = useId();
const dialog = ref<HTMLDialogElement | null>(null);
const title = ref<HTMLElement | null>(null);
const copyState = ref('');
let opener: HTMLElement | null = null;

async function open() {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  copyState.value = '';
  await nextTick();
  if (dialog.value && !dialog.value.open) dialog.value.showModal();
  title.value?.focus();
}

function hide() {
  copyState.value = '';
  if (dialog.value?.open) dialog.value.close();
  if (opener?.isConnected) opener.focus();
  opener = null;
}

watch(() => props.secret, (secret, previous) => {
  if (secret && !previous) void open();
  else if (!secret && previous) hide();
});
onBeforeUnmount(() => { if (dialog.value?.open) dialog.value.close(); });

async function copy() {
  if (!props.secret) return;
  try {
    await navigator.clipboard.writeText(props.secret);
    copyState.value = 'webhook.secret.copied';
  } catch {
    copyState.value = 'webhook.secret.copyFailed';
  }
}

function onNativeClose() { if (props.secret) emit('close'); }
</script>

<template>
  <dialog ref="dialog" class="webhook-secret" :aria-labelledby="`${id}-title`" :aria-describedby="`${id}-warning`" @cancel.prevent="emit('close')" @close="onNativeClose">
    <div v-if="secret" class="webhook-secret-body">
      <h2 :id="`${id}-title`" ref="title" tabindex="-1">{{ t('webhook.secret.title') }}</h2>
      <p :id="`${id}-warning`" class="webhook-secret-warning">{{ t('webhook.secret.warning') }}</p>
      <p class="webhook-secret-label">{{ t('webhook.secret.label') }}</p>
      <code class="webhook-secret-value">{{ secret }}</code>
      <p class="webhook-secret-status" role="status">{{ copyState ? t(copyState) : '' }}</p>
      <div class="webhook-secret-actions">
        <Button variant="secondary" @click="copy">{{ t('webhook.secret.copy') }}</Button>
        <Button @click="emit('close')">{{ t('webhook.secret.done') }}</Button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.webhook-secret { width: min(100% - var(--space-8), 40rem); max-height: calc(100dvh - var(--space-8)); padding: var(--space-6); border: 1px solid var(--color-muted); border-radius: var(--radius-lg); background: var(--color-surface-raised); color: var(--color-ink); }
.webhook-secret::backdrop { background: var(--color-surface); opacity: 0.85; }
.webhook-secret-body { display: grid; gap: var(--space-3); }
.webhook-secret h2 { margin: 0; font-size: var(--text-lg); line-height: var(--leading-lg); }
.webhook-secret-warning { margin: 0; color: var(--color-ink); font-weight: var(--weight-lg); }
.webhook-secret-label { margin: 0; color: var(--color-muted); font-size: var(--text-sm); line-height: var(--leading-sm); }
.webhook-secret-value { display: block; padding: var(--space-3); border: 1px solid var(--color-muted); border-radius: var(--radius-md); background: var(--color-surface); overflow-wrap: anywhere; user-select: all; }
.webhook-secret-status { min-height: var(--leading-sm); margin: 0; font-size: var(--text-sm); line-height: var(--leading-sm); }
.webhook-secret-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-3); }
</style>
