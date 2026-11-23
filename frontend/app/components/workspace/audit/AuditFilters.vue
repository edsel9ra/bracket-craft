<script setup lang="ts">
import { ref, watch } from 'vue';
import Button from '~/components/ui/Button.vue';
import { AUDIT_ACTIONS, auditActionLabelKey, filtersFromQuery, type AuditActorOption, type AuditFilters } from '~/utils/organizationAudit';

const props = defineProps<{ filters: AuditFilters; actors: AuditActorOption[]; busy?: boolean }>();
const emit = defineEmits<{ apply: [filters: AuditFilters]; clear: [] }>();
const { t } = useI18n();
const id = useId();
const draft = ref<AuditFilters>({ ...props.filters, actions: [...props.filters.actions] });
const rangeError = ref(false);

watch(() => props.filters, (filters) => {
  draft.value = { ...filters, actions: [...filters.actions] };
  rangeError.value = false;
});

function submit() {
  rangeError.value = Boolean(draft.value.from && draft.value.to && draft.value.from > draft.value.to);
  if (rangeError.value) return;
  emit('apply', { ...draft.value, actions: [...draft.value.actions].sort(), page: 1 });
}

function clear() {
  draft.value = filtersFromQuery({});
  rangeError.value = false;
  emit('clear');
}
</script>

<template>
  <form class="audit-filters" :aria-label="t('audit.filters')" novalidate @submit.prevent="submit">
    <div class="field audit-actions">
      <label class="field-label" :for="`${id}-actions`">{{ t('audit.filter.actions') }}</label>
      <select :id="`${id}-actions`" v-model="draft.actions" multiple size="6" :aria-describedby="`${id}-actions-hint`">
        <option v-for="action in AUDIT_ACTIONS" :key="action" :value="action" :selected="draft.actions.includes(action)">{{ t(auditActionLabelKey(action)) }}</option>
      </select>
      <span :id="`${id}-actions-hint`" class="audit-hint">{{ t('audit.filter.actionsHint') }}</span>
    </div>
    <div class="audit-fields">
      <label class="field">
        <span class="field-label">{{ t('audit.filter.actor') }}</span>
        <select v-model="draft.actor">
          <option value="">{{ t('audit.filter.anyActor') }}</option>
          <option v-for="actor in actors" :key="actor.member_id" :value="actor.member_id" :selected="draft.actor === actor.member_id">{{ actor.name }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field-label">{{ t('audit.filter.from') }}</span>
        <input v-model="draft.from" type="date" :aria-invalid="rangeError || undefined" :aria-describedby="rangeError ? `${id}-range` : undefined">
      </label>
      <label class="field">
        <span class="field-label">{{ t('audit.filter.to') }}</span>
        <input v-model="draft.to" type="date" :aria-invalid="rangeError || undefined" :aria-describedby="rangeError ? `${id}-range` : undefined">
      </label>
    </div>
    <p v-if="rangeError" :id="`${id}-range`" class="audit-error" role="alert">{{ t('audit.filter.invalidRange') }}</p>
    <div class="audit-filter-actions">
      <Button type="submit" :busy="busy">{{ t('audit.filter.apply') }}</Button>
      <Button variant="secondary" :disabled="busy" @click="clear">{{ t('audit.filter.clear') }}</Button>
    </div>
  </form>
</template>

<style scoped>
.audit-filters { display: grid; gap: var(--space-4); }
.audit-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: var(--space-4); align-content: start; }
.audit-hint { font-size: var(--text-sm); line-height: var(--leading-sm); font-weight: 400; }
.audit-error { margin: 0; color: var(--color-danger); font-size: var(--text-sm); line-height: var(--leading-sm); }
.audit-filter-actions { display: flex; flex-wrap: wrap; gap: var(--space-3); }
@media (min-width: 760px) { .audit-filters { grid-template-columns: minmax(16rem, 1fr) 2fr; } .audit-error, .audit-filter-actions { grid-column: 1 / -1; } }
</style>
