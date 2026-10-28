<script setup lang="ts">
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
  <div class="panel player-stats-panel">
    <div class="panel-heading">
      <div>
        <p class="eyebrow">{{ t('public.stats') }}</p>
        <h2>{{ t('public.playerStats') }}</h2>
      </div>
      <span class="muted">{{ t('public.playersCount', { count: rows.length }) }}</span>
    </div>
    <div v-if="!rows.length" class="empty-state compact" role="status">{{ t('public.noPlayerStats') }}</div>
    <div v-else class="table-scroll">
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
    </div>
    <div id="public-player-stats-definitions" class="stats-definitions muted" role="note">
      <p class="stats-definition">{{ t('public.goalsDefinition') }}</p>
      <p class="stats-definition">{{ t('public.cleanSheetDefinition') }}</p>
      <p class="stats-definition">{{ t('public.statsExclusions') }}</p>
    </div>
    <button v-if="hasMore" class="button-secondary load-more" type="button" :disabled="loadingMore" @click="emit('load-more')">
      {{ loadingMore ? t('common.loading') : t('public.loadMorePlayerStats') }}
    </button>
  </div>
</template>

<style scoped>
.player-stats-panel { min-width: 0; }
.table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: separate; border-spacing: 0; font-variant-numeric: tabular-nums; }
thead th {
  color: var(--muted);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
thead th:nth-child(n+4) { text-align: right; }
tbody td {
  padding: 12px;
  font-size: 0.9rem;
  border-bottom: 1px solid rgba(166, 170, 159, 0.12);
  vertical-align: middle;
}
tbody tr:nth-child(even) { background: rgba(255, 255, 255, 0.02); }
tbody tr:hover { background: rgba(212, 243, 106, 0.06); }
tbody td:first-child { color: var(--accent); font-weight: 800; text-align: center; width: 2.5rem; }
tbody td:nth-child(n+4) { text-align: right; font-weight: 600; }
tbody tr:last-child td { border-bottom: 0; }
.stats-player { display: flex; align-items: center; gap: 10px; min-width: 0; }
.player-photo {
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  object-fit: cover;
  background: rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
}
.player-photo--initials {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: #f5f7fb;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
}
.stats-definitions { display: grid; gap: 6px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line); }
.stats-definition { margin: 0; font-size: 0.78rem; line-height: 1.5; overflow-wrap: anywhere; color: var(--muted); }
.load-more { display: block; margin: 16px auto 0; }
</style>
