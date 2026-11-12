<script setup lang="ts">
import HorizontalScroll from '~/components/ui/HorizontalScroll.vue';
import PublicRectifiedMark from './PublicRectifiedMark.vue';
import PublicBracketConnections from '~/components/public/PublicBracketConnections.vue';
import { groupPublicRounds, inferPublicAdvances, publicRoundLabel } from '~/utils/publicBracket';
import { resolveMatchOutcomeLabel } from '~/utils/publicTournament';
import type { PublicMatch } from '~/utils/publicTournament';

const props = defineProps<{
  matches: PublicMatch[];
}>();

const emit = defineEmits<{
  openLineup: [match: PublicMatch, event: MouseEvent];
}>();

const { t, statusLabel } = useI18n();

const rounds = computed(() => groupPublicRounds(props.matches));
const edges = computed(() => inferPublicAdvances(props.matches));
const { container, layout } = usePublicBracketLayout(rounds, edges);
const matchLabels = computed(() => new Map(props.matches.map((match, i) => [match.id, match.bracket_code || `${t('public.match')} ${i + 1}`])));
const origins = computed(() => {
  const map = new Map<string, string[]>();
  for (const edge of edges.value) map.set(edge.targetId, [...(map.get(edge.targetId) ?? []), matchLabels.value.get(edge.sourceId)!]);
  return map;
});

function roundLabel(round: ReturnType<typeof groupPublicRounds>[number]): string {
  const label = publicRoundLabel(round);
  return t(label.key, label.value === undefined ? undefined : { value: label.value });
}

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
    <p class="bracket-explanation">{{ t('public.connectionsHint') }}</p>
    <div ref="container" class="bracket-grid" :class="{ measured: layout }">
      <PublicBracketConnections v-if="layout" :layout="layout" />
      <section v-for="round in rounds" :key="round.key" class="bracket-round">
        <header class="bracket-round-heading">
          <h3>{{ roundLabel(round) }}</h3>
        </header>
        <div class="bracket-match-list" :style="layout ? { height: `${layout.roundHeights[round.key]}px` } : undefined">
          <article v-for="match in round.matches" :key="match.id" class="bracket-match" :data-match-id="match.id" :data-collision="layout?.positions[match.id]?.collision" :style="layout ? { top: `${layout.positions[match.id]?.top}px` } : undefined">
            <div class="bracket-match-context">
              <span>{{ matchLabels.get(match.id) }}</span>
              <span>{{ match.group_name || t('public.bracket') }}</span>
            </div>
            <div class="bracket-team" :class="{ winner: isWinner(match, match.home_team_id) }">
              <span>{{ teamLabel(match.home_team_name, match.home_team_short_code) }}</span>
              <span v-if="isWinner(match, match.home_team_id)" class="visually-hidden">{{ t('public.winner') }}</span>
              <strong>{{ scoreLabel(match.home_score) }}</strong>
            </div>
            <div class="bracket-team" :class="{ winner: isWinner(match, match.away_team_id) }">
              <span>{{ teamLabel(match.away_team_name, match.away_team_short_code) }}</span>
              <span v-if="isWinner(match, match.away_team_id)" class="visually-hidden">{{ t('public.winner') }}</span>
              <strong>{{ scoreLabel(match.away_score) }}</strong>
            </div>
            <div class="bracket-match-footer">
              <span v-if="resolutionLabel(match)">{{ resolutionLabel(match) }}</span>
              <span v-if="match.home_penalties !== null && match.away_penalties !== null">
                {{ match.home_penalties }}-{{ match.away_penalties }} {{ t('public.penalties') }}
              </span>
              <span>{{ statusLabel(match.status) }}</span>
            </div>
            <PublicRectifiedMark :rectified-at="match.rectified_at" />
            <p v-for="origin in origins.get(match.id)" :key="origin" class="visually-hidden">{{ t('public.fromMatch', { value: origin }) }}</p>
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
.bracket-explanation { max-width: 70ch; margin: 0 0 var(--space-3); color: var(--color-muted); font-size: var(--text-sm); }
.bracket-grid { position: relative; display: grid; grid-auto-columns: minmax(230px, 1fr); grid-auto-flow: column; align-items: start; gap: var(--space-7); width: max-content; min-width: 100%; }
.bracket-round { position: relative; min-width: 0; }
.bracket-round-heading { display: flex; align-items: end; min-height: var(--space-8); margin-bottom: var(--space-3); padding-bottom: var(--space-2); border-bottom: 1px solid var(--color-line); }
.bracket-round-heading h3 { margin: var(--space-1) 0 0; font-size: var(--text-base); letter-spacing: -0.03em; }
.bracket-match-list { display: grid; gap: var(--space-3); }
.measured .bracket-match-list { position: relative; display: block; }
.measured .bracket-match { position: absolute; width: 100%; }
.bracket-match { padding: var(--space-3); border: 1px solid color-mix(in srgb, var(--color-muted) 15%, transparent); border-radius: var(--radius-md); background: var(--color-surface-raised); }
.bracket-match:hover { border-color: color-mix(in srgb, var(--color-accent) 42%, transparent); }
.bracket-match-context, .bracket-match-footer { display: flex; justify-content: space-between; gap: var(--space-2); color: var(--color-muted); font-size: var(--text-2xs); letter-spacing: 0.07em; text-transform: uppercase; }
.bracket-team { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-3) 0; border-bottom: 1px solid color-mix(in srgb, var(--color-muted) 12%, transparent); font-size: var(--text-md); }
.bracket-team:last-of-type { border-bottom: 0; }
.bracket-team strong { color: var(--color-ink); font-size: var(--text-base); }
.bracket-team > span { min-width: 0; overflow-wrap: anywhere; }
.bracket-team strong { flex-shrink: 0; }
.bracket-team.winner span, .bracket-team.winner strong { color: var(--color-accent); font-weight: 800; }
.bracket-match-footer { padding-top: var(--space-2); }
.lineup-trigger { display: block; width: 100%; margin-top: var(--space-3); padding: var(--space-3) 0 0; border-top: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); background: transparent; color: var(--color-accent); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.08em; text-align: left; text-transform: uppercase; }
.lineup-trigger:hover { color: var(--color-ink); }
.empty-state { padding: var(--space-6); border: 1px dashed var(--color-line); border-radius: var(--radius-md); color: var(--color-muted); }
.empty-state.compact { padding: var(--space-5); }
</style>
