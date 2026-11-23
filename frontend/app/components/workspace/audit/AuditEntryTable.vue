<script setup lang="ts">
import { computed } from 'vue';
import Button from '~/components/ui/Button.vue';
import DataTable from '~/components/ui/DataTable.vue';
import { auditActionLabelKey, auditActorLabel, auditEntityLabelKey, auditEntityLink, type AuditEntry } from '~/utils/organizationAudit';

const props = defineProps<{ entries: AuditEntry[]; permissions: readonly string[] }>();
const emit = defineEmits<{ open: [entry: AuditEntry] }>();
const { t, formatDateTime } = useI18n();
const columns = computed(() => [
  { key: 'date', label: t('audit.column.date'), rowHeader: true },
  { key: 'action', label: t('audit.column.action') },
  { key: 'entity', label: t('audit.column.entity') },
  { key: 'actor', label: t('audit.column.actor') },
]);
const rows = computed(() => props.entries.map((entry) => ({
  id: entry.id, entry,
  date: formatDateTime(entry.performed_at),
  action: t(auditActionLabelKey(entry.action)),
  entity: t(auditEntityLabelKey(entry.entity_type)),
  link: auditEntityLink(entry, props.permissions),
  actor: auditActorLabel(entry.actor, t),
})));
type Row = typeof rows.value[number];
</script>

<template>
  <DataTable class="audit-table" :caption="t('audit.table.caption')" :columns="columns" :rows="rows" row-key="id">
    <template #cell-action="{ row }">
      <Button variant="ghost" aria-haspopup="dialog" @click="emit('open', (row as Row).entry)">{{ (row as Row).action }}</Button>
    </template>
    <template #cell-entity="{ row }">
      <span class="audit-entity">
        <span>{{ (row as Row).entity }}</span>
        <NuxtLink v-if="(row as Row).link" :to="(row as Row).link!" class="audit-id"><code>{{ (row as Row).entry.entity_id }}</code></NuxtLink>
        <code v-else class="audit-id">{{ (row as Row).entry.entity_id }}</code>
      </span>
    </template>
  </DataTable>
</template>

<style scoped>
.audit-entity { display: grid; gap: var(--space-1); }
.audit-id { overflow-wrap: anywhere; font-size: var(--text-sm); line-height: var(--leading-sm); }
</style>
