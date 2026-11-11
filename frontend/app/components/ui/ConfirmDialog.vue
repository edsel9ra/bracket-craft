<script setup lang="ts">
import Button from './Button.vue';
const { active, settle, cancelAll } = useConfirm();
const { t } = useI18n();
const id = useId();
const dialog = ref<HTMLDialogElement | null>(null);
const cancelButton = ref<{ $el: HTMLButtonElement } | null>(null);
const confirmButton = ref<{ $el: HTMLButtonElement } | null>(null);
let opener: HTMLElement | null = null;
let shownId: number | null = null;
let generation = 0;

function restoreFocus() {
  if (opener?.isConnected) opener.focus();
  opener = null;
}

async function updateDialog() {
  const version = ++generation;
  const element = dialog.value;
  if (!element) return;
  shownId = null;
  if (element.open) element.close();
  restoreFocus();
  const request = active.value;
  if (!request) return;
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  await nextTick();
  if (version !== generation || active.value?.id !== request.id) return;
  shownId = request.id;
  element.showModal();
  const target = request.options.tone === 'danger' ? cancelButton : confirmButton;
  target.value?.$el.focus();
}

watch(() => active.value?.id, updateDialog, { flush: 'post' });
onMounted(updateDialog);

function finish(value: boolean) {
  if (shownId !== null) settle(value, shownId);
}

function onNativeClose() {
  if (!dialog.value?.open) finish(false);
}

onBeforeUnmount(() => {
  generation++;
  shownId = null;
  dialog.value?.close();
  cancelAll();
  restoreFocus();
});
</script>

<template>
  <dialog ref="dialog" class="ui-confirm" :aria-labelledby="`${id}-title`" :aria-describedby="`${id}-message`" @cancel.prevent="finish(false)" @close="onNativeClose">
    <template v-if="active">
      <h2 :id="`${id}-title`">{{ active.options.title }}</h2>
      <p :id="`${id}-message`">{{ active.options.message }}</p>
      <div class="ui-confirm-actions">
        <Button ref="cancelButton" variant="secondary" @click="finish(false)">{{ t('common.cancel') }}</Button>
        <Button ref="confirmButton" :variant="active.options.tone === 'danger' ? 'danger' : 'primary'" @click="finish(true)">{{ active.options.confirmLabel || t('common.confirm') }}</Button>
      </div>
    </template>
  </dialog>
</template>

<style scoped>
.ui-confirm { width: min(100% - var(--space-8), 32rem); padding: var(--space-6); border: 1px solid var(--color-muted); border-radius: var(--radius-lg); background: var(--color-surface-raised); color: var(--color-ink); }
.ui-confirm[open] { animation: confirm-in 160ms ease-out; }
.ui-confirm::backdrop { background: var(--color-surface); opacity: 0.85; }
.ui-confirm h2 { margin: 0 0 var(--space-4); font-size: var(--text-lg); line-height: var(--leading-lg); }
.ui-confirm p { margin: 0 0 var(--space-6); font-size: var(--text-base); line-height: var(--leading-base); }
.ui-confirm-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-3); }
@keyframes confirm-in { from { opacity: 0; transform: translateY(var(--space-1)); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) { .ui-confirm[open] { animation: none; } }
:root[data-theme="light"] .ui-confirm::backdrop { background: color-mix(in srgb, var(--color-shadow) 32%, transparent); opacity: 1; }
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] .ui-confirm::backdrop { background: color-mix(in srgb, var(--color-shadow) 32%, transparent); opacity: 1; }
}
</style>
