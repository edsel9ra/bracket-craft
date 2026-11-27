<script setup lang="ts">
import { computed } from 'vue';
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import Surface from '~/components/ui/Surface.vue';
import {
  AUDITED_EXPORT_KINDS, TOURNAMENT_EXPORT_KINDS, exportBusyKey, exportDescriptionKey, exportDownloadKey, exportSubject, exportTitleKey, hasPdf,
  type ExportFormat, type TournamentExportKind,
} from '~/utils/exports';
import { keepFocusDuring } from '~/utils/exportDownload';

// Exportaciones del torneo: CSV (spec 048, RF-001, RF-007) y PDF de la clasificación (spec 050, RF-003); cualquier miembro, solo en el Workspace.
definePageMeta({ middleware: 'auth' });
const { t } = useI18n();
const route = useRoute();
const tournamentsStore = useTournamentsStore();
const tournamentId = String(route.params.id);
const tournamentName = computed(
  () => tournamentsStore.tournaments.find((tournament) => tournament.id === tournamentId)?.name || '',
);
const tournamentLabel = computed(() => tournamentName.value || t('shell.tournament'));
useHead({ title: computed(() => `${t('export.title')} | Bracket Craft`) });
const { busy, error, notice, downloadTournament } = useExports();

const titleId = (kind: TournamentExportKind) => `export-${kind}-title`;
const auditId = (kind: TournamentExportKind) => `export-${kind}-audit`;
const audited = (kind: TournamentExportKind) => AUDITED_EXPORT_KINDS.includes(kind);
const describedBy = (kind: TournamentExportKind) => (audited(kind) ? `${titleId(kind)} ${auditId(kind)}` : titleId(kind));
const formats = (kind: TournamentExportKind): ExportFormat[] => (hasPdf(kind) ? ['csv', 'pdf'] : ['csv']);
const busyWith = (kind: TournamentExportKind, format: ExportFormat) => busy.value === exportBusyKey(kind, format);

function download(kind: TournamentExportKind, format: ExportFormat, event: MouseEvent) {
  void keepFocusDuring(event.currentTarget, () => downloadTournament(tournamentId, kind, exportSubject(tournamentName.value, tournamentId), format));
}
</script>

<template>
  <WorkspaceShell
    :breadcrumbs="[
      { label: t('shell.tournaments'), to: '/workspace' },
      { label: tournamentLabel, current: true },
    ]"
    :tournament="{ id: tournamentId, name: tournamentName || null }"
  >
    <main id="main-content" class="container export-page">
      <PageHeader :title="t('export.title')">
        <template #context>{{ tournamentLabel }}</template>
      </PageHeader>
      <p class="export-muted">{{ t('export.hint') }}</p>
      <p class="export-muted">{{ t('export.format') }}</p>
      <p class="export-muted">{{ t('export.format.pdf') }}</p>
      <p v-if="notice" role="status" class="export-notice">{{ notice }}</p>
      <p v-if="error" role="alert" class="export-error">{{ t(error) }}</p>
      <ul class="export-list">
        <li v-for="kind in TOURNAMENT_EXPORT_KINDS" :key="kind">
          <Surface as="section" class="export-item" :aria-labelledby="titleId(kind)">
            <div class="export-text">
              <h2 :id="titleId(kind)">{{ t(exportTitleKey(kind)) }}</h2>
              <p class="export-muted">{{ t(exportDescriptionKey(kind)) }}</p>
              <p v-if="audited(kind)" :id="auditId(kind)" class="export-audit">{{ t('export.auditNotice') }}</p>
            </div>
            <div class="export-actions">
              <Button
                v-for="format in formats(kind)" :key="format"
                variant="secondary" :aria-describedby="describedBy(kind)" :data-format="format"
                :busy="busyWith(kind, format)" :disabled="Boolean(busy) && !busyWith(kind, format)" @click="download(kind, format, $event)"
              >
                {{ t(busyWith(kind, format) ? 'export.downloading' : exportDownloadKey(format)) }}
              </Button>
            </div>
          </Surface>
        </li>
      </ul>
    </main>
  </WorkspaceShell>
</template>

<style scoped>
.export-page { display: grid; gap: var(--space-4); padding-block: var(--space-6); }
.export-muted { margin: 0; color: var(--color-muted); }
.export-notice { margin: 0; color: var(--color-ink); font-weight: var(--weight-lg); }
.export-error { margin: 0; color: var(--color-danger); }
.export-list { display: grid; gap: var(--space-4); margin: 0; padding: 0; list-style: none; }
.export-item { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
.export-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.export-text { display: grid; gap: var(--space-1); min-width: 0; flex: 1 1 18rem; }
.export-text h2 { margin: 0; font-size: var(--text-lg); line-height: var(--leading-lg); }
.export-audit { margin: 0; color: var(--color-ink); font-size: var(--text-sm); line-height: var(--leading-sm); }
</style>
