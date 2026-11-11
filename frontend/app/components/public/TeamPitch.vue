<script setup lang="ts">
import { FORMATIONS_GRID, type FormationCode } from '~/constants/formations';
import { positionAbbreviation, positionLabel } from '~/utils/positions';
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
        <span class="player-position" :title="positionLabel(player.position_slot, t)"><span aria-hidden="true">{{ positionAbbreviation(player.position_slot, t) }}</span><span class="visually-hidden">{{ positionLabel(player.position_slot, t) }}</span></span>
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
/* RF-006: etiquetas bajo escala y gap de 1px conservan la geometría táctica; nombres completos en la alternativa textual. */
.team-pitch { display: grid; gap: var(--space-2); container-type: inline-size; }
.team-pitch-header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-2); }
.team-pitch-name { overflow: hidden; color: var(--color-muted); font-size: var(--text-xs); font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; text-overflow: ellipsis; white-space: nowrap; }
.team-pitch-formation { color: var(--color-accent); font-size: var(--text-base); letter-spacing: -0.04em; }
.pitch { position: relative; aspect-ratio: 1.1 / 1; overflow: hidden; border: 2px solid color-mix(in srgb, var(--color-pitch-line) 62%, transparent); border-radius: var(--radius-md); background: repeating-linear-gradient(90deg, var(--color-pitch-grass) 0, var(--color-pitch-grass) 12%, var(--color-pitch-stripe) 12%, var(--color-pitch-stripe) 24%); box-shadow: inset 0 0 55px color-mix(in srgb, var(--color-shadow) 20%, transparent); }
.pitch::before, .pitch::after { position: absolute; border: 2px solid color-mix(in srgb, var(--color-pitch-line) 55%, transparent); content: ''; }
.pitch::before { inset: 0 0 50%; border-width: 0 0 2px; }
.pitch::after { top: 50%; left: 50%; width: 16%; aspect-ratio: 1; border-radius: 50%; transform: translate(-50%, -50%); }
.pitch-half-line, .pitch-center-circle, .pitch-center-dot, .pitch-box { position: absolute; pointer-events: none; }
.pitch-half-line { top: 50%; left: 0; right: 0; border-top: 2px solid color-mix(in srgb, var(--color-pitch-line) 55%, transparent); }
.pitch-center-circle { top: 50%; left: 50%; width: 16%; aspect-ratio: 1; border: 2px solid color-mix(in srgb, var(--color-pitch-line) 55%, transparent); border-radius: 50%; transform: translate(-50%, -50%); }
.pitch-center-dot { top: 50%; left: 50%; width: 5px; height: 5px; border-radius: 50%; background: color-mix(in srgb, var(--color-pitch-line) 85%, transparent); transform: translate(-50%, -50%); }
.pitch-box { left: 27%; width: 46%; height: 17%; border: 2px solid color-mix(in srgb, var(--color-pitch-line) 55%, transparent); }
.pitch-box-top { top: 0; border-top: 0; }
.pitch-box-bottom { bottom: 0; border-bottom: 0; }
.pitch-player { position: absolute; z-index: 2; display: grid; grid-template-columns: minmax(0, 1fr); width: min(16cqw, 96px); justify-items: center; gap: 1px; transform: translate(-50%, -50%); filter: drop-shadow(0 5px 7px color-mix(in srgb, var(--color-shadow) 35%, transparent)); }
.pitch-player img, .player-avatar { width: clamp(28px, 5.5cqw, 56px); height: clamp(28px, 5.5cqw, 56px); display: grid; place-items: center; border: 2px solid var(--color-accent); border-radius: 50%; background: var(--color-accent-ink); color: var(--color-accent); object-fit: cover; font-size: clamp(0.62rem, 2cqw, 1.1rem); font-weight: 900; line-height: 1; text-align: center; }
.player-number { margin-top: 0; padding: var(--space-1) var(--space-1); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-ink); font-size: 0.62rem; font-weight: 900; line-height: 1; }
.pitch-player .player-name { min-width: 0; max-width: 100%; overflow: hidden; color: var(--color-ink); font-size: 0.6rem; font-weight: 800; line-height: 1.1; text-overflow: ellipsis; white-space: nowrap; }
.player-position { max-width: 100%; color: var(--color-accent); font-size: 0.52rem; font-weight: 800; line-height: 1.1; text-align: center; text-transform: uppercase; white-space: nowrap; }
.team-pitch-substitutes { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); padding: var(--space-2); border: 1px solid color-mix(in srgb, var(--color-muted) 14%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-canvas) 28%, transparent); }
.team-pitch-substitutes small { flex-basis: 100%; color: var(--color-muted); font-size: 0.58rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
.bench-player { padding: var(--space-1) var(--space-1); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--color-accent) 8%, transparent); color: var(--color-ink); font-size: 0.63rem; }
.bench-empty { color: var(--color-muted); font-size: 0.63rem; }
@media (max-width: 480px) { .pitch { aspect-ratio: 0.6 / 1; } .pitch-player .player-name { font-size: 0.54rem; } .player-position { font-size: 0.48rem; } }
:root[data-theme="light"] .pitch { --color-ink: var(--color-island-ink); --color-accent: var(--color-island-accent); --color-warning: var(--color-island-warning); --color-canvas: var(--color-pitch-player); --color-surface: var(--color-pitch-player); --color-accent-ink: var(--color-pitch-player); }
@media (prefers-color-scheme: light) {
  :root[data-theme="system"] .pitch { --color-ink: var(--color-island-ink); --color-accent: var(--color-island-accent); --color-warning: var(--color-island-warning); --color-canvas: var(--color-pitch-player); --color-surface: var(--color-pitch-player); --color-accent-ink: var(--color-pitch-player); }
}
</style>