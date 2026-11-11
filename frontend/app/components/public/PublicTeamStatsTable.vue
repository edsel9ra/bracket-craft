<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import StateMessage from '~/components/ui/StateMessage.vue';
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';
interface TeamStatRow {
  rank: number;
  team_id: string;
  team_name: string | null;
  short_code: string | null;
  crest_url: string | null;
  goals_for: number;
  goals_against: number;
  clean_sheets: number;
  fair_play_points: number;
}

const props = withDefaults(defineProps<{
  rows: TeamStatRow[];
  hasMore?: boolean;
  loadingMore?: boolean;
}>(), {
  hasMore: false,
  loadingMore: false,
});

const emit = defineEmits<{
  'load-more': [];
}>();

const { t } = useI18n();
</script>

<template>
  <Surface class="panel team-stats-panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">{{ t('public.stats') }}</p>
        <h2>{{ t('public.teamStats') }}</h2>
      </div>
      <span class="muted">{{ t('public.rowsShown', { count: rows.length }) }}</span>
    </div>
    <StateMessage v-if="!rows.length" kind="empty" class="empty-state compact">{{ t('public.noTeamStats') }}</StateMessage>
    <HorizontalScroll v-else :label="t('public.teamStats')">
      <table aria-describedby="public-team-stats-definitions">
        <caption class="visually-hidden">{{ t('public.teamStats') }}</caption>
        <thead>
          <tr>
            <th scope="col">{{ t('public.position') }}</th>
            <th scope="col">{{ t('setup.teams') }}</th>
            <th scope="col">{{ t('public.goalsFor') }}</th>
            <th scope="col">{{ t('public.goalsAgainst') }}</th>
            <th scope="col">{{ t('public.cleanSheets') }}</th>
            <th scope="col">{{ t('public.fairPlayPoints') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.team_id">
            <td>{{ row.rank }}</td>
            <td>
              <div class="stats-team">
                <TeamCrest :team="{ name: row.team_name || row.short_code || '', short_code: row.short_code }" :crest-url="row.crest_url" surface="public" />
                <div>
                  <strong>{{ row.team_name }}</strong>
                  <small>{{ row.short_code }}</small>
                </div>
              </div>
            </td>
            <td>{{ row.goals_for }}</td>
            <td>{{ row.goals_against }}</td>
            <td>{{ row.clean_sheets }}</td>
            <td>{{ row.fair_play_points }}</td>
          </tr>
        </tbody>
      </table>
    </HorizontalScroll>
    <div id="public-team-stats-definitions" class="stats-definitions muted" role="note">
      <p class="stats-definition">{{ t('public.teamStatsOrder') }}</p>
      <p class="stats-definition">{{ t('public.goalsForDefinition') }}</p>
      <p class="stats-definition">{{ t('public.goalsAgainstDefinition') }}</p>
      <p class="stats-definition">{{ t('public.cleanSheetDefinition') }}</p>
      <p class="stats-definition">{{ t('public.fairPlayDefinition') }}</p>
      <p class="stats-definition">{{ t('public.statsExclusions') }}</p>
    </div>
    <Button variant="secondary" v-if="hasMore" class="button-secondary load-more" type="button" :disabled="loadingMore" @click="emit('load-more')">
      {{ loadingMore ? t('common.loading') : t('public.loadMoreTeamStats') }}
    </Button>
  </Surface>
</template>

<style scoped>
.team-stats-panel { min-width: 0; }
.empty-state :deep(p) { margin: 0; }
thead th:nth-child(2), tbody td:nth-child(2) { position: sticky; left: 0; z-index: 1; min-width: 130px; max-width: 170px; background: var(--color-surface); box-shadow: 5px 0 8px color-mix(in srgb, var(--color-shadow) 30%, transparent); }
table { width: 100%; border-collapse: separate; border-spacing: 0; font-variant-numeric: tabular-nums; }
thead th {
  color: var(--color-muted);
  font-size: var(--text-2xs);
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  text-align: left;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-line);
  white-space: nowrap;
}
thead th:nth-child(n+3) { text-align: right; }
tbody td {
  padding: var(--space-3);
  font-size: var(--text-md);
  border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 12%, transparent);
  vertical-align: middle;
}
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--color-highlight) 2%, transparent); }
tbody tr:hover { background: color-mix(in srgb, var(--color-accent) 6%, transparent); }
tbody td:first-child { color: var(--color-accent); font-weight: 800; text-align: center; width: 2.5rem; }
tbody td:nth-child(n+3) { text-align: right; font-weight: 600; }
tbody tr:last-child td { border-bottom: 0; }
.stats-team { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.stats-team div { display: grid; gap: var(--space-1); }
.stats-team strong { color: var(--color-ink); }
.stats-team small { color: var(--color-muted); font-size: var(--text-xs); }
.stats-definitions { display: grid; gap: var(--space-1); margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px solid var(--color-line); }
.stats-definition { margin: 0; font-size: var(--text-xs); line-height: 1.5; overflow-wrap: anywhere; color: var(--color-muted); }
.load-more { display: block; margin: var(--space-4) auto 0; }
@media (max-width: 760px) {
  table { table-layout: fixed; min-width: 528px; }
  thead th, tbody td { padding: var(--space-2); }
  thead th { white-space: normal; letter-spacing: 0; overflow-wrap: anywhere; }
  thead th:first-child { width: 72px; white-space: nowrap; }
  thead th:nth-child(2), tbody td:nth-child(2) { width: 136px; min-width: 0; max-width: none; }
  thead th:nth-child(3), thead th:nth-child(4) { width: 56px; }
  .stats-team { align-items: start; }
  .stats-team div { min-width: 0; }
  .stats-team strong, .stats-team small { overflow-wrap: anywhere; }
}
</style>
