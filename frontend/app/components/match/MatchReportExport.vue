<script setup lang="ts">
import { computed } from 'vue';
import Button from '~/components/ui/Button.vue';
import { keepFocusDuring } from '~/utils/exportDownload';
import { EXPORT_FORMATS, MATCH_REPORT_KIND, exportBusyKey, matchReportTitleKey, type ExportFormat } from '~/utils/exports';

// Descarga del acta de un partido cerrado en CSV (spec 048, RF-001, RF-006, D7) o PDF (spec 050, RF-003).
const props = defineProps<{
  match: { id: string; status: string; result_confirmed: boolean; home_team_name: string | null; away_team_name: string | null };
}>();
const { t } = useI18n();
const { busy, error, notice, downloadMatchReport } = useExports();
const closed = computed(() => ['finished', 'administrative_resolution'].includes(props.match.status) && props.match.result_confirmed);

const busyWith = (format: ExportFormat) => busy.value === exportBusyKey(MATCH_REPORT_KIND, format);

function download(format: ExportFormat, event: MouseEvent) {
  const match = props.match;
  void keepFocusDuring(event.currentTarget, () => downloadMatchReport(match.id, `${match.home_team_name || ''} vs ${match.away_team_name || ''}`, format));
}
</script>

<template>
  <section v-if="closed" class="container match-report-export" aria-labelledby="match-report-export-title">
    <div class="match-report-export-text">
      <p id="match-report-export-title" class="match-report-export-description">{{ t('export.kind.match-report.description') }}</p>
      <p v-if="notice" role="status" class="match-report-export-notice">{{ notice }}</p>
      <p v-if="error" role="alert" class="match-report-export-error">{{ t(error) }}</p>
    </div>
    <div class="match-report-export-actions">
      <Button
        v-for="format in EXPORT_FORMATS" :key="format"
        variant="secondary" aria-describedby="match-report-export-title" :data-format="format"
        :busy="busyWith(format)" :disabled="Boolean(busy) && !busyWith(format)" @click="download(format, $event)"
      >
        {{ t(busyWith(format) ? 'export.downloading' : matchReportTitleKey(format)) }}
      </Button>
    </div>
  </section>
</template>

<style scoped>
.match-report-export { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
.match-report-export-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.match-report-export-text { display: grid; gap: var(--space-1); min-width: 0; flex: 1 1 18rem; }
.match-report-export-description { margin: 0; color: var(--color-muted); }
.match-report-export-notice { margin: 0; font-weight: var(--weight-lg); }
.match-report-export-error { margin: 0; color: var(--color-danger); }
</style>
