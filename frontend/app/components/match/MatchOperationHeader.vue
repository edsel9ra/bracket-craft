<script setup lang="ts">
import PageHeader from '~/components/ui/PageHeader.vue';
import type { MatchOperationContext } from '~/composables/useMatchOperation';

const props = defineProps<{ context: MatchOperationContext }>();
const { t, match, matchGameFormat, formatDate } = props.context;
</script>

<template>
  <div class="container operation-hero">
    <PageHeader :title="t('match.matchReport')">
      <template v-if="match" #context>{{ match.tournament_name }} · {{ match.stage_name }} · {{ t('public.matchday', { value: match.matchday || '-' }) }}</template>
      <template v-if="match" #state><span class="match-context">{{ formatDate(match.match_date) }}<template v-if="match.group_name"> · {{ match.group_name }}</template> · <span>{{ t('format.context', { format: matchGameFormat }) }}</span></span></template>
    </PageHeader>
  </div>
</template>

<style scoped>
.match-context { color: var(--color-muted); font-size: var(--text-xs); }
</style>
