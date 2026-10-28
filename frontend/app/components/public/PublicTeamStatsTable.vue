<script setup lang="ts">
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
  <div class="panel team-stats-panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">{{ t('public.stats') }}</p>
        <h2>{{ t('public.teamStats') }}</h2>
      </div>
      <span class="muted">{{ t('public.teamsCount', { count: rows.length }) }}</span>
    </div>
    <div v-if="!rows.length" class="empty-state compact" role="status">{{ t('public.noTeamStats') }}</div>
    <div v-else class="table-scroll">
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
    </div>
    <div id="public-team-stats-definitions" class="stats-definitions muted" role="note">
      <p class="stats-definition">{{ t('public.goalsForDefinition') }}</p>
      <p class="stats-definition">{{ t('public.goalsAgainstDefinition') }}</p>
      <p class="stats-definition">{{ t('public.cleanSheetDefinition') }}</p>
      <p class="stats-definition">{{ t('public.fairPlayDefinition') }}</p>
      <p class="stats-definition">{{ t('public.statsExclusions') }}</p>
    </div>
    <button v-if="hasMore" class="button-secondary load-more" type="button" :disabled="loadingMore" @click="emit('load-more')">
      {{ loadingMore ? t('common.loading') : t('public.loadMoreTeamStats') }}
    </button>
  </div>
</template>

<style scoped>
.team-stats-panel { min-width: 0; }
.table-scroll { overflow-x: auto; }
.stats-team { display: flex; align-items: center; gap: 10px; min-width: 0; }
.stats-definitions { display: grid; gap: 4px; margin-top: 12px; }
.stats-definition { margin: 0; font-size: 0.78rem; line-height: 1.5; overflow-wrap: anywhere; }
.load-more { display: block; margin: 16px auto 0; }
</style>
