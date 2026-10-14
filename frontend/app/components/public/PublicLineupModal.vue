<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { positionLabel, type FormationCode } from '~/constants/formations';

interface LineupPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  dorsal_number: number | null;
  role: 'starter' | 'substitute';
  position_slot: string | null;
  photo_url: string | null;
}

interface TeamLineup {
  team_id: string;
  team_name: string;
  formation_code: FormationCode | null;
  starters: LineupPlayer[];
  substitutes: LineupPlayer[];
}

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
const { t, dateLocale } = useI18n();
const dialog = ref<HTMLDialogElement | null>(null);
const dialogId = 'public-lineup-dialog';
const titleId = 'public-lineup-dialog-title';

function showDialog() {
  if (dialog.value && !dialog.value.open) dialog.value.showModal();
}

function hideDialog() {
  if (dialog.value?.open) dialog.value.close();
}

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    void nextTick(showDialog);
  } else {
    hideDialog();
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
  return `${player.first_name} ${player.last_name}`;
}

function lineupTeams(match: LineupMatch): TeamLineup[] {
  return [match.lineup?.home, match.lineup?.away].filter(
    (team): team is TeamLineup => Boolean(team),
  );
}

function hasTacticalLineup(match: LineupMatch): boolean {
  const teams = [match.lineup?.home, match.lineup?.away];
  return teams.every((team) => Boolean(
    team?.formation_code
    && team.starters.length > 0
    && team.starters.every((player) => Boolean(player.position_slot)),
  ));
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
  return new Intl.DateTimeFormat(dateLocale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
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
            <span>{{ match.home_team_name || match.home_team_short_code || t('public.toDefine') }}</span>
            <b>vs</b>
            <span>{{ match.away_team_name || match.away_team_short_code || t('public.toDefine') }}</span>
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
          <section v-if="hasTacticalLineup(match)" class="lineup-section">
            <div class="lineup-section-heading">
              <div>
                <p class="eyebrow">{{ t('public.formationAvailable') }}</p>
                <h3>{{ t('public.tacticalView') }}</h3>
              </div>
            </div>
            <PublicMatchPitch
              class="lineup-modal-pitch"
              :home="match.lineup.home!"
              :away="match.lineup.away!"
              :show-bench="false"
            />
          </section>

          <section class="lineup-section lineup-list-section">
            <div class="lineup-section-heading">
              <div>
                <p class="eyebrow">{{ t('public.lineupView') }}</p>
                <h3>{{ t('public.listView') }}</h3>
              </div>
              <span v-if="!hasTacticalLineup(match)" class="lineup-section-note">{{ t('public.classicLineup') }}</span>
            </div>

            <div class="lineup-modal-lists">
              <article v-for="team in lineupTeams(match)" :key="team.team_id" class="lineup-modal-team">
                <div class="lineup-modal-team-heading">
                  <strong>{{ team.team_name }}</strong>
                  <span>{{ team.formation_code || t('public.classicLineup') }}</span>
                </div>
                <div class="lineup-modal-roles">
                  <div>
                    <small>{{ t('public.starters') }}</small>
                    <template v-if="team.starters.length">
                      <p v-for="player in team.starters" :key="`starter-${player.player_id}`" class="lineup-modal-player">
                        <b>#{{ player.dorsal_number ?? '—' }}</b>
                        <span class="lineup-modal-player-name">{{ playerName(player) }}</span>
                        <em v-if="player.position_slot">{{ positionLabel(player.position_slot) }}</em>
                      </p>
                    </template>
                    <p v-else class="lineup-modal-empty">{{ t('public.noLineup') }}</p>
                  </div>
                  <div>
                    <small>{{ t('public.substitutes') }}</small>
                    <template v-if="team.substitutes.length">
                      <p v-for="player in team.substitutes" :key="`substitute-${player.player_id}`" class="lineup-modal-player">
                        <b>#{{ player.dorsal_number ?? '—' }}</b>
                        <span class="lineup-modal-player-name">{{ playerName(player) }}</span>
                      </p>
                    </template>
                    <p v-else class="lineup-modal-empty">{{ t('public.noLineup') }}</p>
                  </div>
                </div>
              </article>
            </div>
          </section>
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
.lineup-dialog-meta { margin: 0; color: var(--muted); font-size: 0.78rem; }
.lineup-close { flex: 0 0 auto; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: var(--ink); font-size: 0.72rem; font-weight: 800; text-transform: uppercase; }
.lineup-close:hover { border-color: var(--accent); color: var(--accent); }
.lineup-dialog-content { min-height: 0; overflow-y: auto; padding: 26px 28px 34px; }
.lineup-section { display: grid; gap: 16px; }
.lineup-section + .lineup-section { margin-top: 30px; padding-top: 26px; border-top: 1px solid var(--line); }
.lineup-section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; }
.lineup-section-heading h3 { margin: 7px 0 0; font-size: 1.45rem; letter-spacing: -0.05em; }
.lineup-section-note { color: var(--muted); font-size: 0.76rem; }
.lineup-modal-pitch { width: min(100%, 980px); margin: 0 auto; }
.lineup-modal-pitch :deep(.pitch-player) { width: clamp(62px, 7vw, 80px); }
.lineup-modal-pitch :deep(.pitch-player img), .lineup-modal-pitch :deep(.player-avatar) { width: 42px; height: 42px; line-height: 38px; }
.lineup-modal-pitch :deep(.player-number) { font-size: 0.72rem; }
.lineup-modal-pitch :deep(.pitch-player .player-name) { max-width: 104px; font-size: 0.72rem; }
.lineup-modal-pitch :deep(.player-position) { font-size: 0.62rem; }
.lineup-modal-lists { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.lineup-modal-team { min-width: 0; padding: 18px; border: 1px solid rgba(166, 170, 159, 0.18); border-radius: 14px; background: rgba(12, 15, 12, 0.4); }
.lineup-modal-team-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.lineup-modal-team-heading strong { overflow-wrap: anywhere; font-size: 1rem; }
.lineup-modal-team-heading span { flex: 0 0 auto; color: var(--accent); font-size: 0.72rem; }
.lineup-modal-roles { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 22px; padding-top: 14px; }
.lineup-modal-roles small { color: var(--muted); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; }
.lineup-modal-player { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 8px; margin: 10px 0 0; color: var(--ink); font-size: 0.88rem; line-height: 1.3; }
.lineup-modal-player b { color: var(--accent); }
.lineup-modal-player-name { overflow-wrap: anywhere; }
.lineup-modal-player em { grid-column: 2; color: var(--muted); font-size: 0.68rem; font-style: normal; text-transform: uppercase; }
.lineup-modal-empty { color: var(--muted); font-size: 0.8rem; }
@media (max-width: 700px) {
  .lineup-dialog { width: calc(100vw - 20px); max-height: calc(100dvh - 20px); border-radius: 17px; }
  .lineup-dialog-shell { max-height: calc(100dvh - 20px); }
  .lineup-dialog-header { gap: 14px; padding: 18px; }
  .lineup-dialog-title h2 { align-items: flex-start; flex-direction: column; gap: 5px; font-size: 1.45rem; }
  .lineup-dialog-title h2 b { display: none; }
  .lineup-close { padding: 8px 10px; }
  .lineup-dialog-content { padding: 20px 18px 26px; }
  .lineup-modal-lists { grid-template-columns: 1fr; }
}
@media (max-width: 520px) {
  .lineup-modal-pitch :deep(.pitch-player) { width: 56px; }
  .lineup-modal-pitch :deep(.pitch-player img), .lineup-modal-pitch :deep(.player-avatar) { width: 34px; height: 34px; line-height: 30px; }
  .lineup-modal-pitch :deep(.pitch-player .player-name) { max-width: 72px; font-size: 0.62rem; }
  .lineup-modal-pitch :deep(.player-position) { font-size: 0.55rem; }
}
@media (max-width: 420px) {
  .lineup-modal-roles { grid-template-columns: 1fr; gap: 16px; }
}
</style>
