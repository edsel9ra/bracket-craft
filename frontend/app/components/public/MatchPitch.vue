<script setup lang="ts">
import { FORMATIONS_GRID, positionLabel, type FormationCode } from '~/constants/formations';

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

const props = withDefaults(defineProps<{
  home: TeamLineup;
  away: TeamLineup;
  showBench?: boolean;
}>(), {
  showBench: true,
});
const { t } = useI18n();
const OWN_HALF_START_Y = 52;
const OWN_HALF_SCALE = 0.42;

function playerName(player: LineupPlayer): string {
  return player.last_name || player.first_name;
}

function playerInitials(player: LineupPlayer): string {
  return `${player.first_name.slice(0, 1)}${player.last_name.slice(0, 1)}`.toUpperCase();
}

function playerStyle(player: LineupPlayer, side: 'home' | 'away'): Record<string, string> {
  if (!player.position_slot) return {};
  const formation = side === 'home' ? props.home.formation_code : props.away.formation_code;
  if (!formation) return {};
  const point = FORMATIONS_GRID[formation][player.position_slot];
  if (!point) return {};
  const homeHalfY = OWN_HALF_START_Y + point.y * OWN_HALF_SCALE;
  return {
    left: `${point.x}%`,
    top: `${side === 'home' ? homeHalfY : 100 - homeHalfY}%`,
  };
}
</script>

<template>
  <section class="pitch-section" :aria-label="t('public.tacticalView')">
    <div class="pitch-heading">
      <div><span class="pitch-label">{{ home.team_name }}</span><strong>{{ home.formation_code }}</strong></div>
      <span class="pitch-vs">vs</span>
      <div class="pitch-heading-away"><span class="pitch-label">{{ away.team_name }}</span><strong>{{ away.formation_code }}</strong></div>
    </div>
    <div class="pitch">
      <div class="pitch-half-line" />
      <div class="pitch-center-circle" />
      <div class="pitch-center-dot" />
      <div class="pitch-box pitch-box-top" />
      <div class="pitch-box pitch-box-bottom" />
      <div
        v-for="player in away.starters"
        :key="`away-${player.player_id}`"
        class="pitch-player pitch-player-away"
        :style="playerStyle(player, 'away')"
      >
        <img v-if="player.photo_url" :src="player.photo_url" :alt="playerName(player)" loading="lazy" />
        <span v-else class="player-avatar">{{ playerInitials(player) }}</span>
        <span class="player-number">{{ player.dorsal_number ?? '—' }}</span>
        <span class="player-name">{{ playerName(player) }}</span>
        <span class="player-position">{{ positionLabel(player.position_slot || '') }}</span>
      </div>
      <div
        v-for="player in home.starters"
        :key="`home-${player.player_id}`"
        class="pitch-player pitch-player-home"
        :style="playerStyle(player, 'home')"
      >
        <img v-if="player.photo_url" :src="player.photo_url" :alt="playerName(player)" loading="lazy" />
        <span v-else class="player-avatar">{{ playerInitials(player) }}</span>
        <span class="player-number">{{ player.dorsal_number ?? '—' }}</span>
        <span class="player-name">{{ playerName(player) }}</span>
        <span class="player-position">{{ positionLabel(player.position_slot || '') }}</span>
      </div>
    </div>
    <div v-if="showBench" class="bench-grid">
      <div class="bench-team">
        <small>{{ home.team_name }} · {{ t('public.substitutes') }}</small>
        <span v-for="player in home.substitutes" :key="`home-sub-${player.player_id}`" class="bench-player">#{{ player.dorsal_number ?? '—' }} {{ playerName(player) }}</span>
        <span v-if="!home.substitutes.length" class="bench-empty">{{ t('public.noLineup') }}</span>
      </div>
      <div class="bench-team bench-team-away">
        <small>{{ away.team_name }} · {{ t('public.substitutes') }}</small>
        <span v-for="player in away.substitutes" :key="`away-sub-${player.player_id}`" class="bench-player">#{{ player.dorsal_number ?? '—' }} {{ playerName(player) }}</span>
        <span v-if="!away.substitutes.length" class="bench-empty">{{ t('public.noLineup') }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pitch-section { display: grid; gap: 13px; }
.pitch-heading { display: grid; grid-template-columns: 1fr auto 1fr; align-items: end; gap: 12px; color: var(--ink); }
.pitch-heading div { display: grid; gap: 3px; }
.pitch-heading-away { text-align: right; }
.pitch-heading strong { color: var(--accent); font-size: 1.1rem; letter-spacing: -0.04em; }
.pitch-label { overflow: hidden; color: var(--muted); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }
.pitch-vs { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }
.pitch { position: relative; aspect-ratio: 1.35 / 1; overflow: hidden; border: 2px solid rgba(236, 255, 206, 0.62); border-radius: 13px; background: repeating-linear-gradient(90deg, #315b35 0, #315b35 12%, #38673b 12%, #38673b 24%); box-shadow: inset 0 0 55px rgba(0, 0, 0, 0.2); }
.pitch::before, .pitch::after { position: absolute; border: 2px solid rgba(236, 255, 206, 0.55); content: ''; }
.pitch::before { inset: 0 0 50%; border-width: 0 0 2px; }
.pitch::after { top: 50%; left: 50%; width: 16%; aspect-ratio: 1; border-radius: 50%; transform: translate(-50%, -50%); }
.pitch-half-line, .pitch-center-circle, .pitch-center-dot, .pitch-box { position: absolute; pointer-events: none; }
.pitch-half-line { top: 50%; left: 0; right: 0; border-top: 2px solid rgba(236, 255, 206, 0.55); }
.pitch-center-circle { top: 50%; left: 50%; width: 16%; aspect-ratio: 1; border: 2px solid rgba(236, 255, 206, 0.55); border-radius: 50%; transform: translate(-50%, -50%); }
.pitch-center-dot { top: 50%; left: 50%; width: 5px; height: 5px; border-radius: 50%; background: rgba(236, 255, 206, 0.85); transform: translate(-50%, -50%); }
.pitch-box { left: 27%; width: 46%; height: 17%; border: 2px solid rgba(236, 255, 206, 0.55); }
.pitch-box-top { top: 0; border-top: 0; }
.pitch-box-bottom { bottom: 0; border-bottom: 0; }
.pitch-player { position: absolute; z-index: 2; display: grid; width: 58px; justify-items: center; gap: 1px; transform: translate(-50%, -50%); filter: drop-shadow(0 5px 7px rgba(0, 0, 0, 0.35)); }
.pitch-player img, .player-avatar { width: 34px; height: 34px; border: 2px solid var(--accent); border-radius: 50%; background: #172218; color: var(--accent); object-fit: cover; font-size: 0.62rem; font-weight: 900; line-height: 30px; text-align: center; }
.pitch-player-away img, .pitch-player-away .player-avatar { border-color: #ffcb7a; }
.player-number { margin-top: -8px; padding: 2px 5px; border-radius: 5px; background: #0c0f0c; color: var(--ink); font-size: 0.62rem; font-weight: 900; }
.pitch-player .player-name { max-width: 75px; overflow: hidden; color: var(--ink); font-size: 0.62rem; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.player-position { color: var(--accent); font-size: 0.53rem; font-weight: 800; text-transform: uppercase; }
.pitch-player-away .player-position { color: #ffcb7a; }
.bench-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.bench-team { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; padding: 9px; border: 1px solid rgba(166, 170, 159, 0.14); border-radius: 9px; background: rgba(12, 15, 12, 0.28); }
.bench-team small { flex-basis: 100%; color: var(--muted); font-size: 0.58rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
.bench-player { padding: 4px 6px; border-radius: 5px; background: rgba(212, 243, 106, 0.08); color: var(--ink); font-size: 0.63rem; }
.bench-empty { color: var(--muted); font-size: 0.63rem; }
.bench-team-away { text-align: right; }
@media (max-width: 520px) { .pitch { aspect-ratio: 0.92 / 1; } .pitch-player { width: 49px; } .pitch-player img, .player-avatar { width: 29px; height: 29px; line-height: 25px; } .pitch-player .player-name { max-width: 55px; font-size: 0.54rem; } }
@media (max-width: 520px) { .bench-grid { grid-template-columns: 1fr; } .bench-team-away { text-align: left; } }
</style>
