<script setup lang="ts">
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';
import TeamCrest from '~/components/TeamCrest.vue';
import type { PublicStanding } from '~/utils/publicTournament';

withDefaults(defineProps<{
  rows: PublicStanding[];
  caption?: string;
  showScope?: boolean;
}>(), { showScope: true });
const { t } = useI18n();
</script>

<template>
  <HorizontalScroll :label="caption || t('public.standings')">
    <table>
      <caption class="visually-hidden">{{ caption || t('public.standings') }}</caption>
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">{{ t('setup.teams') }}</th>
          <th scope="col">{{ t('public.played') }}</th>
          <th scope="col">{{ t('public.won') }}</th>
          <th scope="col">{{ t('public.drawn') }}</th>
          <th scope="col">{{ t('public.lost') }}</th>
          <th scope="col">{{ t('public.goalsFor') }}</th>
          <th scope="col">{{ t('public.goalsAgainst') }}</th>
          <th scope="col">{{ t('public.goalDifference') }}</th>
          <th scope="col">{{ t('public.points') }}</th>
          <th scope="col">{{ t('public.fairPlayPoints') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="standing in rows" :key="`${standing.stage_id}:${standing.group_id}:${standing.team_id}`">
          <td class="rank">{{ standing.rank }}</td>
          <td>
            <div class="standing-team">
              <TeamCrest :team="{ name: standing.team_name, short_code: standing.short_code }" :crest-url="standing.crest_url" surface="public" />
              <div>
                <strong>{{ standing.team_name }}</strong>
                <small>{{ standing.short_code }}<template v-if="showScope"> · {{ standing.group_name || standing.stage_name }}</template></small>
              </div>
            </div>
          </td>
          <td>{{ standing.played }}</td>
          <td>{{ standing.won }}</td>
          <td>{{ standing.drawn }}</td>
          <td>{{ standing.lost }}</td>
          <td>{{ standing.goals_for }}</td>
          <td>{{ standing.goals_against }}</td>
          <td>{{ standing.goal_difference > 0 ? `+${standing.goal_difference}` : standing.goal_difference }}</td>
          <td class="points">{{ standing.points }}</td>
          <td>{{ standing.fair_play_points }}</td>
        </tr>
      </tbody>
    </table>
  </HorizontalScroll>
</template>

<style scoped>
table { width: 100%; min-width: 760px; border-collapse: separate; border-spacing: 0; font-variant-numeric: tabular-nums; }
th { color: var(--color-muted); font-size: var(--text-2xs); font-weight: 700; letter-spacing: 0.1em; text-align: left; text-transform: uppercase; }
th, td { padding: var(--space-3) var(--space-2); border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); }
thead th:nth-child(2), tbody td:nth-child(2) { position: sticky; left: 0; z-index: 1; min-width: 180px; max-width: 230px; background: var(--color-surface); box-shadow: 5px 0 8px color-mix(in srgb, var(--color-shadow) 30%, transparent); }
tbody tr:hover { background: color-mix(in srgb, var(--color-accent) 5%, transparent); }
td { font-size: var(--text-md); }
td small { display: block; margin-top: var(--space-1); color: var(--color-muted); font-size: var(--text-xs); }
.standing-team { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.standing-team div { min-width: 0; overflow-wrap: anywhere; }
.rank, .points { color: var(--color-accent); font-weight: 800; }
@media (max-width: 760px) {
  table { table-layout: fixed; }
  thead th:first-child { width: 48px; }
  thead th:nth-child(2), tbody td:nth-child(2) { width: 208px; min-width: 0; max-width: none; }
}
</style>
