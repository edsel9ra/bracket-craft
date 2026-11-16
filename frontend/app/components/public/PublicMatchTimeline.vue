<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import PublicRectifiedMark from './PublicRectifiedMark.vue';
import {
  formatTimelineMinute,
  timelineEventKey,
  timelineEventSide,
  timelineGroups,
  timelinePlayerName,
  type PublicMatchTimeline,
  type PublicTimelineEvent,
} from '~/utils/publicTimeline';

interface TimelineMatch {
  id: string;
  stage_name: string;
  rectified_at?: string | null;
  home_team_id: string | null;
  away_team_id: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
}

const props = defineProps<{
  open: boolean;
  match: TimelineMatch | null;
  timeline: PublicMatchTimeline | null;
  loading: boolean;
  error: boolean;
}>();
const emit = defineEmits<{
  close: [];
  retry: [];
}>();
const { t } = useI18n();
const dialog = ref<HTMLDialogElement | null>(null);
const dialogId = 'public-timeline-dialog';
const titleId = 'public-timeline-dialog-title';
const previousFocus = ref<HTMLElement | null>(null);

function showDialog() {
  if (dialog.value && !dialog.value.open) dialog.value.showModal();
}

function hideDialog() {
  if (dialog.value?.open) dialog.value.close();
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    previousFocus.value = (typeof document !== 'undefined' ? document.activeElement : null) as HTMLElement | null;
    void nextTick(showDialog);
  } else {
    hideDialog();
    void nextTick(() => {
      previousFocus.value?.focus?.();
      previousFocus.value = null;
    });
  }
});

onMounted(() => {
  if (props.open) showDialog();
});

onBeforeUnmount(hideDialog);

function close() {
  emit('close');
}

function handleCancel(event: Event) {
  event.preventDefault();
  close();
}

function handleNativeClose() {
  if (props.open) close();
}

function handleDialogClick(event: MouseEvent) {
  if (event.target === event.currentTarget) close();
}

function teamName(match: TimelineMatch, side: 'home' | 'away' | null): string {
  if (side === 'home') return match.home_team_name || match.home_team_short_code || t('public.toDefine');
  if (side === 'away') return match.away_team_name || match.away_team_short_code || t('public.toDefine');
  return t('public.toDefine');
}

function eventTeam(match: TimelineMatch, event: PublicTimelineEvent): string {
  return teamName(match, timelineEventSide(event, match));
}

function beneficiaryTeam(match: TimelineMatch, event: PublicTimelineEvent): string | null {
  if (event.event_type !== 'own_goal' || !event.beneficiary_team_id) return null;
  return teamName(match, timelineEventSide({ team_id: event.beneficiary_team_id }, match));
}

function eventIcon(event: PublicTimelineEvent): string {
  if (event.event_type === 'yellow_card') return 'yellow';
  if (event.event_type === 'red_card') return 'red';
  if (event.event_type === 'substitution') return 'sub';
  return 'goal';
}

function formatScore(match: TimelineMatch): string {
  if (match.home_score === null || match.away_score === null) return '-';
  if (match.home_penalties === null || match.away_penalties === null) {
    return `${match.home_score}-${match.away_score}`;
  }
  return `${match.home_score}-${match.away_score} (${match.home_penalties}-${match.away_penalties} ${t('public.penalties')})`;
}
</script>

<template>
  <dialog
    v-if="match"
    :id="dialogId"
    ref="dialog"
    class="timeline-dialog"
    aria-modal="true"
    :aria-labelledby="titleId"
    @cancel="handleCancel"
    @close="handleNativeClose"
    @click="handleDialogClick"
  >
    <div class="timeline-dialog-shell">
      <header class="timeline-dialog-header">
        <div class="timeline-dialog-title">
          <p class="eyebrow">{{ t('publicTimeline.title') }} · {{ match.stage_name }}</p>
          <PublicRectifiedMark :rectified-at="match.rectified_at" />
          <h2 :id="titleId">
            {{ teamName(match, 'home') }} <b>{{ formatScore(match) }}</b> {{ teamName(match, 'away') }}
          </h2>
        </div>
        <button
          autofocus
          class="timeline-close"
          type="button"
          :aria-label="t('common.close')"
          @click="close"
        >
          {{ t('common.close') }}
        </button>
      </header>

      <div class="timeline-dialog-content" :aria-busy="loading ? 'true' : 'false'">
        <p v-if="loading" class="timeline-state" role="status">{{ t('publicTimeline.loading') }}</p>
        <div v-else-if="error" class="timeline-state" role="alert">
          <p>{{ t('publicTimeline.error') }}</p>
          <button class="timeline-retry" type="button" @click="emit('retry')">{{ t('publicTimeline.retry') }}</button>
        </div>
        <template v-else-if="timeline">
          <p v-if="timeline.availability === 'pending'" class="timeline-state">{{ t('publicTimeline.pending') }}</p>
          <p v-else-if="timeline.availability === 'not_played'" class="timeline-state">{{ t('publicTimeline.notPlayed') }}</p>
          <template v-else>
            <p v-if="!timeline.score_consistent" class="timeline-note" role="note">{{ t('publicTimeline.scoreMismatch') }}</p>
            <p v-if="!timeline.events.length" class="timeline-state">{{ t('publicTimeline.empty') }}</p>
            <section
              v-for="group in timelineGroups(timeline)"
              :key="group.segmentNumber"
              class="timeline-group"
            >
              <h3 v-if="group.showSeparator" class="timeline-separator">{{ t('public.segment', { n: group.segmentNumber }) }}</h3>
              <p v-if="!group.events.length" class="timeline-segment-empty">{{ t('publicTimeline.segmentEmpty') }}</p>
              <ol v-else class="timeline-list">
                <li
                  v-for="(event, index) in group.events"
                  :key="`${group.segmentNumber}-${index}`"
                  class="timeline-event"
                  :data-side="timelineEventSide(event, match) ?? undefined"
                >
                  <span class="timeline-minute">{{ formatTimelineMinute(event.minute, event.added_minute) }}</span>
                  <span class="timeline-icon" :data-kind="eventIcon(event)" aria-hidden="true" />
                  <span class="timeline-body">
                    <strong>{{ t(timelineEventKey(event)) }}</strong>
                    <template v-if="event.event_type === 'substitution'">
                      <span>{{ t('publicTimeline.playerOut') }}: {{ timelinePlayerName(event.player) }}</span>
                      <span v-if="event.player_in">{{ t('publicTimeline.playerIn') }}: {{ timelinePlayerName(event.player_in) }}</span>
                    </template>
                    <span v-else>{{ timelinePlayerName(event.player) }}</span>
                    <small>{{ eventTeam(match, event) }}</small>
                    <small v-if="beneficiaryTeam(match, event)">{{ t('publicTimeline.beneficiary') }}: {{ beneficiaryTeam(match, event) }}</small>
                  </span>
                </li>
              </ol>
            </section>
          </template>
        </template>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.timeline-dialog { width: min(640px, calc(100vw - 32px)); max-width: none; max-height: calc(100dvh - 32px); margin: auto; padding: 0; overflow: hidden; border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 98%, transparent), color-mix(in srgb, var(--color-canvas) 99%, transparent)); color: var(--color-ink); box-shadow: 0 28px 100px color-mix(in srgb, var(--color-shadow) 50%, transparent); }
.timeline-dialog::backdrop { background: color-mix(in srgb, var(--color-shadow) 78%, transparent); backdrop-filter: blur(5px); }
.timeline-dialog-shell { display: flex; max-height: calc(100dvh - 32px); flex-direction: column; }
.timeline-dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-6); padding: var(--space-6); border-bottom: 1px solid var(--color-line); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); }
.timeline-dialog-title { min-width: 0; }
.timeline-dialog-title h2 { margin: var(--space-2) 0 0; font-size: var(--text-lg); letter-spacing: -0.05em; line-height: 1.1; overflow-wrap: anywhere; }
.timeline-dialog-title h2 b { color: var(--color-accent); }
.timeline-close, .timeline-retry { flex: 0 0 auto; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: transparent; color: var(--color-ink); font-size: var(--text-xs); font-weight: 800; text-transform: uppercase; }
.timeline-close:hover, .timeline-retry:hover { border-color: var(--color-accent); color: var(--color-accent); }
.timeline-dialog-content { min-height: 0; overflow-y: auto; padding: var(--space-5) var(--space-6) var(--space-7); }
.timeline-state { color: var(--color-muted); font-size: var(--text-sm); }
.timeline-note { margin: 0 0 var(--space-4); padding: var(--space-2) var(--space-3); border: 1px solid var(--color-accent); border-radius: var(--radius-sm); color: var(--color-ink); font-size: var(--text-xs); }
.timeline-group + .timeline-group { margin-top: var(--space-5); }
.timeline-separator { margin: 0 0 var(--space-2); color: var(--color-muted); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
.timeline-segment-empty { margin: 0; padding: var(--space-2) 0; border-bottom: 1px solid var(--color-line); color: var(--color-muted); font-size: var(--text-sm); }
.timeline-list { display: grid; gap: var(--space-2); margin: 0; padding: 0; list-style: none; }
.timeline-event { display: grid; grid-template-columns: 56px 16px minmax(0, 1fr); align-items: start; gap: var(--space-3); padding: var(--space-2) 0; border-bottom: 1px solid var(--color-line); }
.timeline-minute { color: var(--color-accent); font-size: var(--text-sm); font-variant-numeric: tabular-nums; font-weight: 800; }
.timeline-icon { width: 12px; height: 16px; margin-top: var(--space-1); border: 1px solid var(--color-muted); border-radius: var(--radius-sm); }
.timeline-icon[data-kind="goal"], .timeline-icon[data-kind="sub"] { width: 12px; height: 12px; border-radius: 50%; }
.timeline-icon[data-kind="yellow"] { background: var(--color-warning); border-color: var(--color-warning); }
.timeline-icon[data-kind="red"] { background: var(--color-danger); border-color: var(--color-danger); }
.timeline-icon[data-kind="goal"] { background: var(--color-ink); border-color: var(--color-ink); }
.timeline-body { display: grid; gap: var(--space-1); min-width: 0; font-size: var(--text-sm); overflow-wrap: anywhere; }
.timeline-body small { color: var(--color-muted); font-size: var(--text-2xs); text-transform: uppercase; }
@media (max-width: 760px) {
  .timeline-dialog { width: calc(100vw - 20px); max-height: calc(100dvh - 20px); }
  .timeline-dialog-shell { max-height: calc(100dvh - 20px); }
  .timeline-dialog-header { gap: var(--space-3); padding: var(--space-4); }
  .timeline-dialog-content { padding: var(--space-4) var(--space-4) var(--space-6); }
  .timeline-event { grid-template-columns: 48px 16px minmax(0, 1fr); gap: var(--space-2); }
}
:root[data-theme="light"] .timeline-dialog::backdrop { background: color-mix(in srgb, var(--color-shadow) 32%, transparent); opacity: 1; }
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] .timeline-dialog::backdrop { background: color-mix(in srgb, var(--color-shadow) 32%, transparent); opacity: 1; }
}
</style>
