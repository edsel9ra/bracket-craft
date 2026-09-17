<script setup lang="ts">
import type { PublicMatch } from '~/utils/publicTournament';

const props = defineProps<{
  matches: PublicMatch[];
}>();

const emit = defineEmits<{
  openLineup: [match: PublicMatch, event: MouseEvent];
}>();

const { t, statusLabel } = useI18n();

interface BracketRound {
  key: string;
  label: string;
  matches: PublicMatch[];
}

function matchSortValue(value: number | null): number {
  return value === null ? Number.MAX_SAFE_INTEGER : value;
}

function compareMatches(left: PublicMatch, right: PublicMatch): number {
  return matchSortValue(left.matchday) - matchSortValue(right.matchday)
    || (left.bracket_code || '').localeCompare(right.bracket_code || '', undefined, { numeric: true })
    || (left.match_date || '').localeCompare(right.match_date || '')
    || left.id.localeCompare(right.id);
}

const rounds = computed<BracketRound[]>(() => {
  const grouped = new Map<string, PublicMatch[]>();
  for (const match of [...props.matches].sort(compareMatches)) {
    const key = match.matchday === null ? 'unassigned' : `matchday:${match.matchday}`;
    const roundMatches = grouped.get(key) || [];
    roundMatches.push(match);
    grouped.set(key, roundMatches);
  }

  return [...grouped.entries()].map(([key, matches]) => ({
    key,
    label: key === 'unassigned'
      ? t('public.bracket')
      : t('public.round', { value: matches[0].matchday ?? '-' }),
    matches,
  }));
});

function teamLabel(teamName: string | null, shortCode: string | null): string {
  return teamName || shortCode || t('public.toDefine');
}

function scoreLabel(score: number | null): string {
  return score === null ? '-' : String(score);
}

function isWinner(match: PublicMatch, teamId: string | null): boolean {
  return Boolean(teamId && match.winner_team_id === teamId);
}
</script>

<template>
  <div v-if="!matches.length" class="empty-state compact">{{ t('public.noFixtures') }}</div>
  <div v-else class="bracket-scroll">
    <div class="bracket-grid">
      <section v-for="round in rounds" :key="round.key" class="bracket-round">
        <header class="bracket-round-heading">
          <p class="eyebrow">{{ t('public.roundLabel') }}</p>
          <h3>{{ round.label }}</h3>
        </header>
        <div class="bracket-match-list">
          <article v-for="match in round.matches" :key="match.id" class="bracket-match">
            <div class="bracket-match-context">
              <span>{{ match.bracket_code || t('public.match') }}</span>
              <span>{{ match.group_name || t('public.bracket') }}</span>
            </div>
            <div class="bracket-team" :class="{ winner: isWinner(match, match.home_team_id) }">
              <span>{{ teamLabel(match.home_team_name, match.home_team_short_code) }}</span>
              <strong>{{ scoreLabel(match.home_score) }}</strong>
            </div>
            <div class="bracket-team" :class="{ winner: isWinner(match, match.away_team_id) }">
              <span>{{ teamLabel(match.away_team_name, match.away_team_short_code) }}</span>
              <strong>{{ scoreLabel(match.away_score) }}</strong>
            </div>
            <div class="bracket-match-footer">
              <span v-if="match.home_penalties !== null && match.away_penalties !== null">
                {{ match.home_penalties }}-{{ match.away_penalties }} {{ t('public.penalties') }}
              </span>
              <span>{{ statusLabel(match.status) }}</span>
            </div>
            <button
              v-if="match.lineup"
              class="lineup-trigger"
              type="button"
              :aria-label="`${t('public.viewLineup')}: ${teamLabel(match.home_team_name, match.home_team_short_code)} vs ${teamLabel(match.away_team_name, match.away_team_short_code)}`"
              @click="emit('openLineup', match, $event)"
            >
              {{ t('public.viewLineup') }}
            </button>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.bracket-scroll { overflow-x: auto; padding-bottom: 8px; }
.bracket-grid { display: grid; grid-auto-columns: minmax(230px, 1fr); grid-auto-flow: column; align-items: start; gap: 16px; min-width: max-content; }
.bracket-round { min-width: 230px; }
.bracket-round-heading { margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.bracket-round-heading h3 { margin: 6px 0 0; font-size: 1.1rem; letter-spacing: -0.03em; }
.bracket-match-list { display: grid; gap: 12px; }
.bracket-match { padding: 13px; border: 1px solid rgba(166, 170, 159, 0.15); border-radius: 15px; background: var(--surface-raised); }
.bracket-match:hover { border-color: rgba(212, 243, 106, 0.42); transform: translateY(-2px); }
.bracket-match-context, .bracket-match-footer { display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 0.64rem; letter-spacing: 0.07em; text-transform: uppercase; }
.bracket-team { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 0; border-bottom: 1px solid rgba(166, 170, 159, 0.12); font-size: 0.86rem; }
.bracket-team:last-of-type { border-bottom: 0; }
.bracket-team strong { color: var(--ink); font-size: 1.05rem; }
.bracket-team.winner span, .bracket-team.winner strong { color: var(--accent); font-weight: 800; }
.bracket-match-footer { padding-top: 9px; }
.lineup-trigger { display: block; width: 100%; margin-top: 12px; padding: 11px 0 0; border-top: 1px solid rgba(166, 170, 159, 0.14); background: transparent; color: var(--accent); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; }
.lineup-trigger:hover { color: var(--ink); }
.empty-state { padding: 28px; border: 1px dashed var(--line); border-radius: 16px; color: var(--muted); }
.empty-state.compact { padding: 20px; }
@media (max-width: 620px) {
  .bracket-grid { grid-auto-columns: minmax(205px, 1fr); }
  .bracket-round { min-width: 205px; }
}
</style>
