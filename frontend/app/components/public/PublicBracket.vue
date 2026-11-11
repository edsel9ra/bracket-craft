<script setup lang="ts">
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';
import { resolveMatchOutcomeLabel } from '~/utils/publicTournament';
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
      : t('public.round', { value: matches[0]?.matchday ?? '-' }),
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

function resolutionLabel(match: PublicMatch): string {
  const outcome = resolveMatchOutcomeLabel(match);
  if (outcome === 'walkover') return t('match.walkover');
  if (outcome === 'penalties') return t('public.penalties');
  if (outcome === 'extra_time') return t('match.overtime');
  if (outcome === 'administrative') return t('match.administrative');
  return '';
}
</script>

<template>
  <div v-if="!matches.length" class="empty-state compact">{{ t('public.noFixtures') }}</div>
  <HorizontalScroll v-else :label="t('public.bracket')">
    <div class="bracket-grid">
      <section v-for="round in rounds" :key="round.key" class="bracket-round">
        <header class="bracket-round-heading">
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
              <span v-if="resolutionLabel(match)">{{ resolutionLabel(match) }}</span>
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
  </HorizontalScroll>
</template>

<style scoped>
.bracket-grid { display: grid; grid-auto-columns: minmax(230px, 1fr); grid-auto-flow: column; align-items: start; gap: var(--space-4); min-width: max-content; }
.bracket-round { min-width: 230px; }
.bracket-round-heading { margin-bottom: var(--space-3); padding-bottom: var(--space-2); border-bottom: 1px solid var(--color-line); }
.bracket-round-heading h3 { margin: var(--space-1) 0 0; font-size: var(--text-base); letter-spacing: -0.03em; }
.bracket-match-list { display: grid; gap: var(--space-3); }
.bracket-match { padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--color-muted) 15%, transparent); border-radius: var(--radius-md); background: var(--color-surface-raised); }
.bracket-match:hover { border-color: color-mix(in srgb, var(--color-accent) 42%, transparent); transform: translateY(-2px); }
@media (prefers-reduced-motion: reduce) {
  .bracket-match:hover { transform: none; }
}
.bracket-match-context, .bracket-match-footer { display: flex; justify-content: space-between; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.07em; text-transform: uppercase; }
.bracket-team { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) 0; border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 12%, transparent); font-size: var(--text-md); }
.bracket-team:last-of-type { border-bottom: 0; }
.bracket-team strong { color: var(--color-ink); font-size: var(--text-base); }
.bracket-team.winner span, .bracket-team.winner strong { color: var(--color-accent); font-weight: 800; }
.bracket-match-footer { padding-top: var(--space-2); }
.lineup-trigger { display: block; width: 100%; margin-top: var(--space-3); padding: var(--space-3) 0 0; border-top: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); background: transparent; color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; }
.lineup-trigger:hover { color: var(--color-ink); }
.empty-state { padding: var(--space-6); border: 1px dashed var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); }
.empty-state.compact { padding: var(--space-5); }
@media (max-width: 480px) {
  .bracket-grid { grid-auto-columns: minmax(205px, 1fr); }
  .bracket-round { min-width: 205px; }
}
</style>
