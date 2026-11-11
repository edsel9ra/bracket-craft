<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import TeamPitch from './TeamPitch.vue';
import { positionLabel } from '~/utils/positions';
import { isTacticalFormationValid, textualFormationLines, playerInitials } from '~/utils/publicLineup';
import type { PublicLineupPlayer, PublicTeamLineup } from '~/utils/publicTournament';

type LineupPlayer = PublicLineupPlayer;
type TeamLineup = PublicTeamLineup;

interface MatchLineup {
  home: TeamLineup | null;
  away: TeamLineup | null;
}

interface LineupMatch {
  id: string;
  stage_name: string;
  match_date: string | null;
  home_team_name: string | null;
  home_team_short_code: string | null;
  away_team_name: string | null;
  away_team_short_code: string | null;
  home_score: number | null;
  away_score: number | null;
  home_penalties: number | null;
  away_penalties: number | null;
  lineup: MatchLineup | null;
}

const props = defineProps<{
  open: boolean;
  match: LineupMatch | null;
}>();
const emit = defineEmits<{
  close: [];
}>();
const { t, formatDateTime } = useI18n();
const dialog = ref<HTMLDialogElement | null>(null);
const dialogId = 'public-lineup-dialog';
const titleId = 'public-lineup-dialog-title';
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

function playerName(player: LineupPlayer): string {
  return `${player.first_name} ${player.last_name}`.trim();
}

function lineupTeams(match: LineupMatch): TeamLineup[] {
  return [match.lineup?.home, match.lineup?.away].filter(
    (team): team is TeamLineup => Boolean(team),
  );
}

function isTactical(team: TeamLineup): boolean {
  return isTacticalFormationValid(team);
}

function segmentLabel(team: TeamLineup): string {
  if (team.segment_number === null || team.segment_number === undefined) return '';
  return t('public.segment', { n: team.segment_number });
}

function lineLabel(line: 'gk' | 'def' | 'mid' | 'att'): string {
  if (line === 'gk') return t('public.line.gk');
  if (line === 'def') return t('public.line.def');
  if (line === 'mid') return t('public.line.mid');
  return t('public.line.att');
}

function formatScore(match: LineupMatch): string {
  if (match.home_score === null || match.away_score === null) return '-';
  if (match.home_penalties === null || match.away_penalties === null) {
    return `${match.home_score}-${match.away_score}`;
  }
  return `${match.home_score}-${match.away_score} (${match.home_penalties}-${match.away_penalties} ${t('public.penalties')})`;
}

function formatDate(value: string | null): string {
  if (!value) return t('public.dateToDefine');
  return formatDateTime(value);
}
</script>

<template>
  <dialog
    v-if="match"
    :id="dialogId"
    ref="dialog"
    class="lineup-dialog"
    aria-modal="true"
    :aria-labelledby="titleId"
    @cancel="handleCancel"
    @close="handleNativeClose"
    @click="handleDialogClick"
  >
    <div class="lineup-dialog-shell">
      <header class="lineup-dialog-header">
        <div class="lineup-dialog-title">
          <p class="eyebrow">{{ match.stage_name }}</p>
          <h2 :id="titleId">
            <span class="lineup-team">
              <TeamCrest
                :team="{ name: match.home_team_name || match.home_team_short_code || t('public.toDefine'), short_code: match.home_team_short_code }"
                :crest-url="match.lineup?.home?.crest_url ?? null"
                surface="public"
              />
              <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
            </span>
            <b>vs</b>
            <span class="lineup-team">
              <TeamCrest
                :team="{ name: match.away_team_name || match.away_team_short_code || t('public.toDefine'), short_code: match.away_team_short_code }"
                :crest-url="match.lineup?.away?.crest_url ?? null"
                surface="public"
              />
              <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
            </span>
          </h2>
          <p class="lineup-dialog-meta">{{ formatScore(match) }} · {{ formatDate(match.match_date) }}</p>
        </div>
        <button
          autofocus
          class="lineup-close"
          type="button"
          :aria-label="t('common.close')"
          @click="close"
        >
          {{ t('common.close') }}
        </button>
      </header>

      <div class="lineup-dialog-content">
        <template v-if="match.lineup">
          <section
            v-for="team in lineupTeams(match)"
            :key="team.team_id"
            class="lineup-section"
          >
            <div class="lineup-section-heading">
              <div>
                <p class="eyebrow">
                  {{ isTactical(team) ? t('public.tacticalFormation') : t('public.matchLineup') }}
                </p>
                <h3>{{ team.team_name }}</h3>
              </div>
              <span v-if="isTactical(team) && segmentLabel(team)" class="lineup-section-note">
                {{ segmentLabel(team) }}
              </span>
            </div>

            <template v-if="isTactical(team)">
              <TeamPitch :team="team" />
              <details class="textual-equivalent">
                <summary>{{ t('public.textualEquivalent') }}</summary>
                <ol class="textual-equivalent-list">
                  <li v-for="entry in textualFormationLines(team)" :key="entry.line" class="textual-equivalent-line">
                    <strong>{{ lineLabel(entry.line) }}</strong>
                    <ul>
                      <li v-for="player in entry.players" :key="player.player_id">
                        #{{ player.dorsal_number ?? '—' }} {{ playerName(player) }}
                        <span v-if="player.position_slot"> ({{ positionLabel(player.position_slot, t) }})</span>
                      </li>
                    </ul>
                  </li>
                </ol>
              </details>
            </template>

            <template v-else>
              <div class="lineup-modal-roles">
                <div>
                  <small>{{ t('public.starters') }}</small>
                  <template v-if="team.starters.length">
                    <p v-for="player in team.starters" :key="`starter-${player.player_id}`" class="lineup-modal-player">
                      <span class="lineup-modal-player-avatar" aria-hidden="true">
                        <img v-if="player.photo_url" :src="player.photo_url" :alt="playerName(player)" loading="lazy" />
                        <span v-else>{{ playerInitials(player) }}</span>
                      </span>
                      <b>#{{ player.dorsal_number ?? '—' }}</b>
                      <span class="lineup-modal-player-name">{{ playerName(player) }}</span>
                      <em v-if="player.position_slot">{{ positionLabel(player.position_slot, t) }}</em>
                    </p>
                  </template>
                  <p v-else class="lineup-modal-empty">{{ t('public.noLineup') }}</p>
                </div>
                <div>
                  <small>{{ t('public.substitutes') }}</small>
                  <template v-if="team.substitutes.length">
                    <p v-for="player in team.substitutes" :key="`substitute-${player.player_id}`" class="lineup-modal-player">
                      <span class="lineup-modal-player-avatar" aria-hidden="true">
                        <img v-if="player.photo_url" :src="player.photo_url" :alt="playerName(player)" loading="lazy" />
                        <span v-else>{{ playerInitials(player) }}</span>
                      </span>
                      <b>#{{ player.dorsal_number ?? '—' }}</b>
                      <span class="lineup-modal-player-name">{{ playerName(player) }}</span>
                    </p>
                  </template>
                  <p v-else class="lineup-modal-empty">{{ t('public.noLineup') }}</p>
                </div>
              </div>
            </template>
          </section>

          <p v-if="!lineupTeams(match).length" class="lineup-modal-empty" />
        </template>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
/* RF-006: el separador de los equipos usa 0.62em para seguir proporcional al título. */
.lineup-dialog { width: min(1080px, calc(100vw - 32px)); max-width: none; max-height: calc(100dvh - 32px); margin: auto; padding: 0; overflow: hidden; border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: linear-gradient(145deg, color-mix(in srgb, var(--color-surface-raised) 98%, transparent), color-mix(in srgb, var(--color-canvas) 99%, transparent)); color: var(--color-ink); box-shadow: 0 28px 100px color-mix(in srgb, var(--color-shadow) 50%, transparent); }
.lineup-dialog::backdrop { background: color-mix(in srgb, var(--color-shadow) 78%, transparent); backdrop-filter: blur(5px); }
.lineup-dialog-shell { display: flex; max-height: calc(100dvh - 32px); flex-direction: column; }
.lineup-dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-6); padding: var(--space-6) var(--space-6); border-bottom: 1px solid var(--color-line); background: color-mix(in srgb, var(--color-canvas) 72%, transparent); }
.lineup-dialog-title { min-width: 0; }
.lineup-dialog-title h2 { display: flex; align-items: center; gap: var(--space-3); margin: var(--space-2) 0 var(--space-1); font-size: var(--text-xl); letter-spacing: -0.06em; line-height: 1; }
.lineup-dialog-title h2 span { overflow-wrap: anywhere; }
.lineup-dialog-title h2 b { color: var(--color-accent); font-size: 0.62em; letter-spacing: 0; }
.lineup-team { display: inline-flex; align-items: center; gap: var(--space-2); min-width: 0; }
.lineup-dialog-meta { margin: 0; color: var(--color-muted); font-size: var(--text-xs); }
.lineup-close { flex: 0 0 auto; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: transparent; color: var(--color-ink); font-size: var(--text-xs); font-weight: 800; text-transform: uppercase; }
.lineup-close:hover { border-color: var(--color-accent); color: var(--color-accent); }
.lineup-dialog-content { min-height: 0; overflow-y: auto; padding: var(--space-6) var(--space-6) var(--space-7); }
.lineup-section { display: grid; gap: var(--space-4); }
.lineup-section + .lineup-section { margin-top: var(--space-7); padding-top: var(--space-6); border-top: 1px solid var(--color-line); }
.lineup-section-heading { display: flex; align-items: end; justify-content: space-between; gap: var(--space-4); }
.lineup-section-heading h3 { margin: var(--space-2) 0 0; font-size: var(--text-lg); letter-spacing: -0.05em; }
.lineup-section-note { color: var(--color-muted); font-size: var(--text-xs); }
.lineup-modal-roles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-5); padding-top: var(--space-3); }
.lineup-modal-roles small { color: var(--color-muted); font-size: var(--text-2xs); font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
.lineup-modal-player { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: var(--space-2); margin: var(--space-2) 0 0; color: var(--color-ink); font-size: var(--text-md); line-height: 1.3; }
.lineup-modal-player b { color: var(--color-accent); }
.lineup-modal-player-name { overflow-wrap: anywhere; }
.lineup-modal-player em { grid-column: 2; color: var(--color-muted); font-size: var(--text-2xs); font-style: normal; text-transform: uppercase; }
.lineup-modal-empty { color: var(--color-muted); font-size: var(--text-sm); }
.lineup-modal-player-avatar { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--color-line); background: color-mix(in srgb, var(--color-canvas) 50%, transparent); color: var(--color-accent); font-size: var(--text-2xs); font-weight: 900; overflow: hidden; }
.lineup-modal-player-avatar img { width: 100%; height: 100%; object-fit: cover; }
.textual-equivalent { margin-top: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 35%, transparent); }
.textual-equivalent summary { cursor: pointer; color: var(--color-accent); font-size: var(--text-xs); font-weight: 800; text-transform: uppercase; }
.textual-equivalent-list { margin: var(--space-2) 0 0; padding-left: var(--space-4); }
.textual-equivalent-line { margin: var(--space-1) 0; }
.textual-equivalent-line strong { color: var(--color-ink); }
.textual-equivalent-line ul { margin: var(--space-1) 0 0; padding-left: var(--space-4); }
@media (max-width: 760px) {
  .lineup-dialog { width: calc(100vw - 20px); max-height: calc(100dvh - 20px); border-radius: var(--radius-lg); }
  .lineup-dialog-shell { max-height: calc(100dvh - 20px); }
  .lineup-dialog-header { gap: var(--space-3); padding: var(--space-4); }
  .lineup-dialog-title h2 { align-items: flex-start; flex-direction: column; gap: var(--space-1); font-size: var(--text-lg); }
  .lineup-dialog-title h2 b { display: none; }
  .lineup-close { padding: var(--space-2) var(--space-2); }
  .lineup-dialog-content { padding: var(--space-5) var(--space-4) var(--space-6); }
  .lineup-modal-roles { grid-template-columns: 1fr; gap: var(--space-4); }
}
@media (max-width: 480px) {
  .lineup-modal-roles { grid-template-columns: 1fr; gap: var(--space-4); }
}
</style>
