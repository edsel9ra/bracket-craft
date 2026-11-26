<script setup lang="ts">
import { computed } from 'vue';
import Button from '~/components/ui/Button.vue';
import PageHeader from '~/components/ui/PageHeader.vue';
import Surface from '~/components/ui/Surface.vue';
import {
  AUDITED_EXPORT_KINDS, TOURNAMENT_EXPORT_KINDS, exportDescriptionKey, exportTitleKey, type TournamentExportKind,
} from '~/utils/exports';
import { keepFocusDuring } from '~/utils/exportDownload';

// Exportaciones CSV del torneo (spec 048, RF-001, RF-007): cualquier miembro, solo en el Workspace.
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

function download(kind: TournamentExportKind, event: MouseEvent) {
  void keepFocusDuring(event.currentTarget, () => downloadTournament(tournamentId, kind, tournamentName.value));
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
            <Button
              variant="secondary" :aria-describedby="describedBy(kind)"
              :busy="busy === kind" :disabled="Boolean(busy) && busy !== kind" @click="download(kind, $event)"
            >
              {{ t(busy === kind ? 'export.downloading' : 'export.download') }}
            </Button>
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
.export-text { display: grid; gap: var(--space-1); min-width: 0; flex: 1 1 18rem; }
.export-text h2 { margin: 0; font-size: var(--text-lg); line-height: var(--leading-lg); }
.export-audit { margin: 0; color: var(--color-ink); font-size: var(--text-sm); line-height: var(--leading-sm); }
</style>
