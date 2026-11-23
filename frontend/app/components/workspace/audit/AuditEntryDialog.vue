<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import Button from '~/components/ui/Button.vue';
import {
  auditActionLabelKey, auditActorLabel, auditEntityLabelKey, auditEntityLink, formatAuditValue, type AuditEntry,
} from '~/utils/organizationAudit';

const props = defineProps<{ entry: AuditEntry | null; permissions: readonly string[] }>();
const emit = defineEmits<{ close: [] }>();
const { t, formatDateTime, formatNumber } = useI18n();
const id = useId();
const dialog = ref<HTMLDialogElement | null>(null);
const title = ref<HTMLElement | null>(null);
const link = computed(() => (props.entry ? auditEntityLink(props.entry, props.permissions) : null));
let opener: HTMLElement | null = null;

async function open() {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  await nextTick();
  if (dialog.value && !dialog.value.open) dialog.value.showModal();
  title.value?.focus();
}

function hide() {
  if (dialog.value?.open) dialog.value.close();
  if (opener?.isConnected) opener.focus();
  opener = null;
}

watch(() => props.entry, (entry, previous) => {
  if (entry && !previous) void open();
  else if (!entry && previous) hide();
});
onBeforeUnmount(() => { if (dialog.value?.open) dialog.value.close(); });

function onNativeClose() { if (props.entry) emit('close'); }
function onBackdrop(event: MouseEvent) { if (event.target === event.currentTarget) emit('close'); }
</script>

<template>
  <dialog ref="dialog" class="audit-dialog" :aria-labelledby="`${id}-title`" @cancel.prevent="emit('close')" @close="onNativeClose" @click="onBackdrop">
    <div v-if="entry" class="audit-dialog-body">
      <header class="audit-dialog-header">
        <h2 :id="`${id}-title`" ref="title" tabindex="-1">{{ t('audit.detail.title') }}</h2>
        <Button variant="secondary" @click="emit('close')">{{ t('common.close') }}</Button>
      </header>
      <dl class="audit-summary">
        <div><dt>{{ t('audit.column.date') }}</dt><dd>{{ formatDateTime(entry.performed_at) }}</dd></div>
        <div><dt>{{ t('audit.column.action') }}</dt><dd>{{ t(auditActionLabelKey(entry.action)) }}</dd></div>
        <div>
          <dt>{{ t('audit.column.entity') }}</dt>
          <dd>
            {{ t(auditEntityLabelKey(entry.entity_type)) }}
            <NuxtLink v-if="link" :to="link" class="audit-id"><code>{{ entry.entity_id }}</code></NuxtLink>
            <code v-else class="audit-id">{{ entry.entity_id }}</code>
          </dd>
        </div>
        <div><dt>{{ t('audit.column.actor') }}</dt><dd>{{ auditActorLabel(entry.actor, t) }}</dd></div>
      </dl>
      <p v-if="!entry.cataloged || entry.details === null" class="audit-note">{{ t('audit.detail.uncataloged') }}</p>
      <p v-else-if="!entry.details.length" class="audit-note">{{ t('audit.detail.empty') }}</p>
      <dl v-else class="audit-details">
        <div v-for="detail in entry.details" :key="detail.key">
          <dt>{{ t(`audit.field.${detail.key}`) }}</dt>
          <dd>{{ formatAuditValue(detail.value, t, formatNumber) }}</dd>
        </div>
      </dl>
    </div>
  </dialog>
</template>

<style scoped>
.audit-dialog { width: min(100% - var(--space-8), 40rem); max-height: calc(100dvh - var(--space-8)); padding: var(--space-6); border: 1px solid var(--color-muted); border-radius: var(--radius-lg); background: var(--color-surface-raised); color: var(--color-ink); }
.audit-dialog::backdrop { background: var(--color-surface); opacity: 0.85; }
.audit-dialog-body { display: grid; gap: var(--space-4); }
.audit-dialog-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
.audit-dialog h2 { margin: 0; font-size: var(--text-lg); line-height: var(--leading-lg); }
.audit-summary, .audit-details { display: grid; gap: var(--space-3); margin: 0; }
.audit-summary div, .audit-details div { display: grid; gap: var(--space-1); }
.audit-summary dt, .audit-details dt { color: var(--color-muted); font-size: var(--text-sm); line-height: var(--leading-sm); font-weight: 600; }
.audit-summary dd, .audit-details dd { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.audit-id { display: block; overflow-wrap: anywhere; font-size: var(--text-sm); line-height: var(--leading-sm); }
.audit-note { margin: 0; color: var(--color-muted); }
:root[data-theme="light"] .audit-dialog::backdrop { background: color-mix(in srgb, var(--color-shadow) 32%, transparent); opacity: 1; }
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] .audit-dialog::backdrop { background: color-mix(in srgb, var(--color-shadow) 32%, transparent); opacity: 1; }
}
</style>
