<script setup lang="ts">
import { computed } from 'vue';
import Button from '~/components/ui/Button.vue';
import { keepFocusDuring } from '~/utils/exportDownload';

// Descarga del acta de un partido cerrado (spec 048, RF-001, RF-006, D7).
const props = defineProps<{
  match: { id: string; status: string; result_confirmed: boolean; home_team_name: string | null; away_team_name: string | null };
}>();
const { t } = useI18n();
const { busy, error, notice, downloadMatchReport } = useExports();
const closed = computed(() => ['finished', 'administrative_resolution'].includes(props.match.status) && props.match.result_confirmed);

function download(event: MouseEvent) {
  const match = props.match;
  void keepFocusDuring(event.currentTarget, () => downloadMatchReport(match.id, `${match.home_team_name || ''} vs ${match.away_team_name || ''}`));
}
</script>

<template>
  <section v-if="closed" class="container match-report-export" aria-labelledby="match-report-export-title">
    <div class="match-report-export-text">
      <p id="match-report-export-title" class="match-report-export-description">{{ t('export.kind.match-report.description') }}</p>
      <p v-if="notice" role="status" class="match-report-export-notice">{{ notice }}</p>
      <p v-if="error" role="alert" class="match-report-export-error">{{ t(error) }}</p>
    </div>
    <Button variant="secondary" :busy="Boolean(busy)" aria-describedby="match-report-export-title" @click="download">
      {{ t(busy ? 'export.downloading' : 'export.kind.match-report.title') }}
    </Button>
  </section>
</template>

<style scoped>
.match-report-export { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
.match-report-export-text { display: grid; gap: var(--space-1); min-width: 0; flex: 1 1 18rem; }
.match-report-export-description { margin: 0; color: var(--color-muted); }
.match-report-export-notice { margin: 0; font-weight: var(--weight-lg); }
.match-report-export-error { margin: 0; color: var(--color-danger); }
</style>
