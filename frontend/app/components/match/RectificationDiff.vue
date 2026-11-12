<script setup lang="ts">
import type { ReportDifference } from '~/utils/rectifications';
defineProps<{ diff: ReportDifference }>();
const { t } = useI18n();
const value = (input: unknown) => input === null || input === undefined ? '—' : typeof input === 'object' ? JSON.stringify(input) : String(input);
</script>

<template>
  <section :aria-label="t('rectification.diff')">
    <h3>{{ t('rectification.diff') }}</h3>
    <p v-if="!diff.fields.length && !diff.events.added.length && !diff.events.removed.length && !diff.events.changed.length" role="status">{{ t('rectification.noDifferences') }}</p>
    <dl>
      <div v-for="field in diff.fields" :key="field.field"><dt>{{ t(`rectification.field.${field.field}`) }}</dt><dd>{{ t('rectification.before') }}: {{ value(field.before) }} → {{ t('rectification.after') }}: {{ value(field.after) }}</dd></div>
    </dl>
    <div v-for="kind in (['added', 'removed'] as const)" :key="kind">
      <h4>{{ t(`rectification.events.${kind}`) }}</h4>
      <pre v-for="event in diff.events[kind]" :key="String(event.client_event_id)">{{ JSON.stringify(event, null, 2) }}</pre>
    </div>
    <div v-for="event in diff.events.changed" :key="event.client_event_id">
      <h4>{{ t('rectification.events.changed') }} · {{ event.client_event_id }}</h4>
      <dl><div v-for="field in event.fields" :key="field.field"><dt>{{ t(`rectification.field.${field.field}`) }}</dt><dd>{{ t('rectification.before') }}: {{ value(field.before) }} → {{ t('rectification.after') }}: {{ value(field.after) }}</dd></div></dl>
    </div>
  </section>
</template>

<style scoped>
dt { color: var(--color-muted); } dd { margin: 0 0 var(--space-3); overflow-wrap: anywhere; } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-sm); }
</style>
