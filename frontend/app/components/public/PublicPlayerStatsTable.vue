<script setup lang="ts">
import Button from '~/components/ui/Button.vue';
import Surface from '~/components/ui/Surface.vue';
import StateMessage from '~/components/ui/StateMessage.vue';
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';
import { playerInitials } from '~/utils/publicLineup';
import { playerPhotoSource } from '~/utils/publicStats';

interface PlayerStatRow {
  rank: number;
  player_id: string;
  first_name: string;
  last_name: string;
  team_name: string | null;
  team_id?: string | null;
  goals: number;
  yellow_cards: number;
  red_cards: number;
  clean_sheets: number;
  matches_played: number;
  photo_url: string | null;
}

const props = withDefaults(defineProps<{
  rows: PlayerStatRow[];
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

// Foto fallida por jugador: guarda la URL que falló, no solo el identificador,
// para que un enlace nuevo vuelva a intentarse y el mismo no se repita.
const failedPhotoUrls = ref(new Map<string, string>());

function photoSource(row: PlayerStatRow) {
  return playerPhotoSource(row, failedPhotoUrls.value);
}

function photoUrl(row: PlayerStatRow): string {
  return row.photo_url ?? '';
}

function markPhotoFailed(row: PlayerStatRow) {
  failedPhotoUrls.value.set(row.player_id, row.photo_url ?? '');
}

function initials(row: PlayerStatRow): string {
  return playerInitials({
    player_id: row.player_id,
    first_name: row.first_name,
    last_name: row.last_name,
    dorsal_number: 0,
    role: 'starter',
    position_slot: null,
    photo_url: row.photo_url,
  } as any);
}
</script>

<template>
  <Surface class="panel player-stats-panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">{{ t('public.stats') }}</p>
        <h2>{{ t('public.playerStats') }}</h2>
      </div>
      <span class="muted">{{ t('public.playersCount', { count: rows.length }) }}</span>
    </div>
    <StateMessage v-if="!rows.length" kind="empty" class="empty-state compact">{{ t('public.noPlayerStats') }}</StateMessage>
    <HorizontalScroll v-else :label="t('public.playerStats')">
      <table aria-describedby="public-player-stats-definitions">
        <caption class="visually-hidden">{{ t('public.playerStats') }}</caption>
        <thead>
          <tr>
            <th scope="col">{{ t('public.position') }}</th>
            <th scope="col">{{ t('public.player') }}</th>
            <th scope="col">{{ t('public.team') }}</th>
            <th scope="col">{{ t('public.goals') }}</th>
            <th scope="col">{{ t('public.yellowCards') }}</th>
            <th scope="col">{{ t('public.redCards') }}</th>
            <th scope="col">{{ t('public.cleanSheets') }}</th>
            <th scope="col">{{ t('public.played') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.player_id">
            <td>{{ row.rank }}</td>
            <td>
              <div class="stats-player">
                <img
                  v-if="photoSource(row) === 'photo'"
                  class="player-photo"
                  :src="photoUrl(row)"
                  :alt="`${row.first_name} ${row.last_name}`"
                  loading="lazy"
                  decoding="async"
                  @error="markPhotoFailed(row)"
                >
                <span v-else class="player-photo player-photo--initials" role="img" :aria-label="`${row.first_name} ${row.last_name}`">{{ initials(row) }}</span>
                <strong>{{ row.first_name }} {{ row.last_name }}</strong>
              </div>
            </td>
            <td>{{ row.team_name }}</td>
            <td>{{ row.goals }}</td>
            <td>{{ row.yellow_cards }}</td>
            <td>{{ row.red_cards }}</td>
            <td>{{ row.clean_sheets }}</td>
            <td>{{ row.matches_played }}</td>
          </tr>
        </tbody>
      </table>
    </HorizontalScroll>
    <div id="public-player-stats-definitions" class="stats-definitions muted" role="note">
      <p class="stats-definition">{{ t('public.goalsDefinition') }}</p>
      <p class="stats-definition">{{ t('public.cleanSheetDefinition') }}</p>
      <p class="stats-definition">{{ t('public.statsExclusions') }}</p>
    </div>
    <Button variant="secondary" v-if="hasMore" class="button-secondary load-more" type="button" :disabled="loadingMore" @click="emit('load-more')">
      {{ loadingMore ? t('common.loading') : t('public.loadMorePlayerStats') }}
    </Button>
  </Surface>
</template>

<style scoped>
.player-stats-panel { min-width: 0; }
.empty-state :deep(p) { margin: 0; }
thead th:nth-child(2), tbody td:nth-child(2) { position: sticky; left: 0; z-index: 1; min-width: 145px; max-width: 180px; background: var(--color-surface); box-shadow: 5px 0 8px color-mix(in srgb, var(--color-shadow) 30%, transparent); }
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
thead th:nth-child(n+4) { text-align: right; }
tbody td {
  padding: var(--space-3);
  font-size: var(--text-md);
  border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 12%, transparent);
  vertical-align: middle;
}
tbody tr:nth-child(even) { background: color-mix(in srgb, var(--color-highlight) 2%, transparent); }
tbody tr:hover { background: color-mix(in srgb, var(--color-accent) 6%, transparent); }
tbody td:first-child { color: var(--color-accent); font-weight: 800; text-align: center; width: 2.5rem; }
tbody td:nth-child(n+4) { text-align: right; font-weight: 600; }
tbody tr:last-child td { border-bottom: 0; }
.stats-player { display: flex; align-items: center; gap: var(--space-2); min-width: 0; }
.player-photo {
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  object-fit: cover;
  background: color-mix(in srgb, var(--color-highlight) 6%, transparent);
  flex-shrink: 0;
}
.player-photo--initials {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in srgb, var(--color-highlight) 18%, transparent);
  color: var(--color-avatar-ink);
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
}
.stats-definitions { display: grid; gap: var(--space-1); margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px solid var(--color-line); }
.stats-definition { margin: 0; font-size: var(--text-xs); line-height: 1.5; overflow-wrap: anywhere; color: var(--color-muted); }
.load-more { display: block; margin: var(--space-4) auto 0; }
</style>
