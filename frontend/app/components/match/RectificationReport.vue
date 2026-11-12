<script setup lang="ts">
import { EVENT_LABEL_KEYS, RECTIFICATION_RESOLUTION_LABEL_KEYS, SCORE_FIELDS } from '~/utils/rectifications';
defineProps<{ report: Record<string, unknown> }>();
const { t } = useI18n();
const resolutionLabel = (value: unknown) => RECTIFICATION_RESOLUTION_LABEL_KEYS[value as keyof typeof RECTIFICATION_RESOLUTION_LABEL_KEYS] || 'match.resolution';
const eventLabel = (value: unknown) => EVENT_LABEL_KEYS[value as keyof typeof EVENT_LABEL_KEYS] || 'match.eventType';
</script>

<template>
  <dl class="report-fields">
    <div><dt>{{ t('match.resolution') }}</dt><dd>{{ t(resolutionLabel(report.resolution_type)) }}</dd></div>
    <div v-for="field in SCORE_FIELDS" :key="field"><dt>{{ t(`rectification.field.${field}`) }}</dt><dd>{{ report[field] ?? '—' }}</dd></div>
    <div><dt>{{ t('rectification.field.winner_team_id') }}</dt><dd>{{ report.winner_team_id || '—' }}</dd></div>
    <div><dt>{{ t('rectification.resolutionReason') }}</dt><dd>{{ report.reason || report.resolution_reason || '—' }}</dd></div>
  </dl>
  <ol class="report-events">
    <li v-for="(event, index) in (report.events as Record<string, unknown>[] || [])" :key="String(event.client_event_id || index)">
      {{ index + 1 }} · {{ t(eventLabel(event.event_type)) }} · {{ event.minute }}′ + {{ event.added_minute || 0 }} · {{ event.team_id }} · {{ event.player_id }}
      <span v-if="event.is_voided"> · {{ t('rectification.voided') }}</span>
      <details><summary>{{ t('rectification.eventDetails') }}</summary><pre>{{ JSON.stringify(event, null, 2) }}</pre></details>
    </li>
  </ol>
</template>

<style scoped>
.report-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: var(--space-3); }
dt { color: var(--color-muted); } dd { margin: 0; overflow-wrap: anywhere; }
.report-events { padding-inline-start: var(--space-6); } pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--text-sm); }
</style>
