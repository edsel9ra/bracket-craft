<script setup lang="ts">
import { FORMATIONS_GRID, type FormationCode } from '~/constants/formations';
import { positionLabel } from '~/utils/positions';
import { playerInitials } from '~/utils/publicLineup';
import type { PublicLineupPlayer, PublicTeamLineup } from '~/utils/publicTournament';

const props = defineProps<{
  team: PublicTeamLineup;
}>();

const { t } = useI18n();

function playerName(player: PublicLineupPlayer): string {
  return player.last_name || player.first_name;
}

function playerStyle(player: PublicLineupPlayer): Record<string, string> {
  if (!player.position_slot) return {};
  const formation = props.team.formation_code;
  if (!formation) return {};
  const point = FORMATIONS_GRID[formation as FormationCode]?.[player.position_slot];
  if (!point) return {};
  return {
    left: `${point.x}%`,
    top: `${point.y}%`,
  };
}
</script>

<template>
  <section class="team-pitch" :aria-label="team.team_name">
    <header class="team-pitch-header">
      <span class="team-pitch-name">{{ team.team_name }}</span>
      <strong class="team-pitch-formation">{{ team.formation_code }}</strong>
    </header>
    <div class="pitch">
      <div class="pitch-half-line" />
      <div class="pitch-center-circle" />
      <div class="pitch-center-dot" />
      <div class="pitch-box pitch-box-top" />
      <div class="pitch-box pitch-box-bottom" />
      <div
        v-for="player in team.starters"
        :key="`starter-${player.player_id}`"
        class="pitch-player"
        :style="playerStyle(player)"
      >
        <img v-if="player.photo_url" :src="player.photo_url" :alt="playerName(player)" loading="lazy" />
        <span v-else class="player-avatar">{{ playerInitials(player) }}</span>
        <span class="player-number">{{ player.dorsal_number ?? '—' }}</span>
        <span class="player-name">{{ playerName(player) }}</span>
        <span class="player-position">{{ positionLabel(player.position_slot || '', t) }}</span>
      </div>
    </div>
    <div class="team-pitch-substitutes">
      <small>{{ t('public.substitutes') }}</small>
      <span
        v-for="player in team.substitutes"
        :key="`substitute-${player.player_id}`"
        class="bench-player"
      >
        #{{ player.dorsal_number ?? '—' }} {{ playerName(player) }}
      </span>
      <span v-if="!team.substitutes.length" class="bench-empty">{{ t('public.noLineup') }}</span>
    </div>
  </section>
</template>

<style scoped>
.team-pitch { display: grid; gap: 10px; }
.team-pitch-header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.team-pitch-name { overflow: hidden; color: var(--muted); font-size: 0.72rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; text-overflow: ellipsis; white-space: nowrap; }
.team-pitch-formation { color: var(--accent); font-size: 1.1rem; letter-spacing: -0.04em; }
.pitch { position: relative; aspect-ratio: 1.1 / 1; overflow: hidden; border: 2px solid rgba(236, 255, 206, 0.62); border-radius: 13px; background: repeating-linear-gradient(90deg, #315b35 0, #315b35 12%, #38673b 12%, #38673b 24%); box-shadow: inset 0 0 55px rgba(0, 0, 0, 0.2); }
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
.pitch-player { position: absolute; z-index: 2; display: grid; width: 52px; justify-items: center; gap: 1px; transform: translate(-50%, -50%); filter: drop-shadow(0 5px 7px rgba(0, 0, 0, 0.35)); }
.pitch-player img, .player-avatar { width: 30px; height: 30px; border: 2px solid var(--accent); border-radius: 50%; background: #172218; color: var(--accent); object-fit: cover; font-size: 0.62rem; font-weight: 900; line-height: 26px; text-align: center; }
.player-number { margin-top: -8px; padding: 2px 5px; border-radius: 5px; background: #0c0f0c; color: var(--ink); font-size: 0.62rem; font-weight: 900; }
.pitch-player .player-name { max-width: 68px; overflow: hidden; color: var(--ink); font-size: 0.6rem; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.player-position { color: var(--accent); font-size: 0.52rem; font-weight: 800; text-transform: uppercase; }
.team-pitch-substitutes { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 9px; border: 1px solid rgba(166, 170, 159, 0.14); border-radius: 9px; background: rgba(12, 15, 12, 0.28); }
.team-pitch-substitutes small { flex-basis: 100%; color: var(--muted); font-size: 0.58rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
.bench-player { padding: 4px 6px; border-radius: 5px; background: rgba(212, 243, 106, 0.08); color: var(--ink); font-size: 0.63rem; }
.bench-empty { color: var(--muted); font-size: 0.63rem; }
@media (max-width: 520px) { .pitch { aspect-ratio: 0.92 / 1; } .pitch-player { width: 46px; } .pitch-player img, .player-avatar { width: 26px; height: 26px; line-height: 22px; } .pitch-player .player-name { max-width: 52px; font-size: 0.54rem; } }
</style>