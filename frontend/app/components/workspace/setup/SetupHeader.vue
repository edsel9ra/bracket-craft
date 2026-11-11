<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import StatusPill from '~/components/ui/StatusPill.vue';
import type { VersionSummary } from './types';

defineProps<{ tournamentLabel: string; declaredGameFormat: string; draftVersion?: VersionSummary }>();
const { t } = useI18n();
</script>

<template>
<PageHeader id="resumen" class="container" :title="t('shell.configuration')">
  <template #context>
    <span>{{ tournamentLabel }}</span>
    <span class="format-summary">{{ t('setup.gameFormat', { format: declaredGameFormat }) }}</span>
    <span v-if="declaredGameFormat !== '11v11'" class="muted-note">{{ t('format.context', { format: declaredGameFormat }) }}</span>
  </template>
  <template #state>
    <StatusPill :tone="draftVersion ? 'warning' : 'success'">{{ draftVersion ? t('setup.editableDraft') : t('setup.publishedVersion') }}</StatusPill>
  </template>
</PageHeader>
</template>
