<script setup lang="ts">
import TeamCrest from '~/components/TeamCrest.vue';
import type { MatchOperationContext } from '~/composables/useMatchOperation';
import { matchScoreDisplay } from '~/utils/matchScoreDisplay';

const props = defineProps<{ context: MatchOperationContext }>();
const { t, match, operation, activeSegment, statusLabel, realtime, realtimeStatusLabel } = props.context;
const emit = defineEmits<{ retryRealtime: [] }>();
const retryRealtime = () => emit('retryRealtime');
const score = computed(() => matchScoreDisplay({
  status: match.value?.status || 'scheduled', segments: operation.value?.segments || [],
  score: { home: match.value?.home_score ?? null, away: match.value?.away_score ?? null }, resolution: match.value?.resolution_type,
}));
const teams = computed(() => [
  { key: 'home', name: match.value?.home_team_name || t('public.toDefine'), short_code: match.value?.home_team_short_code, crest: match.value?.home_team_crest_url, logo: match.value?.home_team_logo_url },
  { key: 'away', name: match.value?.away_team_name || t('public.toDefine'), short_code: match.value?.away_team_short_code, crest: match.value?.away_team_crest_url, logo: match.value?.away_team_logo_url },
]);
</script>

<template>
  <section v-if="match" class="match-bar container" :aria-label="t('match.result')">
    <div class="match-heading">
      <div class="match-team">
        <TeamCrest :team="teams[0]!" :crest-url="match.home_team_crest_url" :logo-url="match.home_team_logo_url" surface="workspace" />
        <span class="team-name" :title="teams[0]!.name">{{ teams[0]!.name }}</span>
      </div>
      <div class="match-score" :aria-label="t(score.labelKey)">
        <span v-if="score.kind === 'pending'" class="score-pending">{{ t(score.labelKey) }}</span>
        <strong v-else>{{ score.home }} – {{ score.away }}</strong>
      </div>
      <div class="match-team away-team">
        <span class="team-name" :title="teams[1]!.name">{{ teams[1]!.name }}</span>
        <TeamCrest :team="teams[1]!" :crest-url="match.away_team_crest_url" :logo-url="match.away_team_logo_url" surface="workspace" />
      </div>
    </div>
    <div class="match-live-state">
      <span>{{ statusLabel(match.status) }}</span>
      <span v-if="activeSegment">{{ t('match.segmentMinute', { segment: activeSegment.segment_number, minute: activeSegment.minute_start }) }}</span>
      <span v-if="realtimeStatusLabel" class="realtime-status" :class="`realtime-${realtime.status.value}`" role="status">{{ realtimeStatusLabel }}</span>
      <button v-if="realtime.status.value === 'error'" class="realtime-retry" type="button" @click="retryRealtime">{{ t('common.retry') }}</button>
    </div>
  </section>
</template>

<style scoped>
.match-bar { position: sticky; top: var(--operation-sticky-top, 0px); z-index: 25; display: grid; gap: var(--space-2); padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line); border-radius: var(--radius-md); background: var(--color-surface-raised); }
.match-heading { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: var(--space-3); }
.match-team { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.match-team :deep(.team-crest) { flex: 0 0 auto; }
.away-team { justify-content: end; }
.team-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--text-md); font-weight: var(--weight-lg); }
.match-score { color: var(--color-accent); font-family: var(--font-display); font-size: var(--text-xl); font-stretch: condensed; font-variation-settings: "wdth" 75; line-height: 1; white-space: nowrap; }
.score-pending { color: var(--color-muted); font-size: var(--text-xs); }
.match-live-state { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-2xs); }
.realtime-error, .realtime-reconnecting, .realtime-retrying { color: var(--color-warning); }
.realtime-retry { padding: 0; background: transparent; color: var(--color-accent); font-size: var(--text-xs); text-decoration: underline; }
@media (min-width: 1000px) { .match-bar { grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: var(--space-6); } }
@media (max-width: 480px) { .match-bar { padding: var(--space-2); } .match-heading { gap: var(--space-2); } .team-name { font-size: var(--text-xs); } .match-team :deep(.team-crest) { width: 24px; height: 24px; font-size: var(--text-2xs); } }
</style>
