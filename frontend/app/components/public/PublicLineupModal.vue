<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
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
.lineup-dialog { width: min(1080px, calc(100vw - 32px)); max-width: none; max-height: calc(100dvh - 32px); margin: auto; padding: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 24px; background: linear-gradient(145deg, rgba(32, 37, 30, 0.98), rgba(15, 19, 15, 0.99)); color: var(--ink); box-shadow: 0 28px 100px rgba(0, 0, 0, 0.5); }
.lineup-dialog::backdrop { background: rgba(4, 6, 4, 0.78); backdrop-filter: blur(5px); }
.lineup-dialog-shell { display: flex; max-height: calc(100dvh - 32px); flex-direction: column; }
.lineup-dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 24px 28px; border-bottom: 1px solid var(--line); background: rgba(12, 15, 12, 0.72); }
.lineup-dialog-title { min-width: 0; }
.lineup-dialog-title h2 { display: flex; align-items: center; gap: 14px; margin: 8px 0 6px; font-size: clamp(1.35rem, 3vw, 2.3rem); letter-spacing: -0.06em; line-height: 1; }
.lineup-dialog-title h2 span { overflow-wrap: anywhere; }
.lineup-dialog-title h2 b { color: var(--accent); font-size: 0.62em; letter-spacing: 0; }
.lineup-team { display: inline-flex; align-items: center; gap: 10px; min-width: 0; }
.lineup-dialog-meta { margin: 0; color: var(--muted); font-size: 0.78rem; }
.lineup-close { flex: 0 0 auto; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--ink); font-size: 0.72rem; font-weight: 800; text-transform: uppercase; }
.lineup-close:hover { border-color: var(--accent); color: var(--accent); }
.lineup-dialog-content { min-height: 0; overflow-y: auto; padding: 26px 28px 34px; }
.lineup-section { display: grid; gap: 16px; }
.lineup-section + .lineup-section { margin-top: 30px; padding-top: 26px; border-top: 1px solid var(--line); }
.lineup-section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; }
.lineup-section-heading h3 { margin: 7px 0 0; font-size: 1.45rem; letter-spacing: -0.05em; }
.lineup-section-note { color: var(--muted); font-size: 0.76rem; }
.lineup-modal-roles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; padding-top: 14px; }
.lineup-modal-roles small { color: var(--muted); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
.lineup-modal-player { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 8px; margin: 10px 0 0; color: var(--ink); font-size: 0.88rem; line-height: 1.3; }
.lineup-modal-player b { color: var(--accent); }
.lineup-modal-player-name { overflow-wrap: anywhere; }
.lineup-modal-player em { grid-column: 2; color: var(--muted); font-size: 0.68rem; font-style: normal; text-transform: uppercase; }
.lineup-modal-empty { color: var(--muted); font-size: 0.8rem; }
.lineup-modal-player-avatar { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--line); background: rgba(12, 15, 12, 0.5); color: var(--accent); font-size: 0.62rem; font-weight: 900; overflow: hidden; }
.lineup-modal-player-avatar img { width: 100%; height: 100%; object-fit: cover; }
.textual-equivalent { margin-top: 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: rgba(12, 15, 12, 0.35); }
.textual-equivalent summary { cursor: pointer; color: var(--accent); font-size: 0.78rem; font-weight: 800; text-transform: uppercase; }
.textual-equivalent-list { margin: 10px 0 0; padding-left: 18px; }
.textual-equivalent-line { margin: 6px 0; }
.textual-equivalent-line strong { color: var(--ink); }
.textual-equivalent-line ul { margin: 4px 0 0; padding-left: 16px; }
@media (max-width: 700px) {
  .lineup-dialog { width: calc(100vw - 20px); max-height: calc(100dvh - 20px); border-radius: 17px; }
  .lineup-dialog-shell { max-height: calc(100dvh - 20px); }
  .lineup-dialog-header { gap: 14px; padding: 18px; }
  .lineup-dialog-title h2 { align-items: flex-start; flex-direction: column; gap: 5px; font-size: 1.45rem; }
  .lineup-dialog-title h2 b { display: none; }
  .lineup-close { padding: 8px 10px; }
  .lineup-dialog-content { padding: 20px 18px 26px; }
  .lineup-modal-roles { grid-template-columns: 1fr; gap: 16px; }
}
@media (max-width: 420px) {
  .lineup-modal-roles { grid-template-columns: 1fr; gap: 16px; }
}
</style>
